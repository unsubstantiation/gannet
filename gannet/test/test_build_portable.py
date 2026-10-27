# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Tests for the portable bundle builder.

The builder is standard library only and never runs the application, so these
tests exercise it on any host: the launcher contract, the layout assertions, and
the planning mode that CI gates on. Nothing here downloads or builds anything.
"""

import importlib.util
import json
import re
import sys
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
        self.assertIn("& $Python -m gannet", self.launcher)

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

    def test_both_cmd_shims_have_clean_crlf(self):
        # A Windows build host writes these as bytes; a translated newline
        # would leave \r\r\n and a batch file with stray control characters.
        for shim in (self.builder.cmd_shim(), self.builder.exe_shim()):
            self.assertNotIn("\r\r\n", shim)
            self.assertTrue(shim.endswith("exit /b %ERRORLEVEL%\r\n"))


class TestExeLauncher(unittest.TestCase):
    """The .exe entry point is generated text; these are its runtime contracts."""

    @classmethod
    def setUpClass(cls):
        cls.builder = _load_builder()
        cls.module_source = cls.builder.exe_launcher_module()

    def _load_module(self, name: str):
        spec = importlib.util.spec_from_file_location(name, self._path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self._path = self.root / "gannet_launcher.py"
        self._path.write_text(self.module_source, encoding="utf-8")
        sys.path.insert(0, str(self.root))
        self.addCleanup(sys.path.remove, str(self.root))
        self.addCleanup(self.temporary.cleanup)
        self.module = self._load_module("gannet_launcher_under_test")

    def test_generated_module_is_valid_python(self):
        compile(self.module_source, "gannet_launcher.py", "exec")
        self.assertIn(
            "SPDX-License-Identifier: LicenseRef-GNCL-1.0", self.module_source
        )

    def test_launcher_is_a_no_op_for_the_bundled_interpreter(self):
        self.assertFalse(self.module.is_launcher_process())

    def test_launcher_recognises_its_own_and_a_winget_alias(self):
        import sys as real_sys
        from unittest import mock

        for name in ("GannetNVR.exe", "gannet.exe"):
            with mock.patch.object(
                real_sys, "executable", f"/tmp/bundle/python/{name}"
            ):
                self.assertTrue(self.module.is_launcher_process(), name)

    def test_python_interpreter_names_are_never_launchers(self):
        import sys as real_sys
        from unittest import mock

        for name in ("python.exe", "pythonw.exe", "pythonservice.exe"):
            with mock.patch.object(
                real_sys, "executable", f"/tmp/bundle/python/{name}"
            ):
                self.assertFalse(self.module.is_launcher_process(), name)

    def test_app_arguments_need_an_end_of_options_separator(self):
        # CPython parses its own options before the .pth hook runs, so the
        # shim inserts -- and the launcher forwards only what follows it.
        self.assertEqual(self.module.app_args(["GannetNVR.exe"]), [])
        self.assertEqual(self.module.app_args(["GannetNVR.exe", "--"]), [])
        self.assertEqual(
            self.module.app_args(["GannetNVR.exe", "--", "--validate-config"]),
            ["--validate-config"],
        )
        self.assertEqual(
            self.module.app_args(["GannetNVR.exe", "--validate-config"]),
            [],
            "an unseparated flag never reaches this module: CPython rejects it",
        )

    def test_module_carries_the_powershell_launcher_contract(self):
        for fragment in (
            '"-m", "gannet"',
            "cwd=str(app)",
            'RESTART_MARKER = "restart.requested"',
            'env.setdefault("PYTHONUTF8", "1")',
            'glob("*.tflite")',
            "os._exit",
            'getattr(sys, "orig_argv", sys.argv)',
        ):
            self.assertIn(fragment, self.module_source)

    def test_launcher_starts_gannet_from_app_with_the_right_environment(self):
        """Simulate the .pth hook: importing the module IS the launch."""
        import os
        import subprocess
        from unittest import mock

        root = self.root / "bundle"
        site_packages = root / "python" / "Lib" / "site-packages"
        site_packages.mkdir(parents=True)
        (root / "python" / "python.exe").write_bytes(b"MZ")
        (root / "app" / "model_cache").mkdir(parents=True)
        (root / "app" / "model_cache" / "cpu_model.tflite").write_bytes(b"weights")
        module = site_packages / "gannet_launcher.py"
        module.write_text(self.module_source, encoding="utf-8")

        data = self.root / "data"
        environ = {
            "LOCALAPPDATA": str(self.root / "appdata"),
            "FRIGATE_BASE_DIR": str(data),
        }
        popen = mock.MagicMock()
        popen.return_value.wait.return_value = 0
        exit_calls = []

        spec = importlib.util.spec_from_file_location("gannet_launcher_hooked", module)
        hooked = importlib.util.module_from_spec(spec)
        with (
            mock.patch.object(
                sys, "executable", str(root / "python" / "GannetNVR.exe")
            ),
            mock.patch.object(
                sys, "orig_argv", ["GannetNVR.exe", "--", "--validate-config"]
            ),
            mock.patch.dict(os.environ, environ, clear=True),
            mock.patch.object(subprocess, "Popen", popen),
            mock.patch.object(os, "_exit", side_effect=exit_calls.append),
        ):
            spec.loader.exec_module(hooked)

        args, kwargs = popen.call_args
        self.assertEqual(
            args[0],
            [str(root / "python" / "python.exe"), "-m", "gannet", "--validate-config"],
        )
        self.assertEqual(kwargs["cwd"], str(root / "app"))
        self.assertEqual(kwargs["env"]["PYTHONUTF8"], "1")
        self.assertEqual(
            (data / "config" / "model_cache" / "cpu_model.tflite").read_bytes(),
            b"weights",
        )
        self.assertEqual(exit_calls, [0])

    def test_site_processing_of_the_pth_file_triggers_the_launch(self):
        """The exact mechanism CPython uses, exercised on any host."""
        import os
        import site
        import subprocess
        from unittest import mock

        root = self.root / "bundle"
        site_packages = root / "python" / "Lib" / "site-packages"
        site_packages.mkdir(parents=True)
        (root / "python" / "python.exe").write_bytes(b"MZ")
        (root / "app").mkdir()
        (site_packages / self.builder.EXE_PTH_NAME).write_text(
            self.builder.exe_launcher_pth(), encoding="utf-8"
        )
        (site_packages / self.builder.EXE_MODULE_NAME).write_text(
            self.module_source, encoding="utf-8"
        )

        popen = mock.MagicMock()
        popen.return_value.wait.return_value = 0
        sys.modules.pop("gannet_launcher", None)
        sys.path.insert(0, str(site_packages))
        try:
            with (
                mock.patch.object(
                    sys, "executable", str(root / "python" / "GannetNVR.exe")
                ),
                mock.patch.object(sys, "orig_argv", ["GannetNVR.exe"]),
                mock.patch.dict(
                    os.environ,
                    {"FRIGATE_BASE_DIR": str(self.root / "data")},
                    clear=True,
                ),
                mock.patch.object(subprocess, "Popen", popen),
                mock.patch.object(os, "_exit"),
            ):
                site.addsitedir(str(site_packages))
        finally:
            sys.path.remove(str(site_packages))
            sys.modules.pop("gannet_launcher", None)

        self.assertTrue(popen.called)
        self.assertEqual(popen.call_args.args[0][-2:], ["-m", "gannet"])

    def test_pth_hook_imports_the_launcher_module(self):
        hook = self.builder.exe_launcher_pth()
        self.assertIn("import gannet_launcher", hook)
        self.assertTrue(hook.startswith("# SPDX-License-Identifier"))

    def test_pth_seed_is_the_same_for_both_executable_names(self):
        seed = self.builder.pth_contents().decode("utf-8")
        self.assertIn(self.builder.stdlib_zip_name(), seed)
        self.assertIn(r"Lib\site-packages", seed)
        self.assertIn(r"..\app", seed)
        self.assertIn("import site", seed)

    def test_exe_shim_runs_the_real_executable_after_a_separator(self):
        shim = self.builder.exe_shim()
        self.assertIn(r'"%~dp0python\GannetNVR.exe" -- %*', shim)
        self.assertIn("SPDX-License-Identifier: LicenseRef-GNCL-1.0", shim)


class TestExeStaging(unittest.TestCase):
    def setUp(self):
        self.builder = _load_builder()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.python_dir = self.root / "python"
        self.site_packages = self.python_dir / "Lib" / "site-packages"
        self.site_packages.mkdir(parents=True)
        self.interpreter = b"MZ pinned upstream python.exe\x00"
        (self.python_dir / "python.exe").write_bytes(self.interpreter)

    def test_staging_copies_the_interpreter_without_recompiling_it(self):
        exe = self.builder.stage_exe_launcher(
            self.python_dir, self.site_packages, self.root
        )
        self.assertEqual(exe.read_bytes(), self.interpreter)
        self.assertEqual(
            (self.python_dir / self.builder.EXE_PTH_CONFIG_NAME).read_bytes(),
            self.builder.pth_contents(),
        )
        self.assertTrue((self.root / self.builder.EXE_SHIM_NAME).is_file())
        self.assertTrue((self.site_packages / self.builder.EXE_PTH_NAME).is_file())
        self.assertTrue((self.site_packages / self.builder.EXE_MODULE_NAME).is_file())

    def test_staging_refuses_to_overwrite_a_wheel_file(self):
        (self.site_packages / self.builder.EXE_MODULE_NAME).write_text("wheel")
        with self.assertRaises(self.builder.BuildError) as caught:
            self.builder.stage_exe_launcher(
                self.python_dir, self.site_packages, self.root
            )
        self.assertIn("already ships", str(caught.exception))

    def test_staging_fails_without_the_pinned_interpreter(self):
        (self.python_dir / "python.exe").unlink()
        with self.assertRaises(self.builder.BuildError):
            self.builder.stage_exe_launcher(
                self.python_dir, self.site_packages, self.root
            )


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

    def _complete_tree(self, root: Path | None = None) -> Path:
        root = root or self.root
        required = [
            "python/python.exe",
            "python/Lib/site-packages",
            "app/gannet/__main__.py",
            "app/migrations",
            "app/web/dist/index.html",
            "app/labelmap.txt",
            "app/audio-labelmap.txt",
            "app/LICENSE",
            self.builder.LAUNCHER_NAME,
            self.builder.SHIM_NAME,
        ]
        for relative in required:
            path = root / relative
            if Path(relative).suffix:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x", encoding="utf-8")
            else:
                path.mkdir(parents=True, exist_ok=True)
        # The .exe tree is machine-generated, so build the fixture the same way
        # the builder does instead of hand-writing another version of its files.
        python_dir = root / "python"
        python_dir.mkdir(parents=True, exist_ok=True)
        (python_dir / "python.exe").write_bytes(b"MZ pinned interpreter")
        standard_pth = self.builder.stdlib_zip_name().removesuffix(".zip") + "._pth"
        (python_dir / standard_pth).write_bytes(self.builder.pth_contents())
        site_packages = python_dir / "Lib" / "site-packages"
        site_packages.mkdir(parents=True, exist_ok=True)
        self.builder.stage_exe_launcher(python_dir, site_packages, root)
        return root

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
        compiled = staging / "app" / "gannet" / "__pycache__"
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

    def test_rejects_a_launcher_exe_that_is_not_the_pinned_binary(self):
        staging = self._complete_tree()
        (staging / "python" / self.builder.EXE_NAME).write_bytes(b"different")
        with self.assertRaises(self.builder.BuildError) as caught:
            self.builder.verify_layout(
                staging, expect_wheels=False, expect_artifacts=False
            )
        self.assertIn("byte-identical", str(caught.exception))

    def test_rejects_a_missing_launcher_exe(self):
        staging = self._complete_tree()
        (staging / "python" / self.builder.EXE_NAME).unlink()
        with self.assertRaises(self.builder.BuildError) as caught:
            self.builder.verify_layout(
                staging, expect_wheels=False, expect_artifacts=False
            )
        self.assertIn(self.builder.EXE_NAME, str(caught.exception))

    def test_rejects_a_broken_path_seed_or_pth_hook(self):
        for relative, expected in (
            (f"python/{self.builder.EXE_PTH_CONFIG_NAME}", "sys.path seed"),
            (
                f"python/Lib/site-packages/{self.builder.EXE_PTH_NAME}",
                "does not import",
            ),
            (self.builder.EXE_SHIM_NAME, "after --"),
        ):
            with self.subTest(relative=relative):
                with tempfile.TemporaryDirectory() as tmp:
                    staging = self._complete_tree(Path(tmp))
                    (staging / relative).write_text("broken", encoding="utf-8")
                    with self.assertRaises(self.builder.BuildError) as caught:
                        self.builder.verify_layout(
                            staging, expect_wheels=False, expect_artifacts=False
                        )
                    self.assertIn(expected, str(caught.exception))


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

    def test_release_notes_put_the_exe_first(self):
        notes = self.builder.release_notes(
            "0.19.0", "GannetNVR-0.19.0-win64", "0" * 64, []
        )
        self.assertIn("Double-click `GannetNVR.cmd`", notes)
        self.assertIn(r"python\GannetNVR.exe", notes)
        # The shim supplies the separator itself; telling users to add a
        # second one makes argparse reject the flag as a positional.
        self.assertIn("GannetNVR.cmd --validate-config", notes)
        self.assertNotIn("GannetNVR.cmd -- --validate-config", notes)
        self.assertIn(r"python\GannetNVR.exe -- --validate-config", notes)
        self.assertIn("FRIGATE_BASE_DIR", notes)
        self.assertIn("run_gannet.ps1", notes)

    def test_winget_manifest_points_at_the_real_executable(self):
        template = (
            REPO_ROOT / "winget-manifest" / self.builder.WINGET_TEMPLATE.name
        ).read_text(encoding="utf-8")
        manifest = self.builder.winget_manifest(
            template,
            "0.19.0",
            "GannetNVR-0.19.0-win64",
            "0" * 64,
            "https://example.invalid/x.zip",
        )
        self.assertIn(r"GannetNVR-0.19.0-win64\python\GannetNVR.exe", manifest)
        self.assertNotIn("run_gannet.cmd", manifest)
        self.assertIn("PortableCommandAlias: GannetNVR", manifest)
        self.assertIn("ArchiveBinariesDependOnPath: true", manifest)
        self.assertIn("GannetNVR -- --validate-config", manifest)

    def test_build_info_records_the_launcher_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            interpreter = root / "python.exe"
            interpreter.write_bytes(b"MZ pinned upstream binary")
            (root / "python312.zip").write_bytes(b"stdlib")
            expected = self.builder.sha256_file(interpreter)
            notes = json.loads(
                self.builder.build_info(
                    "0.19.0",
                    root,
                    [],
                    root / "python312.zip",
                    interpreter,
                )
            )
        self.assertEqual(notes["launcher"]["path"], "python/GannetNVR.exe")
        self.assertEqual(notes["launcher"]["sha256"], expected)
        self.assertIn("byte-identical", notes["launcher"]["note"])

    def test_source_offer_explains_the_launcher_copy(self):
        offer = self.builder.source_offer([])
        self.assertIn("python/GannetNVR.exe", offer)
        self.assertIn("byte-for-byte copy", offer)

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
