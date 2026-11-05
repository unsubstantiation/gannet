# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Install verified native Debian runtime assets after dependencies are installed."""

import argparse
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from urllib.request import urlopen

from bootstrap_windows import AUDIO_MODEL, CPU_DETECTION_MODEL
from gannet.util.platform import require_supported_platform

GO2RTC_URL = (
    "https://github.com/AlexxIT/go2rtc/releases/download/v1.9.14/go2rtc_linux_amd64"
)
GO2RTC_SHA256 = "32d616af226bd731678ffde328b94cfb94e30339bfefc469cfb76323144615a6"


def verified_download(
    url: str, destination: Path, digest: str, *, executable: bool = False
):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (
        destination.is_file()
        and hashlib.sha256(destination.read_bytes()).hexdigest() == digest
    ):
        if executable:
            destination.chmod(0o755)
        return
    descriptor, temporary = tempfile.mkstemp(
        dir=destination.parent, prefix=".download-"
    )
    try:
        with (
            os.fdopen(descriptor, "wb") as output,
            urlopen(url, timeout=120) as response,
        ):
            shutil.copyfileobj(response, output)
        if hashlib.sha256(Path(temporary).read_bytes()).hexdigest() != digest:
            raise ValueError("Downloaded runtime asset failed SHA-256 verification.")
        Path(temporary).chmod(0o755 if executable else 0o644)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    require_supported_platform()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir", type=Path, default=Path("/opt/gannet/bin"))
    parser.add_argument("--config-dir", type=Path, default=Path("/etc/gannet"))
    args = parser.parse_args()
    verified_download(
        GO2RTC_URL, args.bin_dir / "go2rtc", GO2RTC_SHA256, executable=True
    )
    for model in (CPU_DETECTION_MODEL, AUDIO_MODEL):
        destination = args.config_dir / model.dest_subdir / model.filename
        # Preserve existing administrator-provided models on upgrade.
        if not destination.exists():
            verified_download(model.url, destination, model.expected_sha256)


if __name__ == "__main__":
    main()
