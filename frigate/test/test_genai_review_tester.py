"""Tests for the cross platform key reader of the GenAI review tester.

The tester is a developer tool, but it is part of a Windows only repository,
so it has to import and run there: ``termios`` and ``tty`` do not exist on
Windows, and the console reports a key press differently.
"""

import ast
import contextlib
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_ROOT / "testing-scripts" / "genai_review_tester.py"


def _load_tester():
    spec = importlib.util.spec_from_file_location("genai_review_tester", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tester = _load_tester()


class _WindowsOs:
    """The os module as a Windows host reports it.

    Only the name differs, so the module under test takes its Windows branch
    while everything else keeps using the real module.
    """

    def __init__(self, real: object) -> None:
        self._real = real

    def __getattr__(self, name: str):
        return getattr(self._real, name)

    @property
    def name(self) -> str:
        return "nt"


class TestPosixOnlyImportsAreGuarded(unittest.TestCase):
    def test_termios_and_tty_are_not_imported_unconditionally(self):
        """Windows has neither module, so the import has to be guarded."""
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))

        for node in tree.body:
            if isinstance(node, ast.If):
                # a guarded import block
                continue

            for child in ast.walk(node):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        self.assertNotIn(alias.name, ("termios", "tty"))

    def test_the_module_imports_on_windows(self):
        """The module has to import on a host that has neither POSIX module."""
        with patch.dict(
            sys.modules,
            {
                "termios": None,
                "tty": None,
                "msvcrt": MagicMock(),
                "os": _WindowsOs(os),
            },
        ):
            module = _load_tester()

        self.assertTrue(module.IS_WINDOWS)
        self.assertTrue(hasattr(module, "_read_key_windows"))


class TestReadKeyWindows(unittest.TestCase):
    def _read(self, *chars: str) -> str:
        console = MagicMock()
        console.getwch.side_effect = list(chars)

        with patch.object(tester, "msvcrt", console, create=True):
            return tester._read_key_windows()

    def test_the_arrow_keys(self):
        self.assertEqual(self._read("\xe0", "H"), tester.KEY_UP)
        self.assertEqual(self._read("\xe0", "P"), tester.KEY_DOWN)

    def test_enter(self):
        self.assertEqual(self._read("\r"), tester.KEY_ENTER)
        self.assertEqual(self._read("\n"), tester.KEY_ENTER)

    def test_escape_and_control_c(self):
        self.assertEqual(self._read("\x1b"), tester.KEY_ESCAPE)
        self.assertEqual(self._read("\x03"), tester.KEY_CANCEL)

    def test_a_plain_character(self):
        self.assertEqual(self._read("j"), "j")

    def test_an_unknown_scan_code_is_ignored(self):
        self.assertEqual(self._read("\x00", "G"), "")


class TestReadKeyPosix(unittest.TestCase):
    def _read(self, *chars: str) -> str:
        remaining = iter(chars)
        stdin = MagicMock()
        stdin.read.side_effect = lambda size=1: next(remaining)

        with patch.object(tester.sys, "stdin", stdin):
            return tester._read_key_posix()

    def test_the_arrow_keys(self):
        self.assertEqual(self._read("\x1b", "[", "A"), tester.KEY_UP)
        self.assertEqual(self._read("\x1b", "[", "B"), tester.KEY_DOWN)

    def test_enter(self):
        self.assertEqual(self._read("\r"), tester.KEY_ENTER)
        self.assertEqual(self._read("\n"), tester.KEY_ENTER)

    def test_a_bare_escape_cancels(self):
        self.assertEqual(self._read("\x1b", "x"), tester.KEY_ESCAPE)

    def test_a_plain_character(self):
        self.assertEqual(self._read("k"), "k")


class TestAnsiConsole(unittest.TestCase):
    def test_non_windows_console_already_supports_ansi(self):
        with patch.object(tester, "IS_WINDOWS", False):
            with tester._ansi_console() as enabled:
                self.assertTrue(enabled)

    def test_windows_console_mode_is_restored(self):
        """Virtual terminal mode must not leak into the calling shell."""
        import ctypes
        from ctypes import wintypes

        original_mode = 0x0001
        handle = 123
        kernel32 = MagicMock()
        kernel32.GetStdHandle.return_value = handle

        def get_console_mode(_handle, mode_pointer):
            ctypes.cast(mode_pointer, ctypes.POINTER(wintypes.DWORD))[0] = original_mode
            return True

        kernel32.GetConsoleMode.side_effect = get_console_mode
        kernel32.SetConsoleMode.return_value = True

        with patch.object(tester, "IS_WINDOWS", True):
            with patch.object(ctypes, "WinDLL", return_value=kernel32, create=True):
                with tester._ansi_console() as enabled:
                    self.assertTrue(enabled)
                    kernel32.SetConsoleMode.assert_called_once_with(handle, 0x0005)

        self.assertEqual(
            kernel32.SetConsoleMode.call_args_list,
            [
                unittest.mock.call(handle, 0x0005),
                unittest.mock.call(handle, original_mode),
            ],
        )

    def test_windows_non_console_stream_uses_plain_menu(self):
        import ctypes

        kernel32 = MagicMock()
        kernel32.GetStdHandle.return_value = 123
        kernel32.GetConsoleMode.return_value = False

        with patch.object(tester, "IS_WINDOWS", True):
            with patch.object(ctypes, "WinDLL", return_value=kernel32, create=True):
                with tester._ansi_console() as enabled:
                    self.assertFalse(enabled)

        kernel32.SetConsoleMode.assert_not_called()


class TestSelectOption(unittest.TestCase):
    def _select(self, keys: list[str], options: list[str]) -> int | None:
        remaining = iter(keys)

        @contextlib.contextmanager
        def fake_input():
            yield lambda: next(remaining)

        @contextlib.contextmanager
        def fake_ansi():
            yield False

        stdin = MagicMock()
        stdin.isatty.return_value = True

        with patch.object(tester.sys, "stdin", stdin):
            with patch.object(tester, "_raw_key_input", fake_input):
                with patch.object(tester, "_ansi_console", fake_ansi):
                    with patch.object(tester.sys, "stdout", MagicMock()):
                        return tester.select_option("Pick one", options)

    def test_the_selection_moves_with_the_arrow_keys(self):
        self.assertEqual(
            self._select([tester.KEY_DOWN, tester.KEY_ENTER], ["a", "b"]), 1
        )

    def test_the_selection_moves_with_j_and_k(self):
        self.assertEqual(
            self._select(["j", "j", "k", tester.KEY_ENTER], ["a", "b", "c"]),
            1,
        )

    def test_escape_cancels(self):
        self.assertIsNone(self._select([tester.KEY_ESCAPE], ["a", "b"]))

    def test_q_cancels(self):
        self.assertIsNone(self._select(["q"], ["a", "b"]))

    def test_a_console_without_escape_sequences_still_works(self):
        """The menu falls back to printing the options again."""
        self.assertEqual(
            self._select([tester.KEY_DOWN, tester.KEY_ENTER], ["a", "b"]), 1
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
