# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Administrator-only, opt-in network camera discovery API."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from gannet.api.auth import require_role
from gannet.api.defs.tags import Tags
from gannet.util.camera_discovery import DEFAULT_PORTS, CameraDiscoveryManager

router = APIRouter(tags=[Tags.camera], dependencies=[Depends(require_role(["admin"]))])


class CameraDiscoveryRequest(BaseModel):
    target: str | None = Field(
        default=None,
        max_length=64,
        description="Optional local IPv4 address or subnet, no larger than /24.",
    )
    ports: str = Field(
        default=DEFAULT_PORTS,
        max_length=512,
        description="Comma-separated TCP ports and ranges, such as 554,8000-9000.",
    )


class DiscoveredCameraService(BaseModel):
    protocol: str
    port: int
    scheme: str
    path: str
    sources: list[str]
    requires_auth: bool


class DiscoveredCamera(BaseModel):
    host: str
    name: str | None
    model: str | None
    services: list[DiscoveredCameraService]


class CameraDiscoveryResponse(BaseModel):
    id: str
    status: str
    scanned: int
    total: int
    networks: list[str]
    devices: list[DiscoveredCamera]
    error: str | None
    warning: str | None


def _manager(request: Request) -> CameraDiscoveryManager:
    return request.app.state.camera_discovery


@router.post(
    "/camera_discovery",
    status_code=202,
    response_model=CameraDiscoveryResponse,
    summary="Start camera discovery",
    description=(
        "Start ONVIF WS-Discovery and, optionally, a bounded TCP scan of a local "
        "IPv4 address or subnet. Only one scan may run at a time. Poll the "
        "returned id for progress; scans expire if not polled."
    ),
)
async def start_camera_discovery(request: Request, body: CameraDiscoveryRequest):
    try:
        scan = _manager(request).start((body.target or "").strip() or None, body.ports)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return scan.snapshot()


@router.get(
    "/camera_discovery/{scan_id}",
    response_model=CameraDiscoveryResponse,
    summary="Get camera discovery progress",
)
async def get_camera_discovery(request: Request, scan_id: str):
    scan = _manager(request).get(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Camera scan not found.")
    return scan.snapshot()


@router.delete(
    "/camera_discovery/{scan_id}",
    response_model=CameraDiscoveryResponse,
    summary="Stop camera discovery",
)
async def stop_camera_discovery(request: Request, scan_id: str):
    manager = _manager(request)
    scan = manager.get(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Camera scan not found.")
    await manager.cancel(scan)
    return scan.snapshot()
