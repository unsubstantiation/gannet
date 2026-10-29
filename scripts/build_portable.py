# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Assemble the self-contained portable Windows bundle.

``bootstrap_windows.py`` installs the application onto a machine that already has
64-bit CPython 3.12: it creates a virtual environment, pip-installs the
requirements, and fetches the pinned binaries. This script produces the other
thing: one ZIP that already contains all of that, so a target machine needs
nothing installed, no network, and no administrator rights.

Layout inside ``gannet-nvr-<version>-win64.zip``::

    GannetNVR-<version>-win64/
      app/                      source root: gannet/, migrations/, web/dist,
                                labelmap.txt, ffmpeg/, bin/, model_cache/
      python/                   CPython 3.12 embeddable + Lib/site-packages
        GannetNVR.exe           the .exe entry point (a copy of python.exe)
      GannetNVR.cmd             double-clickable shim for the .exe
      run_gannet.ps1            PowerShell launcher (restart loop, model seeding)
      run_gannet.cmd            its double-clickable shim
      BUILD-INFO.json           versions and digests this bundle was built from
      SOURCE-OFFER.txt          source locations for the redistributed binaries
      LICENSE, LICENSES/, THIRD_PARTY.md, LICENSING.md, DEPENDENCIES.md ...

Why the layout is what it is:

* ``gannet/util/platform.py`` derives the install root from its own location
  (``get_source_root()`` is ``parents[2]`` of that file), so the package tree has
  to keep the checkout's shape. Third-party packages therefore live in the
  embedded interpreter's ``site-packages``, and ``python312._pth`` adds
  ``..\\app`` to ``sys.path`` for the application itself.
* ``migrations/`` is discovered relative to the working directory, so the
  launcher changes directory to ``app`` before starting the application.
* The models ship inside ``app/model_cache`` and the launcher copies them into
  the writable data directory on first run, because the application reads them
  from ``config/model_cache`` under the bundle's ``data`` directory.
* ``python/GannetNVR.exe`` is a byte-identical copy of the pinned
  ``python.exe``: a real PE executable that needs no compiler on the build
  host. ``gannet_launcher.pth`` in site-packages imports a small module while
  CPython sets up ``site``; that module recognises the renamed executable and
  starts ``python.exe -m gannet`` from ``app/``. The application and its spawned
  workers still run under ``python.exe``, so multiprocessing is unaffected.

Everything downloaded is either already pinned in ``bootstrap_windows.py`` (the
FFmpeg/go2rtc archives and the two models, re-verified here) or the CPython
embeddable package, whose SHA-256 is pinned in ``scripts/python_embed_pin.json``
to the digest upstream signed in the file's Sigstore bundle on python.org.
``--require-pinned`` turns an unrecorded digest into an error, which is what CI
uses; without it, an empty pin is filled in from the first download so a new
interpreter version can be adopted deliberately.

This runs on Windows (the supported build host) and on POSIX as a convenience,
because assembling wheels for a Windows target does not require Windows. It does
not run the result: only a Windows x64 host can do that.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import warnings
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
DIST = ROOT / "dist"
CACHE = DIST / ".cache"
PIN_FILE = SCRIPTS / "python_embed_pin.json"
REQUIREMENTS = ROOT / "requirements.txt"
WEB_DIR = ROOT / "web"
WINGET_TEMPLATE = ROOT / "winget-manifest" / "unsubstantiation.GannetNVR.yaml"

# The interpreter the bundle embeds. 3.12 is the only supported series
# (pyproject.toml `requires-python`), and the embeddable package is the CPython
# distribution intended for redistribution inside an application. 3.12.10 is
# the last 3.12 release python.org publishes Windows binaries for: under PEP
# 693 the 3.12.11+ security releases are source-only, so no embeddable package
# exists for them at any URL. The pin therefore tracks 3.12.10 deliberately;
# moving past it means building CPython from source or embedding a third-party
# standalone build, either of which is its own change with its own provenance.
PYTHON_EMBED_VERSION = "3.12.10"
PYTHON_EMBED_URL = "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"
# (implementation, abi tag) for the wheel tags pip must resolve against.
PYTHON_EMBED_ABI = ("cp", "cp312")

APP_DIRS = ("gannet", "migrations", "config")
APP_FILES = (
    "labelmap.txt",
    "audio-labelmap.txt",
    "pyproject.toml",
    "requirements.txt",
    # Licensing evidence travels with the binaries it governs.
    "LICENSE",
    "LICENSING.md",
    "THIRD_PARTY.md",
    "TRADEMARK.md",
    "DEPENDENCIES.md",
    "REUSE.toml",
)

# Not needed at runtime and large or misleading inside a bundle.
APP_EXCLUDES = {
    "__pycache__",
    "test",  # gannet/test
    ".pytest_cache",
    ".mypy_cache",
}

LAUNCHER_NAME = "run_gannet.ps1"
SHIM_NAME = "run_gannet.cmd"

# The .exe entry point. It is a copy of python.exe, not a compiled stub: the
# embeddable archive is already pinned and verified, so no compiler, SDK, or
# extra download is needed on the build host. A .pth file (processed by `site`)
# is what turns that interpreter into an application launcher.
EXE_NAME = "GannetNVR.exe"
EXE_SHIM_NAME = "GannetNVR.cmd"
EXE_PTH_NAME = "gannet_launcher.pth"
EXE_MODULE_NAME = "gannet_launcher.py"
# CPython also looks for <executable stem>._pth before <library stem>._pth on
# some builds. Shipping both with identical content keeps a renamed interpreter
# on exactly the same sys.path as python.exe.
EXE_PTH_CONFIG_NAME = "GannetNVR._pth"

log = logging.getLogger("build_portable")


class BuildError(RuntimeError):
    """The bundle cannot be produced from the current tree."""


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
    )


def load_bootstrap():
    """Load the root-level bootstrap script for its shared install-time code.

    The builder lives in ``scripts/`` and is also loaded by unit tests through
    importlib, so the repository root is not guaranteed to be on ``sys.path``.
    """
    sys.path.insert(0, str(ROOT))
    try:
        import bootstrap_windows as bootstrap

        return bootstrap
    finally:
        sys.path.pop(0)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(cmd: list[str], cwd: Path | None = None, capture: bool = False) -> str:
    log.info("  $ %s", " ".join(str(part) for part in cmd))
    result = subprocess.run(
        [str(part) for part in cmd],
        cwd=str(cwd) if cwd else None,
        capture_output=capture,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        if capture:
            sys.stderr.write(result.stdout or "")
            sys.stderr.write(result.stderr or "")
        raise BuildError(f"command failed ({result.returncode}): {' '.join(cmd)}")
    return (result.stdout or "") if capture else ""


### Manifest inputs


def project_version() -> str:
    """The version from pyproject.toml, which is what `frigate-nvr` ships."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise BuildError("pyproject.toml has no [project] version")
    return match.group(1)


def requirement_pins(path: Path) -> list[str]:
    pins = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            pins.append(stripped)
    return pins


def load_pin() -> dict:
    if not PIN_FILE.is_file():
        return {"version": PYTHON_EMBED_VERSION, "sha256": ""}
    return json.loads(PIN_FILE.read_text(encoding="utf-8"))


def save_pin(version: str, digest: str) -> None:
    PIN_FILE.write_text(
        json.dumps({"version": version, "sha256": digest}, indent=2) + "\n",
        encoding="utf-8",
    )


### Downloading


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    log.info("Downloading %s", url)
    try:
        with (
            urllib.request.urlopen(url, timeout=120) as response,
            open(partial, "wb") as out,
        ):
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        os.replace(partial, dest)
    except OSError as error:
        # HTTPError and URLError are OSErrors. A bare traceback buries which
        # pinned input moved (or was misspelled) several frames deep; the URL
        # is the one thing the person reading a failed build needs first.
        raise BuildError(f"downloading {url} failed: {error}") from error
    finally:
        partial.unlink(missing_ok=True)


def fetch_python_embed(explicit_zip: Path | None, require_pinned: bool) -> Path:
    """Return a verified embeddable CPython archive, recording the digest once."""
    if explicit_zip:
        archive = explicit_zip.resolve()
        if not archive.is_file():
            raise BuildError(f"--python-zip does not exist: {archive}")
        log.info("Using the supplied interpreter archive %s", archive)
        return archive

    archive = CACHE / f"python-{PYTHON_EMBED_VERSION}-embed-amd64.zip"
    pin = load_pin()
    if pin.get("version") != PYTHON_EMBED_VERSION:
        log.warning(
            "scripts/python_embed_pin.json pins %s but this builder embeds %s; "
            "the recorded digest does not apply",
            pin.get("version"),
            PYTHON_EMBED_VERSION,
        )
        pin = {"version": PYTHON_EMBED_VERSION, "sha256": ""}

    if archive.is_file():
        digest = sha256_file(archive)
        if pin.get("sha256") and digest != pin["sha256"]:
            raise BuildError(
                f"{archive} does not match the pinned sha256: got {digest}, "
                f"expected {pin['sha256']}. Delete {archive} and rebuild; if "
                "upstream re-published the file, update "
                "scripts/python_embed_pin.json deliberately"
            )
    else:
        download(PYTHON_EMBED_URL.format(v=PYTHON_EMBED_VERSION), archive)
        digest = sha256_file(archive)

    if not pin.get("sha256"):
        if require_pinned:
            raise BuildError(
                "the CPython embeddable digest is not pinned, and "
                "--require-pinned was requested. Build once without it, check "
                "the digest printed below against python.org, commit "
                "scripts/python_embed_pin.json, then rebuild:\n"
                f"    python {PYTHON_EMBED_VERSION}-embed-amd64.zip sha256 {digest}"
            )
        save_pin(PYTHON_EMBED_VERSION, digest)
        log.warning(
            "Recorded the CPython %s embeddable digest as %s in %s. Verify it "
            "against python.org and commit that file so later builds are "
            "checked rather than trusted",
            PYTHON_EMBED_VERSION,
            digest,
            PIN_FILE.relative_to(ROOT),
        )
    else:
        log.info("CPython %s embeddable digest verified", PYTHON_EMBED_VERSION)

    return archive


### Staging


def copy_tree(source: Path, dest: Path, excludes: set[str]) -> None:
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source)
        if any(part in excludes for part in relative.parts):
            continue
        if item.is_dir():
            continue
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def stage_app(app_dir: Path) -> None:
    log.info("Staging the application tree")
    for name in APP_DIRS:
        source = ROOT / name
        if name == "gannet":
            copy_tree(source, app_dir / name, APP_EXCLUDES)
        elif name == "config":
            # Only the example: a real config is user data and never ships.
            (app_dir / "config").mkdir(parents=True, exist_ok=True)
            example = source / "config.yml.example"
            if example.is_file():
                shutil.copy2(example, app_dir / "config" / example.name)
        else:
            copy_tree(source, app_dir / name, APP_EXCLUDES)

    for name in APP_FILES:
        source = ROOT / name
        if not source.is_file():
            raise BuildError(f"{name} is missing from the repository root")
        shutil.copy2(source, app_dir / name)

    licenses = ROOT / "LICENSES"
    if licenses.is_dir():
        copy_tree(licenses, app_dir / "LICENSES", set())


def build_web() -> Path:
    """Run the production frontend build and return ``web/dist``."""
    if not (WEB_DIR / "package.json").is_file():
        raise BuildError("web/package.json is missing")
    npm = shutil.which("npm")
    if not npm:
        raise BuildError(
            "npm is not on PATH. Install Node.js 22 or newer, or pass "
            "--skip-web to bundle an existing web/dist"
        )
    log.info("Building the web interface")
    if not (WEB_DIR / "node_modules").is_dir():
        run([npm, "ci"], cwd=WEB_DIR)
    run([npm, "run", "build:native"], cwd=WEB_DIR)
    dist = WEB_DIR / "dist"
    if not (dist / "index.html").is_file():
        raise BuildError("npm run build:native did not produce web/dist/index.html")
    return dist


def stage_web(app_dir: Path, skip_web: bool) -> None:
    built = WEB_DIR / "dist"
    if not skip_web:
        build_web()
    elif not (built / "index.html").is_file():
        raise BuildError(
            "--skip-web was passed but web/dist/index.html does not exist; "
            "build it first or drop the flag"
        )
    else:
        log.info("Bundling the existing web/dist")
    copy_tree(built, app_dir / "web" / "dist", {"__pycache__"})
    # The dev entry point makes platform._is_built_web_dir() reject a tree that
    # was never built; its presence here means the build silently did nothing.
    index = (app_dir / "web" / "dist" / "index.html").read_text(
        encoding="utf-8", errors="replace"
    )
    if "/src/main.tsx" in index:
        raise BuildError(
            "web/dist/index.html still references /src/main.tsx: that is the "
            "Vite dev entry, not a production build"
        )


def stage_python(python_dir: Path, archive: Path) -> str:
    """Extract the embeddable interpreter and return the ``._pth`` file name."""
    log.info("Staging CPython %s", PYTHON_EMBED_VERSION)
    python_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(python_dir)

    site_packages = python_dir / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)

    pth_files = sorted(python_dir.glob("python3*._pth"))
    if not pth_files:
        raise BuildError(
            f"{archive.name} has no python3xx._pth file; it is not the "
            "embeddable distribution this builder expects"
        )
    if not (python_dir / "python.exe").is_file():
        raise BuildError(f"{archive.name} does not contain python.exe")

    pth = pth_files[0]
    expected_zip = stdlib_zip_name()
    if pth.stem + ".zip" != expected_zip:
        raise BuildError(
            f"{archive.name} contains {pth.name}, but CPython "
            f"{PYTHON_EMBED_VERSION} needs a {expected_zip} path seed"
        )
    pth.write_bytes(pth_contents())
    log.info("  sys.path seed written to %s", pth.name)
    return str(site_packages)


def stdlib_zip_name() -> str:
    """``python312.zip`` for the pinned 3.12.x embeddable interpreter."""
    major, minor = PYTHON_EMBED_VERSION.split(".")[:2]
    return f"python{major}{minor}.zip"


def pth_contents() -> bytes:
    """The path seed, shared by ``python312._pth`` and ``GannetNVR._pth``.

    CPython probes a ``._pth`` named after the loaded DLL, then one named after
    the executable. The standard name is what a normal ``python.exe`` finds;
    the copy named after ``GannetNVR.exe`` keeps a renamed interpreter on the
    same path if a future build probes it first. Entries are relative to
    ``python/``. ``import site`` is required: it processes the launcher's
    ``.pth`` file.
    """
    return (
        "\n".join(
            [
                stdlib_zip_name(),
                ".",
                r"Lib\site-packages",
                r"..\app",
                "import site",
                "",
            ]
        )
    ).encode("utf-8")


# Distributions that publish no wheel the cross-install below can use. A
# native install builds them from the sdist without comment, but pip requires
# --only-binary alongside --platform/--abi because an sdist built on this host
# would carry this host's wheel tag, so wheels for these are built locally
# first and fed back through --find-links. That is only safe for pure-Python
# packages, whose wheel is none-any on every host; build_sdist_only_wheels
# asserts exactly that, so adding a compiled package here fails the build
# instead of shipping a host-platform wheel.
#
# Keys are normalised distribution names. The value is the requirement spec to
# build when the distribution is not itself a line in requirements.txt, or
# None when it is: requirements.txt remains the single source for the versions
# it pins, and this list only records the publishing gap. A spec is needed for
# a transitive dependency, whose constraint lives in another package's
# metadata; mirror it from there and say whose it is.
SDIST_ONLY_REQUIREMENTS: dict[str, str | None] = {
    # Direct pin in requirements.txt; 2.4.x is sdist-only (its one wheel is 2.3).
    "titlecase": None,
    # norfair 2.3.0 requires filterpy>=1.4.5,<2.0.0; filterpy has never
    # published a wheel.
    "filterpy": "filterpy>=1.4.5,<2.0.0",
    # pywebpush requires http-ece>=1.1.0; http-ece has never published a wheel.
    "http-ece": "http-ece>=1.1.0",
}


def requirement_name(pin: str) -> str:
    """The normalised distribution name of one requirement line."""
    name = re.split(r"[\s\[<>=!~;]", pin, maxsplit=1)[0].strip().lower()
    return re.sub(r"[-_.]+", "-", name)


def build_sdist_only_wheels(requirements: Path) -> Path | None:
    """Build wheels for the sdist-only pins and return their directory.

    The wheels land in the same cache ``install_project_metadata`` uses, and a
    later build reuses them only through the same constraints, so the cache
    cannot widen the set of acceptable versions.
    """
    pins_by_name = {
        requirement_name(pin): pin for pin in requirement_pins(requirements)
    }
    wanted = []
    for name, fallback_spec in SDIST_ONLY_REQUIREMENTS.items():
        spec = pins_by_name.get(name, fallback_spec)
        if spec:
            wanted.append(spec)
    if not wanted:
        return None

    wheels = CACHE / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    for pin in wanted:
        log.info("Building a wheel for %s (no wheel published for the pin)", pin)
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--disable-pip-version-check",
                "--wheel-dir",
                str(wheels),
                pin,
            ]
        )
        dist = requirement_name(pin).replace("-", "_")
        built = [
            path
            for path in wheels.glob("*.whl")
            if path.name.lower().startswith(f"{dist}-")
        ]
        if not built:
            raise BuildError(f"pip wheel produced no wheel for {pin} in {wheels}")
        for path in built:
            if not path.name.endswith("-none-any.whl"):
                raise BuildError(
                    f"{path.name} is not a pure-Python (none-any) wheel; a "
                    "host-built binary wheel must never enter a win_amd64 "
                    "bundle. If the distribution now ships compiled code, it "
                    "does not belong in SDIST_ONLY_REQUIREMENTS"
                )
    return wheels


def install_wheels(site_packages: Path, requirements: Path) -> None:
    """Install the pinned requirements for a Windows CPython 3.12 target.

    ``--no-compile`` is not an optimisation: pip would compile bytecode with the
    interpreter running the build, and 3.12 refuses ``.pyc`` files written by a
    different magic number. The bundle compiles on first launch instead.
    """
    count = len(requirement_pins(requirements))
    log.info("Installing %s pinned requirements into site-packages", count)
    local_wheels = build_sdist_only_wheels(requirements)
    implementation, abi = PYTHON_EMBED_ABI
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-compile",
        "--no-warn-script-location",
        "--disable-pip-version-check",
        "--upgrade",
        "--target",
        str(site_packages),
        "--requirement",
        str(requirements),
        "--platform",
        "win_amd64",
        # The full patch version, not "3.12": pip reads the latter as exactly
        # 3.12.0 when checking Requires-Python, and the interpreter the
        # bundle ships is the version named here.
        "--python-version",
        PYTHON_EMBED_VERSION,
        "--implementation",
        implementation,
        "--abi",
        abi,
        "--only-binary=:all:",
    ]
    if local_wheels is not None:
        command += ["--find-links", str(local_wheels)]
    run(command)

    # Console-script shims are generated for the build host's shell and cannot
    # run on Windows from inside site-packages.
    for scripts_dir in (site_packages / "bin", site_packages / "Scripts"):
        if scripts_dir.is_dir():
            shutil.rmtree(scripts_dir)

    fix_pywin32(site_packages)
    # filterpy 1.4.5 docstrings contain invalid escapes, which CPython 3.12
    # reports on the first import. The bundle ships no bytecode, so that first
    # import happens on the user's machine; fix the installed source instead.
    bootstrap = load_bootstrap()
    try:
        patched = bootstrap.fix_filterpy_escapes(site_packages)
    except bootstrap.BootstrapError as exc:
        raise BuildError(f"cannot patch filterpy sources: {exc}") from exc
    for relative in patched:
        log.info("  fixed invalid escape sequences in %s", relative)


def fix_pywin32(site_packages: Path) -> None:
    """Put pywin32's DLLs where the embedded interpreter will find them.

    A normal ``pip install`` of pywin32 relies on ``pywin32_postinstall.py`` to
    copy ``pywintypes312.dll`` out of ``pywin32_system32``. The embeddable
    interpreter searches its own directory, so the copies go there.
    """
    system = site_packages / "pywin32_system32"
    if not system.is_dir():
        return
    python_dir = site_packages.parent.parent
    copied = []
    for dll in sorted(system.glob("*.dll")):
        shutil.copy2(dll, python_dir / dll.name)
        copied.append(dll.name)
    if copied:
        log.info("  pywin32 DLLs placed next to python.exe: %s", ", ".join(copied))


def install_project_metadata(site_packages: Path, version: str) -> None:
    """Add the ``frigate-nvr`` metadata the app reads its version from.

    ``gannet/util/version.py`` calls ``importlib.metadata.version``, so the
    bundle needs a ``.dist-info`` directory. Only the metadata is copied: the
    package itself ships in ``app/`` in its checkout layout, which
    ``get_source_root()`` depends on.
    """
    log.info("Recording package metadata for version %s", version)
    wheels = CACHE / "wheels"
    wheels.mkdir(parents=True, exist_ok=True)
    # setuptools builds a local project in place, leaving build/lib behind. It is
    # not this script's output and must not end up in the checkout (or, worse, in
    # `git add -A`). Remove it only if the build created it.
    build_dir = ROOT / "build"
    preexisting_build_dir = build_dir.exists()
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            # Only the metadata is used, and the host running the build is not
            # necessarily the 3.12 the bundle targets, so the wheel's
            # requires-python is not a constraint on the builder.
            "--ignore-requires-python",
            "--wheel-dir",
            str(wheels),
            str(ROOT),
        ]
    )
    if build_dir.is_dir() and not preexisting_build_dir:
        shutil.rmtree(build_dir)

    candidates = sorted(wheels.glob("frigate_nvr-*.whl")) or sorted(
        wheels.glob("frigate-*.whl")
    )
    if not candidates:
        raise BuildError(f"no frigate-nvr wheel was produced in {wheels}")
    wheel = candidates[-1]
    with zipfile.ZipFile(wheel) as bundle:
        members = [
            name
            for name in bundle.namelist()
            if name.split("/")[0].endswith(".dist-info")
        ]
        if not members:
            raise BuildError(f"{wheel.name} has no .dist-info directory")
        for name in members:
            bundle.extract(name, site_packages)

    metadata = next(
        path
        for path in site_packages.glob("*.dist-info")
        if path.name.lower().startswith("frigate")
    )
    declared = re.search(
        r"^Version:\s*(.+)$",
        (metadata / "METADATA").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if declared and declared.group(1).strip() != version:
        raise BuildError(
            f"the wheel reports version {declared.group(1).strip()} but the "
            f"bundle is version {version}"
        )


# Only C/C++ SDK headers are optional here. In particular, TensorFlow's .bin
# descriptors, native libraries, Python packages, and license files are runtime
# or redistribution material and must not be treated as disposable SDK files.
SLIM_HEADER_RULES = {
    "tensorflow": (Path("tensorflow/include"), {".h", ".hpp", ".inc"}),
    "openvino": (Path("openvino/include"), {".h", ".hpp"}),
}
NOTICE_NAME_PARTS = ("license", "licence", "notice", "copying", "copyright")
NOTICE_CONTENT_PARTS = NOTICE_NAME_PARTS + (
    "spdx-",
    "all rights reserved",
    "permission is hereby granted",
    "redistribution and use",
)
COPYRIGHT_SYMBOL = re.compile(r"\(\s*c\s*\)", re.IGNORECASE)


def has_notice_or_unknown_content(path: Path) -> bool:
    """Keep headers that might carry attribution, or cannot be inspected safely."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BuildError(f"cannot inspect SDK header {path}: {exc}") from exc
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    if "\x00" in text or "©" in text or COPYRIGHT_SYMBOL.search(text):
        return True
    lower = text.lower()
    return any(marker in lower for marker in NOTICE_CONTENT_PARTS)


def is_link_or_reparse_point(path: Path) -> bool:
    """Catch Windows junctions as well as POSIX/Windows symbolic links."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def prune_sdk_headers(site_packages: Path) -> dict:
    """Remove the opt-in SDK headers and update all owning wheel RECORDs.

    Headers with attribution or uncertain content are retained. Ownership is
    established for every selected path before anything is removed; a missing
    or unreadable RECORD aborts the build rather than making package metadata
    silently inaccurate. Paths in the report are relative to site-packages.
    """
    if is_link_or_reparse_point(site_packages) or not site_packages.is_dir():
        raise BuildError(f"not a regular site-packages directory: {site_packages}")

    selected: dict[str, tuple[Path, str, int]] = {}
    components = {
        name: {
            "files_removed": 0,
            "bytes_removed": 0,
            "headers_retained_for_notices_or_unknown_content": 0,
        }
        for name in SLIM_HEADER_RULES
    }

    def walk_error(error: OSError) -> None:
        raise BuildError(f"cannot inspect SDK directory: {error}") from error

    for name, (relative_root, extensions) in SLIM_HEADER_RULES.items():
        include = site_packages
        for part in relative_root.parts:
            include /= part
            if is_link_or_reparse_point(include):
                raise BuildError(
                    f"refusing to prune a symlinked SDK directory or reparse point: {include}"
                )
        if not include.exists():
            continue
        if not include.is_dir():
            raise BuildError(f"SDK path is not a directory: {include}")

        # Never follow links out of the staged tree. Wheel installs normally
        # contain regular files; unexpected links are a reason to fail closed.
        for root, dirs, files in os.walk(
            include, onerror=walk_error, followlinks=False
        ):
            dirs.sort()
            files.sort()
            for entry in dirs + files:
                path = Path(root) / entry
                if is_link_or_reparse_point(path):
                    raise BuildError(
                        f"refusing to prune a symlinked SDK path or reparse point: {path}"
                    )
            for entry in files:
                path = Path(root) / entry
                if path.suffix.lower() not in extensions:
                    continue
                if any(
                    marker in part.lower()
                    for part in path.relative_to(include).parts
                    for marker in NOTICE_NAME_PARTS
                ) or has_notice_or_unknown_content(path):
                    components[name][
                        "headers_retained_for_notices_or_unknown_content"
                    ] += 1
                    continue
                relative = path.relative_to(site_packages).as_posix()
                selected[relative] = (path, name, path.stat().st_size)

    if selected:
        # A path can be recorded by more than one distribution. Remove it from
        # every owning RECORD, not merely from the first one found.
        owned: set[str] = set()
        updates: list[tuple[Path, list[list[str]]]] = []
        records = sorted(site_packages.glob("*.dist-info/RECORD"))
        for record in records:
            if is_link_or_reparse_point(record) or is_link_or_reparse_point(
                record.parent
            ):
                raise BuildError(f"refusing to modify a symlinked RECORD: {record}")
            try:
                with record.open(encoding="utf-8", newline="") as handle:
                    rows = list(csv.reader(handle, strict=True))
            except (OSError, UnicodeError, csv.Error) as exc:
                raise BuildError(f"cannot read wheel RECORD {record}: {exc}") from exc
            if any(len(row) != 3 for row in rows):
                raise BuildError(f"malformed wheel RECORD: {record}")

            retained = []
            changed = False
            record_path = record.relative_to(site_packages).as_posix()
            for row in rows:
                relative = row[0].replace("\\", "/")
                if relative in selected:
                    owned.add(relative)
                    changed = True
                else:
                    # The RECORD itself cannot retain a digest of its old
                    # contents. Empty hash/size is permitted by the wheel spec.
                    if relative == record_path:
                        row = [row[0], "", ""]
                    retained.append(row)
            if changed:
                # Rewriting a signed RECORD would invalidate the package's
                # signature. Do not silently drop or corrupt that metadata.
                for signature in ("RECORD.jws", "RECORD.p7s"):
                    signature_path = record.parent / signature
                    if signature_path.exists() or signature_path.is_symlink():
                        raise BuildError(f"cannot slim a signed wheel RECORD: {record}")
                updates.append((record, retained))

        missing = sorted(set(selected) - owned)
        if missing:
            raise BuildError(
                f"refusing slim cleanup: {len(missing)} selected header(s) have "
                f"no owning wheel RECORD; first: {missing[0]}"
            )

        temporary_records: list[tuple[Path, Path]] = []
        try:
            # Prepare all replacement metadata before deleting any headers.
            for record, rows in updates:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="",
                    prefix=".RECORD-slim-",
                    dir=record.parent,
                    delete=False,
                ) as handle:
                    temporary_records.append((record, Path(handle.name)))
                    csv.writer(handle, lineterminator="\n").writerows(rows)
            for path, name, size in selected.values():
                path.unlink()
                components[name]["files_removed"] += 1
                components[name]["bytes_removed"] += size
            for record, temporary in temporary_records:
                temporary.replace(record)
        finally:
            for _, temporary in temporary_records:
                temporary.unlink(missing_ok=True)

    report = {
        "enabled": True,
        "files_removed": sum(item["files_removed"] for item in components.values()),
        "bytes_removed": sum(item["bytes_removed"] for item in components.values()),
        "headers_retained_for_notices_or_unknown_content": sum(
            item["headers_retained_for_notices_or_unknown_content"]
            for item in components.values()
        ),
        "components": components,
        "removed_paths_relative_to_site_packages": sorted(selected),
    }
    log.info(
        "Slim SDK cleanup: %s headers, %.2f MiB extracted; %s retained for "
        "possible notices or unknown content",
        report["files_removed"],
        report["bytes_removed"] / (1024 * 1024),
        report["headers_retained_for_notices_or_unknown_content"],
    )
    return report


def stage_artifacts(app_dir: Path) -> list[dict]:
    """Fetch the pinned binaries and models, reusing bootstrap's pins.

    The URLs and digests are imported from ``bootstrap_windows.py`` rather than
    repeated here, so an install and a bundle can never disagree about which
    FFmpeg build they are.
    """
    bootstrap = load_bootstrap()

    downloads = CACHE / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    digests = downloads / "digests.json"
    staged: list[dict] = []

    ffmpeg_dir = app_dir / "ffmpeg"
    archive = downloads / f"ffmpeg-{bootstrap.FFMPEG_ARTIFACT.version}.zip"
    if not archive.is_file():
        download(bootstrap.FFMPEG_ARTIFACT.url, archive)
    digest = bootstrap.verify_or_record_digest(
        archive, bootstrap.FFMPEG_ARTIFACT, digests
    )
    bootstrap.extract_members(archive, bootstrap.FFMPEG_ARTIFACT.members, ffmpeg_dir)
    staged.append(
        {
            "name": "FFmpeg",
            "version": bootstrap.FFMPEG_ARTIFACT.version,
            "url": bootstrap.FFMPEG_ARTIFACT.url,
            "sha256": digest,
            "license": "GPL-2.0-or-later as built",
        }
    )

    go2rtc_dir = app_dir / "bin"
    archive = downloads / f"go2rtc-{bootstrap.GO2RTC_ARTIFACT.version}.zip"
    if not archive.is_file():
        download(bootstrap.GO2RTC_ARTIFACT.url, archive)
    digest = bootstrap.verify_or_record_digest(
        archive, bootstrap.GO2RTC_ARTIFACT, digests
    )
    bootstrap.extract_members(archive, bootstrap.GO2RTC_ARTIFACT.members, go2rtc_dir)
    staged.append(
        {
            "name": "go2rtc",
            "version": bootstrap.GO2RTC_ARTIFACT.version,
            "url": bootstrap.GO2RTC_ARTIFACT.url,
            "sha256": digest,
            "license": "MIT",
        }
    )

    model_dir = app_dir / "model_cache"
    model_dir.mkdir(parents=True, exist_ok=True)
    for artifact in (bootstrap.CPU_DETECTION_MODEL, bootstrap.AUDIO_MODEL):
        cached = downloads / f"{artifact.name}-{artifact.version}-{artifact.filename}"
        if not cached.is_file():
            download(artifact.url, cached)
        digest = bootstrap.verify_or_record_digest(cached, artifact, digests)
        shutil.copy2(cached, model_dir / artifact.filename)
        staged.append(
            {
                "name": artifact.name,
                "version": artifact.version,
                "url": artifact.url,
                "sha256": digest,
                "license": "Apache-2.0 (weights)",
            }
        )

    return staged


### Generated files


def launcher_script() -> str:
    """The launcher, modelled on the one bootstrap_windows.py generates.

    Gannet signals a restart by writing a marker file; the loop restarts only
    when the marker is present, so Ctrl+C and window close still stop it.
    """
    return r"""# SPDX-License-Identifier: LicenseRef-GNCL-1.0
# Generated by scripts/build_portable.py. Start Gannet NVR with this script.
#
# Everything runs from this folder: no Python install, no pip, no network.
# Writable data lives in data\ beside this script unless -BaseDir is given.
[CmdletBinding()]
param(
    # Store config, recordings, and the database somewhere other than the
    # bundle's data directory. Both forms are accepted: a relative path is
    # resolved against the current directory.
    [string]$BaseDir
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "python\python.exe"
$App = Join-Path $Root "app"

if (-not (Test-Path $Python)) {
    Write-Error "python\python.exe is missing from this bundle; the ZIP was not extracted completely"
    exit 1
}

$DataRoot = if ($BaseDir) { $BaseDir } elseif ($env:GANNET_BASE_DIR) {
    $env:GANNET_BASE_DIR
} elseif ($env:FRIGATE_BASE_DIR) {
    $env:FRIGATE_BASE_DIR
} else {
    Join-Path $Root "data"
}

# Pin the selected root for the app and every spawned child. Without this,
# platform.py would fall back to the interactive install's AppData directory.
$DataRoot = [Environment]::ExpandEnvironmentVariables($DataRoot)
$env:GANNET_BASE_DIR = [System.IO.Path]::GetFullPath($DataRoot)
$DataRoot = $env:GANNET_BASE_DIR

# Seed the pinned models into the data directory the application reads them
# from. Copying is idempotent and only happens when the file is absent, so a
# user who installed newer models keeps them.
$ModelSource = Join-Path $App "model_cache"
$ModelTarget = Join-Path $DataRoot "config\model_cache"
New-Item -ItemType Directory -Force -Path $ModelTarget | Out-Null
if (Test-Path $ModelSource) {
    Get-ChildItem -Path $ModelSource -Filter "*.tflite" -File | ForEach-Object {
        $destination = Join-Path $ModelTarget $_.Name
        if (-not (Test-Path $destination)) {
            Copy-Item -Path $_.FullName -Destination $destination
            Write-Host "Seeded model $($_.Name)"
        }
    }
}

# Gannet reads and writes its text files as UTF-8.
if (-not $env:PYTHONUTF8) { $env:PYTHONUTF8 = "1" }

$TmpRoot = if ($env:GANNET_TMP_DIR) { $env:GANNET_TMP_DIR } elseif ($env:FRIGATE_TMP_DIR) {
    $env:FRIGATE_TMP_DIR
} else { Join-Path $DataRoot "tmp" }
$Marker = Join-Path $TmpRoot "restart.requested"
$RestartLog = Join-Path $TmpRoot "logs\launcher.log"
$RestartWindowSeconds = 120
$MaxRestarts = 5
$BackoffSeconds = 30
$RestartTimes = @()

# A restart loop is otherwise invisible: the marker says only "restart", and
# a console that closes on exit takes the messages with it. Keep a small log
# of every restart with the marker's reason and the child's exit code.
function Write-RestartLog {
    param([string]$Message)
    $line = "$(Get-Date -Format o) $Message"
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $RestartLog) | Out-Null
        if ((Test-Path $RestartLog) -and ((Get-Item $RestartLog).Length -gt 524288)) {
            Move-Item -Path $RestartLog -Destination "$RestartLog.1" -Force
        }
        Add-Content -Path $RestartLog -Value $line -Encoding UTF8
    } catch {
        Write-Host "Could not write the restart log: $_"
    }
    Write-Host $line
}

# The migration router resolves ``migrations/`` against the working directory.
Push-Location $App
try {
    while ($true) {
        & $Python -m gannet @args
        $code = $LASTEXITCODE

        if (Test-Path $Marker) {
            $reason = (Get-Content $Marker -Raw -ErrorAction SilentlyContinue).Trim()
            if (-not $reason) { $reason = "unspecified" }
            Remove-Item $Marker -ErrorAction SilentlyContinue

            $now = Get-Date
            $RestartTimes = @($RestartTimes | Where-Object { ($now - $_).TotalSeconds -lt $RestartWindowSeconds })
            $RestartTimes += $now
            Write-RestartLog "restart $($RestartTimes.Count) in ${RestartWindowSeconds}s: exit code $code, reason: $reason"

            if ($RestartTimes.Count -gt $MaxRestarts) {
                Write-RestartLog "restart loop detected; backing off ${BackoffSeconds}s (see logs\gannet\current for the cause)"
                Start-Sleep -Seconds $BackoffSeconds
                $RestartTimes = @()
            }
            continue
        }

        if ($code -ne 0) {
            Write-RestartLog "Gannet exited with code $code; no restart requested"
        }
        break
    }
}
finally {
    Pop-Location
}

exit $code
"""


def cmd_shim() -> str:
    return (
        "@echo off\r\n"
        "rem SPDX-License-Identifier: LicenseRef-GNCL-1.0\r\n"
        "rem Double-clickable shim for run_gannet.ps1.\r\n"
        'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_gannet.ps1" %*\r\n'
        "exit /b %ERRORLEVEL%\r\n"
    )


def exe_shim() -> str:
    """Root-level double-clickable entry point for the real .exe.

    The ``--`` matters: CPython parses its own options before the launcher
    module runs, so Gannet's flags have to come after an end-of-options marker.
    The shim inserts it so ``GannetNVR.cmd --validate-config`` just works.
    """
    return (
        "@echo off\r\n"
        "rem SPDX-License-Identifier: LicenseRef-GNCL-1.0\r\n"
        "rem Double-clickable entry point for python\\GannetNVR.exe.\r\n"
        "rem Arguments follow -- so CPython does not parse them as its own.\r\n"
        '"%~dp0python\\GannetNVR.exe" -- %*\r\n'
        "exit /b %ERRORLEVEL%\r\n"
    )


def exe_launcher_pth() -> str:
    """The .pth line that starts the .exe launcher during ``site`` setup."""
    return (
        "# SPDX-License-Identifier: LicenseRef-GNCL-1.0\n"
        "# Generated by scripts/build_portable.py. Do not edit.\n"
        "import gannet_launcher\n"
    )


def exe_launcher_module() -> str:
    """The module imported by ``gannet_launcher.pth``.

    It runs only when the host executable is the renamed copy of python.exe.
    For the application and every multiprocessing child it is a cheap no-op.
    Keeping the launch here (rather than in a compiled stub) means the .exe is
    an unmodified, upstream-signed CPython binary and the build needs no
    compiler on Windows.
    """
    return r'''# SPDX-License-Identifier: LicenseRef-GNCL-1.0
# Generated by scripts/build_portable.py. Do not edit this copy in the bundle.
"""Start Gannet NVR when the bundle's .exe is launched.

GannetNVR.exe is a byte-identical copy of the pinned CPython python.exe. The
gannet_launcher.pth file next to this module imports it while CPython sets up
"site", before its own main loop runs. Every other process in the bundle (the
application and its multiprocessing children) runs python.exe, so importing
this module does nothing for them.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# The copy may be launched under another name (a command alias, for example),
# so the interpreter's own names are the ones that must NOT trigger a launch.
INTERPRETER_NAMES = {
    "python.exe",
    "pythonw.exe",
    "python3.exe",
    "pythonservice.exe",
}
RESTART_MARKER = "restart.requested"
# More than MAX_RESTARTS in RESTART_WINDOW_S is a crash loop, not a user
# pressing Restart. Back off so the machine is not spun in a tight circle and
# so the restart log has time to be read.
RESTART_WINDOW_S = 120
MAX_RESTARTS = 5
RESTART_BACKOFF_S = 30
RESTART_LOG_MAX_BYTES = 512 * 1024


def is_launcher_process() -> bool:
    """True for GannetNVR.exe, including a copy launched under another name."""
    executable = Path(sys.executable or "").resolve()
    return (
        executable.suffix.lower() == ".exe"
        and executable.name.lower() not in INTERPRETER_NAMES
    )


def app_args(raw_argv: list[str]) -> list[str]:
    """Gannet's arguments are the tokens after a -- separator.

    CPython parses its own options before this module runs, so application
    flags must follow --. GannetNVR.cmd inserts the separator for you.
    """
    rest = raw_argv[1:]
    if "--" not in rest:
        return []
    return list(rest[rest.index("--") + 1 :])


def bundle_root() -> Path:
    """This module lives at <root>/python/Lib/site-packages/gannet_launcher.py."""
    root = Path(__file__).resolve().parents[3]
    if not (root / "python" / "python.exe").is_file():
        root = Path(sys.executable).resolve().parent.parent
    return root


def data_root() -> Path:
    """Keep portable data in the bundle unless an explicit override is set."""
    override = os.environ.get("GANNET_BASE_DIR") or os.environ.get(
        "FRIGATE_BASE_DIR"
    )
    if override:
        return Path(os.path.expanduser(os.path.expandvars(override)))
    return bundle_root() / "data"


def seed_models(root: Path, data: Path) -> None:
    """Copy pinned models only when the writable copy is absent."""
    import shutil

    source = root / "app" / "model_cache"
    if not source.is_dir():
        return
    target = data / "config" / "model_cache"
    target.mkdir(parents=True, exist_ok=True)
    for model in sorted(source.glob("*.tflite")):
        destination = target / model.name
        if not destination.exists():
            shutil.copy2(model, destination)
            print(f"Seeded model {model.name}", flush=True)


def fail(message: str) -> None:
    print(f"GannetNVR.exe: {message}", file=sys.stderr, flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1)


def restart_log_path(data: Path) -> Path:
    """Next to the app's own log, so one folder holds all crash evidence."""
    return data / "tmp" / "logs" / "launcher.log"


def record_restart_event(data: Path, message: str) -> None:
    """Append a restart line to disk as well as the (often hidden) console.

    The .exe is a console app, but a shortcut can hide that window and it
    closes on exit. Without a file, a restart loop leaves no trace at all.
    """
    import datetime

    path = restart_log_path(data)
    try:
        if path.is_file() and path.stat().st_size > RESTART_LOG_MAX_BYTES:
            path.replace(path.with_suffix(".log.1"))
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {message}\n")
    except OSError:
        pass
    print(f"GannetNVR.exe: {message}", flush=True)


def main() -> None:
    # Imported here so the application and its workers only pay for os/sys at
    # startup, and so nothing but a launcher failure imports subprocess early.
    import subprocess

    root = bundle_root()
    python = root / "python" / "python.exe"
    app = root / "app"
    if not python.is_file():
        fail(f"{python} is missing; the ZIP was not extracted completely")
    if not app.is_dir():
        fail(f"{app} is missing; the ZIP was not extracted completely")

    data = data_root().resolve()
    seed_models(root, data)
    tmp_override = os.environ.get("GANNET_TMP_DIR") or os.environ.get(
        "FRIGATE_TMP_DIR"
    )
    marker = (Path(tmp_override) if tmp_override else data / "tmp") / RESTART_MARKER

    env = os.environ.copy()
    # The app and its spawned children must use the same bundle-local root as
    # model seeding and restart logging, not platform.py's AppData default.
    env["GANNET_BASE_DIR"] = str(data)
    env.setdefault("PYTHONUTF8", "1")

    raw_argv = list(getattr(sys, "orig_argv", sys.argv))
    command = [str(python), "-m", "gannet", *app_args(raw_argv)]

    # peewee-migrate resolves migrations/ against the working directory.
    restarts: list[float] = []
    while True:
        process = subprocess.Popen(command, cwd=str(app), env=env)
        try:
            code = process.wait()
        except KeyboardInterrupt:
            # Ctrl+C reaches both processes; let the child finish first.
            code = process.wait()
        if code is None:
            code = 0

        if marker.is_file():
            try:
                reason = marker.read_text(encoding="utf-8").strip() or "unspecified"
            except (OSError, UnicodeError):
                reason = "unspecified"
            try:
                marker.unlink()
            except OSError as err:
                record_restart_event(data, f"could not clear restart marker: {err}")

            now = time.monotonic()
            restarts = [t for t in restarts if now - t < RESTART_WINDOW_S]
            restarts.append(now)
            record_restart_event(
                data,
                f"restart {len(restarts)} in {RESTART_WINDOW_S}s: "
                f"exit code {code}, reason: {reason[:200]}",
            )
            if len(restarts) > MAX_RESTARTS:
                record_restart_event(
                    data,
                    f"restart loop detected; backing off {RESTART_BACKOFF_S}s "
                    "(see logs/gannet/current for the cause)",
                )
                time.sleep(RESTART_BACKOFF_S)
                restarts.clear()
            continue

        record_restart_event(data, f"child exited with code {code}; no restart requested")
        break

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(int(code) & 0xFFFFFFFF)


if is_launcher_process():
    try:
        main()
    except Exception:
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
'''


def stage_exe_launcher(python_dir: Path, site_packages: Path, staging: Path) -> Path:
    """Create the .exe entry point and the files that make it start Gannet.

    The executable is copied, never compiled: it is the same bytes CPython
    published and the build already verified against the committed SHA-256.
    """
    source = python_dir / "python.exe"
    if not source.is_file():
        raise BuildError(f"{source} is missing; cannot create {EXE_NAME}")

    # A wheel must never have claimed either name: a silent overwrite here
    # would either kill the .pth hook or import the wrong module at startup.
    for name in (EXE_PTH_NAME, EXE_MODULE_NAME):
        if (site_packages / name).exists():
            raise BuildError(
                f"a wheel already ships {name}; the .exe launcher needs it"
            )

    exe = python_dir / EXE_NAME
    shutil.copyfile(source, exe)
    (python_dir / EXE_PTH_CONFIG_NAME).write_bytes(pth_contents())
    (site_packages / EXE_PTH_NAME).write_bytes(exe_launcher_pth().encode("utf-8"))
    (site_packages / EXE_MODULE_NAME).write_bytes(exe_launcher_module().encode("utf-8"))
    (staging / EXE_SHIM_NAME).write_bytes(exe_shim().encode("utf-8"))
    log.info("  %s is a copy of python.exe (no compiler needed)", EXE_NAME)
    return exe


def verify_layout(staging: Path, expect_wheels: bool, expect_artifacts: bool) -> None:
    """Assert the staged tree has what the launcher and the app look for.

    Every path here is one the application resolves at runtime, so a rename in
    the app or a mistake in this script fails the build instead of producing an
    archive that starts and then cannot find its own models.
    """
    required = [
        staging / "python" / "python.exe",
        staging / "python" / "Lib" / "site-packages",
        staging / "app" / "gannet" / "__main__.py",
        staging / "app" / "migrations",
        staging / "app" / "web" / "dist" / "index.html",
        staging / "app" / "labelmap.txt",
        staging / "app" / "audio-labelmap.txt",
        staging / "app" / "LICENSE",
        staging / LAUNCHER_NAME,
        staging / SHIM_NAME,
        staging / EXE_SHIM_NAME,
        staging / "python" / EXE_NAME,
        staging / "python" / EXE_PTH_CONFIG_NAME,
        staging / "python" / "Lib" / "site-packages" / EXE_PTH_NAME,
        staging / "python" / "Lib" / "site-packages" / EXE_MODULE_NAME,
    ]
    if expect_artifacts:
        required += [
            staging / "app" / "ffmpeg" / "ffmpeg.exe",
            staging / "app" / "ffmpeg" / "ffprobe.exe",
            staging / "app" / "bin" / "go2rtc.exe",
            staging / "app" / "model_cache" / "cpu_model.tflite",
            staging / "app" / "model_cache" / "cpu_audio_model.tflite",
        ]
    missing = [str(path.relative_to(staging)) for path in required if not path.exists()]
    if missing:
        raise BuildError("the staged bundle is incomplete: " + ", ".join(missing))

    python_dir = staging / "python"
    interpreter = (python_dir / "python.exe").read_bytes()
    if (python_dir / EXE_NAME).read_bytes() != interpreter:
        raise BuildError(
            f"{EXE_NAME} is not a byte-identical copy of python.exe; the .exe "
            "must stay the pinned upstream binary"
        )
    standard_pth = stdlib_zip_name().removesuffix(".zip") + "._pth"
    for name in (standard_pth, EXE_PTH_CONFIG_NAME):
        seed = python_dir / name
        if not seed.is_file() or seed.read_bytes() != pth_contents():
            raise BuildError(f"{name} does not carry the expected sys.path seed")
    pth_hook = python_dir / "Lib" / "site-packages" / EXE_PTH_NAME
    if "import gannet_launcher" not in [
        line.strip()
        for line in pth_hook.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]:
        raise BuildError(f"{EXE_PTH_NAME} does not import the .exe launcher")
    if r'"%~dp0python\GannetNVR.exe" -- %*' not in (staging / EXE_SHIM_NAME).read_text(
        encoding="utf-8"
    ):
        raise BuildError(f"{EXE_SHIM_NAME} must pass arguments after --")

    if expect_wheels:
        metadata = list(
            (staging / "python" / "Lib" / "site-packages").glob("*.dist-info")
        )
        if len(metadata) < 2:
            raise BuildError(
                "site-packages has almost no installed distributions; the wheel "
                "install did not run"
            )
        if not any(path.name.startswith("frigate_nvr-") for path in metadata):
            raise BuildError(
                "the frigate-nvr metadata is missing; the version would report as 'dev'"
            )

    # Anything compiled on the build host would carry the wrong bytecode magic
    # number for 3.12, and a stale __pycache__ in the app tree would shadow the
    # source it was built from.
    stale = [
        path
        for path in list(staging.rglob("__pycache__")) + list(staging.rglob("*.pyc"))
        if path.exists()
    ]
    if stale:
        raise BuildError(f"bytecode leaked into the bundle: {stale[0]}")

    # With no bytecode in the bundle, every source is compiled on the user's
    # first launch. A leftover invalid escape in filterpy would be printed as a
    # SyntaxWarning then, so catch it here instead.
    filterpy_dir = staging / "python" / "Lib" / "site-packages" / "filterpy"
    for path in sorted(filterpy_dir.rglob("*.py")):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                compile(path.read_bytes(), str(path), "exec")
            except (SyntaxError, ValueError):
                continue  # an unimportable example cannot warn at runtime
        if any("invalid escape sequence" in str(item.message) for item in caught):
            raise BuildError(f"invalid escape sequence left in {path}")


def build_info(
    version: str,
    site_packages: Path,
    artifacts: list[dict],
    python_archive: Path,
    launcher_exe: Path,
    sdk_pruning: dict | None = None,
) -> str:
    distributions = []
    for metadata in sorted(site_packages.glob("*.dist-info")):
        name = metadata.name.removesuffix(".dist-info").rsplit("-", 1)[0]
        declared = re.search(
            r"^Version:\s*(.+)$",
            (metadata / "METADATA").read_text(encoding="utf-8", errors="replace"),
            re.MULTILINE,
        )
        distributions.append(
            {
                "name": name,
                "version": declared.group(1).strip() if declared else "unknown",
            }
        )

    suffix = "-slim" if sdk_pruning is not None else ""
    payload = {
        "bundle": f"GannetNVR-{version}-win64{suffix}",
        "version": version,
        "bundle_mode": "slim" if sdk_pruning is not None else "full",
        "sdk_pruning": sdk_pruning
        if sdk_pruning is not None
        else {"enabled": False, "files_removed": 0, "bytes_removed": 0},
        "python": {
            "version": PYTHON_EMBED_VERSION,
            "source": PYTHON_EMBED_URL.format(v=PYTHON_EMBED_VERSION),
            "sha256": sha256_file(python_archive),
        },
        "launcher": {
            "path": f"python/{EXE_NAME}",
            "source": "python.exe from the pinned CPython embeddable archive",
            "sha256": sha256_file(launcher_exe),
            "note": "byte-identical copy of python.exe; unmodified upstream binary",
        },
        "runtime_artifacts": artifacts,
        "python_distributions": distributions,
        "notes": [
            "Licenses for every Python and npm dependency are in THIRD_PARTY.md.",
            "Source locations for the redistributed binaries are in SOURCE-OFFER.txt.",
            "This bundle contains no machine-specific data; the first launch "
            "creates data\\ beside the launchers inside the extracted bundle.",
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def source_offer(artifacts: list[dict], slim: bool = False) -> str:
    """Written offer for the copyleft components a redistributed bundle carries."""
    lines = [
        "Source code for the third-party binaries redistributed in this bundle",
        "=====================================================================",
        "",
        "This bundle contains compiled third-party components. Their licenses",
        "require that the corresponding source stays available, and this file is",
        "the written offer for it. Nothing here belongs to the Gannet NVR",
        "project's own license; see LICENSE and THIRD_PARTY.md.",
        "",
    ]
    for artifact in artifacts:
        lines += [
            f"{artifact['name']} {artifact['version']} -- {artifact['license']}",
            f"  Shipped from: {artifact['url']}",
            f"  sha256:       {artifact['sha256']}",
        ]
        if artifact["name"] == "FFmpeg":
            lines += [
                "  Source: https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz",
                "  Build scripts: https://github.com/GyanD/codexffmpeg/tree/8.1.2",
                "  This build enables x264 and x265, so it is GPL-2.0-or-later and",
                "  not LGPL. Redistributing it carries the GPL's source",
                "  obligations; the binaries are unmodified.",
            ]
        elif artifact["name"] == "go2rtc":
            lines += ["  Source: https://github.com/AlexxIT/go2rtc/tree/v1.9.14"]
        else:
            lines += [
                "  Source: https://github.com/google-coral/test_data"
                if artifact["name"] == "cpu-detection-model"
                else "  Source: https://tfhub.dev/google/lite-model/yamnet/classification/tflite/1"
            ]
        lines.append("")

    lines += [
        "CPython 3.12 (PSF-2.0)",
        f"  Source: https://www.python.org/ftp/python/{PYTHON_EMBED_VERSION}/",
        "  The embeddable distribution is redistributed unmodified.",
        f"  python/{EXE_NAME} is a byte-for-byte copy of its python.exe, not a",
        "  separately compiled launcher; any Authenticode signature on it is",
        "  upstream's. The Gannet launcher code next to it is Python source.",
        "",
        "Python packages: wheel distributions installed into",
        "  python/Lib/site-packages (pip updates installation metadata).",
        "  filterpy (MIT) is modified in place: invalid escape sequences",
        "  in its LaTeX docstrings are doubled so CPython 3.12 does not warn.",
        "  String values are unchanged. Apply the same change with",
        "  bootstrap_windows.py's fix_filterpy_escapes, or fetch the original",
        "  sdist at https://pypi.org/project/filterpy/#files.",
    ]
    if slim:
        lines += [
            "  This slim bundle omits selected TensorFlow and OpenVINO SDK",
            "  headers and updates the owning wheel RECORD files. BUILD-INFO.json",
            "  lists the omitted paths. License and notice files, and headers",
            "  that may contain attribution, are retained.",
        ]
    lines += [
        "GPL-2.0-or-later applies to Unidecode",
        "  (https://pypi.org/project/Unidecode/1.4.0/#files); MPL-2.0 applies to",
        "py-vapid and pywebpush. Sources are the published sdists, and the",
        "licenses section of DEPENDENCIES.md explains what each requires.",
        "",
    ]
    return "\n".join(lines)


def winget_manifest(
    template: str, version: str, bundle_name: str, digest: str, url: str
) -> str:
    return (
        template.replace("__VERSION__", version)
        .replace("__BUNDLE_ROOT__", bundle_name)
        .replace("__SHA256__", digest)
        .replace("__URL__", url)
    )


def release_notes(
    version: str,
    bundle_name: str,
    digest: str,
    artifacts: list[dict],
    slim: bool = False,
) -> str:
    slim_note = (
        "## Slim build\n\n"
        "Selected TensorFlow and OpenVINO C/C++ SDK headers are omitted. "
        "Native custom-op or extension development requires the full bundle. "
        "See `BUILD-INFO.json` for the omitted paths and cleanup statistics.\n\n"
        if slim
        else ""
    )
    rows = "\n".join(
        f"| {item['name']} | {item['version']} | {item['license']} |"
        for item in artifacts
    )
    return f"""# Gannet NVR {version} for Windows x64

Self-contained portable bundle. No Python install, no administrator rights, no
network access required.

{slim_note}## Install

1. Extract `{bundle_name}.zip` anywhere writable, for example
   `%LOCALAPPDATA%\\Programs\\GannetNVR`. Do not extract into `C:\\Program Files`.
2. Double-click `GannetNVR.cmd`, or run `python\\{EXE_NAME}` directly. It is a
   real Windows executable: a copy of the bundled CPython interpreter that starts
   Gannet with the right working directory and models.
3. Open <https://localhost:8971> and accept the first-run warning for the
   generated self-signed certificate. The generated administrator password is
   printed on first start and recorded in
   `data\\tmp\\logs\\gannet\\current` inside the extracted bundle.

`run_gannet.ps1` and `run_gannet.cmd` remain as a PowerShell alternative with
`-BaseDir <path>`. With the .exe, set `GANNET_BASE_DIR` instead. The `.cmd`
inserts the `--` separator CPython needs, so pass application flags straight
to it: `GannetNVR.cmd --validate-config`. Running the exe directly needs the
separator: `python\\GannetNVR.exe -- --validate-config`.

Configuration, the database, media, cache, logs, and downloaded models live in
`data\\` inside the bundle by default. Moving the bundle moves its data with it.
To remove the application and its data, stop it and delete the folder.

## Verify

```
{digest}  {bundle_name}.zip
```

## Included runtime

| Component | Version | License |
| --- | --- | --- |
{rows}
| CPython | {PYTHON_EMBED_VERSION} embeddable | PSF-2.0 |

Licensing for every dependency, and the source locations for the binaries above,
are in `THIRD_PARTY.md`, `DEPENDENCIES.md`, and `SOURCE-OFFER.txt` inside the
bundle.
"""


### Packaging


def write_deterministic_zip(source_root: Path, dest: Path) -> None:
    """Zip a directory tree with sorted entries and fixed timestamps.

    Two builds of the same tree should produce the same bytes, so the archive
    carries no build clock and no filesystem metadata.
    """
    files = sorted(path for path in source_root.rglob("*") if path.is_file())
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(source_root)
            info = zipfile.ZipInfo(str(Path(source_root.name) / relative))
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            executable = path.suffix.lower() in {".exe", ".dll", ".cmd", ".ps1"}
            info.external_attr = (0o755 if executable else 0o644) << 16
            archive.writestr(info, path.read_bytes())


### Orchestration


def main(argv: list[str] | None = None) -> int:
    global PYTHON_EMBED_VERSION

    parser = argparse.ArgumentParser(
        prog="build_portable",
        description="Build the self-contained portable Windows bundle",
    )
    parser.add_argument("--version", help="override the pyproject.toml version")
    parser.add_argument(
        "--output-dir",
        help="where artifacts are written (default: dist/, or dist/slim/ with --slim)",
    )
    parser.add_argument(
        "--slim",
        action="store_true",
        help="omit selected TensorFlow/OpenVINO SDK headers (native extensions need the full bundle)",
    )
    parser.add_argument(
        "--python-version",
        default=PYTHON_EMBED_VERSION,
        help="CPython embeddable version to bundle (default: %(default)s)",
    )
    parser.add_argument(
        "--python-zip",
        help="use a local embeddable archive instead of downloading one",
    )
    parser.add_argument(
        "--requirements",
        default=str(REQUIREMENTS),
        help="requirements file to install (default: requirements.txt)",
    )
    parser.add_argument("--skip-web", action="store_true", help="reuse web/dist")
    parser.add_argument(
        "--skip-wheels", action="store_true", help="do not install the requirements"
    )
    parser.add_argument(
        "--skip-artifacts",
        action="store_true",
        help="do not fetch FFmpeg, go2rtc, models",
    )
    parser.add_argument(
        "--require-pinned",
        action="store_true",
        help="fail instead of recording an unpinned interpreter digest (CI)",
    )
    parser.add_argument(
        "--plan-only", action="store_true", help="print the plan and exit, no network"
    )
    parser.add_argument(
        "--keep-staging", action="store_true", help="leave the staging tree"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    PYTHON_EMBED_VERSION = args.python_version

    version = args.version or project_version()
    output_dir = Path(
        args.output_dir or (DIST / "slim" if args.slim else DIST)
    ).resolve()
    bundle_name = f"GannetNVR-{version}-win64" + ("-slim" if args.slim else "")
    staging = output_dir / ".staging" / bundle_name
    requirements = Path(args.requirements).resolve()

    if args.slim and args.skip_wheels:
        raise BuildError("--slim cannot be combined with --skip-wheels")
    if not requirements.is_file():
        raise BuildError(f"requirements file not found: {requirements}")

    log.info("Gannet NVR %s portable bundle", version)
    log.info("  staging: %s", staging)
    log.info("  CPython: %s embeddable amd64", PYTHON_EMBED_VERSION)
    log.info("  requirements: %s", requirements)
    log.info("  mode: %s", "slim (SDK headers omitted)" if args.slim else "full")
    log.info("  web: %s", "reuse web/dist" if args.skip_web else "build")
    log.info(
        "  binaries: %s", "skip" if args.skip_artifacts else "FFmpeg, go2rtc, 2 models"
    )
    if os.name != "nt":
        log.info(
            "  host: %s (wheels cross-installed for win_amd64; the bundle itself "
            "runs on Windows only)",
            sys.platform,
        )

    if args.plan_only:
        missing = [name for name in APP_DIRS + APP_FILES if not (ROOT / name).exists()]
        if missing:
            raise BuildError(f"missing from the tree: {', '.join(missing)}")
        log.info("Plan is complete: %s", bundle_name)
        return 0

    if staging.exists():
        shutil.rmtree(staging)
    app_dir = staging / "app"
    app_dir.mkdir(parents=True)

    stage_app(app_dir)
    stage_web(app_dir, args.skip_web)

    python_archive = fetch_python_embed(
        Path(args.python_zip) if args.python_zip else None, args.require_pinned
    )
    site_packages = Path(stage_python(staging / "python", python_archive))

    if args.skip_wheels:
        log.warning("Skipping the requirements; the bundle will not start")
    else:
        install_wheels(site_packages, requirements)
        install_project_metadata(site_packages, version)

    sdk_pruning = prune_sdk_headers(site_packages) if args.slim else None
    artifacts = [] if args.skip_artifacts else stage_artifacts(app_dir)

    (staging / LAUNCHER_NAME).write_text(launcher_script(), encoding="utf-8")
    # The .cmd shims carry CRLF themselves; write bytes so a Windows build host
    # does not translate \n a second time and leave stray \r characters.
    (staging / SHIM_NAME).write_bytes(cmd_shim().encode("utf-8"))
    launcher_exe = stage_exe_launcher(staging / "python", site_packages, staging)

    log.info("Checking the staged layout")
    verify_layout(staging, not args.skip_wheels, not args.skip_artifacts)

    (staging / "BUILD-INFO.json").write_text(
        build_info(
            version, site_packages, artifacts, python_archive, launcher_exe, sdk_pruning
        ),
        encoding="utf-8",
    )
    (staging / "SOURCE-OFFER.txt").write_text(
        source_offer(artifacts, slim=args.slim), encoding="utf-8"
    )

    log.info("Writing the archive")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{bundle_name}.zip"
    write_deterministic_zip(staging, archive)
    digest = sha256_file(archive)
    size_mb = archive.stat().st_size / (1024 * 1024)

    (archive.with_suffix(".zip.sha256")).write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )
    checksums_name = "SHA256SUMS-slim.txt" if args.slim else "SHA256SUMS.txt"
    notes_name = "RELEASE-NOTES-slim.md" if args.slim else "RELEASE-NOTES.md"
    (output_dir / checksums_name).write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )
    (output_dir / notes_name).write_text(
        release_notes(version, bundle_name, digest, artifacts, slim=args.slim),
        encoding="utf-8",
    )

    # The checked-in winget template describes the standard release, not this
    # optional SDK-trimmed variant.
    if not args.slim and WINGET_TEMPLATE.is_file():
        url = (
            "https://github.com/unsubstantiation/gannet/releases/download/"
            f"v{version}/{archive.name}"
        )
        (output_dir / WINGET_TEMPLATE.name).write_text(
            winget_manifest(
                WINGET_TEMPLATE.read_text(encoding="utf-8"),
                version,
                bundle_name,
                digest,
                url,
            ),
            encoding="utf-8",
        )
        log.info("Wrote a winget manifest with this build's digest")

    if not args.keep_staging:
        shutil.rmtree(staging)
        # Another full/slim build may have its own retained staging tree.
        try:
            staging.parent.rmdir()
        except OSError:
            pass  # leave a nonempty staging directory alone

    log.info("")
    log.info("Built %s (%.1f MiB)", archive, size_mb)
    log.info("  sha256 %s", digest)
    log.info(
        "  %s",
        "Extract on a Windows x64 host and double-click GannetNVR.cmd "
        "(or python\\GannetNVR.exe) to verify it starts",
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BuildError as error:
        log.error("build failed: %s", error)
        sys.exit(1)
