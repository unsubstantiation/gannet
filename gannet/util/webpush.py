"""Validation helpers for externally supplied Web Push subscriptions."""

import ipaddress
from typing import Any
from urllib.parse import urlparse

# Push endpoints are opaque URLs but stay well under this in practice.
MAX_ENDPOINT_LENGTH = 2048
INTERNAL_HOST_SUFFIXES = (".local", ".localdomain", ".internal", ".home.arpa")


def validate_push_endpoint(endpoint: Any) -> str | None:
    """Return a reason an endpoint is unusable, or None when it is valid.

    Push endpoints are supplied by browser vendors and should be public HTTPS
    services. Validate persisted subscriptions again at send time: old database
    rows may predate registration validation, and can otherwise make Gannet
    send requests to local services.
    """
    if not isinstance(endpoint, str) or not endpoint:
        return "endpoint must be a url"

    if len(endpoint) > MAX_ENDPOINT_LENGTH:
        return "endpoint is too long"

    try:
        parsed = urlparse(endpoint)
        port = parsed.port
    except ValueError:
        return "endpoint is not a valid url"

    if parsed.scheme != "https":
        return "endpoint must use https"

    if parsed.username or parsed.password:
        return "endpoint must not include credentials"

    if port is not None and port != 443:
        return "endpoint must use the default https port"

    hostname = parsed.hostname

    if not hostname:
        return "endpoint must include a hostname"

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None

    if address is not None:
        if not address.is_global:
            return "endpoint must not use a private address"
    elif hostname == "localhost" or "." not in hostname:
        return "endpoint must use a fully qualified hostname"
    elif "" in hostname.split("."):
        return "endpoint hostname must not contain empty labels"
    elif hostname.endswith(INTERNAL_HOST_SUFFIXES):
        return "endpoint must not use an internal hostname"

    if len(parsed.path) <= 1:
        return "endpoint must include a subscription path"

    return None


def validate_subscription(subscription: Any) -> str | None:
    """Return a reason a stored push subscription is unusable, if any."""
    if not isinstance(subscription, dict):
        return "subscription must be an object"

    reason = validate_push_endpoint(subscription.get("endpoint"))

    if reason:
        return reason

    keys = subscription.get("keys")
    if not isinstance(keys, dict):
        return "subscription must include keys"

    for name in ("p256dh", "auth"):
        value = keys.get(name)
        if not isinstance(value, str) or not value:
            return f"subscription keys must include {name}"

    return None


def vapid_audience(endpoint: str) -> str:
    """Return the origin used to scope a VAPID authorization claim."""
    parsed = urlparse(endpoint)
    return f"{parsed.scheme}://{parsed.netloc}"
