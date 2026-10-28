# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""List or acquire hardware-compatible Windows ML execution providers."""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from gannet.detectors.windows_ml import (  # noqa: E402
    ensure_provider_ready,
    experimental_webgpu_enabled,
)


def list_providers() -> int:
    """Print the Windows ML providers compatible with this machine."""
    try:
        from windowsml import EpCatalog
    except (ImportError, OSError) as err:
        print(
            "Windows ML is not available. Install the Windows ML extra and use "
            "Windows 11 24H2 or later.",
            file=sys.stderr,
        )
        print(err, file=sys.stderr)
        return 1

    try:
        with EpCatalog() as catalog:
            providers = catalog.find_all_providers()
            if not providers:
                print("No compatible Windows ML providers found.")
                return 0
            for provider in providers:
                state = getattr(provider.ready_state, "name", str(provider.ready_state))
                label = (
                    " [experimental; requires explicit opt-in]"
                    if provider.name == "WebGpuExecutionProvider"
                    else ""
                )
                print(f"{provider.name}\t{provider.version}\t{state}{label}")
    except Exception as err:
        print(f"Could not query the Windows ML catalog: {err}", file=sys.stderr)
        return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list providers compatible with this PC")
    install = commands.add_parser(
        "install", help="download and prepare a compatible provider"
    )
    install.add_argument(
        "provider",
        nargs="?",
        help="exact Windows ML provider name; use --all to install every compatible provider",
    )
    install.add_argument(
        "--all",
        action="store_true",
        help="install every compatible provider returned by the Windows catalog",
    )
    args = parser.parse_args(argv)

    if os.name != "nt":
        print(
            "Windows ML provider management only runs on native Windows.",
            file=sys.stderr,
        )
        return 1

    if args.command == "list":
        return list_providers()

    if args.all == bool(args.provider):
        parser.error("install requires exactly one provider name or --all")

    if args.all:
        try:
            from windowsml import EpCatalog

            with EpCatalog() as catalog:
                names = [
                    provider.name
                    for provider in catalog.find_all_providers()
                    if provider.name != "WebGpuExecutionProvider"
                    or experimental_webgpu_enabled()
                ]
        except Exception as err:
            print(f"Could not query the Windows ML catalog: {err}", file=sys.stderr)
            return 1
    else:
        names = [args.provider]

    if "WebGpuExecutionProvider" in names and not experimental_webgpu_enabled():
        print(
            "WebGPU is experimental. Set FRIGATE_ENABLE_EXPERIMENTAL_WEBGPU=1 "
            "before installing or running Gannet to opt in.",
            file=sys.stderr,
        )
        return 1

    failed = False
    for name in names:
        try:
            installed_name, state = ensure_provider_ready(name)
            print(f"{installed_name}: {state}")
        except Exception as err:
            print(f"{name}: {err}", file=sys.stderr)
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
