# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Checks on the layered licensing: the license files and REUSE.toml must agree.

The fork's licensing claim is narrow on purpose: upstream Frigate files stay MIT,
the files this project authored carry the noncommercial terms in LICENSE, and
REUSE.toml says which is which. That only holds if the pieces stay consistent.
Each test here fails on a mistake a future merge or a careless rename would
actually make:

* ``test_license_text_matches_the_spdx_copy`` — the text scanners resolve
  ``LicenseRef-GNCL-1.0`` against drifts from the text humans read.
* ``test_upstream_mit_notice_is_intact`` — the MIT License requires its own
  notice to travel unmodified, so editing it would put this repository outside
  the terms it was granted.
* ``test_reuse_mapping_paths_exist`` / ``..._is_disjoint`` — a stale mapping
  silently reassigns copyright, which is the one error this layout cannot afford.
* ``test_gannet_material_is_marked_in_headers`` — the convention documented in
  CONTRIBUTING.md.
* ``test_readmes_do_not_advertise_the_wrong_license`` — the READMEs used to
  badge the whole repository MIT. A badge that overstates the license is the
  misrepresentation risk this structure exists to remove, and it is the easiest
  thing to reintroduce by accident.
* ``test_rights_reservations_are_published`` — the machine-readable no-AI/TDM
  reservation is only credible if the files are really served.

Run from the repository root::

    python -m unittest gannet.test.test_licensing
"""

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]

LICENSE_TEXT = REPO / "LICENSE"
LICENSE_COPY = REPO / "LICENSES" / "LicenseRef-GNCL-1.0.txt"
MIT_TEXT = REPO / "LICENSES" / "MIT.txt"
REUSE_TOML = REPO / "REUSE.toml"

GANNET_ID = "LicenseRef-GNCL-1.0"
HEADER = f"SPDX-License-Identifier: {GANNET_ID}"

# A corporate licensor that was written into early drafts and never existed. Built
# by concatenation so this file, which forbids the phrase, does not contain it.
FAKE_ENTITY = "Gannet" + ", Inc."

# The sentences the MIT License requires to be reproduced verbatim.
MIT_REQUIRED = (
    "Copyright (c) 2026 Frigate, Inc. (Frigate™)",
    "Permission is hereby granted, free of charge, to any person obtaining a copy",
    "The above copyright notice and this permission notice shall be included in all",
    'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND',
)

# Files whose comments are stripped by the bundler, so a header is the only place
# a scanner and a human can both read the claim. Markdown and JSON carry none.
HEADER_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".css", ".ps1"}


def tracked_files() -> list[str]:
    """`git ls-files`, or the tree itself when there is no git checkout."""
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return [
            str(p.relative_to(REPO))
            for p in REPO.rglob("*")
            if p.is_file() and ".git" not in p.parts
        ]
    return sorted(line for line in out.splitlines() if line)


def reuse_blocks() -> list[dict]:
    if not REUSE_TOML.is_file():
        raise AssertionError(
            f"{REUSE_TOML.relative_to(REPO)} is missing; run scripts/generate_reuse_toml.py"
        )
    return tomllib.loads(REUSE_TOML.read_text(encoding="utf-8"))["annotations"]


def paths_for(identifier: str) -> list[str]:
    for block in reuse_blocks():
        if block["SPDX-License-Identifier"] == identifier:
            path = block["path"]
            return [path] if isinstance(path, str) else list(path)
    return []


class TestLicenseTexts(unittest.TestCase):
    def test_license_text_matches_the_spdx_copy(self):
        self.assertEqual(
            LICENSE_TEXT.read_bytes(),
            LICENSE_COPY.read_bytes(),
            "LICENSES/LicenseRef-GNCL-1.0.txt must be a byte-for-byte copy of "
            "LICENSE; copy it with `cp LICENSE LICENSES/LicenseRef-GNCL-1.0.txt`",
        )

    def test_license_declares_what_it_is(self):
        text = LICENSE_TEXT.read_text(encoding="utf-8")
        self.assertIn(f"`{GANNET_ID}`", text)
        self.assertIn("not an open-source license", text)
        # PolyForm's own rule: a modified version of one of their licenses must
        # not carry their name or URL. The provenance belongs in LICENSING.md.
        self.assertNotIn("PolyForm", text)
        self.assertNotIn("polyformproject.org", text)
        self.assertIn("Required Notice:", text)
        self.assertLessEqual(text.count("\n## "), 40, "sections should stay navigable")

    def test_upstream_mit_notice_is_intact(self):
        text = MIT_TEXT.read_text(encoding="utf-8")
        for line in MIT_REQUIRED:
            self.assertIn(line, text, f"MIT notice lost or edited: {line[:40]}...")
        head = text.split("---", 1)[0]
        self.assertNotIn(
            "Gannet", head, "the block above the note is Frigate's text, verbatim"
        )

    def test_mit_notice_is_not_claimed_as_gannet_material(self):
        self.assertNotIn(
            "LICENSES/MIT.txt",
            paths_for(GANNET_ID),
            "Frigate's license text is not this fork's to claim",
        )

    def test_root_license_is_not_marked_upstream(self):
        self.assertIn("LICENSE", paths_for(GANNET_ID))
        self.assertNotIn("LICENSE", paths_for("MIT AND LicenseRef-GNCL-1.0"))


class TestReuseMapping(unittest.TestCase):
    def test_every_mapped_path_exists_and_is_tracked(self):
        tracked = set(tracked_files())
        for block in reuse_blocks():
            path = block["path"]
            if isinstance(path, str):
                continue  # the "**" catch-all
            for rel in path:
                self.assertIn(
                    rel, tracked, f"REUSE.toml maps a path that is not tracked: {rel}"
                )

    def test_buckets_are_disjoint(self):
        seen: dict[str, str] = {}
        for block in reuse_blocks():
            path = block["path"]
            if isinstance(path, str):
                continue
            for rel in path:
                self.assertNotIn(
                    rel,
                    seen,
                    f"{rel} is mapped twice, by {seen.get(rel)} and {block['SPDX-License-Identifier']}",
                )
                seen[rel] = block["SPDX-License-Identifier"]

    def test_mapping_order_is_specific_last(self):
        ids = [block["SPDX-License-Identifier"] for block in reuse_blocks()]
        self.assertEqual(
            ids[0], "MIT", "the catch-all must come first so closer entries win"
        )
        self.assertEqual(
            ids[-1], GANNET_ID, "Gannet Material must be the closest entry"
        )

    def test_generated_file_says_it_is_generated(self):
        head = REUSE_TOML.read_text(encoding="utf-8").splitlines()[:12]
        self.assertTrue(any("GENERATED" in line for line in head))
        self.assertTrue(any("generate_reuse_toml" in line for line in head))

    def test_renamed_package_is_compared_to_its_upstream_path(self):
        spec = importlib.util.spec_from_file_location(
            "generate_reuse_toml", REPO / "scripts" / "generate_reuse_toml.py"
        )
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        rel = "gannet/api/defs/tags.py"
        with tempfile.TemporaryDirectory() as directory:
            upstream = Path(directory)
            original = upstream / "frigate" / "api" / "defs" / "tags.py"
            original.parent.mkdir(parents=True)
            original.write_bytes((REPO / rel).read_bytes())
            with patch.object(generator, "tracked_files", return_value=[rel]):
                modified, only_here, _, _ = generator.classify(upstream)
                self.assertNotIn(rel, modified)
                self.assertNotIn(rel, only_here)
                original.write_text("different upstream content", encoding="utf-8")
                modified, only_here, _, _ = generator.classify(upstream)
                self.assertIn(rel, modified)
                self.assertNotIn(rel, only_here)

    def test_explicit_mixed_override_preserves_existing_classification(self):
        spec = importlib.util.spec_from_file_location(
            "generate_reuse_toml", REPO / "scripts" / "generate_reuse_toml.py"
        )
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        rel = "gannet/test/test_media_sync.py"
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(generator, "tracked_files", return_value=[rel]):
                modified, only_here, _, _ = generator.classify(Path(directory))
        self.assertIn(rel, modified)
        self.assertNotIn(rel, only_here)

    def test_mapping_is_current_against_the_upstream_pin(self):
        """Regenerate and compare, but only when an upstream checkout is at hand.

        `tomllib` needs the repository's minimum Python; no separate guard, since
        the rest of the file would not import on anything older anyway.
        """
        script = REPO / "scripts" / "generate_reuse_toml.py"
        upstream = Path("/tmp/frigate-license-compare")
        if not (upstream / "frigate").is_dir():
            self.skipTest(
                f"no upstream checkout at {upstream}; run scripts/generate_reuse_toml.py after merging"
            )
        before = REUSE_TOML.read_text(encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(script), "--upstream-dir", str(upstream), "--check"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(before, REUSE_TOML.read_text(encoding="utf-8"))


class TestGannetMaterialHeaders(unittest.TestCase):
    def test_gannet_material_is_marked_in_headers(self):
        missing = []
        for rel in paths_for(GANNET_ID):
            path = REPO / rel
            if path.suffix not in HEADER_SUFFIXES or not path.is_file():
                continue
            head = "\n".join(
                path.read_text(encoding="utf-8", errors="replace").splitlines()[:5]
            )
            if HEADER not in head:
                missing.append(rel)
        self.assertFalse(
            missing,
            "new Gannet Material files need the SPDX header (see CONTRIBUTING.md):\n  "
            + "\n  ".join(missing),
        )

    def test_only_the_catch_all_maps_to_plain_mit(self):
        block = reuse_blocks()[0]
        self.assertEqual(block["SPDX-License-Identifier"], "MIT")
        self.assertEqual(
            block["path"],
            "**",
            "no explicit path may be MIT-only: an unclaimed file is fine, a claimed one is a bug",
        )

    def test_no_upstream_file_claimed_in_headers(self):
        """A header on a file REUSE.toml maps as MIT-only would contradict itself."""
        dual_or_upstream = set(paths_for("MIT AND LicenseRef-GNCL-1.0"))
        offenders = []
        for rel in sorted(dual_or_upstream):
            path = REPO / rel
            if path.suffix not in {".py", ".ts", ".tsx"} or not path.is_file():
                continue
            head = "\n".join(
                path.read_text(encoding="utf-8", errors="replace").splitlines()[:5]
            )
            if HEADER in head:
                offenders.append(rel)
        self.assertFalse(
            offenders,
            "these files are Frigate's with Gannet edits; the mapping in REUSE.toml "
            "is what records that, a header would overstate it:\n  "
            + "\n  ".join(offenders),
        )


class TestPublicStatements(unittest.TestCase):
    def test_readmes_do_not_advertise_the_wrong_license(self):
        for rel in ("README.md", "README_CN.md"):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertNotIn(
                "opensource.org/licenses/MIT",
                text,
                f"{rel} still badges the whole repository as MIT/open source",
            )
            self.assertNotRegex(
                text,
                r"\[!\[License: MIT\]",
                f"{rel} still carries the MIT badge",
            )
            self.assertIn(
                "LICENSES/MIT.txt",
                text,
                f"{rel} must point at the upstream license it preserves",
            )

    def test_trademark_policy_does_not_misdescribe_the_license(self):
        text = (REPO / "TRADEMARK.md").read_text(encoding="utf-8")
        self.assertNotIn(
            "The software in this repository is licensed under the [MIT License](LICENSE)",
            text,
        )
        self.assertIn("Gannet Noncommercial License", text)

    def test_package_metadata_matches_the_layering(self):
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^license\s*=\s*"([^"]+)"', text, re.MULTILINE)
        self.assertIsNotNone(match, "pyproject.toml needs a PEP 639 license expression")
        self.assertEqual(match.group(1), f"{GANNET_ID} AND MIT")

    def test_rights_reservations_are_published(self):
        robots = REPO / "docs" / "static" / "robots.txt"
        self.assertTrue(
            robots.is_file(), "robots.txt is what the license cross-references"
        )
        body = robots.read_text(encoding="utf-8")
        self.assertIn("Disallow: /", body)
        self.assertIn("Content-Signal", body)

        tdmrep = REPO / "docs" / "static" / ".well-known" / "tdmrep.json"
        self.assertTrue(
            tdmrep.is_file(), "TDMRep belongs under .well-known, not at the site root"
        )
        rules = json.loads(tdmrep.read_text(encoding="utf-8"))
        self.assertIsInstance(rules, list)
        self.assertTrue(rules, "TDMRep must express at least one rule")
        for rule in rules:
            self.assertEqual(rule["tdm-reservation"], 1)
            self.assertIn("location", rule)

        headers = (REPO / "docs" / "static" / "_headers").read_text(encoding="utf-8")
        self.assertIn("TDM-Reservation: 1", headers)

        config = (REPO / "docs" / "docusaurus.config.ts").read_text(encoding="utf-8")
        self.assertIn('"tdm-reservation"', config)


class TestBranding(unittest.TestCase):
    """Branding is a licensing obligation here, not decoration.

    Frigate's brand notice demands that a fork shipping a modified version replace
    its logo and icons, and this fork's `TRADEMARK.md` claims Gannet marks in the
    same breath. Both statements are only true if the tree matches them, so they
    are checked rather than asserted.
    """

    #: Frigate's artwork, removed rather than licensed. Re-adding one of these is
    #: how a merge quietly undoes the branding swap.
    UPSTREAM_BRAND_FILES = (
        "docs/static/img/branding/frigate.png",
        "docs/static/img/branding/logo.svg",
        "docs/static/img/branding/logo-dark.svg",
    )

    def test_upstream_brand_assets_are_not_shipped(self):
        tracked = set(tracked_files())
        shipped = sorted(path for path in self.UPSTREAM_BRAND_FILES if path in tracked)
        self.assertFalse(
            shipped,
            f"these are Frigate's assets, and this fork's own notices require a fork to "
            f"replace them rather than ship them: {shipped}",
        )

    def test_docs_favicon_is_the_forks_own_icon(self):
        """Same bytes as the shipped UI icon, so the docs cannot drift back."""
        docs = REPO / "docs" / "static" / "img" / "branding" / "favicon.ico"
        ui = REPO / "web" / "images" / "branding" / "favicon.ico"
        self.assertTrue(docs.is_file() and ui.is_file(), "both favicons must exist")
        self.assertEqual(
            docs.read_bytes(),
            ui.read_bytes(),
            "the documentation favicon must be this fork's own icon, not upstream's",
        )
        mark = REPO / "docs" / "static" / "img" / "branding" / "gannet.png"
        self.assertTrue(
            mark.is_file(), "the navbar logo referenced by docusaurus is missing"
        )

    def test_brand_notices_do_not_give_our_artwork_away(self):
        for rel in (
            "web/images/branding/LICENSE",
            "docs/static/img/branding/LICENSE.md",
        ):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertNotIn(
                "proprietary to Frigate",
                text,
                f"{rel} assigns this fork's own artwork to Frigate, Inc.",
            )
            self.assertIn(
                "replace these assets",
                text.lower(),
                f"{rel} must tell a fork to swap the assets out",
            )
            self.assertIn(
                "unsubstantiation", text, f"{rel} must name who the marks sit with"
            )

    def test_no_notice_invents_a_legal_entity(self):
        """There is no company behind this fork, so nothing may claim one."""
        suffixes = {
            ".md",
            ".txt",
            ".py",
            ".ts",
            ".tsx",
            ".toml",
            ".yaml",
            ".yml",
            ".json",
        }
        offenders = []
        for rel in tracked_files():
            path = REPO / rel
            if (
                path.suffix not in suffixes
                or not path.is_file()
                or path.stat().st_size > 2_000_000
            ):
                continue
            if FAKE_ENTITY in path.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(rel)
        self.assertFalse(
            offenders,
            "these files assert a corporate licensor that does not exist; the copyright "
            f"and the marks are held personally: {offenders}",
        )

    def test_docs_site_presents_this_fork(self):
        config = (REPO / "docs" / "docusaurus.config.ts").read_text(encoding="utf-8")
        self.assertIn('title: "Gannet"', config, "the documentation site title")
        self.assertIn('alt: "Gannet"', config, "the navbar logo alternative text")
        self.assertNotIn(
            "blakeblackshear", config, "docs config must not link upstream's repo"
        )
        for rel in ("README.md", "README_CN.md", "notebooks/README.md"):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertNotIn(
                "nuipona", text, f"{rel} points at an organization that is not this one"
            )
        self.assertNotIn(
            "docs/static/img/branding/frigate.png",
            (REPO / "README.md").read_text(encoding="utf-8"),
            "the README must display this fork's logo, not Frigate's wordmark",
        )
        if "docs.frigate.video" in config:
            self.assertIn(
                "FIXME(owner)",
                config,
                "serving our terms from upstream's domain is a defect worth flagging in place",
            )

    def test_package_metadata_is_not_upstream_identity(self):
        manifests = [
            rel for rel in tracked_files() if rel.startswith("winget-manifest/")
        ]
        self.assertTrue(manifests, "the winget manifest disappeared")
        (rel,) = manifests
        stem = rel.rsplit("/", 1)[-1][: -len(".yaml")]
        text = (REPO / rel).read_text(encoding="utf-8")
        identifier = re.search(r"(?m)^PackageIdentifier:\s*(\S+)$", text)
        self.assertIsNotNone(identifier, "PackageIdentifier must be a top-level key")
        self.assertEqual(
            identifier.group(1),
            stem,
            "winget requires the manifest filename to match PackageIdentifier",
        )
        publisher = identifier.group(1).split(".", 1)[0]
        self.assertIn(
            f"Publisher: {publisher}",
            text,
            "the manifest must name the person who publishes it, not Frigate, Inc.",
        )
        self.assertNotIn("InstallLocation: C:\\Program Files\\Frigate", text)
        self.assertNotEqual(
            "License: MIT",
            re.search(r"(?m)^License:.*$", text).group(0).strip(),
            "this distribution is not MIT; the manifest used to say otherwise",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
