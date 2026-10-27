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
| Output | `dist/GannetNVR-<version>-win64.zip` |
| Entry point (in the ZIP) | `GannetNVR.cmd` or `python\GannetNVR.exe` |
| Typical size | ~875 MiB for 0.19.0 (dominated by TensorFlow, OpenVINO and ONNX Runtime) |
| Runtime contract | Windows 10/11 or Server, x64. Nothing else runs it. |

## What a build is, and what it is not

It **is** a portable application directory, archived:

- the application tree exactly as a checkout has it,
- a 64-bit CPython 3.12 embeddable interpreter,
- every wheel from `requirements.txt`, installed for a Windows target,
- FFmpeg, go2rtc, and the two pinned TFLite models,
- the licensing and provenance files that redistribution requires.

It **is** launchable from a real executable. `python\GannetNVR.exe` is a native
PE binary and `GannetNVR.cmd` at the archive root is a double-clickable shim for
it. No compiler is needed to produce it: it is a byte-identical copy of the
pinned CPython `python.exe`, turned into an application launcher by a `.pth`
hook (see [The .exe launcher](#the-exe-launcher)).

It is **not** an installer, a service, or an auto-updating application. There is
no `.exe` setup program, no Start Menu entry, no uninstaller, and no code signing
of Gannet's own code. Extract it, run it, delete the folder to remove it.
`bootstrap_windows.py --install-service` remains the way to run as a Windows
service, and it expects a checkout with a real Python install, not this bundle.
The winget manifest is generated from the build but is a template until someone
runs `winget validate` and submits it.

## Prerequisites

| Requirement | Why | Notes |
| --- | --- | --- |
| Python 3.10 or newer on the build host | runs the builder and pip | The host does **not** need to be 3.12; wheels are resolved for the target, not the host |
| Node.js 22 or newer | `npm ci` and `npm run build:native` | Skip with `-SkipWeb` if `web/dist` already exists |
| **No C/C++ compiler** | the `.exe` is a copy of the pinned interpreter, not a compiled stub | Keeps the build reproducible on a plain Windows host |
| Network access | PyPI, python.org, GitHub release assets | Only on the first build; `dist/.cache` keeps every download |
| ~4 GiB free disk | wheels, staging tree, and archive | `dist/` holds the cache, the staging tree, and the ZIP |
| Windows x64 | the supported build host, and the only host that can *verify* the result | The builder also runs on POSIX, but pip evaluates dependency environment markers (`sys_platform` and friends) for the build host, so a POSIX build can resolve a different dependency set than the Windows target. Release bundles are built on Windows |

## Quick start

```powershell
pwsh scripts/build_portable.ps1
```

Every build verifies the CPython embeddable download against the SHA-256
committed in `scripts/python_embed_pin.json` (see
[Supply chain and pinning](#supply-chain-and-pinning) for where that digest
comes from). A release build passes `-RequirePinned`, which fails if the pin is
ever blank instead of recording a fresh digest from whatever was downloaded:

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
    gannet/                     the application package
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
    GannetNVR.exe               byte-identical copy of python.exe: the .exe entry point
    GannetNVR._pth              same path seed, named after the exe as a fallback
    Lib/site-packages/          every wheel, plus frigate_nvr-<version>.dist-info
      gannet_launcher.pth       imports the launcher module while site is set up
      gannet_launcher.py        the Python launcher logic
  GannetNVR.cmd                 double-clickable shim for python\GannetNVR.exe
  run_gannet.ps1               the PowerShell launcher (restart loop, model seeding)
  run_gannet.cmd               its double-clickable shim
  BUILD-INFO.json               exact versions and digests this bundle was built from
  SOURCE-OFFER.txt              where to get the source of the binaries above
```

### Why the layout is not negotiable

Each of these is a lookup the application performs at runtime, so a rename breaks
the bundle in a way that only shows up on Windows:

| Path | Read by | Consequence if moved |
| --- | --- | --- |
| `app/gannet/util/platform.py` at depth 2 under the root | `get_source_root()` (`parents[2]`) | install dir, labelmaps, and web dir all resolve elsewhere |
| `app/web/dist/index.html` | `get_web_dir()` + `web_dir_has_build()` | the UI serves "The Gannet web app is not built" and the API still works |
| Working directory `app/` | peewee-migrate's `Router` | the database is created empty and startup fails on first table access |
| `app/ffmpeg/` | `get_ffmpeg_dir()` fallback | FFmpeg is not found and streams fail |
| `app/bin/` | `find_executable()` candidate list | go2rtc is not found and restreaming fails |
| `python/python312._pth` | CPython's path configuration | `import gannet` fails, because `..\app` is what puts it on `sys.path` |
| `python/GannetNVR.exe` next to `python312.dll` | the Windows loader | the copy cannot start: its import table resolves `python312.dll` beside the executable |
| `python/Lib/site-packages/gannet_launcher.pth` | `site` during interpreter startup | `GannetNVR.exe` starts an interactive REPL instead of the application |
| `python/GannetNVR._pth` | CPython's `._pth` probe for a renamed executable | a future interpreter that probes the exe name first finds no path seed |

`scripts/build_portable.py` asserts all of these after staging and before writing
the archive, so a change in the application that breaks the mapping fails the
build rather than the first launch.

### The .exe launcher

`python/GannetNVR.exe` is an **unmodified copy** of `python.exe` from the pinned
CPython 3.12.10 embeddable archive. That is the whole reason no compiler appears
in the prerequisites: the archive is already a native x64 PE executable, its
SHA-256 is committed in `scripts/python_embed_pin.json`, and copying it keeps
upstream's Authenticode signature intact. `BUILD-INFO.json` records the digest
of the copy under `launcher`.

A copy of `python.exe` is still just an interpreter, so a few small text files
turn it into an application launcher:

1. `python/python312._pth` and `python/GannetNVR._pth` carry the same path seed:
   `python312.zip`, `python/`, site-packages and `..\app`, ending with
   `import site`. Two names cover both ways CPython probes for a `._pth` file.
2. `site` processes `gannet_launcher.pth`, whose one active line is
   `import gannet_launcher`.
3. `gannet_launcher.py` checks the running executable. For `python.exe`,
   `pythonw.exe` and the other interpreter names it returns immediately, so the
   application and every `spawn`ed worker are unaffected. For `GannetNVR.exe`
   (or a copy launched under another name) it starts `python.exe -m gannet` and
   calls `os._exit` before CPython reaches its own main loop.

That module implements the same contract as the PowerShell launcher: seed
`app/model_cache/*.tflite` into the writable data directory only when absent,
set `PYTHONUTF8=1`, run with the working directory set to `app/`, forward Gannet's
arguments, loop only while `restart.requested` exists, and propagate the exit
code. The app itself always runs under `python.exe`, so `sys.executable` and
multiprocessing stay the same as a checkout install.

**Arguments.** CPython parses its own command-line options before `site` runs,
so application flags must follow `--` when the exe is invoked directly. The
`GannetNVR.cmd` shim already inserts that separator, so do not add a second
one:

```powershell
.\GannetNVR.cmd --validate-config
.\python\GannetNVR.exe -- --validate-config   # the exe directly
```

With no arguments, either entry point just starts Gannet. Use the
`FRIGATE_BASE_DIR` environment variable to move the writable data directory
(`run_gannet.ps1 -BaseDir <path>` is the PowerShell equivalent). The launcher
recognises any renamed copy of the interpreter (winget installs the command as
`GannetNVR`), so don't rename `python.exe` for other purposes inside the bundle.
The winget command runs through `PATH`, not a symlink, because Windows resolves
an executable's private DLLs next to the symlink rather than its target; see
[Releasing](#releasing).

### The PowerShell launcher

`run_gannet.ps1` is modelled on the launcher `bootstrap_windows.py` generates, and
differs only in where it finds Python:

1. resolves the bundle root from its own location, so the archive can be extracted
   anywhere writable;
2. seeds `model_cache/*.tflite` into `%LOCALAPPDATA%\Frigate\config\model_cache`
   when a file is absent, so an upgraded model is never overwritten;
3. sets `PYTHONUTF8=1`, because the application reads and writes UTF-8;
4. runs `python.exe -m gannet` **with the working directory set to `app`**;
5. restarts only when Gannet wrote `restart.requested` in the tmp directory, so
   Ctrl+C and closing the window still stop it.

`-BaseDir <path>` keeps the writable data somewhere other than
`%LOCALAPPDATA%\Frigate`. The bundle itself is never written to.

## First run

1. Extract the ZIP to a writable location, for example
   `%LOCALAPPDATA%\Programs\GannetNVR`. Do not extract into `C:\Program Files`.
2. Double-click `GannetNVR.cmd` (or `python\GannetNVR.exe` directly). Both run
   the bundled interpreter as a real Windows executable; `run_gannet.ps1` and
   `run_gannet.cmd` remain as a PowerShell alternative.
3. Open <https://localhost:8971> and accept the first-run warning for the
   generated self-signed certificate. The generated administrator password is
   printed on first start and recorded in
   `%LOCALAPPDATA%\Frigate\tmp\logs\frigate\current`.
4. Data appears in `%LOCALAPPDATA%\Frigate`: `config/`, `media/`, `cache/`, `tmp/`.

The first launch is slower than later ones because CPython compiles the installed
packages to bytecode as they are imported. Nothing is precompiled at build time:
bytecode is tied to the interpreter's magic number, and a build host that is not
3.12 would write files the bundled interpreter must ignore.

## Supply chain and pinning

| Input | Pinned by | Verified |
| --- | --- | --- |
| Python dependencies | `requirements.txt` (`== X.Y.*`) | wheel tags for cp312 win_amd64; `--only-binary=:all:` means no sdist builds |
| CPython embeddable | `scripts/python_embed_pin.json` | SHA-256 verified on every build against the committed pin |
| `python/GannetNVR.exe` | same pinned archive | `verify_layout` asserts it is byte-identical to `python.exe`; `BUILD-INFO.json` records its digest |
| FFmpeg, go2rtc, models | `bootstrap_windows.py` | SHA-256 enforced from the artifact constants imported by the builder, so an install and a bundle can never disagree about which build they contain |
| npm packages | `web/package-lock.json` | `npm ci` |

### Why the embedded interpreter is 3.12.10

Under [PEP 693](https://peps.python.org/pep-0693/), 3.12.10 is the last full
maintenance release of the 3.12 series; 3.12.11 and later are security releases
published **as source only**. Their python.org directories contain nothing but
the source tarballs — there is no `python-3.12.15-embed-amd64.zip`, no Windows
installer, and no install-manager manifest. 3.12.10 is therefore the newest
embeddable package CPython publishes in the only series this application
supports, and it is also what `bootstrap_windows.py` users get when they
install 3.12 from python.org today, so the bundle and a checkout run the same
interpreter patch level.

The tradeoff should be stated plainly: the bundled interpreter does not have
the standard-library security fixes that landed in 3.12.11–3.12.15. Closing
that gap means building the embeddable package from the signed CPython source
on a supported build host, or embedding a third-party standalone build; both change who produces
the interpreter binary and need their own provenance story, so neither is
smuggled into a version bump here.

The pinned digest is quoted from upstream, not trust-on-first-use: it is the
SHA-256 in the Sigstore bundle python.org ships beside the file
(`python-3.12.10-embed-amd64.zip.sigstore`, signed by the 3.12 release
manager's `th@python.org` identity and logged in Rekor); the release page's
MD5 for the same file is a second, weaker cross-check. The pin is committed,
so the local build fails closed if the download ever differs.

### Reproducibility

The archive is written deterministically: sorted entries, fixed 1980-01-01
timestamps, no filesystem metadata, and no bytecode, so two builds of the same
tree with the same inputs are expected to produce the same SHA-256. The `.exe`
does not weaken that: it is copied from the pinned archive rather than compiled
on the build host, so it carries no compiler version, timestamp, or machine ID.
Treat that
as a property to spot-check (build twice, compare `SHA256SUMS.txt`) rather than
a guarantee: no automated check asserts it, and a tool that embeds a build stamp in
one of the staged files would break it silently.

It is *not* bit-reproducible over time, and cannot be while `requirements.txt`
pins minor series: `numpy == 1.26.*` installs whatever the newest 1.26 patch is on
the day of the build. If a release must be rebuilt identically later, the wheels
in `dist/.cache` are the only way to get the same bytes — or the requirements need
exact pins, which is a separate decision with its own tradeoffs (see
[`DEPENDENCIES.md`](DEPENDENCIES.md) §7.1).

## Building in CI (a downloadable build without a local Windows host)

`.github/workflows/windows-release.yml` runs the same
`pwsh scripts/build_portable.ps1 -RequirePinned` command on a `windows-latest`
GitHub Actions runner. It has full network access to python.org, the pinned
GitHub release assets, and the model hosts, so it can produce the real ~875 MiB
bundle that a network-restricted machine cannot.

- Push a `v*` tag at any commit to build **and publish** a pre-release with the
  ZIP, its checksums, release notes, and the winget manifest attached.
- Or run the workflow by hand (`workflow_dispatch`) to build and upload the ZIP
  as a 30-day workflow artifact without publishing anything.
- Every run smoke-tests the extracted archive: the bundled interpreter, the
  `.exe` launcher copy and its `.pth` hook, the web build, native wheels, and
  `ffmpeg.exe`. The artifact is uploaded before that check, so a smoke-test
  failure still leaves a downloadable bundle for diagnosis.

The direct download URL for a published tag is
`https://github.com/unsubstantiation/gannet/releases/download/<tag>/GannetNVR-<version>-win64.zip`.

## Releasing

1. Bump `version` in `pyproject.toml` and commit it.
2. Tag and push:

   ```powershell
   git tag v0.19.0
   git push origin v0.19.0
   ```

3. Build the bundle locally on a supported Windows host with pinned inputs:

   ```powershell
   pwsh scripts/build_portable.ps1 -RequirePinned
   ```

4. Review the bundle and checksums in `dist/`, then attach the release assets
   manually when publishing the tag.

The version comes from `pyproject.toml`, and the build fails if the built wheel
disagrees with it. `gannet/util/version.py` reads that metadata at runtime, so the
version shown in the UI is the version the bundle carries.

The bundle name carries the version too, so the winget manifest the build writes
already points at the asset the release will have. Its `portable` nested installer
now points at `python\GannetNVR.exe`, the executable winget expects, with
`GannetNVR` as the command. `winget validate` is still a human step; the template
also records that the binary is upstream's unsigned-by-us CPython copy and that
application flags need a `--` separator (`GannetNVR -- --validate-config`).

One winget detail is load-bearing: the manifest sets
`ArchiveBinariesDependOnPath: true`. Winget normally exposes a portable command
through a symlink in `WinGet\Links`, but Windows looks for an executable's
private DLLs next to the **symlink**, not its target, so a symlinked copy of
`python.exe` cannot find `python312.dll`. The field makes winget put the exe's
own directory on `PATH` instead, so the loader finds the bundled runtime. The
side effect is that the bundled `python.exe` also lands on `PATH`; a submission
reviewer who objects can move the .exe and copies of its DLLs into a dedicated
`launcher\` directory and point the nested installer there.

## Licensing of what you redistribute

A bundle you hand to someone else is a distribution, and it carries more
obligations than running the app yourself. Everything below ships inside the ZIP:

| Component | License | What distribution requires |
| --- | --- | --- |
| FFmpeg 8.1.2 (x264/x265 enabled) | GPL-2.0-or-later as built | Corresponding source must be available. `SOURCE-OFFER.txt` states the exact build, digest, and source locations; do not strip it |
| CPython 3.12 embeddable (including the `GannetNVR.exe` copy) | PSF-2.0 | Keep the license and notice; unmodified |
| Unidecode | GPL-2.0-or-later | Source availability; see `DEPENDENCIES.md` §6 for the MIT alternative |
| py-vapid, pywebpush | MPL-2.0 | Nothing unless those files are modified |
| Everything else | permissive (MIT/Apache/BSD/ISC) | copyright and NOTICE retention |
| Gannet Material (`gannet/`, docs) | GNCL-1.0, noncommercial | Not open source; see [`LICENSING.md`](LICENSING.md) |

The project's own noncommercial terms never applied to FFmpeg, CPython, or any
wheel, and cannot be used to narrow them. `BUILD-INFO.json` records every Python
distribution and its version that the bundle actually contains, which is what a
downstream packager needs to reconstruct the obligations.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `does not match the pinned sha256` for CPython | upstream re-published, or a stale cached archive | delete `dist/.cache/python-*.zip`; if upstream really changed, update `python_embed_pin.json` deliberately |
| `No matching distribution found for ...` | the pinned version does not exist on the index, or it exists but publishes no wheel the `--only-binary` cross-install can take | check the pin against the index first; if the release is sdist-only and pure Python, it belongs in `SDIST_ONLY_REQUIREMENTS` in `scripts/build_portable.py`, which builds it a local wheel |
| `npm is not on PATH` | Node missing or too old | install Node 22+, or pass `-SkipWeb` with an existing `web/dist` |
| Build succeeds, UI says "web app is not built" | `web/dist` was not a production build | the builder rejects the Vite dev entry; delete `web/dist` and rebuild |
| `import gannet` fails on first run | `python312._pth` lost its `..\app` line, or the tree was re-zipped | re-extract the original archive; this is why the builder asserts the `._pth` contents |
| Startup fails on a missing table | extracted tree started from the wrong working directory | launch through `GannetNVR.cmd` or `run_gannet.ps1`; both set the working directory to `app` |
| Double-clicking `GannetNVR.exe` opens a Python `>>>` prompt | the `.pth` hook is missing, or the exe was renamed to one of the interpreter's own names | re-extract the archive; `verify_layout` asserts the hook and the `._pth` seeds at build time |
| `unknown option --validate-config` when passing a Gannet flag | CPython parsed the flag as its own option before `site` ran | put `--` before application flags (`GannetNVR.cmd` does this for you) |
| `python312.dll was not found` when running the .exe | `GannetNVR.exe` was moved out of `python\` | keep the copy next to `python.exe` and the DLLs; the Windows loader looks beside the executable |
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
