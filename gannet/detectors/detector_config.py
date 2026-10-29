import hashlib
import logging
import os
from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.fields import PrivateAttr

from gannet.const import DEFAULT_ATTRIBUTE_LABEL_MAP
from gannet.util.builtin import generate_color_palette, load_labels
from gannet.util.platform import get_default_labelmap_path

logger = logging.getLogger(__name__)

# attributes that are recognized rather than shown as a logo
NON_LOGO_ATTRIBUTES = ["face", "license_plate"]


class PixelFormatEnum(str, Enum):
    rgb = "rgb"
    bgr = "bgr"
    yuv = "yuv"


class InputTensorEnum(str, Enum):
    nchw = "nchw"
    nhwc = "nhwc"
    hwnc = "hwnc"
    hwcn = "hwcn"


class InputDTypeEnum(str, Enum):
    float = "float"
    float_denorm = "float_denorm"  # non-normalized float
    int = "int"


class ModelTypeEnum(str, Enum):
    dfine = "dfine"
    rfdetr = "rfdetr"
    ssd = "ssd"
    yolox = "yolox"
    yolonas = "yolonas"
    yologeneric = "yolo-generic"


# the scene of the model used by cameras that don't name one
DEFAULT_SCENE = "default"
SCENE_PATTERN = r"^[A-Za-z0-9_-]+$"


class ModelConfig(BaseModel):
    scene: str = Field(
        default=DEFAULT_SCENE,
        pattern=SCENE_PATTERN,
        title="Model scene",
        description="A name for the camera environment this model is used for, such as 'thermal'. Cameras select a model by setting detect.scene to a matching value, and the 'default' model is used by any camera that does not set one.",
    )
    devices: list[str] = Field(
        default_factory=list,
        title="Detection hardware",
        description="Hardware this model runs on, as '<detector>' or '<detector>:<device>' (for example 'onnx:0' or 'openvino:GPU'). Listing the same device more than once runs additional inference processes on it.",
    )
    path: str | None = Field(
        None,
        title="Custom object detector model path",
        description="Path to a local custom detection model file.",
    )
    labelmap_path: str | None = Field(
        None,
        title="Label map for custom object detector",
        description="Path to a labelmap file that maps numeric classes to string labels for the detector.",
    )
    width: int = Field(
        default=320,
        title="Object detection model input width",
        description="Width of the model input tensor in pixels.",
    )
    height: int = Field(
        default=320,
        title="Object detection model input height",
        description="Height of the model input tensor in pixels.",
    )
    labelmap: dict[int, str] = Field(
        default_factory=dict,
        title="Labelmap customization",
        description="Overrides or remapping entries to merge into the standard labelmap.",
    )
    attributes_map: dict[str, list[str]] = Field(
        default=DEFAULT_ATTRIBUTE_LABEL_MAP,
        title="Map of object labels to their attribute labels",
        description="Mapping from object labels to attribute labels used to attach metadata (for example 'car' -> ['license_plate']).",
    )
    input_tensor: InputTensorEnum = Field(
        default=InputTensorEnum.nhwc,
        title="Model Input Tensor Shape",
        description="Tensor format expected by the model: 'nhwc' or 'nchw'.",
    )
    input_pixel_format: PixelFormatEnum = Field(
        default=PixelFormatEnum.rgb,
        title="Model Input Pixel Color Format",
        description="Pixel colorspace expected by the model: 'rgb', 'bgr', or 'yuv'.",
    )
    input_dtype: InputDTypeEnum = Field(
        default=InputDTypeEnum.int,
        title="Model Input D Type",
        description="Data type of the model input tensor (for example 'float32').",
    )
    model_type: ModelTypeEnum = Field(
        default=ModelTypeEnum.ssd,
        title="Object Detection Model Type",
        description="Detector model architecture type (ssd, yolox, yolonas, yolo-generic, rfdetr, dfine) used by some detectors for optimization.",
    )
    _merged_labelmap: dict[int, str] | None = PrivateAttr()
    _colormap: dict[int, tuple[int, int, int]] = PrivateAttr()
    _all_attributes: list[str] = PrivateAttr()
    _all_attribute_logos: list[str] = PrivateAttr()
    _model_hash: str = PrivateAttr()

    @property
    def merged_labelmap(self) -> dict[int, str]:
        return self._merged_labelmap

    @property
    def colormap(self) -> dict[int, tuple[int, int, int]]:
        return self._colormap

    @property
    def non_logo_attributes(self) -> list[str]:
        return NON_LOGO_ATTRIBUTES

    @property
    def all_attributes(self) -> list[str]:
        return self._all_attributes

    @property
    def all_attribute_logos(self) -> list[str]:
        return self._all_attribute_logos

    @property
    def model_hash(self) -> str:
        return self._model_hash

    @field_validator("path")
    @classmethod
    def reject_removed_cloud_model(cls, path: str | None) -> str | None:
        if path and path.lower().startswith("plus://"):
            raise ValueError(
                "Frigate+ model paths are no longer supported; configure a local model file."
            )
        return path

    def __init__(self, **config):
        super().__init__(**config)

        labelmap_path = config.get("labelmap_path")
        if "labelmap_path" not in config:
            labelmap_path = get_default_labelmap_path()

        self._merged_labelmap = {
            **load_labels(labelmap_path),
            **config.get("labelmap", {}),
        }
        self._colormap = {}

        # generate list of attribute labels
        unique_attributes = set()

        for attributes in self.attributes_map.values():
            unique_attributes.update(attributes)

        self._all_attributes = list(unique_attributes)
        self._all_attribute_logos = list(
            unique_attributes - set(self.non_logo_attributes)
        )

    def compute_model_hash(self) -> None:
        if not self.path or not os.path.exists(self.path):
            self._model_hash = hashlib.md5(b"unknown").hexdigest()
        else:
            with open(self.path, "rb") as f:
                file_hash = hashlib.md5()
                while chunk := f.read(8192):
                    file_hash.update(chunk)
            self._model_hash = file_hash.hexdigest()

    def create_colormap(self, enabled_labels: set[str]) -> None:
        """Get a list of colors for enabled labels that aren't attributes."""
        enabled_trackable_labels = list(
            filter(lambda label: label not in self._all_attributes, enabled_labels)
        )
        colors = generate_color_palette(len(enabled_trackable_labels))
        self._colormap = {
            label: color for label, color in zip(enabled_trackable_labels, colors)
        }

    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class BaseDetectorConfig(BaseModel):
    # how the trailing part of a device string ("openvino:GPU" -> "GPU") maps onto
    # this detector's fields, and whether the same device may be listed more than
    # once to run additional inference processes against it. Most accelerators
    # multiplex fine, so this is opt-out rather than opt-in.
    device_spec_field: ClassVar[str] = "device"
    device_spec_type: ClassVar[type] = str
    shareable: ClassVar[bool] = True

    # the type field must be defined in all subclasses
    type: str = Field(
        default="cpu",
        title="Detector Type",
        description="Native Windows detector type: cpu, onnx, openvino, or zmq.",
    )
    model: ModelConfig | None = Field(
        default=None,
        title="Detector specific model configuration",
        description="Detector-specific model configuration options (path, input size, etc.).",
    )
    model_path: str | None = Field(
        default=None,
        title="Detector specific model path",
        description="File path to the detector model binary if required by the chosen detector.",
    )
    model_config = ConfigDict(
        extra="allow", arbitrary_types_allowed=True, protected_namespaces=()
    )
