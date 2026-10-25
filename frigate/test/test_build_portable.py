# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Tests for the portable bundle builder.

The builder is standard library only and never runs the application, so these
tests exercise it on any host: the launcher contract, the layout assertions, and
the planning mode that CI gates on. Nothing here downloads or builds anything.
"""

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_portable", REPO_ROOT / "scripts" / "build_portable.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestLauncher(unittest.TestCase):
    """The launcher is generated text; these are the parts that must not drift."""

    @classmethod
    def setUpClass(cls):
        cls.builder = _load_builder()
        cls.launcher = cls.builder.launcher_script()

    def test_runs_the_bundled_interpreter_from_the_bundle(self):
        self.assertIn(r'Join-Path $Root "python\python.exe"', self.launcher)
        self.assertIn("& $Python -m frigate", self.launcher)

    def test_sets_the_working_directory_the_migration_router_needs(self):
        # peewee-migrate finds migrations/ relative to the working directory, and
        # starting anywhere else creates an empty database.
        self.assertIn("Push-Location $App", self.launcher)
        self.assertIn("Pop-Location", self.launcher)

    def test_restarts_only_when_frigate_wrote_the_marker(self):
        self.assertIn("restart.requested", self.launcher)
        self.assertIn("if (Test-Path $Marker)", self.launcher)

    def test_seeds_models_without_overwriting_existing_ones(self):
        self.assertIn('-Filter "*.tflite"', self.launcher)
        self.assertIn("if (-not (Test-Path $destination))", self.launcher)

    def test_never_writes_into_the_bundle(self):
        # Data belongs in %LOCALAPPDATA%\Frigate or -BaseDir; nothing may be
        # copied to $Root or set as the working directory for writes.
        self.assertNotIn("Copy-Item -Destination $Root", self.launcher)

    def test_cmd_shim_forwards_arguments_to_the_launcher(self):
        shim = self.builder.cmd_shim()
        self.assertIn(r"%~dp0run_gannet.ps1", shim)
        self.assertIn("%*", shim)
        self.assertIn("exit /b %ERRORLEVEL%", shim)


class TestDownloads(unittest.TestCase):
    def test_a_failed_download_names_its_url(self):
        # Every pinned input arrives through download(); its failure must
        # say which URL is wrong instead of leaving a urllib traceback.
        builder = _load_builder()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(builder.BuildError) as caught:
                builder.download(
                    "file:///definitely-missing-embed-amd64.zip",
                    Path(tmp) / "out.zip",
                )
        self.assertIn("definitely-missing-embed-amd64.zip", str(caught.exception))


class TestPowerShellWrapper(unittest.TestCase):
    def test_host_version_variable_cannot_shadow_the_parameter(self):
        # PowerShell variables are case-insensitive: a local $pythonVersion
        # IS the -PythonVersion parameter. Assigning the host's "3.12" to it
        # made the wrapper ask the builder for python-3.12-embed-amd64.zip.
        text = (REPO_ROOT / "scripts" / "build_portable.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIsNone(re.search(r"\$pythonVersion\s*=", text, re.IGNORECASE))


class TestLayoutAssertions(unittest.TestCase):
    def setUp(self):
        self.builder = _load_builder()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def _complete_tree(self) -> Path:
        required = [
            "python/python.exe",
            "python/Lib/site-packages",
            "app/frigate/__main__.py",
            "app/migrations",
            "app/web/dist/index.html",
            "app/labelmap.txt",
            "app/audio-labelmap.txt",
            "app/LICENSE",
            self.builder.LAUNCHER_NAME,
            self.builder.SHIM_NAME,
        ]
        for relative in required:
            path = self.root / relative
            if Path(relative).suffix:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x", encoding="utf-8")
            else:
                path.mkdir(parents=True, exist_ok=True)
        return self.root

    def test_accepts_a_complete_tree(self):
        staging = self._complete_tree()
        self.builder.verify_layout(staging, expect_wheels=False, expect_artifacts=False)

    def test_reports_every_missing_runtime_path(self):
        staging = self._complete_tree()
        (staging / "app" / "web" / "dist" / "index.html").unlink()
        (staging / "app" / "labelmap.txt").unlink()
        with self.assertRaises(self.builder.BuildError) as caught:
            self.builder.verify_layout(
                staging, expect_wheels=False, expect_artifacts=False
            )
        message = str(caught.exception)
        self.assertIn("app/web/dist/index.html", message)
        self.assertIn("app/labelmap.txt", message)

    def test_requires_the_version_metadata_when_wheels_are_expected(self):
        staging = self._complete_tree()
        site_packages = staging / "python" / "Lib" / "site-packages"
        (site_packages / "click-8.1.7.dist-info").mkdir()
        (site_packages / "aiofiles-24.1.0.dist-info").mkdir()
        with self.assertRaises(self.builder.BuildError) as caught:
            self.builder.verify_layout(
                staging, expect_wheels=True, expect_artifacts=False
            )
        self.assertIn("frigate-nvr metadata", str(caught.exception))

    def test_rejects_bytecode_from_the_build_host(self):
        staging = self._complete_tree()
        compiled = staging / "app" / "frigate" / "__pycache__"
        compiled.mkdir()
        (compiled / "app.cpython-311.pyc").write_bytes(b"\0")
        with self.assertRaises(self.builder.BuildError) as caught:
            self.builder.verify_layout(
                staging, expect_wheels=False, expect_artifacts=False
            )
        self.assertIn("bytecode", str(caught.exception))

    def test_artifacts_are_required_only_when_requested(self):
        staging = self._complete_tree()
        self.builder.verify_layout(staging, expect_wheels=False, expect_artifacts=False)
        with self.assertRaises(self.builder.BuildError):
            self.builder.verify_layout(
                staging, expect_wheels=False, expect_artifacts=True
            )


class TestManifestInputs(unittest.TestCase):
    def setUp(self):
        self.builder = _load_builder()

    def test_version_comes_from_pyproject(self):
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'version = "{self.builder.project_version()}"', text)

    def test_requirements_are_read_without_comments_or_blanks(self):
        pins = self.builder.requirement_pins(REPO_ROOT / "requirements.txt")
        self.assertTrue(pins)
        for pin in pins:
            self.assertNotIn("#", pin)
            self.assertEqual(pin, pin.strip())
            self.assertTrue(pin[0].isalnum(), pin)

    def test_requirement_name_handles_extras_and_separators(self):
        self.assertEqual(
            self.builder.requirement_name(
                "fastapi[standard-no-fastapi-cloud-cli] == 0.143.*"
            ),
            "fastapi",
        )
        self.assertEqual(
            self.builder.requirement_name("ruamel.yaml == 0.19.*"), "ruamel-yaml"
        )
        self.assertEqual(
            self.builder.requirement_name("titlecase == 2.4.*"), "titlecase"
        )

    def test_sdist_only_specs_agree_with_their_names(self):
        # SDIST_ONLY_REQUIREMENTS is bookkeeping about what the index
        # publishes. An entry without its own spec takes the version from
        # requirements.txt, so it must be pinned there; an entry with one (a
        # transitive constraint) must at least name the same distribution.
        pinned = {
            self.builder.requirement_name(pin)
            for pin in self.builder.requirement_pins(REPO_ROOT / "requirements.txt")
        }
        for name, spec in self.builder.SDIST_ONLY_REQUIREMENTS.items():
            if spec is None:
                self.assertIn(name, pinned)
            else:
                self.assertEqual(self.builder.requirement_name(spec), name)

    def test_release_notes_match_the_native_first_run(self):
        notes = self.builder.release_notes(
            "0.19.0", "GannetNVR-0.19.0-win64", "0" * 64, []
        )

        self.assertIn("https://localhost:8971", notes)
        self.assertNotIn("http://localhost:8971", notes)
        self.assertIn(r"tmp\logs\frigate\current", notes)

    def test_plan_only_exits_cleanly_without_touching_the_tree(self):
        self.assertEqual(self.builder.main(["--plan-only"]), 0)

    def test_committed_pin_matches_the_embedded_interpreter(self):
        # CI builds with --require-pinned, so a pin file that names another
        # interpreter (or carries no digest) would only be discovered by a
        # failed release build. Check the recorded digest here instead: it
        # must name the version the builder embeds and look like a SHA-256.
        pin = json.loads(
            (REPO_ROOT / "scripts" / "python_embed_pin.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(pin["version"], self.builder.PYTHON_EMBED_VERSION)
        self.assertIsNotNone(
            re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]),
            "python_embed_pin.json must carry the pinned SHA-256 digest",
        )


if __name__ == "__main__":
    unittest.main()
