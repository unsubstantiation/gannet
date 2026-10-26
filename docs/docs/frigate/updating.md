---
id: updating
title: Updating
---

# Updating Gannet on Windows

Before updating, back up `%LOCALAPPDATA%\Gannet\config` and any media or database paths overridden through environment variables.

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

For a packaged release, stop Gannet, extract the new bundle over a new application directory, run its bootstrap or installer, and point the service at the new interpreter. Do not delete the data directory. Keep the old application directory until the new version has started and recordings play correctly.

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
5. Start Gannet and inspect the logs under `%LOCALAPPDATA%\Gannet\logs`.
