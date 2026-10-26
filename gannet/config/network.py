from pydantic import Field, field_validator, model_validator

from gannet.util.config import parse_listen_address

from .base import FrigateBaseModel

__all__ = ["IPv6Config", "ListenConfig", "NetworkingConfig"]


class IPv6Config(FrigateBaseModel):
    enabled: bool = Field(
        default=False,
        title="Enable IPv6",
        description="Allow an IPv6 address in FRIGATE_WEB_HOST.",
    )


class ListenConfig(FrigateBaseModel):
    internal: int | str = Field(
        default=5000,
        title="Internal port",
        description=(
            "Loopback-only port for Frigate media jobs. Requests on this port "
            'are trusted and never exposed to the LAN. A "host:port" value '
            "is accepted for compatibility, but the internal listener always "
            "binds 127.0.0.1."
        ),
    )
    external: int | str = Field(
        default=8971,
        title="External port",
        description=(
            'Authenticated Windows web-interface port. A "host:port" value '
            "sets the address the public listener binds; FRIGATE_WEB_HOST "
            "takes precedence when it is set."
        ),
    )

    # Runs before pydantic coerces a bool to an int port, which the address
    # parser rejects: a config typo must fail loudly instead of listening on 1
    @field_validator("internal", "external", mode="before")
    @classmethod
    def validate_listen(cls, value: int | str) -> int | str:
        return parse_listen_address(value)[0]

    @property
    def internal_port(self) -> int:
        return parse_listen_address(self.internal)[1]

    @property
    def external_port(self) -> int:
        return parse_listen_address(self.external)[1]

    @property
    def internal_host(self) -> str | None:
        """Address named by the internal value, if any.

        The native internal listener is loopback-only by contract, so an
        address here is never used to widen it.
        """
        return _listen_host(self.internal)

    @property
    def external_host(self) -> str | None:
        """Address the public listener should bind, or None for the default."""
        return _listen_host(self.external)

    @model_validator(mode="after")
    def validate_distinct_ports(self) -> "ListenConfig":
        if self.internal_port == self.external_port:
            raise ValueError("internal and external must listen on different ports")

        return self


def _listen_host(value: int | str) -> str | None:
    """Return the address part of a listen value, or None when it is a bare port."""
    host, sep, _ = str(value).strip().rpartition(":")

    if not sep or not host:
        return None

    if host.startswith("[") and host.endswith("]"):
        return host[1:-1]

    return host


class NetworkingConfig(FrigateBaseModel):
    ipv6: IPv6Config = Field(
        default_factory=IPv6Config,
        title="IPv6 configuration",
        description="IPv6 support for the native Windows listener.",
    )
    listen: ListenConfig = Field(
        default_factory=ListenConfig,
        title="Listening ports configuration",
        description=(
            "The loopback-only internal port and authenticated public Windows "
            "web port. FRIGATE_WEB_PORT may override the public listener."
        ),
    )
