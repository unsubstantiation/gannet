"""Native Windows HLS generation for recorded video.

The ``/vod`` endpoints build playlists from recording rows in the database and
produce segments on demand with FFmpeg:

- a playlist covers the requested range so the player can seek without another
  metadata round trip;
- each recording file contributes an entry whose duration comes from the
  database;
- MPEG-TS segments are remuxed with ``-c copy`` on first request and cached.

No video is transcoded. If a camera records H.265, the browser must support it.
"""

import asyncio
import hashlib
import logging
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from frigate.const import CACHE_DIR
from frigate.models import Event, Recordings
from frigate.util.platform import resolve_ffmpeg_binary

logger = logging.getLogger(__name__)

# how long a generated playlist and its segments stay on disk. Scrubbing back
# and forth within this window is served from the cache.
VOD_CACHE_TTL = 3600

# the longest range a single playlist may cover. Frigate's own player asks for
# an hour at a time; anything larger is a sign of a bad request.
MAX_VOD_RANGE = 4 * 3600

# a segment shorter than this is not worth its own playlist entry
MIN_SEGMENT_DURATION = 0.5

# how long to wait for ffmpeg to remux one segment
SEGMENT_TIMEOUT = 60

# how long a remux that overran its budget gets to exit after being killed
SEGMENT_TERMINATE_TIMEOUT = 10

SEGMENT_PATTERN = re.compile(r"^seg-(\d{5})\.ts$")


@dataclass
class VodSegment:
    """One playlist entry, backed by a recording file."""

    index: int
    path: str
    start: float
    duration: float
    #: start time of the recording file itself, which a playlist entry that
    #: begins part way into a range is clipped forward from
    file_start: float

    @property
    def name(self) -> str:
        return f"seg-{self.index:05d}.ts"

    @property
    def end(self) -> float:
        return self.start + self.duration

    @property
    def offset(self) -> float:
        """Seconds into the recording file this entry starts at."""
        return max(self.start - self.file_start, 0.0)


@dataclass
class VodPlaylist:
    """A playable range of recordings."""

    camera: str
    stream_type: str
    start: float
    end: float
    segments: list[VodSegment]

    @property
    def key(self) -> str:
        """Stable name for the cache directory of this range."""
        raw = f"{self.camera}|{self.stream_type}|{self.start:.3f}|{self.end:.3f}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    @property
    def directory(self) -> str:
        return os.path.join(VOD_CACHE_ROOT, self.key)

    def m3u8(self) -> str:
        """Render the media playlist."""
        target = max(
            (round(segment.duration) + 1 for segment in self.segments), default=1
        )
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{max(target, 1)}",
            "#EXT-X-MEDIA-SEQUENCE:0",
            "#EXT-X-PLAYLIST-TYPE:VOD",
            "#EXT-X-INDEPENDENT-SEGMENTS",
        ]

        for segment in self.segments:
            lines.append(f"#EXTINF:{segment.duration:.3f},")
            lines.append(segment.name)

        lines.append("#EXT-X-ENDLIST")
        return "\n".join(lines) + "\n"

    def master_m3u8(self) -> str:
        """Render a one variant master playlist pointing at the media playlist.

        The variant URI is relative. HLS clients resolve it against the URL
        the master playlist was fetched from, so the media playlist always
        sits next to the master whatever path, prefix, or timestamp
        formatting the player used to ask for it. Rebuilding the absolute
        path here is what used to break playback: the ``start``/``end``
        numbers were re-rendered in a different notation to the one the
        routes accept, so the variant 404'd.

        ``BANDWIDTH`` is mandatory in a variant entry; recordings are a
        single quality so the value only needs to be plausible.
        """
        return (
            "#EXTM3U\n"
            "#EXT-X-VERSION:3\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=2000000\n"
            "index.m3u8\n"
        )


VOD_CACHE_ROOT = os.path.join(CACHE_DIR, "vod")


class VodUnavailable(Exception):
    """Raised when a range cannot be played."""


def _resolve_stream_type(camera: str, stream_type: str | None) -> str:
    """Normalize the stream type used in the request against what is recorded."""
    if stream_type in ("main", "sub"):
        return stream_type

    from frigate.const import STREAM_TYPE_MAIN

    return STREAM_TYPE_MAIN


def _recordings_for_range(
    camera: str, start: float, end: float, stream_type: str
) -> list[dict]:
    """Recording rows overlapping a range, oldest first."""
    query = (
        Recordings.select(
            Recordings.path,
            Recordings.start_time,
            Recordings.end_time,
            Recordings.stream_type,
        )
        .where(
            (Recordings.camera == camera)
            & (Recordings.end_time >= start)
            & (Recordings.start_time <= end)
        )
        .order_by(Recordings.start_time.asc())
        .dicts()
    )

    rows = []
    wanted = stream_type or "main"

    for row in query:
        # older rows predate the stream_type column and are main stream
        row_stream = row.get("stream_type") or "main"

        if wanted == "sub" and row_stream != "sub":
            continue

        if wanted == "main" and row_stream == "sub":
            # a main stream request must not silently mix in sub stream video
            continue

        rows.append(row)

    return rows


def build_playlist(
    camera: str, start: float, end: float, stream_type: str | None = None
) -> VodPlaylist:
    """Build the playlist for a camera over a time range.

    Raises:
        VodUnavailable: when the range is not usable or holds no recordings.
    """
    if end <= start:
        raise VodUnavailable("the end of the range must be after its start")

    if end - start > MAX_VOD_RANGE:
        raise VodUnavailable("the requested range is too large")

    resolved_stream = _resolve_stream_type(camera, stream_type)
    rows = _recordings_for_range(camera, start, end, resolved_stream)

    segments: list[VodSegment] = []
    index = 0

    for row in rows:
        file_start = float(row["start_time"])
        row_start = max(file_start, start)
        row_end = min(float(row["end_time"]), end)

        if row_end - row_start < MIN_SEGMENT_DURATION:
            continue

        path = row["path"]

        if not path or not os.path.isfile(path):
            logger.debug("Recording %s is missing from disk", path)
            continue

        segments.append(
            VodSegment(
                index=index,
                path=path,
                start=row_start,
                duration=row_end - row_start,
                file_start=file_start,
            )
        )
        index += 1

    if not segments:
        raise VodUnavailable("no recordings found for the requested range")

    return VodPlaylist(
        camera=camera,
        stream_type=resolved_stream,
        start=start,
        end=end,
        segments=segments,
    )


def playlist_for_event(
    event: Event, padding: int = 0, stream_type: str | None = None
) -> VodPlaylist:
    """Build the playlist covering a single event."""
    start = float(event.start_time) - padding
    end = float(event.end_time if event.end_time else event.start_time) + padding
    return build_playlist(
        event.camera, start, end, stream_type or getattr(event, "stream_type", None)
    )


def _sweep_cache() -> None:
    """Drop cache directories that have not been used recently."""
    if not os.path.isdir(VOD_CACHE_ROOT):
        return

    cutoff = time.time() - VOD_CACHE_TTL

    for entry in os.scandir(VOD_CACHE_ROOT):
        try:
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry.path, ignore_errors=True)
        except OSError:
            continue


async def _sweep_cache_periodically() -> None:
    while True:
        await asyncio.sleep(VOD_CACHE_TTL / 2)
        await asyncio.to_thread(_sweep_cache)


#: strong references to the sweep tasks this module starts. An event loop holds
#: only a weak reference to a task, so a task whose result is discarded can be
#: collected while it sleeps and the cache would never be swept again.
_SWEEP_TASKS: set[asyncio.Task] = set()


def start_cache_maintenance() -> asyncio.Task | None:
    """Start the background sweep of stale vod cache directories."""
    try:
        os.makedirs(VOD_CACHE_ROOT, exist_ok=True)
    except OSError as err:
        logger.warning("Unable to create the vod cache directory: %s", err)
        return None

    task = asyncio.create_task(_sweep_cache_periodically())
    _SWEEP_TASKS.add(task)
    task.add_done_callback(_SWEEP_TASKS.discard)
    return task


def _refresh(path: str) -> None:
    """Record that a cached path is still in use."""
    try:
        os.utime(path, None)
    except OSError:
        pass


def _discard(path: str) -> None:
    """Remove a partial file, which is never a reason to fail a request."""
    try:
        os.unlink(path)
    except OSError:
        pass


async def _terminate(process: Any) -> None:
    """Stop an ffmpeg that outlived its remux budget."""
    if process.returncode is not None:
        return

    try:
        process.kill()
    except (ProcessLookupError, OSError) as err:
        logger.debug("Unable to kill the ffmpeg remux: %s", err)
        return

    try:
        await asyncio.wait_for(process.wait(), SEGMENT_TERMINATE_TIMEOUT)
    except TimeoutError:
        logger.warning("ffmpeg did not exit after being killed")


async def render_segment(playlist: VodPlaylist, segment: VodSegment) -> str | None:
    """Remux one playlist entry into an MPEG-TS file, returning its path.

    The file is written next to the playlist and reused on later requests. It is
    remuxed under a temporary name and moved into place only when ffmpeg
    finished: a cached segment is served without being checked again, so a file
    left half written by a timeout or a failure would stay broken until the
    whole cache directory expired.
    """
    try:
        os.makedirs(playlist.directory, exist_ok=True)
    except OSError as err:
        logger.warning(
            "Unable to create the vod cache directory %s: %s",
            playlist.directory,
            err,
        )
        return None

    output = os.path.join(playlist.directory, segment.name)

    if os.path.isfile(output) and os.path.getsize(output) > 0:
        _refresh(output)
        # the sweep expires whole directories by their own modification time,
        # which re-serving a segment inside one does not update
        _refresh(playlist.directory)
        return output

    # cut relative to the start of the recording file, so the first frame is
    # the keyframe at or before the requested position
    offset = segment.offset
    temporary = f"{output}.{uuid.uuid4().hex}.part"

    command = [
        resolve_ffmpeg_binary("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        # seek before -i so ffmpeg jumps instead of decoding up to the offset
        "-ss",
        f"{offset:.3f}",
        "-i",
        segment.path,
        "-t",
        f"{segment.duration:.3f}",
        "-c",
        "copy",
        # no explicit bitstream filter: the mpegts muxer inserts the matching
        # mp4toannexb filter for H.264 and HEVC itself. Forcing
        # h264_mp4toannexb here made ffmpeg refuse every HEVC recording.
        "-f",
        "mpegts",
        "-y",
        temporary,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.error("ffmpeg was not found, unable to serve recordings")
        return None
    except OSError as err:
        logger.warning("Unable to start ffmpeg to remux %s: %s", segment.path, err)
        return None

    try:
        _, stderr = await asyncio.wait_for(process.communicate(), SEGMENT_TIMEOUT)
    except TimeoutError:
        logger.warning("Timed out remuxing %s", segment.path)
        # a remux left running keeps the recording file open, which on Windows
        # is what stops the recording maintainer from moving it
        await _terminate(process)
        _discard(temporary)
        return None

    if process.returncode != 0:
        logger.warning(
            "ffmpeg failed to remux %s: %s",
            segment.path,
            stderr.decode(errors="replace").strip() if stderr else "no output",
        )
        _discard(temporary)
        return None

    if not os.path.isfile(temporary) or os.path.getsize(temporary) == 0:
        logger.warning("ffmpeg produced no data for %s", segment.path)
        _discard(temporary)
        return None

    try:
        os.replace(temporary, output)
    except OSError as err:
        logger.warning("Unable to move the remuxed segment into place: %s", err)
        _discard(temporary)
        return None

    return output


def parse_segment_name(name: str) -> int | None:
    """Extract the playlist entry index from a segment file name."""
    match = SEGMENT_PATTERN.match(name)

    if match is None:
        return None

    return int(match.group(1))


def find_segment(playlist: VodPlaylist, name: str) -> VodSegment | None:
    """Look up the playlist entry a segment file name refers to."""
    index = parse_segment_name(name)

    if index is None or index >= len(playlist.segments):
        return None

    return playlist.segments[index]


def vod_unavailable_response(reason: str) -> JSONResponse:
    """Response used when a range cannot be played."""
    return JSONResponse(content={"success": False, "message": reason}, status_code=404)


def playlist_response(playlist: VodPlaylist) -> Response:
    """Media playlist response."""
    return PlainTextResponse(
        playlist.m3u8(),
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


def segment_response(path: str) -> Response:
    """Segment response, with range support so a player can resume a fetch."""
    return FileResponse(
        path,
        media_type="video/mp2t",
        headers={"Cache-Control": "no-store"},
    )


def hour_range(
    year_month: str, day: int, hour: int, tz_name: str | None
) -> tuple[float, float] | None:
    """Convert the year/hour form of the vod endpoints into a timestamp range."""
    from zoneinfo import ZoneInfo

    from frigate.util.time import get_normalized_tz_name

    parts = year_month.split("-")

    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None

    try:
        tz = (
            ZoneInfo(get_normalized_tz_name(tz_name.replace(",", "/")))
            if tz_name
            else UTC
        )
    except Exception:
        tz = UTC

    try:
        # the hour is local to the requested zone, so build it there and let
        # the zone supply the offset in force at that moment. Subtracting the
        # zone's *current* offset instead returned the wrong hour for any day
        # on the other side of a daylight saving change.
        start_date = datetime(int(parts[0]), int(parts[1]), day, hour, tzinfo=tz)
    except (ValueError, TypeError):
        return None

    # one real hour of recordings, worked out on the timeline rather than the
    # wall clock so a range that straddles a daylight saving change is still
    # sixty minutes long
    start = start_date.timestamp()
    return start, start + timedelta(hours=1).total_seconds() - 0.001
