import os
import re

from gannet.util.platform import (
    birdseye_pipe_path,
    get_cache_dir,
    get_config_dir,
    get_ffmpeg_dir,
    get_install_dir,
    get_log_dir,
    get_media_dir,
    get_model_cache_dir,
    get_tmp_dir,
)

# Writable paths in the native Windows application-data layout.
INSTALL_DIR = get_install_dir()
FFMPEG_DIR = get_ffmpeg_dir()
CONFIG_DIR = get_config_dir()
TMP_DIR = get_tmp_dir()
DEFAULT_DB_PATH = os.path.join(CONFIG_DIR, "gannet.db")
MODEL_CACHE_DIR = get_model_cache_dir()
BASE_DIR = get_media_dir()
CLIPS_DIR = os.path.join(BASE_DIR, "clips")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
EXPORT_STAGING_DIR = os.path.join(EXPORT_DIR, "staging")
FACE_DIR = os.path.join(CLIPS_DIR, "faces")
THUMB_DIR = os.path.join(CLIPS_DIR, "thumbs")
RECORD_DIR = os.path.join(BASE_DIR, "recordings")
TRIGGER_DIR = os.path.join(CLIPS_DIR, "triggers")
LOG_DIR = get_log_dir()
CACHE_DIR = get_cache_dir()
BIRDSEYE_PIPE = birdseye_pipe_path()
REPLAY_CAMERA_PREFIX = "_replay_"
REPLAY_DIR = os.path.join(CLIPS_DIR, "replay")

FULL_SYSTEM_CPU_KEY = "frigate.full_system"

SHM_FRAMES_VAR = "SHM_MAX_FRAMES"

REDACTED_CREDENTIAL_SENTINEL = "__FRIGATE_SAVED_CREDENTIAL__"

# Stream type constants

STREAM_TYPE_MAIN = "main"
STREAM_TYPE_SUB = "sub"
SUB_CACHE_TAG = "@sub"
RECORD_STREAM_TYPES = (STREAM_TYPE_MAIN, STREAM_TYPE_SUB)
ROLE_TO_STREAM_TYPE = {"record": STREAM_TYPE_MAIN, "record_sub": STREAM_TYPE_SUB}
STREAM_TYPE_TO_ROLE = {v: k for k, v in ROLE_TO_STREAM_TYPE.items()}

# Attribute & Object constants

DEFAULT_ATTRIBUTE_LABEL_MAP = {
    "person": ["amazon", "face"],
    "car": [
        "amazon",
        "an_post",
        "canada_post",
        "dhl",
        "dpd",
        "fedex",
        "gls",
        "license_plate",
        "nzpost",
        "postnl",
        "postnord",
        "purolator",
        "royal_mail",
        "ups",
        "usps",
    ],
    "truck": ["license_plate"],
    "garbage_truck": ["license_plate"],
    "motorcycle": ["license_plate"],
    "bus": ["license_plate"],
    "school_bus": ["license_plate"],
}
ATTRIBUTE_LABEL_DISPLAY_MAP = {
    "amazon": "Amazon",
    "an_post": "An Post",
    "canada_post": "Canada Post",
    "dhl": "DHL",
    "dpd": "DPD",
    "fedex": "FedEx",
    "gls": "GLS",
    "nzpost": "NZ Post",
    "postnl": "PostNL",
    "postnord": "PostNord",
    "purolator": "Purolator",
    "royal_mail": "Royal Mail",
    "ups": "UPS",
    "usps": "USPS",
}
LABEL_CONSOLIDATION_MAP = {
    "car": 0.8,
    "face": 0.5,
}
LABEL_CONSOLIDATION_DEFAULT = 0.9
LABEL_NMS_MAP = {
    "car": 0.6,
}
LABEL_NMS_DEFAULT = 0.4

# Audio constants

AUDIO_DURATION = 0.975
AUDIO_FORMAT = "s16le"
AUDIO_MAX_BIT_RANGE = 32768.0
AUDIO_SAMPLE_RATE = 16000
AUDIO_MIN_CONFIDENCE = 0.5

# DB constants

MAX_WAL_SIZE = 10  # MB

# Ffmpeg constants

LIBAVFORMAT_VERSION_MAJOR = int(os.environ.get("LIBAVFORMAT_VERSION_MAJOR", "59"))
FFMPEG_HVC1_ARGS = ["-tag:v", "hvc1"]

# Regex constants

REGEX_CAMERA_NAME = r"^[a-zA-Z0-9_-]+$"

# Camera names that match REGEX_CAMERA_NAME but are not usable as file or
# directory names on Windows: the path layer resolves them to a device rather
# than to a file, so a camera named con writes its recordings to the console
# and fails to create its own directories. Windows also treats a device name
# as reserved with any extension appended, so only the bare name matters here.
WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(10)}
    | {f"lpt{index}" for index in range(10)}
)
REGEX_RTSP_CAMERA_USER_PASS = r":\/\/[a-zA-Z0-9_-]+:[\S]+@"
# A "user:" userinfo may hold "/", "#" or "@" in the password, so it runs to the
# last "@" before the next URL. Anything else stops at the authority end. Group 1
# is the userinfo and group 2 the rest of the URL.
REGEX_URL_USERINFO = (
    r"://((?:[^\s/?#:\[\]]*:(?:(?!://)\S)*|[^\s/?#]+))@((?:(?!://)\S)*)"
)
_CREDENTIAL_QUERY_KEYS = (
    r"(?:user(?:name)?|usr|login|pass(?:word|wd)?|pwd"
    r"|(?:[a-z_]*_)?token|(?:[a-z_]*_)?secret|client_private|api_?key)"
)
REGEX_CREDENTIAL_QUERY_KEY = rf"(?i)[?&]{_CREDENTIAL_QUERY_KEYS}="
REGEX_CREDENTIAL_QUERY_PARAM = rf"(?i)([?&]{_CREDENTIAL_QUERY_KEYS}=)[^&\s]*"
# UniFi Protect publishes a bearer token as the first path component on its
# standard RTSPS (7441) and RTSP (7447) ports, rather than as userinfo.
REGEX_UNIFI_PROTECT_TOKEN = (
    r"(?i)(rtsps?://[^\s/?#]+:744[17]/)(?:(?!,rtsps?://)[^/?#\s])+"
)
# XMEye-style RTSP paths put both credentials after /user=. Mask the entire
# credential portion, including underscore-separated ONVIF variants. Stop at
# another comma-separated RTSP URL, not at an unescaped comma in a password.
REGEX_XMEYE_AUTH_PATH = (
    r"(?i)(rtsps?://[^\s/?#]+/(?:[^/\s?#]+/)*?)user="
    r"((?:(?!,rtsps?://)[^\r\n])*)"
)
# Native services can log a stream as a percent-encoded query parameter.
# Hide the remainder of that line instead of trying to decode and re-encode it.
REGEX_XMEYE_ENCODED_AUTH_PATH = (
    r"(?i)(rtsps?%3a%2f%2f(?:(?!rtsps?%3a%2f%2f)[^\s])*?%2fuser%3d)[^\r\n]*"
)
# Only preserve a well-known, non-secret channel/stream suffix. Everything
# else, including unexpected parameters or unescaped whitespace, stays hidden.
REGEX_XMEYE_SAFE_SUFFIX = (
    r"(?i)([&_]channel=\d+[&_]stream=\d+(?:[&_]onvif=\d+)?"
    r"\.sdp(?:\?real_stream|\?)?)$"
)
REGEX_MASKED_CREDENTIAL = (
    rf"(?i)://\*:\*@|[?&]{_CREDENTIAL_QUERY_KEYS}=\*(?![^&\s])"
    r"|rtsps?://[^\s/?#]+:744[17]/\*(?=[/?#\s,]|$)"
    r"|rtsps?://[^\s/?#]+/(?:[^/\s?#]+/)*user=\*(?=[&_?]|$)"
)
REGEX_JSON = re.compile(r"^\s*\{")

# Preview Values

PREVIEW_FRAME_TYPE = "webp"

# Record Values

CACHE_SEGMENT_FORMAT = "%Y%m%d%H%M%S%z"
MAX_PRE_CAPTURE = 60
MAX_SEGMENT_DURATION = 600
MAX_SEGMENTS_IN_CACHE = 6
MAX_PLAYLIST_SECONDS = 7200  # support 2 hour segments for a single playlist to account for cameras with inconsistent segment times

# Internal Comms Topics

INSERT_MANY_RECORDINGS = "insert_many_recordings"
INSERT_PREVIEW = "insert_preview"
REQUEST_REGION_GRID = "request_region_grid"
UPSERT_REVIEW_SEGMENT = "upsert_review_segment"
CLEAR_ONGOING_REVIEW_SEGMENTS = "clear_ongoing_review_segments"
UPDATE_CAMERA_ACTIVITY = "update_camera_activity"
UPDATE_AUDIO_ACTIVITY = "update_audio_activity"
EXPIRE_AUDIO_ACTIVITY = "expire_audio_activity"
UPDATE_AUDIO_TRANSCRIPTION_STATE = "update_audio_transcription_state"
UPDATE_EVENT_DESCRIPTION = "update_event_description"
UPDATE_REVIEW_DESCRIPTION = "update_review_description"
UPDATE_MODEL_STATE = "update_model_state"
UPDATE_EMBEDDINGS_REINDEX_PROGRESS = "handle_embeddings_reindex_progress"
UPDATE_BIRDSEYE_LAYOUT = "update_birdseye_layout"
UPDATE_JOB_STATE = "update_job_state"
UPDATE_NOTICE = "update_notice"
NOTIFICATION_TEST = "notification_test"

# IO Nice Values

PROCESS_PRIORITY_HIGH = 0
PROCESS_PRIORITY_MED = 10
PROCESS_PRIORITY_LOW = 19

# Stats Values

FREQUENCY_STATS_POINTS = 15

# Autotracking

AUTOTRACKING_MAX_AREA_RATIO = 0.6
AUTOTRACKING_MOTION_MIN_DISTANCE = 20
AUTOTRACKING_MOTION_MAX_POINTS = 500
AUTOTRACKING_MAX_MOVE_METRICS = 500
AUTOTRACKING_ZOOM_OUT_HYSTERESIS = 1.1
AUTOTRACKING_ZOOM_IN_HYSTERESIS = 0.95
AUTOTRACKING_ZOOM_EDGE_THRESHOLD = 0.05

# Auth

#: Preferred name, then the pre-rename alias. Whichever is set first is used.
JWT_SECRET_ENV_VARS = ("GANNET_JWT_SECRET", "FRIGATE_JWT_SECRET")
JWT_SECRET_ENV_VAR = JWT_SECRET_ENV_VARS[0]
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"

# Queues

FAST_QUEUE_TIMEOUT = 0.00001  # seconds
