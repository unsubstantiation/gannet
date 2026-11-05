# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Admin-only management of shared native WireGuard tunnel services."""

from fastapi import APIRouter, Depends, HTTPException, Request
from filelock import FileLock
from pydantic import BaseModel, Field, SecretStr
from ruamel.yaml import YAML

from gannet.api.auth import require_role
from gannet.api.defs.tags import Tags
from gannet.util.config import find_config_file
from gannet.util.wireguard import WireGuardManager

router = APIRouter(tags=[Tags.camera], dependencies=[Depends(require_role(["admin"]))])


class TunnelImport(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    config: SecretStr


class TunnelSummary(BaseModel):
    id: str
    name: str
    routes: list[str]
    status: str
    cameras: list[str] = Field(default_factory=list)


def _references(request: Request, tunnel_id: str) -> list[str]:
    # Check both active configuration and pending restart edits. Caller holds
    # the same config lock used by config/set to prevent deletion/save races.
    references = {
        name
        for name, camera in request.app.frigate_config.cameras.items()
        if camera.wireguard_tunnel == tunnel_id
    }
    with open(find_config_file(), encoding="utf-8") as handle:
        saved = YAML(typ="safe").load(handle) or {}
    references.update(
        name
        for name, camera in (saved.get("cameras") or {}).items()
        if camera.get("wireguard_tunnel") == tunnel_id
    )
    return sorted(references)


def _failure(error: Exception):
    if isinstance(error, ValueError):
        raise HTTPException(400, str(error)) from None
    if isinstance(error, RuntimeError):
        raise HTTPException(503, str(error)) from None
    raise HTTPException(
        503,
        "WireGuard operation failed. On Windows verify administrator/LocalSystem permissions and Event Viewer; on Debian verify the restricted sudo helper and journalctl.",
    ) from None


@router.get(
    "/wireguard/tunnels",
    response_model=list[TunnelSummary],
    summary="List saved WireGuard tunnels",
)
def list_tunnels(request: Request):
    try:
        with FileLock(f"{find_config_file()}.lock", timeout=5):
            return [
                {**item, "cameras": _references(request, item["id"])}
                for item in WireGuardManager().list()
            ]
    except Exception as error:
        _failure(error)


@router.post(
    "/wireguard/tunnels",
    response_model=TunnelSummary,
    status_code=201,
    summary="Import a WireGuard tunnel",
)
def import_tunnel(body: TunnelImport):
    try:
        return WireGuardManager().create(body.name, body.config.get_secret_value())
    except Exception as error:
        _failure(error)


@router.post(
    "/wireguard/tunnels/{tunnel_id}/start",
    response_model=TunnelSummary,
    summary="Start a saved WireGuard tunnel",
)
def start_tunnel(tunnel_id: str):
    manager = WireGuardManager()
    try:
        manager.start(tunnel_id)
        return {**manager.get(tunnel_id), "status": manager.status(tunnel_id)}
    except Exception as error:
        _failure(error)


@router.post(
    "/wireguard/tunnels/{tunnel_id}/stop",
    response_model=TunnelSummary,
    summary="Stop an unused WireGuard tunnel",
)
def stop_tunnel(request: Request, tunnel_id: str):
    manager = WireGuardManager()
    try:
        with FileLock(f"{find_config_file()}.lock", timeout=5):
            if _references(request, tunnel_id):
                raise HTTPException(
                    409, "Detach all cameras before stopping this tunnel."
                )
            manager.stop(tunnel_id)
        return {**manager.get(tunnel_id), "status": manager.status(tunnel_id)}
    except HTTPException:
        raise
    except Exception as error:
        _failure(error)


@router.delete(
    "/wireguard/tunnels/{tunnel_id}",
    status_code=204,
    summary="Delete an unused WireGuard tunnel",
)
def delete_tunnel(request: Request, tunnel_id: str):
    try:
        with FileLock(f"{find_config_file()}.lock", timeout=5):
            if _references(request, tunnel_id):
                raise HTTPException(
                    409, "Detach all cameras before deleting this tunnel."
                )
            WireGuardManager().delete(tunnel_id)
    except HTTPException:
        raise
    except Exception as error:
        _failure(error)
