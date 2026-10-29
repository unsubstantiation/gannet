---
id: object_detectors
title: Object Detectors
---

# Object detectors on Windows

Gannet runs object detection locally. A model declares one or more Windows detector devices using the `models[].devices` list. Each value is either a detector name or `<detector>:<device>`.

## Supported detectors

| Detector | Device examples | Runtime | Model formats |
| --- | --- | --- | --- |
| CPU TFLite | `cpu` | `ai-edge-litert` | `.tflite` |
| ONNX Runtime | `onnx`, `onnx:0`, `onnx:CPU` | CPU, CUDA, or DirectML provider exposed by the installed ONNX Runtime package | `.onnx` |
| OpenVINO | `openvino:CPU`, `openvino:GPU`, `openvino:NPU` | Intel CPU, GPU, and NPU through OpenVINO | `.xml`, `.onnx`, `.pdmodel`, `.pb` |
| Remote ZMQ | `zmq:tcp://host:5555` | A compatible remote inference service | `.onnx` and other formats the endpoint loads |

Coral Edge TPU, Hailo, TensorRT, RKNN, MemryX, DeepX, Synaptics, AXEngine, and other Linux or appliance-specific detectors are not part of the native Windows application.

## CPU TFLite

The default configuration uses the CPU detector:

```yaml
models:
  - scene: default
    devices:
      - cpu
```

On first use Gannet downloads its default TFLite model into `data\config\model_cache` in the portable bundle (or `%LOCALAPPDATA%\Gannet\config\model_cache` for a default interactive install). Set `path` to use another compatible model.

## ONNX Runtime

```yaml
models:
  - scene: default
    path: C:\Models\yolo.onnx
    model_type: yolonas
    width: 320
    height: 320
    input_tensor: nchw
    input_pixel_format: rgb
    devices:
      - onnx:0
```

The standard installer selects `onnxruntime-directml` by default. DirectML supports modern AMD, Intel, and NVIDIA display adapters. Run `bootstrap_windows.py --no-directml` for CPU-only ONNX Runtime. A separately installed CUDA-capable ONNX Runtime can expose NVIDIA CUDA as well.

The numeric suffix selects the provider's adapter index. Use the System page and startup logs to confirm which provider and adapter loaded.

## OpenVINO

```yaml
models:
  - scene: default
    path: C:\Models\detector.xml
    devices:
      - openvino:GPU
```

Valid device values are those reported by OpenVINO on the machine, commonly `CPU`, `GPU`, `GPU.0`, and `NPU`. Current Intel graphics and NPU drivers must be installed.

OpenVINO reads OpenVINO IR (`.xml`), ONNX (`.onnx`), Paddle (`.pdmodel`), and TensorFlow (`.pb`) models. It cannot read `.tflite` detection models: SSDLite and MobileNet-SSD exports run their non-max suppression in a `TFLite_Detection_PostProcess` op, which OpenVINO's TFLite frontend has no translator for, so the detector fails with `No translator found for TFLite_Detection_PostProcess node`. Gannet rejects this combination when it validates the config rather than at detector startup. Run a `.tflite` model on the `cpu` detector, or point `path` at an IR or ONNX export of the same detector. Converting the `.tflite` file itself does not help, because the conversion fails at the same op; the export has to come from the model author or from the framework the model was trained in.

## Remote ZMQ

```yaml
models:
  - scene: default
    path: C:\Models\detector.onnx
    devices:
      - zmq:tcp://192.168.1.20:5555
```

The remote endpoint is responsible for loading a compatible model and returning detections using Gannet's ZMQ detector protocol. Keep the endpoint on a trusted network; ZMQ transport does not add authentication by itself.

## Multiple devices and scenes

Listing multiple devices runs inference workers for the same model:

```yaml
models:
  - scene: outdoor
    path: C:\Models\outdoor.onnx
    devices:
      - onnx:0
      - onnx:0
  - scene: indoor
    path: C:\Models\indoor.xml
    devices:
      - openvino:NPU
```

Repeated shareable devices receive unique worker names automatically. Cameras select a model with `detect.scene`. Every configured camera scene must have a matching model.

## Model compatibility

The model format, dimensions, tensor layout, pixel format, and label map must match the selected detector. Gannet checks the file suffix against the detector when it validates the config: a mismatch is reported at that point instead of at detector startup, because a detector that cannot load its model is restarted until the app gives up. Files without a suffix are left to the detector to identify. Configure the dimensions, tensor layout, pixel format, and label map explicitly when they differ from the defaults. Legacy `plus://` paths are no longer supported: replace them with a compatible local model path and its matching settings.
