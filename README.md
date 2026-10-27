<p align="center">
  <img align="center" alt="Gannet NVR logo" src="web/images/branding/logo.png" width="420">
</p>

# Gannet NVR™ - Realtime Object Detection for IP Cameras

[![License: Source-available, non-commercial](https://img.shields.io/badge/License-Non--commercial-red.svg)](LICENSING.md)
[![Upstream Frigate code: MIT](https://img.shields.io/badge/Upstream_Frigate_code-MIT-yellow.svg)](LICENSES/MIT.txt)

\[English\] | [简体中文](README_CN.md)

A complete and local NVR designed for [Home Assistant](https://www.home-assistant.io) with AI object detection, running realtime detection locally for IP cameras.

Use of a GPU or AI accelerator is highly recommended: accelerators outperform even the best CPUs with very little overhead. See the supported [object detectors](https://docs.frigate.video/configuration/object_detectors/).

- Tight integration with Home Assistant via a [custom component](https://github.com/blakeblackshear/frigate-hass-integration)
- Only looks for objects when and where it is necessary, to minimize resource use
- Multiprocessing design that favors realtime over processing every frame
- Low overhead motion detection decides where object detection runs
- Detection runs in separate processes for maximum FPS
- MQTT for integration into other systems
- Recording with retention based on detected objects, plus 24/7 recording
- Re-streaming via RTSP to reduce the number of connections to your camera
- WebRTC and MSE for low-latency live view

## Native Windows application

This distribution is designed exclusively for native 64-bit Windows. Gannet runs as a normal Windows process or SCM service; container, WSL, and Unix runtime paths are not supported. Gannet itself serves the API, media endpoints, and web interface.

Install from an ordinary PowerShell window:

```powershell
git clone https://github.com/unsubstantiation/gannet.git
cd gannet
py -3.12 bootstrap_windows.py
powershell -ExecutionPolicy Bypass -File .\run_frigate.ps1
```

The bootstrap script needs 64-bit CPython 3.12. It creates the venv, installs the Windows requirements, fetches pinned FFmpeg and go2rtc builds plus the detection and audio models, builds the web interface when Node.js is available, and writes a launcher that restarts Gannet when Gannet asks to be restarted. Node.js is only needed for that frontend build; a packaged bundle can ship `web/dist` prebuilt.

To produce that bundle — one self-contained ZIP with CPython, every dependency, FFmpeg,
go2rtc, the models, and a double-clickable `GannetNVR.exe` entry point — see
[BUILD.md](BUILD.md). The ZIP needs nothing installed on the target machine; no
`setup.exe` is involved.

Windows-specific behaviour:

- Inference: CPU (TFLite and ONNX Runtime), Intel GPU/NPU through OpenVINO, and selectable ONNX Runtime DirectML, CUDA, or Windows ML catalog providers. DirectML is installed by default; bootstrap profiles are `--directml`, `--cuda`, `--windows-ml`, and `--no-directml` (CPU). CUDA targets NVIDIA and installs the official CUDA 13/cuDNN 9 runtime extras. Windows ML vendor providers (including MIGraphX, TensorRT-RTX, OpenVINO, QNN, and Vitis AI when the catalog reports them compatible) are installed explicitly with `python scripts/manage_windows_ml.py`; see the [acceleration guide](docs/docs/configuration/hardware_acceleration_enrichments.md). The Windows ML profile uses the ONNX Runtime version pinned by Microsoft's `windowsml` package; do not mix runtime profiles in one environment. Provider, model, driver, and hardware support varies. Coral, Hailo and accelerators requiring Linux-only drivers are unavailable.
- Video: `preset-windows-d3d11va`, `preset-windows-dxva2`, `preset-windows-qsv` and `preset-windows-nvenc`, and `ffmpeg.hwaccel_args: auto` detects which one to use.
- Files: everything lives under one base directory, `%LOCALAPPDATA%\Frigate` by default, relocatable with `FRIGATE_BASE_DIR`.
- Optional SCM service: `bootstrap_windows.py --install-service`.

Read the [Windows installation guide](docs/docs/frigate/installation.md#windows) for setup, ports and tuning, and [WINDOWS_COMPATIBILITY.md](WINDOWS_COMPATIBILITY.md) for the port audit: what was changed, what is verified, and what is still open.

## Documentation

The documentation site is currently configured with Frigate's upstream host, https://docs.frigate.video. To build this fork's docs locally or configure a Gannet-specific host, see [docs/README.md](docs/README.md).

## License

This project is **source-available and non-commercial**. It is not open source, and the
terms are deliberately narrower and more specific than a badge can carry:

- **Code this fork wrote** — the Windows bootstrap, the native platform, service and
  job-object layers, the PowerShell tooling, the Gannet theme, and the Windows test
  suite — is under the [Gannet Noncommercial License 1.0](LICENSE): free to use,
  study, modify, and fork for personal, educational, and noncommercial use, under the
  same terms; **not** for commercial use of any kind, including free-of-charge
  internal use by a business; and not for training AI models or publishing
  AI-generated forks.
- **Code inherited from [Frigate](https://github.com/blakeblackshear/frigate)** stays
  under its [MIT License](LICENSES/MIT.txt), unaltered, because a fork cannot take
  rights back from the people upstream granted them. That includes commercial use of
  those files, and it is most of this repository.
- **[THIRD_PARTY.md](THIRD_PARTY.md)** lists what belongs to neither.

[`REUSE.toml`](REUSE.toml) says which files are which, and
[`LICENSING.md`](LICENSING.md) explains the boundaries, the reasoning, and how to ask
for a commercial license if you need one.

**Trademarks are not licenses.** The "Gannet" and "Gannet NVR" names and logo are
trademarks of unsubstantiation and are not licensed here; the "Frigate" name and logo
belong to Frigate, Inc. and are covered by neither license. A fork must replace both
sets of brand assets and rename itself — see [TRADEMARK.md](TRADEMARK.md) and the
notices in `web/images/branding/`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md). Contributions are
accepted under these same terms; there is no CLA and no copyright assignment.

## Donations

If you would like to support development, donations go to upstream Frigate via
[Github Sponsors](https://github.com/sponsors/blakeblackshear); this fork has no
donation channel of its own and is funded by commercial licenses under Section 15 of
[LICENSE](LICENSE).

## Screenshots

### Live dashboard

<div>
<img width="800" alt="Live dashboard" src="https://github.com/blakeblackshear/frigate/assets/569905/5e713cb9-9db5-41dc-947a-6937c3bc376e">
</div>

### Streamlined review workflow

<div>
<img width="800" alt="Streamlined review workflow" src="https://github.com/blakeblackshear/frigate/assets/569905/6fed96e8-3b18-40e5-9ddc-31e6f3c9f2ff">
</div>

### Multi-camera scrubbing

<div>
<img width="800" alt="Multi-camera scrubbing" src="https://github.com/blakeblackshear/frigate/assets/569905/d6788a15-0eeb-4427-a8d4-80b93cae3d74">
</div>

### Built-in mask and zone editor

<div>
<img width="800" alt="Built-in mask and zone editor" src="https://github.com/blakeblackshear/frigate/assets/569905/d7885fc3-bfe6-452f-b7d0-d957cb3e31f5">
</div>

## Translations

We use [Weblate](https://hosted.weblate.org/projects/frigate-nvr/) to support language translations. Contributions are always welcome.

<a href="https://hosted.weblate.org/engage/frigate-nvr/">
<img src="https://hosted.weblate.org/widget/frigate-nvr/multi-auto.svg" alt="Translation status" />
</a>

---

**Copyright © 2026 Frigate, Inc.** for the Frigate code in this repository, under the
MIT License. **Copyright © 2026 unsubstantiation** for the material this fork authored,
under the Gannet Noncommercial License. See [LICENSING.md](LICENSING.md).
