# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Debian wg-quick services behind a narrow, root-owned sudo helper.

The unprivileged application never reads keys. Only the isolated helper writes
OS-encrypted credentials, validates the same no-hooks/split-route subset, and calls
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
        """Legacy plaintext store, retained only until a successful migration."""
        return self.directory.parent / f"{self.interface(tunnel_id)}.conf"

    def _sealed(self, tunnel_id: str) -> Path:
        return self.directory / f"{self.interface(tunnel_id)}.cred"

    def _crypt(self, action: str, tunnel_id: str, value: str) -> str:
        """Use the OS host key; secrets are stdin/stdout, never command arguments."""
        command = [
            "/usr/bin/systemd-creds",
            action,
            f"--name={self.interface(tunnel_id)}.conf",
        ]
        if action == "encrypt":
            command.append("--with-key=host")
        command.extend(["-", "-"])
        try:
            return subprocess.run(
                command,
                input=value,
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
            ).stdout
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError(
                "WireGuard credential encryption/decryption failed. Verify systemd-creds and the system host key; secrets were not returned."
            ) from None

    def _open(self, tunnel_id: str) -> str:
        from gannet.util.wireguard import validate_config

        path = self._sealed(tunnel_id)
        if path.is_symlink() or not path.is_file():
            raise ValueError("Saved WireGuard credential not found.")
        config = self._crypt("decrypt", tunnel_id, path.read_text(encoding="utf-8"))
        validate_config(config)
        return config

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

    def _systemctl(
        self, action: str, tunnel_id: str, *, legacy: bool = False
    ) -> subprocess.CompletedProcess:
        self._id(tunnel_id)
        try:
            return subprocess.run(
                [
                    "/usr/bin/systemctl",
                    action,
                    f"{'wg-quick' if legacy else 'gannet-wireguard'}@{self.interface(tunnel_id)}.service",
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
        if (
            value not in ("active", "activating", "deactivating")
            and self._config(tunnel_id).is_file()
        ):
            value = self._systemctl("is-active", tunnel_id, legacy=True).stdout.strip()
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
                if (
                    not self._sealed(tunnel_id).exists()
                    and not self._config(tunnel_id).exists()
                    and all(
                        self.interface(record["id"]) != self.interface(tunnel_id)
                        for record in records
                    )
                ):
                    break
            record = {"id": tunnel_id, "name": name, "routes": routes}
            self._write_private(
                self._sealed(tunnel_id), self._crypt("encrypt", tunnel_id, config)
            )
            try:
                self._write_private(self._metadata(tunnel_id), json.dumps(record))
            except Exception:
                self._sealed(tunnel_id).unlink()
                raise
            return {**record, "status": "stopped"}

    def _migrate_one(self, tunnel_id: str):
        """Called under the management lock; preserve IDs and roll back live routes."""
        from gannet.util.wireguard import validate_config

        legacy = self._config(tunnel_id)
        if legacy.is_symlink():
            raise ValueError("Refusing a symlinked legacy WireGuard configuration.")
        if not legacy.exists():
            return
        config = legacy.read_text(encoding="utf-8")
        validate_config(config)
        if not self._sealed(tunnel_id).exists():
            self._write_private(
                self._sealed(tunnel_id), self._crypt("encrypt", tunnel_id, config)
            )
        if self._open(tunnel_id) != config:
            raise ValueError(
                "Legacy and encrypted tunnel configurations differ; both have been retained for administrator review."
            )
        was_running = self._systemctl(
            "is-active", tunnel_id, legacy=True
        ).stdout.strip() in ("active", "activating")
        # Stop the old unit while its config still exists. wg-quick down needs
        # it. Never delete the original until the replacement is usable.
        self._systemctl("stop", tunnel_id, legacy=True)
        if was_running:
            try:
                self._systemctl("start", tunnel_id)
            except Exception:
                try:
                    self._systemctl("start", tunnel_id, legacy=True)
                except Exception:
                    pass
                raise
        legacy.unlink()

    def migrate(self):
        """Installer-only bulk upgrade of owned stores; never a side effect of GET."""
        if not self.privileged:
            raise RuntimeError("Migration must be run by the installer as root.")
        if not self.directory.exists():
            return
        with FileLock(str(self.directory / "management.lock"), timeout=5):
            for path in sorted(self.directory.glob("*.json")):
                self.get(path.stem)
                self._migrate_one(path.stem)

    def start(self, tunnel_id: str):
        if not self.privileged:
            return self._call("start", tunnel_id)
        self.get(tunnel_id)
        with FileLock(str(self.directory / "management.lock"), timeout=5):
            self._migrate_one(tunnel_id)
            # Check authentication, credential name binding and the no-hooks
            # subset again before PID 1 exposes a runtime-only decrypted copy.
            self._open(tunnel_id)
            self._systemctl("start", tunnel_id)

    def stop(self, tunnel_id: str):
        if not self.privileged:
            return self._call("stop", tunnel_id)
        self.get(tunnel_id)
        with FileLock(str(self.directory / "management.lock"), timeout=5):
            self._systemctl("stop", tunnel_id)
            if self._config(tunnel_id).exists():
                self._systemctl("stop", tunnel_id, legacy=True)

    def delete(self, tunnel_id: str):
        if not self.privileged:
            return self._call("delete", tunnel_id)
        self.get(tunnel_id)
        with FileLock(str(self.directory / "management.lock"), timeout=5):
            self._systemctl("stop", tunnel_id)
            if self._config(tunnel_id).exists():
                self._systemctl("stop", tunnel_id, legacy=True)
                self._config(tunnel_id).unlink()
            self._sealed(tunnel_id).unlink(missing_ok=True)
            self._metadata(tunnel_id).unlink()
