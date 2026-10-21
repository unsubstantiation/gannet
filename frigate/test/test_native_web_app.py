# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""The native web server, which replaces nginx on Windows."""

import asyncio
import ntpath
import threading
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import urljoin

from aiohttp import web as aiohttp_web
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount

from frigate.api.auth import deny_response_for_go2rtc_stream
from frigate.api.vod_native import VodPlaylist, VodSegment
from frigate.api.web import (
    GO2RTC_URL,
    JSMEPEG_URL,
    MQTT_WS_URL,
    InProcessAuth,
    NativeAuthMiddleware,
    _serve,
    build_auth_scope,
    create_native_web_app,
    is_contained_in,
    log_startup_banner,
    needs_auth,
    upstream_for,
)


class _FakeServer:
    """Small Uvicorn-like listener for shutdown coordination tests."""

    def __init__(self, exits_immediately: bool = False) -> None:
        self.should_exit = False
        self.exits_immediately = exits_immediately
        self.started = asyncio.Event()

    async def serve(self) -> None:
        self.started.set()

        if self.exits_immediately:
            return

        while not self.should_exit:
            await asyncio.sleep(0.01)


class TestNativeWebServerShutdown(unittest.IsolatedAsyncioTestCase):
    async def test_stop_event_stops_every_listener(self) -> None:
        """A service event must stop Uvicorn so Frigate can shut down cleanly."""
        stop_event = threading.Event()
        servers = [_FakeServer(), _FakeServer()]
        serving = asyncio.create_task(_serve(servers, stop_event))

        try:
            await asyncio.gather(*(server.started.wait() for server in servers))
            stop_event.set()
            await asyncio.wait_for(serving, timeout=2)
        finally:
            if not serving.done():
                stop_event.set()
                await asyncio.wait_for(serving, timeout=2)

        self.assertTrue(all(server.should_exit for server in servers))

    async def test_exit_of_one_listener_stops_the_other(self) -> None:
        """Ctrl+C reaches one Uvicorn server, not the loopback listener."""
        servers = [_FakeServer(exits_immediately=True), _FakeServer()]

        await asyncio.wait_for(_serve(servers), timeout=2)

        self.assertTrue(all(server.should_exit for server in servers))


class TestWebPathContainment(unittest.TestCase):
    def test_windows_paths_are_case_insensitive_but_component_aware(self):
        """A casing difference must not hide a valid web root or allow a sibling."""
        with patch("frigate.api.web.os.path", ntpath):
            self.assertTrue(
                is_contained_in(
                    r"C:\Frigate\web\assets\app.js",
                    r"c:\frigate\web",
                )
            )
            self.assertFalse(
                is_contained_in(
                    r"C:\Frigate\web_evil\assets\app.js",
                    r"c:\frigate\web",
                )
            )


class TestNativeWebApp(unittest.TestCase):
    def test_app_carries_the_startup_work_as_a_lifespan(self):
        """Starlette removed on_startup, so a lifespan has to be provided.

        Passing the removed argument raised TypeError while the config was
        loading, which meant the native install never answered on any port.
        """
        with patch("frigate.api.web.vod_native.start_cache_maintenance") as sweep:
            app = create_native_web_app(MagicMock(), 5000)

        # the startup work is reachable through the app rather than by calling
        # the helper directly, which is what the lifespan is for
        self.assertTrue(callable(app.router.lifespan_context))
        sweep.assert_not_called()

    def test_in_process_auth_blocks_unknown_go2rtc_streams(self):
        """Native auth retains the raw path needed by the stream security check."""
        for path in (
            "/live/mse/api/ws",
            "/live/webrtc/api/ws",
            "/api/go2rtc/webrtc",
        ):
            with self.subTest(path=path):
                scope = {
                    "type": "http",
                    "method": "GET",
                    "scheme": "http",
                    "path": path,
                    "raw_path": path.encode(),
                    "query_string": b"src=unknown_stream",
                    "headers": [(b"host", b"frigate.local")],
                }
                auth_scope = build_auth_scope(scope, 8971)
                auth_scope["app"] = SimpleNamespace(frigate_config=MagicMock())
                request = Request(auth_scope)
                original_url = dict(auth_scope["headers"])[b"x-original-url"].decode()

                with patch(
                    "frigate.api.auth._is_existing_go2rtc_stream",
                    return_value=False,
                ):
                    self.assertEqual(
                        deny_response_for_go2rtc_stream(original_url, "admin", request),
                        403,
                    )

    def test_startup_sweeps_stale_vod_cache_directories(self):
        """Entering the lifespan runs the startup work exactly once."""
        try:
            from starlette.testclient import TestClient
        except ImportError:  # pragma: no cover - testclient ships with starlette
            self.skipTest("starlette testclient is unavailable")

        with patch("frigate.api.web.vod_native.start_cache_maintenance") as sweep:
            app = create_native_web_app(MagicMock(), 5000)

            with TestClient(app):
                sweep.assert_called_once()


def _admin_auth(request: Request) -> Response:
    """Stand-in for the auth endpoint that lets everything through as admin."""
    return Response(
        status_code=202,
        headers={"remote-user": "admin", "remote-role": "admin"},
    )


def _fake_playlist(camera: str, start: float, end: float, stream: str | None):
    """A playlist for a range, without touching the recordings table."""
    return VodPlaylist(
        camera=camera,
        stream_type=stream or "main",
        start=start,
        end=end,
        segments=[
            VodSegment(
                index=0,
                path=f"/recordings/{camera}/00.00.mp4",
                start=start,
                duration=end - start,
                file_start=start,
            )
        ],
    )


class TestMountedApiLifespan(unittest.TestCase):
    """The FastAPI app's lifespan has to run even though it is mounted.

    Starlette only drives the lifespan of the outermost application, so the
    background work FastAPI starts on startup (the debug replay auto-stop
    watchdog) silently never ran on a native install.
    """

    def test_the_api_lifespan_is_entered_and_left_with_the_gateway(self):
        from starlette.testclient import TestClient

        events: list[str] = []

        @asynccontextmanager
        async def api_lifespan(app: FastAPI):
            events.append("startup")
            yield
            events.append("shutdown")

        api_app = FastAPI(lifespan=api_lifespan)

        with patch("frigate.api.web.vod_native.start_cache_maintenance"):
            app = create_native_web_app(api_app, 5000)

            with TestClient(app):
                self.assertEqual(events, ["startup"])

        self.assertEqual(events, ["startup", "shutdown"])

    def test_an_api_app_without_a_lifespan_is_tolerated(self):
        """Tests and tooling hand the gateway stand-ins for the API app."""
        from starlette.testclient import TestClient

        with patch("frigate.api.web.vod_native.start_cache_maintenance"):
            app = create_native_web_app(MagicMock(), 5000)

            with TestClient(app):
                pass


class TestGatewayRoutes(unittest.TestCase):
    """Requests through the whole gateway stack with a permissive auth check."""

    def _client(self, api_app=None):
        from starlette.testclient import TestClient

        self.enterContext(patch("frigate.api.web.vod_native.start_cache_maintenance"))
        self.enterContext(patch("frigate.api.web.auth_check", side_effect=_admin_auth))
        api_app = api_app or SimpleNamespace(
            frigate_config=SimpleNamespace(
                auth=SimpleNamespace(enabled=True),
                proxy=SimpleNamespace(
                    auth_secret=None,
                    header_map=SimpleNamespace(user=None, role=None),
                ),
            )
        )
        return TestClient(create_native_web_app(api_app, 8971))

    def test_the_master_playlist_variant_resolves_to_a_served_playlist(self):
        """``master.m3u8`` is a master playlist whose variant can be fetched.

        The web player asks for ``master.m3u8`` for every recordings range.
        Two things were wrong with it: the route compared the ``{playlist}``
        parameter against ``master.m3u8`` although the pattern strips the
        suffix, so the branch never ran, and had it run it would have built
        the variant URL with ``:g`` formatting, which renders ``1700000000.5``
        as ``1.7e+09`` and is not a path the float routes accept.
        """
        for master_url in (
            "/vod/front_door/start/1700000000.5/end/1700003600.25/master.m3u8",
            "/vod/front_door/sub/start/1700000000.5/end/1700003600.25/master.m3u8",
            "/vod/clip/front_door/start/1700000000.5/end/1700000030/master.m3u8",
        ):
            with (
                self.subTest(master_url=master_url),
                patch(
                    "frigate.api.web.vod_native.build_playlist",
                    side_effect=_fake_playlist,
                ),
            ):
                client = self._client()
                master = client.get(master_url)

                self.assertEqual(master.status_code, 200)
                self.assertEqual(
                    master.headers["content-type"].split(";")[0],
                    "application/vnd.apple.mpegurl",
                )

                lines = master.text.splitlines()
                self.assertEqual(lines[0], "#EXTM3U")
                self.assertTrue(
                    any(line.startswith("#EXT-X-STREAM-INF:") for line in lines),
                    master.text,
                )
                self.assertNotIn("#EXTINF:", master.text)
                variant_uri = [line for line in lines if not line.startswith("#")][-1]

                # resolve the way an HLS client does, against the master URL
                media = client.get(urljoin(master_url, variant_uri))

                self.assertEqual(media.status_code, 200, media.text)
                self.assertIn("#EXTINF:", media.text)
                self.assertIn("seg-00000.ts", media.text)

    def test_the_cache_directory_is_not_served(self):
        """CACHE_DIR holds every camera's in-progress recordings and previews.

        The web app never reads it over HTTP, so publishing it only gave any
        signed-in viewer a way around the per-camera media checks.
        """
        client = self._client()
        app = client.app

        self.assertFalse(
            any(
                isinstance(route, Mount) and route.path == "/cache"
                for route in app.routes
            )
        )
        self.assertTrue(needs_auth("/cache/preview.jpg"))


class TestProxyHttp(unittest.IsolatedAsyncioTestCase):
    """The plain HTTP proxy in front of go2rtc."""

    async def _serve_upstream(self, handler):
        """Start a loopback upstream, returning its base URL and runner."""
        app = aiohttp_web.Application()
        app.router.add_route("*", "/{tail:.*}", handler)
        runner = aiohttp_web.AppRunner(app)
        await runner.setup()
        site = aiohttp_web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}", runner

    async def test_the_upstream_status_and_body_reach_the_browser(self):
        """WebRTC signalling answers through this proxy.

        The upstream status was read from an attribute aiohttp responses do
        not have, so every proxied request ended in a 500 before the body or
        status reached the browser.
        """
        from frigate.api.web import proxy_http

        seen: dict[str, object] = {}

        async def upstream(request: aiohttp_web.Request):
            seen["path"] = request.path_qs
            seen["method"] = request.method
            seen["body"] = await request.text()
            return aiohttp_web.Response(
                status=201,
                text='{"type":"answer"}',
                content_type="application/json",
                headers={"X-Upstream": "go2rtc"},
            )

        base, runner = await self._serve_upstream(upstream)
        self.addAsyncCleanup(runner.cleanup)

        scope = {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/api/go2rtc/webrtc",
            "raw_path": b"/api/go2rtc/webrtc",
            "query_string": b"src=front_door",
            "headers": [(b"host", b"frigate.local"), (b"content-type", b"text/plain")],
            "server": ("127.0.0.1", 8971),
        }

        async def receive():
            return {"type": "http.request", "body": b"v=0 offer", "more_body": False}

        with patch("frigate.api.web.GO2RTC_URL", base):
            response = await proxy_http(Request(scope, receive))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.body, b'{"type":"answer"}')
        self.assertEqual(response.headers["x-upstream"], "go2rtc")
        self.assertTrue(response.headers["content-type"].startswith("application/json"))
        self.assertEqual(
            seen,
            {
                "path": "/api/webrtc?src=front_door",
                "method": "POST",
                "body": "v=0 offer",
            },
        )

    async def test_an_unreachable_upstream_is_a_bad_gateway(self):
        from frigate.api.web import proxy_http

        async def upstream(request: aiohttp_web.Request):
            return aiohttp_web.Response()

        base, runner = await self._serve_upstream(upstream)
        # the server is closed again before the request is made
        await runner.cleanup()

        scope = {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/go2rtc/api/streams",
            "raw_path": b"/go2rtc/api/streams",
            "query_string": b"",
            "headers": [(b"host", b"frigate.local")],
            "server": ("127.0.0.1", 8971),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        with patch("frigate.api.web.GO2RTC_URL", base):
            response = await proxy_http(Request(scope, receive))

        self.assertEqual(response.status_code, 502)


class TestNativeProxyIdentity(unittest.IsolatedAsyncioTestCase):
    def _api_app(self):
        return SimpleNamespace(
            frigate_config=SimpleNamespace(
                auth=SimpleNamespace(enabled=False),
                proxy=SimpleNamespace(
                    auth_secret="proxy-secret",
                    header_map=SimpleNamespace(
                        user="x-auth-user",
                        role="x-auth-groups",
                    ),
                ),
            )
        )

    @staticmethod
    def _scope(secret: str | None = None) -> dict:
        headers = [(b"host", b"frigate.local"), (b"x-auth-user", b"alice")]
        if secret is not None:
            headers.append((b"x-proxy-secret", secret.encode()))
        return {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": "/api/config",
            "raw_path": b"/api/config",
            "query_string": b"",
            "headers": headers,
        }

    async def test_mapped_identity_requires_the_proxy_secret(self) -> None:
        auth = InProcessAuth(self._api_app())

        with patch("frigate.api.web.auth_check") as auth_check:
            for supplied in (None, "wrong-secret"):
                with self.subTest(secret=supplied):
                    status, headers, body = await auth(self._scope(supplied), 8971)
                    self.assertEqual((status, headers, body), (401, [], b""))
            auth_check.assert_not_called()

    async def test_valid_proxy_secret_forwards_only_configured_identity(self) -> None:
        auth = InProcessAuth(self._api_app())
        observed_headers: dict[str, str] = {}

        def authorize(request: Request) -> Response:
            nonlocal observed_headers
            observed_headers = dict(request.headers)
            return Response(
                status_code=202,
                headers={"remote-user": request.headers["x-auth-user"]},
            )

        scope = self._scope("proxy-secret")
        scope["headers"].extend(
            [
                (b"remote-role", b"admin"),
                (b"x-unrelated-identity", b"spoofed"),
            ]
        )
        with patch("frigate.api.web.auth_check", side_effect=authorize):
            status, headers, _body = await auth(scope, 8971)

        self.assertEqual(status, 202)
        self.assertIn((b"remote-user", b"alice"), headers)
        self.assertEqual(observed_headers["x-proxy-secret"], "proxy-secret")
        self.assertEqual(observed_headers["x-auth-user"], "alice")
        self.assertNotIn("remote-role", observed_headers)
        self.assertNotIn("x-unrelated-identity", observed_headers)

    def test_client_proxy_headers_are_removed_before_dispatch(self) -> None:
        scope = self._scope("proxy-secret")
        scope["headers"].extend(
            [(b"remote-user", b"mallory"), (b"remote-role", b"admin")]
        )

        stripped = NativeAuthMiddleware._strip_proxy_headers(scope)
        names = {name.lower() for name, _value in stripped}

        self.assertNotIn(b"x-proxy-secret", names)
        self.assertNotIn(b"remote-user", names)
        self.assertNotIn(b"remote-role", names)
        self.assertIn(b"x-auth-user", names)

    def test_client_supplied_listener_headers_are_removed(self) -> None:
        """The gateway states which listener a request arrived on.

        ``x-server-port`` is how the auth endpoint recognises the loopback
        listener it trusts, and ``x-original-url`` is what the go2rtc stream
        check reads, so a client that could set either could describe its own
        request as an internal one.
        """
        scope = self._scope("proxy-secret")
        scope["headers"].extend(
            [
                (b"x-server-port", b"5000"),
                (b"x-original-url", b"http://127.0.0.1:5000/api/config"),
                (b"x-original-method", b"DELETE"),
            ]
        )

        scope["headers"].extend(
            [
                (b"x-original-host", b"evil.example"),
                (b"x-original-upgrade", b"websocket"),
            ]
        )

        names = {
            name.lower()
            for name, _value in NativeAuthMiddleware._strip_proxy_headers(scope)
        }

        self.assertNotIn(b"x-server-port", names)
        self.assertNotIn(b"x-original-url", names)
        self.assertNotIn(b"x-original-method", names)
        self.assertNotIn(b"x-original-host", names)
        self.assertNotIn(b"x-original-upgrade", names)
        self.assertIn(b"host", names)

    def test_auth_scope_carries_the_origin_check_inputs(self) -> None:
        """The gateway derives what nginx used to pass to ``/auth``.

        ``/auth`` rejects a cross-origin websocket or go2rtc stream request, so
        it needs the browser's ``Origin``, the request host, the outer proxy's
        ``X-Forwarded-Host`` and the ``Upgrade`` header. A forwarded scheme is
        what makes the session cookie Secure behind the TLS listener.
        """
        scope = {
            "type": "websocket",
            "method": "GET",
            "scheme": "https",
            "path": "/ws",
            "raw_path": b"/ws",
            "query_string": b"",
            "headers": [
                (b"host", b"frigate.lan:8971"),
                (b"origin", b"https://frigate.lan:8971"),
                (b"upgrade", b"websocket"),
                (b"x-forwarded-host", b"frigate.example.com"),
            ],
        }

        headers = dict(build_auth_scope(scope, 8971)["headers"])

        self.assertEqual(headers[b"origin"], b"https://frigate.lan:8971")
        self.assertEqual(headers[b"x-original-host"], b"frigate.lan:8971")
        self.assertEqual(headers[b"x-forwarded-host"], b"frigate.example.com")
        self.assertEqual(headers[b"x-original-upgrade"], b"websocket")
        self.assertEqual(headers[b"x-forwarded-proto"], b"https")

    def test_auth_scope_defaults_the_forwarded_host_to_host(self) -> None:
        """nginx sets ``$forwarded_host`` to ``$http_host`` without an outer proxy."""
        scope = {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/api/config",
            "raw_path": b"/api/config",
            "query_string": b"",
            "headers": [(b"host", b"127.0.0.1:5000")],
        }

        headers = dict(build_auth_scope(scope, 5000)["headers"])

        self.assertEqual(headers[b"x-forwarded-host"], b"127.0.0.1:5000")
        self.assertEqual(headers[b"x-forwarded-proto"], b"http")
        self.assertNotIn(b"origin", headers)
        self.assertNotIn(b"x-original-upgrade", headers)


class TestUpstreamRouting(unittest.TestCase):
    """Which loopback child service a live request belongs to."""

    def test_jsmpeg_reaches_the_frigate_jsmpeg_server(self):
        """JSMpeg is served by the output process, not by go2rtc.

        A camera that is not restreamed falls back to the jsmpeg player, so
        routing it to go2rtc left that player connecting to a service that does
        not speak jsmpeg at all.
        """
        self.assertEqual(
            upstream_for("/live/jsmpeg/front_door"),
            (JSMEPEG_URL, "/front_door"),
        )

    def test_the_mqtt_websocket_reaches_the_comms_server(self):
        self.assertEqual(upstream_for("/ws"), (MQTT_WS_URL, "/"))

    def test_mse_and_webrtc_reach_go2rtc(self):
        for path, expected in (
            ("/live/mse/api/ws", (GO2RTC_URL, "/api/ws")),
            ("/live/webrtc/api/ws", (GO2RTC_URL, "/api/ws")),
            ("/live/webrtc/webrtc.html", (GO2RTC_URL, "/webrtc.html")),
            ("/go2rtc/api/streams", (GO2RTC_URL, "/api/streams")),
            ("/api/go2rtc/webrtc", (GO2RTC_URL, "/api/webrtc")),
        ):
            with self.subTest(path=path):
                self.assertEqual(upstream_for(path), expected)

    def test_a_path_no_child_service_serves_is_not_proxied(self):
        self.assertIsNone(upstream_for("/api/config"))


class TestStartupBanner(unittest.TestCase):
    def test_the_loopback_listener_is_reported(self):
        """The internal port is unauthenticated, so it has to be visible."""
        with self.assertLogs("frigate.api.web", level="INFO") as logs:
            log_startup_banner("0.0.0.0", 8971, 5000)

        text = "\n".join(logs.output)

        self.assertIn("127.0.0.1:5000", text)
        self.assertIn("8971", text)

    def test_a_dual_stack_bind_says_it_accepts_both_families(self):
        with self.assertLogs("frigate.api.web", level="INFO") as logs:
            log_startup_banner("::", 8971, 5000)

        self.assertIn("IPv6", "\n".join(logs.output))


class TestNeedsAuth(unittest.TestCase):
    def test_login_flow_is_exempt(self):
        """The login endpoints must answer before a session exists.

        They all start with the protected ``/api/`` prefix, so checking the
        prefixes before the exemptions would leave them requiring the very
        session they exist to create, and nobody could log in on a native
        install that serves the web interface on its own port.
        """
        for path in ("/api/login", "/api/logout", "/api/auth/first_time_login"):
            with self.subTest(path=path):
                self.assertFalse(needs_auth(path))

    def test_protected_prefixes_require_auth(self):
        for path in (
            "/api/config",
            "/api",
            "/ws",
            "/vod/front_door/start/0/end/1/index.m3u8",
            "/clips/front_door/event.jpg",
            "/recordings/2024-01-01/00/front_door/00.00.mp4",
            "/exports/clip.mp4",
            "/cache/preview.jpg",
            "/live/mse/front_door",
        ):
            with self.subTest(path=path):
                self.assertTrue(needs_auth(path))

    def test_go2rtc_proxy_requires_auth(self):
        """The proxy reaches go2rtc's API, which reports camera URLs."""
        self.assertTrue(needs_auth("/go2rtc/api/streams"))

    def test_web_app_is_public(self):
        for path in ("/", "/review", "/assets/index.js", "/locales/en.json"):
            with self.subTest(path=path):
                self.assertFalse(needs_auth(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
