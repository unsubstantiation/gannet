"""Tests for ONNX Runtime session option selection."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import onnxruntime as ort

from gannet.detectors.detection_runners import (
    CudaGraphRunner,
    OpenVINOModelError,
    OpenVINOModelRunner,
    describe_openvino_failure,
    get_ort_session_options,
)
from gannet.detectors.detector_config import ModelTypeEnum
from gannet.embeddings.types import EnrichmentModelTypeEnum


class TestGetOrtSessionOptions(unittest.TestCase):
    def test_jina_v2_uses_extended(self):
        """jina-clip-v2 returns an identical vector for every image on the CUDA
        execution provider at anything below EXTENDED."""
        options = get_ort_session_options(EnrichmentModelTypeEnum.jina_v2.value)

        self.assertIsNotNone(options)
        self.assertEqual(
            options.graph_optimization_level,
            ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED,
        )

    def test_jina_v1_uses_basic(self):
        options = get_ort_session_options(EnrichmentModelTypeEnum.jina_v1.value)

        self.assertIsNotNone(options)
        self.assertEqual(
            options.graph_optimization_level,
            ort.GraphOptimizationLevel.ORT_ENABLE_BASIC,
        )

    def test_cpu_enrichment_models_disable_spinning(self):
        for model_type in EnrichmentModelTypeEnum:
            with self.subTest(model_type=model_type):
                options = get_ort_session_options(model_type.value, cpu=True)

                self.assertEqual(
                    options.get_session_config_entry("session.intra_op.allow_spinning"),
                    "0",
                )

    def test_gpu_enrichment_models_keep_spinning(self):
        options = get_ort_session_options(EnrichmentModelTypeEnum.arcface.value)

        with self.assertRaises(RuntimeError):
            options.get_session_config_entry("session.intra_op.allow_spinning")

    def test_arcface_keeps_default_optimization(self):
        options = get_ort_session_options(EnrichmentModelTypeEnum.arcface.value)

        self.assertEqual(
            options.graph_optimization_level,
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL,
        )

    def test_detector_models_use_defaults(self):
        for model_type in [None, ModelTypeEnum.rfdetr.value]:
            with self.subTest(model_type=model_type):
                self.assertIsNone(get_ort_session_options(model_type, cpu=True))


class TestCudaGraphRunner(unittest.TestCase):
    """CUDA graph capture fails if the arena has to allocate during capture, so
    the session is warmed up with capture disabled before the first real run."""

    def setUp(self):
        self.session = MagicMock()
        self.session.get_outputs.return_value = [MagicMock(name="output")]
        self.io_binding = self.session.io_binding.return_value
        self.input = {"images": np.zeros((1, 3, 320, 320), np.float32)}

    def _annotations(self) -> list[str | None]:
        """Graph annotation id passed with each run, None when unset."""
        annotations = []

        for call in self.session.run_with_iobinding.call_args_list:
            try:
                annotations.append(call.args[1].get_run_config_entry("gpu_graph_id"))
            except RuntimeError:
                annotations.append(None)

        return annotations

    def test_first_run_warms_up_with_capture_disabled(self):
        with patch.object(ort.OrtValue, "ortvalue_from_numpy"):
            CudaGraphRunner(self.session, 0).run(self.input)

        self.assertEqual(
            self._annotations(),
            ["-1"] * CudaGraphRunner.GRAPH_FREE_WARMUP_RUNS + [None],
        )

    def test_later_runs_allow_capture(self):
        with patch.object(ort.OrtValue, "ortvalue_from_numpy"):
            runner = CudaGraphRunner(self.session, 0)
            runner.run(self.input)
            self.session.run_with_iobinding.reset_mock()
            runner.run(self.input)

        self.assertEqual(self._annotations(), [None])
        runner._input_ortvalue.update_inplace.assert_called_once()


class TestOpenVINOModelFormatErrors(unittest.TestCase):
    """OpenVINO's frontend error is replaced with one an operator can act on."""

    tflite_error = RuntimeError(
        "Exception from src/inference/src/cpp/core.cpp:135:\n"
        "Check 'translate_map.count(decoder->get_op_type())' failed at "
        "src/frontends/tensorflow_lite/src/frontend.cpp:222:\n"
        "FrontEnd API failed with OpConversionFailure:\n"
        "No translator found for TFLite_Detection_PostProcess node."
    )

    def test_tflite_detection_failure_names_the_op_and_the_fix(self):
        message = describe_openvino_failure(
            r"C:\Models\cpu_model.tflite", "GPU", self.tflite_error
        )

        self.assertIn("TFLite_Detection_PostProcess", message)
        self.assertIn("cpu detector", message)
        self.assertIn("IR (.xml) or ONNX export", message)
        # Converting the .tflite itself hits the same missing translator, and
        # a restart cannot fix a model format problem.
        self.assertIn("cannot help", message)
        self.assertIn("no restart", message)

    def test_a_conversion_failure_for_another_op_keeps_the_detail(self):
        error = RuntimeError(
            "FrontEnd API failed with OpConversionFailure:\n"
            "No translator found for SomeCustomOp node."
        )
        message = describe_openvino_failure(r"C:\Models\m.onnx", "CPU", error)

        self.assertIn("could not convert", message)
        self.assertIn("SomeCustomOp", message)

    def test_an_unrelated_error_is_passed_through_with_context(self):
        message = describe_openvino_failure(
            r"C:\Models\m.xml", "NPU", RuntimeError("device not found")
        )

        self.assertIn("device not found", message)
        self.assertIn("NPU", message)

    def test_a_tflite_detection_model_is_refused_before_openvino_runs(self):
        with tempfile.TemporaryDirectory() as model_dir:
            model = os.path.join(model_dir, "detector.tflite")
            with open(model, "wb") as handle:
                handle.write(b"not a real model")

            with self.assertRaises(OpenVINOModelError) as raised:
                OpenVINOModelRunner(
                    model_path=model,
                    device="CPU",
                    model_type=ModelTypeEnum.ssd.value,
                )

        self.assertIn("TFLite_Detection_PostProcess", str(raised.exception))

    def test_a_tflite_enrichment_model_is_not_refused_the_same_way(self):
        """Only detection models use the fused NMS op that has no translator."""
        with tempfile.TemporaryDirectory() as model_dir:
            model = os.path.join(model_dir, "classifier.tflite")
            with open(model, "wb") as handle:
                handle.write(b"not a real model")

            # OpenVINO still reports the load failure, but not as a format
            # conversion problem, so no "this model cannot be converted" hint.
            with self.assertRaises(OpenVINOModelError) as raised:
                OpenVINOModelRunner(
                    model_path=model,
                    device="CPU",
                    model_type=EnrichmentModelTypeEnum.paddleocr.value,
                )

        message = str(raised.exception)
        self.assertIn("could not load", message)
        self.assertNotIn("TFLite_Detection_PostProcess", message)
