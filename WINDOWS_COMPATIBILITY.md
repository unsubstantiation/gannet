# Native Windows Architecture

Frigate in this repository is a Windows-only application. It requires 64-bit
CPython 3.12 and runs directly on Windows; there is no alternate container,
WSL, POSIX, or Unix-service runtime.

## Runtime contract

- `frigate.__main__` rejects every platform other than Windows before runtime
  initialization.
- Multiprocessing always uses `spawn`.
- Writable data defaults to `%LOCALAPPDATA%\Frigate`. `FRIGATE_BASE_DIR`,
  `FRIGATE_CONFIG_DIR`, `FRIGATE_MEDIA_DIR`, `FRIGATE_CACHE_DIR`, and
  `FRIGATE_TMP_DIR` can relocate it, including to another drive.
- Executables are native `.exe` files. The bootstrap installs pinned FFmpeg
  8.1.2 and go2rtc 1.9.14 builds and verifies their SHA-256 digests.
- Named shared-memory mappings, loopback TCP IPC, Windows process groups,
  priority classes, service events, and a kill-on-close Job Object replace
  Unix-specific process facilities.
- Files inherit Windows ACLs. There is no UID/GID ownership layer.

`frigate/util/platform.py` is the central implementation of these rules. It is
kept independent of the rest of the package because `frigate.const` imports it
during early initialization.

## Web and service topology

`frigate/api/web.py` owns HTTP serving. The default listeners are:

- `0.0.0.0:8971`: authenticated UI, API, media, VOD, and live proxy traffic.
- `127.0.0.1:5000`: trusted internal media requests from Frigate's own jobs.

The two ports must be distinct. Authentication is evaluated in process and
caller-supplied identity headers are removed before requests enter the API.
Proxy identity mappings require a configured shared secret. Client-address
forwarding is accepted only when the direct peer belongs to a configured
trusted network.

Frigate launches and stops `go2rtc.exe` as a child. FFmpeg and other descendants
are attached to a Windows Job Object so they cannot outlive Frigate. The
optional SCM wrapper in `frigate/util/windows_service.py` uses the same runtime
and pins the child working directory to the source/install root.

## Supported hardware

Object detection is intentionally limited to backends with native Windows
runtimes:

- CPU TensorFlow Lite
- ONNX Runtime (CPU or DirectML)
- OpenVINO (CPU, Intel GPU, or Intel NPU)
- ZMQ remote inference

Video acceleration presets cover D3D11VA, DXVA2, Intel QSV, NVIDIA CUDA/NVENC,
AMD AMF, Vulkan, and software fallback. Hardware statistics use `psutil` and,
when installed and enabled, NVIDIA NVML.

Accelerators that require Unix device nodes or vendor Linux SDKs are not part
of the codebase or configuration schema.

## Installation and validation

Run from 64-bit CPython 3.12 on Windows:

```powershell
py -3.12 bootstrap_windows.py
.\run_frigate.ps1
```

Add `--install-service` from an elevated PowerShell session to register the SCM
service. See `docs/docs/frigate/installation.md` for paths, environment
overrides, service commands, upgrades, and uninstall steps.

Repository checks are:

```powershell
ruff format --check bootstrap_windows.py frigate migrations testing-scripts
ruff check bootstrap_windows.py frigate migrations testing-scripts
python -m compileall -q bootstrap_windows.py frigate migrations testing-scripts
python testing-scripts/check_windows_requirements.py
python testing-scripts/run_windows_unit_suite.py
cd web
npm ci
npm run lint
npm run build:native
```

PowerShell and real-device validation must run on Windows. Linux/container test
results are not accepted as evidence for this runtime.

These checks also run automatically in the `Windows Python` and `Windows Web`
GitHub Actions workflows on every pull request and push to `dev`.

## Port audit

What the conversion from the Linux image to a native Windows application
changed, how the result is verified, and what is deliberately still open.

### What changed

| Area | Before | Now |
| --- | --- | --- |
| Process model | An image with nginx, supervisord and a Frigate container | One process; `frigate/api/web.py` serves the UI, the API, media and live streams |
| Multiprocessing | `fork` | `spawn` (`frigate.util.platform.get_mp_start_method`) |
| Writable paths | `/config`, `/media`, `/cache` | `%LOCALAPPDATA%\Frigate`, relocatable with `FRIGATE_*_DIR` |
| Executables | `ffmpeg` and `go2rtc` on `PATH` | `ffmpeg.exe` and `go2rtc.exe` installed by `bootstrap_windows.py` with verified SHA-256 digests |
| Local IPC | Unix domain sockets and FIFOs | Loopback TCP (`frigate.util.platform.ipc_endpoint`) and named shared memory |
| Child lifetime | The supervisor reaped orphans | A kill-on-close Job Object (`frigate/util/job_object.py`) |
| Shutdown | `SIGTERM` | Console control events, plus a named event for the SCM service |
| Ownership | UID, GID and `chown` | Windows ACLs inherited from the parent directory |
| Detectors | Coral, Hailo, TensorRT, RKNN and other appliance SDKs | CPU TFLite, ONNX Runtime (CPU or DirectML), OpenVINO (CPU, GPU or NPU) and ZMQ |
| Acceleration | VAAPI, DRM, V4L2, RKMPP, Jetson and VideoToolbox | D3D11VA, DXVA2, Intel QSV, NVIDIA NVENC and CUDA, AMD AMF, Vulkan and software |
| Storage statistics | A `/dev/shm` quota and a root check | Page-file backed shared memory and the Win32 APIs |

### What is verified

The repository checks above run on a Windows x64 host for every pull request.
The unit suite is the main gate: `frigate/test/windows_suite_denylist.txt` is
empty, so no test is known to be unable to run on Windows, and a test that
fails there fails the build. The platform behaviour itself is covered by
`frigate/test/test_platform_windows.py`, `test_windows_service.py`,
`test_job_object.py`, `test_go2rtc_windows.py` and `test_native_e2e.py`.

### What is still open

- The Windows installer is not published, so the winget manifest stays a
  template (see below).
- PowerShell, SCM and Win32 process behaviour can only be validated on a
  Windows x64 host; results from another operating system are not evidence.
- The hardware presets need the matching device: QSV, NVENC and AMF are
  verified by configuration and by the presets themselves, not on every
  vendor's silicon.

## Release limitation

`winget-manifest/Frigate.FrigateWindows.yaml` remains a template until a signed
Windows installer is published. The bootstrap and source launcher are the
supported installation path in the meantime.
