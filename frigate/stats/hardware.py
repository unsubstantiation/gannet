"""Native Windows hardware usage collection.

CPU counters come from psutil. NVIDIA counters come from NVML. Intel and AMD
GPU counters come from Windows WMI performance counters
(``Win32_PerfFormattedData_GpuPerformanceCounters_*``), which are available on
Windows 8 and later for all display-adapter vendors.
"""

import logging
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from frigate.config import FrigateConfig
from frigate.config.camera.updater import (
    CameraConfigUpdateEnum,
    CameraConfigUpdateSubscriber,
)
from frigate.detectors.hardware import hardware_prober
from frigate.util.platform import get_display_adapter_vendors
from frigate.util.services import get_cpu_stats, get_nvidia_gpu_stats

logger = logging.getLogger(__name__)

HARDWARE_ERROR_COOLDOWN_SECONDS = 3600
POLL_TIMEOUT_SECONDS = 10

WMI_NAMESPACE = r"winmgmts:\\.\root\cimv2"
GPU_ENGINE_WMI_CLASS = "Win32_PerfFormattedData_GpuPerformanceCounters_GpuEngine"
GPU_MEMORY_WMI_CLASS = "Win32_PerfFormattedData_GpuPerformanceCounters_GpuMemory"


@dataclass
class HardwarePollResult:
    gpu: dict[str, dict[str, Any]] = field(default_factory=dict)
    npu: dict[str, dict[str, Any]] = field(default_factory=dict)
    ok: bool = True


def _wmi_service():
    """Connect to the local WMI service, or return None when unavailable."""
    try:
        import win32com.client

        return win32com.client.GetObject(WMI_NAMESPACE)
    except Exception:
        logger.debug("WMI service is not available for hardware stats")
        return None


def _gpu_vendor_indices(wmi) -> dict[str, list[int]]:
    """Map WMI GPU instance indexes to vendors using ``Win32_VideoController``."""
    vendors: dict[str, list[int]] = {}
    try:
        controllers = wmi.ExecQuery(
            "SELECT Name, VideoProcessor FROM Win32_VideoController"
        )
    except Exception:
        return vendors

    for index, controller in enumerate(controllers):
        name = controller.Name or ""
        processor = controller.VideoProcessor or ""
        combined = f"{name} {processor}".lower()
        if "nvidia" in combined:
            vendors.setdefault("nvidia", []).append(index)
        elif "amd" in combined or "radeon" in combined or "advanced micro" in combined:
            vendors.setdefault("amd", []).append(index)
        elif "intel" in combined:
            vendors.setdefault("intel", []).append(index)
    return vendors


def _query_wmi_gpu_engines(wmi, vendor_indices: dict[str, list[int]]) -> dict[int, dict[str, float]]:
    """Query per-GPU engine utilization percentages from WMI."""
    engines: dict[int, dict[str, float]] = {}
    try:
        for entry in wmi.ExecQuery(
            f"SELECT Name, UtilizationPercentage FROM {GPU_ENGINE_WMI_CLASS}"
        ):
            parts = (entry.Name or "").split(":", 1)
            if len(parts) != 2:
                continue
            try:
                gpu_idx = int(parts[0].replace("GPU", "").strip())
            except ValueError:
                continue
            engine_type = parts[1].strip()
            for _vendor, indices in vendor_indices.items():
                if gpu_idx in indices:
                    engines.setdefault(gpu_idx, {})[engine_type] = float(
                        entry.UtilizationPercentage
                    )
                    break
    except Exception:
        logger.debug("WMI GPU engine counters are not available")
    return engines


def _query_wmi_gpu_memory(wmi, vendor_indices: dict[str, list[int]]) -> dict[int, float]:
    """Query per-GPU dedicated memory usage percentages from WMI."""
    memories: dict[int, float] = {}
    try:
        for entry in wmi.ExecQuery(
            f"SELECT Name, DedicatedUsagePercentage FROM {GPU_MEMORY_WMI_CLASS}"
        ):
            parts = (entry.Name or "").split(":", 1)
            if len(parts) != 2:
                continue
            try:
                gpu_idx = int(parts[0].replace("GPU", "").strip())
            except ValueError:
                continue
            for _vendor, indices in vendor_indices.items():
                if gpu_idx in indices:
                    memories[gpu_idx] = float(entry.DedicatedUsagePercentage)
                    break
    except Exception:
        logger.debug("WMI GPU memory counters are not available")
    return memories


def _video_controller_names(wmi) -> dict[int, str]:
    """Return GPU index -> friendly name from ``Win32_VideoController``."""
    names: dict[int, str] = {}
    try:
        for index, controller in enumerate(wmi.ExecQuery("SELECT Name FROM Win32_VideoController")):
            names[index] = controller.Name or f"GPU {index}"
    except Exception:
        pass
    return names


def _poll_wmi_gpu_stats(config: FrigateConfig, vendor: str) -> HardwarePollResult:
    """Poll GPU stats from WMI for Intel or AMD adapters."""
    wmi = _wmi_service()
    if wmi is None:
        return HardwarePollResult(ok=False)

    vendor_indices = _gpu_vendor_indices(wmi)
    indices = vendor_indices.get(vendor, [])
    if not indices:
        # No matching adapter; not an error, just nothing to poll.
        return HardwarePollResult()

    gpu_names = _video_controller_names(wmi)
    engines = _query_wmi_gpu_engines(wmi, vendor_indices)
    memories = _query_wmi_gpu_memory(wmi, vendor_indices)

    gpu: dict[str, dict[str, Any]] = {}
    for gpu_idx in indices:
        name = gpu_names.get(gpu_idx, f"{vendor} GPU {gpu_idx}")
        eng = engines.get(gpu_idx, {})
        mem = memories.get(gpu_idx, 0.0)

        compute = eng.get("3D", 0.0)
        dec = eng.get("Video Decode", 0.0)
        enc = eng.get("Video Encode", 0.0)

        overall = min(100.0, compute + dec)

        entry: dict[str, Any] = {
            "vendor": vendor,
            "gpu": f"{round(overall, 2)}%",
            "mem": f"{round(mem, 2)}%",
        }
        if vendor == "intel":
            entry["compute"] = f"{round(compute, 2)}%"
            entry["dec"] = f"{round(dec, 2)}%"
        gpu[name] = entry

    return HardwarePollResult(gpu=gpu)


def _poll_intel_gpu(config: FrigateConfig) -> HardwarePollResult:
    return _poll_wmi_gpu_stats(config, "intel")


def _poll_amd_gpu(config: FrigateConfig) -> HardwarePollResult:
    return _poll_wmi_gpu_stats(config, "amd")


def _present_hardware() -> set[str]:
    return {hardware.key for hardware in hardware_prober.probe()}


def _present_gpu() -> set[str]:
    """Return the pollable GPU vendors available to this process."""
    vendors = set()
    hardware_keys = _present_hardware()
    if "onnx:nvidia" in hardware_keys:
        vendors.add("nvidia")
    # Intel GPU via OpenVINO GPU device
    if any(k.startswith("openvino:GPU") for k in hardware_keys):
        vendors.add("intel")
    # AMD GPU via DirectML or Windows ML MIGraphX (AMD vendor provider)
    if any(k.startswith("onnx:directml") for k in hardware_keys) or any(
        k.startswith("onnx:windowsml:MIGraphX") for k in hardware_keys
    ):
        vendors.add("amd")
    # Also use display adapter classification as a broader hint
    vendors |= get_display_adapter_vendors()
    return vendors


def _poll_nvidia(config: FrigateConfig) -> HardwarePollResult:
    usage = get_nvidia_gpu_stats()
    if not usage:
        return HardwarePollResult(
            gpu={"nvidia-gpu": {"vendor": "nvidia", "gpu": "", "mem": ""}},
            ok=False,
        )

    gpu: dict[str, dict[str, Any]] = {}
    for entry in usage.values():
        gpu[entry["name"]] = {
            "vendor": "nvidia",
            "gpu": f"{round(float(entry['gpu']), 2)}%",
            "mem": f"{round(float(entry['mem']), 2)}%",
            "enc": f"{round(float(entry['enc']), 2)}%",
            "dec": f"{round(float(entry['dec']), 2)}%",
            "temp": str(entry["temp"]),
        }
    return HardwarePollResult(gpu=gpu)


POLLERS: dict[str, Callable[[FrigateConfig], HardwarePollResult]] = {
    "nvidia": _poll_nvidia,
    "intel": _poll_intel_gpu,
    "amd": _poll_amd_gpu,
}


def _hwaccel_hardware(args: str) -> str | None:
    lowered = args.lower()
    if "windows-nvenc" in lowered or "-hwaccel cuda" in lowered:
        return "nvidia"
    if "windows-qsv" in lowered:
        return "intel"
    if "windows-d3d11va" in lowered or "windows-dxva2" in lowered:
        # D3D11VA/DXVA2 can be Intel, AMD, or NVIDIA; report all detected vendors.
        return None  # handled by display-adapter classification in _present_gpu
    return None


class HardwareStats:
    """Catalog and poll usage counters available through Windows APIs."""

    def __init__(self, config: FrigateConfig) -> None:
        self.config = config
        self._monitored: dict[str, Callable[[], HardwarePollResult]] = {}
        self._errors: dict[str, float] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="hw_stats"
        )
        self._config_subscriber = CameraConfigUpdateSubscriber(
            config,
            config.cameras,
            [
                CameraConfigUpdateEnum.add,
                CameraConfigUpdateEnum.remove,
                CameraConfigUpdateEnum.ffmpeg,
                CameraConfigUpdateEnum.audio_transcription,
                CameraConfigUpdateEnum.semantic_search,
                CameraConfigUpdateEnum.face_recognition,
                CameraConfigUpdateEnum.lpr,
            ],
        )
        self.update_config()

    def set_config(self, config: FrigateConfig) -> None:
        self.config = config
        self._config_subscriber.config = config
        self._config_subscriber.camera_configs = config.cameras
        self.update_config()

    def update_config(self) -> None:
        names = self._scan_ffmpeg() | self._scan_detectors() | self._scan_enrichments()
        stats_cfg = self.config.telemetry.stats
        if not stats_cfg.nvidia_gpu_stats:
            names.discard("nvidia")
        if not stats_cfg.intel_gpu_stats:
            names.discard("intel")
        if not stats_cfg.amd_gpu_stats:
            names.discard("amd")
        self._monitored = {
            name: partial(POLLERS[name], self.config)
            for name in sorted(names)
            if name in POLLERS
        }
        logger.debug("Monitoring Windows hardware stats: %s", list(self._monitored))

    def update_stats(self, all_stats: dict[str, Any]) -> None:
        if self._config_subscriber.check_for_updates():
            self.update_config()

        now = time.monotonic()
        hardware_futures: dict[Future[HardwarePollResult], str] = {}
        for name, poll in self._monitored.items():
            last_error = self._errors.get(name)
            if (
                last_error is not None
                and now - last_error < HARDWARE_ERROR_COOLDOWN_SECONDS
            ):
                continue
            self._errors.pop(name, None)
            hardware_futures[self._executor.submit(poll)] = name

        cpu_future = self._executor.submit(get_cpu_stats)
        done, _ = wait([*hardware_futures, cpu_future], timeout=POLL_TIMEOUT_SECONDS)
        gpu_usages: dict[str, dict[str, Any]] = {}

        for future, name in hardware_futures.items():
            if future not in done:
                logger.warning("Timed out collecting %s stats", name)
                self._errors[name] = time.monotonic()
                continue
            try:
                result = future.result()
            except Exception:
                logger.exception("Failed to collect %s stats", name)
                self._errors[name] = time.monotonic()
                continue
            gpu_usages.update(result.gpu)
            if not result.ok:
                self._errors[name] = time.monotonic()

        if gpu_usages:
            all_stats["gpu_usages"] = gpu_usages

        if cpu_future in done:
            try:
                cpu_stats = cpu_future.result()
            except Exception:
                logger.exception("Failed to collect CPU stats")
            else:
                if cpu_stats:
                    all_stats["cpu_usages"] = cpu_stats

    def stop(self) -> None:
        self._config_subscriber.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _scan_ffmpeg(self) -> set[str]:
        names: set[str] = set()
        for camera in self.config.cameras.values():
            values = [camera.ffmpeg.hwaccel_args]
            values.extend(stream.hwaccel_args for stream in camera.ffmpeg.inputs)
            for value in values:
                args = " ".join(value) if isinstance(value, list) else value
                if args and (name := _hwaccel_hardware(args)):
                    names.add(name)
        return names

    def _scan_detectors(self) -> set[str]:
        names: set[str] = set()
        hardware_keys = _present_hardware()
        for model in self.config.models:
            for spec in self.config.devices_for_model(model):
                if spec.detector == "onnx":
                    if spec.device.startswith("cuda") and "onnx:nvidia" in hardware_keys:
                        names.add("nvidia")
                    elif spec.device.startswith("directml"):
                        # DirectML can target any vendor; rely on display-adapter classification
                        names |= get_display_adapter_vendors()
                    elif spec.device.startswith("openvino:GPU"):
                        names.add("intel")
                elif spec.detector == "openvino":
                    if spec.device.startswith("GPU"):
                        names.add("intel")
        return names

    def _scan_enrichments(self) -> set[str]:
        names: set[str] = set()
        config = self.config
        if config.semantic_search.enabled:
            device = config.semantic_search.device
            if device.startswith("cuda") and "onnx:nvidia" in _present_hardware():
                names.add("nvidia")
            elif device.startswith("openvino:GPU"):
                names.add("intel")
        if config.face_recognition.enabled:
            device = config.face_recognition.device
            if device.startswith("cuda") and "onnx:nvidia" in _present_hardware():
                names.add("nvidia")
            elif device.startswith("openvino:GPU"):
                names.add("intel")
        if config.lpr.enabled:
            device = config.lpr.device
            if device.startswith("cuda") and "onnx:nvidia" in _present_hardware():
                names.add("nvidia")
            elif device.startswith("openvino:GPU"):
                names.add("intel")

        transcription = config.audio_transcription
        if transcription.device == "GPU" and (
            transcription.enabled
            or any(c.audio_transcription.enabled for c in config.cameras.values())
        ):
            names.add("nvidia")
        return names