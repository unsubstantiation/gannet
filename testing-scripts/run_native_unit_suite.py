# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Run all unit tests without downloading inference models during validation.

Tests of successful/failed downloads install their own mocks, overriding this
outer offline guard. Live camera/driver/systemd tests remain separate acceptance
checks; this runner does not certify hardware or a production installation.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _offline_download(*args, **kwargs):
    # Raise a fresh exception each time: reusing an exception object retains
    # every earlier traceback and makes large suites progressively expensive.
    raise OSError("Model downloads are disabled in the offline unit suite.")


def main() -> int:
    with patch(
        "gannet.config.config.urlopen",
        side_effect=_offline_download,
    ):
        suite = unittest.defaultTestLoader.discover(
            str(ROOT / "gannet/test"), top_level_dir=str(ROOT)
        )
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
