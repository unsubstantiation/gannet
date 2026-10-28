---
id: hardware_acceleration_enrichments
title: Enrichment Acceleration
---

# Enrichment acceleration on Windows

Semantic search, face recognition, license-plate recognition, classification, and other enrichment models use ONNX Runtime or OpenVINO when the model supports them.

## Device values

Common values are:

- `CPU` — force CPU inference;
- `AUTO` — choose an available provider automatically;
- `GPU` or `GPU.0` — use an available GPU provider or an OpenVINO Intel GPU;
- `NPU` — use an OpenVINO Intel NPU;
- `cuda:0` — explicitly select NVIDIA CUDA device zero;
- `directml:0` — explicitly select DirectML adapter zero;
- `windowsml:<ExecutionProvider>` — select a catalog-installed Windows ML provider, for example `windowsml:QNNExecutionProvider`.

The System page reports the provider selected by each loaded enrichment model. Actual support depends on model operators, Windows build, provider version, hardware and driver.

## DirectML

The default bootstrap swaps CPU ONNX Runtime for `onnxruntime-directml`. DirectML can use AMD, Intel, and NVIDIA display adapters without a CUDA-specific Python package. Choose the runtime profile at bootstrap time: `--directml` (default), `--cuda`, `--windows-ml`, or `--no-directml` for CPU. The ONNX Runtime distributions are alternatives and must not be layered together; rerun bootstrap with the desired profile to switch.

## OpenVINO

OpenVINO is included in the Windows requirements. Intel GPU and NPU devices appear only when the matching Windows driver exposes them to OpenVINO. `CPU` remains available as a fallback.

## NVIDIA CUDA

Install the official ONNX Runtime GPU profile with `py -3.12 bootstrap_windows.py --cuda`. It selects `onnxruntime-gpu` 1.31 and its CUDA/cuDNN extras (CUDA 13 and cuDNN 9 libraries), replacing CPU/DirectML/Windows ML ONNX Runtime packages. A compatible NVIDIA driver and GPU are still required. Object-detection inference uses ONNX Runtime CUDA; FFmpeg video decoding/encoding is configured separately and does not depend on this profile.

## Windows ML catalog providers

Use Windows 11 24H2 or later and select the `--windows-ml` bootstrap profile. It installs `windowsml[with-ort]`, whose published extra pins its compatible ONNX Runtime build (1.27.1); compatibility with the general 1.31 line is not assumed. Then inspect providers and explicitly prepare one from an elevated or appropriately permitted PowerShell session:

```powershell
.\.venv\Scripts\python.exe scripts\manage_windows_ml.py list
.\.venv\Scripts\python.exe scripts\manage_windows_ml.py install QNNExecutionProvider
.\.venv\Scripts\python.exe scripts\manage_windows_ml.py install --all
```

Only providers the Windows ML catalog reports as compatible are available. After installation, Gannet registers ready provider libraries in its Python ONNX Runtime process and exposes selectable device strings such as `onnx:windowsml:QNNExecutionProvider`. This is separate from the standalone OpenVINO backend. Catalog availability does not guarantee that a particular model is supported or fast on the selected hardware. WebGPU is experimental and is excluded by default; opt in by setting `GANNET_ENABLE_EXPERIMENTAL_WEBGPU=1` in the environment used for both provider installation and the Gannet process.

## Memory considerations

A model loaded by more than one process consumes memory per process. Start with `AUTO`, inspect runtime-device and memory statistics, and pin a device only when automatic selection is unsuitable. If a GPU runs out of memory, move some enrichments to `CPU` or reduce the number of concurrently enabled models.
