from enum import Enum
from typing import TYPE_CHECKING, TypedDict

from gannet.camera import CameraMetrics
from gannet.data_processing.types import DataProcessorMetrics
from gannet.object_detection.base import ObjectDetectProcess

if TYPE_CHECKING:
    from gannet.storage import StorageMaintainer


class StatsTrackingTypes(TypedDict):
    camera_metrics: dict[str, CameraMetrics]
    embeddings_metrics: DataProcessorMetrics
    detectors: dict[str, ObjectDetectProcess]
    started: int
    latest_frigate_version: str
    last_updated: int
    processes: dict[str, int]
    storage_maintainer: "StorageMaintainer | None"


class ModelStatusTypesEnum(str, Enum):
    not_downloaded = "not_downloaded"
    downloading = "downloading"
    downloaded = "downloaded"
    error = "error"
    training = "training"
    complete = "complete"
    failed = "failed"


class JobStatusTypesEnum(str, Enum):
    pending = "pending"
    queued = "queued"
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"


class TrackedObjectUpdateTypesEnum(str, Enum):
    description = "description"
    face = "face"
    lpr = "lpr"
    classification = "classification"
