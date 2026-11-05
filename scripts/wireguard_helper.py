# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Isolated entry point for the Debian sudo helper; never print submitted keys."""

import argparse
import json
import sys

# Invoked by a root-owned wrapper with python -I; ignore Python environment
# variables and import only the root-owned installation, not the caller's cwd.
sys.path.insert(0, "/opt/gannet")

from gannet.util.platform import require_supported_platform  # noqa: E402
from gannet.util.wireguard_debian import DebianWireGuardManager  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "list",
            "get",
            "status",
            "create",
            "start",
            "stop",
            "delete",
            "migrate",
        ),
    )
    parser.add_argument("tunnel_id", nargs="?", default="")
    args = parser.parse_args()
    try:
        require_supported_platform()
        raw = sys.stdin.buffer.read(131073)
        if len(raw) > 131072:
            raise ValueError("Request is too large.")
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            raise ValueError("Invalid helper request.") from None
        manager = DebianWireGuardManager(privileged=True)
        if args.action == "create":
            if (
                not isinstance(body, dict)
                or not isinstance(body.get("name"), str)
                or not isinstance(body.get("config"), str)
            ):
                raise ValueError("Tunnel name and configuration are required.")
            result = manager.create(body["name"], body["config"])
        elif args.action == "migrate":
            result = manager.migrate()
        elif args.action == "list":
            result = manager.list()
        else:
            result = getattr(manager, args.action)(args.tunnel_id)
        print(json.dumps({"result": result}))
    except ValueError as error:
        print(json.dumps({"error": str(error)}))
    except Exception:
        print(
            json.dumps(
                {
                    "error": "WireGuard helper failed; verify systemd, permissions, and the WireGuard tools installation.",
                    "retry": True,
                }
            )
        )


if __name__ == "__main__":
    main()
