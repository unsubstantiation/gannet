<!-- SPDX-License-Identifier: LicenseRef-GNCL-1.0 -->
# Native Debian 13 installation

Target: **Debian 13 (trixie), x86-64, systemd, CPython 3.12**. This is a native
installation, not a container or WSL deployment. CPU is the default, with native
VAAPI, Quick Sync and CUDA/NVENC video paths and optional CUDA/OpenVINO inference.
Windows retains its existing bootstrap, portable bundle, acceleration providers
and SCM service. This is functional parity work, not a claim that all hardware
and Windows-specific capabilities have been certified on Debian.

## Install

Use a fresh Debian 13 x86-64 machine with systemd running, adequate recording
storage, and Internet access. Review the source revision before installing:
installation executes Python/npm dependency build scripts as root. The source,
venv, helper, and service unit must remain root-owned and not group/world writable.
Do not deploy untrusted plugins or dependencies in this installation.

```sh
sudo apt-get update
sudo apt-get install -y git
sudo git clone https://github.com/unsubstantiation/gannet.git /opt/gannet
cd /opt/gannet
# Select/review the release or source revision you intend to deploy first.
sudo bash scripts/install_debian.sh
```

The installer:

- Installs Debian FFmpeg/ffprobe, WireGuard tools, Node.js/npm and build tools.
- Keeps Debian's system Python 3.13 intact. A pinned uv bootstrap provisions a
  separate CPython 3.12 under `/opt/gannet/.python` and builds `.venv` from
  `requirements-debian.txt`. Python package pins are shared with Windows;
  `pywin32` is Windows-only and Debian uses headless OpenCV.
- Verifies the SHA-256 of go2rtc 1.9.14 Linux amd64 and the default CPU detection
  and audio models before installing them. Existing administrator-supplied
  models are preserved. Downloads require GitHub, PyPI and Google's model hosts.
- Builds the same native web frontend used by Windows.
- Creates a dedicated, non-login `gannet` account, installs the restricted
  WireGuard helper and sudo rule, validates configuration, and enables the service.
  The **NVR does not run as root and receives no CAP_NET_ADMIN capability**.

Installation is fail-fast, not transactional: a failed upgrade leaves Gannet
stopped. Correct the error and rerun. Existing configuration, media, and tunnel
secrets are not removed. The source tree must be at `/opt/gannet`; configurable
installation prefixes and ARM are not initial targets.

## Service and files

```sh
sudo systemctl status gannet
sudo journalctl -u gannet -f
sudo systemctl restart gannet
sudo systemctl stop gannet
```

| Path | Purpose |
| --- | --- |
| `/opt/gannet` | Root-owned code, Python, venv, go2rtc and frontend |
| `/etc/gannet` | Service-user configuration, database/model cache and HomeKit state |
| `/var/lib/gannet/media` | Recordings, clips and exports |
| `/var/cache/gannet` | Video/cache data |
| `/run/gannet` | Temporary files, child logs and restart marker; recreated by systemd |
| `/etc/wireguard/gannet` | Root-only saved tunnel metadata |
| `/etc/wireguard/gn*.conf` | Root-only managed WireGuard configurations with private keys |

Check configuration with the service's environment, not your login account's
XDG paths:

```sh
sudo -u gannet env GANNET_BASE_DIR=/var/lib/gannet \
  GANNET_CONFIG_DIR=/etc/gannet GANNET_CACHE_DIR=/var/cache/gannet \
  GANNET_TMP_DIR=/run/gannet PATH=/opt/gannet/bin:/usr/bin:/bin \
  /opt/gannet/.venv/bin/python -m gannet --validate-config
```

The public listener is authenticated on port **8971**. Inspect the local journal
for first-start administrator credentials; do not publish logs containing them.
Use TLS through a trusted reverse proxy for remote access. Port **5000** remains
loopback-only/trusted and must never be forwarded publicly. Restrict exposure of
RTSP/WebRTC ports to the clients that need them. There is no automatic firewall
reconfiguration.

`SIGTERM` requests coordinated shutdown. systemd gives the main process 120
seconds, then cleans up remaining children through its cgroup (`KillMode=mixed`).
`Restart=always` also handles clean-exit UI restart requests; an explicit
`systemctl stop` does not restart the service. Windows Job Objects and SCM stop
events remain unchanged. Both runtimes continue to use spawn and loopback TCP IPC.

For different recording storage, mount it at `/var/lib/gannet/media`, grant the
`gannet` account access, and ensure it is mounted before starting the service
(for example with a systemd `RequiresMountsFor=` drop-in). The service restricts
writes to its managed directories; an arbitrary alternative path also needs a
`ReadWritePaths=` drop-in. Do not relax source/helper ownership to fix data access.

## Managed camera WireGuard tunnels

Import and reuse saved tunnels through Settings and camera add/edit, just as on
Windows. Configurations must use split routes to camera networks. DNS, shell
hooks, default/broad routes and overlapping saved routes remain rejected.
Private keys are sent only on import and are never returned by the API.

Debian uses standard **root-owned mode-0600 WireGuard files**, not Windows DPAPI.
Protect backups and use disk encryption if protection against offline disk theft
is required. The service account cannot read these keys. Its only sudo grant is
`/usr/local/libexec/gannet-wireguard`, an isolated Python entry point with fixed
operations, validated 16-hex IDs, fixed paths and generated interface names under
Linux's 15-character limit. It revalidates stored configuration before starting
`wg-quick@gn….service`. The helper never accepts arbitrary commands, unit names,
paths, DNS settings or hooks. Do not add broad `sudo systemctl`/shell grants.

Check a tunnel with `sudo systemctl status wg-quick@<interface>.service`,
`sudo journalctl -u wg-quick@<interface>.service`, and `sudo wg show` locally.
Running service status is **not** evidence of a peer handshake or camera reachability.
Routes affect the host, not just one camera, and there is no per-camera kill
switch. Current/pending camera references block stop/delete through the API.
Detaching a camera or stopping Gannet does not tear down an active tunnel.
On boot Gannet restores tunnels referenced by enabled cameras before ONVIF/go2rtc;
unreferenced tunnels are not separately enabled for boot by the helper.

Windows DPAPI stores cannot be copied to Debian. Reimport the original configs
and remove/reassign old camera tunnel IDs before validating the migrated config.

## Upgrade, backup and removal

Stop Gannet before backing up its database and changing the reviewed source
revision. Back up `/etc/gannet`, `/var/lib/gannet`, and `/etc/wireguard` as root
(the latter contains unencrypted private keys). Rerun the installer after updating
the source. It replaces the venv/assets/service, preserves data, and restarts Gannet.
Keep a backup of the previous source/dependency environment for rollback.

Before removal, detach cameras and stop/delete managed tunnels in Settings if you
want their host routes removed. Disable Gannet with
`sudo systemctl disable --now gannet`. Remove its service, the helper and
`/etc/sudoers.d/gannet-wireguard` only after reviewing active `wg-quick` units.
Removing Gannet does not implicitly stop independently managed systemd tunnels or
wipe recordings, configuration, backups or private keys.

## Validation status and checks

Run on Debian 13 with the installed CPython 3.12:

```sh
python -m unittest gannet.test.test_debian gannet.test.test_wireguard \
  gannet.test.test_platform_windows gannet.test.test_ffmpeg_path_resolution \
  gannet.test.test_ffmpeg_presets gannet.test.test_go2rtc_windows \
  gannet.test.test_ffmpeg_stop gannet.test.test_main_process_manager \
  gannet.test.test_windows_hwaccel gannet.test.test_hwaccel_recommendation
bash -n scripts/install_debian.sh
sudo systemd-analyze verify /etc/systemd/system/gannet.service
```

The Debian CI job resolves/installs the shared pins on Debian 13/Python 3.12 and
runs these regression tests; it does not claim a booted-systemd or live-camera
integration test. Before production deployment, validate a full installation,
reboot, UI restart, graceful stop with recording children, an actual CPU camera,
and WireGuard import/start/handshake/reuse/stop/delete on the target machine.
Tests run on Debian 12/Python 3.11 are development checks, not target certification.
Docker, other distributions, ARM and the system Python 3.13 are outside this
Debian support target.


## Feature parity audit

The user-facing NVR is shared, not a separate reduced Debian frontend/backend.
The full offline unit suite exercises recording/retention, review/events, exports,
substreams, dynamic camera updates, ONVIF, restream configuration, birdseye,
auth/roles, MQTT, notifications, search/enrichment configuration and model runners.
That establishes code-path coverage, not a live-camera or GPU certification.

| Capability | Debian implementation / remaining qualification |
| --- | --- |
| NVR, camera management, review/playback, exports, retention | Shared implementation and complete unit suite; live target-machine acceptance still required |
| Audio, semantic search, face/LPR, transcription, GenAI, push/MQTT integrations | Shared workers/APIs, dependencies and model runners; provider credentials, model downloads and live integrations must be validated on deployment |
| TFLite CPU, ONNX CPU, ZMQ inference | Same native Python backends |
| NVIDIA inference | Optional exclusive ONNX Runtime CUDA profile; same runner and per-device selection; needs a compatible installed NVIDIA driver |
| Intel GPU/NPU inference | Existing native OpenVINO discovery/runner; devices appear only when the installed Intel driver exposes them to the service |
| NVIDIA decode/encode | `preset-nvidia`, CUDA scaling/download, NVENC birdseye/timelapse; previews retain the same CPU path as Windows |
| Intel decode/encode | `preset-intel-qsv-h264` / `preset-intel-qsv-h265`, Intel render-node selection, QSV scaling/download/encoding |
| Intel/AMD decode/encode | `preset-vaapi`, VAAPI scaling/download and birdseye/timelapse upload/encoding; preserve export speed/scale filters; complex graphs retain software fallback |
| Setup wizard/config/health | Native families and presets exposed and classified, not hidden or mislabeled as Windows |
| GPU telemetry | NVIDIA NVML is shared. Linux Intel/AMD gauges use driver sysfs counters when present; unavailable counters stay unknown, never fake zero. WMI-only engine/memory/NPU counters are not universally reproduced |
| Managed reusable WireGuard | Same camera association, reference protection and lifecycle API; restricted root helper/systemd instead of SCM. Live handshake/routing acceptance is outstanding |
| Secret storage | Debian root-only plaintext WireGuard files versus Windows DPAPI-encrypted files. Access control is implemented; cryptographic at-rest parity is **not** implemented. Encrypt the disk/backups as required |
| Background service, stop/restart and child cleanup | systemd cgroups/SIGTERM instead of SCM/Job Objects; booted target-host lifecycle acceptance is outstanding |
| Portable ZIP / Start Menu / Windows ML acquisition | Windows-specific distribution/integration, not present on Debian; Debian has the native installer/systemd workflow |
| DirectML / Windows ML vendor EPs (including AMD MIGraphX and Qualcomm QNN) | Windows-only here. No supported equivalent Debian provider is implemented for every vendor. Do not call this complete GPU-inference parity |

**Full platform parity is not yet certified.** In particular, AMD/Qualcomm vendor
inference coverage, cryptographic tunnel-store parity, all hardware usage counters
and target-host integration checks remain explicit gaps, not skipped successes.

### Native GPU setup

The installer adds `gannet` to existing `render` and `video` groups; it never makes
the whole NVR root or grants CAP_NET_ADMIN for graphics. Install matching firmware
and kernel/user-space drivers using the hardware vendor's Debian-compatible
instructions before selecting a preset. Intel OpenVINO GPU/NPU drivers are not
made available merely by installing the OpenVINO Python wheel. Check as the
service user, not just as root.

Use the default installer for CPU/OpenVINO and native video acceleration. For
NVIDIA ONNX inference:

```sh
sudo bash scripts/install_debian.sh --onnx-runtime cuda
```

This removes the CPU ONNX Runtime distribution before installing the pinned
`onnxruntime-gpu[cuda,cudnn]` alternative. Do not install multiple ORT distributions
in the same environment. Runtime CUDA libraries are preloaded from NVIDIA's pip
packages before creating Linux ONNX sessions; the kernel NVIDIA driver remains a
host prerequisite. As on the existing Windows alternative-runtime install, some
third-party metadata (notably faster-whisper) names the CPU `onnxruntime`
distribution even though the GPU distribution supplies the same Python module;
`pip check` can report that name missing in the CUDA profile. Do not "fix" that
by installing overlapping ORT distributions. CPU-profile dependency checks do not
certify CUDA-profile metadata or actual GPU execution.

Choose the native family in the setup wizard or configure a native preset.
`auto` chooses only a method go2rtc has successfully opened; before that probe is
available it safely stays on CPU. A PCI vendor ID or compiled FFmpeg method is
not proof that the service has working drivers or device access.

### Continuous parity regression gate

Both Windows x64 and Debian 13/CPython 3.12 CI jobs run the entire offline suite:

```sh
python testing-scripts/run_native_unit_suite.py
```

Only default model fetches are disabled by the outer test guard. Download tests
supply their own mocks and still exercise verification/error paths. The suite
has no new failure denylist. Native OS/driver tests keep explicit existing skips;
those skips are not evidence of feature validation. See target acceptance above.
