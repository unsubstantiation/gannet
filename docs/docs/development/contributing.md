---
id: contributing
title: Contributing
---

# Contributing on Windows

Gannet's supported development and runtime platform is 64-bit Windows with CPython 3.12. See the repository-root `CONTRIBUTING.md` for the authoritative setup and validation commands.

## Setup

Install:

- Git for Windows;
- 64-bit CPython 3.12 with the Python launcher;
- Node.js 22.12 or newer and npm;
- current GPU drivers when changing accelerated code;
- Visual Studio Build Tools only when a dependency must be compiled locally.

From PowerShell:

```powershell
git clone https://github.com/unsubstantiation/gannet.git
cd gannet
py -3.12 bootstrap_windows.py
.\.venv\Scripts\Activate.ps1
```

The bootstrap installs pinned native dependencies, verified FFmpeg/go2rtc binaries, and the verified detection/audio models. Do not introduce a dependency unless it supplies a CPython 3.12 `win_amd64` wheel or is pure Python.

## Local configuration

Set a separate writable data root before bootstrapping so dependencies and
models are installed in the same tree the development process will use:

```powershell
$env:GANNET_BASE_DIR = "$PWD\.devdata"
py -3.12 bootstrap_windows.py
.\run_gannet.ps1
```

Create `.devdata\config\config.yml` through the first-run UI or start with the minimal example in [Configuration](/configuration/config). Keep credentials in `.devdata\config\secrets.yaml`; never commit them.

A local sample can be looped with an absolute Windows path:

```yaml
cameras:
  test:
    ffmpeg:
      inputs:
        - path: 'C:\GannetSamples\camera.mp4'
          input_args: -re -stream_loop -1 -fflags +genpts
          roles: [detect]
```

## Backend validation

Run formatting, lint, compilation, and the focused tests for code you changed:

```powershell
ruff format --check bootstrap_windows.py gannet migrations testing-scripts
ruff check bootstrap_windows.py gannet migrations testing-scripts
python -m compileall -q bootstrap_windows.py gannet migrations testing-scripts
python testing-scripts/check_windows_requirements.py
python testing-scripts/run_windows_unit_suite.py
```

The suite runner reports known Windows exclusions from
`gannet/test/windows_suite_denylist.txt`; new failures must not be silently
excluded. Some tests that mock Win32 APIs can run on non-Windows hosts, but behavior that depends on the Service Control Manager, Job Objects, named events, DirectML, or Windows GPU drivers must also be exercised on Windows.

## Web application

```powershell
cd web
npm ci
npm run lint
npm run build:native
```

Its available validation commands are listed in `web/README.md`. Frontend browser requests must use relative URLs so the native gateway can route them. Do not add a browser-side dependency on `localhost`.

## Documentation

```powershell
cd docs
npm ci
npm run build
```

Keep examples Windows-native: PowerShell commands, drive-letter or UNC paths, Windows Firewall, and supported acceleration/detector names. Verify links after deleting or renaming a page.

## Pull requests

- Keep changes focused and include tests for bug fixes.
- Describe any manual Windows validation and hardware used.
- Do not restore removed service supervisors, Unix sockets, device-node discovery, or platform branches.
- Never commit camera credentials, JWT/proxy secrets, databases, recordings, downloaded models, or generated certificates.
- Update `WINDOWS_COMPATIBILITY.md` when changing a platform boundary.
