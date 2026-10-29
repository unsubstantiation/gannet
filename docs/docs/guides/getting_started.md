---
id: getting_started
title: Getting Started
---

import NavPath from "@site/src/components/NavPath";

# Getting started on Windows

This guide takes a new native Windows installation from bootstrap to the first working camera.

## 1. Prepare the computer

Use 64-bit Windows 10 or Windows 11 and 64-bit CPython 3.12. Install current GPU drivers before selecting hardware acceleration. A wired network and a local NTFS media volume are strongly recommended.

Open PowerShell in the Gannet source directory and run:

```powershell
py -3.12 bootstrap_windows.py
```

The bootstrap creates `.venv`, installs pinned Python packages, downloads verified Windows FFmpeg and go2rtc builds plus the detection and audio models, builds the web UI, and creates the native data directories.

Start Gannet interactively for the first setup:

```powershell
.\run_gannet.ps1
```

Open `https://localhost:8971`. The generated certificate is self-signed, so the first browser visit displays a certificate warning. Retrieve the generated administrator password from `data\tmp\logs\gannet\current` below the portable bundle root (or `%LOCALAPPDATA%\Gannet\tmp\logs\gannet\current` for a default interactive install) and change it during setup.

## 2. Add a camera

Use <NavPath path="Settings > Global configuration > Camera management" /> or edit `config\config.yml`. Start with one camera and one stable RTSP stream:

```yaml
mqtt:
  enabled: false

cameras:
  front:
    ffmpeg:
      inputs:
        - path: rtsp://{GANNET_RTSP_USER}:{GANNET_RTSP_PASSWORD}@camera/stream
          roles: [detect]
```

Put the substituted values in `config\secrets.yaml`:

```yaml
GANNET_RTSP_USER: camera-user
GANNET_RTSP_PASSWORD: a-long-unique-password
```

Test the exact URL in VLC or the installed `ffplay.exe` from the Gannet machine. Prefer a camera substream near the model's useful detection resolution and around 5 frames per second. Detection on a 4K stream wastes resources without improving most models.

## 3. Configure object detection

The default TFLite detector runs on the CPU and uses the digest-verified model installed by the bootstrap. It is suitable for setup and small installations.

The setup wizard probes native Windows runtimes and offers supported devices:

- **CPU** — always available;
- **OpenVINO** — Intel CPU, GPU, or NPU exposed by the installed OpenVINO runtime;
- **ONNX Runtime DirectML** — GPU inference through `onnxruntime-directml`;
- **ONNX Runtime CUDA** — NVIDIA inference when the CUDA provider is installed.

ONNX and OpenVINO require a compatible local model path. Set it under <NavPath path="Settings > System > Detection models" />. Do not select a provider that is not shown by <NavPath path="System > Hardware" />.

## 4. Enable Windows video acceleration

Begin without acceleration so camera connectivity is easy to diagnose. Then select the recommendation shown by the setup wizard or use a supported preset:

```yaml
ffmpeg:
  hwaccel_args: preset-windows-d3d11va
```

Other native presets cover Intel QSV, NVIDIA NVDEC/NVENC, DXVA2, AMD AMF, and Vulkan. A working detector does not prove that video decoding is accelerated; they are separate pipelines.

## 5. Configure recording

Add a higher-quality stream for recording when the camera offers one:

```yaml
record:
  enabled: true
  retain:
    days: 7
    mode: motion

cameras:
  front:
    ffmpeg:
      inputs:
        - path: rtsp://{GANNET_RTSP_USER}:{GANNET_RTSP_PASSWORD}@camera/substream
          roles: [detect]
        - path: rtsp://{GANNET_RTSP_USER}:{GANNET_RTSP_PASSWORD}@camera/mainstream
          roles: [record]
```

Media defaults to `data\media` in the portable bundle or `%LOCALAPPDATA%\Gannet\media` for a default interactive install. Set `GANNET_MEDIA_DIR` before startup to place it on another local NTFS volume. The Windows service account needs Modify access.

## 6. Tune motion and objects

After detections are visible:

1. draw motion masks only over unavoidable movement such as timestamps or swaying foliage;
2. create zones for areas that matter;
3. tune object thresholds and minimum area from real examples;
4. enable snapshots, alerts, and longer retention only after basic tracking is stable.

Large motion masks can prevent Gannet from running object detection where it is needed. Object masks discard detections whose anchor point falls inside the mask; they should not be used as general privacy masks.

## 7. Configure live view

Add the source to go2rtc, preferably with a stream name matching the camera:

```yaml
go2rtc:
  streams:
    front:
      - rtsp://{GANNET_RTSP_USER}:{GANNET_RTSP_PASSWORD}@camera/mainstream
```

MSE usually works with no extra network rule. WebRTC needs a candidate address that the browser can reach and Windows Firewall access to its configured TCP/UDP port.

## 8. Install the Windows service

After the interactive configuration works, open an elevated PowerShell session:

```powershell
.\scripts\install_gannet_service.ps1
```

The installer records paths and environment for the service account. Verify:

```powershell
Get-Service Gannet
Get-Content "$env:ProgramData\Gannet\tmp\logs\gannet\current" -Tail 100
```

If the installer was given another data root, read the log from that configured root instead.

## Next steps

- [Configuration](../configuration/config.md)
- [Object detectors](../configuration/object_detectors.md)
- [Video hardware acceleration](../configuration/hardware_acceleration_video.md)
- [Recording](../configuration/record.md)
- [Live view](../configuration/live.md)
- [Windows troubleshooting](../troubleshooting/common_errors.md)
