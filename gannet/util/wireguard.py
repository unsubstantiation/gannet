# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Managed native Windows WireGuard services; never expose stored key material."""

from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import subprocess
import uuid
from pathlib import Path

from filelock import FileLock

from gannet.util.platform import IS_WINDOWS, find_executable, get_config_dir

ID_PATTERN = r"[a-f0-9]{16}"


def validate_config(text: str) -> list[str]:
    """Accept a deliberately limited, split-tunnel subset of wg-quick syntax.

    No hooks, DNS changes, default routes or arbitrary driver options. Error
    messages deliberately never include submitted values (which may be keys).
    """
    if len(text.encode("utf-8")) > 65536 or "\x00" in text:
        raise ValueError(
            "WireGuard configuration is too large or contains invalid data."
        )
    sections: list[tuple[str, dict[str, str]]] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line in ("[Interface]", "[Peer]"):
            sections.append((line, {}))
            continue
        if not sections or "=" not in line:
            raise ValueError("Invalid WireGuard configuration syntax.")
        key, value = (part.strip() for part in line.split("=", 1))
        allowed = (
            {"PrivateKey", "Address", "ListenPort", "MTU"}
            if sections[-1][0] == "[Interface]"
            else {
                "PublicKey",
                "PresharedKey",
                "AllowedIPs",
                "Endpoint",
                "PersistentKeepalive",
            }
        )
        if key not in allowed or key in sections[-1][1] or not value:
            raise ValueError(
                "Unsupported, duplicate or empty WireGuard option. DNS and hooks are not supported."
            )
        sections[-1][1][key] = value
    if (
        not sections
        or sections[0][0] != "[Interface]"
        or sum(s[0] == "[Interface]" for s in sections) != 1
        or len(sections) < 2
    ):
        raise ValueError("Exactly one Interface and at least one Peer are required.")
    routes: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    try:
        for section, values in sections:
            keys = (
                ("PrivateKey",)
                if section == "[Interface]"
                else ("PublicKey", "PresharedKey")
            )
            for key in keys:
                if key == "PresharedKey" and key not in values:
                    continue
                if len(base64.b64decode(values[key], validate=True)) != 32:
                    raise ValueError
            if section == "[Interface]":
                for address in values["Address"].split(","):
                    ipaddress.ip_interface(address.strip())
                numbers = {"ListenPort": (0, 65535), "MTU": (576, 9000)}
            else:
                peer_routes = [
                    ipaddress.ip_network(value.strip(), strict=False)
                    for value in values["AllowedIPs"].split(",")
                ]
                # Reject broad catch-all routes, including default-route halves.
                if any(
                    route.prefixlen < (8 if route.version == 4 else 16)
                    for route in peer_routes
                ):
                    raise ValueError
                if any(
                    a.version == b.version and a.overlaps(b)
                    for a in peer_routes
                    for b in routes
                ):
                    raise ValueError
                routes.extend(peer_routes)
                if "Endpoint" in values:
                    endpoint = values["Endpoint"]
                    host, port = endpoint.rsplit(":", 1)
                    if (
                        not host
                        or re.search(r"[\s/\\]", host)
                        or not 1 <= int(port) <= 65535
                    ):
                        raise ValueError
                numbers = {"PersistentKeepalive": (0, 65535)}
            for key, (minimum, maximum) in numbers.items():
                if key in values and not minimum <= int(values[key]) <= maximum:
                    raise ValueError
    except (ValueError, KeyError) as exc:
        raise ValueError(
            "Invalid WireGuard key, address, endpoint, numeric option or route. Use non-overlapping split-tunnel AllowedIPs (IPv4 /8 or narrower; IPv6 /16 or narrower)."
        ) from exc
    return [str(route) for route in routes]


class WindowsWireGuardManager:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or Path(get_config_dir()) / "wireguard"

    @staticmethod
    def _windows():
        if os.name != "nt":
            raise RuntimeError(
                "Managed WireGuard tunnels require Windows and elevation."
            )

    def _prepare(self):
        self._windows()
        import ntsecuritycon
        import win32security

        self.directory.mkdir(parents=True, exist_ok=True)
        acl = win32security.ACL()
        for sid in ("S-1-5-18", "S-1-5-32-544"):
            acl.AddAccessAllowedAceEx(
                win32security.ACL_REVISION,
                win32security.OBJECT_INHERIT_ACE | win32security.CONTAINER_INHERIT_ACE,
                ntsecuritycon.FILE_ALL_ACCESS,
                win32security.ConvertStringSidToSid(sid),
            )
        win32security.SetNamedSecurityInfo(
            str(self.directory),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION
            | win32security.PROTECTED_DACL_SECURITY_INFORMATION
            | win32security.OWNER_SECURITY_INFORMATION,
            win32security.ConvertStringSidToSid("S-1-5-32-544"),
            None,
            acl,
            None,
        )
        # Access failure is intentionally surfaced instead of weakening the ACL.

    def _path(self, tunnel_id: str, suffix: str) -> Path:
        if re.fullmatch(ID_PATTERN, tunnel_id) is None:
            raise ValueError("Invalid tunnel id.")
        return self.directory / f"gannet_{tunnel_id}{suffix}"

    @staticmethod
    def _service(tunnel_id: str) -> str:
        return f"WireGuardTunnel$gannet_{tunnel_id}"

    def _records(self) -> list[dict]:
        if not self.directory.exists():
            return []
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(self.directory.glob("gannet_*.json"))
        ]

    def get(self, tunnel_id: str) -> dict:
        path = self._path(tunnel_id, ".json")
        if not path.is_file():
            raise ValueError("Saved WireGuard tunnel not found.")
        return json.loads(path.read_text(encoding="utf-8"))

    def status(self, tunnel_id: str) -> str:
        self._windows()
        import pywintypes
        import win32service
        import win32serviceutil

        try:
            state = win32serviceutil.QueryServiceStatus(self._service(tunnel_id))[1]
        except pywintypes.error as exc:
            if exc.winerror == 1060:
                return "not_installed"
            raise RuntimeError(
                "Cannot query WireGuard service. Run Gannet elevated or as LocalSystem."
            ) from None
        return (
            "running"
            if state == win32service.SERVICE_RUNNING
            else "stopped"
            if state == win32service.SERVICE_STOPPED
            else "pending"
        )

    def list(self) -> list[dict]:
        self._windows()
        return [{**item, "status": self.status(item["id"])} for item in self._records()]

    def create(self, name: str, config: str) -> dict:
        routes = validate_config(config)
        name = name.strip()
        if not name or len(name) > 80 or not name.isprintable():
            raise ValueError("Tunnel name must contain 1–80 printable characters.")
        self._prepare()
        import win32crypt

        with FileLock(str(self.directory / "management.lock"), timeout=5):
            for item in self._records():
                if item["name"].casefold() == name.casefold():
                    raise ValueError("A tunnel with this name already exists.")
                for route in routes:
                    a = ipaddress.ip_network(route)
                    if any(
                        a.version == (b := ipaddress.ip_network(other)).version
                        and a.overlaps(b)
                        for other in item["routes"]
                    ):
                        raise ValueError(
                            "AllowedIPs overlap another saved tunnel. Overlapping camera networks are not supported."
                        )
            tunnel_id = uuid.uuid4().hex[:16]
            # WireGuard's .conf.dpapi reader verifies this description against
            # the filename. Machine scope permits its LocalSystem service to
            # read the encrypted configuration; the directory ACL limits access.
            encrypted = win32crypt.CryptProtectData(
                config.encode("utf-8"), f"gannet_{tunnel_id}", None, None, None, 0x5
            )
            config_path = self._path(tunnel_id, ".conf.dpapi")
            config_path.write_bytes(encrypted)
            record = {"id": tunnel_id, "name": name, "routes": routes}
            try:
                temporary = self._path(tunnel_id, ".json.tmp")
                temporary.write_text(json.dumps(record), encoding="utf-8")
                temporary.replace(self._path(tunnel_id, ".json"))
            except Exception:
                config_path.unlink(missing_ok=True)
                raise
            return {**record, "status": "not_installed"}

    def _command(self, *args: str):
        # Elevated service installation must not execute a same-named program
        # from a user-writable PATH directory.
        binary = find_executable(
            str(
                Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                / "WireGuard"
                / "wireguard.exe"
            )
        )
        if binary is None:
            raise RuntimeError(
                "Install the official WireGuard for Windows application first."
            )
        try:
            subprocess.run(
                [binary, *args],
                check=True,
                capture_output=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError(
                "WireGuard service operation failed. Run Gannet elevated or as LocalSystem and check Windows Event Viewer."
            ) from None

    def _demand_start(self, tunnel_id: str):
        """Gannet, not Windows boot, decides which saved tunnels to restore."""
        import win32service

        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        try:
            service = win32service.OpenService(
                scm, self._service(tunnel_id), win32service.SERVICE_CHANGE_CONFIG
            )
            try:
                win32service.ChangeServiceConfig(
                    service,
                    win32service.SERVICE_NO_CHANGE,
                    win32service.SERVICE_DEMAND_START,
                    win32service.SERVICE_NO_CHANGE,
                    None,
                    None,
                    0,
                    None,
                    None,
                    None,
                    None,
                )
            finally:
                win32service.CloseServiceHandle(service)
        finally:
            win32service.CloseServiceHandle(scm)

    def start(self, tunnel_id: str):
        self._windows()
        self.get(tunnel_id)
        import win32serviceutil

        with FileLock(str(self.directory / "management.lock"), timeout=5):
            status = self.status(tunnel_id)
            if status == "not_installed":
                self._command(
                    "/installtunnelservice", str(self._path(tunnel_id, ".conf.dpapi"))
                )
            elif status == "stopped":
                win32serviceutil.StartService(self._service(tunnel_id))
            self._demand_start(tunnel_id)
            win32serviceutil.WaitForServiceStatus(self._service(tunnel_id), 4, 30)

    def stop(self, tunnel_id: str):
        self._windows()
        self.get(tunnel_id)
        import win32serviceutil

        with FileLock(str(self.directory / "management.lock"), timeout=5):
            if self.status(tunnel_id) not in ("not_installed", "stopped"):
                win32serviceutil.StopService(self._service(tunnel_id))
                win32serviceutil.WaitForServiceStatus(self._service(tunnel_id), 1, 30)

    def delete(self, tunnel_id: str):
        self._windows()
        self.get(tunnel_id)
        with FileLock(str(self.directory / "management.lock"), timeout=5):
            if self.status(tunnel_id) != "not_installed":
                self._command("/uninstalltunnelservice", f"gannet_{tunnel_id}")
            self._path(tunnel_id, ".conf.dpapi").unlink(missing_ok=True)
            self._path(tunnel_id, ".json").unlink()


def WireGuardManager(directory: Path | None = None):
    """Select the native backend without importing Win32 libraries on Debian."""
    if IS_WINDOWS:
        return WindowsWireGuardManager(directory)
    from gannet.util.wireguard_debian import DebianWireGuardManager

    return DebianWireGuardManager()


def start_camera_tunnels(config):
    """Restore required services before starting camera consumers (fail closed)."""
    manager = WireGuardManager()
    for tunnel_id in {
        camera.wireguard_tunnel
        for camera in config.cameras.values()
        if camera.enabled and camera.wireguard_tunnel
    }:
        manager.start(tunnel_id)
