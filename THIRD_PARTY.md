# Third-party components and what their licenses require

LICENSE governs the material this project owns. It governs nothing else, and it
could not: a license can only convey rights its grantor holds. This file is the
honest boundary — what arrives from elsewhere, on whose terms, and what you owe
if you redistribute a working system.

Three separate categories, and they do not mix:

| Category | Governing terms | Who can change them |
| --- | --- | --- |
| Gannet Material (see `REUSE.toml`) | Gannet Noncommercial License 1.0 | unsubstantiation |
| Upstream Material (Frigate files) | MIT, `LICENSES/MIT.txt` | Frigate, Inc. and Frigate contributors only |
| Dependencies and runtime artifacts (below) | each package's own license | nobody but that package's authors |

## Runtime artifacts the bootstrap downloads

`bootstrap_windows.py` pins exact URLs and SHA-256 digests. These are not
vendored into the repository; they are fetched at install time, so whoever
ships a bundle that includes them takes on the obligations below directly.

| Component | Source | License | What it means for redistribution |
| --- | --- | --- | --- |
| FFmpeg | `GyanD/codexffmpeg` `ffmpeg-8.1.2-essentials_build` | GPL-2.0-or-later as built (x264/x265 enabled) | If you distribute an installer or image containing this build, you must offer the corresponding FFmpeg source and keep its licenses intact. Swapping to an LGPL/shared build changes which obligations attach; it does not remove any. The project's own noncommercial terms never applied to FFmpeg and do not now. |
| go2rtc | `AlexxIT/go2rtc` `v1.9.14` `go2rtc_win64.zip` | MIT | Keep the copyright and permission notice. go2rtc incorporates FFmpeg libraries, so check that build's terms too. |
| Default CPU detection model | `google-coral/test_data` `release-frogfish` `ssdlite_mobiledet_coco_qat_post_process.tflite` | Apache-2.0 (repository license) | Weights, not code. Attribution and the NOTICE requirement apply. Not relicensed by anything in this repository. |
| YAMNet audio model | `tfhub.dev/google/lite-model/yamnet/classification/tflite/1` | Apache-2.0 | As above; confirm the terms served at that URL before bundling. |

Models fetched at runtime for semantic search, audio transcription, GenAI,
face and license-plate recognition are downloaded from their own publishers, and
several of those publishers already restrict commercial use or set acceptable-use
terms. That is their restriction, not this project's, and it is independent of
LICENSE. Verify the model card before shipping a build that embeds weights.

## Package dependencies

Every declared package, where it is imported and why its pin cannot move is
inventoried in [`DEPENDENCIES.md`](DEPENDENCIES.md); this section is the
licensing half of that picture.

Two things in this repository's dependency set constrain what this project can
promise about its own license:

- **`unidecode` is GPL-2.0-or-later** (`requirements.txt`). Copyleft terms cannot
  be narrowed by us and cannot be made noncommercial by us; anyone who
  redistributes a build has to carry that through. It is used for
  license-plate text normalization, so it is close to a load-bearing
  dependency, and it is the first thing to replace if a cleaner licensing
  posture ever matters (`text-unidecode`, MIT, is the usual drop-in).
`unidecode` is confirmed by both its registry metadata and its source repository,
so it is not a metadata artifact. The practical fix, if a cleaner posture ever
matters, is `text-unidecode` (MIT, same API shape, same author lineage of
purpose) rather than a licensing argument.

MPL-2.0 (`py-vapid`, `pywebpush`) is file-level copyleft: use it as a dependency
and nothing is asked of you, modify those files and they stay MPL. That is
compatible with the terms in `LICENSE`; it is just not ours to relicense.

The generated table below is a snapshot of what each registry reports, taken on
2026-10-18. Registry metadata is the author's own claim, and several entries
report nothing or report prose instead of an SPDX id. Those were resolved by hand
against the upstream source, and are recorded here so the next reader does not
have to redo them:

| Package | Registry said | Actual |
| --- | --- | --- |
| `peewee` | no field | MIT (`coleifer/peewee/LICENSE`) |
| `transformers` | `Apache 2.0 License` prose | Apache-2.0 |
| `sherpa-onnx` | prose | Apache-2.0 |
| `sqlite-vec` | `MIT License, Apache License, Version 2.0` | dual MIT OR Apache-2.0 |
| `Pillow` | `MIT-CMU` | MIT-CMU (the Historical Permission Notice variant) |
| `regex` | `Apache-2.0 AND CNRI-Python` | both apply; CNRI-Python covers the bundled Python-derived bits |
| `paho-mqtt` | `EPL-2.0 OR BSD-3-Clause` | dual; take BSD-3-Clause and the copyleft option drops out |
| `apexcharts`, `react-apexcharts` | `SEE LICENSE IN LICENSE` | MIT, per each repository's `LICENSE.md` |

Nothing in this file is under `LicenseRef-GNCL-1.0`, and nothing in `LICENSE`
purports to change what is written above.



`scripts/license_audit.py` reads `requirements.txt` and `web/package.json`, asks
PyPI and the npm registry what each dependency reports, and rewrites the block
below. Regenerate it whenever either manifest changes; `--check` reports whether
the committed snapshot is stale, and `--json` dumps the raw table.

<!-- BEGIN GENERATED DEPENDENCY TABLE (scripts/license_audit.py) -->
| Dependency | Version checked | SPDX license |
| --- | --- | --- |
| Python: `ai-edge-litert` | 2.3.0 | Apache-2.0 |
| Python: `aiofiles` | 25.1.0 | Apache-2.0 |
| Python: `aiohttp` | 3.14.5 | Apache-2.0 AND MIT |
| Python: `argcomplete` | 3.7.2 | Apache-2.0 |
| Python: `click` | 8.5.0 | BSD-3-Clause |
| Python: `contextlib2` | 21.6.0 | Apache-2.0 |
| Python: `cryptography` | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| Python: `faster-whisper` | 1.2.1 | MIT |
| Python: `filelock` | 4.2.2 | MIT |
| Python: `future` | 1.0.0 | MIT |
| Python: `google-genai` | 2.31.0 | Apache-2.0 |
| Python: `httpx` | 0.28.1 | BSD-3-Clause |
| Python: `joserfc` | 1.7.5 | BSD-3-Clause |
| Python: `librosa` | 0.11.0 | ISC |
| Python: `markupsafe` | 3.0.4 | BSD-3-Clause |
| Python: `netaddr` | 1.3.0 | BSD-3-Clause |
| Python: `norfair` | 2.3.0 | BSD-3-Clause |
| Python: `numpy` | 1.26.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| Python: `ollama` | 0.6.3 | MIT |
| Python: `onnxruntime` | 1.31.0 | MIT |
| Python: `onvif-zeep-async` | 4.3.0 | MIT |
| Python: `openai` | 3.33.0 | Apache-2.0 |
| Python: `opencv-contrib-python` | 4.11.0.86 | Apache-2.0 |
| Python: `openvino` | 2026.4.1 | Apache-2.0 |
| Python: `paho-mqtt` | 2.1.0 | not reported |
| Python: `pandas` | 3.0.6 | BSD-3-Clause |
| Python: `pathvalidate` | 3.3.1 | MIT |
| Python: `peewee` | 4.5.3 | not reported |
| Python: `peewee_migrate` | 2.3.0 | MIT |
| Python: `Pillow` | 13.0.0 | MIT-CMU |
| Python: `prometheus-client` | 0.26.0 | Apache-2.0 AND BSD-2-Clause |
| Python: `psutil` | 7.2.2 | BSD-3-Clause |
| Python: `py-vapid` | 1.9.6 | MPL-2.0 |
| Python: `py3nvml` | 0.2.7 | BSD-3-Clause |
| Python: `pyclipper` | 1.4.0 | MIT |
| Python: `pydantic` | 2.14.1 | MIT |
| Python: `python-multipart` | 0.0.32 | Apache-2.0 |
| Python: `pywebpush` | 2.5.0 | MPL-2.0 |
| Python: `pywin32` | 312 | PSF-2.0 |
| Python: `pyzmq` | 27.2.0 | BSD-3-Clause |
| Python: `rapidfuzz` | 3.14.6 | MIT |
| Python: `regex` | 2026.9.29 | Apache-2.0 AND CNRI-Python |
| Python: `requests` | 2.34.2 | Apache-2.0 |
| Python: `rich` | 14.3.4 | MIT |
| Python: `ruamel.yaml` | 0.19.1 | MIT |
| Python: `scikit-build` | 0.19.1 | MIT |
| Python: `scipy` | 1.17.1 | BSD-3-Clause |
| Python: `shapely` | 2.2.0 | BSD-3-Clause |
| Python: `sherpa-onnx` | 1.13.8 | not reported |
| Python: `slowapi` | 0.1.10 | MIT |
| Python: `soundfile` | 0.14.0 | BSD-3-Clause |
| Python: `sqlite-vec` | 0.1.9 | not reported |
| Python: `starlette` | 1.8.0 | BSD-3-Clause |
| Python: `tensorflow-cpu` | 2.21.0 | Apache-2.0 |
| Python: `titlecase` | 2.4.1 | MIT |
| Python: `transformers` | 5.20.1 | not reported |
| Python: `tzdata` | 2026.5 | Apache-2.0 |
| Python: `tzlocal` | 5.4.4 | MIT |
| Python: `unidecode` | 1.4.0 | GPL-2.0-or-later |
| Python: `uvicorn` | 0.54.0 | BSD-3-Clause |
| Python: `ws4py` | 0.6.0 | BSD-3-Clause |
| npm: `@cycjimmy/jsmpeg-player` | 6.1.2 | MIT |
| npm: `@eslint/js` | 10.0.1 | MIT |
| npm: `@hookform/resolvers` | 5.9.2 | MIT |
| npm: `@playwright/test` | 1.64.1 | Apache-2.0 |
| npm: `@radix-ui/react-alert-dialog` | 1.2.1 | MIT |
| npm: `@radix-ui/react-aspect-ratio` | 1.2.0 | MIT |
| npm: `@radix-ui/react-checkbox` | 1.4.1 | MIT |
| npm: `@radix-ui/react-collapsible` | 1.2.1 | MIT |
| npm: `@radix-ui/react-context-menu` | 2.4.1 | MIT |
| npm: `@radix-ui/react-dialog` | 1.3.1 | MIT |
| npm: `@radix-ui/react-dropdown-menu` | 2.2.1 | MIT |
| npm: `@radix-ui/react-hover-card` | 1.2.1 | MIT |
| npm: `@radix-ui/react-label` | 2.1.17 | MIT |
| npm: `@radix-ui/react-popover` | 1.3.1 | MIT |
| npm: `@radix-ui/react-progress` | 1.2.1 | MIT |
| npm: `@radix-ui/react-radio-group` | 1.5.1 | MIT |
| npm: `@radix-ui/react-scroll-area` | 1.4.0 | MIT |
| npm: `@radix-ui/react-select` | 2.4.1 | MIT |
| npm: `@radix-ui/react-separator` | 1.2.0 | MIT |
| npm: `@radix-ui/react-slider` | 1.6.1 | MIT |
| npm: `@radix-ui/react-slot` | 1.5.0 | MIT |
| npm: `@radix-ui/react-switch` | 1.4.1 | MIT |
| npm: `@radix-ui/react-tabs` | 1.2.1 | MIT |
| npm: `@radix-ui/react-toggle` | 1.2.1 | MIT |
| npm: `@radix-ui/react-toggle-group` | 1.2.1 | MIT |
| npm: `@radix-ui/react-tooltip` | 1.4.1 | MIT |
| npm: `@rjsf/core` | 6.11.0 | Apache-2.0 |
| npm: `@rjsf/shadcn` | 6.11.0 | MIT |
| npm: `@rjsf/utils` | 6.11.0 | Apache-2.0 |
| npm: `@rjsf/validator-ajv8` | 6.11.0 | Apache-2.0 |
| npm: `@types/js-yaml` | 4.0.9 | MIT |
| npm: `@types/lodash` | 4.17.26 | MIT |
| npm: `@types/node` | 26.6.5 | MIT |
| npm: `@types/react` | 19.3.0 | MIT |
| npm: `@types/react-dom` | 19.3.0 | MIT |
| npm: `@vitejs/plugin-react` | 6.1.2 | MIT |
| npm: `apexcharts` | 8.3.1 | SEE LICENSE IN LICENSE.md |
| npm: `autoprefixer` | 10.6.1 | MIT |
| npm: `axios` | 1.20.0 | MIT |
| npm: `class-variance-authority` | 0.7.1 | Apache-2.0 |
| npm: `clsx` | 2.1.1 | MIT |
| npm: `cmdk` | 1.1.1 | MIT |
| npm: `copy-to-clipboard` | 4.0.2 | MIT |
| npm: `date-fns` | 4.4.0 | MIT |
| npm: `date-fns-tz` | 3.2.0 | MIT |
| npm: `esbuild` | 0.28.2 | MIT |
| npm: `eslint` | 10.13.0 | MIT |
| npm: `eslint-config-prettier` | 10.1.8 | MIT |
| npm: `eslint-plugin-prettier` | 5.5.7 | MIT |
| npm: `eslint-plugin-react-hooks` | 7.1.1 | MIT |
| npm: `eslint-plugin-react-refresh` | 0.5.7 | MIT |
| npm: `framer-motion` | 14.3.0 | MIT |
| npm: `globals` | 17.13.0 | MIT |
| npm: `hls.js` | 1.7.3 | Apache-2.0 |
| npm: `i18next` | 26.5.2 | MIT |
| npm: `i18next-cli` | 1.77.0 | MIT |
| npm: `i18next-http-backend` | 4.0.4 | MIT |
| npm: `idb-keyval` | 6.3.0 | Apache-2.0 |
| npm: `js-yaml` | 5.5.0 | MIT |
| npm: `konva` | 10.9.0 | MIT |
| npm: `lodash` | 4.18.1 | MIT |
| npm: `lucide-react` | 1.59.0 | ISC |
| npm: `monaco-editor` | 0.57.0 | MIT |
| npm: `monaco-yaml` | 5.5.1 | MIT |
| npm: `next-themes` | 0.4.6 | MIT |
| npm: `nosleep.js` | 0.12.0 | MIT |
| npm: `patch-package` | 8.0.1 | MIT |
| npm: `postcss` | 8.5.30 | MIT |
| npm: `prettier` | 3.9.10 | MIT |
| npm: `prettier-plugin-tailwindcss` | 0.8.1 | MIT |
| npm: `react` | 19.3.1 | MIT |
| npm: `react-apexcharts` | 2.1.1 | SEE LICENSE IN LICENSE |
| npm: `react-day-picker` | 10.0.2 | MIT |
| npm: `react-device-detect` | 2.2.3 | MIT |
| npm: `react-dom` | 19.3.1 | MIT |
| npm: `react-dropzone` | 20.1.4 | MIT |
| npm: `react-grid-layout` | 2.3.0 | MIT |
| npm: `react-hook-form` | 7.90.0 | MIT |
| npm: `react-i18next` | 17.1.0 | MIT |
| npm: `react-icons` | 5.7.0 | MIT |
| npm: `react-konva` | 19.3.2 | MIT |
| npm: `react-markdown` | 10.1.0 | MIT |
| npm: `react-router-dom` | 7.18.4 | MIT |
| npm: `react-swipeable` | 7.0.2 | MIT |
| npm: `react-zoom-pan-pinch` | 4.2.0 | MIT |
| npm: `remark-gfm` | 4.0.1 | MIT |
| npm: `scroll-into-view-if-needed` | 3.1.0 | MIT |
| npm: `sonner` | 2.0.8 | MIT |
| npm: `swr` | 2.5.1 | MIT |
| npm: `tailwind-merge` | 3.7.0 | MIT |
| npm: `tailwind-scrollbar` | 4.0.2 | MIT |
| npm: `tailwindcss` | 4.3.3 | MIT |
| npm: `tailwindcss-animate` | 1.0.7 | MIT |
| npm: `typescript` | 7.0.2 | Apache-2.0 |
| npm: `typescript-eslint` | 8.71.2 | MIT |
| npm: `use-long-press` | 3.3.0 | MIT |
| npm: `vaul` | 1.1.2 | MIT |
| npm: `virtua` | 0.53.5 | MIT |
| npm: `vite` | 8.3.4 | MIT |
| npm: `vite-plugin-monaco-editor` | 1.1.0 | MIT |
| npm: `zod` | 4.6.7 | MIT |

### Needs a human before redistribution
- Python `py-vapid` — MPL-2.0
- Python `pywebpush` — MPL-2.0
- Python `unidecode` — GPL-2.0-or-later

- Python `paho-mqtt` — reported nothing (unmapped: EPL-2.0 OR BSD-3-Clause)
- Python `peewee` — reported nothing (none)
- Python `Pillow` — reported MIT-CMU (license-expression)
- Python `regex` — reported Apache-2.0 AND CNRI-Python (license-expression)
- Python `sherpa-onnx` — reported nothing (unmapped: Apache licensed, as found in the LICENSE file)
- Python `sqlite-vec` — reported nothing (unmapped: MIT License, Apache License, Version 2.0)
- Python `transformers` — reported nothing (unmapped: Apache 2.0 License)
- npm `apexcharts` — reported SEE LICENSE IN LICENSE.md (license-field)
- npm `react-apexcharts` — reported SEE LICENSE IN LICENSE (license-field)

Generated by `python scripts/license_audit.py`. Registry metadata is
the package author's own claim; confirm against the source tarball
before shipping a bundle outside your own machine.
<!-- END GENERATED DEPENDENCY TABLE -->

