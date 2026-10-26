# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Windows ML execution-provider discovery and per-process registration.

The Windows ML catalog manages vendor EP installation. ONNX Runtime's Python
API must register the installed EP library itself (the catalog's native
registration API targets a different ORT environment), so this module keeps
catalog acquisition and Python-runtime registration separate.
"""

import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Provider names shipped by the Windows ML catalog. Keep the list explicit for
# configuration and diagnostics while still allowing newer catalog EPs to be
# registered when they use the same public plugin API.
WINDOWS_ML_PROVIDER_NAMES = {
    "MIGraphXExecutionProvider": "AMD MIGraphX",
    "NvTensorRtRtxExecutionProvider": "NVIDIA TensorRT-RTX",
    "OpenVINOExecutionProvider": "OpenVINO (Windows ML)",
    "QNNExecutionProvider": "Qualcomm QNN",
    "VitisAIExecutionProvider": "AMD Vitis AI",
    "WebGpuExecutionProvider": "WebGPU (experimental)",
}

EXPERIMENTAL_WEBGPU_ENV = "FRIGATE_ENABLE_EXPERIMENTAL_WEBGPU"
_registration_lock = threading.Lock()
_registered: dict[int, set[str]] = {}


def experimental_webgpu_enabled() -> bool:
    """Whether experimental WebGPU provider support was explicitly enabled."""
    return os.environ.get(EXPERIMENTAL_WEBGPU_ENV, "").casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _catalog_providers() -> list[Any]:
    """Return a snapshot of compatible Windows ML EP metadata, if available."""
    try:
        from windowsml import EpCatalog
    except (ImportError, OSError):
        logger.debug("Windows ML EP catalog is not installed or available")
        return []

    try:
        with EpCatalog() as catalog:
            return [
                (
                    provider.name,
                    provider.version,
                    provider.ready_state,
                    provider.library_path,
                )
                for provider in catalog.find_all_providers()
            ]
    except Exception:
        logger.debug("Unable to query the Windows ML EP catalog", exc_info=True)
        return []


def register_ready_providers(ort_module: Any) -> set[str]:
    """Register already-ready vendor EP libraries with this Python ORT runtime.

    This function never downloads a provider implicitly. Use the management
    command to acquire EPs explicitly, then Frigate registers them when it
    creates model sessions.
    """
    runtime_id = id(ort_module)
    with _registration_lock:
        registered = _registered.setdefault(runtime_id, set())
        for name, version, state, library_path in _catalog_providers():
            if name == "WebGpuExecutionProvider" and not experimental_webgpu_enabled():
                logger.info(
                    "Skipping experimental WebGPU provider; set %s=1 to enable it",
                    EXPERIMENTAL_WEBGPU_ENV,
                )
                continue
            state_name = getattr(state, "name", str(state)).casefold()
            if state_name != "ready":
                continue
            if name in registered:
                continue
            if not library_path or not Path(library_path).is_file():
                logger.warning(
                    "Windows ML provider %s %s has no usable library at %r",
                    name,
                    version,
                    library_path,
                )
                continue

            try:
                ort_module.register_execution_provider_library(name, library_path)
            except Exception as err:
                if "already registered" not in str(err).casefold():
                    logger.warning(
                        "Could not register Windows ML provider %s: %s", name, err
                    )
                    continue
            registered.add(name)
            logger.info("Registered Windows ML provider %s %s", name, version)

        return set(registered)


def registered_provider_devices(ort_module: Any) -> dict[str, list[Any]]:
    """Return registered Windows ML EP devices exposed by ONNX Runtime."""
    registered = register_ready_providers(ort_module)
    if not registered:
        return {}

    try:
        devices = ort_module.get_ep_devices()
    except Exception:
        logger.debug(
            "ONNX Runtime could not enumerate plugin EP devices", exc_info=True
        )
        return {}

    found: dict[str, list[Any]] = {}
    for device in devices:
        name = getattr(device, "ep_name", None)
        if name in registered:
            found.setdefault(name, []).append(device)

    return found


def provider_label(name: str) -> str:
    """Return a friendly label for a Windows ML provider."""
    return WINDOWS_ML_PROVIDER_NAMES.get(name, name.removesuffix("ExecutionProvider"))


def provider_from_device(device: str | None) -> str | None:
    """Parse the explicit ``windowsml:<ExecutionProvider>`` device selector."""
    if not device:
        return None
    prefix, separator, value = device.partition(":")
    if separator and prefix.casefold() in {"windowsml", "winml"} and value:
        return value
    return None


def ensure_provider_ready(name: str) -> tuple[str, str]:
    """Acquire one Windows ML provider using the OS catalog.

    Returns its provider name and readiness state. Intended for the explicit
    management command; never called from Frigate startup or an inference path.
    """
    try:
        from windowsml import EpCatalog
    except (ImportError, OSError) as err:
        raise RuntimeError(
            "Windows ML provider management requires the Windows ML runtime "
            "and the 'windowsml' Python package on Windows 11 24H2 or later."
        ) from err

    with EpCatalog() as catalog:
        providers = catalog.find_all_providers()
        selected = next(
            (
                provider
                for provider in providers
                if provider.name.casefold() == name.casefold()
            ),
            None,
        )
        if selected is None:
            choices = ", ".join(provider.name for provider in providers) or "none"
            raise RuntimeError(
                f"Windows ML provider {name!r} is not compatible with this PC. "
                f"Compatible providers: {choices}."
            )

        try:
            selected.ensure_ready()
        except Exception as err:
            raise RuntimeError(
                f"Windows ML could not install provider {selected.name}: {err}"
            ) from err

        state = getattr(selected.ready_state, "name", str(selected.ready_state))
        return selected.name, state
