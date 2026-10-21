# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Check this fork's feature surface against a blakeblackshear/frigate checkout.

Gannet tracks upstream Frigate feature for feature. The only differences
allowed are Windows implementations of the same feature and the deliberate
exclusions recorded below, each with the reason it cannot ship in a native
Windows application. This tool makes that claim checkable instead of
rhetorical: it compares the two trees and fails when upstream carries a
surface the fork does not have and no exclusion covers.

Five surfaces are compared against an upstream checkout:

1. **Modules** - every upstream ``frigate/**/*.py`` outside the test tree
   must exist here (excluded detector plugins and Unix utilities aside).
2. **Definitions** - every upstream function and class (including methods)
   must exist here. Top-level names may live in a different module, so a
   helper that moved during the port counts as present; methods must keep
   their class.
3. **API routes** - every upstream HTTP route must be served here. Routes
   may be added (``/gpuinfo`` replaces ``/vainfo``).
4. **Config schema** - every upstream config class and field must exist,
   so an upstream config file keeps parsing.
5. **Web surface** - every upstream ``web/src`` file and English locale key
   must exist, so no UI feature is missing a page, a component, or a string.

Every exclusion is a pattern plus a written reason. An exclusion that no
longer suppresses anything is reported as stale, so the list shrinks as the
port grows instead of rotting into an excuse list. New gaps are listed with
the surface they belong to; adding an exclusion is a deliberate act that
should name what the fork does instead.

Run from the repository root, with any upstream checkout (depth-1 clone is
enough)::

    git clone --depth 1 --branch dev https://github.com/blakeblackshear/frigate /tmp/frigate
    python testing-scripts/check_upstream_parity.py --upstream-dir /tmp/frigate

Exits non-zero when a gap is not covered by an exclusion.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FORK_FRIGATE = REPO_ROOT / "frigate"
FORK_WEB_SRC = REPO_ROOT / "web" / "src"
FORK_LOCALE_EN = REPO_ROOT / "web" / "public" / "locales" / "en"

SKIP_DIRS = {"test", "__pycache__", "node_modules"}


@dataclass(frozen=True)
class Exclusion:
    """A documented, reasoned exception to parity."""

    pattern: str
    reason: str

    def matches(self, name: str) -> bool:
        return fnmatchcase(name, self.pattern)


# ---------------------------------------------------------------------------
# Deliberate exclusions. Keep each entry short, matched by fnmatch, and tied
# to one reason. The run reports entries that no longer match anything.
# ---------------------------------------------------------------------------

#: Upstream modules the fork does not carry.
EXCLUDED_MODULES: tuple[Exclusion, ...] = (
    Exclusion(
        "frigate/detectors/plugins/axelera.py",
        "Axelera Metis SDK is a Linux runtime; Windows supports cpu, onnx, openvino and zmq detectors",
    ),
    Exclusion(
        "frigate/detectors/plugins/axengine.py",
        "Axelera axengine SDK is a Linux runtime; Windows supports cpu, onnx, openvino and zmq detectors",
    ),
    Exclusion(
        "frigate/detectors/plugins/deepx.py",
        "DeepX NPU SDK is a Linux runtime; Windows supports cpu, onnx, openvino and zmq detectors",
    ),
    Exclusion(
        "frigate/detectors/plugins/edgetpu_tfl.py",
        "Coral libedgetpu targets Unix device nodes; Windows supports cpu, onnx, openvino and zmq detectors",
    ),
    Exclusion(
        "frigate/detectors/plugins/hailo.py",
        "HailoRT is a Linux SDK; Windows supports cpu, onnx, openvino and zmq detectors",
    ),
    Exclusion(
        "frigate/detectors/plugins/memryx.py",
        "MemryX SDK is a Linux runtime; Windows supports cpu, onnx, openvino and zmq detectors",
    ),
    Exclusion(
        "frigate/detectors/plugins/rknn.py",
        "Rockchip RKNN is a Linux NPU runtime; Windows supports cpu, onnx, openvino and zmq detectors",
    ),
    Exclusion(
        "frigate/detectors/plugins/synaptics.py",
        "Synaptics AIPU SDK is a Linux runtime; Windows supports cpu, onnx, openvino and zmq detectors",
    ),
    Exclusion(
        "frigate/detectors/plugins/teflon_tfl.py",
        "Google Edge TPU runtime is a Linux library; Windows supports cpu, onnx, openvino and zmq detectors",
    ),
    Exclusion(
        "frigate/detectors/plugins/tensorrt.py",
        "TF-TRT plugin targets the Linux TensorFlow build; NVIDIA acceleration ships through ONNX Runtime (CUDA) and the Windows ML catalog instead",
    ),
    Exclusion(
        "frigate/util/ownership.py",
        "UID/GID chown has no Windows meaning; files inherit the parent directory ACL",
    ),
    Exclusion(
        "frigate/util/rknn_converter.py",
        "Rockchip NPU model tooling, shipped with the rknn plugin",
    ),
    Exclusion(
        "frigate/util/runtime_deps.py",
        "pip-installs Linux detector SDKs at startup; bootstrap_windows.py installs the supported Windows runtimes",
    ),
)

#: Upstream functions and classes the fork does not carry. Matched against
#: `module:qualname` first, then `Class.method` and bare names for public
#: top-level definitions that moved modules.
EXCLUDED_DEFS: tuple[Exclusion, ...] = (
    # Detector frameworks whose only consumers are the excluded Linux plugins.
    Exclusion(
        "*ensure_detector_dependencies",
        "installs Linux detector SDKs at startup; bootstrap_windows.py owns the Windows runtime install",
    ),
    Exclusion(
        "DetectionApi.*_dependencies",
        "detector runtime installer hooks used by the excluded Linux detector plugins",
    ),
    Exclusion(
        "Async*",
        "async detector API whose only implementers are the axelera and memryx Linux plugins",
    ),
    Exclusion(
        "detectors.detection_runners:RKNNModelRunner*",
        "Rockchip RKNN model runner, shipped with the rknn plugin",
    ),
    Exclusion(
        "detectors.detection_runners:get_migraphx_devices",
        "MIGraphX device probing for the Linux ROCm stack; Windows selects MIGraphX through the Windows ML catalog",
    ),
    Exclusion(
        "detectors.detection_runners:get_lighter_ane_devices",
        "Apple Neural Engine device probing; macOS-only hardware",
    ),
    Exclusion(
        "detectors.detection_runners:is_arm64_platform",
        "ARM Linux runtime probing for the excluded Linux detector plugins",
    ),
    Exclusion(
        "ONNXModelRunner.is_migraphx_complex_model",
        "Linux MIGraphX complexity check; Windows selects providers through the Windows ML catalog",
    ),
    Exclusion(
        "detectors.detector_types:StrEnum",
        "enum.StrEnum is in the Python 3.11+ standard library",
    ),
    Exclusion(
        "detectors.detector_types:_discriminator_value",
        "plugin auto-discovery; the Windows detector registry is an explicit list of the supported backends",
    ),
    Exclusion(
        "detectors.hardware:detect_*",
        "Unix device-node detector discovery (Coral, Jetson, Rockchip, Hailo, and friends); the Windows list comes from the platform APIs",
    ),
    Exclusion(
        "detectors.hardware:_drm_devices",
        "Linux DRM device enumeration for the excluded detector backends",
    ),
    Exclusion(
        "detectors.hardware:_dev_units",
        "Linux device-unit enumeration for the excluded detector backends",
    ),
    Exclusion(
        "detectors.hardware:_read",
        "sysfs helper for the excluded Linux detector discovery paths",
    ),
    Exclusion(
        "*:add_hailo_alias",
        "Frigate+ model aliasing for the excluded Hailo detector",
    ),
    Exclusion(
        "*:rename_hailo_detector",
        "config migration for the excluded Hailo detector name",
    ),
    # Acceleration and hardware statistics that have no Windows runtime.
    Exclusion(
        "LibvaGpuSelector*",
        "libva GPU selection; Windows uses the preset-windows-* ffmpeg families",
    ),
    Exclusion(
        "*:vainfo_hwaccel",
        "libva vainfo diagnostics; /api/gpuinfo reports the Windows display adapters, ffmpeg -hwaccels and go2rtc accelerators instead",
    ),
    Exclusion(
        "util.services:*intel*",
        "Intel DRM fdinfo GPU statistics; only NVIDIA adapters report usage counters on Windows (NVML)",
    ),
    Exclusion(
        "util.services:get_amd_gpu_stats",
        "AMD DRM GPU statistics; only NVIDIA adapters report usage counters on Windows (NVML)",
    ),
    Exclusion(
        "util.services:get_*_npu_stats",
        "vendor NPU utilization counters; no Windows runtime in this tree reports NPU utilization",
    ),
    Exclusion(
        "util.services:get_*_temp*",
        "vendor board thermometers; no Windows runtime in this tree exposes one",
    ),
    Exclusion(
        "util.services:get_jetson_stats",
        "Jetson tegrastats; Linux-only hardware",
    ),
    Exclusion(
        "util.services:get_rockchip_gpu_stats",
        "Rockchip GPU statistics; Linux-only hardware",
    ),
    Exclusion(
        "util.services:is_vaapi_amd_driver",
        "libva AMD driver detection; not applicable to the Windows ffmpeg builds",
    ),
    Exclusion(
        "util.services:enumerate_drm_devices",
        "Linux DRM device enumeration; Windows reports display adapters through EnumDisplayDevices",
    ),
    Exclusion(
        "util.services:get_cgroups_version",
        "cgroups accounting; Windows reports memory through the Win32 APIs",
    ),
    Exclusion(
        "util.services:get_docker_memlimit_bytes",
        "Docker memory limits; there is no container runtime",
    ),
    Exclusion(
        "util.services:get_physical_interfaces",
        "nethogs interface enumeration; the Windows bandwidth collector is an ETW kernel-logger session",
    ),
    Exclusion(
        "stats.hardware:*",
        "Linux sysfs/DRM statistics pollers; Windows polls NVIDIA through NVML and hides the panes no counter feeds",
    ),
    Exclusion(
        "util.hwaccel:*",
        "Linux VAAPI/DRM hwaccel probing; ffmpeg.hwaccel_args: auto probes the preset-windows-* families",
    ),
    # POSIX and container runtime facilities.
    Exclusion(
        "log:reopen_std_streams",
        "os.register_at_fork child hook; the Windows runtime always spawns and never forks",
    ),
    Exclusion(
        "UntrackedSharedMemory.*",
        "POSIX shm open/unlink tracking; Windows mappings are named and close with the last handle",
    ),
    Exclusion(
        "FrigateProcess._*memray*",
        "memray profiling hooks; the profiler has no maintained Windows runtime",
    ),
    Exclusion(
        "util.services:listen",
        "SIGUSR1 stack-dump handler; Windows has no SIGUSR1",
    ),
    Exclusion(
        "util.services:print_stack",
        "SIGUSR1 stack-dump handler body",
    ),
    Exclusion(
        "*:_load_credentials_dir",
        "Docker/systemd credentials directory; the native build reads the process environment, secrets.yaml and environment_vars only (enforced by frigate/test/test_env.py)",
    ),
    Exclusion(
        "*:_warn_ignored_ffmpeg_path",
        "warning for the upstream granular Linux service's ffmpeg path rule",
    ),
    Exclusion(
        "util.config:frigate_service_is_granular_root",
        "upstream Linux service granularity; the Windows service runs as one account",
    ),
    Exclusion(
        "util.config:is_runtime_user_writable",
        "upstream Linux service writable-path check against /dev/shm and /tmp",
    ),
    Exclusion(
        "StatsEmitter._update_shm_notice",
        "/dev/shm sizing notice; Windows frame memory is page-file backed and has no shm quota",
    ),
    Exclusion(
        "api.app:vainfo",
        "replaced by /api/gpuinfo (see WINDOWS_COMPATIBILITY.md)",
    ),
    Exclusion(
        "api.fastapi_app:RemoteUserPlugin",
        "defined upstream but never registered or read; proxy identity uses the header_map on this fork",
    ),
    Exclusion(
        "comms.webpush:_vapid_audience",
        "renamed util.webpush:vapid_audience during the web push hardening port",
    ),
)

#: Upstream API routes the fork serves differently.
EXCLUDED_ROUTES: tuple[Exclusion, ...] = (
    Exclusion(
        "/vainfo",
        "replaced by /api/gpuinfo: display adapters, ffmpeg -hwaccels, go2rtc accelerators",
    ),
)

#: Upstream config fields the fork replaces with Windows equivalents.
EXCLUDED_CONFIG_FIELDS: tuple[Exclusion, ...] = (
    Exclusion(
        "*.amd_gpu_stats",
        "AMD DRM statistics toggle; replaced by the nvidia_gpu_stats NVML toggle",
    ),
    Exclusion(
        "*.intel_gpu_stats",
        "Intel DRM statistics toggle; replaced by the nvidia_gpu_stats NVML toggle",
    ),
    Exclusion(
        "*.intel_gpu_device",
        "Intel DRM device pinning; no Intel utilization counter exists in the Windows runtimes",
    ),
)

#: Upstream English locale keys that belong to the exclusions above.
EXCLUDED_LOCALE_KEYS: tuple[Exclusion, ...] = (
    Exclusion(
        "telemetry.stats.amd_gpu_stats.*",
        "strings for the excluded AMD GPU statistics toggle",
    ),
    Exclusion(
        "telemetry.stats.intel_gpu_stats.*",
        "strings for the excluded Intel GPU statistics toggle",
    ),
    Exclusion(
        "telemetry.stats.intel_gpu_device.*",
        "strings for the excluded Intel GPU device field",
    ),
)

#: Upstream web files the fork serves differently. Empty is the goal state.
EXCLUDED_WEB_FILES: tuple[Exclusion, ...] = ()

ALL_EXCLUSIONS = (
    EXCLUDED_MODULES,
    EXCLUDED_DEFS,
    EXCLUDED_ROUTES,
    EXCLUDED_CONFIG_FIELDS,
    EXCLUDED_LOCALE_KEYS,
    EXCLUDED_WEB_FILES,
)


class Surface:
    """One comparable slice of the two trees."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.gaps: list[str] = []
        self.suppressed: dict[str, int] = {}


def _forms(name: str) -> tuple[str, ...]:
    """Every name an entry may answer to.

    `module:qualname` entries also answer to `qualname`, and public
    top-level definitions answer to their bare name so helpers that moved
    modules during the port count as present. A locale key answers to the
    part after its namespace.
    """
    _, _, qualname = name.partition(":")
    candidates = [name, qualname, name.split(":", 1)[-1]]
    if qualname and "." not in qualname and not qualname.startswith("_"):
        candidates.append(qualname)
    return tuple(dict.fromkeys(candidates))


def apply_exclusions(
    surface: Surface, names: set[str], exclusions: tuple[Exclusion, ...]
) -> None:
    """Record names that survive the exclusion table as gaps."""
    for name in sorted(names):
        for exclusion in exclusions:
            if any(exclusion.matches(form) for form in _forms(name)):
                surface.suppressed[exclusion.pattern] = (
                    surface.suppressed.get(exclusion.pattern, 0) + 1
                )
                break
        else:
            surface.gaps.append(name)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def module_files(root: Path, excluded: tuple[Exclusion, ...] = ()) -> dict[str, str]:
    """Map `module:like:name` -> repo-relative path for frigate modules.

    Modules matching an entry of ``excluded`` are left out, so definitions
    inside an excluded detector plugin never surface as gaps.
    """
    files: dict[str, str] = {}
    base = root / "frigate"
    for path in base.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        parts = rel.split("/")
        if SKIP_DIRS & set(parts):
            continue
        module = "/".join(parts[1:])[:-3].replace("/", ".")
        if any(exclusion.matches(rel) for exclusion in excluded):
            continue
        files[module] = rel
    return files


def definitions(root: Path, excluded_modules: tuple[Exclusion, ...] = ()) -> set[str]:
    """`module:qualname` for functions and classes, `module:Class.method` for methods."""
    found: set[str] = set()
    for module, rel in module_files(root, excluded_modules).items():
        path = root / rel
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.add(f"{module}:{node.name}")
            elif isinstance(node, ast.ClassDef):
                found.add(f"{module}:{node.name}")
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        found.add(f"{module}:{node.name}.{sub.name}")
    return found


def api_routes(root: Path) -> set[str]:
    pattern = re.compile(
        r"@(?:router|app)\.(?:get|post|put|patch|delete)\(\s*[\"']([^\"']+)[\"']"
    )
    found: set[str] = set()
    for path in (root / "frigate" / "api").rglob("*.py"):
        found.update(pattern.findall(path.read_text(encoding="utf-8")))
    return found


def config_surface(root: Path) -> set[str]:
    """`Class.field` pairs and class names declared under frigate/config."""
    found: set[str] = set()
    for path in (root / "frigate" / "config").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            found.add(node.name)
            for sub in node.body:
                if isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
                    found.add(f"{node.name}.{sub.target.id}")
    return found


def web_files(root: Path) -> set[str]:
    base = root / "web" / "src"
    return {
        path.relative_to(root).as_posix() for path in base.rglob("*") if path.is_file()
    }


def locale_keys(root: Path) -> set[str]:
    found: set[str] = set()
    base = root / "web" / "public" / "locales" / "en"
    for path in sorted(base.rglob("*.json")):
        prefix = path.relative_to(base).as_posix()[:-5]
        data = json.loads(path.read_text(encoding="utf-8"))

        def walk(node: object, trail: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(value, f"{trail}.{key}" if trail else key)
            else:
                found.add(f"{prefix}:{trail}")

        walk(data, "")
    return found


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_modules(upstream: Path, _fork: Path) -> Surface:
    surface = Surface("modules")
    up = set(module_files(upstream).values())
    here = set(module_files(REPO_ROOT).values())
    apply_exclusions(surface, up - here, EXCLUDED_MODULES)
    return surface


def check_defs(upstream: Path, _fork: Path) -> Surface:
    surface = Surface("definitions")
    up = definitions(upstream, EXCLUDED_MODULES)
    here = definitions(REPO_ROOT)
    here_forms: set[str] = set()
    for name in here:
        here_forms.update(_forms(name))
    missing = {
        name for name in up if not any(form in here_forms for form in _forms(name))
    }
    apply_exclusions(surface, missing, EXCLUDED_DEFS)
    return surface


def check_routes(upstream: Path, _fork: Path) -> Surface:
    surface = Surface("api routes")
    apply_exclusions(
        surface, api_routes(upstream) - api_routes(REPO_ROOT), EXCLUDED_ROUTES
    )
    return surface


def check_config(upstream: Path, _fork: Path) -> Surface:
    surface = Surface("config schema")
    apply_exclusions(
        surface,
        config_surface(upstream) - config_surface(REPO_ROOT),
        EXCLUDED_CONFIG_FIELDS,
    )
    return surface


def check_web(upstream: Path, _fork: Path) -> Surface:
    surface = Surface("web files")
    apply_exclusions(
        surface, web_files(upstream) - web_files(REPO_ROOT), EXCLUDED_WEB_FILES
    )
    keys = Surface("locale keys")
    apply_exclusions(
        keys, locale_keys(upstream) - locale_keys(REPO_ROOT), EXCLUDED_LOCALE_KEYS
    )
    surface.gaps.extend(keys.gaps)
    surface.suppressed.update(keys.suppressed)
    return surface


CHECKS = (check_modules, check_defs, check_routes, check_config, check_web)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--upstream-dir",
        required=True,
        help="a checkout of blakeblackshear/frigate to compare against",
    )
    args = parser.parse_args()

    upstream = Path(args.upstream_dir)
    if not (upstream / "frigate").is_dir():
        print(f"{upstream} does not look like a frigate checkout", file=sys.stderr)
        return 2

    surfaces = [check(upstream, REPO_ROOT) for check in CHECKS]
    failed = False

    for surface in surfaces:
        if surface.gaps:
            failed = True
            print(
                f"{surface.name}: {len(surface.gaps)} gap(s) not covered by an exclusion"
            )
            for gap in surface.gaps:
                print(f"  missing: {gap}")
        else:
            print(f"{surface.name}: parity")

    used = {pattern for surface in surfaces for pattern in surface.suppressed}
    stale = [
        exclusion
        for group in ALL_EXCLUSIONS
        for exclusion in group
        if exclusion.pattern not in used
    ]
    if stale:
        print(f"\n{len(stale)} stale exclusion(s) that no longer match anything:")
        for exclusion in stale:
            print(f"  {exclusion.pattern}  # {exclusion.reason}")

    if failed:
        print(
            "\nParity gaps found. Port the feature, or record a reasoned "
            "exclusion in testing-scripts/check_upstream_parity.py."
        )
        return 1

    suppressed = sum(sum(surface.suppressed.values()) for surface in surfaces)
    print(
        f"\nFeature parity holds: {suppressed} documented exclusion(s) applied, "
        f"{len(stale)} stale."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
