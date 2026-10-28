---
id: common_errors
title: Common Errors
---

# Common Windows errors

Start with `%LOCALAPPDATA%\Gannet\tmp\logs\gannet\current` for an interactive install or `%ProgramData%\Gannet\tmp\logs\gannet\current` for the default service install. If another base directory was selected, use the same `tmp\logs\gannet\current` path below that root.

## Gannet requires 64-bit Windows and CPython 3.12

The native runtime intentionally refuses unsupported operating systems, architectures, and Python versions. Verify:

```powershell
py -3.12 -c "import platform,struct; print(platform.platform()); print(struct.calcsize('P') * 8)"
```

Run `bootstrap_windows.py` with that interpreter. A Microsoft Store alias or 32-bit Python is not supported.

## FFmpeg or go2rtc executable not found

Rerun the bootstrap from the repository root:

```powershell
py -3.12 bootstrap_windows.py --skip-web
```

Do not rename downloaded files. Antivirus quarantine, an incomplete archive, or changing `GANNET_BASE_DIR` after installation are common causes. Gannet checks executable names and rejects a directory where a file is required.

## Port 8971 is already in use

Find the owner from an elevated PowerShell session:

```powershell
Get-NetTCPConnection -LocalPort 8971 -State Listen |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

Stop the conflicting process or change `networking.listen.external`. The external and internal ports must differ. Port `5000` remains loopback-only.

## The service starts and immediately stops

Run these commands from an elevated shell:

```powershell
Get-Service Gannet
Get-WinEvent -LogName Application -MaxEvents 50 |
  Where-Object ProviderName -Match 'Gannet|Python'
Get-Content "$env:ProgramData\Gannet\tmp\logs\gannet\current" -Tail 200
```

Typical causes are an invalid config, a missing service environment variable, a data-directory ACL that excludes the service account, or a partial TLS certificate pair. Validate using the service installation's interpreter and environment.

## The app keeps restarting ("the process resets")

A restart is not always a crash. Gannet writes `tmp\restart.requested` when the
UI or API asks for a restart, or when the watchdog sees a detector process die;
the launcher then starts the whole application again. Current builds also record
every restart — with the child's exit code and the reason from the marker — in
`tmp\logs\launcher.log`, and back off briefly after five restarts in two minutes.
The 0.19.0 bundle predates that log, so use the application log and the event
log there:

```powershell
$Data = if ($env:GANNET_BASE_DIR) { $env:GANNET_BASE_DIR } `
        elseif ($env:FRIGATE_BASE_DIR) { $env:FRIGATE_BASE_DIR } `
        else { Join-Path $env:LOCALAPPDATA 'Gannet' }
Get-Content (Join-Path $Data 'tmp\logs\launcher.log') -Tail 50 -ErrorAction SilentlyContinue
Get-Content (Join-Path $Data 'tmp\logs\gannet\current') -Tail 200
Get-Content (Join-Path $Data 'tmp\logs\gannet\current.1') -Tail 200 -ErrorAction SilentlyContinue
```

New builds write the application log to `tmp\logs\gannet\current`; older
builds used `tmp\logs\frigate\current`. If you upgraded from an older build
without setting `GANNET_BASE_DIR`, the new process is reading the new
`%LOCALAPPDATA%\Gannet` tree — set the variable to the legacy
`%LOCALAPPDATA%\Gannet` path to see the logs from the install that has been
running.

The application log is a rotating 5 MiB file; `current.1` and `current.2` hold
the previous runs, which is where the first failure of a fast restart loop ends
up. Look for `Detection appears to have stopped: detector ... exited with code N`:
that is a detector subprocess dying (commonly a missing model file, an
unavailable inference device, or a failing native runtime) and the watchdog
restarting everything. Repeated `config saved with restart option` or
`restart command received over inter-process comms` reasons point at an UI or
automation loop instead.

If there is no Python traceback, check the Windows Application event log for a
native crash of `python.exe` or one of the inference runtimes:

```powershell
Get-WinEvent -FilterHashtable @{LogName='Application'; StartTime=(Get-Date).AddDays(-1)} |
  Where-Object { $_.LevelDisplayName -in @('Error','Critical') -and
                 $_.Message -match 'python|GannetNVR|go2rtc|ffmpeg|onnxruntime|openvino' } |
  Select-Object -First 20 TimeCreated, ProviderName, Id, Message | Format-List
```

When you start the portable bundle with `python\GannetNVR.exe` directly, its
console messages disappear as soon as the window closes. Start `GannetNVR.cmd`
from the bundle root instead, or redirect the output to a file, so the restart
messages are kept.

## Permission denied or database cannot be opened

The service account needs Modify permission on config, media, cache, temporary, and log directories. Keep `gannet.db` on local NTFS. Mapped drive letters from an interactive user are not available to a service; use a UNC path with explicit account permissions only for non-database storage.

## Database is locked

Do not run two Gannet instances against one database. Stop the service before launching an interactive copy. Antivirus, backup, and indexing tools can hold SQLite sidecar files; configure exclusions only if permitted by your security policy. Never put the database on SMB or another network filesystem.

## TLS certificate or private key error

`tls.cert_file` and `tls.key_file` must either both exist or both be absent. When both are absent, Gannet generates a self-signed pair. Custom files must be unencrypted PEM and readable by the service account.

If Gannet starts but a client rejects HTTPS, install a certificate with the hostname in its Subject Alternative Name and a chain trusted by that client.

## Camera has no frames

Test the exact stream from the Gannet host:

```powershell
& "$env:LOCALAPPDATA\Gannet\ffmpeg\bin\ffplay.exe" `
  'rtsp://user:password@camera/stream'
```

Then check DNS, Windows Firewall, credentials, camera connection limits, and codec support. Start without hardware acceleration. Add a Windows acceleration preset only after software decoding works.

## Hardware acceleration initialization failed

Update the display driver, confirm the GPU appears in Device Manager, and choose a preset reported by **System > Hardware**. Remote Desktop and virtual machines may expose a different adapter from a local session. See [GPU troubleshooting](./gpu.md).

## Detector is not running

The configured device must be present in the hardware probe. Native Windows supports CPU TFLite, OpenVINO, ONNX Runtime, and external ZMQ detectors. ONNX models need a compatible execution provider and explicit model path. Review [Object Detectors](/configuration/object_detectors).

## Configuration contains an unsupported preset or path

Validation rejects Unix device paths, sockets, unsupported detector names, and non-Windows FFmpeg backends. Replace copied configuration rather than attempting to pass a Linux device or argument through unchanged.

```powershell
.\.venv\Scripts\python.exe -m gannet --validate-config
```

## Long path or reserved-name error

Keep `GANNET_BASE_DIR` short and enable Windows long-path support. Camera names are case-insensitive and cannot use reserved device names such as `CON`, `PRN`, `AUX`, `NUL`, `COM1`, or `LPT1`.

## Recording errors

See [Recording troubleshooting](./recordings.md) for timestamp, codec, disk, retention, and segment problems. Do not delete database rows or recording files while Gannet is running.
