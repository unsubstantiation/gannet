# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Generate REUSE.toml, the file-by-file license mapping for this fork.

The fork's licensing is layered: files that came from blakeblackshear/frigate
and were not touched stay MIT, files this project added are Gannet Material
under the noncommercial license in LICENSE, and files that are Frigate files
with Gannet changes carry both. That mapping is the only thing that makes the
distinction enforceable rather than rhetorical, so it must not be hand-maintained:
regenerate it whenever the fork merges upstream.

The comparison is a byte-for-byte file hash against a checkout of the upstream
project, because the fork's history is squashed and has no usable merge base.

REUSE.toml is also the contract two other files have to keep up with. The
`LicenseRef-GNCL-1.0` id it uses resolves against
LICENSES/LicenseRef-GNCL-1.0.txt, which must stay byte-identical to LICENSE, and
every path this script lists as Gannet Material needs a header comment naming
that id, because the web build strips comments from bundles. frigate/test/test_
licensing.py checks all of that in CI.

Usage, from the repository root::

    # one-time: a checkout of frigate at the commit you compare against
    git clone --depth 1 https://github.com/blakeblackshear/frigate /tmp/frigate
    python scripts/generate_reuse_toml.py --upstream-dir /tmp/frigate
    python scripts/generate_reuse_toml.py --upstream-dir /tmp/frigate --check

`--check` exits non-zero if REUSE.toml no longer matches the tree, which is what
CI uses to keep the mapping honest after a merge.

Binaries, generated artifacts, and everything the upstream tree also has are
covered by the catch-all `**` entry, so a file that this script cannot see (new
upstream file, renamed directory) still resolves to MIT rather than silently
becoming Gannet Material. That is the conservative direction: the fork may not
claim rights it was not given.

A file that exists only here is not automatically original: a rewritten module
that lifted half its body from an upstream file is still a joint work, and
claiming sole copyright in it would repeat the mistake the rest of this
arrangement exists to avoid. So new files are screened for copied lines against
the upstream tree (`DERIVATION_THRESHOLD`) and anything that trips the screen is
marked dual, like a modified upstream file. The screen is a heuristic on literal
line overlap; a human owns the judgment call, and `--report` prints the ratios
nearest the threshold so the borderline files can be read.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REUSE_TOML = ROOT / "REUSE.toml"

UPSTREAM_PROJECT = "blakeblackshear/frigate"
UPSTREAM_COMMIT = "ee2ae1a957c3c19556240b54520ee8631cbd0c9f"
UPSTREAM_COMMIT_DATE = "2026-10-18T17:50:05Z"

FRIGATE_NOTICE = "Copyright (c) 2026 Frigate, Inc. and Frigate contributors"
GANNET_NOTICE = "Copyright (c) 2026 unsubstantiation and the Gannet contributors"

# Paths that exist in the upstream tree but are this fork's own writing rather
# than a modification of upstream's, so they are Gannet Material outright and not
# dual-licensed. Keep this list tiny; every entry is a claim, not a convenience.
GANNET_ONLY_OVERRIDES = ("LICENSE",)

# Paths unsubstantiation makes no claim to, which therefore inherit the catch-all MIT
# entry rather than becoming Gannet Material:
#   - generated catalogs and specs, whose strings belong to the translators and to
#     the code they were generated from;
#   - brand assets that this fork still carries byte-for-byte from Frigate, which
#     are Frigate, Inc. property whatever the notice file in that directory says;
#   - editor, spellcheck, and lockfile configuration too thin to own.
# Each of these is disclaimed only where upstream has the same path; see
# is_not_claimed.
NOT_CLAIMED_PATTERNS = (
    "web/src/locales/**",
    "docs/static/frigate-api.yaml",
    "web/images/branding/**",
    "docs/static/img/**",
    ".cspell/**",
    ".vscode/**",
    ".gitignore",
    ".gitattributes",
    ".github/dependabot.yml",
    "package-lock.json",
    "web/package-lock.json",
    "docs/package-lock.json",
    "notebooks/**",
)

# Never claimed, wherever they came from. Frigate's license text is the case that
# counts: it sits at a path upstream does not have, so a "new file, therefore
# ours" rule would mark Frigate's own license as Gannet Material. That is the
# exact error this layout exists to avoid, so it is ruled out by name.
NEVER_CLAIMED = (
    "LICENSES/MIT.txt",
    "scripts/license_audit_cache.json",
)


# Fraction of a new file's significant lines that must appear verbatim in the
# upstream tree before the file is treated as derived rather than original.
DERIVATION_THRESHOLD = 0.25
DERIVATION_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".css"}


def significant_lines(path: Path) -> set[str]:
    """Lines worth comparing: stripped, long enough to be a real statement."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return {
        line.strip()
        for line in text.splitlines()
        if len(line.strip()) >= 32 and not line.strip().startswith(("#", "//", "/*", "*"))
    }


def upstream_line_index(upstream_dir: Path) -> set[str]:
    """Every significant line in the upstream tree's source files."""
    index: set[str] = set()
    for path in upstream_dir.rglob("*"):
        if path.suffix in DERIVATION_SUFFIXES and path.is_file() and ".git" not in path.parts:
            index |= significant_lines(path)
    return index


def derivation_ratio(rel: str, index: set[str]) -> float:
    """Share of this file's significant lines that already exist upstream."""
    here = significant_lines(ROOT / rel)
    if not here or not index:
        return 0.0
    return len(here & index) / len(here)


# Brand artwork is the one place where "upstream has this path too" says nothing
# about whose bytes are in the file: this fork replaced Frigate's logo, wordmark,
# and icon set with its own art. So a branding file that differs from upstream - or
# that upstream does not have at all - is Gannet Material, not a modification of
# Frigate's artwork, and it is claimed. A branding file that is byte-identical to
# upstream is Frigate's and stays disclaimed, and
# `frigate.test.test_licensing` fails if one is present in the tree at all.
BRANDING_PREFIXES = ("web/images/branding/", "docs/static/img/branding/")


def same_bytes(here: Path, there: Path) -> bool:
    """Whether this file is still upstream's, byte for byte."""
    mine = digest(here)
    return mine is not None and mine == digest(there)


def is_not_claimed(rel: str, exists_upstream: bool) -> bool:
    """Whether this fork disclaims the path, so the catch-all MIT entry governs it.

    The pattern list is conditioned on upstream having the same path on purpose: a
    file under `web/images/branding/` that upstream does not have is Gannet's own
    logo, and that one genuinely is this fork's to claim.
    """
    if rel in NEVER_CLAIMED:
        return True
    if not exists_upstream:
        return False
    return any(
        fnmatch.fnmatch(rel, pattern) or rel == pattern.rstrip("/*")
        for pattern in NOT_CLAIMED_PATTERNS
    )

HEADER = f"""# Which license covers which file, for tools and for people.
#
# GENERATED FILE - do not edit by hand. Regenerate with:
#     python scripts/generate_reuse_toml.py --upstream-dir <path to a {UPSTREAM_PROJECT} checkout>
#
# Compared against {UPSTREAM_PROJECT}@{UPSTREAM_COMMIT} ({UPSTREAM_COMMIT_DATE}).
# Spec: https://reuse.software/spec-3.3/#reusetoml
#   "**"                  -> MIT      (files this fork did not author)
#   MIT AND LicenseRef-GNCL-1.0        (upstream files carrying Gannet changes)
#   LicenseRef-GNCL-1.0                (Gannet Material: new, original files)
#
# A file that exists only here is screened for copied upstream lines before it is
# claimed as Gannet Material (see DERIVATION_THRESHOLD in the script); files that
# trip the screen are dual, like modified ones. Files that exist only here because
# upstream moved or renamed them are still upstream material; audit the last list
# below whenever the upstream pin changes.
"""


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return sorted(line for line in out.splitlines() if line)


def digest(path: Path) -> str | None:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


def classify(
    upstream_dir: Path,
) -> tuple[list[str], list[str], list[str], dict[str, float]]:
    """Return (dual files, original Gannet files, not-claimed files, ratios)."""
    index = upstream_line_index(upstream_dir)
    modified: list[str] = []
    only_here: list[str] = []
    not_claimed: list[str] = []
    ratios: dict[str, float] = {}
    for rel in tracked_files():
        here, there = ROOT / rel, upstream_dir / rel
        if rel.startswith(BRANDING_PREFIXES) and not same_bytes(here, there):
            only_here.append(rel)
            continue
        if is_not_claimed(rel, there.exists()):
            not_claimed.append(rel)
            continue
        if rel in GANNET_ONLY_OVERRIDES:
            only_here.append(rel)
        elif not there.exists():
            ratio = derivation_ratio(rel, index) if Path(rel).suffix in DERIVATION_SUFFIXES else 0.0
            ratios[rel] = ratio
            if ratio > DERIVATION_THRESHOLD:
                modified.append(rel)
            else:
                only_here.append(rel)
        elif digest(here) != digest(there):
            modified.append(rel)
    return modified, only_here, not_claimed, ratios


def render_array(paths: list[str], indent: str = "    ") -> str:
    if not paths:
        return "[]"
    body = ",\n".join(f'{indent}"{p}"' for p in paths)
    return "[\n" + body + ",\n  ]"


def render_copyright(values: list[str]) -> str:
    if len(values) == 1:
        return f'"{values[0]}"'
    return "[\n" + ",\n".join(f'    "{value}"' for value in values) + ",\n  ]"


def render(modified: list[str], only_here: list[str]) -> str:
    blocks = [
        HEADER,
        "version = 1",
        "",
        "[[annotations]]",
        'path = "**"',
        'precedence = "closest"',
        f'SPDX-FileCopyrightText = "{FRIGATE_NOTICE}"',
        'SPDX-License-Identifier = "MIT"',
        "",
        "# Frigate files with Gannet changes: the upstream portions stay MIT and",
        "# the Gannet portions carry the noncommercial terms. Both apply.",
        "[[annotations]]",
        f"path = {render_array(modified)}",
        'precedence = "closest"',
        f"SPDX-FileCopyrightText = {render_copyright([FRIGATE_NOTICE, GANNET_NOTICE])}",
        'SPDX-License-Identifier = "MIT AND LicenseRef-GNCL-1.0"',
        "",
        "# Gannet Material: authored here, licensed only under LICENSE.",
        "[[annotations]]",
        f"path = {render_array(only_here)}",
        'precedence = "closest"',
        f'SPDX-FileCopyrightText = "{GANNET_NOTICE}"',
        'SPDX-License-Identifier = "LicenseRef-GNCL-1.0"',
        "",
    ]
    return "\n".join(blocks)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-dir",
        type=Path,
        help=f"path to a checkout of {UPSTREAM_PROJECT} at the pinned commit",
    )
    parser.add_argument(
        "--check", action="store_true", help="fail if REUSE.toml differs from a regeneration"
    )
    parser.add_argument(
        "--report", action="store_true", help="print derivation ratios near the threshold"
    )
    args = parser.parse_args()

    if not args.upstream_dir:
        print("error: --upstream-dir is required", file=sys.stderr)
        return 2
    upstream = args.upstream_dir.resolve()
    if not (upstream / "frigate").is_dir():
        print(f"error: {upstream} does not look like a {UPSTREAM_PROJECT} checkout", file=sys.stderr)
        return 2

    modified, only_here, not_claimed, ratios = classify(upstream)
    if args.report:
        near = sorted(
            ((r, p) for p, r in ratios.items() if abs(r - DERIVATION_THRESHOLD) < 0.25),
            reverse=True,
        )
        print(f"derivation screen (threshold {DERIVATION_THRESHOLD}):")
        for ratio, path in near or []:
            print(f"  {ratio:5.2f}  {path}")
        if not near:
            print("  nothing within 0.25 of the threshold")
    text = render(modified, only_here)
    if args.check:
        if not REUSE_TOML.exists() or REUSE_TOML.read_text(encoding="utf-8") != text:
            print("REUSE_TOML is stale; run scripts/generate_reuse_toml.py", file=sys.stderr)
            return 1
        print(f"REUSE.toml is current ({len(modified)} dual, {len(only_here)} Gannet-only)")
        return 0
    REUSE_TOML.write_text(text, encoding="utf-8")
    total = len(tracked_files())
    print(
        f"REUSE.toml: {total - len(modified) - len(only_here) - len(not_claimed)} MIT, "
        f"{len(modified)} MIT AND LicenseRef-GNCL-1.0, {len(only_here)} LicenseRef-GNCL-1.0, "
        f"{len(not_claimed)} not claimed by this fork"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
