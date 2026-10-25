# Dependencies

Everything this repository asks for from outside itself: what is declared, what is
actually installed, why each package is here, and which terms it arrives under.

This file is an inventory. It is not the source of truth for any of those answers:

| Question | Authoritative file |
| --- | --- |
| What does the Python runtime install? | [`requirements.txt`](requirements.txt) |
| What does the web UI install? | [`web/package.json`](web/package.json) + `web/package-lock.json` |
| What does the docs site install? | [`docs/package.json`](docs/package.json) + `docs/package-lock.json` |
| What license does each package carry, and what does that require of a distributor? | [`THIRD_PARTY.md`](THIRD_PARTY.md) |
| What do this project's own terms cover? | [`LICENSE`](LICENSE), [`LICENSING.md`](LICENSING.md), [`REUSE.toml`](REUSE.toml) |
| What may a change add or remove? | [`AGENTS.md`](AGENTS.md), [`CONTRIBUTING.md`](CONTRIBUTING.md) |

If this file and a manifest disagree, the manifest wins and this file is stale.
Section 8 says how to refresh it.

**Snapshot:** 2026-10-24, `frigate-nvr` 0.19.0, from `requirements.txt`,
`web/package.json`, `web/package-lock.json`, `docs/package.json`,
`docs/package-lock.json` and `bootstrap_windows.py` as they stood at that date.

## 0. Supported toolchain

| Component | Version | Where it is enforced |
| --- | --- | --- |
| Operating system | Windows 10/11 or Server, x64 only | `frigate/util/platform.py` rejects every other platform at startup |
| Python | 64-bit CPython 3.12 (`>=3.12,<3.13`) | `pyproject.toml` `requires-python`, checked again by `bootstrap_windows.py` |
| Node.js | 20 (CI), 20.19+ for the docs site | `.github/workflows/windows-web.yml`, `docs/package.json` `engines` |
| FFmpeg / go2rtc | 8.1.2 / 1.9.14, SHA-256 pinned | Downloaded by `bootstrap_windows.py`, never vendored |
| Package managers | `pip` + `npm` | No `uv`, `poetry`, `pnpm` or `yarn` lockfile exists |

Dependency counts at this snapshot:

| Surface | Declared | Installed (lockfile) |
| --- | --- | --- |
| Python runtime (`requirements.txt`) | 62 distributions | no lockfile; `requirements.txt` is the resolution |
| Web UI direct dependencies | 75 + 26 dev | 696 packages |
| Docs site direct dependencies | 16 + 3 dev | 1562 packages |
| Downloaded binaries/model files | 4 | 4, digest-verified |

## 1. Python runtime dependencies

`requirements.txt` is the single authoritative set: native Windows wheels for
64-bit CPython 3.12. Most entries are pinned to a minor series (`== 25.1.*`) so
patch releases flow in; seven are pinned to an exact release (`pywin32 == 312`,
`tzdata == 2026.5`, `tzlocal == 5.4.4`, `py3nvml == 0.2.7`, `py-vapid == 1.9.6`,
`sqlite-vec == 0.1.9`, `python-multipart == 0.0.32`). Every entry publishes a
cp312 `win_amd64` wheel except `titlecase`, which is pure Python. The pins are
deliberately narrow — the file explains inline why several of them cannot move
(see 1.3).

"Import sites" counts non-test modules that import the package; it answers
"what breaks if this goes away", not "where is it used most". The scan covers
`frigate/`, `migrations/` and `bootstrap_windows.py`, so a package used only by
`testing-scripts/` shows as `none` even when something does use it.

### 1.1 Direct requirements (62)

| Package | Pin | Import | Import sites | Role | License |
| --- | --- | --- | --- | --- | --- |
| `aiofiles` | `== 25.1.*` | — | 1 · `api/app.py` | serves files from FastAPI responses without blocking the loop | Apache-2.0 |
| `click` | `== 8.5.*` | — | none | argv parsing for `testing-scripts/process_clip.py`; also a `uvicorn` CLI dependency | BSD-3-Clause |
| `aiohttp` | `== 3.14.*` | — | 1 · `api/web.py` | client sessions for camera probes and upstream fetches | Apache-2.0 AND MIT |
| `starlette` | `== 1.8.*` | — | 2 · `api/vod_native.py`, `api/web.py` | Request/Response and streaming primitives that FastAPI sits on | BSD-3-Clause |
| `fastapi[standard-no-fastapi-cloud-cli]` | `== 0.143.*` | `fastapi` | 18 · `api/app.py`, `api/auth.py` | routing, dependency injection and OpenAPI for both listeners | MIT † |
| `uvicorn` | `== 0.54.*` | — | 1 · `api/web.py` | serves the authenticated and internal listeners | BSD-3-Clause |
| `slowapi` | `== 0.1.*` | — | 2 · `api/auth.py`, `api/fastapi_app.py` | per-route limits on the public listener | MIT |
| `joserfc` | `== 1.7.*` | — | 2 · `api/auth.py`, `api/fastapi_app.py` | token signing and verification for API auth | BSD-3-Clause |
| `cryptography` | `== 50.0.*` | — | 2 · `api/notification.py`, `util/tls.py` | TLS material and Web Push payload encryption | Apache-2.0 OR BSD-3-Clause |
| `pathvalidate` | `== 3.3.*` | — | 7 · `api/export.py`, `api/media.py` | sanitises user-derived filenames for exports and media | MIT |
| `markupsafe` | `== 3.0.*` | — | 1 · `api/app.py` | escapes values interpolated into error pages | BSD-3-Clause |
| `python-multipart` | `== 0.0.32` | `multipart` | none | multipart bodies and file uploads for FastAPI; no direct import | Apache-2.0 |
| `filelock` | `== 4.2.*` | — | 3 · `api/app.py`, `api/camera.py` | serialises access to the DB, models and config files | MIT |
| `httpx` | `== 0.28.*` | — | 4 · `api/camera.py`, `genai/plugins/llama_cpp.py` | outbound requests and the API test client | BSD-3-Clause |
| `Pillow` | `== 13.0.*` | `PIL` | 5 · `embeddings/embeddings.py`, `embeddings/onnx/base_embedding.py` | decodes and re-encodes JPEG/PNG frames and thumbnails | MIT-CMU |
| `regex` | `== 2026.9.*` | — | 2 · `db/sqlitevecq.py`, `embeddings/__init__.py` | text search with timeout support where `re` cannot bound work | Apache-2.0 AND CNRI-Python |
| `rich` | `== 14.*` | — | 1 · `track/norfair_tracker.py` | progress/console output inside the norfair tracker; pinned by norfair | MIT |
| `tensorflow-cpu` | `== 2.21.*` | `tensorflow` | 1 · `util/classification.py` | TFLite interpreter for classification models | Apache-2.0 |
| `scikit-build` | `== 0.19.*` | — | none | build-time only; nothing imports it at runtime | MIT |
| `onvif-zeep-async` | `== 4.3.*` | `onvif` | 2 · `api/camera.py`, `ptz/onvif.py` | PTZ control and camera discovery | MIT |
| `paho-mqtt` | `== 2.1.*` | `paho.mqtt` | 1 · `comms/mqtt.py` | publishes events and stats to Home Assistant and brokers | EPL-2.0 OR BSD-3-Clause † |
| `pandas` | `== 3.0.*` | — | 1 · `api/review.py` | review/activity summaries in the API | BSD-3-Clause |
| `peewee` | `== 4.5.*` | — | 70 · `api/app.py`, `api/auth.py` | events, recordings and review rows in SQLite | MIT † |
| `peewee_migrate` | `== 2.3.*` | — | 1 · `app.py` | applies migrations at startup | MIT |
| `psutil` | `== 7.2.*` | — | 5 · `api/export.py`, `record/maintainer.py` | process, disk and memory stats for the stats endpoints | BSD-3-Clause |
| `pydantic` | `== 2.14.*` | — | 75 · `__main__.py`, `api/app.py` | the config schema and every API request/response model | MIT |
| `py3nvml` | `== 0.2.7` | — | 2 · `detectors/hardware.py`, `util/services.py` | NVIDIA utilisation and memory in stats | BSD-3-Clause |
| `tzdata` | `== 2026.5` | — | none | IANA zone data for `zoneinfo` on Windows; imported indirectly | Apache-2.0 |
| `pyzmq` | `== 27.2.*` | `zmq` | 7 · `comms/config_updater.py`, `comms/embeddings_updater.py` | inter-process messaging between the main, detection and recording processes | BSD-3-Clause |
| `ruamel.yaml` | `== 0.19.*` | — | 9 · `__main__.py`, `api/app.py` | reads and rewrites the config while keeping comments | MIT |
| `tzlocal` | `== 5.4.4` | — | 2 · `api/media.py`, `util/time.py` | resolves the host timezone for timestamp display | MIT |
| `requests` | `== 2.34.*` | — | 11 · `api/auth.py`, `api/camera.py` | blocking calls into go2rtc, ONVIF helpers and notifications | Apache-2.0 |
| `norfair` | `== 2.3.*` | — | 2 · `ptz/autotrack.py`, `track/norfair_tracker.py` | the tracker and the camera-motion estimation used by autotrack | BSD-3-Clause |
| `ws4py` | `== 0.6.*` | — | 2 · `comms/ws.py`, `output/output.py` | server side of the internal websocket feeds | BSD-3-Clause |
| `unidecode` | `== 1.4.*` | — | 1 · `util/image.py` | strips accents before license-plate normalisation (GPL, see below) | GPL-2.0-or-later |
| `titlecase` | `== 2.4.*` | — | 2 · `comms/webpush.py`, `data_processing/post/review_descriptions.py` | human-readable titles for events and notifications | MIT |
| `numpy` | `== 1.26.*` | — | 62 · `api/chat.py`, `api/event.py` | arrays for frames, embeddings, motion and detection post-processing | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| `opencv-contrib-python` | `== 4.11.0.*` | `cv2` | 37 · `api/chat.py`, `api/classification.py` | decode, resize, masks, optical flow and drawing | Apache-2.0 |
| `scipy` | `== 1.17.*` | — | 4 · `data_processing/common/face/recognizer.py`, `motion/improved_motion.py` | distance and similarity maths for face/embedding matching | BSD-3-Clause |
| `openvino` | `== 2026.4.*` | — | 4 · `detectors/detection_runners.py`, `detectors/hardware.py` | OpenVINO detector and embedding runners | Apache-2.0 |
| `onnxruntime` | `== 1.31.*` | — | 3 · `detectors/detection_runners.py`, `detectors/hardware.py` | ONNX detector, face and embedding runners (CPU, or DirectML/GPU via the extras) | MIT |
| `transformers` | `== 5.20.*` | — | 2 · `embeddings/onnx/jina_v1_embedding.py`, `embeddings/onnx/jina_v2_embedding.py` | Jina CLIP text/image encoders for semantic search | Apache-2.0 † |
| `google-genai` | `== 2.31.*` | `google.genai` | 1 · `genai/plugins/gemini.py` | Gemini plugin | Apache-2.0 |
| `ollama` | `== 0.6.*` | — | 1 · `genai/plugins/ollama.py` | local Ollama plugin | MIT |
| `openai` | `== 3.33.*` | — | 3 · `data_processing/real_time/whisper_online.py`, `genai/plugins/azure-openai.py` | Azure OpenAI and OpenAI-compatible plugins, plus online Whisper | Apache-2.0 |
| `py-vapid` | `== 1.9.6` | `py_vapid` | 2 · `api/notification.py`, `comms/webpush.py` | VAPID key generation for browser push | MPL-2.0 |
| `pywebpush` | `== 2.5.*` | — | 1 · `comms/webpush.py` | delivers push notifications | MPL-2.0 |
| `pywin32` | `== 312` | `win32service` | 1 · `util/windows_service.py` | service install, start and stop through the SCM | PSF-2.0 |
| `pyclipper` | `== 1.4.*` | — | 1 · `data_processing/common/license_plate/mixin.py` | expands license-plate boxes before OCR | MIT |
| `shapely` | `== 2.2.*` | — | 1 · `data_processing/common/license_plate/mixin.py` | polygon intersection for zone and mask tests | BSD-3-Clause |
| `rapidfuzz` | `== 3.14.*` | — | 1 · `data_processing/common/license_plate/mixin.py` | scores plate OCR candidates against known plates | MIT |
| `argcomplete` | `== 3.7.*` | — | none | declared but not imported anywhere (see 1.4) | Apache-2.0 |
| `contextlib2` | `== 21.6.*` | — | none | declared but not imported anywhere (see 1.4) | Apache-2.0 |
| `future` | `== 1.0.*` | — | none | declared but not imported anywhere (see 1.4) | MIT |
| `netaddr` | `== 1.3.*` | — | none | declared but not imported anywhere (see 1.4) | BSD-3-Clause |
| `prometheus-client` | `== 0.26.*` | `prometheus_client` | 1 · `stats/prometheus.py` | exposes `/metrics` for scraping | Apache-2.0 AND BSD-2-Clause |
| `ai-edge-litert` | `== 2.3.*` | `ai_edge_litert` | 6 · `data_processing/real_time/bird.py`, `data_processing/real_time/custom_classification.py` | runs the TFLite detector/classifier/audio models | Apache-2.0 |
| `sqlite-vec` | `== 0.1.9` | `sqlite_vec` | 1 · `db/sqlitevecq.py` | SQLite extension backing semantic-search similarity | MIT OR Apache-2.0 † |
| `sherpa-onnx` | `== 1.13.*` | `sherpa_onnx` | 2 · `data_processing/common/audio_transcription/model.py`, `data_processing/types.py` | speech recognition and audio event models | Apache-2.0 † |
| `faster-whisper` | `== 1.2.*` | `faster_whisper` | 3 · `data_processing/common/audio_transcription/model.py`, `data_processing/post/audio_transcription.py` | offline audio transcription | MIT |
| `librosa` | `== 0.11.*` | — | 1 · `data_processing/real_time/whisper_online.py` | resampling and spectrograms before transcription | ISC |
| `soundfile` | `== 0.14.*` | — | 1 · `data_processing/real_time/whisper_online.py` | reads and writes audio buffers | BSD-3-Clause |

`†` marks a license resolved by hand, because the registry metadata is
missing, free-form prose, or — for `fastapi` — absent entirely. The same mark is
used for `apexcharts` and `react-apexcharts` in section 2, which publish no SPDX
identifier and are MIT per their own `LICENSE` files. See
[`THIRD_PARTY.md`](THIRD_PARTY.md) for the reasoning behind each.

### 1.2 Optional accelerator extras

Declared in `pyproject.toml` as `[project.optional-dependencies]`, not in
`requirements.txt`. All three provide the `onnxruntime` import and are mutually
exclusive with the base `onnxruntime` line, which `bootstrap_windows.py` swaps
out when a profile is selected.

| Extra | Package | Pin | Runtime | License |
| --- | --- | --- | --- | --- |
| `windows-directml` | `onnxruntime-directml` | `== 1.24.*` | AMD / Intel / NVIDIA through DirectML | MIT |
| `windows-cuda` | `onnxruntime-gpu[cuda,cudnn]` | `== 1.31.*` | NVIDIA CUDA + cuDNN | MIT |
| `windows-ml` | `windowsml[with-ort]` | `== 2.4.*` | Windows ML | MIT |

The DirectML build lags the CPU line: `1.24.*` against `1.31.*`. Windows ML's
extra pins ORT 1.27.1, which is intentional and commented in `pyproject.toml`
until cross-version compatibility is verified. Do not "align" these three pins;
they are separate release trains.

### 1.3 Why some pins cannot move

Four constraints hold the image and audio stacks where they are. They are written
into `requirements.txt` as comments; they are repeated here because they explain
why several packages look arbitrarily old.

- **`numpy == 1.26.*`** is required by `norfair 2.3.0`, which has no newer release
  and is load-bearing for `frigate/ptz/autotrack.py` camera-motion estimation.
  Three packages cap themselves to stay installable against numpy 1.x:
  `scipy 1.17.*` (1.18 wants numpy>=2), `opencv-contrib-python 4.11.0.*`
  (4.12+ wants numpy>=2) and `librosa 0.11.*` (1.0 wants numpy>=2.1).
  Bumping any one of them without dropping `norfair` makes
  `pip install -r requirements.txt` unresolvable.
- **`rich == 14.*`** because `norfair 2.3.0` declares `rich<15.0.0`. Keep it in
  step with `norfair`'s `requires_dist`; a 15.x pin makes the file unresolvable.
- **`filelock`, `httpx`, `Pillow`, `regex`** are pinned even though they arrive
  transitively, because Frigate imports them at module scope. Pinning them means
  an upstream extra that stops depending on one of them cannot break the import.
- **`tensorflow-cpu`, `ai-edge-litert`, `openvino`, `onnxruntime`** each carry a
  large native wheel; they are pinned per minor series so a patch release cannot
  silently change a kernel or a model parser.

### 1.4 Declared but not imported directly

These install, but nothing in this tree has a line that imports them. Most are
inherited from upstream Frigate with no purpose left on Python 3.12; the last
three are still needed, just not by an `import` the scan can see. Nothing fails
if the genuinely unused ones are removed, but each removal is a separate
decision, so they are listed rather than unilaterally dropped.

| Package | Pin | Status |
| --- | --- | --- |
| `argcomplete` | `== 3.7.*` | no import site; shell completion only if a CLI used it |
| `contextlib2` | `== 21.6.*` | no import site; stdlib `contextlib` covers Python 3.12 |
| `future` | `== 1.0.*` | no import site; every `from __future__ import annotations` is the stdlib feature, not this package |
| `netaddr` | `== 1.3.*` | no import site; `ipaddress` (stdlib) is what the code uses |
| `scikit-build` | `== 0.19.*` | build tooling; no runtime import by design |
| `python-multipart` | `== 0.0.32` | imported by FastAPI, not by this tree; required for form/file uploads |
| `tzdata` | `== 2026.5` | consumed indirectly by `zoneinfo` on Windows |
| `click` | `== 8.5.*` | used by `testing-scripts/process_clip.py` and the `uvicorn` CLI, not by `frigate/` |

## 2. Web UI (`web/`)

React 19 single-page app built with Vite 8 and TypeScript 6, styled with
Tailwind 3 and Radix primitives, with configuration forms rendered by
`@rjsf/*` and a Monaco YAML editor for the raw config. `web/package-lock.json`
pins all 696 installed packages; only the direct dependencies below are audited for
licenses.

### 2.1 Runtime dependencies (75)

| Package | Declared | Locked | License |
| --- | --- | --- | --- |
| `@cycjimmy/jsmpeg-player` | `^6.1.2` | `6.1.2` | MIT |
| `@hookform/resolvers` | `^5.9.1` | `5.9.1` | MIT |
| `@radix-ui/react-alert-dialog` | `^1.2.1` | `1.2.1` | MIT |
| `@radix-ui/react-aspect-ratio` | `^1.2.0` | `1.2.0` | MIT |
| `@radix-ui/react-checkbox` | `^1.4.1` | `1.4.1` | MIT |
| `@radix-ui/react-collapsible` | `^1.2.1` | `1.2.1` | MIT |
| `@radix-ui/react-context-menu` | `^2.4.1` | `2.4.1` | MIT |
| `@radix-ui/react-dialog` | `^1.3.1` | `1.3.1` | MIT |
| `@radix-ui/react-dropdown-menu` | `^2.2.1` | `2.2.1` | MIT |
| `@radix-ui/react-hover-card` | `^1.2.1` | `1.2.1` | MIT |
| `@radix-ui/react-label` | `^2.1.17` | `2.1.17` | MIT |
| `@radix-ui/react-popover` | `^1.3.1` | `1.3.1` | MIT |
| `@radix-ui/react-progress` | `^1.2.1` | `1.2.1` | MIT |
| `@radix-ui/react-radio-group` | `^1.5.1` | `1.5.1` | MIT |
| `@radix-ui/react-scroll-area` | `^1.4.0` | `1.4.0` | MIT |
| `@radix-ui/react-select` | `^2.4.1` | `2.4.1` | MIT |
| `@radix-ui/react-separator` | `^1.2.0` | `1.2.0` | MIT |
| `@radix-ui/react-slider` | `^1.6.1` | `1.6.1` | MIT |
| `@radix-ui/react-slot` | `1.5.0` | `1.5.0` | MIT |
| `@radix-ui/react-switch` | `^1.4.1` | `1.4.1` | MIT |
| `@radix-ui/react-tabs` | `^1.2.1` | `1.2.1` | MIT |
| `@radix-ui/react-toggle` | `^1.2.1` | `1.2.1` | MIT |
| `@radix-ui/react-toggle-group` | `^1.2.1` | `1.2.1` | MIT |
| `@radix-ui/react-tooltip` | `^1.4.1` | `1.4.1` | MIT |
| `@rjsf/core` | `^6.11.0` | `6.11.0` | Apache-2.0 |
| `@rjsf/shadcn` | `^6.11.0` | `6.11.0` | MIT |
| `@rjsf/utils` | `^6.11.0` | `6.11.0` | Apache-2.0 |
| `@rjsf/validator-ajv8` | `^6.11.0` | `6.11.0` | Apache-2.0 |
| `apexcharts` | `^8.3.1` | `8.3.1` | MIT † |
| `axios` | `^1.20.0` | `1.20.0` | MIT |
| `class-variance-authority` | `^0.7.1` | `0.7.1` | Apache-2.0 |
| `clsx` | `^2.1.1` | `2.1.1` | MIT |
| `cmdk` | `^1.1.1` | `1.1.1` | MIT |
| `copy-to-clipboard` | `^4.0.2` | `4.0.2` | MIT |
| `date-fns` | `^4.4.0` | `4.4.0` | MIT |
| `date-fns-tz` | `^3.2.0` | `3.2.0` | MIT |
| `framer-motion` | `^14.3.0` | `14.3.0` | MIT |
| `hls.js` | `^1.7.3` | `1.7.3` | Apache-2.0 |
| `i18next` | `^26.4.7` | `26.4.7` | MIT |
| `i18next-http-backend` | `^4.0.3` | `4.0.3` | MIT |
| `idb-keyval` | `^6.3.0` | `6.3.0` | Apache-2.0 |
| `js-yaml` | `^5.5.0` | `5.5.0` | MIT |
| `konva` | `^10.9.0` | `10.9.0` | MIT |
| `lodash` | `^4.18.1` | `4.18.1` | MIT |
| `lucide-react` | `^1.59.0` | `1.59.0` | ISC |
| `monaco-yaml` | `^5.5.1` | `5.5.1` | MIT |
| `next-themes` | `^0.4.6` | `0.4.6` | MIT |
| `nosleep.js` | `^0.12.0` | `0.12.0` | MIT |
| `react` | `^19.3.1` | `19.3.1` | MIT |
| `react-apexcharts` | `^2.1.1` | `2.1.1` | MIT † |
| `react-day-picker` | `^10.0.2` | `10.0.2` | MIT |
| `react-device-detect` | `^2.2.3` | `2.2.3` | MIT |
| `react-dom` | `^19.3.1` | `19.3.1` | MIT |
| `react-dropzone` | `^20.1.4` | `20.1.4` | MIT |
| `react-grid-layout` | `^2.3.0` | `2.3.0` | MIT |
| `react-hook-form` | `^7.90.0` | `7.90.0` | MIT |
| `react-i18next` | `^17.0.20` | `17.0.20` | MIT |
| `react-icons` | `^5.7.0` | `5.7.0` | MIT |
| `react-konva` | `^19.3.2` | `19.3.2` | MIT |
| `react-markdown` | `^10.1.0` | `10.1.0` | MIT |
| `react-router-dom` | `^7.18.4` | `7.18.4` | MIT |
| `react-swipeable` | `^7.0.2` | `7.0.2` | MIT |
| `react-zoom-pan-pinch` | `3.4.4` | `3.4.4` | MIT |
| `remark-gfm` | `^4.0.1` | `4.0.1` | MIT |
| `scroll-into-view-if-needed` | `^3.1.0` | `3.1.0` | MIT |
| `sonner` | `^2.0.8` | `2.0.8` | MIT |
| `swr` | `^2.5.1` | `2.5.1` | MIT |
| `tailwind-merge` | `^3.7.0` | `3.7.0` | MIT |
| `tailwind-scrollbar` | `^3.1.0` | `3.1.0` | MIT |
| `tailwindcss-animate` | `^1.0.7` | `1.0.7` | MIT |
| `use-long-press` | `^3.3.0` | `3.3.0` | MIT |
| `vaul` | `^1.1.2` | `1.1.2` | MIT |
| `virtua` | `^0.53.5` | `0.53.5` | MIT |
| `vite-plugin-monaco-editor` | `^1.1.0` | `1.1.0` | MIT |
| `zod` | `^3.25.76` | `3.25.76` | MIT |

### 2.2 Development dependencies (26)

| Package | Declared | Locked | License |
| --- | --- | --- | --- |
| `@eslint/js` | `^10.0.1` | `10.0.1` | MIT |
| `@playwright/test` | `^1.64.1` | `1.64.1` | Apache-2.0 |
| `@types/js-yaml` | `^4.0.9` | `4.0.9` | MIT |
| `@types/lodash` | `^4.17.26` | `4.17.26` | MIT |
| `@types/node` | `^26.6.5` | `26.6.5` | MIT |
| `@types/react` | `^19.3.0` | `19.3.0` | MIT |
| `@types/react-dom` | `^19.3.0` | `19.3.0` | MIT |
| `@vitejs/plugin-react` | `^6.1.2` | `6.1.2` | MIT |
| `autoprefixer` | `^10.6.1` | `10.6.1` | MIT |
| `esbuild` | `^0.28.2` | `0.28.2` | MIT |
| `eslint` | `^10.13.0` | `10.13.0` | MIT |
| `eslint-config-prettier` | `^10.1.8` | `10.1.8` | MIT |
| `eslint-plugin-prettier` | `^5.5.7` | `5.5.7` | MIT |
| `eslint-plugin-react-hooks` | `^7.1.1` | `7.1.1` | MIT |
| `eslint-plugin-react-refresh` | `^0.5.7` | `0.5.7` | MIT |
| `globals` | `^17.13.0` | `17.13.0` | MIT |
| `i18next-cli` | `^1.75.3` | `1.75.3` | MIT |
| `monaco-editor` | `^0.52.2` | `0.52.2` | MIT |
| `patch-package` | `^8.0.1` | `8.0.1` | MIT |
| `postcss` | `^8.5.30` | `8.5.30` | MIT |
| `prettier` | `^3.9.10` | `3.9.10` | MIT |
| `prettier-plugin-tailwindcss` | `^0.8.1` | `0.8.1` | MIT |
| `tailwindcss` | `^3.4.19` | `3.4.19` | MIT |
| `typescript` | `^6.0.3` | `6.0.3` | Apache-2.0 |
| `typescript-eslint` | `^8.71.2` | `8.71.2` | MIT |
| `vite` | `^8.3.4` | `8.3.4` | MIT |

### 2.3 Local modifications to third-party packages

| Mechanism | What it does |
| --- | --- |
| `web/patches/@radix-ui+react-compose-refs+1.1.2.patch` | applied by `patch-package` on `postinstall`; rewrites `useComposedRefs` so the callback identity stays stable and cleanup functions returned by refs are honoured |
| `overrides` in `web/package.json` | forces `@radix-ui/react-compose-refs` 1.1.2, `@radix-ui/react-popper` 1.2.8 and `@radix-ui/react-slot` 1.5.0 so the patch and the Radix tree stay consistent |

`npm ci` in CI applies the patch automatically; a fresh `node_modules` built
without `postinstall` is not a supported state.

## 3. Docs site (`docs/`)

Docusaurus 3.10 with the Mermaid theme, OpenAPI doc generation and Inkeep search.
It is a separate dependency tree from the app and is **not** audited by
`scripts/license_audit.py` (see 7.2). Its React is 18 while the app runs 19:
Docusaurus 3.x peers on React 18, so the two trees stay pinned separately and
must not share a lockfile.

### 3.1 Runtime dependencies (16)

| Package | Declared | Locked | License |
| --- | --- | --- | --- |
| `@docusaurus/core` | `^3.10.2` | `3.10.2` | MIT |
| `@docusaurus/plugin-content-docs` | `^3.10.2` | `3.10.2` | MIT |
| `@docusaurus/preset-classic` | `^3.10.2` | `3.10.2` | MIT |
| `@docusaurus/theme-mermaid` | `^3.10.2` | `3.10.2` | MIT |
| `@inkeep/docusaurus` | `^2.0.16` | `2.0.16` | MIT |
| `@mdx-js/react` | `^3.1.0` | `3.1.1` | MIT |
| `@types/js-yaml` | `^4.0.9` | `4.0.9` | MIT |
| `clsx` | `^2.1.1` | `2.1.1` | MIT |
| `docusaurus-plugin-openapi-docs` | `^5.2.0` | `5.2.0` | MIT |
| `docusaurus-theme-openapi-docs` | `^5.2.0` | `5.2.0` | MIT |
| `js-yaml` | `^4.3.2` | `4.3.2` | MIT |
| `marked` | `^16.4.2` | `16.4.2` | MIT |
| `prism-react-renderer` | `^2.4.1` | `2.4.1` | MIT |
| `raw-loader` | `^4.0.2` | `4.0.2` | MIT |
| `react` | `^18.3.1` | `18.3.1` | MIT |
| `react-dom` | `^18.3.1` | `18.3.1` | MIT |

### 3.2 Development dependencies (3)

| Package | Declared | Locked | License |
| --- | --- | --- | --- |
| `@docusaurus/module-type-aliases` | `^3.10.2` | `3.10.2` | MIT |
| `@docusaurus/types` | `^3.10.2` | `3.10.2` | MIT |
| `@types/react` | `^18.3.27` | `18.3.27` | MIT |

`js-yaml` is intentionally a different major here (4.x) than in `web/` (5.x):
each tree resolves its own copy, and the docs build does not consume the app's
code.

## 4. Downloaded runtime artifacts

Not packages and not vendored: `bootstrap_windows.py` pins one URL and one
SHA-256 digest per artifact and verifies the digest on every install and on every
subsequent startup check. Nothing else in the build path fetches executables.

| Artifact | Version | Source | Digest (prefix) | License |
| --- | --- | --- | --- | --- |
| FFmpeg (`ffmpeg.exe`, `ffprobe.exe`) | 8.1.2 essentials | `GyanD/codexffmpeg` | `db580001caa2` | GPL-2.0-or-later as built (x264/x265 enabled) |
| go2rtc (`go2rtc.exe`) | 1.9.14 | `AlexxIT/go2rtc` | `dd4167d75cb0` | MIT |
| CPU detection model (`cpu_model.tflite`) | `frogfish` | `google-coral/test_data` | `90bb33a634e0` | Apache-2.0 (weights) |
| YAMNet audio model (`cpu_audio_model.tflite`) | `1` | `tfhub.dev` | `10c95ea3eb9a` | Apache-2.0 (weights) |

Full digests are in `bootstrap_windows.py`. Redistribution duties for these are
covered in [`THIRD_PARTY.md`](THIRD_PARTY.md); the FFmpeg build is the one that
carries source-offer obligations, and the project's own noncommercial terms never
applied to it.

Models fetched at runtime for semantic search, transcription, GenAI, face
recognition and ALPR are downloaded from their own publishers, on their own
terms. They are outside this file's inventory because no manifest pins them.

## 5. Build, CI and test tooling not in any manifest

Deliberately listed: none of these appear in `requirements.txt` or a
`package.json`, so a dependency scanner will not see them.

| Tool | Pin | Where it comes from | License |
| --- | --- | --- | --- |
| Ruff | `0.17.1` | `pip install ruff==0.17.1` in `.github/workflows/windows-python.yml` | MIT |
| `actions/checkout`, `actions/setup-python@v7`, `actions/setup-node` | floating major tags | GitHub-hosted actions | MIT |
| Node.js for web CI | `20` | `actions/setup-node` | MIT |
| Playwright browsers | unpinned; downloaded on first `npx playwright install` | `@playwright/test` 1.64.1 | Apache-2.0 (Playwright); each browser binary keeps its vendor's terms |
| Python test framework | `unittest` (stdlib) | `testing-scripts/run_windows_unit_suite.py` | PSF-2.0 |
| `pywin32_postinstall.py` | ships with `pywin32` 312 | run in CI after install | PSF-2.0 |

There is no `dev-requirements.txt`, `test-requirements.txt` or `constraints.txt`
in this repository. `testing-scripts/` imports `click`, `PIL`, `cv2`, `numpy`,
`onnxruntime` and `scipy`, all of which `requirements.txt` already provides, which
is why no separate test requirements file exists.

## 6. Licensing posture

Short version, with the full argument in [`THIRD_PARTY.md`](THIRD_PARTY.md) and
[`LICENSING.md`](LICENSING.md). No dependency inherits this project's
noncommercial terms, and none of this project's terms can be pushed onto them.

| Obligation | Packages | What a distributor owes |
| --- | --- | --- |
| Strong copyleft | `unidecode` 1.4.0 (GPL-2.0-or-later) | Source availability for the GPL-covered library. Load-bearing for ALPR plate normalisation; `text-unidecode` (MIT) is the documented drop-in if a cleaner posture matters |
| File-level copyleft | `py-vapid` 1.9.6, `pywebpush` 2.5.0 (MPL-2.0) | Nothing unless those files are modified; modifications stay MPL |
| Dual license, choose one | `paho-mqtt` (EPL-2.0 OR BSD-3-Clause), `sqlite-vec` (MIT OR Apache-2.0), `cryptography` (Apache-2.0 OR BSD-3-Clause) | Take the permissive option and the copyleft option drops out |
| Attribution / notice | `numpy` (multi-license), `regex` (Apache-2.0 AND CNRI-Python), `Pillow` (MIT-CMU), Apache-2.0 packages | Keep copyright, license text and NOTICE files intact |
| Binaries with their own terms | FFmpeg 8.1.2 (GPL-2.0-or-later as built), the TFLite models (Apache-2.0) | FFmpeg source offer; model NOTICE attribution |
| Third-party model terms | semantic search, Whisper, GenAI, face and ALPR weights | Check each model card; several restrict commercial use independently of this project |

The noncommercial license in [`LICENSE`](LICENSE) covers Gannet Material only. It
cannot narrow MIT in the upstream Frigate files, and it does not reach any
package listed here.

## 7. Known gaps and drift in this snapshot

### 7.1 There is no Python lockfile

`requirements.txt` mostly pins minor series (`== 25.1.*`), not exact releases,
and carries no hashes at all. Two installs on two days can produce different
wheels, and nothing in CI compares them. The npm side is locked
(`package-lock.json`, `npm ci`); the Python side is not. The root
`package-lock.json` is an empty stub (`packages: {}`) with no packages declared
at the root.

### 7.2 The license audit skips FastAPI and all of `docs/`

`scripts/license_audit.py` parses requirements with
`^([A-Za-z0-9._-]+)\s*==`, which does not match an extras line. The
`fastapi[standard-no-fastapi-cloud-cli]` entry therefore never reaches the
generated table in `THIRD_PARTY.md` — the most load-bearing Python dependency in
the project is absent from the license audit. FastAPI is MIT per its own
repository; PyPI metadata reports no license field at all. Widening that regex to
accept `[...]` and re-running the audit fixes the omission.

The same script reads only `requirements.txt` and `web/package.json`. The
16 + 3 docs-site dependencies have never been audited. Their
licenses in section 3 were checked by hand against registry metadata on
2026-10-24, and all are MIT.

### 7.3 The audited version is not the installed version

`npm_spdx` reads `dist-tags.latest` and the Python path takes the newest release
matching the pin prefix, so `THIRD_PARTY.md`'s "Version checked" column records
what the registry offered at audit time, not what the lockfile installs.
11 of the 101 audited npm packages disagree:

| Package | Declared | Audited in THIRD_PARTY.md | Installed from package-lock.json |
| --- | --- | --- | --- |
| `@hookform/resolvers` | `^5.9.1` | `5.9.2` | `5.9.1` |
| `i18next` | `^26.4.7` | `26.5.2` | `26.4.7` |
| `i18next-cli` | `^1.75.3` | `1.77.0` | `1.75.3` |
| `i18next-http-backend` | `^4.0.3` | `4.0.4` | `4.0.3` |
| `monaco-editor` | `^0.52.2` | `0.57.0` | `0.52.2` |
| `react-i18next` | `^17.0.20` | `17.1.0` | `17.0.20` |
| `react-zoom-pan-pinch` | `3.4.4` | `4.2.0` | `3.4.4` |
| `tailwind-scrollbar` | `^3.1.0` | `4.0.2` | `3.1.0` |
| `tailwindcss` | `^3.4.19` | `4.3.3` | `3.4.19` |
| `typescript` | `^6.0.3` | `7.0.2` | `6.0.3` |
| `zod` | `^3.25.76` | `4.6.7` | `3.25.76` |

Licenses are stable across those bumps, so the verdicts still hold, but the
version column should not be read as "what ships". At this snapshot
`python scripts/license_audit.py --check` already exits non-zero: the table was
last regenerated on 2026-10-18 and releases have moved since. That staleness
predates this file and is unrelated to it. `typescript` is the one case
where the audited major (7.x) and installed major (6.x) differ enough that the
license itself is worth re-checking if the pin ever moves.

### 7.4 Unused and legacy entries

Section 1.4 lists eight packages with no direct import site. `future`,
`contextlib2` and `netaddr` are upstream-era leftovers with no Python 3.12
purpose. Removing them is safe in principle; it has not been done here.

### 7.5 Two React majors, two js-yaml majors

`web/` runs React 19, `docs/` runs React 18, and `js-yaml` is 5.x in `web/` and
4.x in `docs/`. This is intentional, but it means a repo-wide dependency bump
must not treat the two trees as one.

## 8. Refreshing this file

After changing any manifest, from the repository root:

```powershell
pip install -r requirements.txt          # confirm the set still resolves
python scripts/license_audit.py          # regenerate THIRD_PARTY.md's license table
python scripts/license_audit.py --check  # fails when that table is stale
```

For the web UI:

```powershell
cd web
npm install                              # updates the lockfile and reapplies patches
npm run lint
npm run build:native
```

Then update by hand in this file: the counts in section 0, any changed pins and
roles in sections 1-3, the artifact table in section 4 if `bootstrap_windows.py`
pins move, and the drift table in 7.3. Nothing generates this document, so a
manifest change that skips it leaves a stale inventory — the `--check` target is
`THIRD_PARTY.md`, not this file.

`REUSE.toml` maps this file to Gannet Material; it is regenerated by
`scripts/generate_reuse_toml.py`, never edited by hand.
