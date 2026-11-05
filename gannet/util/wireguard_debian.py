# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Debian wg-quick services behind a narrow, root-owned sudo helper.

The unprivileged application never reads keys. Only the isolated helper writes
root-only configs, validates the same no-hooks/split-route subset, and calls
systemctl with generated interface names. There are no client-controlled paths.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import uuid
from pathlib import Path

from filelock import FileLock

HELPER = "/usr/local/libexec/gannet-wireguard"
STORE = Path("/etc/wireguard/gannet")


class DebianWireGuardManager:
    def __init__(self, *, privileged: bool = False, directory: Path = STORE):
        self.privileged = privileged
        self.directory = directory
        if privileged and os.geteuid() != 0:
            raise RuntimeError("WireGuard helper requires root.")

    def _call(self, action: str, tunnel_id: str = "", body: dict | None = None):
        command = ["/usr/bin/sudo", "-n", HELPER, action]
        if tunnel_id:
            self._id(tunnel_id)
            command.append(tunnel_id)
        try:
            result = subprocess.run(
                command,
                input=json.dumps(body or {}),
                text=True,
                capture_output=True,
                timeout=90,
                check=True,
                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
            )
            response = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            raise RuntimeError(
                "Debian WireGuard helper unavailable or operation failed. Check the sudo helper installation and journalctl for the tunnel service."
            ) from None
        if "error" in response:
            if response.get("retry"):
                raise RuntimeError(response["error"])
            raise ValueError(response["error"])
        return response.get("result")

    @staticmethod
    def _id(tunnel_id: str):
        if re.fullmatch(r"[a-f0-9]{16}", tunnel_id) is None:
            raise ValueError("Invalid tunnel id.")

    @classmethod
    def interface(cls, tunnel_id: str) -> str:
        cls._id(tunnel_id)
        return "gn" + tunnel_id[:12]  # Linux interface names must be <16 bytes.

    def _metadata(self, tunnel_id: str) -> Path:
        self._id(tunnel_id)
        return self.directory / f"{tunnel_id}.json"

    def _config(self, tunnel_id: str) -> Path:
        return self.directory.parent / f"{self.interface(tunnel_id)}.conf"

    @staticmethod
    def _write_private(path: Path, value: str):
        # Refuse existing paths and symlinks, and set permissions at creation.
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())

    def _systemctl(self, action: str, tunnel_id: str) -> subprocess.CompletedProcess:
        self._id(tunnel_id)
        try:
            return subprocess.run(
                [
                    "/usr/bin/systemctl",
                    action,
                    f"wg-quick@{self.interface(tunnel_id)}.service",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=action != "is-active",
                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
            )
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError(
                "WireGuard service operation failed; inspect journalctl for the managed tunnel."
            ) from None

    def get(self, tunnel_id: str) -> dict:
        if not self.privileged:
            return self._call("get", tunnel_id)
        path = self._metadata(tunnel_id)
        if not path.is_file() or path.is_symlink():
            raise ValueError("Saved WireGuard tunnel not found.")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict]:
        if not self.privileged:
            return self._call("list")
        if not self.directory.exists():
            return []
        return [
            {**self.get(path.stem), "status": self.status(path.stem)}
            for path in sorted(self.directory.glob("*.json"))
        ]

    def status(self, tunnel_id: str) -> str:
        if not self.privileged:
            return self._call("status", tunnel_id)
        self.get(tunnel_id)
        value = self._systemctl("is-active", tunnel_id).stdout.strip()
        return (
            "running"
            if value == "active"
            else "pending"
            if value in ("activating", "deactivating")
            else "stopped"
        )

    def create(self, name: str, config: str) -> dict:
        if not self.privileged:
            return self._call("create", body={"name": name, "config": config})
        from gannet.util.wireguard import validate_config

        routes = validate_config(config)
        name = name.strip()
        if not name or len(name) > 80 or not name.isprintable():
            raise ValueError("Tunnel name must contain 1–80 printable characters.")
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.directory.is_symlink() or self.directory.parent.is_symlink():
            raise RuntimeError("Unsafe WireGuard storage directory.")
        self.directory.chmod(0o700)
        with FileLock(str(self.directory / "management.lock"), timeout=5):
            records = [self.get(path.stem) for path in self.directory.glob("*.json")]
            for record in records:
                if record["name"].casefold() == name.casefold():
                    raise ValueError("A tunnel with this name already exists.")
                for value in routes:
                    route = ipaddress.ip_network(value)
                    if any(
                        route.version == (other := ipaddress.ip_network(value)).version
                        and route.overlaps(other)
                        for value in record["routes"]
                    ):
                        raise ValueError("AllowedIPs overlap another saved tunnel.")
            while True:
                tunnel_id = uuid.uuid4().hex[:16]
                if not self._config(tunnel_id).exists():
                    break
            record = {"id": tunnel_id, "name": name, "routes": routes}
            self._write_private(self._config(tunnel_id), config)
            try:
                self._write_private(self._metadata(tunnel_id), json.dumps(record))
            except Exception:
                self._config(tunnel_id).unlink()
                raise
            return {**record, "status": "stopped"}

    def start(self, tunnel_id: str):
        if not self.privileged:
            return self._call("start", tunnel_id)
        from gannet.util.wireguard import validate_config

        self.get(tunnel_id)
        with FileLock(str(self.directory / "management.lock"), timeout=5):
            # Validate again before wg-quick: stored data must not smuggle hooks
            # into a privileged shell script, even if manually edited by root.
            validate_config(self._config(tunnel_id).read_text(encoding="utf-8"))
            self._systemctl("start", tunnel_id)

    def stop(self, tunnel_id: str):
        if not self.privileged:
            return self._call("stop", tunnel_id)
        self.get(tunnel_id)
        with FileLock(str(self.directory / "management.lock"), timeout=5):
            self._systemctl("stop", tunnel_id)

    def delete(self, tunnel_id: str):
        if not self.privileged:
            return self._call("delete", tunnel_id)
        self.get(tunnel_id)
        with FileLock(str(self.directory / "management.lock"), timeout=5):
            self._systemctl("stop", tunnel_id)
            self._config(tunnel_id).unlink(missing_ok=True)
            self._metadata(tunnel_id).unlink()
