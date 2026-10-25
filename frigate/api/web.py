# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Native Windows HTTP gateway for the UI, API, media, and live streams.

The public listener serves the React application, authenticates protected
requests in process, exposes static media, creates recorded-video HLS, and
forwards websocket/live traffic to Frigate and go2rtc. A second listener on
``127.0.0.1`` serves trusted media requests from Frigate's own FFmpeg jobs.

Authentication runs directly against :func:`frigate.api.auth.auth`, avoiding a
loopback request and preserving the API app's configuration and database state.
"""

import asyncio
import logging
import os
import secrets
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import aiohttp
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

from frigate.api import vod_native
from frigate.api.auth import auth as auth_check
from frigate.const import CLIPS_DIR, EXPORT_DIR, RECORD_DIR
from frigate.models import Event
from frigate.util.platform import (
    get_web_dir,
    get_web_host,
    get_web_port,
    web_dir_has_build,
)
from frigate.util.tls import ensure_tls_certificate

logger = logging.getLogger(__name__)

# Native child services reached through loopback.
MQTT_WS_URL = "http://127.0.0.1:5002"
JSMEPEG_URL = "http://127.0.0.1:8082"
GO2RTC_URL = "http://127.0.0.1:1984"

# Protected gateway prefixes. The web-app shell is public so the login route can
# render. go2rtc's API reports camera URLs containing credentials, so it must
# never answer anonymously.
PROTECTED_PREFIXES = (
    "/api/",
    "/vod/",
    "/clips/",
    "/recordings/",
    "/exports/",
    # nothing is mounted at /cache any more; it stays protected so a future
    # mount cannot be reached without signing in
    "/cache/",
    "/live/",
    "/go2rtc/",
)

PROTECTED_EXACT = ("/api", "/ws")

# The login flow must work before a session exists.
AUTH_EXEMPT = (
    "/api/login",
    "/api/logout",
    "/api/auth/first_time_login",
)

PLAYERS = ("mse", "webrtc", "jsmpeg")

# headers a client may not set, because Frigate uses them to carry its own
# authentication decision
FORWARDED_REQUEST_HEADERS = (
    b"authorization",
    b"cookie",
    b"x-csrf-token",
    b"x-forwarded-for",
)


def needs_auth(path: str) -> bool:
    """Whether the native gateway must authenticate a path."""
    # the login flow has to work before a session exists, so the exemptions
    # are checked first: every exempt path also starts with a protected
    # prefix, and checking the prefixes first would make them unreachable
    if path in AUTH_EXEMPT:
        return False

    # a protected exact path is always authenticated on its own; a subpath
    # also requires auth, but only when it is actually below it (the path
    # either is the root or starts with the root followed by a slash).
    if path in PROTECTED_EXACT:
        return True

    return any(
        path == root or path.startswith(f"{root}/") for root in PROTECTED_EXACT
    ) or path.startswith(PROTECTED_PREFIXES)


# ---------------------------------------------------------------------------
# in process auth
# ---------------------------------------------------------------------------


def _request_header(scope: dict, name: bytes) -> str | None:
    """Return the first value of a request header, decoded."""
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")

    return None


def build_auth_scope(scope: dict, port: int) -> dict:
    """Build the scope the local auth check runs against.

    Preserve the original method and URL, listener port, credentials, and CSRF
    marker. Only explicitly allowed request headers reach the auth endpoint, so
    a caller cannot inject a trusted ``Remote-Role`` value. The origin inputs
    are derived the same way the container's nginx proxy derives them, and the
    forwarded scheme comes from the listener the request actually arrived on,
    never from a client header.
    """
    headers = [
        (key, value)
        for key, value in scope.get("headers", [])
        if key.lower() in FORWARDED_REQUEST_HEADERS
    ]

    scheme = scope.get("scheme", "http")
    host = _request_header(scope, b"host") or ""

    raw_path = scope.get("raw_path") or scope.get("path", "").encode("latin-1")
    query = scope.get("query_string", b"")
    original_url = f"{scheme}://{host}{raw_path.decode('latin-1')}"

    if query:
        original_url = f"{original_url}?{query.decode('latin-1')}"

    headers.append((b"x-original-method", scope.get("method", "GET").encode()))
    headers.append((b"x-original-url", original_url.encode("latin-1")))
    headers.append((b"x-server-port", str(port).encode()))
    headers.append((b"x-csrf-token", b"1"))

    # inputs for the cross-origin check on websocket and go2rtc stream requests.
    # nginx sets X-Forwarded-Host to the outer proxy's value when there is one
    # and to the request Host otherwise, so mirror that instead of trusting a
    # client value for the check.
    forwarded_host = _request_header(scope, b"x-forwarded-host")
    headers.append((b"x-original-host", host.encode("latin-1")))
    headers.append((b"x-forwarded-host", (forwarded_host or host).encode("latin-1")))

    if origin := _request_header(scope, b"origin"):
        headers.append((b"origin", origin.encode("latin-1")))

    if upgrade := _request_header(scope, b"upgrade"):
        headers.append((b"x-original-upgrade", upgrade.encode("latin-1")))

    # nginx passes its own scheme, which is what makes the Secure cookie flag
    # correct behind its TLS listener without any client-supplied value
    headers.append((b"x-forwarded-proto", scheme.encode("latin-1")))

    return {
        "type": "http",
        "http_version": "1.1",
        "method": scope.get("method", "GET"),
        "scheme": scheme,
        "path": "/auth",
        "raw_path": b"/auth",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": scope.get("client") or ("127.0.0.1", 0),
        "server": scope.get("server") or ("127.0.0.1", port),
    }


class InProcessAuth:
    """Runs the auth endpoint without an HTTP round trip."""

    def __init__(self, api_app: Any) -> None:
        self.api_app = api_app

    async def __call__(
        self, scope: dict, port: int
    ) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
        auth_scope = build_auth_scope(scope, port)
        auth_scope["app"] = self.api_app

        proxy = self.api_app.frigate_config.proxy
        configured_secret = str(proxy.auth_secret or "")
        incoming_headers = {
            key.lower(): value for key, value in scope.get("headers", [])
        }
        supplied_secret = incoming_headers.get(b"x-proxy-secret", b"").decode("latin-1")

        mapped_identity_enabled = not self.api_app.frigate_config.auth.enabled and bool(
            proxy.header_map.user or proxy.header_map.role
        )
        secret_matches = bool(configured_secret) and secrets.compare_digest(
            supplied_secret, configured_secret
        )

        # With native authentication disabled, a configured upstream identity
        # is the security boundary. Fail closed unless the caller proves it is
        # the proxy; otherwise proxy.default_role could accidentally authorize
        # a direct client even though its forged identity headers were stripped.
        if mapped_identity_enabled and not secret_matches:
            return 401, [], b""

        # The gateway presents the configured value to the in-process auth
        # endpoint. Mapped identity headers are copied only after the caller
        # proved it knows that same value.
        if configured_secret:
            auth_scope["headers"].append(
                (b"x-proxy-secret", configured_secret.encode("utf-8"))
            )

            if secret_matches:
                mapped_headers = {
                    name.casefold().encode("latin-1")
                    for name in (proxy.header_map.user, proxy.header_map.role)
                    if name
                }
                auth_scope["headers"].extend(
                    (key, value)
                    for key, value in scope.get("headers", [])
                    if key.lower() in mapped_headers
                )

        started = False
        status = 500
        headers: list[tuple[bytes, bytes]] = []
        body = bytearray()

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            nonlocal started, status, headers

            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                headers = message.get("headers", [])
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))

        try:
            # the auth endpoint is a sync function, so it is called through the
            # same starlette request machinery a real request would use
            response = await asyncio.to_thread(auth_check, Request(auth_scope))

            if isinstance(response, Response):
                return response.status_code, response.raw_headers, response.body
        except Exception as err:  # pragma: no cover - defensive
            logger.exception("Authentication check failed: %s", err)

        if started:  # pragma: no cover - the auth endpoint returns a response
            return status, headers, bytes(body)

        return 500, [], b""


class NativeAuthMiddleware:
    """Authenticate requests and inject trusted identity headers.

    A pure ASGI middleware rather than a ``BaseHTTPMiddleware`` because
    websockets need the same treatment: ``BaseHTTPMiddleware`` passes websocket
    scopes through untouched, which would leave ``/ws`` and the live view
    unauthenticated.
    """

    def __init__(self, app: Any, api_app: Any, port: int) -> None:
        self.app = app
        self.port = port
        self.auth = InProcessAuth(api_app)

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        if not needs_auth(path):
            scope = dict(scope)
            scope["headers"] = self._strip_proxy_headers(scope)
            await self.app(scope, receive, send)
            return

        status, headers, payload = await self.auth(scope, self.port)

        if status >= 300:
            await self._deny(scope, status, headers, payload, receive, send)
            return

        scope = dict(scope)
        scope["headers"] = self._injected(headers) + self._strip_proxy_headers(scope)

        await self.app(
            scope,
            receive,
            self._send_with_cookies(send, self._response_cookies(headers)),
        )

    @staticmethod
    def _response_cookies(
        headers: list[tuple[bytes, bytes]],
    ) -> list[tuple[bytes, bytes]]:
        """Cookies set by a successful auth check, notably a refreshed JWT."""
        return [(key, value) for key, value in headers if key.lower() == b"set-cookie"]

    @staticmethod
    def _send_with_cookies(send: Any, cookies: list[tuple[bytes, bytes]]) -> Any:
        """Attach auth-check cookies to the downstream HTTP response.

        The in-process equivalent of nginx's ``auth_request_set`` copying:
        without it, ``/auth`` can refresh an expiring session cookie but the
        browser never receives the replacement and is logged out anyway.
        """
        if not cookies:
            return send

        async def send_with_cookies(message: dict) -> None:
            if message["type"] == "http.response.start":
                message = dict(message)
                # Auth ran before the endpoint, so its cookies come first: a
                # cookie the endpoint sets itself (for example after changing
                # a password) must win over a merely refreshed session token.
                message["headers"] = cookies + list(message.get("headers", []))

            await send(message)

        return send_with_cookies

    @staticmethod
    def _injected(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
        """Copy the identity established by the in-process auth check."""
        wanted = (
            b"remote-user",
            b"remote-role",
            b"remote-groups",
            b"remote-email",
            b"remote-name",
        )

        return [(key, value) for key, value in headers if key.lower() in wanted]

    @staticmethod
    def _strip_proxy_headers(scope: dict) -> list[tuple[bytes, bytes]]:
        """Drop client-supplied identity headers and proxy credentials.

        ``x-server-port``, ``x-original-url``, ``x-original-method``,
        ``x-original-host`` and ``x-original-upgrade`` are how the gateway tells
        the auth endpoint which listener a request arrived on and what it was
        really for. A client that could set them itself could claim the loopback
        listener, so they are removed from what reaches the API application along
        with the identity headers.
        """
        dropped = (
            b"x-proxy-secret",
            b"x-server-port",
            b"x-original-url",
            b"x-original-method",
            b"x-original-host",
            b"x-original-upgrade",
        )

        return [
            (key, value)
            for key, value in scope.get("headers", [])
            if not key.lower().startswith(b"remote-") and key.lower() not in dropped
        ]

    async def _deny(
        self,
        scope: dict,
        status: int,
        headers: list[tuple[bytes, bytes]],
        payload: bytes,
        receive: Any,
        send: Any,
    ) -> None:
        if scope["type"] == "websocket":
            # a websocket handshake cannot carry a status code, and the
            # websocket clients expect to reconnect rather than to be told why
            await send({"type": "websocket.close", "code": 1008})
            return

        response = Response(payload, status_code=status)

        for key, value in headers:
            if key.lower() in (b"location", b"set-cookie", b"content-type"):
                response.raw_headers.append((key, value))

        await response(scope, receive, send)


# ---------------------------------------------------------------------------
# static files
# ---------------------------------------------------------------------------


def is_contained_in(path: str, directory: str) -> bool:
    """Containment check that survives symlinks pointing outside a root.

    The comparison is case insensitive where the platform is, because Windows
    resolves a path that differs only in letter case to the same file.
    """
    resolved = os.path.realpath(path)
    root = os.path.realpath(directory)

    try:
        common = os.path.commonpath([resolved, root])
    except ValueError:
        # different Windows drives, so the paths are not comparable
        return False

    return os.path.normcase(common) == os.path.normcase(root)


class SpaFiles:
    """Serve static assets with an ``index.html`` client-route fallback."""

    def __init__(self, directory: str) -> None:
        self.directory = directory
        self.static = StaticFiles(directory=directory, html=True, check_dir=False)

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.static(scope, receive, send)
            return

        path = scope.get("path", "/")
        candidate = self._candidate(path)

        if candidate is not None:
            response = FileResponse(candidate)

            # hashed asset names are safe to cache forever, the shell is not
            if path.startswith("/assets/"):
                response.headers["Cache-Control"] = "public, max-age=31536000"
            else:
                response.headers["Cache-Control"] = "no-store"

            await response(scope, receive, send)
            return

        index = os.path.join(self.directory, "index.html")

        if not os.path.isfile(index):
            await PlainTextResponse(
                "The Frigate web app is not built. Run 'npm install' and "
                "'npm run build' in the web directory to create it.",
                status_code=503,
            )(scope, receive, send)
            return

        await FileResponse(index, headers={"Cache-Control": "no-store"})(
            scope, receive, send
        )

    def _candidate(self, path: str) -> str | None:
        """Resolve a request path to a file the way ``try_files`` does."""
        relative = path.replace("\\", "/").lstrip("/")

        if not relative or ".." in relative.split("/"):
            return None

        direct = os.path.join(self.directory, relative)

        for candidate in (direct, f"{direct}.html"):
            if os.path.isfile(candidate) and is_contained_in(candidate, self.directory):
                return candidate

        if os.path.isdir(direct) and is_contained_in(direct, self.directory):
            index = os.path.join(direct, "index.html")

            if os.path.isfile(index):
                return index

        return None


# ---------------------------------------------------------------------------
# vod
# ---------------------------------------------------------------------------


def _playlist_or_error(
    camera: str, start: float, end: float, stream: str | None
) -> vod_native.VodPlaylist | Response:
    """Build a playlist, or the response explaining why it cannot be built."""
    if end <= start:
        return vod_native.vod_unavailable_response(
            "the end of the range must be after its start"
        )

    try:
        return vod_native.build_playlist(camera, start, end, _stream_preference(stream))
    except vod_native.VodUnavailable as err:
        return vod_native.vod_unavailable_response(str(err))


def _stream_preference(stream: str | None) -> str | None:
    """Only main and sub name a recorded stream."""
    if stream in ("main", "sub"):
        return stream

    return None


def _media_playlist(
    camera: str, start: float, end: float, stream: str | None
) -> Response:
    playlist = _playlist_or_error(camera, start, end, stream)

    if isinstance(playlist, Response):
        return playlist

    return vod_native.playlist_response(playlist)


def _master_playlist(
    camera: str, start: float, end: float, stream: str | None
) -> Response:
    """A one variant master whose media playlist is the sibling ``index.m3u8``.

    The variant URI is relative, so whatever route shape the player used to
    fetch the master (``/vod/{camera}/...``, ``/vod/clip/...``, with or
    without a stream name) resolves to the matching ``index.m3u8`` beside it.
    """
    playlist = _playlist_or_error(camera, start, end, stream)

    if isinstance(playlist, Response):
        return playlist

    return PlainTextResponse(
        playlist.master_m3u8(),
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


#: the ``{playlist}`` route parameter names the file without its ``.m3u8``
#: suffix, which the route pattern matches separately
MASTER_PLAYLIST = "master"


async def vod_playlist(request: Request) -> Response:
    """``/vod/{camera}[/{stream}]/start/{start}/end/{end}/{index,master}.m3u8``.

    The player asks for both names: ``master.m3u8`` when it wants a variant
    playlist to select from, ``index.m3u8`` when it wants the media playlist
    directly.
    """
    camera = request.path_params["camera"]
    start = float(request.path_params["start"])
    end = float(request.path_params["end"])
    stream = request.path_params.get("stream")

    if request.path_params["playlist"] == MASTER_PLAYLIST:
        return _master_playlist(camera, start, end, stream)

    return _media_playlist(camera, start, end, stream)


async def vod_clip(request: Request) -> Response:
    """``/vod/clip/{camera}/start/{start}/end/{end}/{index,master}.m3u8``.

    The tracked-object player uses this route shape. Native playlists use real
    segment boundaries and therefore do not need synthetic discontinuities.
    """
    camera = request.path_params["camera"]
    start = float(request.path_params["start"])
    end = float(request.path_params["end"])

    if request.path_params["playlist"] == MASTER_PLAYLIST:
        return _master_playlist(camera, start, end, None)

    return _media_playlist(camera, start, end, None)


async def vod_event(request: Request) -> Response:
    """``/vod/event/{event_id}/start/{start}/end/{end}/{index,master}.m3u8``."""
    event_id = request.path_params["event_id"]
    start = float(request.path_params["start"])
    end = float(request.path_params["end"])

    try:
        event = await asyncio.to_thread(Event.get, Event.id == event_id)
    except Event.DoesNotExist:
        return Response(status_code=404)

    if request.path_params["playlist"] == MASTER_PLAYLIST:
        return _master_playlist(event.camera, start, end, None)

    return _media_playlist(event.camera, start, end, None)


async def vod_hour(request: Request) -> Response:
    """``/vod/{year_month}/{day}/{hour}/{camera}[/{tz}]/index.m3u8``."""
    camera = request.path_params["camera"]
    time_range = vod_native.hour_range(
        request.path_params["year_month"],
        int(request.path_params["day"]),
        int(request.path_params["hour"]),
        request.path_params.get("tz"),
    )

    if time_range is None:
        return vod_native.vod_unavailable_response("invalid date")

    return _media_playlist(camera, time_range[0], time_range[1], None)


async def vod_segment(request: Request) -> Response:
    """``/vod/{camera}[/{stream}]/start/{start}/end/{end}/{segment}.ts``."""
    camera = request.path_params["camera"]
    start = float(request.path_params["start"])
    end = float(request.path_params["end"])
    stream = request.path_params.get("stream")
    name = request.path_params["segment"]

    playlist = _playlist_or_error(camera, start, end, stream)

    if isinstance(playlist, Response):
        return playlist

    segment = vod_native.find_segment(playlist, name)

    if segment is None:
        return Response(status_code=404)

    path = await vod_native.render_segment(playlist, segment)

    if path is None:
        return Response(status_code=500)

    return vod_native.segment_response(path)


def vod_routes() -> list[Route]:
    """Return the VOD routes consumed by the web player."""
    return [
        Route(
            "/clip/{camera}/start/{start:float}/end/{end:float}/{playlist}.m3u8",
            vod_clip,
        ),
        Route(
            "/event/{event_id}/start/{start:float}/end/{end:float}/{playlist}.m3u8",
            vod_event,
        ),
        Route(
            "/{year_month}/{day:int}/{hour:int}/{camera}/{tz}/{playlist}.m3u8",
            vod_hour,
        ),
        Route(
            "/{year_month}/{day:int}/{hour:int}/{camera}/{playlist}.m3u8",
            vod_hour,
        ),
        Route(
            "/{camera}/stream/{stream}/start/{start:float}/end/{end:float}/{segment}.ts",
            vod_segment,
        ),
        Route(
            "/{camera}/start/{start:float}/end/{end:float}/{segment}.ts",
            vod_segment,
        ),
        Route(
            "/{camera}/{stream}/start/{start:float}/end/{end:float}/{playlist}.m3u8",
            vod_playlist,
        ),
        Route(
            "/{camera}/start/{start:float}/end/{end:float}/{playlist}.m3u8",
            vod_playlist,
        ),
    ]


# ---------------------------------------------------------------------------
# proxies
# ---------------------------------------------------------------------------


def upstream_for(path: str) -> tuple[str, str] | None:
    """Map a live request path onto its loopback child service."""
    if path == "/ws":
        return MQTT_WS_URL, "/"

    if path.startswith("/live/jsmpeg/"):
        # Frigate's own jsmpeg websocket server, started by the output process
        # (see frigate/output/output.py). go2rtc does not serve jsmpeg, so a
        # camera that is not restreamed has no live view through go2rtc.
        return JSMEPEG_URL, path[len("/live/jsmpeg") :]

    if path.startswith("/live/mse/"):
        return GO2RTC_URL, path[len("/live/mse") :]

    if path.startswith("/live/webrtc/"):
        remainder = path[len("/live/webrtc") :]

        if remainder.startswith("/api/") or remainder == "/webrtc.html":
            return GO2RTC_URL, remainder

        return GO2RTC_URL, f"/{PLAYERS[1]}{remainder}"

    if path.startswith("/go2rtc/"):
        return GO2RTC_URL, path[len("/go2rtc") :]

    if path == "/api/go2rtc/webrtc":
        return GO2RTC_URL, "/api/webrtc"

    return None


async def websocket_endpoint(scope: dict, receive: Any, send: Any) -> None:
    """Bridge a browser websocket to the upstream websocket server."""
    upstream = upstream_for(scope.get("path", ""))

    if upstream is None:
        await send({"type": "websocket.close", "code": 1000})
        return

    url = f"{upstream[0]}{upstream[1]}"
    query = scope.get("query_string", b"").decode("latin-1")

    if query:
        url = f"{url}?{query}"

    accepted = False
    session = aiohttp.ClientSession()

    try:
        async with session.ws_connect(
            url.replace("http://", "ws://"),
            headers=_forwarded_headers(scope, websocket=True),
            heartbeat=None,
            max_msg_size=0,
        ) as upstream_ws:
            await send({"type": "websocket.accept"})
            accepted = True

            browser_to_upstream = asyncio.create_task(
                _pump_browser(receive, upstream_ws)
            )
            upstream_to_browser = asyncio.create_task(_pump_upstream(upstream_ws, send))

            done, pending = await asyncio.wait(
                (browser_to_upstream, upstream_to_browser),
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
    except Exception as err:
        logger.debug("Websocket proxy to %s failed: %s", url, err)
    finally:
        await session.close()

        try:
            await send({"type": "websocket.close", "code": 1000 if accepted else 1011})
        except Exception:
            # the client may already be gone, which is not an error
            pass


async def _pump_browser(receive: Any, upstream_ws: Any) -> None:
    """Forward browser messages to the upstream server."""
    while True:
        message = await receive()

        if message["type"] == "websocket.disconnect":
            return

        if message["type"] != "websocket.receive":
            continue

        if message.get("text") is not None:
            await upstream_ws.send_str(message["text"])
        elif message.get("bytes") is not None:
            await upstream_ws.send_bytes(message["bytes"])


async def _pump_upstream(upstream_ws: Any, send: Any) -> None:
    """Forward upstream messages to the browser."""
    async for message in upstream_ws:
        if message.type == aiohttp.WSMsgType.TEXT:
            await send({"type": "websocket.send", "text": message.data})
        elif message.type == aiohttp.WSMsgType.BINARY:
            await send({"type": "websocket.send", "bytes": message.data})
        elif message.type in (
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSING,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.ERROR,
        ):
            return


async def proxy_http(request: Request) -> Response:
    """Proxy a plain HTTP request upstream, which only go2rtc needs."""
    upstream = upstream_for(request.url.path)

    if upstream is None:
        return Response(status_code=404)

    url = f"{upstream[0]}{upstream[1]}"

    if request.url.query:
        url = f"{url}?{request.url.query}"

    body = await request.body()
    session = aiohttp.ClientSession()

    try:
        async with session.request(
            request.method,
            url,
            data=body if body else None,
            headers=_forwarded_headers(request.scope),
        ) as upstream_response:
            content = await upstream_response.read()
            headers = {
                key: value
                for key, value in upstream_response.headers.items()
                if key.lower()
                not in (
                    "content-encoding",
                    "content-length",
                    "transfer-encoding",
                    "connection",
                )
            }

            return Response(
                content,
                # aiohttp reports the code as ``status``; ``status_code`` is the
                # Starlette name, and reading it here raised AttributeError
                # for every proxied request, which broke WebRTC signalling
                status_code=upstream_response.status,
                headers=headers,
                media_type=upstream_response.headers.get("Content-Type"),
            )
    except aiohttp.ClientError as err:
        logger.debug("Proxy to %s failed: %s", url, err)
        return Response(status_code=502)
    finally:
        await session.close()


def _forwarded_headers(scope: dict, websocket: bool = False) -> dict[str, str]:
    """Request headers to forward upstream."""
    skipped = {"host", "content-length"}

    if websocket:
        skipped |= {
            "connection",
            "upgrade",
            "sec-websocket-key",
            "sec-websocket-version",
            "sec-websocket-extensions",
        }

    return {
        key.decode("latin-1"): value.decode("latin-1")
        for key, value in scope.get("headers", [])
        if key.decode("latin-1").lower() not in skipped
    }


# ---------------------------------------------------------------------------
# app
# ---------------------------------------------------------------------------


async def _startup() -> None:
    """Start the background work the native server needs."""
    # stale vod cache directories are swept while the server runs. The sweep
    # keeps its own strong reference to the task it creates.
    vod_native.start_cache_maintenance()


def _lifespan_for(api_app: Any) -> Any:
    """Build the gateway lifespan, which also runs the mounted API's lifespan.

    Starlette only drives the lifespan of the outermost application. The
    FastAPI app is mounted under ``/api`` here, so its own lifespan (which
    starts the debug replay auto-stop watchdog) would otherwise never be
    entered on a native install, even though it runs when FastAPI is served
    directly.
    """

    @asynccontextmanager
    async def _lifespan(app: Starlette) -> AsyncIterator[Mapping[str, Any] | None]:
        await _startup()

        if not isinstance(api_app, Starlette):
            yield None
            return

        async with api_app.router.lifespan_context(api_app) as api_state:
            yield api_state if isinstance(api_state, Mapping) else None

    return _lifespan


def create_native_web_app(api_app: Any, port: int) -> Starlette:
    """Build the native Windows gateway application.

    Args:
        api_app: the app from :func:`frigate.api.fastapi_app.create_fastapi_app`
        port: the port the server is bound to, which the auth check reports as
            the port the client connected to
    """
    web_dir = get_web_dir()

    if not web_dir_has_build():
        logger.warning(
            "No built web app found in %s. The web interface will not load "
            "until 'npm install' and 'npm run build' have been run in the web "
            "directory.",
            web_dir,
        )

    routes = [
        # go2rtc handles WebRTC signalling; Frigate handles every other API path
        Route("/api/go2rtc/webrtc", proxy_http, methods=["POST", "OPTIONS"]),
        Mount("/api", app=api_app),
        # Recorded video is packaged into HLS by the native VOD implementation.
        Mount("/vod", app=Starlette(routes=vod_routes())),
        # media directories
        Mount("/clips", app=StaticFiles(directory=CLIPS_DIR, check_dir=False)),
        Mount("/recordings", app=StaticFiles(directory=RECORD_DIR, check_dir=False)),
        Mount("/exports", app=StaticFiles(directory=EXPORT_DIR, check_dir=False)),
        # CACHE_DIR is deliberately not served. It holds in-progress recording
        # segments, preview frames, and VOD remux output for every camera, and
        # nothing in the web app reads it over HTTP; exposing it would let any
        # signed-in viewer bypass the per-camera media checks.
        # live view and the websocket servers
        Route("/live/webrtc/webrtc.html", proxy_http, methods=["GET"]),
        WebSocketRoute("/ws", websocket_endpoint),
        WebSocketRoute("/live/jsmpeg/{path:path}", websocket_endpoint),
        WebSocketRoute("/live/mse/{path:path}", websocket_endpoint),
        WebSocketRoute("/live/webrtc/{path:path}", websocket_endpoint),
        Route("/go2rtc/{path:path}", proxy_http, methods=["GET", "POST", "OPTIONS"]),
        # the web app
        Mount("/", app=SpaFiles(web_dir)),
    ]

    app = Starlette(routes=routes, lifespan=_lifespan_for(api_app))
    app.add_middleware(NativeAuthMiddleware, api_app=api_app, port=port)
    return app


async def _watch_stop_event(servers: list, stop_event: Any) -> None:
    """Ask every listener to stop when Frigate's process event is set."""
    while not stop_event.is_set():
        await asyncio.sleep(0.1)

    for server in servers:
        server.should_exit = True


async def _serve(servers: list, stop_event: Any | None = None) -> None:
    """Run listeners until one exits or the process stop event is set."""
    server_tasks = [asyncio.create_task(server.serve()) for server in servers]
    stop_watcher = None

    if stop_event is not None:
        stop_watcher = asyncio.create_task(_watch_stop_event(servers, stop_event))

    try:
        wait_for = set(server_tasks)
        if stop_watcher is not None:
            wait_for.add(stop_watcher)

        # A Uvicorn listener exits on Ctrl+C, or when its startup fails. Other
        # listeners must be asked to stop too, otherwise gather waits forever.
        await asyncio.wait(wait_for, return_when=asyncio.FIRST_COMPLETED)

        for server in servers:
            server.should_exit = True

        errors: list[BaseException] = []
        for task in server_tasks:
            if task.done() and not task.cancelled():
                error = task.exception()
                if error is not None:
                    errors.append(error)

        await asyncio.gather(*server_tasks, return_exceptions=True)

        if errors:
            raise errors[0]
    finally:
        if stop_watcher is not None:
            stop_watcher.cancel()
            await asyncio.gather(stop_watcher, return_exceptions=True)

        for task in server_tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(*server_tasks, return_exceptions=True)


def run_native_web_server(
    api_app: Any,
    internal_port: int,
    public_port: int,
    stop_event: Any | None = None,
    *,
    ipv6_enabled: bool = False,
    public_host: str | None = None,
    tls_enabled: bool = False,
    tls_cert_file: str | None = None,
    tls_key_file: str | None = None,
) -> None:
    """Serve the authenticated public gateway and trusted loopback listener.

    Two things have to be reachable at once:

    - the authenticated web interface, on ``FRIGATE_WEB_HOST`` and the port
      from ``FRIGATE_WEB_PORT``, which defaults to the configured public port;
      ``networking.ipv6`` decides which wildcard address is bound when
      ``FRIGATE_WEB_HOST`` does not name one, a ``host:port`` value in
      ``networking.listen.external`` ``public_host`` names one when the
      environment does not, and TLS is applied to this listener when enabled
    - the internal port itself, on loopback, because Frigate's own consumers
      (export, motion search, debug replay) fetch VOD playlists from it with
      FFmpeg and cannot authenticate

    The internal listener is loopback-only, plain HTTP, and bypasses
    authentication for Frigate's own media jobs. The public listener is
    authenticated by default.
    """
    import uvicorn

    # FRIGATE_WEB_HOST is the explicit override, so it wins over the address
    # named by networking.listen.external
    host = get_web_host(ipv6_enabled, public_host)
    port = get_web_port(public_port)

    if port == internal_port:
        raise ValueError(
            "The public and internal listeners must use different ports; "
            "change FRIGATE_WEB_PORT or networking.listen.internal."
        )

    tls_options: dict[str, str] = {}
    scheme = "http"

    if tls_enabled:
        if not tls_cert_file or not tls_key_file:
            raise ValueError("TLS is enabled but certificate paths are not configured")

        cert_file, key_file = ensure_tls_certificate(tls_cert_file, tls_key_file)
        tls_options = {"ssl_certfile": cert_file, "ssl_keyfile": key_file}
        scheme = "https"

    log_startup_banner(host, port, internal_port, scheme)

    public_server = uvicorn.Server(
        uvicorn.Config(
            create_native_web_app(api_app, port),
            host=host,
            port=port,
            log_level="error",
            **tls_options,
        )
    )

    internal_server = uvicorn.Server(
        uvicorn.Config(
            create_native_web_app(api_app, internal_port),
            host="127.0.0.1",
            port=internal_port,
            log_level="error",
            # The public listener already ran application startup.
            lifespan="off",
        )
    )
    # Only one listener may install process signal handlers.
    internal_server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

    asyncio.run(_serve([public_server, internal_server], stop_event))


def log_startup_banner(
    host: str, port: int, internal_port: int, scheme: str = "http"
) -> None:
    """Explain how the web interface is exposed."""
    logger.info("Serving the Frigate web interface on %s://%s:%s", scheme, host, port)

    # the internal listener is unauthenticated, so an operator who cannot find
    # out which port it took cannot check that it stayed on loopback
    logger.info(
        "Serving trusted internal media requests on http://127.0.0.1:%s "
        "(loopback only, never publish this port)",
        internal_port,
    )

    if host in ("::", "::0"):
        logger.info(
            "Binding to %s accepts IPv6 and IPv4 connections. Set "
            "FRIGATE_WEB_HOST=127.0.0.1 to restrict Frigate to this computer.",
            host,
        )
    elif host not in ("127.0.0.1", "::1", "localhost"):
        logger.info(
            "Binding to %s makes Frigate reachable from other devices on your "
            "network. Set FRIGATE_WEB_HOST=127.0.0.1 to restrict it to this "
            "computer.",
            host,
        )


__all__ = [
    "create_native_web_app",
    "log_startup_banner",
    "run_native_web_server",
]
