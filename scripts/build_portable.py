# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Assemble the self-contained portable Windows bundle.

``bootstrap_windows.py`` installs the application onto a machine that already has
64-bit CPython 3.12: it creates a virtual environment, pip-installs the
requirements, and fetches the pinned binaries. This script produces the other
thing: one ZIP that already contains all of that, so a target machine needs
nothing installed, no network, and no administrator rights.

Layout inside ``gannet-nvr-<version>-win64.zip``::

    GannetNVR-<version>-win64/
      app/                      source root: frigate/, migrations/, web/dist,
                                labelmap.txt, ffmpeg/, bin/, model_cache/
      python/                   CPython 3.12 embeddable + Lib/site-packages
      run_gannet.ps1            launcher (restart loop, model seeding)
      run_gannet.cmd            double-clickable shim for the launcher
      BUILD-INFO.json           versions and digests this bundle was built from
      SOURCE-OFFER.txt          source locations for the redistributed binaries
      LICENSE, LICENSES/, THIRD_PARTY.md, LICENSING.md, DEPENDENCIES.md ...

Why the layout is what it is:

* ``frigate/util/platform.py`` derives the install root from its own location
  (``get_source_root()`` is ``parents[2]`` of that file), so the package tree has
  to keep the checkout's shape. Third-party packages therefore live in the
  embedded interpreter's ``site-packages``, and ``python312._pth`` adds
  ``..\\app`` to ``sys.path`` for the application itself.
* ``migrations/`` is discovered relative to the working directory, so the
  launcher changes directory to ``app`` before starting the application.
* The models ship inside ``app/model_cache`` and the launcher copies them into
  the writable data directory on first run, because the application reads them
  from ``config/model_cache`` under ``%LOCALAPPDATA%\\Frigate``.

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
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.request
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

APP_DIRS = ("frigate", "migrations", "config")
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
    "test",  # frigate/test
    ".pytest_cache",
    ".mypy_cache",
}

LAUNCHER_NAME = "run_gannet.ps1"
SHIM_NAME = "run_gannet.cmd"

log = logging.getLogger("build_portable")


class BuildError(RuntimeError):
    """The bundle cannot be produced from the current tree."""


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
    )


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
        if name == "frigate":
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
    pth.write_text(
        "\n".join(
            [
                pth.stem.replace("python", "python") + ".zip",
                ".",
                r"Lib\site-packages",
                r"..\app",
                "import site",
                "",
            ]
        ),
        encoding="utf-8",
    )
    log.info("  sys.path seed written to %s", pth.name)
    return str(site_packages)


def install_wheels(site_packages: Path, requirements: Path) -> None:
    """Install the pinned requirements for a Windows CPython 3.12 target.

    ``--no-compile`` is not an optimisation: pip would compile bytecode with the
    interpreter running the build, and 3.12 refuses ``.pyc`` files written by a
    different magic number. The bundle compiles on first launch instead.
    """
    count = len(requirement_pins(requirements))
    log.info("Installing %s pinned requirements into site-packages", count)
    implementation, abi = PYTHON_EMBED_ABI
    run(
        [
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
            "--python-version",
            PYTHON_EMBED_VERSION.rsplit(".", 1)[0],
            "--implementation",
            implementation,
            "--abi",
            abi,
            "--only-binary=:all:",
        ]
    )

    # Console-script shims are generated for the build host's shell and cannot
    # run on Windows from inside site-packages.
    for scripts_dir in (site_packages / "bin", site_packages / "Scripts"):
        if scripts_dir.is_dir():
            shutil.rmtree(scripts_dir)

    fix_pywin32(site_packages)


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

    ``frigate/util/version.py`` calls ``importlib.metadata.version``, so the
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


def stage_artifacts(app_dir: Path) -> list[dict]:
    """Fetch the pinned binaries and models, reusing bootstrap's pins.

    The URLs and digests are imported from ``bootstrap_windows.py`` rather than
    repeated here, so an install and a bundle can never disagree about which
    FFmpeg build they are.
    """
    sys.path.insert(0, str(ROOT))
    try:
        import bootstrap_windows as bootstrap
    finally:
        sys.path.pop(0)

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

    Frigate signals a restart by writing a marker file; the loop restarts only
    when the marker is present, so Ctrl+C and window close still stop it.
    """
    return r"""# SPDX-License-Identifier: LicenseRef-GNCL-1.0
# Generated by scripts/build_portable.py. Start Gannet NVR with this script.
#
# Everything runs from this folder: no Python install, no pip, no network.
# Writable data lives in %LOCALAPPDATA%\Frigate unless -BaseDir is given.
[CmdletBinding()]
param(
    # Store config, recordings, and the database somewhere other than
    # %LOCALAPPDATA%\Frigate. Both forms are accepted: a relative path is
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

if ($BaseDir) {
    $env:FRIGATE_BASE_DIR = [System.IO.Path]::GetFullPath($BaseDir)
}
$DataRoot = if ($env:FRIGATE_BASE_DIR) { $env:FRIGATE_BASE_DIR } else {
    Join-Path $env:LOCALAPPDATA "Frigate"
}

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

# Frigate reads and writes its text files as UTF-8.
if (-not $env:PYTHONUTF8) { $env:PYTHONUTF8 = "1" }

$TmpRoot = if ($env:FRIGATE_TMP_DIR) { $env:FRIGATE_TMP_DIR } else { Join-Path $DataRoot "tmp" }
$Marker = Join-Path $TmpRoot "restart.requested"

# The migration router resolves ``migrations/`` against the working directory.
Push-Location $App
try {
    while ($true) {
        & $Python -m frigate @args
        $code = $LASTEXITCODE

        if (Test-Path $Marker) {
            Remove-Item $Marker -ErrorAction SilentlyContinue
            Write-Host "Frigate requested a restart, starting it again"
            continue
        }

        if ($code -ne 0) {
            Write-Host "Frigate exited with code $code"
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


def verify_layout(staging: Path, expect_wheels: bool, expect_artifacts: bool) -> None:
    """Assert the staged tree has what the launcher and the app look for.

    Every path here is one the application resolves at runtime, so a rename in
    the app or a mistake in this script fails the build instead of producing an
    archive that starts and then cannot find its own models.
    """
    required = [
        staging / "python" / "python.exe",
        staging / "python" / "Lib" / "site-packages",
        staging / "app" / "frigate" / "__main__.py",
        staging / "app" / "migrations",
        staging / "app" / "web" / "dist" / "index.html",
        staging / "app" / "labelmap.txt",
        staging / "app" / "audio-labelmap.txt",
        staging / "app" / "LICENSE",
        staging / LAUNCHER_NAME,
        staging / SHIM_NAME,
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


def build_info(
    version: str,
    site_packages: Path,
    artifacts: list[dict],
    python_archive: Path,
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

    payload = {
        "bundle": f"GannetNVR-{version}-win64",
        "version": version,
        "python": {
            "version": PYTHON_EMBED_VERSION,
            "source": PYTHON_EMBED_URL.format(v=PYTHON_EMBED_VERSION),
            "sha256": sha256_file(python_archive),
        },
        "runtime_artifacts": artifacts,
        "python_distributions": distributions,
        "notes": [
            "Licenses for every Python and npm dependency are in THIRD_PARTY.md.",
            "Source locations for the redistributed binaries are in SOURCE-OFFER.txt.",
            "This bundle contains no machine-specific data; the first launch "
            "creates %LOCALAPPDATA%\\Frigate.",
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def source_offer(artifacts: list[dict]) -> str:
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
        "",
        "Python packages: each wheel in python/Lib/site-packages is unmodified.",
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
    version: str, bundle_name: str, digest: str, artifacts: list[dict]
) -> str:
    rows = "\n".join(
        f"| {item['name']} | {item['version']} | {item['license']} |"
        for item in artifacts
    )
    return f"""# Gannet NVR {version} for Windows x64

Self-contained portable bundle. No Python install, no administrator rights, no
network access required.

## Install

1. Extract `{bundle_name}.zip` anywhere writable, for example
   `%LOCALAPPDATA%\\Programs\\GannetNVR`.
2. Run `run_gannet.ps1` (or double-click `run_gannet.cmd`).
3. Open <http://localhost:8971>. The generated administrator password is in the
   log on first start.

Data lives in `%LOCALAPPDATA%\\Frigate`. Pass `-BaseDir <path>` to keep it
somewhere else. To remove the application, stop it and delete the folder.

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
        default=str(DIST),
        help="where the ZIP and checksums are written (default: dist/)",
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
    output_dir = Path(args.output_dir).resolve()
    staging = output_dir / ".staging" / f"GannetNVR-{version}-win64"
    bundle_name = staging.name
    requirements = Path(args.requirements).resolve()

    if not requirements.is_file():
        raise BuildError(f"requirements file not found: {requirements}")

    log.info("Gannet NVR %s portable bundle", version)
    log.info("  staging: %s", staging)
    log.info("  CPython: %s embeddable amd64", PYTHON_EMBED_VERSION)
    log.info("  requirements: %s", requirements)
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

    artifacts = [] if args.skip_artifacts else stage_artifacts(app_dir)

    (staging / LAUNCHER_NAME).write_text(launcher_script(), encoding="utf-8")
    (staging / SHIM_NAME).write_text(cmd_shim(), encoding="utf-8")

    log.info("Checking the staged layout")
    verify_layout(staging, not args.skip_wheels, not args.skip_artifacts)

    (staging / "BUILD-INFO.json").write_text(
        build_info(version, site_packages, artifacts, python_archive), encoding="utf-8"
    )
    (staging / "SOURCE-OFFER.txt").write_text(source_offer(artifacts), encoding="utf-8")

    log.info("Writing the archive")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{bundle_name}.zip"
    write_deterministic_zip(staging, archive)
    digest = sha256_file(archive)
    size_mb = archive.stat().st_size / (1024 * 1024)

    (archive.with_suffix(".zip.sha256")).write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )
    (output_dir / "RELEASE-NOTES.md").write_text(
        release_notes(version, bundle_name, digest, artifacts), encoding="utf-8"
    )

    if WINGET_TEMPLATE.is_file():
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
        shutil.rmtree(staging.parent if staging.parent.name == ".staging" else staging)

    log.info("")
    log.info("Built %s (%.1f MiB)", archive, size_mb)
    log.info("  sha256 %s", digest)
    log.info(
        "  %s",
        "Extract and run run_gannet.ps1 on a Windows x64 host to verify it starts",
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BuildError as error:
        log.error("build failed: %s", error)
        sys.exit(1)
