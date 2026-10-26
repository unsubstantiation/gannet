"""Native Windows hardware usage collection.

CPU counters come from psutil. NVIDIA counters come from NVML. Intel and AMD
GPU counters come from Windows WMI performance counters
(``Win32_PerfFormattedData_GpuPerformanceCounters_*``), which are available on
Windows 8 and later for all display-adapter vendors.
"""

import logging
import math
import re
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from gannet.config import FrigateConfig
from gannet.config.camera.updater import (
    CameraConfigUpdateEnum,
    CameraConfigUpdateSubscriber,
)
from gannet.detectors.hardware import hardware_prober
from gannet.util.platform import get_display_adapter_vendors
from gannet.util.services import get_cpu_stats, get_nvidia_gpu_stats

logger = logging.getLogger(__name__)

HARDWARE_ERROR_COOLDOWN_SECONDS = 3600
POLL_TIMEOUT_SECONDS = 10

WMI_NAMESPACE = r"winmgmts:\\.\root\cimv2"
GPU_ENGINE_WMI_CLASS = "Win32_PerfFormattedData_GpuPerformanceCounters_GpuEngine"
GPU_MEMORY_WMI_CLASS = "Win32_PerfFormattedData_GpuPerformanceCounters_GpuAdapterMemory"
DIRECTX_REGISTRY_PATH = r"SOFTWARE\Microsoft\DirectX"
PCI_GPU_VENDORS = {
    0x1002: "amd",
    0x1022: "amd",
    0x10DE: "nvidia",
    0x8086: "intel",
}
GPU_ENGINE_INSTANCE_RE = re.compile(
    r"^pid_\d+_luid_(?P<high>0x[0-9a-f]+)_(?P<low>0x[0-9a-f]+)_"
    r"phys_(?P<phys>\d+)_eng_(?P<eng>\d+)_engtype_(?P<engine_type>.*)$",
    re.IGNORECASE,
)
GPU_MEMORY_INSTANCE_RE = re.compile(
    r"^luid_(?P<high>0x[0-9a-f]+)_(?P<low>0x[0-9a-f]+)_phys_\d+$",
    re.IGNORECASE,
)


@dataclass
class HardwarePollResult:
    gpu: dict[str, dict[str, Any]] = field(default_factory=dict)
    npu: dict[str, dict[str, Any]] = field(default_factory=dict)
    ok: bool = True


@dataclass(frozen=True)
class WindowsGpuAdapter:
    """DirectX adapter identity shared with Windows GPU counter names."""

    luid: int
    name: str
    vendor: str
    dedicated_memory: int


def _wmi_service():
    """Connect to the local WMI service, or return None when unavailable."""
    try:
        import win32com.client

        return win32com.client.GetObject(WMI_NAMESPACE)
    except Exception:
        logger.debug("WMI service is not available for hardware stats", exc_info=True)
        return None


def _windows_gpu_adapters() -> dict[int, WindowsGpuAdapter]:
    """Return DirectX adapters keyed by the LUID used by GPU counters.

    Win32_VideoController enumeration indexes do not identify GPU performance
    counter instances. The DirectX registry records contain the same adapter
    LUID as the counter names, along with a stable name, PCI vendor, and memory
    capacity. Reading them also avoids inventing a mapping between unrelated
    adapter enumeration orders.
    """
    adapters: dict[int, WindowsGpuAdapter] = {}
    try:
        import winreg
    except ImportError:
        return adapters

    value_names = (
        "AdapterLuid",
        "Description",
        "VendorId",
        "DedicatedVideoMemory",
        "DedicatedSystemMemory",
    )

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, DIRECTX_REGISTRY_PATH) as root:
            for index in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                        values: dict[str, Any] = {}
                        for value_name in value_names:
                            try:
                                values[value_name] = winreg.QueryValueEx(
                                    key, value_name
                                )[0]
                            except FileNotFoundError:
                                pass

                    luid = int(values.get("AdapterLuid", 0) or 0) & 0xFFFFFFFFFFFFFFFF
                    vendor = PCI_GPU_VENDORS.get(int(values.get("VendorId", 0) or 0))
                    if not luid or vendor is None:
                        continue

                    name = str(
                        values.get("Description") or f"{vendor.upper()} GPU {luid:x}"
                    ).strip()
                    dedicated_memory = sum(
                        max(0, int(values.get(value_name, 0) or 0))
                        for value_name in (
                            "DedicatedVideoMemory",
                            "DedicatedSystemMemory",
                        )
                    )
                    adapters[luid] = WindowsGpuAdapter(
                        luid=luid,
                        name=name,
                        vendor=vendor,
                        dedicated_memory=dedicated_memory,
                    )
                except (OSError, TypeError, ValueError):
                    # Individual records can be incomplete or disappear during
                    # driver installation; other adapters remain usable.
                    continue
    except OSError:
        logger.debug("Unable to enumerate DirectX GPU adapters", exc_info=True)

    return adapters


def _luid_from_match(match: re.Match[str]) -> int:
    return (int(match.group("high"), 16) << 32) | int(match.group("low"), 16)


def _query_wmi_gpu_engines(
    wmi, adapters: Mapping[int, WindowsGpuAdapter]
) -> dict[int, dict[str, float]] | None:
    """Return per-adapter engine loads keyed by adapter LUID.

    Each WMI row is one process on one physical engine. Sum all processes on
    that engine, then retain the busiest engine of each type. This avoids both
    overwriting concurrent clients and adding independent engines together.
    """
    totals: dict[tuple[int, int, int], float] = {}
    engine_types: dict[tuple[int, int, int], str] = {}

    try:
        for entry in wmi.ExecQuery(
            f"SELECT Name, UtilizationPercentage FROM {GPU_ENGINE_WMI_CLASS}"
        ):
            match = GPU_ENGINE_INSTANCE_RE.fullmatch(str(entry.Name or ""))
            if match is None:
                continue

            luid = _luid_from_match(match)
            if luid not in adapters:
                continue

            try:
                utilization = float(entry.UtilizationPercentage)
                engine_key = (
                    luid,
                    int(match.group("phys")),
                    int(match.group("eng")),
                )
            except (TypeError, ValueError):
                continue
            if not math.isfinite(utilization) or utilization < 0:
                continue

            totals[engine_key] = totals.get(engine_key, 0.0) + utilization
            engine_type = match.group("engine_type").strip().lower()
            if engine_type or engine_key not in engine_types:
                engine_types[engine_key] = engine_type
    except Exception:
        logger.debug("WMI GPU engine counters are not available", exc_info=True)
        return None

    engines: dict[int, dict[str, float]] = {}
    for engine_key, utilization in totals.items():
        luid = engine_key[0]
        engine_type = engine_types[engine_key] or "unknown"
        adapter_engines = engines.setdefault(luid, {})
        adapter_engines[engine_type] = min(
            100.0, max(adapter_engines.get(engine_type, 0.0), utilization)
        )

    return engines


def _query_wmi_gpu_memory(
    wmi, adapters: Mapping[int, WindowsGpuAdapter]
) -> dict[int, float] | None:
    """Return adapter-wide dedicated memory usage in bytes, keyed by LUID."""
    memory_usage: dict[int, float] = {}
    try:
        for entry in wmi.ExecQuery(
            f"SELECT Name, DedicatedUsage FROM {GPU_MEMORY_WMI_CLASS}"
        ):
            match = GPU_MEMORY_INSTANCE_RE.fullmatch(str(entry.Name or ""))
            if match is None:
                continue

            luid = _luid_from_match(match)
            if luid not in adapters:
                continue

            try:
                usage = float(entry.DedicatedUsage)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(usage) or usage < 0:
                continue

            memory_usage[luid] = memory_usage.get(luid, 0.0) + usage
    except Exception:
        logger.debug("WMI GPU memory counters are not available", exc_info=True)
        return None

    return memory_usage


def _poll_wmi_gpu_stats(config: FrigateConfig, vendor: str) -> HardwarePollResult:
    """Poll GPU stats from WMI for Intel or AMD adapters."""
    wmi = _wmi_service()
    if wmi is None:
        return HardwarePollResult(ok=False)

    adapters = {
        luid: adapter
        for luid, adapter in _windows_gpu_adapters().items()
        if adapter.vendor == vendor
    }
    if not adapters:
        # No matching adapter; not an error, just nothing to poll.
        return HardwarePollResult()

    engines = _query_wmi_gpu_engines(wmi, adapters)
    memory_usage = _query_wmi_gpu_memory(wmi, adapters)
    active_luids = sorted(
        (
            luid
            for luid in adapters
            if (engines is not None and luid in engines)
            or (memory_usage is not None and luid in memory_usage)
        ),
        key=lambda luid: (adapters[luid].name.lower(), luid),
    )
    if not active_luids:
        return HardwarePollResult(ok=False)

    name_counts: dict[str, int] = {}
    for luid in active_luids:
        name = adapters[luid].name
        name_counts[name] = name_counts.get(name, 0) + 1

    gpu: dict[str, dict[str, Any]] = {}
    for luid in active_luids:
        adapter = adapters[luid]
        eng = None if engines is None else engines.get(luid, {})
        entry: dict[str, Any] = {"vendor": vendor, "gpu": "", "mem": ""}

        if eng is not None:
            # Task Manager's overall value is the busiest physical engine
            # after summing its processes; independent engines are not added.
            overall = max(eng.values(), default=0.0)
            compute = min(100.0, eng.get("3d", 0.0) + eng.get("compute", 0.0))
            dec = min(
                100.0,
                eng.get("videodecode", 0.0) + eng.get("videoprocessing", 0.0),
            )
            enc = eng.get("videoencode", 0.0)
            entry.update(
                {
                    "gpu": f"{round(overall, 2)}%",
                    "compute": f"{round(compute, 2)}%",
                    "dec": f"{round(dec, 2)}%",
                    "enc": f"{round(enc, 2)}%",
                }
            )

        if memory_usage is not None:
            usage = memory_usage.get(luid)
            if usage is None or adapter.dedicated_memory <= 0:
                entry["mem"] = "-%"
            else:
                memory_percent = min(100.0, usage * 100.0 / adapter.dedicated_memory)
                entry["mem"] = f"{round(memory_percent, 2)}%"

        name = adapter.name
        if name_counts[name] > 1:
            name = f"{name} ({luid & 0xFFFFFFFF:08x})"
        gpu[name] = entry

    return HardwarePollResult(
        gpu=gpu, ok=engines is not None and memory_usage is not None
    )


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
    # MIGraphX is AMD-specific. DirectML is vendor-neutral, so its presence
    # alone must not create an AMD poller on Intel or NVIDIA machines.
    if any(k.startswith("onnx:windowsml:MIGraphX") for k in hardware_keys):
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
    if "nvenc" in lowered or "-hwaccel cuda" in lowered:
        return "nvidia"
    if "qsv" in lowered:
        return "intel"
    if "amf" in lowered:
        return "amd"
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
                if not args:
                    continue
                if name := _hwaccel_hardware(args):
                    names.add(name)
                elif any(
                    family in args.lower() for family in ("d3d11va", "dxva2", "vulkan")
                ):
                    # These APIs are vendor-neutral. Attribute their counters
                    # through the adapters actually present on this machine.
                    names |= _present_gpu()

        return names

    def _scan_detectors(self) -> set[str]:
        names: set[str] = set()
        hardware_keys = _present_hardware()
        for model in self.config.models:
            for spec in self.config.devices_for_model(model):
                if spec.detector == "onnx":
                    if (
                        spec.device.startswith("cuda")
                        and "onnx:nvidia" in hardware_keys
                    ):
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
