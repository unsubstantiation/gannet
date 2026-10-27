# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Tests for the portable bundle builder.

The builder is standard library only and never runs the application, so these
tests exercise it on any host: the launcher contract, the layout assertions, and
the planning mode that CI gates on. Nothing here downloads or builds anything.
"""

import csv
import importlib.util
import json
import re
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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

    def test_slim_switch_is_forwarded(self):
        text = (REPO_ROOT / "scripts" / "build_portable.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("[switch]$Slim", text)
        self.assertIn('if ($Slim) { $arguments += "--slim" }', text)
        self.assertIn('Join-Path $RepoRoot "dist\\slim"', text)


class TestSlimPruning(unittest.TestCase):
    """SDK cleanup never touches runtime data or unowned files."""

    @classmethod
    def setUpClass(cls):
        cls.builder = _load_builder()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.site = Path(self.temporary.name) / "site-packages"
        self.site.mkdir()

    def put(self, relative, data=b"test data"):
        path = self.site / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def record(self, distribution, paths):
        record = self.site / f"{distribution}.dist-info" / "RECORD"
        record.parent.mkdir(parents=True, exist_ok=True)
        with record.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerows([[path, "sha256=unchanged", "123"] for path in paths])
            writer.writerow([record.relative_to(self.site).as_posix(), "", ""])
        return record

    def rows(self, record):
        with record.open(encoding="utf-8", newline="") as handle:
            return list(csv.reader(handle))

    def test_prunes_only_owned_sdk_headers_and_preserves_other_rows(self):
        removed = {
            "tensorflow/include/core,defs.h": b"aaa",
            "tensorflow/include/deep/layer.hpp": b"12345",
            "tensorflow/include/generated.inc": b"abcd",
            "openvino/include/openvino/op.hpp": b"xyz",
            "openvino/include/core.H": b"12",
        }
        retained = {
            "tensorflow/include/LICENSE": b"license text",
            "tensorflow/include/NOTICE.hpp": b"notice text",
            "tensorflow/include/copyright/attribution.h": b"copyright text",
            "tensorflow/include/embedded.h": b"// Copy" + b"right marker\nint x;",
            "tensorflow/include/symbol.h": b"// \xc2\xa9 marker\n",
            "tensorflow/include/unknown.inc": b"\xff\xfe\x00\x01",
            "tensorflow/include/descriptors.bin": b"descriptor",
            "tensorflow/runtime.h": b"outside SDK",
            "tensorflow/runtime.dll": b"native library",
            "openvino/include/COPYING.h": b"copying text",
            "openvino/include/embedded.hpp": b"// SPDX-License-Identifier: Apache-2.0\n",
            "openvino/include/symbol.h": b"// (C) marker\n",
            "openvino/include/notice.h": b"// Legal notice\n",
            "openvino/include/model.bin": b"weights",
            "openvino/include/config.hpp.in": b"not an SDK header",
            "openvino/runtime/openvino.dll": b"native library",
            "numpy/testing/__init__.py": b"numpy testing",
            "scipy/special/tests/test_hyp2f1.py": b"scipy tests",
        }
        for relative, data in (removed | retained).items():
            self.put(relative, data)

        tensorflow_paths = [
            p for p in removed | retained if p.startswith("tensorflow/")
        ]
        # RECORD is normally POSIX-style even on Windows; also accept a record
        # whose owner used Windows separators without changing retained rows.
        tensorflow_paths[tensorflow_paths.index("tensorflow/include/generated.inc")] = (
            r"tensorflow\include\generated.inc"
        )
        tf_record = self.record("tensorflow_cpu-2.21.0", tensorflow_paths)
        ov_record = self.record(
            "openvino-2026.4.1",
            [p for p in removed | retained if p.startswith("openvino/")],
        )
        shared_record = self.record("other-1.0", ["tensorflow/include/core,defs.h"])
        old_tf = self.rows(tf_record)
        old_ov = self.rows(ov_record)

        result = self.builder.prune_sdk_headers(self.site)

        self.assertTrue(result["enabled"])
        self.assertEqual(result["files_removed"], len(removed))
        self.assertEqual(result["bytes_removed"], sum(map(len, removed.values())))
        self.assertEqual(
            result["removed_paths_relative_to_site_packages"], sorted(removed)
        )
        self.assertEqual(result["components"]["tensorflow"]["files_removed"], 3)
        self.assertEqual(result["components"]["openvino"]["files_removed"], 2)
        self.assertEqual(
            result["components"]["tensorflow"][
                "headers_retained_for_notices_or_unknown_content"
            ],
            5,
        )
        self.assertEqual(
            result["components"]["openvino"][
                "headers_retained_for_notices_or_unknown_content"
            ],
            4,
        )
        for relative in removed:
            self.assertFalse((self.site / relative).exists(), relative)
        for relative, data in retained.items():
            self.assertEqual((self.site / relative).read_bytes(), data, relative)

        def without_removed(rows):
            return [row for row in rows if row[0].replace("\\", "/") not in removed]

        self.assertEqual(self.rows(tf_record), without_removed(old_tf))
        self.assertEqual(self.rows(ov_record), without_removed(old_ov))
        self.assertEqual(len(self.rows(shared_record)), 1)
        self.assertFalse(list(self.site.rglob(".RECORD-slim-*")))

        # The helper is idempotent; a second pass does not rewrite the records.
        before = {r: r.read_bytes() for r in (tf_record, ov_record, shared_record)}
        second = self.builder.prune_sdk_headers(self.site)
        self.assertEqual(second["files_removed"], 0)
        self.assertEqual(second["bytes_removed"], 0)
        self.assertEqual(before, {r: r.read_bytes() for r in before})

    def test_missing_ownership_aborts_before_any_changes(self):
        first = self.put("tensorflow/include/owned.h")
        second = self.put("tensorflow/include/unowned.h")
        record = self.record("tensorflow_cpu-2.21.0", ["tensorflow/include/owned.h"])
        before = record.read_bytes()
        with self.assertRaisesRegex(self.builder.BuildError, "no owning wheel RECORD"):
            self.builder.prune_sdk_headers(self.site)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assertEqual(record.read_bytes(), before)
        self.assertFalse(list(self.site.rglob(".RECORD-slim-*")))

    def test_malformed_record_aborts_before_any_changes(self):
        header = self.put("tensorflow/include/owned.h")
        record = self.record("tensorflow_cpu-2.21.0", ["tensorflow/include/owned.h"])
        bad = self.put("other-1.0.dist-info/RECORD", b"not,a,valid,row\n")
        before = record.read_bytes(), bad.read_bytes()
        with self.assertRaisesRegex(self.builder.BuildError, "malformed wheel RECORD"):
            self.builder.prune_sdk_headers(self.site)
        self.assertTrue(header.exists())
        self.assertEqual((record.read_bytes(), bad.read_bytes()), before)

    def test_signed_record_aborts_without_invalidating_the_signature(self):
        header = self.put("tensorflow/include/owned.h")
        record = self.record("tensorflow_cpu-2.21.0", ["tensorflow/include/owned.h"])
        signature = self.put("tensorflow_cpu-2.21.0.dist-info/RECORD.jws", b"signature")
        before = record.read_bytes(), signature.read_bytes()
        with self.assertRaisesRegex(self.builder.BuildError, "signed wheel RECORD"):
            self.builder.prune_sdk_headers(self.site)
        self.assertTrue(header.is_file())
        self.assertEqual((record.read_bytes(), signature.read_bytes()), before)

    def test_record_self_digest_is_cleared_after_rewrite(self):
        self.put("tensorflow/include/owned.h")
        record = self.record("tensorflow_cpu-2.21.0", ["tensorflow/include/owned.h"])
        with record.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows(
                [
                    ["tensorflow/include/owned.h", "sha256=x", "4"],
                    [record.relative_to(self.site).as_posix(), "sha256=stale", "100"],
                ]
            )
        self.builder.prune_sdk_headers(self.site)
        self.assertEqual(
            self.rows(record), [[record.relative_to(self.site).as_posix(), "", ""]]
        )

    def test_symlinked_sdk_files_are_rejected(self):
        header = self.put("tensorflow/include/owned.h")
        outside = self.put("outside.h", b"outside")
        link = header.parent / "linked.h"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"creating symlinks is unavailable: {exc}")
        record = self.record("tensorflow_cpu-2.21.0", ["tensorflow/include/owned.h"])
        before = record.read_bytes()
        with self.assertRaisesRegex(self.builder.BuildError, "symlinked SDK"):
            self.builder.prune_sdk_headers(self.site)
        self.assertTrue(header.exists())
        self.assertEqual(outside.read_bytes(), b"outside")
        self.assertEqual(record.read_bytes(), before)

    def test_symlinked_package_directory_is_rejected(self):
        outside = Path(self.temporary.name) / "outside-package"
        (outside / "include").mkdir(parents=True)
        header = outside / "include" / "external.h"
        header.write_bytes(b"outside")
        link = self.site / "tensorflow"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"creating symlinks is unavailable: {exc}")
        with self.assertRaisesRegex(self.builder.BuildError, "symlinked SDK"):
            self.builder.prune_sdk_headers(self.site)
        self.assertEqual(header.read_bytes(), b"outside")

    def test_windows_reparse_points_are_treated_as_links(self):
        fake_stat = SimpleNamespace(
            st_mode=stat.S_IFDIR,
            st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
        )
        with mock.patch.object(Path, "lstat", return_value=fake_stat):
            self.assertTrue(self.builder.is_link_or_reparse_point(self.site))

    def test_unreadable_header_fails_closed(self):
        header = self.put("tensorflow/include/owned.h")
        record = self.record("tensorflow_cpu-2.21.0", ["tensorflow/include/owned.h"])
        before = record.read_bytes()
        with mock.patch.object(
            Path, "read_bytes", side_effect=PermissionError("denied")
        ):
            with self.assertRaisesRegex(
                self.builder.BuildError, "cannot inspect SDK header"
            ):
                self.builder.prune_sdk_headers(self.site)
        self.assertTrue(header.is_file())
        self.assertEqual(record.read_bytes(), before)

    def test_unreadable_sdk_walk_fails_closed(self):
        self.put("tensorflow/include/owned.h")

        def fail_walk(path, onerror, followlinks):
            onerror(PermissionError("inaccessible"))
            return []

        with mock.patch.object(self.builder.os, "walk", side_effect=fail_walk):
            with self.assertRaisesRegex(self.builder.BuildError, "cannot inspect SDK"):
                self.builder.prune_sdk_headers(self.site)
        self.assertTrue((self.site / "tensorflow/include/owned.h").is_file())

    def test_no_optional_sdks_is_a_noop(self):
        self.put("numpy/testing/__init__.py")
        result = self.builder.prune_sdk_headers(self.site)
        self.assertEqual(result["files_removed"], 0)
        self.assertEqual(result["removed_paths_relative_to_site_packages"], [])
        self.assertTrue((self.site / "numpy/testing/__init__.py").exists())


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


class TestSlimBuild(unittest.TestCase):
    """Exercise both modes through the builder without downloads or Windows."""

    def setUp(self):
        self.builder = _load_builder()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "output"
        self.archive = self.root / "python.zip"
        self.archive.write_bytes(b"pinned interpreter archive")

    def _build(self, slim, keep_staging=False):
        def stage_python(python_dir, _archive):
            site = python_dir / "Lib" / "site-packages"
            site.mkdir(parents=True)
            (python_dir / "python.exe").write_bytes(b"MZ interpreter")
            return str(site)

        def install(site, _requirements):
            files = {
                "tensorflow/include/core.h": b"header",
                "tensorflow/include/LICENSE": b"license",
                "tensorflow/include/runtime.bin": b"runtime data",
            }
            for relative, content in files.items():
                path = site / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            metadata = site / "tensorflow_cpu-2.21.0.dist-info"
            metadata.mkdir()
            (metadata / "METADATA").write_text("Version: 2.21.0\n", encoding="utf-8")
            with (metadata / "RECORD").open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerows(
                    [
                        [path, "sha256=test", str(len(data))]
                        for path, data in files.items()
                    ]
                )
                writer.writerow([f"{metadata.name}/RECORD", "", ""])

        def launcher(python_dir, _site, _staging):
            path = python_dir / "GannetNVR.exe"
            path.write_bytes((python_dir / "python.exe").read_bytes())
            return path

        args = [
            "--version",
            "0.19.0",
            "--output-dir",
            str(self.output),
            "--skip-web",
            "--skip-artifacts",
        ]
        if slim:
            args.append("--slim")
        if keep_staging:
            args.append("--keep-staging")
        with mock.patch.multiple(
            self.builder,
            stage_app=mock.DEFAULT,
            stage_web=mock.DEFAULT,
            fetch_python_embed=mock.DEFAULT,
            stage_python=mock.DEFAULT,
            install_wheels=mock.DEFAULT,
            install_project_metadata=mock.DEFAULT,
            stage_exe_launcher=mock.DEFAULT,
            verify_layout=mock.DEFAULT,
        ) as patched:
            patched["fetch_python_embed"].return_value = self.archive
            patched["stage_python"].side_effect = stage_python
            patched["install_wheels"].side_effect = install
            patched["stage_exe_launcher"].side_effect = launcher
            self.assertEqual(self.builder.main(args), 0)

    def test_slim_and_full_artifacts_coexist_and_describe_their_contents(self):
        self._build(slim=False, keep_staging=True)
        full_name = "GannetNVR-0.19.0-win64"
        full_staging = self.output / ".staging" / full_name
        full_artifacts = [
            self.output / f"{full_name}.zip",
            self.output / f"{full_name}.zip.sha256",
            self.output / "SHA256SUMS.txt",
            self.output / "RELEASE-NOTES.md",
            self.output / self.builder.WINGET_TEMPLATE.name,
        ]
        before = {path: path.read_bytes() for path in full_artifacts}

        # Even an explicitly shared output directory must not clobber full
        # artifacts or a retained full staging tree.
        self._build(slim=True)
        self.assertEqual(before, {path: path.read_bytes() for path in full_artifacts})
        self.assertTrue(full_staging.is_dir())
        slim_name = f"{full_name}-slim"
        for name in (
            f"{slim_name}.zip",
            f"{slim_name}.zip.sha256",
            "SHA256SUMS-slim.txt",
            "RELEASE-NOTES-slim.md",
        ):
            self.assertTrue((self.output / name).is_file(), name)

        prefix = "python/Lib/site-packages/tensorflow/include/"
        with zipfile.ZipFile(self.output / f"{full_name}.zip") as archive:
            self.assertIn(f"{full_name}/{prefix}core.h", archive.namelist())
            info = json.loads(archive.read(f"{full_name}/BUILD-INFO.json"))
            self.assertEqual(info["bundle_mode"], "full")
            self.assertFalse(info["sdk_pruning"]["enabled"])
        with zipfile.ZipFile(self.output / f"{slim_name}.zip") as archive:
            self.assertNotIn(f"{slim_name}/{prefix}core.h", archive.namelist())
            self.assertIn(f"{slim_name}/{prefix}LICENSE", archive.namelist())
            self.assertIn(f"{slim_name}/{prefix}runtime.bin", archive.namelist())
            info = json.loads(archive.read(f"{slim_name}/BUILD-INFO.json"))
            offer = archive.read(f"{slim_name}/SOURCE-OFFER.txt").decode("utf-8")
            record = archive.read(
                f"{slim_name}/python/Lib/site-packages/"
                "tensorflow_cpu-2.21.0.dist-info/RECORD"
            ).decode("utf-8")
        self.assertEqual(info["bundle"], slim_name)
        self.assertEqual(info["bundle_mode"], "slim")
        self.assertEqual(info["sdk_pruning"]["files_removed"], 1)
        self.assertEqual(info["sdk_pruning"]["bytes_removed"], len(b"header"))
        self.assertEqual(
            info["sdk_pruning"]["removed_paths_relative_to_site_packages"],
            ["tensorflow/include/core.h"],
        )
        self.assertIn("omits selected TensorFlow and OpenVINO", offer)
        self.assertNotIn("each wheel in python/Lib/site-packages is unmodified", offer)
        self.assertNotIn("tensorflow/include/core.h", record)
        self.assertIn("tensorflow/include/LICENSE", record)
        self.assertIn(
            "Native custom-op or extension development requires the full bundle",
            (self.output / "RELEASE-NOTES-slim.md").read_text(encoding="utf-8"),
        )

    def test_slim_plan_defaults_to_a_separate_directory_without_writes(self):
        dist = self.root / "dist"
        with mock.patch.object(self.builder, "DIST", dist):
            with self.assertLogs("build_portable", level="INFO") as logs:
                self.assertEqual(
                    self.builder.main(["--version", "0.19.0", "--slim", "--plan-only"]),
                    0,
                )
        self.assertIn(
            str(dist / "slim" / ".staging" / "GannetNVR-0.19.0-win64-slim"),
            "\n".join(logs.output),
        )
        self.assertFalse(dist.exists())

    def test_slim_cannot_claim_a_build_without_wheels(self):
        with self.assertRaisesRegex(self.builder.BuildError, "cannot be combined"):
            self.builder.main(
                ["--slim", "--skip-wheels", "--output-dir", str(self.output)]
            )
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
