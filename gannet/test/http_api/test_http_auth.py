"""Tests for authentication endpoints."""

import os
import tempfile
import unittest
from unittest.mock import ANY, patch

from starlette.testclient import TestClient

from gannet.api.auth import (
    FAILED_LOGIN_BURST_GAP_S,
    JWT_SECRET_FILE_NAME,
    MAX_NOTICE_USERNAME,
    MAX_OPEN_BURSTS,
    FailedLoginTracker,
    get_jwt_secret,
    hash_password,
)
from gannet.api.web import create_native_web_app
from gannet.const import JWT_SECRET_ENV_VAR, JWT_SECRET_ENV_VARS
from gannet.models import User
from gannet.test.http_api.base_http_test import AuthTestClient, BaseTestHttp


@patch.dict(os.environ, {JWT_SECRET_ENV_VAR: "test-secret"})
class TestHttpAuth(BaseTestHttp):
    def setUp(self):
        super().setUp([User])
        self.app = super().create_app()

    def tearDown(self):
        User.delete().execute()
        super().tearDown()

    def test_login_unknown_user_logs_warning(self):
        with self.assertLogs("gannet.api.auth", level="WARNING") as logs:
            with AuthTestClient(self.app) as client:
                response = client.post(
                    "/login", json={"user": "ghost", "password": "irrelevant"}
                )
        assert response.status_code == 401
        assert any("Login failed" in m and "ghost" in m for m in logs.output)

    def test_login_bad_password_logs_warning(self):
        password_hash = hash_password("correct-horse-battery", iterations=1000)
        User.insert(
            username="admin",
            password_hash=password_hash,
            role="admin",
            notification_tokens=[],
        ).execute()
        with self.assertLogs("gannet.api.auth", level="WARNING") as logs:
            with AuthTestClient(self.app) as client:
                response = client.post(
                    "/login", json={"user": "admin", "password": "wrong"}
                )
        assert response.status_code == 401
        assert any("Login failed" in m and "admin" in m for m in logs.output)


@patch.dict(os.environ, {JWT_SECRET_ENV_VAR: "test-secret"})
class TestNativeGatewayLogin(BaseTestHttp):
    """The browser login sequence through the native ``/api`` mount.

    Direct-to-FastAPI tests cannot see a whole class of mount bugs: Starlette
    reports ``/api/login`` as the URL path while the global admin dependency's
    exemptions are application paths such as ``/login``. The production
    combination therefore returned 403 before checking a correct password,
    which the login page surfaces as an unknown error rather than a 401.
    """

    password = "correct-horse-battery"

    def setUp(self):
        super().setUp([User])
        User.delete().execute()
        for username, role in (("admin", "admin"), ("viewer", "viewer")):
            User.insert(
                username=username,
                password_hash=hash_password(self.password, iterations=1),
                role=role,
                notification_tokens=[],
            ).execute()

        # Users must exist before the app loads its in-memory session map.
        self.api_app = super().create_app(enforce_default_admin=True)
        # Prove the actual HTTPS scheme, not the config default, secures the
        # native gateway's session cookie.
        self.api_app.frigate_config.auth.cookie_secure = False
        self.gateway = create_native_web_app(self.api_app, 8971)

    def tearDown(self):
        User.delete().execute()
        super().tearDown()

    def _client(self) -> TestClient:
        return TestClient(self.gateway, base_url="https://frigate.local:8971")

    def _login(self, client: TestClient, username: str, password: str):
        return client.post(
            "/api/login",
            json={"user": username, "password": password},
            headers={
                "origin": "https://frigate.local:8971",
                "x-csrf-token": "1",
            },
        )

    def test_admin_and_viewer_can_login_through_the_native_gateway(self):
        for username, role in (("admin", "admin"), ("viewer", "viewer")):
            with self.subTest(username=username):
                client = self._client()
                login = self._login(client, username, self.password)

                self.assertEqual(login.status_code, 200, login.text)
                self.assertIn("; secure", login.headers["set-cookie"].lower())

                profile = client.get("/api/profile")
                self.assertEqual(profile.status_code, 200, profile.text)
                self.assertEqual(profile.json()["username"], username)
                self.assertEqual(profile.json()["role"], role)

    def test_wrong_password_through_the_native_gateway_is_unauthorized(self):
        response = self._login(self._client(), "admin", "wrong-password")

        self.assertEqual(response.status_code, 401, response.text)


@patch.dict(os.environ, {JWT_SECRET_ENV_VAR: "test-secret"})
class TestFailedLoginNotices(BaseTestHttp):
    def setUp(self):
        super().setUp([User])
        self.app = super().create_app()
        User.insert(
            username="admin",
            password_hash=hash_password("correct-horse-battery", iterations=1000),
            role="admin",
            notification_tokens=[],
        ).execute()
        tracker_patch = patch("gannet.api.auth.failed_logins")
        self.failed_logins = tracker_patch.start()
        self.addCleanup(tracker_patch.stop)

    def tearDown(self):
        User.delete().execute()
        super().tearDown()

    def _login(self, user: str, password: str) -> int:
        with AuthTestClient(self.app) as client:
            response = client.post("/login", json={"user": user, "password": password})

        return response.status_code

    def test_unknown_user_is_recorded(self):
        self.assertEqual(self._login("ghost", "irrelevant"), 401)
        self.failed_logins.record.assert_called_once_with("ghost", ANY)

    def test_bad_password_is_recorded_as_known(self):
        self.assertEqual(self._login("admin", "wrong"), 401)
        self.failed_logins.record.assert_called_once_with("admin", ANY, known=True)

    def test_success_is_not_recorded(self):
        self.assertEqual(self._login("admin", "correct-horse-battery"), 200)
        self.failed_logins.record.assert_not_called()


class TestFailedLoginTracker(unittest.TestCase):
    def setUp(self):
        self.tracker = FailedLoginTracker()
        raise_patch = patch("gannet.api.auth.raise_notice")
        self.raise_notice = raise_patch.start()
        self.addCleanup(raise_patch.stop)

    def _scopes(self) -> list[str]:
        return [call.kwargs["scope"] for call in self.raise_notice.call_args_list]

    def _fill(self, now: float) -> None:
        for index in range(MAX_OPEN_BURSTS):
            self.tracker.record(f"ghost{index}", now)

    def test_attempts_inside_the_gap_share_a_burst(self):
        for now in (1000.0, 1010.0, 1299.0):
            self.tracker.record("admin", now)

        self.raise_notice.assert_called_with(
            "failed_login", scope="admin:1000", params={"user": "admin"}
        )
        self.assertEqual(self._scopes(), ["admin:1000"] * 3)

    def test_each_user_gets_their_own_burst(self):
        self.tracker.record("admin", 1000.0)
        self.tracker.record("ghost", 1010.0)
        self.tracker.record("admin", 1020.0)

        self.assertEqual(self._scopes(), ["admin:1000", "ghost:1010", "admin:1000"])

    def test_a_quiet_gap_opens_a_new_burst(self):
        self.tracker.record("admin", 1000.0)
        self.tracker.record("admin", 1000.0 + FAILED_LOGIN_BURST_GAP_S)

        self.assertEqual(self._scopes(), ["admin:1000", "admin:1300"])

    def test_the_gap_runs_from_the_latest_attempt(self):
        for now in (1000.0, 1200.0, 1450.0):
            self.tracker.record("admin", now)

        self.assertEqual(self._scopes(), ["admin:1000"] * 3)

    def test_quiet_users_are_forgotten(self):
        self.tracker.record("ghost", 1000.0)
        self.tracker.record("admin", 1000.0 + FAILED_LOGIN_BURST_GAP_S)

        self.assertEqual(list(self.tracker._bursts), ["admin"])

    def test_a_long_username_is_cut(self):
        self.tracker.record("x" * 500, 1000.0)

        user = self.raise_notice.call_args.kwargs["params"]["user"]
        self.assertEqual(len(user), MAX_NOTICE_USERNAME)

    def test_unknown_users_past_the_cap_get_no_notice(self):
        self._fill(1000.0)
        self.tracker.record("one-too-many", 1001.0)
        self.tracker.record("ghost0", 1002.0)

        self.assertEqual(self.raise_notice.call_count, MAX_OPEN_BURSTS + 1)
        self.assertEqual(self._scopes()[-1], "ghost0:1000")

    def test_known_users_skip_the_cap(self):
        self._fill(1000.0)
        self.tracker.record("admin", 1001.0, known=True)

        self.assertEqual(self._scopes()[-1], "admin:1001")

    def test_quiet_bursts_free_their_slots(self):
        self._fill(1000.0)
        self.tracker.record("late", 1000.0 + FAILED_LOGIN_BURST_GAP_S)

        self.assertEqual(self._scopes()[-1], "late:1300")


class TestJwtSecretFile(unittest.TestCase):
    """The signing secret has to outlive a restart, or every session ends.

    A secret that is regenerated per start makes each browser's cookie fail as
    "bad_signature" - and every request and live-view websocket it then opens
    logs that failure - until the user signs in again.
    """

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config_dir = directory.name
        self.path = os.path.join(self.config_dir, JWT_SECRET_FILE_NAME)

        patched_dir = patch("gannet.api.auth.CONFIG_DIR", self.config_dir)
        patched_dir.start()
        self.addCleanup(patched_dir.stop)

        patched_env = patch.dict(os.environ, {}, clear=False)
        patched_env.start()
        self.addCleanup(patched_env.stop)

        for name in JWT_SECRET_ENV_VARS:
            os.environ.pop(name, None)

    def _stored(self) -> str:
        with open(self.path, encoding="utf-8") as f:
            return f.read().strip()

    def test_the_secret_is_written_once_and_reused(self):
        first = get_jwt_secret()

        self.assertEqual(len(first), 128)
        self.assertEqual(self._stored(), first)
        self.assertEqual(get_jwt_secret(), first)

    def test_a_secret_written_by_another_instance_is_adopted(self):
        """The exclusive create can lose a race; losing it must not fork keys."""
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("b" * 128)

        # the file appears between the check for it and the exclusive create
        with patch("gannet.api.auth.os.path.isfile", return_value=False):
            secret = get_jwt_secret()

        self.assertEqual(secret, "b" * 128)
        self.assertEqual(self._stored(), "b" * 128)

    def test_an_empty_secret_file_is_repaired_for_the_next_start(self):
        open(self.path, "w", encoding="utf-8").close()

        with self.assertLogs("gannet.api.auth", level="WARNING") as logs:
            secret = get_jwt_secret()

        self.assertEqual(len(secret), 128)
        self.assertEqual(self._stored(), secret)
        self.assertEqual(get_jwt_secret(), secret)
        self.assertTrue(any("is empty" in message for message in logs.output))

    def test_an_unwritable_config_directory_still_signs_in(self):
        secret = get_jwt_secret()

        with patch("gannet.api.auth.open", side_effect=OSError("denied")):
            unwritable = get_jwt_secret()

        self.assertNotEqual(secret, unwritable)
        self.assertEqual(len(unwritable), 128)
