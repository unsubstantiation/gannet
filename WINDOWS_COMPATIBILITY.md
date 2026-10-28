# Native Windows Architecture

Gannet in this repository is a Windows-only application. It requires 64-bit
CPython 3.12 and runs directly on Windows; there is no alternate container,
WSL, POSIX, or Unix-service runtime.

## Runtime contract

- `gannet.__main__` rejects every platform other than Windows before runtime
  initialization.
- Multiprocessing always uses `spawn`.
- Writable data defaults to `%LOCALAPPDATA%\Gannet`. `GANNET_BASE_DIR`,
  `GANNET_CONFIG_DIR`, `GANNET_MEDIA_DIR`, `GANNET_CACHE_DIR`, and
  `GANNET_TMP_DIR` can relocate it, including to another drive.
- Executables are native `.exe` files. The bootstrap installs pinned FFmpeg
  8.1.2 and go2rtc 1.9.14 builds and verifies their SHA-256 digests.
- Named shared-memory mappings, loopback TCP IPC, Windows process groups,
  priority classes, service events, and a kill-on-close Job Object replace
  Unix-specific process facilities.
- Files inherit Windows ACLs. There is no UID/GID ownership layer.

`gannet/util/platform.py` is the central implementation of these rules. It is
kept independent of the rest of the package because `gannet.const` imports it
during early initialization.

## Web and service topology

`gannet/api/web.py` owns HTTP serving. The default listeners are:

- `0.0.0.0:8971`: authenticated UI, API, media, VOD, and live proxy traffic.
- `127.0.0.1:5000`: trusted internal media requests from Gannet's own jobs.

The two ports must be distinct. Authentication is evaluated in process and
caller-supplied identity headers are removed before requests enter the API.
Proxy identity mappings require a configured shared secret. Client-address
forwarding is accepted only when the direct peer belongs to a configured
trusted network.

Media is authorised per camera for roles with a camera allow-list. The check
in `gannet/api/media_auth.py` classifies `/clips`, `/recordings`, `/exports`
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

Gannet launches and stops `go2rtc.exe` as a child. FFmpeg and other descendants
are attached to a Windows Job Object so they cannot outlive Gannet. The
optional SCM wrapper in `gannet/util/windows_service.py` uses the same runtime
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
go2rtc could open, and the `preset-windows-*` families Gannet recommends.
`/api/nvinfo` still returns NVML driver details when an NVIDIA adapter is
polled.

Accelerators that require Unix device nodes or vendor Linux SDKs are not part
of the codebase or configuration schema.

## Installation and validation

Run from 64-bit CPython 3.12 on Windows:

```powershell
py -3.12 bootstrap_windows.py
.\run_gannet.ps1
```

Add `--install-service` from an elevated PowerShell session to register the SCM
service. See `docs/docs/frigate/installation.md` for paths, environment
overrides, service commands, upgrades, and uninstall steps.

Repository checks are (`check_windows_requirements.py` resolves every pin
against PyPI for Windows CPython 3.12 and also verifies the pins against each
other's declared dependency bounds, so a pin that pip could never install
alongside the others fails locally before deployment):

```powershell
ruff format --check bootstrap_windows.py gannet migrations testing-scripts
ruff check bootstrap_windows.py gannet migrations testing-scripts
python -m compileall -q bootstrap_windows.py gannet migrations testing-scripts
python testing-scripts/check_windows_requirements.py
python testing-scripts/run_windows_unit_suite.py
cd web
npm ci
npm run lint
npm run build:native
```

PowerShell and real-device validation must run on Windows. Linux/container test
results are not accepted as evidence for this runtime.

## Port audit

What the conversion from the Linux image to a native Windows application
changed, how the result is verified, and what is deliberately still open.

### What changed

| Area | Before | Now |
| --- | --- | --- |
| Process model | An image with nginx, supervisord and a Gannet container | One process; `gannet/api/web.py` serves the UI, the API, media and live streams |
| Multiprocessing | `fork` | `spawn` (`gannet.util.platform.get_mp_start_method`) |
| Writable paths | `/config`, `/media`, `/cache` | `%LOCALAPPDATA%\Gannet`, relocatable with `GANNET_*_DIR` (legacy `FRIGATE_*_DIR` aliases still work) |
| Executables | `ffmpeg` and `go2rtc` on `PATH` | `ffmpeg.exe` and `go2rtc.exe` installed by `bootstrap_windows.py` with verified SHA-256 digests |
| Local IPC | Unix domain sockets and FIFOs | Loopback TCP (`gannet.util.platform.ipc_endpoint`) and named shared memory |
| Child lifetime | The supervisor reaped orphans | A kill-on-close Job Object (`gannet/util/job_object.py`) |
| Shutdown | `SIGTERM` | Console control events, plus a named event for the SCM service |
| Ownership | UID, GID and `chown` | Windows ACLs inherited from the parent directory |
| Text files | Locale default encoding (UTF-8 on the image) | Explicit UTF-8 for the config, go2rtc config, state files, labelmaps and logs; the launcher and service set `PYTHONUTF8=1` |
| File removal | `rm -rf` semantics | `gannet.util.file.robust_remove`/`robust_move`/`robust_rmdir`/`robust_rmtree`, which clear the read-only attribute and retry sharing violations |
| Detectors | Coral, Hailo, TensorRT, RKNN and other appliance SDKs | CPU TFLite, ONNX Runtime (CPU or DirectML), OpenVINO (CPU, GPU or NPU) and ZMQ |
| Acceleration | VAAPI, DRM, V4L2, RKMPP, Jetson and VideoToolbox | D3D11VA, DXVA2, Intel QSV, NVIDIA NVENC and CUDA, AMD AMF, Vulkan and software |
| Storage statistics | A `/dev/shm` quota and a root check | Page-file backed shared memory and the Win32 APIs |
| GPU diagnostics | `vainfo` (libva) via `/api/vainfo` | `/api/gpuinfo`: display adapters, `ffmpeg -hwaccels`, go2rtc accelerators and the recommended `preset-windows-*` family |
| Bandwidth statistics | `nethogs` (root, `CAP_NET_ADMIN`/`CAP_NET_RAW`) | A real-time ETW kernel-logger session (`gannet/util/bandwidth.py`); the `telemetry.stats.network_bandwidth` collector reports the bytes each camera `ffmpeg.exe` and `go2rtc.exe` moves, so it needs an elevated Gannet process and is off by default |

### What is verified

The repository checks above run on a Windows x64 host for every pull request.
The unit suite is the main gate: `gannet/test/windows_suite_denylist.txt` is
empty, so no test is known to be unable to run on Windows, and a test that
fails there fails the build. The platform behaviour itself is covered by
`gannet/test/test_platform_windows.py`, `test_windows_service.py`,
`test_job_object.py`, `test_go2rtc_windows.py`, `test_native_e2e.py`,
`test_windows_gpu_info.py`, `test_file.py` (read-only and held-file removal)
and `http_api/test_http_config_encoding.py` (UTF-8 config round trips).

### Feature parity with upstream

This fork tracks [blakeblackshear/frigate](https://github.com/blakeblackshear/frigate)
feature for feature. The port is audited against upstream `dev` at `91e91c68`
(2026-10-21); the licensing map in `REUSE.toml` pins the merge point at
`5bb2cde8`. Five surfaces are compared: the Python modules and their
functions and classes, the API routes, the configuration schema, and the web
application (files and English locale keys). `gannet/models.py` and
`gannet/api/defs` are byte-identical to upstream. Every difference is either
the same feature with a Windows implementation or one of the exclusions
below; there is no dropped product feature.

Re-run the audit against any upstream checkout after every merge:

```powershell
git clone --depth 1 --branch dev https://github.com/blakeblackshear/frigate C:\src\frigate
python testing-scripts/check_upstream_parity.py --upstream-dir C:\src\frigate
```

The tool fails when upstream grows a surface the fork does not carry and no
exclusion covers, and reports exclusions that no longer match anything so the
list shrinks instead of rotting. Every exclusion is a pattern with a written
reason in the tool itself.

| Upstream feature not carried | Why | What the fork does instead |
| --- | --- | --- |
| Detector plugins for Coral/Edge TPU, TensorRT (TF-TRT), Hailo, RKNN, DeepX, Axelera, AxEngine, MemryX, Synaptics and Teflon | Unix device nodes and vendor Linux SDKs with no maintained native Windows runtime | `cpu` TFLite, `onnx` (DirectML, CUDA, Windows ML catalog), `openvino`, `zmq` |
| Detector runtime auto-installer (`ensure_dependencies`, `util/runtime_deps.py`) | Installs those Linux SDKs at startup | `bootstrap_windows.py` installs the supported Windows runtimes |
| Async detector API (`AsyncDetectorRunner`) | Its only implementers are the Axelera and MemryX Linux plugins | The synchronous `DetectorRunner` serves every supported backend |
| libva diagnostics and GPU selection (`vainfo`, `LibvaGpuSelector`) | libva/DRM | `/api/gpuinfo` and the `preset-windows-*` families |
| AMD, Intel, Jetson, Rockchip and Raspberry Pi GPU/NPU statistics and thermal-zone temperatures | DRM fdinfo, sysfs, tegrastats | NVML for NVIDIA; panes without a counter are hidden rather than filled with invented numbers |
| The `/dev/shm` sizing notice | Windows frame memory is page-file backed and has no shm quota | `stats.service.storage` reports the page file |
| UID/GID ownership, POSIX shm `unlink`, `os.register_at_fork`, memray, SIGUSR1 stack dumps | POSIX-only facilities | ACLs, named mappings, spawn-only multiprocessing |
| Docker secrets (`CREDENTIALS_DIRECTORY`), the `/run/secrets` JWT lookup and the Home Assistant add-on `/data/options.json` | Container facilities; the native build reads the process environment, `secrets.yaml` and `environment_vars` only | The same three sources, enforced by `gannet/test/test_env.py` |
| nethogs bandwidth accounting | Needs root and `CAP_NET_ADMIN`/`CAP_NET_RAW` | The ETW kernel-logger collector (elevated Gannet process) |
| `RemoteUserPlugin` | Defined upstream but never registered or read there | Proxy identity uses `proxy_config.header_map` with the shared-secret check |

### Upstream feature-parity audit (2026-10-22)

Compared this checkout (`830b1bc`, Gannet 0.19.0) with upstream `dev`
(`91e91c68`, 2026-10-20; `Add Axelera Metis NPU detector plugin v.0.19`). The
comparison is by behavior and feature surface, not a blind tree merge: this
checkout is the native Windows runtime, and large source diffs include
intentional Windows substitutions (paths, process/service management, FFmpeg,
GPU reporting, and packaging). The check covered the upstream feature/test
surfaces in `gannet/`, `web/src/`, and the compatibility exclusions above.

| Upstream capability/change | Audit result | Windows disposition |
| --- | --- | --- |
| Login-session revocation, cross-origin websocket protection, media-auth path normalization | Present in native auth/API/websocket code and covered by Windows-side tests (`test_http_auth_jwt_role`, `test_ws_origin`, `test_media_auth`) | Portable; retained with native listener and proxy handling |
| Camera credential redaction in config responses and safe config updates | Present in `gannet/api/app.py`, frontend credential masking, and config/API tests | Portable; retained, with raw-path handling adapted to the native server |
| Web-push registration/send hardening and malformed-subscription handling | Present in `gannet/comms/webpush.py` and `test_webpush_registration.py` | Portable; retained |
| Same-origin-only chat images | Present in `web/src/components/chat/ChatMessage.tsx` | Portable; retained |
| Motion-search concurrency/resource limits | Present in `gannet/jobs/motion_search.py` and `gannet/api/motion_search.py` | Portable; retained |
| Avoid buffering raw FFmpeg frames on watchdog reset | Present in `gannet/video/ffmpeg.py`; reset waits while the capture reader drains stdout | Portable; retained for the Windows process wrapper |
| Autotracking tracker rebuild/selection and cropped histogram work | Present in `gannet/track/norfair_tracker.py` and `gannet/util/image.py` | Portable; retained |
| Newer UI and application flows (auto-live, GenAI audio transcription, live/review/search/export, camera setup and settings) | Present in the corresponding frontend/backend components and config models | Portable; retained; no missing feature confirmed in this audit |
| Axelera Metis detector plugin | Upstream-only plugin and tests; no supported native Windows driver/runtime is provided by this fork | Not ported; existing detector exclusion remains appropriate |
| Docker/container startup, Nginx cache/proxy configuration, Linux device plugins and Linux-only metrics | Runtime-specific, not application features transferable to the native process | Not applicable; native HTTP/media server, Windows process/service, and hardware stats are used instead |

**Outcome:** the reviewed portable upstream behaviors are already present in
this checkout; the identified differences are covered by the explicit Windows
exclusions or native replacements above. No safe, confirmed portable feature
gap was found in this comparison, so no runtime code was changed. The audit
found no basis for claiming bit-for-bit or exhaustive parity with all upstream
platforms: upstream `dev` continues to move, and new hardware backends require
a maintained Windows runtime plus hardware validation before they can be
classified as portable. Re-run this comparison against the then-current
upstream `dev` before each parity claim.

### What is still open

- The Windows installer is not published, so the winget manifest stays a
  template (see below).
- PowerShell, SCM and Win32 process behaviour can only be validated on a
  Windows x64 host; results from another operating system are not evidence.
- The hardware presets need the matching device: QSV, NVENC and AMF are
  verified by configuration and by the presets themselves, not on every
  vendor's silicon.
- The bandwidth collector opens the NT Kernel Logger session, so it runs
  only when Gannet is elevated and reports nothing (with one warning)
  otherwise, exactly as upstream reports nothing when it is not root. The
  ETW parsing is covered by unit tests and the MOF layouts are pinned by
  structure-layout tests, but the live capture was not exercised on every
  network adapter; a non-elevated run degrades to no stat rather than an
  error.
- Only NVIDIA adapters report usage counters. `stats.gpu_usages` can therefore
  only ever carry entries polled through NVML; there is no utilization counter
  for an Intel or AMD GPU, or for an Intel NPU, in the Windows runtimes Gannet
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
process and manifest in the same change, or `winget validate` fails on a
404.

The bootstrap and source launcher are the supported installation path in the
meantime.
