# Agent and contributor guide

Gannet supports native Windows x64 and native Debian 13 x86-64, both with
CPython 3.12 and spawn multiprocessing. Containers, WSL, ARM, other Linux
distributions and system Python 3.13 are not supported runtime targets.
See [WINDOWS_COMPATIBILITY.md](WINDOWS_COMPATIBILITY.md) for the Windows contract,
[DEBIAN.md](DEBIAN.md) for native systemd installation, and
[CONTRIBUTING.md](CONTRIBUTING.md) for review rules.

## Runtime contract

- `gannet.__main__` calls `require_supported_platform` before initialization.
- Multiprocessing always uses `spawn`; IPC remains loopback TCP on both targets.
- Windows keeps native `.exe` discovery, PowerShell/SCM, DPAPI, Job Objects,
  Windows quoting, priority classes and `%LOCALAPPDATA%\Gannet` defaults.
  Do not introduce a POSIX dependency into Windows execution paths.
- Debian uses native binaries, POSIX argument quoting, SIGTERM shutdown,
  XDG defaults for foreground use, and dedicated systemd state/config/cache
  directories. CPU, CUDA/NVENC, native Intel QSV and Intel/AMD VAAPI paths are
  available with matching drivers and service render/video permissions. Never
  select Windows device APIs on Debian. Auto decode requires a successful go2rtc
  runtime probe, otherwise use CPU. See DEBIAN.md for remaining parity limits.
- Platform/process behavior goes through `gannet/util/platform.py` and adapters.
  Keep platform.py independent of other Gannet modules for early startup.
- The Debian app runs unprivileged. Managed WireGuard uses a narrowly scoped,
  root-owned isolated helper, never a root NVR or broad sudo/shell permissions.
  Preserve hook/DNS/default-route rejection and metadata-only secret APIs on both
  backends. Debian uses systemd host-key encrypted credentials, with plaintext
  available only in the root tunnel unit's runtime credential directory; keep
  host keys root-only and preserve legacy IDs during migration. Windows keeps
  DPAPI and ACLs.
- The public listener (`0.0.0.0:8971`) is authenticated; the internal listener
  (`127.0.0.1:5000`) is loopback-only and trusted. Never trust client identity headers.
- Windows retains CPU TensorFlow Lite, ONNX Runtime CPU/DirectML/CUDA/Windows ML,
  OpenVINO and ZMQ. Preserve existing Windows wheels and ML-provider behavior.

## Licensing rules an agent must follow

This repository is source-available and non-commercial, not open source; the
boundaries are in [LICENSING.md](LICENSING.md). Concretely:

- Do not add or remove copyright lines, and do not touch `LICENSE`,
  `LICENSES/MIT.txt`, `TRADEMARK.md`, or `REUSE.toml` by hand. `REUSE.toml` is
  generated (`scripts/generate_reuse_toml.py`), and `LICENSES/MIT.txt` is upstream Frigate's
  notice, which the MIT License requires to stay intact and unmodified.
- New files must carry `SPDX-License-Identifier: LicenseRef-GNCL-1.0` in a file-header
  comment. Upstream Frigate-authored files keep their existing identifiers; a mixed file is
  `MIT AND LicenseRef-GNCL-1.0` and is recorded in `REUSE.toml`, not in the header.
- Do not copy code from AGPL or GPL-licensed projects into this tree. It cannot be
  relabeled as Gannet Material, and the resulting terms are unmanageable here.
- Never propose replacing these terms with MIT or Apache on the Gannet Material, and
  never propose adding a noncommercial or field-of-use restriction to the Upstream
  Material — the first is the point of the license, the second is not ours to do.
- `gannet/test/test_licensing.py` fails when any of the above is violated.

## Required checks

From the repository root, on Windows:

```powershell
ruff format bootstrap_windows.py gannet migrations testing-scripts
ruff check bootstrap_windows.py gannet migrations testing-scripts
python -m compileall -q bootstrap_windows.py gannet migrations testing-scripts
python testing-scripts/check_windows_requirements.py
python testing-scripts/run_windows_unit_suite.py
```

PowerShell, SCM, Win32 process behavior, and the downloaded Windows
executables can only be validated on a Windows x64 host; results from other
operating systems are not evidence for this runtime. Tests that cannot pass
on Windows belong in `gannet/test/windows_suite_denylist.txt` with a
concrete reason, and the list is expected to shrink, never grow silently.

For Debian checks and target-machine acceptance tests, follow [DEBIAN.md](DEBIAN.md).
Cross-platform mocked tests are not evidence of native SCM, systemd, VPN routing,
GPU or live-camera behavior. New Debian files also require formatting/linting.

Regenerate derived artifacts when their sources change:

- API auth spec: `python generate_api_auth_spec.py` (verify with `--check`)
- Config translations: `python generate_config_translations.py`

## Web frontend

From `web`:

```powershell
npm ci
npm run lint
npm run build:native
```

- `npm run build` builds with the `/BASE_PATH/` placeholder; the native server
  serves `npm run build:native` output from `/`. The native build is what
  ships.
- All user-facing strings go through `react-i18next`. English strings live
  in `public/locales/en/`, organized by namespace; never hardcode display
  text in a component. Extract keys with `npm run i18n:extract`.
- UI primitives are Radix UI/shadcn components in `src/components/ui/`,
  styled with TailwindCSS and the `cn()` helper.
- TypeScript runs in strict mode; avoid `any`.
- `npm run build` output and `web/dist` are generated. Do not hand-edit
  generated files, Playwright outputs, or locale files beyond adding the
  English source strings for new keys.

## Pull requests

Open pull requests against `dev`. Keep each pull request focused and
describe the behavior, the tests run, and any hardware used for validation.
Every pull request must be read and submitted by a person; disclose AI
assistance in the pull request description.
