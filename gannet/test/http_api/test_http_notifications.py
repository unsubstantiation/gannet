"""Tests for notification registration and the admin row it relies on."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from gannet.app import FrigateApp
from gannet.config import FrigateConfig
from gannet.models import User
from gannet.test.http_api.base_http_test import AuthTestClient, BaseTestHttp

SUBSCRIPTION = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/dGhpcy1pcy1hLXRva2Vu",
    "keys": {"p256dh": "cHVibGljLWtleQ", "auth": "YXV0aC1zZWNyZXQ"},
}


class TestNotificationRegistration(BaseTestHttp):
    def setUp(self):
        super().setUp([User])

    def _init_auth(self, enabled: bool) -> FrigateConfig:
        config = FrigateConfig(**{**self.minimal_config, "auth": {"enabled": enabled}})
        FrigateApp.init_auth(SimpleNamespace(config=config))
        return config

    def _register(self):
        self.minimal_config["auth"] = {"enabled": False}
        with AuthTestClient(self.create_app()) as client:
            return client.post("/notifications/register", json={"sub": SUBSCRIPTION})

    def test_auth_disabled_fresh_install_persists_token(self):
        self._init_auth(enabled=False)

        assert self._register().status_code == 200
        admin = User.get(User.username == "admin")
        assert admin.password_hash == ""
        assert admin.notification_tokens == [SUBSCRIPTION]

    def test_auth_disabled_does_not_recreate_deleted_admin(self):
        User.insert(
            username="viewer1",
            role="viewer",
            password_hash="x$1$y$z",
            notification_tokens=[],
        ).execute()
        self._init_auth(enabled=False)

        assert User.get_or_none(User.username == "admin") is None
        assert self._register().status_code == 404

    def test_enabling_auth_sets_password_and_keeps_tokens(self):
        self._init_auth(enabled=False)
        assert self._register().status_code == 200

        config = self._init_auth(enabled=True)

        admin = User.get(User.username == "admin")
        assert admin.password_hash.count("$") == 3
        assert admin.notification_tokens == [SUBSCRIPTION]
        assert config.auth.admin_first_time_login is True

    def test_repeated_registration_is_idempotent(self):
        self._init_auth(enabled=False)
        for _ in range(3):
            assert self._register().status_code == 200
        assert User.get_by_id("admin").notification_tokens == [SUBSCRIPTION]

    def test_registration_replaces_rotated_keys_and_keeps_other_devices(self):
        self._init_auth(enabled=False)
        other = {**SUBSCRIPTION, "endpoint": SUBSCRIPTION["endpoint"] + "-other"}
        stale = {**SUBSCRIPTION, "keys": {"p256dh": "old", "auth": "old"}}
        User.update(notification_tokens=[stale, other, stale]).execute()
        assert self._register().status_code == 200
        assert User.get_by_id("admin").notification_tokens == [other, SUBSCRIPTION]

    def test_authenticated_registration_uses_current_user_not_admin(self):
        self._init_auth(enabled=True)
        User.create(
            username="alice", role="viewer", password_hash="x", notification_tokens=[]
        )
        self.minimal_config["auth"] = {"enabled": True}
        with AuthTestClient(self.create_app()) as client:
            response = client.post(
                "/notifications/register",
                json={"sub": SUBSCRIPTION},
                headers={"remote-user": "alice", "remote-role": "viewer"},
            )
        assert response.status_code == 200
        assert User.get_by_id("alice").notification_tokens == [SUBSCRIPTION]
        assert User.get_by_id("admin").notification_tokens == []

    def test_registration_retries_without_losing_concurrent_device(self):
        self._init_auth(enabled=False)
        other = {**SUBSCRIPTION, "endpoint": SUBSCRIPTION["endpoint"] + "-other"}
        real_update = User.update

        def concurrent_write():
            real_update(notification_tokens=[other]).execute()
            return 0

        conflict = Mock()
        conflict.where.return_value.execute.side_effect = concurrent_write
        updates = iter([conflict])

        def update(**kwargs):
            return next(updates, None) or real_update(**kwargs)

        with patch("gannet.api.notification.User.update", side_effect=update):
            assert self._register().status_code == 200
        assert User.get_by_id("admin").notification_tokens == [other, SUBSCRIPTION]

    def test_persistent_registration_conflict_is_retryable(self):
        self._init_auth(enabled=False)
        with patch("gannet.api.notification.User.update") as update:
            update.return_value.where.return_value.execute.return_value = 0
            assert self._register().status_code == 409
            assert update.call_count == 5
        assert User.get_by_id("admin").notification_tokens == []
