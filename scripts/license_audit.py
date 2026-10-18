# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Regenerate the dependency license table in THIRD_PARTY.md.

The project's own terms live in LICENSE. What this script reports is the other
half of the picture: the licenses of the packages and artifacts the application
depends on, which this project cannot relicense and which the noncommercial
terms in LICENSE deliberately do not touch.

Reads requirements.txt and web/package.json, asks PyPI and the npm registry for
the license each dependency reports, and rewrites the generated block in
THIRD_PARTY.md between the BEGIN/END markers. Everything outside those markers
is hand-written and preserved.

Registry metadata is a claim by the package author, not a legal opinion. The
`license` field is often stale or free-form, so the SPDX expression in the
`License ::` classifiers wins when both exist, and anything the script cannot
map to an SPDX identifier lands in the "needs a human" section.

Usage (from the repository root, needs network access)::

    python scripts/license_audit.py            # rewrite THIRD_PARTY.md
    python scripts/license_audit.py --check    # fail if the file is out of date
    python scripts/license_audit.py --json     # dump the table instead

Pinned runtime artifacts (FFmpeg, go2rtc, the detection and audio models) are
not registry packages, so they are listed in RUNTIME_ARTIFACTS below and must be
updated by hand when bootstrap_windows.py changes its pins.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
WEB_PACKAGE_JSON = ROOT / "web" / "package.json"
THIRD_PARTY = ROOT / "THIRD_PARTY.md"
CACHE = Path(__file__).resolve().parent / "license_audit_cache.json"

BEGIN = "<!-- BEGIN GENERATED DEPENDENCY TABLE (scripts/license_audit.py) -->"
END = "<!-- END GENERATED DEPENDENCY TABLE -->"

# Anything in this set gets called out in THIRD_PARTY.md: a noncommercial term in
# this project's license cannot be pushed onto these packages, and copyleft
# components carry source-availability duties of their own that a distributor has
# to satisfy regardless of what LICENSE says.
COPYLEFT = {
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "LGPL-2.1-only",
    "LGPL-2.1-or-later",
    "LGPL-3.0-only",
    "LGPL-3.0-or-later",
    "AGPL-3.0-only",
    "AGPL-3.0-or-later",
    "MPL-2.0",
    "EPL-1.0",
    "EPL-2.0",
    "CDDL-1.0",
    "CDDL-1.1",
    "Sleepycat",
    "Qhull",
    "Python-2.0",
}

# Licenses that are permissive and compatible with the terms in LICENSE.
PERMISSIVE = {
    "MIT",
    "MIT-0",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "0BSD",
    "Unlicense",
    "CC0-1.0",
    "Zlib",
    "PSF-2.0",
    "Python-2.0",
    "BSL-1.0",
    "curl",
    "blessing",
    "MySQL-exception-FOSS-2.0",
}

CLASSIFIER_RE = re.compile(r"License :: OSI Approved :: (.+)$")

CLASSIFIER_TO_SPDX = {
    "Apache Software License": "Apache-2.0",
    "BSD License": "BSD-3-Clause",
    "GNU General Public License v2 or later (GPLv2+)": "GPL-2.0-or-later",
    "GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
    "GNU Lesser General Public License v2.1 or later (LGPLv2.1+)": "LGPL-2.1-or-later",
    "GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
    "GNU Library or Lesser General Public License (LGPL)": "LGPL-2.1-or-later",
    "GNU Library or Lesser General Public License (LGPL)": "LGPL-2.1-or-later",
    "Intel License": "Intel",
    "ISC License (ISCL)": "ISC",
    "MIT License": "MIT",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "Proprietary License": "LicenseRef-Proprietary",
    "Public Domain": "CC0-1.0",
    "Python Software Foundation License": "PSF-2.0",
    "Server Side Public License v1 (SSPLv1)": "SSPL-1.0",
    "The Unlicense (Unlicense)": "Unlicense",
    "Eclipse Public License 1.0 (EPL-1.0)": "EPL-1.0",
    "Eclipse Public License v2.0 (EPL-2.0)": "EPL-2.0",
    "European Union Public License 1.1 (EUPL 1.1)": "EUPL-1.1",
    "European Union Public License 1.2 (EUPL 1.2)": "EUPL-1.2",
    "GNU Affero General Public License v3 (AGPLv3)": "AGPL-3.0-only",
    "GNU Affero General Public License v3 or later (AGPLv3+)": "AGPL-3.0-or-later",
    "Historical Permission Notice and Caption (HPNC)": "HPND",
    "zlib/libpng License": "Zlib",
}

# Free-form text some projects put in the metadata `license` field.
TEXT_TO_SPDX = {
    "MIT": "MIT",
    "MIT License": "MIT",
    "Apache License, Version 2.0": "Apache-2.0",
    "Apache 2.0": "Apache-2.0",
    "Apache-2.0": "Apache-2.0",
    "Apache Software License": "Apache-2.0",
    "BSD": "BSD-3-Clause",
    "BSD 3-Clause License": "BSD-3-Clause",
    "BSD-3-Clause": "BSD-3-Clause",
    "BSD License": "BSD-3-Clause",
    "ISC License (ISCL)": "ISC",
    "ISC": "ISC",
    "Public Domain": "CC0-1.0",
    "The Unlicense": "Unlicense",
    "Unlicense": "Unlicense",
    "GNU LGPL 2.1 or later (LGPL-2.1-or-later)": "LGPL-2.1-or-later",
    "LGPL-2.1-or-later": "LGPL-2.1-or-later",
    "GNU Lesser General Public License v2.1 or later (LGPL-2.1-or-later)": "LGPL-2.1-or-later",
    "GNU Library or Lesser General Public License (LGPL)": "LGPL-2.1-or-later",
    "GNU GPLv3": "GPL-3.0-or-later",
    "GPL-3.0-or-later": "GPL-3.0-or-later",
    "MPL-2.0": "MPL-2.0",
    "Mozilla Public License 2.0": "MPL-2.0",
    "Eclipse Public License v2.0": "EPL-2.0",
    "EPL-2.0": "EPL-2.0",
    "Eclipse Distribution License - v 1.0": "BSD-3-Clause",
    "Python Software Foundation License": "PSF-2.0",
    "BSD 2-Clause License": "BSD-2-Clause",
    "0BSD": "0BSD",
    "PSF": "PSF-2.0",
    "MIT License (MIT)": "MIT",
    "ISC License": "ISC",
    "BSD-2-Clause": "BSD-2-Clause",
    "Apache 2": "Apache-2.0",
    "MIT OR GPL-3.0-or-later": "MIT",
}

# Runtime artifacts bootstrap_windows.py downloads or that the application
# needs at runtime. Update by hand with the pins in bootstrap_windows.py.
RUNTIME_ARTIFACTS = [
    {
        "name": "FFmpeg",
        "origin": "GyanD/codexffmpeg `essentials_build` Windows build, pinned in bootstrap_windows.py",
        "spdx": "GPL-2.0-or-later (build-dependent)",
        "note": (
            "Gyan's `essentials_build` is configured with external libraries "
            "including x264 and x265, which makes that build GPL rather than "
            "LGPL. Anyone who redistributes a bundle containing it takes on the "
            "GPL source-availability duties for that build. A `shared`/LGPL "
            "build trades that for separate-license DLLs. Not this project's "
            "code and not covered by LICENSE."
        ),
    },
    {
        "name": "go2rtc",
        "origin": "AlexxIT/go2rtc release binary, pinned in bootstrap_windows.py",
        "spdx": "MIT",
        "note": (
            "MIT per the upstream repository. It statically incorporates FFmpeg "
            "libraries, so the same LGPL/GPL build question applies to the "
            "distributed go2rtc.exe."
        ),
    },
    {
        "name": "ssdlite_mobiledet_coco_qat_postprocess.tflite (default detection model)",
        "origin": "google-coral/test_data, tag release-frogfish",
        "spdx": "Apache-2.0",
        "note": (
            "Weights, not code. Machine-learning restrictions in LICENSE speak "
            "to this project's source and documentation; the model's own terms "
            "govern the weights."
        ),
    },
    {
        "name": "YAMNet lite model (audio classification)",
        "origin": "tfhub.dev/google/lite-model/yamnet/classification/tflite/1",
        "spdx": "Apache-2.0",
        "note": "Published by Google on TensorFlow Hub under Apache-2.0; verify the terms at the download URL before redistributing a bundle.",
    },
    {
        "name": "Whisper / faster-whisper model weights (audio transcription)",
        "origin": "fetched at runtime, not vendored",
        "spdx": "MIT (weights) / BSD-3-Clause (OpenAI source)",
        "note": "Model repositories carry their own terms; nothing in this project's license changes them.",
    },
    {
        "name": "ONNX embedding and GenAI models (semantic search, review summaries)",
        "origin": "downloaded on demand into the model cache",
        "spdx": "per-model",
        "note": "Check each model card. Several embedding checkpoints ship under noncommercial or acceptable-use terms already, independent of this project's license.",
    },
]


def fetch_json(url: str, cache: dict[str, Any]) -> Any:
    """GET a URL as JSON, using a checked-in cache to stay re-runnable offline."""
    if url in cache:
        return cache[url]
    request = urllib.request.Request(url, headers={"User-Agent": "gannet-license-audit"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    cache[url] = data
    return data


def load_cache() -> dict[str, Any]:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def requirements_pins(path: Path) -> list[tuple[str, str]]:
    """Return (distribution, pinned prefix) pairs from a requirements file."""
    pins: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = re.match(r"^([A-Za-z0-9._-]+)\s*==\s*([0-9][0-9.]*)", line)
        if match:
            pins.append((match.group(1), match.group(2)))
    return pins


def npm_dependencies(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    names = list(data.get("dependencies", {}))
    names += list(data.get("devDependencies", {}))
    return sorted(set(names))


def pypi_spdx(name: str, pin: str, cache: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": name, "pin": pin, "spdx": None, "source": "none"}
    try:
        data = fetch_json(f"https://pypi.org/pypi/{name}/json", cache)
    except Exception as exc:  # registry unreachable or package renamed
        entry["error"] = str(exc)
        return entry
    releases = data.get("releases", {})
    info = data.get("info", {})
    # Newest release matching the pinned prefix, else the latest release.
    candidates = sorted(
        (v for v in releases if v.startswith(pin) and "rc" not in v and "dev" not in v),
        key=lambda v: [int(p) if p.isdigit() else 0 for p in re.split(r"[.\-]", v)],
    )
    version = candidates[-1] if candidates else info.get("version")
    entry["version"] = version
    expr = (info.get("license_expression") or "").strip()
    if expr:
        entry["spdx"], entry["source"] = expr, "license-expression"
        return entry
    classifiers = [
        CLASSIFIER_TO_SPDX[m.group(1)]
        for m in (CLASSIFIER_RE.search(c) for c in info.get("classifiers", []))
        if m and m.group(1) in CLASSIFIER_TO_SPDX
    ]
    if classifiers:
        entry["spdx"], entry["source"] = sorted(set(classifiers))[0], "classifier"
        return entry
    raw = (info.get("license") or "").strip()
    if raw in TEXT_TO_SPDX:
        entry["spdx"], entry["source"] = TEXT_TO_SPDX[raw], "license-field"
    elif raw:
        entry["spdx"], entry["source"] = None, f"unmapped: {raw[:60]}"
    return entry


def npm_spdx(name: str, cache: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": name, "pin": "latest", "spdx": None, "source": "none"}
    try:
        data = fetch_json(f"https://registry.npmjs.org/{name}", cache)
    except Exception as exc:
        entry["error"] = str(exc)
        return entry
    latest = (data.get("dist-tags") or {}).get("latest")
    version = (data.get("versions") or {}).get(latest, {})
    entry["version"] = latest
    for field in ("license", "licenseSPDX"):
        value = version.get(field)
        if isinstance(value, str) and value:
            entry["spdx"], entry["source"] = value.strip(), "license-field"
            return entry
    licenses = version.get("licenses")
    if isinstance(licenses, str):
        entry["spdx"], entry["source"] = licenses.strip(), "licenses-field"
    elif isinstance(licenses, list) and licenses:
        types = [str(x.get("type")) for x in licenses if isinstance(x, dict) and x.get("type")]
        if types:
            entry["spdx"], entry["source"] = " OR ".join(sorted(set(types))), "licenses-array"
    if entry["spdx"] in TEXT_TO_SPDX:
        entry["spdx"] = TEXT_TO_SPDX[entry["spdx"]]
    if not entry["spdx"] and version.get("license") is None:
        entry["source"] = "no field: (c) npm Inc. MIT License style README"
    return entry


def bucket(spdx: str | None) -> str:
    if not spdx:
        return "unknown"
    tokens = set(re.split(r"[ ,]+|(?:AND|OR)", spdx)) - {""}
    if any(t in COPYLEFT for t in tokens):
        return "copyleft"
    if all(t in PERMISSIVE for t in tokens):
        return "permissive"
    return "review"


def collect() -> dict[str, list[dict[str, Any]]]:
    cache = load_cache()
    py_jobs = requirements_pins(REQUIREMENTS)
    js_jobs = npm_dependencies(WEB_PACKAGE_JSON)
    with ThreadPoolExecutor(max_workers=12) as pool:
        py_rows = list(pool.map(lambda a: pypi_spdx(*a, cache), py_jobs))
        js_rows = list(pool.map(lambda n: npm_spdx(n, cache), js_jobs))
    CACHE.write_text(json.dumps(cache, indent=0, sort_keys=True), encoding="utf-8")
    return {"python": py_rows, "npm": js_rows}


def render(rows: dict[str, list[dict[str, Any]]]) -> str:
    lines = [
        "| Dependency | Version checked | SPDX license |",
        "| --- | --- | --- |",
    ]
    flagged: list[str] = []
    unmapped: list[str] = []
    for section, title in (("python", "Python"), ("npm", "npm")):
        for row in sorted(rows[section], key=lambda r: r["name"].lower()):
            spdx = row.get("spdx")
            shown = spdx or "not reported"
            lines.append(f"| {title}: `{row['name']}` | {row.get('version', '?')} | {shown} |")
            kind = bucket(spdx)
            if kind == "copyleft":
                flagged.append(f"- {title} `{row['name']}` — {spdx}")
            elif kind in {"unknown", "review"}:
                unmapped.append(
                    f"- {title} `{row['name']}` — reported {spdx or 'nothing'} "
                    f"({row.get('source', 'no metadata')}"
                    f"{'; ' + row['error'] if row.get('error') else ''})"
                )
    lines.append("")
    lines.append("### Needs a human before redistribution")
    lines.append(
        "\n".join(flagged)
        + ("\n\n" + "\n".join(unmapped) if unmapped else "")
        if (flagged or unmapped)
        else "- None flagged."
    )
    lines.append("")
    lines.append("Generated by `python scripts/license_audit.py`. Registry metadata is")
    lines.append("the package author's own claim; confirm against the source tarball")
    lines.append("before shipping a bundle outside your own machine.")
    return "\n".join(lines)


def apply_to_doc(block: str) -> tuple[str, bool]:
    text = THIRD_PARTY.read_text(encoding="utf-8") if THIRD_PARTY.exists() else ""
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        new = f"{head}{BEGIN}\n{block}\n{END}{tail}"
        return new, new != text
    return f"{text.rstrip()}\n\n{BEGIN}\n{block}\n{END}\n", True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print JSON instead of rewriting the file")
    parser.add_argument("--check", action="store_true", help="exit non-zero if THIRD_PARTY.md is stale")
    args = parser.parse_args()

    rows = collect()
    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        print()
        return 0
    block = render(rows)
    new_text, changed = apply_to_doc(block)
    if args.check:
        if changed:
            print("THIRD_PARTY.md is stale; run `python scripts/license_audit.py`", file=sys.stderr)
            return 1
        print("THIRD_PARTY.md is current")
        return 0
    THIRD_PARTY.write_text(new_text, encoding="utf-8")
    total = len(rows["python"]) + len(rows["npm"])
    print(f"rewrote the generated block in THIRD_PARTY.md for {total} dependencies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
