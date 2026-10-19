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

Media is authorised per camera for roles with a camera allow-list. The check
in `frigate/api/media_auth.py` classifies `/clips`, `/recordings`, `/exports`
and the native `/vod` playlist and segment routes, so a restricted viewer can
only play back the cameras their role names. The cache directory is never
served over HTTP: it holds in-progress segments and preview frames for every
camera, and nothing in the web app reads it.

The gateway runs the mounted FastAPI application's lifespan inside its own, so
startup work FastAPI declares (such as the debug replay auto-stop watchdog)
runs on the native install exactly as it does when FastAPI is served directly.
Only the public listener runs the lifespan; the loopback listener shares the
same application state.

When `tls.enabled` is set and no certificate is configured, the gateway
generates a self-signed pair and renews it itself once it is within 30 days of
expiry. A certificate an administrator installed is never replaced.

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

The System page's "Hardware Info" button calls `/api/gpuinfo`, the native
replacement for the Linux `vainfo` output. It reports the active display
adapters (Win32 `EnumDisplayDevices`), the processor, the acceleration methods
compiled into the installed `ffmpeg.exe` (`ffmpeg -hwaccels`), the accelerators
go2rtc could open, and the `preset-windows-*` families Frigate recommends.
`/api/nvinfo` still returns NVML driver details when an NVIDIA adapter is
polled.

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

Repository checks are (`check_windows_requirements.py` resolves every pin
against PyPI for Windows CPython 3.12 and also verifies the pins against each
other's declared dependency bounds, so a pin that pip could never install
alongside the others fails locally rather than in the install step on CI):

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
| Text files | Locale default encoding (UTF-8 on the image) | Explicit UTF-8 for the config, go2rtc config, state files, labelmaps and logs; the launcher and service set `PYTHONUTF8=1` |
| File removal | `rm -rf` semantics | `frigate.util.file.robust_remove`/`robust_move`/`robust_rmdir`/`robust_rmtree`, which clear the read-only attribute and retry sharing violations |
| Detectors | Coral, Hailo, TensorRT, RKNN and other appliance SDKs | CPU TFLite, ONNX Runtime (CPU or DirectML), OpenVINO (CPU, GPU or NPU) and ZMQ |
| Acceleration | VAAPI, DRM, V4L2, RKMPP, Jetson and VideoToolbox | D3D11VA, DXVA2, Intel QSV, NVIDIA NVENC and CUDA, AMD AMF, Vulkan and software |
| Storage statistics | A `/dev/shm` quota and a root check | Page-file backed shared memory and the Win32 APIs |
| GPU diagnostics | `vainfo` (libva) via `/api/vainfo` | `/api/gpuinfo`: display adapters, `ffmpeg -hwaccels`, go2rtc accelerators and the recommended `preset-windows-*` family |

### What is verified

The repository checks above run on a Windows x64 host for every pull request.
The unit suite is the main gate: `frigate/test/windows_suite_denylist.txt` is
empty, so no test is known to be unable to run on Windows, and a test that
fails there fails the build. The platform behaviour itself is covered by
`frigate/test/test_platform_windows.py`, `test_windows_service.py`,
`test_job_object.py`, `test_go2rtc_windows.py`, `test_native_e2e.py`,
`test_windows_gpu_info.py`, `test_file.py` (read-only and held-file removal)
and `http_api/test_http_config_encoding.py` (UTF-8 config round trips).

### What is still open

- The Windows installer is not published, so the winget manifest stays a
  template (see below).
- PowerShell, SCM and Win32 process behaviour can only be validated on a
  Windows x64 host; results from another operating system are not evidence.
- The hardware presets need the matching device: QSV, NVENC and AMF are
  verified by configuration and by the presets themselves, not on every
  vendor's silicon.
- Only NVIDIA adapters report usage counters. `stats.gpu_usages` can therefore
  only ever carry entries polled through NVML; there is no utilization counter
  for an Intel or AMD GPU, or for an Intel NPU, in the Windows runtimes Frigate
  uses. For the same reason `npu_usages` and `detectors.temperature` are never
  emitted: the OpenVINO NPU is selectable and runs inference, but nothing
  reports how busy it is, and no detector exposes a thermometer. The System
  page treats both keys as optional and hides the panes that would show them,
  so this degrades rather than breaks. Reporting invented numbers was
  rejected; adding real counters means a Windows performance-counter or
  vendor-silicon implementation with hardware to test it against.
- The Playwright fixtures under `web/e2e/fixtures/mock-data` still describe a
  Linux install in places. `config-schema.json` and `config-snapshot.json` are
  generated artifacts: regenerate them on Windows with `generate-mock-data.py`,
  which embeds the host's data-layout paths and refreshes the wall-clock
  timestamps in the review and event fixtures. Regenerating on another
  operating system bakes that operating system's paths into a fixture that is
  meant to describe a Windows install.

## Release limitation

`winget-manifest/unsubstantiation.GannetNVR.yaml` remains a template until a
signed Windows installer is published from this fork's own releases. Two fields in
it are not formatting choices: `Publisher` is the person who maintains this fork,
because Frigate, Inc. does not publish it, and `License: GNCL-1.0 AND MIT` is what
the tree actually carries, so a submission that says otherwise would be a
misstatement to the registry as well as to users. The installer asset is still
named for upstream (`frigate-windows-installer.exe`); rename it in the release
workflow and the manifest in the same change, or `winget validate` fails on a
404.

The bootstrap and source launcher are the supported installation path in the
meantime.
