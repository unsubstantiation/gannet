# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Tests for the native Windows bootstrap script.

The script is standard library only so these can run anywhere; they exercise
the digest bookkeeping, archive extraction, layout resolution and launcher
generation without touching the network.
"""

import ast
import base64
import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location(
        "bootstrap_windows", REPO_ROOT / "bootstrap_windows.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bootstrap = _load_bootstrap()


class TestBaseLayout(unittest.TestCase):
    def test_defaults_to_the_local_app_data_directory(self):
        with tempfile.TemporaryDirectory() as appdata:
            with patch.dict(
                os.environ,
                {
                    "LOCALAPPDATA": appdata,
                    "FRIGATE_BASE_DIR": "",
                    "FRIGATE_CONFIG_DIR": "",
                    "FRIGATE_MEDIA_DIR": "",
                    "FRIGATE_CACHE_DIR": "",
                    "FRIGATE_TMP_DIR": "",
                },
            ):
                layout = bootstrap.BaseLayout()

        self.assertEqual(layout.base_dir, Path(appdata) / "Gannet")
        self.assertEqual(layout.config_dir, layout.base_dir / "config")
        self.assertEqual(layout.tmp_dir, layout.base_dir / "tmp")
        self.assertEqual(
            layout.restart_marker(), layout.base_dir / "tmp" / "restart.requested"
        )

    def test_service_defaults_to_program_data(self):
        with patch.dict(
            os.environ,
            {
                "ProgramData": r"C:\ProgramData",
                "FRIGATE_BASE_DIR": "",
                "FRIGATE_CONFIG_DIR": "",
                "FRIGATE_MEDIA_DIR": "",
                "FRIGATE_CACHE_DIR": "",
                "FRIGATE_TMP_DIR": "",
            },
        ):
            layout = bootstrap.BaseLayout(service_mode=True)

        self.assertEqual(layout.base_dir, Path(r"C:\ProgramData") / "Gannet")

    def test_base_dir_moves_every_directory(self):
        with tempfile.TemporaryDirectory() as base:
            with patch.dict(
                os.environ,
                {"FRIGATE_BASE_DIR": base, "LOCALAPPDATA": "C:\\unused"},
            ):
                layout = bootstrap.BaseLayout()

        self.assertEqual(layout.base_dir, Path(base))
        self.assertEqual(layout.config_dir, Path(base) / "config")

    def test_individual_directories_can_be_overridden(self):
        with (
            tempfile.TemporaryDirectory() as base,
            tempfile.TemporaryDirectory() as config,
        ):
            with patch.dict(
                os.environ,
                {"FRIGATE_BASE_DIR": base, "FRIGATE_CONFIG_DIR": config},
            ):
                layout = bootstrap.BaseLayout()

        self.assertEqual(layout.config_dir, Path(config))
        self.assertEqual(layout.media_dir, Path(base) / "media")

    def test_legacy_env_alias_still_selects_the_base_dir(self):
        with patch.dict(os.environ, {"FRIGATE_BASE_DIR": r"D:\OldData"}):
            layout = bootstrap.BaseLayout()
        self.assertEqual(layout.base_dir, Path(r"D:\OldData"))

    def test_preferred_env_name_wins_over_the_legacy_alias(self):
        with patch.dict(
            os.environ,
            {"GANNET_BASE_DIR": r"D:\NewData", "FRIGATE_BASE_DIR": r"D:\OldData"},
        ):
            layout = bootstrap.BaseLayout()
        self.assertEqual(layout.base_dir, Path(r"D:\NewData"))


class TestDigests(unittest.TestCase):
    def _artifact(self, expected: str = ""):
        return bootstrap.PinnedArtifact(
            name="test",
            version="1.0",
            url="https://example.com/test.zip",
            members=("test.exe",),
            expected_sha256=expected,
        )

    def _archive(self, directory: Path, content: bytes = b"payload") -> Path:
        path = directory / "test-1.0.zip"

        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("test.exe", content)

        return path

    def test_first_download_records_its_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(Path(tmp))
            store = Path(tmp) / "digests.json"

            digest = bootstrap.verify_or_record_digest(archive, self._artifact(), store)

            self.assertEqual(json.loads(store.read_text())["test"], digest)

    def test_second_download_must_match_the_recorded_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(Path(tmp))
            store = Path(tmp) / "digests.json"
            digest = bootstrap.verify_or_record_digest(archive, self._artifact(), store)

            # same content verifies, changed content is rejected
            self.assertEqual(
                bootstrap.verify_or_record_digest(archive, self._artifact(), store),
                digest,
            )

            archive.write_bytes(b"tampered")

            with self.assertRaises(bootstrap.DigestMismatchError):
                bootstrap.verify_or_record_digest(archive, self._artifact(), store)

    def test_pinned_digest_is_enforced_from_the_first_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(Path(tmp))
            store = Path(tmp) / "digests.json"

            with self.assertRaises(bootstrap.DigestMismatchError):
                bootstrap.verify_or_record_digest(
                    archive, self._artifact("0" * 64), store
                )

            digest = bootstrap.sha256_file(archive)

            self.assertEqual(
                bootstrap.verify_or_record_digest(
                    archive, self._artifact(digest), store
                ),
                digest,
            )
            # a pinned digest is not recorded to the store
            self.assertFalse(store.exists())

    def test_a_corrupt_digest_store_behaves_like_no_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = self._archive(Path(tmp))
            store = Path(tmp) / "digests.json"
            store.write_text("{not json")

            digest = bootstrap.verify_or_record_digest(archive, self._artifact(), store)

            self.assertEqual(json.loads(store.read_text())["test"], digest)


class TestExtraction(unittest.TestCase):
    def test_only_the_named_members_are_extracted_flat(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "build.zip"

            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("nested/deep/ffmpeg.exe", b"ffmpeg")
                bundle.writestr("nested/deep/ffprobe.exe", b"ffprobe")
                bundle.writestr("nested/deep/unrelated.txt", b"nope")

            dest = Path(tmp) / "bin"
            extracted = bootstrap.extract_members(
                archive,
                ("nested/deep/ffmpeg.exe", "nested/deep/ffprobe.exe"),
                dest,
            )

            self.assertEqual(
                sorted(path.name for path in extracted),
                ["ffmpeg.exe", "ffprobe.exe"],
            )
            self.assertEqual((dest / "ffmpeg.exe").read_bytes(), b"ffmpeg")
            self.assertFalse((dest / "unrelated.txt").exists())

    def test_a_missing_member_is_an_error_naming_the_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "build.zip"

            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("somethingelse.exe", b"x")

            with self.assertRaises(bootstrap.BootstrapError) as raised:
                bootstrap.extract_members(archive, ("bin/ffmpeg.exe",), Path(tmp) / "b")

            self.assertIn("bin/ffmpeg.exe", str(raised.exception))


class TestLauncher(unittest.TestCase):
    def test_launcher_restarts_only_when_the_marker_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / ".venv"
            script = bootstrap.build_launcher_script(venv, bootstrap.BaseLayout())

        self.assertIn("while ($true)", script)
        self.assertIn("restart.requested", script)
        self.assertIn(str(bootstrap.python_executable_in(venv).resolve()), script)
        self.assertIn("-m gannet", script)
        self.assertIn("$env:GANNET_BASE_DIR", script)
        self.assertIn("$env:GANNET_CONFIG_DIR", script)
        # UTF-8 mode so non-ASCII camera names survive the console and files
        self.assertIn('$env:PYTHONUTF8 = "1"', script)
        # the marker is consumed so a later manual stop is not mistaken
        # for another restart request
        self.assertIn("Remove-Item $marker", script)

    def test_launcher_uses_the_given_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / "venv3"
            script = bootstrap.build_launcher_script(venv, bootstrap.BaseLayout())

        # the launcher resolves the interpreter it embeds, and resolving on
        # Windows expands the 8.3 form of the temporary directory it came from
        self.assertIn(str(venv.resolve()), script)


class TestAcceleratorInstall(unittest.TestCase):
    def test_cpu_profile_replaces_any_existing_gpu_runtime(self):
        calls = []
        with patch.object(
            bootstrap, "run", side_effect=lambda command: calls.append(command)
        ):
            bootstrap.install_requirements(Path(r"C:\venv\python.exe"), "cpu")

        self.assertEqual(calls[-1][-1], bootstrap.ONNXRUNTIME_CPU_PACKAGE)
        self.assertTrue(any("onnxruntime-directml" in call for call in calls))

    def test_cuda_profile_replaces_runtime_and_installs_cuda_extras(self):
        calls = []
        with patch.object(
            bootstrap, "run", side_effect=lambda command: calls.append(command)
        ):
            bootstrap.install_requirements(Path(r"C:\venv\python.exe"), "cuda")

        packages = [call[-1] for call in calls if "pip" in call and len(call) > 4]
        self.assertEqual(packages[-1], bootstrap.CUDA_PACKAGE)
        self.assertIn("onnxruntime-gpu", packages)
        self.assertIn("onnxruntime-directml", packages)
        self.assertIn("onnxruntime-windowsml", packages)

    def test_windows_ml_profile_uses_its_declared_compatible_runtime_extra(self):
        calls = []
        with patch.object(
            bootstrap, "run", side_effect=lambda command: calls.append(command)
        ):
            bootstrap.install_requirements(Path(r"C:\venv\python.exe"), "windows-ml")

        self.assertEqual(calls[-1][-1], bootstrap.WINDOWS_ML_PACKAGE)

    def test_unknown_profile_is_rejected_before_running_pip(self):
        with patch.object(bootstrap, "run") as run:
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.install_requirements(Path("python"), "bogus")

        run.assert_not_called()


class TestInstallArtifact(unittest.TestCase):
    def test_existing_binaries_short_circuit_the_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            layout = bootstrap.BaseLayout()
            config = Path(tmp) / "config"
            layout.config_dir = config
            (config / "ffmpeg").mkdir(parents=True)
            (config / "ffmpeg" / "ffmpeg.exe").write_bytes(b"existing")

            artifact = bootstrap.PinnedArtifact(
                name="ffmpeg",
                version="8.1.2",
                url="https://example.com/ffmpeg.zip",
                members=("build/ffmpeg.exe",),
                dest_subdir="ffmpeg",
            )

            def fail_download(url: str, dest: Path) -> None:
                raise AssertionError("a complete install must not download")

            with patch.object(bootstrap, "download", fail_download):
                installed = bootstrap.install_artifact(
                    artifact, layout, Path(tmp) / "downloads"
                )

            self.assertEqual(installed, [config / "ffmpeg" / "ffmpeg.exe"])

    def test_pinned_file_is_installed_atomically(self):
        payload = b"model"
        with tempfile.TemporaryDirectory() as tmp:
            layout = bootstrap.BaseLayout()
            layout.config_dir = Path(tmp) / "config"
            artifact = bootstrap.PinnedFile(
                name="model",
                version="1",
                url="https://example.com/model.tflite",
                filename="model.tflite",
                dest_subdir="model_cache",
                expected_sha256=hashlib.sha256(payload).hexdigest(),
            )

            def fake_download(_url: str, dest: Path) -> None:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(payload)

            with patch.object(bootstrap, "download", fake_download):
                installed = bootstrap.install_file(
                    artifact, layout, Path(tmp) / "downloads"
                )

            self.assertEqual(installed.read_bytes(), payload)
            self.assertFalse(installed.with_name("model.tflite.tmp").exists())


if __name__ == "__main__":
    unittest.main()


class TestServiceInstall(unittest.TestCase):
    """The SCM installer is driven with this environment's interpreter."""

    def test_the_environment_interpreter_is_passed_to_the_installer(self):
        python = Path("C:/Frigate/.venv/Scripts/python.exe")

        with patch.object(bootstrap.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0)
            bootstrap.install_service(python, bootstrap.BaseLayout())

        command = run.call_args.args[0]
        self.assertEqual(command[0], "powershell")
        self.assertIn("-Action", command)
        self.assertIn("Install", command)
        # without this the installer would guess, and could register a service
        # that runs an interpreter without Frigate or pywin32 in it
        self.assertIn(str(python), command)
        self.assertIn("-BaseDir", command)

    def test_a_refused_install_is_reported(self):
        """The installer refuses rather than registering a broken service."""
        with patch.object(bootstrap.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 1)

            with self.assertRaises(bootstrap.BootstrapError) as raised:
                bootstrap.install_service(
                    Path("C:/Frigate/.venv/Scripts/python.exe"), bootstrap.BaseLayout()
                )

        self.assertIn("not installed", str(raised.exception))

    def test_a_missing_installer_is_reported(self):
        with patch.object(bootstrap, "REPO_ROOT", Path("C:/nowhere")):
            with self.assertRaises(bootstrap.BootstrapError) as raised:
                bootstrap.install_service(Path("python.exe"), bootstrap.BaseLayout())

        self.assertIn("not found", str(raised.exception))


class TestFilterpyEscapePatch(unittest.TestCase):
    """The filterpy 1.4.5 source fix used by both install paths.

    CPython 3.12 turns the invalid escapes in filterpy's LaTeX docstrings into
    SyntaxWarnings. The portable bundle ships no bytecode, so the first launch
    compiles them in front of the user. These tests use small stand-ins for the
    two affected modules, including CRLF endings, raw strings and a real wheel
    RECORD, so no download is needed.
    """

    HELPERS = (
        b"# a comment with \\Sum that must not change\n"
        b"def outer_product_sum(A, B=None):\n"
        b'    """\n'
        b"    P = \\Sum {A[i] B[i].T} for i in 0..N\n"
        b"    sigma $\\sigma$, and a valid escape\\n is here\n"
        b'    """\n'
        b"    PATTERN = r'\\s+\\d'\n"
        b"    return A\n"
    )
    GH_FILTER = (
        b"def vrf():\r\n"
        b'    """\r\n'
        b"    VRF(\\hat{x}) = \\\\frac{VAR(\\hat{x})}{\\sigma^2_x}\r\n"
        b'    """\r\n'
        b"    return 1\r\n"
    )
    PATHS = ("filterpy/common/helpers.py", "filterpy/gh/gh_filter.py")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.site = Path(temporary.name) / "site-packages"
        self.originals = {
            self.PATHS[0]: self.HELPERS,
            self.PATHS[1]: self.GH_FILTER,
            "filterpy/__init__.py": b"# untouched\n",
        }
        for relative, data in self.originals.items():
            path = self.site / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        record = self.site / "filterpy-1.4.5.dist-info" / "RECORD"
        record.parent.mkdir(parents=True, exist_ok=True)
        with record.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            for relative, data in self.originals.items():
                writer.writerow([relative, self.digest(data), str(len(data))])
            writer.writerow(["filterpy-1.4.5.dist-info/METADATA", "sha256=kept", "12"])
            writer.writerow(["filterpy-1.4.5.dist-info/RECORD", "", ""])
        self.record = record

    @staticmethod
    def digest(data: bytes) -> str:
        encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode()
        return f"sha256={encoded.rstrip('=')}"

    @staticmethod
    def escape_warnings(data: bytes) -> list[str]:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            compile(data, "module.py", "exec")
        return [str(item.message) for item in caught]

    def rows(self):
        with self.record.open(encoding="utf-8", newline="") as handle:
            return list(csv.reader(handle))

    def test_rewrites_invalid_escapes_without_changing_string_values(self):
        self.assertIn(
            "invalid escape sequence", " ".join(self.escape_warnings(self.HELPERS))
        )

        fixed = bootstrap.fix_filterpy_escapes(self.site)

        self.assertEqual(fixed, list(self.PATHS))
        helpers = (self.site / self.PATHS[0]).read_bytes()
        gh_filter = (self.site / self.PATHS[1]).read_bytes()
        self.assertEqual(self.escape_warnings(helpers), [])
        self.assertEqual(self.escape_warnings(gh_filter), [])
        # The source now has doubled backslashes, but the docstring still says
        # exactly what it said before the patch.
        self.assertIn(b"P = \\\\Sum", helpers)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            before = ast.parse(self.HELPERS)
            after = ast.parse(helpers)
        self.assertEqual(
            ast.dump(before, include_attributes=False),
            ast.dump(after, include_attributes=False),
        )
        self.assertIn(r"P = \Sum", ast.get_docstring(after.body[0]))
        # Raw strings, comments and CRLF endings are untouched.
        self.assertIn(b"PATTERN = r'\\s+\\d'", helpers)
        self.assertIn(b"# a comment with \\Sum that must not change", helpers)
        self.assertEqual(gh_filter.count(b"\r\n"), self.GH_FILTER.count(b"\r\n"))
        self.assertNotIn(b"\r\r\n", gh_filter)

    def test_updates_the_owning_record_and_only_its_own_rows(self):
        bootstrap.fix_filterpy_escapes(self.site)

        rows = {row[0]: row for row in self.rows()}
        for relative in self.PATHS:
            data = (self.site / relative).read_bytes()
            self.assertEqual(rows[relative][1], self.digest(data))
            self.assertEqual(rows[relative][2], str(len(data)))
        self.assertEqual(rows["filterpy/__init__.py"][1], self.digest(b"# untouched\n"))
        self.assertEqual(rows["filterpy-1.4.5.dist-info/METADATA"][1], "sha256=kept")
        self.assertEqual(rows["filterpy-1.4.5.dist-info/RECORD"][1], "")

    def test_is_idempotent_and_a_no_op_on_clean_installs(self):
        bootstrap.fix_filterpy_escapes(self.site)
        contents = {
            relative: (self.site / relative).read_bytes() for relative in self.originals
        }
        record = self.record.read_bytes()

        self.assertEqual(bootstrap.fix_filterpy_escapes(self.site), [])
        for relative, data in contents.items():
            self.assertEqual((self.site / relative).read_bytes(), data)
        self.assertEqual(self.record.read_bytes(), record)

        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(bootstrap.fix_filterpy_escapes(Path(empty)), [])

    def test_refuses_to_patch_an_unrecorded_or_signed_install(self):
        self.record.unlink()
        with self.assertRaises(bootstrap.VendorPatchError):
            bootstrap.fix_filterpy_escapes(self.site)
        self.assertEqual((self.site / self.PATHS[0]).read_bytes(), self.HELPERS)

    def test_signed_record_is_not_invalidated(self):
        (self.record.parent / "RECORD.jws").write_text("signature", encoding="utf-8")
        with self.assertRaises(bootstrap.VendorPatchError):
            bootstrap.fix_filterpy_escapes(self.site)
        self.assertEqual((self.site / self.PATHS[0]).read_bytes(), self.HELPERS)

    def test_site_packages_follows_the_venv_interpreter(self):
        python = Path("C:/Gannet/.venv/Scripts/python.exe")
        self.assertEqual(
            bootstrap.site_packages_for(python),
            Path("C:/Gannet/.venv/Lib/site-packages"),
        )

    def test_install_requirements_applies_the_patch(self):
        with (
            patch.object(bootstrap, "run"),
            patch.object(
                bootstrap, "fix_filterpy_escapes", return_value=["filterpy/a.py"]
            ) as fix,
        ):
            bootstrap.install_requirements(
                Path("C:/Gannet/.venv/Scripts/python.exe"), "cpu"
            )
        fix.assert_called_once_with(Path("C:/Gannet/.venv/Lib/site-packages"))
