---
id: updating
title: Updating
---

# Updating Gannet on Windows

Before updating, back up the portable bundle's `data\config` directory (or `%LOCALAPPDATA%\Gannet\config` for a default interactive install) and any media or database paths overridden through environment variables.

## Source checkout installation

From PowerShell in the Gannet checkout:

```powershell
git fetch origin
git checkout dev
git pull --ff-only
py -3.12 bootstrap_windows.py
```

The bootstrap reuses the virtual environment, installs the pinned dependency set, verifies the pinned FFmpeg, go2rtc, and model downloads, rebuilds the web interface when Node.js is installed, and rewrites the launcher.

If Gannet is installed as a Windows service, stop it before updating and start it afterward:

```powershell
Stop-Service Gannet
py -3.12 bootstrap_windows.py --install-service
Start-Service Gannet
```

Run those commands from an elevated PowerShell when changing the service registration.

## Release bundle

For a packaged release, stop Gannet and back up the old bundle's `data\` directory. Extract the new bundle into a new application directory and copy `data\` into it so the new launchers find the existing configuration, database, and media. Keep the old application directory and its data until the new version has started and recordings play correctly.

## Configuration migrations

Gannet backs up and migrates older `config.yml` files at startup. Review release notes before skipping versions. A configuration using a detector, FFmpeg preset, path, or service option removed by the Windows-only release must be updated before startup.

Validate before restarting production:

```powershell
.\.venv\Scripts\python.exe -m gannet --validate-config
```

## Rollback

1. Stop Gannet.
2. Restore the previous application directory and virtual environment.
3. Restore the matching configuration/database backup if the newer version performed an incompatible migration.
4. Reinstall or repoint the Windows service.
5. Start Gannet and inspect `tmp\logs\gannet\current` below its configured data root.
