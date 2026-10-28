import multiprocessing as mp
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import gannet.__main__ as gannet_main
import gannet.log
from gannet.config import FrigateConfig
from gannet.util.platform import get_mp_start_method
from gannet.util.process import FrigateProcess

ENV_KEY = "FRIGATE_TEST_PROCESS_ENV"


class EnvReportingProcess(FrigateProcess):
    def __init__(self, stop_event, result_queue):
        super().__init__(stop_event, 0, name="env_reporter", daemon=True)
        self.result_queue = result_queue

    def run(self) -> None:
        self.pre_run_setup()
        self.result_queue.put(os.environ.get(ENV_KEY))


def _run_main_and_report(result_queue) -> None:
    """Run frigate's main() with the config load and app faked out.

    Runs in a fresh interpreter so no earlier test initialized multiprocessing.
    """
    mp.set_start_method(get_mp_start_method(), force=True)

    def load(**kwargs):
        os.environ[ENV_KEY] = "applied"
        return SimpleNamespace(cameras={})

    def setup_logging(manager):
        gannet.log.log_listener = SimpleNamespace(queue=manager.Queue())

    class FakeApp:
        def __init__(self, config, manager, stop_event):
            self.stop_event = stop_event

        def start(self):
            child_queue = mp.Queue()
            process = EnvReportingProcess(self.stop_event, child_queue)
            process.start()
            result_queue.put(child_queue.get(timeout=30))
            process.join(timeout=10)

    try:
        with (
            patch.object(sys, "argv", ["frigate"]),
            patch.object(FrigateConfig, "load", load),
            patch("gannet.__main__.require_windows"),
            patch("gannet.__main__.setup_logging", setup_logging),
            patch("gannet.__main__.FrigateApp", FakeApp),
            patch("gannet.__main__.ensure_runtime_dirs"),
            patch("gannet.__main__.install_job_object"),
            patch("gannet.__main__.install_signal_handlers"),
            patch("gannet.__main__.install_service_stop_watcher"),
            patch("gannet.__main__.long_path_warning", return_value=None),
        ):
            gannet_main.main()
    except Exception as err:
        result_queue.put(f"error: {err!r}")


class TestWorkerEnvironment(unittest.TestCase):
    def test_env_applied_by_config_load_reaches_worker_processes(self):
        ctx = mp.get_context("spawn")
        result_queue = ctx.Queue()
        runner = ctx.Process(target=_run_main_and_report, args=(result_queue,))
        runner.start()

        try:
            self.assertEqual(result_queue.get(timeout=60), "applied")
        finally:
            runner.join(timeout=10)

            if runner.is_alive():
                runner.terminate()
                runner.join()


if __name__ == "__main__":
    unittest.main()
