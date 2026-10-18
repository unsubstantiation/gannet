# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Tests for the Windows requirements checker.

The checker is the gate that stops a ``requirements.txt`` change from
reaching CI when pip could never install it on Windows. These tests feed it
fabricated PyPI metadata so they run without the network, and cover the
pin-versus-pin check that was missing when a ``rich`` pin was raised past the
upper bound ``norfair`` declares.
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_ROOT / "testing-scripts" / "check_windows_requirements.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_windows_requirements", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    # the script declares a dataclass with postponed annotations, which the
    # dataclass machinery resolves through sys.modules
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def _wheel(filename: str, yanked: bool = False) -> dict:
    return {"packagetype": "bdist_wheel", "filename": filename, "yanked": yanked}


def _sdist(filename: str) -> dict:
    return {"packagetype": "sdist", "filename": filename, "yanked": False}


def _pin(name: str, version: str | None, raw: str | None = None, **fields):
    pin = checker.Pin(name, set(), version, raw or f"{name} == {version}.*")

    for key, value in fields.items():
        setattr(pin, key, value)

    return pin


class TestParseRequirements(unittest.TestCase):
    def test_pins_extras_and_comments_are_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements.txt"
            path.write_text(
                "# comment\n"
                "numpy == 1.26.*\n"
                "fastapi[standard-no-fastapi-cloud-cli] == 0.143.*\n"
                "pywin32 == 312 ; sys_platform == 'win32'\n"
                "titlecase\n"
                "--extra-index-url https://example.invalid/simple\n",
                encoding="utf-8",
            )

            pins = {pin.name: pin for pin in checker.parse_requirements(path)}

        self.assertEqual(pins["numpy"].version, "1.26")
        self.assertEqual(pins["numpy"].raw, "numpy == 1.26.*")
        self.assertEqual(pins["fastapi"].version, "0.143")
        self.assertEqual(pins["fastapi"].extras, {"standard-no-fastapi-cloud-cli"})
        self.assertEqual(pins["pywin32"].version, "312")
        self.assertIsNone(pins["titlecase"].version)
        self.assertNotIn("--extra-index-url", pins)


class TestMatchesPin(unittest.TestCase):
    def test_a_wildcard_pin_matches_by_version_component(self):
        """``1.26.*`` must not accept ``1.260.0`` just because it starts alike."""
        self.assertTrue(checker.matches_pin("1.26.4", "1.26"))
        self.assertTrue(checker.matches_pin("1.26", "1.26"))
        self.assertFalse(checker.matches_pin("1.260.0", "1.26"))
        self.assertFalse(checker.matches_pin("1.2.6", "1.26"))
        self.assertTrue(checker.matches_pin("anything", None))


class TestResolveRelease(unittest.TestCase):
    def test_the_newest_installable_stable_release_is_chosen(self):
        metadata = {
            "releases": {
                "14.3.4": [_wheel("rich-14.3.4-py3-none-any.whl")],
                "14.3.5rc1": [_wheel("rich-14.3.5rc1-py3-none-any.whl")],
                # nothing pip could install on Windows
                "14.3.6": [_sdist("rich-14.3.6.tar.gz")],
                "14.10.0": [_wheel("rich-14.10.0-py3-none-any.whl", yanked=True)],
                "15.0.0": [_wheel("rich-15.0.0-py3-none-any.whl")],
            }
        }

        self.assertEqual(checker.resolve_release("rich", "14", metadata), "14.3.4")
        self.assertEqual(checker.resolve_release("rich", "15.0", metadata), "15.0.0")
        self.assertIsNone(checker.resolve_release("rich", "16", metadata))

    def test_a_prerelease_is_only_chosen_when_nothing_else_matches(self):
        metadata = {"releases": {"2.0.0b1": [_wheel("x-2.0.0b1-py3-none-any.whl")]}}

        self.assertEqual(checker.resolve_release("x", "2", metadata), "2.0.0b1")

    def test_a_windows_wheel_counts_as_installable(self):
        metadata = {
            "releases": {
                "1.0.0": [
                    _wheel("x-1.0.0-cp312-cp312-manylinux_2_17_x86_64.whl"),
                    _wheel("x-1.0.0-cp312-cp312-win_amd64.whl"),
                ],
                "1.1.0": [_wheel("x-1.1.0-cp312-cp312-manylinux_2_17_x86_64.whl")],
            }
        }

        # 1.1.0 is newer but has no Windows build
        self.assertEqual(checker.resolve_release("x", None, metadata), "1.0.0")


@unittest.skipUnless(checker.HAVE_PACKAGING, "packaging is not installed")
class TestAppliesOnWindows(unittest.TestCase):
    def test_markers_are_evaluated_for_windows_cpython(self):
        Requirement = checker.Requirement

        self.assertTrue(checker.applies_on_windows(Requirement("rich<15"), set()))
        self.assertTrue(
            checker.applies_on_windows(
                Requirement("pywin32>=300; sys_platform == 'win32'"), set()
            )
        )
        self.assertFalse(
            checker.applies_on_windows(
                Requirement("uvloop>=0.17; sys_platform != 'win32'"), set()
            )
        )
        self.assertFalse(
            checker.applies_on_windows(
                Requirement("tomli>=2; python_version < '3.11'"), set()
            )
        )

    def test_extra_markers_follow_the_requested_extras(self):
        requirement = checker.Requirement("uvicorn>=0.12; extra == 'standard'")

        self.assertFalse(checker.applies_on_windows(requirement, set()))
        self.assertTrue(checker.applies_on_windows(requirement, {"standard"}))


@unittest.skipUnless(checker.HAVE_PACKAGING, "packaging is not installed")
class TestPinConflicts(unittest.TestCase):
    """The check that would have caught the ``rich == 15.0.*`` change."""

    def test_a_pin_outside_another_pins_declared_bound_is_reported(self):
        pins = [
            _pin(
                "norfair",
                "2.3",
                resolved="2.3.0",
                requires_dist=["rich<15.0.0,>=9.10.0", "numpy<2.0.0,>=1.23.0"],
            ),
            _pin("rich", "15.0", resolved="15.0.0"),
            _pin("numpy", "1.26", resolved="1.26.4"),
        ]

        conflicts = checker.pin_conflicts(pins)

        self.assertEqual(
            conflicts,
            [
                "norfair == 2.3.* (2.3.0) requires rich<15.0.0,>=9.10.0, "
                "but rich == 15.0.* selects 15.0.0"
            ],
        )

    def test_compatible_pins_are_quiet(self):
        pins = [
            _pin(
                "norfair",
                "2.3",
                resolved="2.3.0",
                requires_dist=["rich<15.0.0,>=9.10.0", "numpy<2.0.0,>=1.23.0"],
            ),
            _pin("rich", "14", resolved="14.3.4"),
            _pin("numpy", "1.26", resolved="1.26.4"),
        ]

        self.assertEqual(checker.pin_conflicts(pins), [])

    def test_dependencies_that_do_not_apply_on_windows_are_ignored(self):
        pins = [
            _pin(
                "server",
                "1",
                resolved="1.0.0",
                requires_dist=[
                    "uvloop>=0.17; sys_platform != 'win32'",
                    "fastspeed>=9; extra == 'fast'",
                ],
            ),
            _pin("uvloop", "0.14", resolved="0.14.0"),
            _pin("fastspeed", "1", resolved="1.0.0"),
        ]

        self.assertEqual(checker.pin_conflicts(pins), [])

    def test_dependencies_on_packages_that_are_not_pinned_are_ignored(self):
        pins = [
            _pin("server", "1", resolved="1.0.0", requires_dist=["unpinned<1"]),
        ]

        self.assertEqual(checker.pin_conflicts(pins), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
