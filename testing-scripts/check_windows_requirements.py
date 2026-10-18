# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Check that the native Windows dependency set can actually install.

Three things are verified, all against the PyPI JSON API so the check needs no
Windows machine:

1. Every requirement resolves to a version and publishes a Windows wheel (or is
   pure Python and installs from its source distribution).
2. The pins agree with each other. Each pinned package's own dependency
   declarations (``requires_dist`` of the release the pin selects, with its
   environment markers evaluated for 64-bit CPython 3.12 on Windows) are
   checked against every other pin in the file. A pin that satisfies PyPI on
   its own but contradicts another pin, such as a ``numpy`` or ``rich`` bump
   that an unchanged ``norfair`` cannot accept, makes ``pip install -r`` abort
   with "ResolutionImpossible" on the user's machine and in CI; this reports
   it here, naming both lines.
3. Every module Frigate imports at module scope that is not in the standard
   library is provided by a requirement, either directly or as a dependency of
   one. A package that arrives only transitively today can disappear with an
   upstream release, and the failure shows up as an ImportError on a user's
   machine rather than in CI.

The conflict check needs the ``packaging`` library for PEP 440 specifiers and
PEP 508 markers. It is part of the installed dependency closure, so CI has it;
when it is missing the check is skipped with a notice rather than failing.

Run from the repository root::

    python testing-scripts/check_windows_requirements.py

Exits non-zero and prints what is missing when the check fails.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

try:
    from packaging.markers import UndefinedEnvironmentName
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.version import InvalidVersion, Version

    HAVE_PACKAGING = True
except ImportError:  # pragma: no cover - only outside the dependency closure
    HAVE_PACKAGING = False

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = REPO_ROOT / "requirements.txt"
PACKAGE_ROOT = REPO_ROOT / "frigate"

#: import name -> distribution name, for the packages where they differ
IMPORT_TO_DISTRIBUTION = {
    "PIL": "Pillow",
    "cv2": "opencv-contrib-python",
    "dateutil": "python-dateutil",
    "paho": "paho-mqtt",
    "peewee_migrate": "peewee-migrate",
    "playhouse": "peewee",
    "py3nvml": "py3nvml",
    "py_vapid": "py-vapid",
    "ruamel": "ruamel.yaml",
    "sherpa_onnx": "sherpa-onnx",
    "sqlite_vec": "sqlite-vec",
    "titlecase": "titlecase",
    "zeep": "zeep",
    "zmq": "pyzmq",
    "ai_edge_litert": "ai-edge-litert",
    "bs4": "beautifulsoup4",
    "google": "google-genai",
    "onvif": "onvif-zeep-async",
    "pydantic_settings": "pydantic-settings",
    "tensorflow": "tensorflow-cpu",
    # the pywin32 package provides the SCM modules the Windows service imports
    "servicemanager": "pywin32",
    "win32event": "pywin32",
    "win32service": "pywin32",
    "win32serviceutil": "pywin32",
}

#: packages that publish only a source distribution. They are pure Python, so
#: pip builds them on Windows as part of the install.
SDIST_ONLY = {"titlecase"}

#: modules that are Linux, macOS or accelerator specific and are imported only
#: inside a guarded block or a platform branch
PLATFORM_ONLY = {
    "axengine",
    "cuda",
    "dx_engine",
    "hailo_platform",
    "memray",
    "memryx",
    "mlx",
    "mlx_whisper",
    "mosestokenizer",
    "rknn",
    "rknnlite",
    "setproctitle",
    "silero_vad_iterator",
    "synap",
    "tensorrt",
    "tflite_runtime",
    "tokenize_uk",
    "torch",
    "whisper",
    "whisper_timestamped",
    "wtpsplit",
}

WHEEL_PLATFORM_TAGS = ("win32", "win_amd64", "win_arm64")

#: the PEP 508 environment the markers are evaluated for: the only runtime
#: this application supports (see WINDOWS_COMPATIBILITY.md)
WINDOWS_PY312_ENVIRONMENT = {
    "implementation_name": "cpython",
    "implementation_version": "3.12.0",
    "os_name": "nt",
    "platform_machine": "AMD64",
    "platform_python_implementation": "CPython",
    "platform_release": "10",
    "platform_system": "Windows",
    "platform_version": "10.0.22631",
    "python_full_version": "3.12.0",
    "python_version": "3.12",
    "sys_platform": "win32",
}


@dataclass
class Pin:
    """One line of requirements.txt."""

    name: str
    extras: set[str]
    #: the version prefix of an ``==`` pin, with any trailing ``.*`` removed,
    #: or None for an unpinned line
    version: str | None
    raw: str
    #: the release the pin selects on PyPI, once resolved
    resolved: str | None = None
    #: that release's dependency declarations
    requires_dist: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return normalize(self.name)


def normalize(name: str) -> str:
    """Normalize a distribution name the way PyPI does."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements(path: Path) -> list[Pin]:
    """Return a :class:`Pin` for each requirement line."""
    requirements = []

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()

        if not line or line.startswith("-") or "://" in line:
            continue

        match = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[([^\]]*)\])?\s*(.*)$", line)

        if match is None:
            continue

        name = match.group(1)
        extras = {
            normalize(extra.strip())
            for extra in (match.group(2) or "").split(",")
            if extra.strip()
        }
        rest = match.group(3).strip()

        version = None
        pinned = re.match(r"^==\s*([0-9]+(?:\.[0-9]+)*)", rest)

        if pinned:
            version = pinned.group(1)

        requirements.append(Pin(name, extras, version, raw.strip()))

    return requirements


def fetch(name: str, version: str | None = None) -> dict:
    """Fetch the PyPI metadata for a distribution, or for one of its releases."""
    url = f"https://pypi.org/pypi/{name}/json"

    if version:
        url = f"https://pypi.org/pypi/{name}/{version}/json"

    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def matches_pin(release: str, version: str | None) -> bool:
    """Whether a release is one of the versions an ``==`` pin accepts.

    The pin ``1.26.*`` is stored as the prefix ``1.26`` and matches ``1.26.4``
    but not ``1.260.0``, so the comparison is by version component rather than
    by string prefix.
    """
    if version is None:
        return True

    wanted = version.split(".")
    parts = release.split(".")
    return parts[: len(wanted)] == wanted


def _is_prerelease(release: str) -> bool:
    if HAVE_PACKAGING:
        try:
            return Version(release).is_prerelease
        except InvalidVersion:
            return True

    return re.search(r"(a|b|rc|dev)\d*$", release) is not None


def _release_sort_key(release: str) -> tuple:
    if HAVE_PACKAGING:
        try:
            return (0, Version(release))
        except InvalidVersion:
            pass

    return (
        1,
        tuple(int(part) if part.isdigit() else -1 for part in release.split(".")),
    )


def _is_installable(files: list[dict], sdist_ok: bool) -> bool:
    """Whether a release's files include something pip can install on Windows."""
    for file in files:
        if file.get("yanked"):
            continue

        if file["packagetype"] == "sdist":
            if sdist_ok:
                return True
            continue

        if file["packagetype"] != "bdist_wheel":
            continue

        filename = file["filename"]

        if filename.endswith("-none-any.whl"):
            return True

        if any(tag in filename for tag in WHEEL_PLATFORM_TAGS):
            return True

    return False


def resolve_release(name: str, version: str | None, metadata: dict) -> str | None:
    """The release pip would select for a pin: the newest one that can install.

    Pre-releases are only considered when a pin names nothing else, which is
    also pip's rule.
    """
    releases = metadata["releases"]
    sdist_ok = normalize(name) in SDIST_ONLY
    candidates = [
        release
        for release, files in releases.items()
        if matches_pin(release, version) and _is_installable(files, sdist_ok)
    ]
    stable = [release for release in candidates if not _is_prerelease(release)]

    if stable:
        candidates = stable

    if not candidates:
        return None

    return max(candidates, key=_release_sort_key)


def has_windows_build(name: str, version: str | None, metadata: dict) -> bool:
    """Whether a distribution provides a Windows wheel or a pure Python wheel."""
    releases = metadata["releases"]

    for release, files in releases.items():
        if matches_pin(release, version) and _is_installable(files, sdist_ok=False):
            return True

    return False


def dependency_name(requirement: str) -> str:
    """The distribution a ``requires_dist`` entry names."""
    dependency = requirement.split(";")[0].strip()
    return re.split(r"[\s<>=!~\[(]", dependency)[0]


def applies_on_windows(requirement: Requirement, extras: set[str]) -> bool:
    """Whether a dependency declaration is active for this runtime.

    A marker that names ``extra`` is active when the requirement line asks for
    that extra; every other marker is evaluated against the Windows CPython
    3.12 environment.
    """
    if requirement.marker is None:
        return True

    for extra in sorted(extras) + [""]:
        environment = dict(WINDOWS_PY312_ENVIRONMENT, extra=extra)

        try:
            if requirement.marker.evaluate(environment):
                return True
        except UndefinedEnvironmentName:
            return False

    return False


def pin_conflicts(pins: list[Pin]) -> list[str]:
    """Pins that contradict the dependency declarations of other pins.

    Each message names the pinned line that declares the constraint, the
    constraint itself, and the pinned line that breaks it, so the fix is
    obvious from the report.
    """
    if not HAVE_PACKAGING:
        return []

    by_key = {pin.key: pin for pin in pins if pin.resolved is not None}
    conflicts: list[str] = []

    for pin in pins:
        if pin.resolved is None:
            continue

        for entry in pin.requires_dist:
            try:
                requirement = Requirement(entry)
            except InvalidRequirement:
                continue

            other = by_key.get(normalize(requirement.name))

            if other is None or other is pin:
                continue

            if not applies_on_windows(requirement, pin.extras):
                continue

            if not requirement.specifier:
                continue

            if requirement.specifier.contains(other.resolved, prereleases=True):
                continue

            conflicts.append(
                f"{pin.raw} ({pin.resolved}) requires "
                f"{requirement.name}{requirement.specifier}, but "
                f"{other.raw} selects {other.resolved}"
            )

    return conflicts


def imported_distribution(module: str) -> str:
    """Distribution name that provides an import name."""
    return IMPORT_TO_DISTRIBUTION.get(module, module)


def third_party_imports() -> dict[str, set[str]]:
    """Every non standard library module imported at module scope in frigate/."""
    stdlib = sys.stdlib_module_names
    imports: dict[str, set[str]] = {}

    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as err:
            print(f"unable to parse {path}: {err}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] if not node.level else []
            else:
                continue

            for name in names:
                top_level = name.split(".")[0]

                if not top_level or top_level in stdlib or top_level == "frigate":
                    continue

                imports.setdefault(top_level, set()).add(
                    str(path.relative_to(REPO_ROOT))
                )

    return imports


def main(requirements_path: Path = REQUIREMENTS) -> int:
    failures: list[str] = []
    pins = parse_requirements(requirements_path)
    provided: set[str] = set()

    try:
        shown = requirements_path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        shown = requirements_path

    print(f"Checking {shown} against PyPI")

    for pin in pins:
        try:
            metadata = fetch(pin.name)
        except (urllib.error.URLError, urllib.error.HTTPError) as err:
            failures.append(f"{pin.raw}: unable to read PyPI metadata ({err})")
            continue

        if pin.key not in SDIST_ONLY and not has_windows_build(
            pin.name, pin.version, metadata
        ):
            failures.append(f"{pin.raw}: no Windows wheel or pure Python wheel found")

        provided.add(pin.key)
        pin.resolved = resolve_release(pin.name, pin.version, metadata)

        # the dependency declarations of the release the pin selects, which
        # can differ from the newest release's that the project page reports
        requires_dist = metadata["info"].get("requires_dist") or []

        if pin.resolved and pin.resolved != metadata["info"].get("version"):
            try:
                requires_dist = (
                    fetch(pin.name, pin.resolved)["info"].get("requires_dist") or []
                )
            except (urllib.error.URLError, urllib.error.HTTPError) as err:
                failures.append(
                    f"{pin.raw}: unable to read PyPI metadata for "
                    f"{pin.resolved} ({err})"
                )

        pin.requires_dist = list(requires_dist)

        # a requirement's own dependencies can satisfy an import too
        for requirement in pin.requires_dist:
            dependency = dependency_name(requirement)

            if dependency:
                provided.add(normalize(dependency))

    print(f"{len(pins)} requirements checked")

    if HAVE_PACKAGING:
        conflicts = pin_conflicts(pins)

        if conflicts:
            failures.append(
                "pins that cannot be installed together (pip reports "
                "ResolutionImpossible):\n"
                + "\n".join(f"  {conflict}" for conflict in conflicts)
            )
        else:
            print("The pins are mutually compatible on Windows CPython 3.12")
    else:
        print(
            "NOTE: the packaging library is not installed, so the pins were not "
            "checked against each other"
        )

    missing = []

    for module, locations in sorted(third_party_imports().items()):
        if module in PLATFORM_ONLY:
            continue

        distribution = normalize(imported_distribution(module))

        if distribution not in provided:
            missing.append((module, sorted(locations)[0]))

    if missing:
        failures.append(
            "modules imported at module scope with no Windows requirement:\n"
            + "\n".join(f"  {module} (e.g. {path})" for module, path in missing)
        )

    if failures:
        print()
        for failure in failures:
            print(f"FAIL {failure}")
        return 1

    print("Windows requirements are complete and installable")
    return 0


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else REQUIREMENTS
    sys.exit(main(path))
