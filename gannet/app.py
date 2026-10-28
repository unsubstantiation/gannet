import datetime
import logging
import multiprocessing as mp
import os
import secrets
import shutil
from collections.abc import Callable
from multiprocessing import Queue
from multiprocessing.managers import DictProxy, SyncManager
from multiprocessing.synchronize import Event as MpEvent
from pathlib import Path

from peewee import SqliteDatabase
from peewee_migrate import Router

from gannet.api.auth import hash_password
from gannet.api.fastapi_app import create_fastapi_app
from gannet.api.web import run_native_web_server
from gannet.camera import CameraMetrics, PTZMetrics
from gannet.camera.maintainer import CameraMaintainer
from gannet.comms.base_communicator import Communicator
from gannet.comms.dispatcher import Dispatcher
from gannet.comms.event_metadata_updater import EventMetadataPublisher
from gannet.comms.inter_process import InterProcessCommunicator
from gannet.comms.mqtt import MqttClient
from gannet.comms.object_detector_signaler import DetectorProxy
from gannet.comms.webpush import WebPushClient
from gannet.comms.ws import WebSocketClient
from gannet.comms.zmq_proxy import ZmqProxy
from gannet.config.camera.updater import CameraConfigUpdatePublisher
from gannet.config.config import FrigateConfig
from gannet.config.holder import ConfigHolder
from gannet.config.profile_manager import ProfileManager
from gannet.const import (
    CACHE_DIR,
    CLIPS_DIR,
    CONFIG_DIR,
    EXPORT_DIR,
    FACE_DIR,
    MODEL_CACHE_DIR,
    RECORD_DIR,
    THUMB_DIR,
    TMP_DIR,
    TRIGGER_DIR,
)
from gannet.data_processing.types import DataProcessorMetrics
from gannet.db.sqlitevecq import SqliteVecQueueDatabase
from gannet.debug_replay import (
    DebugReplayManager,
    cleanup_replay_cameras,
)
from gannet.detectors.device import build_detector_config, runner_names
from gannet.embeddings import EmbeddingProcess, EmbeddingsContext
from gannet.events.audio import AudioProcessor, join_audio_process
from gannet.events.cleanup import EventCleanup
from gannet.events.maintainer import EventProcessor
from gannet.jobs.export import reap_stale_exports
from gannet.jobs.motion_search import stop_all_motion_search_jobs
from gannet.log import _stop_logging
from gannet.models import (
    Event,
    Export,
    Notice,
    NoticeStats,
    Previews,
    Recordings,
    RecordingsToDelete,
    Regions,
    ReviewSegment,
    Timeline,
    Trigger,
    User,
)
from gannet.notices import install_registry
from gannet.notices.registry import NoticeRegistry
from gannet.object_detection.base import ObjectDetectProcess
from gannet.object_detection.util import detection_frame_size
from gannet.output.output import OutputProcess
from gannet.ptz.autotrack import PtzAutoTracker
from gannet.ptz.onvif import OnvifController
from gannet.record.cleanup import RecordingCleanup
from gannet.record.export import migrate_exports
from gannet.record.record import RecordProcess
from gannet.review.review import ReviewProcess
from gannet.stats.emitter import StatsEmitter
from gannet.stats.util import stats_init
from gannet.storage import StorageMaintainer
from gannet.timeline import TimelineProcessor
from gannet.track.object_processing import TrackedObjectProcessor
from gannet.util.builtin import empty_and_close_queue
from gannet.util.file import robust_remove
from gannet.util.go2rtc_config import (
    build_go2rtc_config,
    go2rtc_config_path,
    load_raw_config,
    write_go2rtc_config,
)
from gannet.util.go2rtc_process import Go2rtcProcess
from gannet.util.image import UntrackedSharedMemory
from gannet.util.process import FrigateProcess
from gannet.util.services import set_file_limit
from gannet.util.version import VERSION
from gannet.watchdog import FrigateWatchdog

logger = logging.getLogger(__name__)


class FrigateApp:
    def __init__(
        self, config: FrigateConfig, manager: SyncManager, stop_event: MpEvent
    ) -> None:
        self.metrics_manager = manager
        self.audio_process: mp.Process | None = None
        self.go2rtc_process: Go2rtcProcess | None = None
        self.stop_event = stop_event
        self.detection_queues: dict[str, Queue] = {
            model.scene: mp.Queue() for model in config.models
        }
        self.detectors: dict[str, ObjectDetectProcess] = {}
        self.detection_shms: list[mp.shared_memory.SharedMemory] = []
        self.log_queue: Queue = mp.Queue()
        self.camera_metrics: DictProxy = self.metrics_manager.dict()

        self.embeddings_metrics = DataProcessorMetrics(
            self.metrics_manager, list(config.classification.custom.keys())
        )
        self.ptz_metrics: dict[str, PTZMetrics] = {}
        self.processes: dict[str, int] = {}
        self.embeddings: EmbeddingsContext | None = None
        self.config_holder = ConfigHolder(config)

    @property
    def config(self) -> FrigateConfig:
        """The current config, not the one Gannet booted with.

        Read through the holder so the deferred watchdog factories below build
        a replacement process from the config as it is now. There is no setter
        on purpose: a plain attribute would let a caller pin this back to a
        single object and reintroduce the staleness.
        """
        return self.config_holder.config

    def ensure_dirs(self) -> None:
        dirs = [
            CONFIG_DIR,
            RECORD_DIR,
            THUMB_DIR,
            os.path.join(CLIPS_DIR, "cache"),
            CACHE_DIR,
            MODEL_CACHE_DIR,
            EXPORT_DIR,
        ]

        if self.config.face_recognition.enabled:
            dirs.append(FACE_DIR)

        if self.config.semantic_search.enabled:
            dirs.append(TRIGGER_DIR)

        for d in dirs:
            if not os.path.exists(d) and not os.path.islink(d):
                logger.info(f"Creating directory: {d}")
                os.makedirs(d, exist_ok=True)
            else:
                logger.debug(f"Skipping directory: {d}")

    def init_debug_replay_manager(self) -> None:
        self.replay_manager = DebugReplayManager()

    def init_camera_metrics(self) -> None:
        # create camera_metrics
        for camera_name in self.config.cameras.keys():
            self.camera_metrics[camera_name] = CameraMetrics(self.metrics_manager)
            self.ptz_metrics[camera_name] = PTZMetrics()

    def init_queues(self) -> None:
        # Queue for cameras to push tracked objects to
        # leaving room for 2 extra cameras to be added
        self.detected_frames_queue: Queue = mp.Queue(
            maxsize=(
                sum(
                    camera.enabled_in_config == True
                    for camera in self.config.cameras.values()
                )
                + 2
            )
            * 2
        )

        # Queue for timeline events
        self.timeline_queue: Queue = mp.Queue()

    def init_database(self) -> None:
        def vacuum_db(db: SqliteDatabase) -> None:
            logger.info("Running database vacuum")
            db.execute_sql("VACUUM;")

            try:
                with open(f"{CONFIG_DIR}/.vacuum", "w", encoding="utf-8") as f:
                    f.write(str(datetime.datetime.now().timestamp()))
            except PermissionError:
                logger.error("Unable to write to %s to save DB state", CONFIG_DIR)

        # Migrate DB schema
        migrate_db = SqliteDatabase(self.config.database.path)

        # Run migrations
        del logging.getLogger("peewee_migrate").handlers[:]
        router = Router(migrate_db)

        if len(router.diff) > 0:
            logger.info("Making backup of DB before migrations...")
            shutil.copyfile(
                self.config.database.path,
                self.config.database.path.replace("gannet.db", "backup.db"),
            )

        router.run()

        # check if vacuum needs to be run
        if os.path.exists(f"{CONFIG_DIR}/.vacuum"):
            with open(f"{CONFIG_DIR}/.vacuum", encoding="utf-8") as f:
                try:
                    timestamp = round(float(f.readline()))
                except Exception:
                    timestamp = 0

                if (
                    timestamp
                    < (
                        datetime.datetime.now() - datetime.timedelta(weeks=2)
                    ).timestamp()
                ):
                    vacuum_db(migrate_db)
        else:
            vacuum_db(migrate_db)

        migrate_db.close()

    def init_go2rtc(self) -> None:
        self.start_native_go2rtc()

    def start_native_go2rtc(self) -> None:
        """Generate go2rtc's config and start the managed Windows child process."""
        path = go2rtc_config_path()

        # go2rtc reads the config once at startup, so a stale file from a
        # previous run has to go before a new one is dumped
        try:
            robust_remove(path, missing_ok=True)
        except OSError as err:
            logger.warning("Unable to remove the stale go2rtc config: %s", err)

        try:
            write_go2rtc_config(build_go2rtc_config(load_raw_config()), path)
        except Exception as err:
            logger.error("Unable to generate the go2rtc config: %s", err)

        go2rtc = Go2rtcProcess(path)

        if go2rtc.start():
            self.go2rtc_process = go2rtc

    def init_recording_manager(self) -> None:
        recording_process = RecordProcess(self.config, self.stop_event)
        self.recording_process = recording_process
        recording_process.start()
        self.processes["recording"] = recording_process.pid or 0
        logger.info(f"Recording process started: {recording_process.pid}")

    def init_review_segment_manager(self) -> None:
        review_segment_process = ReviewProcess(self.config, self.stop_event)
        self.review_segment_process = review_segment_process
        review_segment_process.start()
        self.processes["review_segment"] = review_segment_process.pid or 0
        logger.info(f"Review process started: {review_segment_process.pid}")

    def init_embeddings_manager(self) -> None:
        # always start the embeddings process
        embedding_process = EmbeddingProcess(
            self.config, self.embeddings_metrics, self.stop_event
        )
        self.embedding_process = embedding_process
        embedding_process.start()
        self.processes["embeddings"] = embedding_process.pid or 0
        logger.info(f"Embedding process started: {embedding_process.pid}")

    def bind_database(self) -> None:
        """Bind db to the main process."""
        # NOTE: all db accessing processes need to be created before the db can be bound to the main process
        self.db = SqliteVecQueueDatabase(
            self.config.database.path,
            pragmas={
                "auto_vacuum": "FULL",  # Does not defragment database
                "cache_size": -512 * 1000,  # 512MB of cache,
                "synchronous": "NORMAL",  # Safe when using WAL https://www.sqlite.org/pragma.html#pragma_synchronous
            },
            timeout=max(
                60,
                10
                * len([c for c in self.config.cameras.values() if c.enabled_in_config]),
            ),
            load_vec_extension=True,
        )
        models = [
            Event,
            Export,
            Notice,
            NoticeStats,
            Previews,
            Recordings,
            RecordingsToDelete,
            Regions,
            ReviewSegment,
            Timeline,
            User,
            Trigger,
        ]
        self.db.bind(models)

    def check_db_data_migrations(self) -> None:
        # check if vacuum needs to be run
        if not os.path.exists(f"{CONFIG_DIR}/.exports"):
            try:
                with open(f"{CONFIG_DIR}/.exports", "w", encoding="utf-8") as f:
                    f.write(str(datetime.datetime.now().timestamp()))
            except PermissionError:
                logger.error(
                    "Unable to write export state to the Windows config directory"
                )

            migrate_exports(self.config.ffmpeg, list(self.config.cameras.keys()))

    def install_notice_registry(self) -> None:
        self.notice_registry = NoticeRegistry()
        install_registry(self.notice_registry)

    def init_embeddings_client(self) -> None:
        # Create a client for other processes to use
        self.embeddings = EmbeddingsContext(self.db)

    def init_inter_process_communicator(self) -> None:
        self.inter_process_communicator = InterProcessCommunicator()
        self.inter_config_updater = CameraConfigUpdatePublisher()
        self.event_metadata_updater = EventMetadataPublisher()
        self.inter_zmq_proxy = ZmqProxy()
        self.detection_proxy = DetectorProxy()

    def init_onvif(self) -> None:
        self.onvif_controller = OnvifController(self.config, self.ptz_metrics)

    def init_dispatcher(self) -> None:
        comms: list[Communicator] = []

        if self.config.mqtt.enabled:
            comms.append(MqttClient(self.config))

        notification_cameras = [
            c
            for c in self.config.cameras.values()
            if c.enabled and c.notifications.enabled_in_config
        ]

        if notification_cameras:
            comms.append(WebPushClient(self.config, self.stop_event))

        comms.append(WebSocketClient(self.config))
        comms.append(self.inter_process_communicator)

        self.dispatcher = Dispatcher(
            self.config,
            self.inter_config_updater,
            self.onvif_controller,
            self.ptz_metrics,
            comms,
            notice_registry=self.notice_registry,
        )
        self.dispatcher.start_communicators()

    def init_profile_manager(self) -> None:
        self.profile_manager = ProfileManager(
            self.config, self.inter_config_updater, self.dispatcher
        )
        self.dispatcher.profile_manager = self.profile_manager

    def start_detectors(self) -> None:
        model_cameras: dict[str, list[str]] = {
            model.scene: [] for model in self.config.models
        }

        for name in self.config.cameras.keys():
            model = self.config.model_for_camera(name)
            model_cameras[model.scene].append(name)

            try:
                shm_in = UntrackedSharedMemory(
                    name=name,
                    create=True,
                    size=detection_frame_size(model),
                )
            except FileExistsError:
                shm_in = UntrackedSharedMemory(name=name)

            try:
                shm_out = UntrackedSharedMemory(
                    name=f"out-{name}", create=True, size=20 * 6 * 4
                )
            except FileExistsError:
                shm_out = UntrackedSharedMemory(name=f"out-{name}")

            self.detection_shms.append(shm_in)
            self.detection_shms.append(shm_out)

        # a device may be listed more than once to run additional inference
        # processes on it, so names are only unique once de-duplicated
        all_devices = [
            device
            for model in self.config.models
            for device in self.config.devices_for_model(model)
        ]
        names = iter(runner_names(all_devices))

        for model in self.config.models:
            for device in self.config.devices_for_model(model):
                name = next(names)
                self.detectors[name] = ObjectDetectProcess(
                    name,
                    self.detection_queues[model.scene],
                    model_cameras[model.scene],
                    self.config,
                    build_detector_config(device, model),
                    self.stop_event,
                )

    def start_ptz_autotracker(self) -> None:
        self.ptz_autotracker_thread = PtzAutoTracker(
            self.config,
            self.onvif_controller,
            self.ptz_metrics,
            self.dispatcher,
            self.stop_event,
        )
        self.ptz_autotracker_thread.start()

    def start_detected_frames_processor(self) -> None:
        self.detected_frames_processor = TrackedObjectProcessor(
            self.config,
            self.dispatcher,
            self.detected_frames_queue,
            self.ptz_autotracker_thread,
            self.stop_event,
        )
        self.detected_frames_processor.start()

    def start_video_output_processor(self) -> None:
        output_processor = OutputProcess(self.config, self.stop_event)
        self.output_processor = output_processor
        output_processor.start()
        logger.info(f"Output process started: {output_processor.pid}")

    def start_camera_processor(self) -> None:
        self.camera_maintainer = CameraMaintainer(
            self.config,
            self.detection_queues,
            self.detected_frames_queue,
            self.camera_metrics,
            self.ptz_metrics,
            self.stop_event,
            self.metrics_manager,
        )
        self.camera_maintainer.start()

    def start_audio_processor(self) -> None:
        self.audio_process = AudioProcessor(
            self.config, self.camera_metrics, self.embeddings_metrics, self.stop_event
        )
        self.audio_process.start()
        self.processes["audio_detector"] = self.audio_process.pid or 0

    def start_timeline_processor(self) -> None:
        self.timeline_processor = TimelineProcessor(
            self.config, self.timeline_queue, self.stop_event
        )
        self.timeline_processor.start()

    def start_event_processor(self) -> None:
        self.event_processor = EventProcessor(
            self.config,
            self.timeline_queue,
            self.stop_event,
        )
        self.event_processor.start()

    def start_event_cleanup(self) -> None:
        self.event_cleanup = EventCleanup(self.config, self.stop_event, self.db)
        self.event_cleanup.start()

    def start_record_cleanup(self) -> None:
        self.record_cleanup = RecordingCleanup(self.config, self.stop_event)
        self.record_cleanup.start()

    def start_storage_maintainer(self) -> None:
        self.storage_maintainer = StorageMaintainer(self.config, self.stop_event)
        self.storage_maintainer.start()

    def start_stats_emitter(self) -> None:
        self.stats_emitter = StatsEmitter(
            self.config,
            stats_init(
                self.config,
                self.camera_metrics,
                self.embeddings_metrics,
                self.detectors,
                self.processes,
                self.storage_maintainer,
            ),
            self.stop_event,
        )
        self.stats_emitter.start()

    def start_watchdog(self) -> None:
        self.frigate_watchdog = FrigateWatchdog(self.detectors, self.stop_event)

        # (attribute on self, key in self.processes, factory)
        specs: list[tuple[str, str, Callable[[], FrigateProcess]]] = [
            (
                "embedding_process",
                "embeddings",
                lambda: EmbeddingProcess(
                    self.config, self.embeddings_metrics, self.stop_event
                ),
            ),
            (
                "recording_process",
                "recording",
                lambda: RecordProcess(self.config, self.stop_event),
            ),
            (
                "review_segment_process",
                "review_segment",
                lambda: ReviewProcess(self.config, self.stop_event),
            ),
            (
                "output_processor",
                "output",
                lambda: OutputProcess(self.config, self.stop_event),
            ),
            (
                "audio_process",
                "audio_detector",
                lambda: AudioProcessor(
                    self.config,
                    self.camera_metrics,
                    self.embeddings_metrics,
                    self.stop_event,
                ),
            ),
        ]

        for attr, key, factory in specs:
            if getattr(self, attr, None) is None:
                continue

            def on_restart(
                proc: FrigateProcess, _attr: str = attr, _key: str = key
            ) -> None:
                setattr(self, _attr, proc)
                self.processes[_key] = proc.pid or 0

            self.frigate_watchdog.register(
                key, getattr(self, attr), factory, on_restart
            )

        self.frigate_watchdog.start()

    def init_auth(self) -> None:
        if self.config.auth.enabled:
            if (
                User.select().count() == 0
                or User.select()
                .where((User.username == "admin") & (User.password_hash == ""))
                .exists()
            ):
                password = secrets.token_hex(16)
                password_hash = hash_password(
                    password, iterations=self.config.auth.hash_iterations
                )
                User.insert(
                    {
                        User.username: "admin",
                        User.role: "admin",
                        User.password_hash: password_hash,
                        User.notification_tokens: [],
                    }
                ).on_conflict(
                    conflict_target=[User.username],
                    update={User.password_hash: password_hash},
                ).execute()

                self.config.auth.admin_first_time_login = True

                logger.info("********************************************************")
                logger.info("********************************************************")
                logger.info("***    Auth is enabled, but no users exist.          ***")
                logger.info("***    Created a default user:                       ***")
                logger.info("***    User: admin                                   ***")
                logger.info(f"***    Password: {password}   ***")
                logger.info("********************************************************")
                logger.info("********************************************************")
            elif self.config.auth.reset_admin_password:
                password = secrets.token_hex(16)
                password_hash = hash_password(
                    password, iterations=self.config.auth.hash_iterations
                )
                User.replace(
                    username="admin",
                    role="admin",
                    password_hash=password_hash,
                    password_changed_at=datetime.datetime.now(),
                    notification_tokens=[],
                ).execute()

                logger.info("********************************************************")
                logger.info("********************************************************")
                logger.info("***    Reset admin password set in the config.       ***")
                logger.info(f"***    Password: {password}   ***")
                logger.info("********************************************************")
                logger.info("********************************************************")
        else:
            # Notification registrations store tokens on the admin row. Its
            # empty password hash marks it for a generated password if auth
            # is enabled later.
            if User.select().count() == 0:
                User.insert(
                    {
                        User.username: "admin",
                        User.role: "admin",
                        User.password_hash: "",
                        User.notification_tokens: [],
                    }
                ).execute()

    def start(self) -> None:
        logger.info(f"Starting Gannet ({VERSION})")

        # Ensure global state.
        self.ensure_dirs()

        # Set soft file limits.
        set_file_limit()

        # Start frigate services.
        self.init_debug_replay_manager()
        self.init_camera_metrics()
        self.init_queues()
        self.init_database()
        self.init_onvif()
        self.init_recording_manager()
        self.init_review_segment_manager()
        self.init_go2rtc()
        self.init_embeddings_manager()
        self.bind_database()
        self.check_db_data_migrations()
        self.install_notice_registry()

        # Clean up any stale replay camera artifacts (filesystem + DB)
        cleanup_replay_cameras()

        # Reap any Export rows still marked in_progress from a previous
        # session (crash, kill, broken migration). Runs synchronously before
        # uvicorn binds so no API request can observe a stale row.
        reap_stale_exports()

        self.init_inter_process_communicator()
        self.start_detectors()
        self.init_dispatcher()
        self.init_profile_manager()

        # workers get a copy of the config and can miss the broadcast below, so
        # apply both layers here. must stay after init_profile_manager(), which
        # snapshots the base config that profile deactivation resets to
        self.profile_manager.restore_persisted_profile_to_config()
        self.dispatcher.reapply_runtime_state_to_config()

        self.init_embeddings_client()
        self.start_video_output_processor()
        self.start_ptz_autotracker()
        self.start_detected_frames_processor()
        self.start_camera_processor()
        self.start_audio_processor()
        self.start_storage_maintainer()
        self.start_stats_emitter()
        self.start_timeline_processor()
        self.start_event_processor()
        self.start_event_cleanup()
        self.start_record_cleanup()
        self.start_watchdog()

        # publish for the recording/review/embeddings processes, which start
        # before the config can be corrected, and for the retained MQTT states
        self.profile_manager.restore_persisted_profile()
        self.dispatcher.restore_runtime_state()

        self.init_auth()

        app = create_fastapi_app(
            self.config,
            self.db,
            self.embeddings,
            self.detected_frames_processor,
            self.storage_maintainer,
            self.onvif_controller,
            self.stats_emitter,
            self.event_metadata_updater,
            self.inter_config_updater,
            self.replay_manager,
            self.dispatcher,
            self.profile_manager,
            config_holder=self.config_holder,
            notice_registry=self.notice_registry,
        )

        try:
            run_native_web_server(
                app,
                self.config.networking.listen.internal_port,
                self.config.networking.listen.external_port,
                self.stop_event,
                ipv6_enabled=self.config.networking.ipv6.enabled,
                public_host=self.config.networking.listen.external_host,
                tls_enabled=self.config.tls.enabled,
                tls_cert_file=self.config.tls.cert_file,
                tls_key_file=self.config.tls.key_file,
            )
        finally:
            self.stop()

    def stop(self) -> None:
        logger.info("Stopping...")

        # The launcher can use this runtime marker to distinguish a clean stop
        # from a crash.
        stopping_flag = Path(TMP_DIR) / ".gannet-is-stopping"

        try:
            stopping_flag.parent.mkdir(parents=True, exist_ok=True)
            stopping_flag.touch()
        except OSError as err:
            logger.debug("Unable to write the stopping flag: %s", err)

        # Cancel any running motion search jobs before setting stop_event
        stop_all_motion_search_jobs()

        self.stop_event.set()

        # set an end_time on entries without an end_time before exiting
        Event.update(
            end_time=datetime.datetime.now().timestamp(), has_snapshot=False
        ).where(Event.end_time == None).execute()
        ReviewSegment.update(end_time=datetime.datetime.now().timestamp()).where(
            ReviewSegment.end_time == None
        ).execute()

        # stop the audio process after the shared stop event so it can flush
        # and close its own FFmpeg workers cleanly on Windows.
        if self.audio_process:
            join_audio_process(self.audio_process)

        # stop go2rtc, which a native install runs as a child process
        if self.go2rtc_process:
            self.go2rtc_process.stop()

        # stop the onvif controller
        if self.onvif_controller:
            self.onvif_controller.close()

        # ensure the detectors are done
        for detector in self.detectors.values():
            detector.stop()

        for detection_queue in self.detection_queues.values():
            empty_and_close_queue(detection_queue)

        logger.info("Detection queues closed")

        self.detected_frames_processor.join()
        empty_and_close_queue(self.detected_frames_queue)
        logger.info("Detected frames queue closed")

        self.timeline_processor.join()
        self.event_processor.join()
        empty_and_close_queue(self.timeline_queue)
        logger.info("Timeline queue closed")

        # These workers observe the shared event and perform their own cleanup;
        # do not terminate them while they hold queues or files open.
        self.output_processor.join()
        self.recording_process.join()
        self.review_segment_process.join()

        self.dispatcher.stop()
        self.ptz_autotracker_thread.join()

        self.event_cleanup.join()
        self.record_cleanup.join()
        self.stats_emitter.join()
        self.frigate_watchdog.join()
        self.camera_maintainer.join()
        self.db.stop()

        # Save embeddings stats to disk
        if self.embeddings:
            self.embeddings.stop()

        # Stop Communicators
        self.inter_process_communicator.stop()
        self.inter_config_updater.stop()
        self.event_metadata_updater.stop()
        self.inter_zmq_proxy.stop()
        self.detection_proxy.stop()

        while len(self.detection_shms) > 0:
            shm = self.detection_shms.pop()
            shm.close()
            shm.unlink()

        _stop_logging()
        self.metrics_manager.shutdown()
