# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Windows ML execution-provider registration and selection helpers."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from gannet.detectors import windows_ml


class TestWindowsMlRegistration(unittest.TestCase):
    def setUp(self):
        windows_ml._registered.clear()
        self.catalog_providers = windows_ml._catalog_providers

    def tearDown(self):
        windows_ml._catalog_providers = self.catalog_providers

    def test_registers_only_ready_catalog_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "qnn.dll"
            library.write_bytes(b"provider")
            ready = SimpleNamespace(name="Ready")
            not_present = SimpleNamespace(name="NotPresent")
            windows_ml._catalog_providers = lambda: [
                ("QNNExecutionProvider", "1.0", ready, str(library)),
                ("VitisAIExecutionProvider", "1.0", not_present, str(library)),
            ]
            runtime = MagicMock()

            names = windows_ml.register_ready_providers(runtime)

        self.assertEqual(names, {"QNNExecutionProvider"})
        runtime.register_execution_provider_library.assert_called_once_with(
            "QNNExecutionProvider", str(library)
        )

    def test_experimental_webgpu_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "webgpu.dll"
            library.write_bytes(b"provider")
            windows_ml._catalog_providers = lambda: [
                (
                    "WebGpuExecutionProvider",
                    "1.0",
                    SimpleNamespace(name="Ready"),
                    str(library),
                )
            ]
            runtime = MagicMock()

            with patch.dict("os.environ", {}, clear=True):
                names = windows_ml.register_ready_providers(runtime)

        self.assertEqual(names, set())
        runtime.register_execution_provider_library.assert_not_called()

    def test_registration_is_idempotent_for_a_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / "provider.dll"
            library.write_bytes(b"provider")
            windows_ml._catalog_providers = lambda: [
                (
                    "QNNExecutionProvider",
                    "1.0",
                    SimpleNamespace(name="Ready"),
                    str(library),
                )
            ]
            runtime = MagicMock()

            windows_ml.register_ready_providers(runtime)
            windows_ml.register_ready_providers(runtime)

        runtime.register_execution_provider_library.assert_called_once()

    def test_discovers_devices_only_for_registered_providers(self):
        device = SimpleNamespace(ep_name="QNNExecutionProvider")
        runtime = MagicMock()
        runtime.get_ep_devices.return_value = [
            device,
            SimpleNamespace(ep_name="CPUExecutionProvider"),
        ]
        with patch.object(
            windows_ml,
            "register_ready_providers",
            return_value={"QNNExecutionProvider"},
        ):
            found = windows_ml.registered_provider_devices(runtime)

        self.assertEqual(found, {"QNNExecutionProvider": [device]})

    def test_provider_selector_accepts_named_prefixes(self):
        self.assertEqual(
            windows_ml.provider_from_device("windowsml:QNNExecutionProvider"),
            "QNNExecutionProvider",
        )
        self.assertEqual(
            windows_ml.provider_from_device("winml:VitisAIExecutionProvider"),
            "VitisAIExecutionProvider",
        )
        self.assertIsNone(windows_ml.provider_from_device("cuda:0"))
        self.assertEqual(
            windows_ml.provider_label("NvTensorRtRtxExecutionProvider"),
            "NVIDIA TensorRT-RTX",
        )


if __name__ == "__main__":
    unittest.main()
