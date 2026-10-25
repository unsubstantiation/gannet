# Building the portable bundle

`scripts/build_portable.py` produces one ZIP that runs on a 64-bit Windows machine
with nothing installed: no Python, no pip, no network, no administrator rights. It
is the counterpart to `bootstrap_windows.py`, which installs the application onto a
machine that already has CPython 3.12.

This document is about producing that ZIP. To run the application from a checkout
instead, see [`WINDOWS_COMPATIBILITY.md`](WINDOWS_COMPATIBILITY.md) and the
[Windows installation guide](docs/docs/frigate/installation.md#windows).

| | |
| --- | --- |
| Entry point (local) | `pwsh scripts/build_portable.ps1` |
| Entry point (CI) | `.github/workflows/windows-release.yml` calls the same script |
| Output | `dist/GannetNVR-<version>-win64.zip` |
| Typical size | 400-700 MiB (dominated by TensorFlow, OpenVINO and ONNX Runtime) |
| Runtime contract | Windows 10/11 or Server, x64. Nothing else runs it. |

## What a build is, and what it is not

It **is** a portable application directory, archived:

- the application tree exactly as a checkout has it,
- a 64-bit CPython 3.12 embeddable interpreter,
- every wheel from `requirements.txt`, installed for a Windows target,
- FFmpeg, go2rtc, and the two pinned TFLite models,
- the licensing and provenance files that redistribution requires.

It is **not** an installer, a service, or an auto-updating application. There is no
`.exe` setup, no Start Menu entry, no uninstaller, and no code signing. Extract it,
run it, delete the folder to remove it. `bootstrap_windows.py --install-service`
remains the way to run as a Windows service, and it expects a checkout with a real
Python install, not this bundle. The winget manifest is generated from the build
but is a template until someone runs `winget validate` and submits it.

## Prerequisites

| Requirement | Why | Notes |
| --- | --- | --- |
| Python 3.10 or newer on the build host | runs the builder and pip | The host does **not** need to be 3.12; wheels are resolved for the target, not the host |
| Node.js 22 or newer | `npm ci` and `npm run build:native` | Skip with `-SkipWeb` if `web/dist` already exists |
| Network access | PyPI, python.org, GitHub release assets | Only on the first build; `dist/.cache` keeps every download |
| ~4 GiB free disk | wheels, staging tree, and archive | `dist/` holds the cache, the staging tree, and the ZIP |
| Windows x64 | to *verify* the result | Building works on POSIX; running does not |

## Quick start

```powershell
pwsh scripts/build_portable.ps1
```

The first build records the CPython embeddable digest in
`scripts/python_embed_pin.json` and prints it. **Check that digest against
python.org and commit the file** — from then on every build verifies it. A release
build passes `-RequirePinned`, which fails instead of trusting an unrecorded
digest:

```powershell
pwsh scripts/build_portable.ps1 -RequirePinned
```

Useful flags:

| Flag | Effect |
| --- | --- |
| `-Version X.Y.Z` | override the `pyproject.toml` version |
| `-PlanOnly` | print the plan and exit; no network, no disk writes |
| `-SkipWeb` | reuse the existing `web/dist` instead of building |
| `-SkipWheels` | skip the requirement install (the result will not start) |
| `-SkipArtifacts` | skip FFmpeg, go2rtc, and the models (the result will not start) |
| `-PythonZip PATH` | use a local embeddable archive instead of downloading |
| `-Requirements PATH` | swap the requirements file, for testing |
| `-KeepStaging` | leave `dist/.staging` in place for inspection |
| `-VerboseOutput` | echo every pip command |

`dist/` after a successful build:

```
GannetNVR-0.19.0-win64.zip           the bundle
GannetNVR-0.19.0-win64.zip.sha256    "<sha256>  <name>"
SHA256SUMS.txt                        same line, ready for a release asset
RELEASE-NOTES.md                      release body, with the digest and a table
unsubstantiation.GannetNVR.yaml        winget manifest, tokens already filled
.staging/                             removed unless -KeepStaging
.cache/                               downloads and built wheels, reused next time
```

## What is inside the archive

```
GannetNVR-<version>-win64/
  app/                          the source root, in its checkout layout
    frigate/                    the application package
    migrations/                 database migrations (resolved from the cwd)
    web/dist/                   the built front end
    ffmpeg/                     ffmpeg.exe, ffprobe.exe
    bin/                        go2rtc.exe
    model_cache/                cpu_model.tflite, cpu_audio_model.tflite
    config/config.yml.example   a starting point, never a live config
    labelmap.txt, audio-labelmap.txt
    LICENSE, LICENSES/, THIRD_PARTY.md, LICENSING.md, DEPENDENCIES.md, REUSE.toml
  python/                       CPython 3.12 embeddable
    python.exe, python312.zip, python312._pth
    Lib/site-packages/          every wheel, plus frigate_nvr-<version>.dist-info
  run_gannet.ps1                the launcher
  run_gannet.cmd                double-clickable shim
  BUILD-INFO.json               exact versions and digests this bundle was built from
  SOURCE-OFFER.txt              where to get the source of the binaries above
```

### Why the layout is not negotiable

Each of these is a lookup the application performs at runtime, so a rename breaks
the bundle in a way that only shows up on Windows:

| Path | Read by | Consequence if moved |
| --- | --- | --- |
| `app/frigate/util/platform.py` at depth 2 under the root | `get_source_root()` (`parents[2]`) | install dir, labelmaps, and web dir all resolve elsewhere |
| `app/web/dist/index.html` | `get_web_dir()` + `web_dir_has_build()` | the UI serves "The Frigate web app is not built" and the API still works |
| Working directory `app/` | peewee-migrate's `Router` | the database is created empty and startup fails on first table access |
| `app/ffmpeg/` | `get_ffmpeg_dir()` fallback | FFmpeg is not found and streams fail |
| `app/bin/` | `find_executable()` candidate list | go2rtc is not found and restreaming fails |
| `python/python312._pth` | CPython's path configuration | `import frigate` fails, because `..\app` is what puts it on `sys.path` |

`scripts/build_portable.py` asserts all of these after staging and before writing
the archive, so a change in the application that breaks the mapping fails the
build rather than the first launch.

### The launcher

`run_gannet.ps1` is modelled on the launcher `bootstrap_windows.py` generates, and
differs only in where it finds Python:

1. resolves the bundle root from its own location, so the archive can be extracted
   anywhere writable;
2. seeds `model_cache/*.tflite` into `%LOCALAPPDATA%\Frigate\config\model_cache`
   when a file is absent, so an upgraded model is never overwritten;
3. sets `PYTHONUTF8=1`, because the application reads and writes UTF-8;
4. runs `python.exe -m frigate` **with the working directory set to `app`**;
5. restarts only when Frigate wrote `restart.requested` in the tmp directory, so
   Ctrl+C and closing the window still stop it.

`-BaseDir <path>` keeps the writable data somewhere other than
`%LOCALAPPDATA%\Frigate`. The bundle itself is never written to.

## First run

1. Extract the ZIP to a writable location, for example
   `%LOCALAPPDATA%\Programs\GannetNVR`. Do not extract into `C:\Program Files`.
2. Run `run_gannet.ps1` from that folder, or double-click `run_gannet.cmd`.
3. Open <http://localhost:8971>. The generated administrator password is written
   to the log on first start.
4. Data appears in `%LOCALAPPDATA%\Frigate`: `config/`, `media/`, `cache/`, `tmp/`.

The first launch is slower than later ones because CPython compiles the installed
packages to bytecode as they are imported. Nothing is precompiled at build time:
bytecode is tied to the interpreter's magic number, and a build host that is not
3.12 would write files the bundled interpreter must ignore.

## Supply chain and pinning

| Input | Pinned by | Verified |
| --- | --- | --- |
| Python dependencies | `requirements.txt` (`== X.Y.*`) | wheel tags for cp312 win_amd64; `--only-binary=:all:` means no sdist builds |
| CPython embeddable | `scripts/python_embed_pin.json` | SHA-256 on every build once recorded; first use records it |
| FFmpeg, go2rtc, models | `bootstrap_windows.py` | SHA-256 enforced from the artifact constants imported by the builder, so an install and a bundle can never disagree about which build they contain |
| npm packages | `web/package-lock.json` | `npm ci` |

The CPython digest is the one input whose upstream value python.org does not
publish for a security-only 3.12 release: there is no install-manager manifest for
3.12.15. `python_embed_pin.json` is therefore trust-on-first-use, exactly like the
bootstrap's own bookkeeping for artifacts without a pinned digest. Record it once,
commit it, and let CI fail closed from then on.

### Reproducibility

The archive is deterministic: sorted entries, fixed 1980-01-01 timestamps, no
filesystem metadata, and no bytecode. Two builds of the same tree with the same
cache produce the same SHA-256, which was verified by building twice.

It is *not* bit-reproducible over time, and cannot be while `requirements.txt`
pins minor series: `numpy == 1.26.*` installs whatever the newest 1.26 patch is on
the day of the build. If a release must be rebuilt identically later, the wheels
in `dist/.cache` are the only way to get the same bytes — or the requirements need
exact pins, which is a separate decision with its own tradeoffs (see
[`DEPENDENCIES.md`](DEPENDENCIES.md) §7.1).

## Releasing

1. Bump `version` in `pyproject.toml` and commit it.
2. Tag and push:

   ```powershell
   git tag v0.19.0
   git push origin v0.19.0
   ```

3. `.github/workflows/windows-release.yml` builds on `windows-latest` with
   `-RequirePinned`, uploads the ZIP and checksums as a workflow artifact, and
   attaches them plus `RELEASE-NOTES.md` and the filled winget manifest to the
   release for that tag. Re-running the job is safe: it attaches with `--clobber`.
4. A `workflow_dispatch` run builds without publishing unless `publish` is set.

The version comes from `pyproject.toml`, and the build fails if the built wheel
disagrees with it. `frigate/util/version.py` reads that metadata at runtime, so the
version shown in the UI is the version the bundle carries.

The bundle name carries the version too, so the winget manifest the build writes
already points at the asset the release will have. `winget validate` is still a
human step, and the manifest documents the one open question: winget's `portable`
nested installer expects an executable, while this bundle's entry point is
`run_gannet.cmd`.

## Licensing of what you redistribute

A bundle you hand to someone else is a distribution, and it carries more
obligations than running the app yourself. Everything below ships inside the ZIP:

| Component | License | What distribution requires |
| --- | --- | --- |
| FFmpeg 8.1.2 (x264/x265 enabled) | GPL-2.0-or-later as built | Corresponding source must be available. `SOURCE-OFFER.txt` states the exact build, digest, and source locations; do not strip it |
| CPython 3.12 embeddable | PSF-2.0 | Keep the license and notice; unmodified |
| Unidecode | GPL-2.0-or-later | Source availability; see `DEPENDENCIES.md` §6 for the MIT alternative |
| py-vapid, pywebpush | MPL-2.0 | Nothing unless those files are modified |
| Everything else | permissive (MIT/Apache/BSD/ISC) | copyright and NOTICE retention |
| Gannet Material (`frigate/`, docs) | GNCL-1.0, noncommercial | Not open source; see [`LICENSING.md`](LICENSING.md) |

The project's own noncommercial terms never applied to FFmpeg, CPython, or any
wheel, and cannot be used to narrow them. `BUILD-INFO.json` records every Python
distribution and its version that the bundle actually contains, which is what a
downstream packager needs to reconstruct the obligations.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `does not match the pinned sha256` for CPython | upstream re-published, or a stale cached archive | delete `dist/.cache/python-*.zip`; if upstream really changed, update `python_embed_pin.json` deliberately |
| `No matching distribution found for ...` | a pinned version does not exist on the index the build host reaches | the pins are the project's contract; check `requirements.txt` against the index before blaming the builder |
| `npm is not on PATH` | Node missing or too old | install Node 22+, or pass `-SkipWeb` with an existing `web/dist` |
| Build succeeds, UI says "web app is not built" | `web/dist` was not a production build | the builder rejects the Vite dev entry; delete `web/dist` and rebuild |
| `import frigate` fails on first run | `python312._pth` lost its `..\app` line, or the tree was re-zipped | re-extract the original archive; this is why the builder asserts the `._pth` contents |
| Startup fails on a missing table | extracted tree started from the wrong working directory | launch through `run_gannet.ps1`; it sets the working directory to `app` |
| `win32service` / `pywintypes` import error | `pywintypes312.dll` is not next to `python.exe` | the builder copies it from `pywin32_system32`; a re-zipped tree that dropped it will fail |
| Antivirus quarantines the archive | unsigned executables in a ZIP | expected for unsigned builds; ship a signature or document the exclusion |

## Changing dependencies

`requirements.txt` drives the bundle, so the usual rules apply: see
[`AGENTS.md`](AGENTS.md) for what a change may touch, then regenerate the derived
files.

```powershell
pip install -r requirements.txt          # confirm the set still resolves
python scripts/license_audit.py          # refresh THIRD_PARTY.md's license table
python testing-scripts/check_windows_requirements.py
```

Then update [`DEPENDENCIES.md`](DEPENDENCIES.md) by hand — nothing generates it —
and rebuild. Nothing in this document needs to change unless a new runtime lookup
or a new redistributed binary appears.
