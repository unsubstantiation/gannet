# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Classification category renames on a case-insensitive (NTFS) file system."""

import os
import shutil
import tempfile
from unittest.mock import patch

from frigate.models import Event
from frigate.test.http_api.base_http_test import AuthTestClient, BaseTestHttp


class TestHttpClassificationRename(BaseTestHttp):
    def setUp(self):
        super().setUp([Event])
        self.minimal_config["classification"] = {
            "custom": {"model1": {"object_config": {"objects": ["person"]}}}
        }
        self.app = super().create_app()

        self.root = tempfile.mkdtemp()
        self.clips = os.path.join(self.root, "clips")
        self.dataset = os.path.join(self.clips, "model1", "dataset")
        os.makedirs(os.path.join(self.dataset, "cat"))
        os.makedirs(os.path.join(self.dataset, "dog"))

        for module in (
            "frigate.api.classification.CLIPS_DIR",
            "frigate.util.classification.CLIPS_DIR",
        ):
            patcher = patch(module, self.clips)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        self.app.dependency_overrides.clear()
        super().tearDown()

    def _categories(self) -> list[str]:
        return sorted(
            name
            for name in os.listdir(self.dataset)
            if os.path.isdir(os.path.join(self.dataset, name))
        )

    def test_rename_category(self):
        client = AuthTestClient(self.app)

        response = client.put(
            "/classification/model1/dataset/cat/rename",
            json={"new_category": "feline"},
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(self._categories(), ["dog", "feline"])

    def test_case_only_rename_is_not_a_collision(self):
        """NTFS resolves 'Cat' to the existing 'cat' folder; the rename must
        still change the spelling instead of reporting a duplicate."""
        client = AuthTestClient(self.app)

        response = client.put(
            "/classification/model1/dataset/cat/rename",
            json={"new_category": "Cat"},
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(self._categories(), ["Cat", "dog"])

    def test_rename_onto_another_category_is_rejected(self):
        client = AuthTestClient(self.app)

        response = client.put(
            "/classification/model1/dataset/cat/rename",
            json={"new_category": "dog"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._categories(), ["cat", "dog"])
