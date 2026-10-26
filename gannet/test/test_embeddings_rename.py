# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Tests for renaming a face library folder."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from gannet.embeddings import EmbeddingsContext


class TestRenameFace(unittest.TestCase):
    def setUp(self) -> None:
        self.face_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.face_dir, True)

        self.context = EmbeddingsContext.__new__(EmbeddingsContext)
        self.context.requestor = MagicMock()

    def _face(self, name: str) -> str:
        path = os.path.join(self.face_dir, name)
        os.makedirs(path, exist_ok=True)
        return path

    def test_renames_an_existing_face(self):
        old = self._face("John")
        self._face("Jane")

        with patch("gannet.embeddings.FACE_DIR", self.face_dir):
            self.context.rename_face("John", "Johnny")

        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.isdir(os.path.join(self.face_dir, "Johnny")))

    def test_refuses_to_rename_onto_an_existing_face(self):
        """The destination is checked before the folder is moved.

        os.rename replaces an existing file on POSIX but fails on Windows, so
        without the check the request answered 500 on Windows and 400
        everywhere else.
        """
        old = self._face("John")
        taken = self._face("Johnny")

        with patch("gannet.embeddings.FACE_DIR", self.face_dir):
            with self.assertRaisesRegex(ValueError, "already exists"):
                self.context.rename_face("John", "Johnny")

        self.assertTrue(os.path.isdir(old))
        self.assertTrue(os.path.isdir(taken))

    def test_a_name_that_only_differs_in_case_is_allowed(self):
        """Windows resolves both spellings to the same folder."""
        old = self._face("John")

        with patch("gannet.embeddings.FACE_DIR", self.face_dir):
            self.context.rename_face("John", "john")

        self.assertTrue(os.path.isdir(os.path.join(self.face_dir, "john")))

        if os.name == "nt":
            self.assertTrue(os.path.isdir(old))
        else:
            self.assertFalse(os.path.exists(old))


if __name__ == "__main__":
    unittest.main(verbosity=2)
