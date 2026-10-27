# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Bounded, opt-in discovery of ONVIF devices and RTSP services.

Discovery never authenticates or opens a video stream. WS-Discovery is link
local; an optional TCP scan fingerprints the protocols, not just open ports.
The scanner uses ordinary sockets and works with Windows' asyncio proactor.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import ipaddress
import logging
import re
import socket
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

import psutil

logger = logging.getLogger(__name__)

DISCOVERY_ADDRESS = ("239.255.255.250", 3702)
DISCOVERY_SECONDS = 3.0
CONNECT_TIMEOUT = 0.5
PROTOCOL_TIMEOUT = 0.8
SCAN_CONCURRENCY = 64
SCAN_LEASE_SECONDS = 120.0
MAX_DEVICES = 512
MAX_SERVICES_PER_DEVICE = 32
MAX_PACKET_BYTES = 32768
# Some errno names (notably ENFILE) are not exposed on every platform.
RESOURCE_ERRNOS = frozenset(
    getattr(errno, name)
    for name in ("EMFILE", "ENFILE", "ENOBUFS")
    if hasattr(errno, name)
)
DEFAULT_PORTS = "80,88,443,554,8000,8001,8080,8081,8554,8899,9000,10554"
COMMON_PORTS = tuple(int(port) for port in DEFAULT_PORTS.split(","))
LOCAL_NETWORKS = tuple(
    ipaddress.IPv4Network(network)
    for network in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "100.64.0.0/10",
    )
)

_SOAP_BODY = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
    b'xmlns:tds="http://www.onvif.org/ver10/device/wsdl">'
    b"<s:Body><tds:GetSystemDateAndTime/></s:Body></s:Envelope>"
)


def parse_target(value: str) -> list[str]:
    """Expand one local IPv4 host or subnet, with a maximum of 256 addresses."""
    try:
        network = ipaddress.ip_network(value.strip(), strict=False)
    except ValueError as error:
        raise ValueError("Enter a valid local IPv4 address or CIDR subnet.") from error
    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError("Only IPv4 addresses are supported for port scans.")
    if network.prefixlen < 24:
        raise ValueError("The subnet must be /24 or smaller (at most 256 addresses).")
    if not any(network.subnet_of(allowed) for allowed in LOCAL_NETWORKS):
        raise ValueError(
            "Only private, link-local, or shared IPv4 networks can be scanned."
        )
    return [str(host) for host in network.hosts()]


def parse_ports(value: str) -> list[int]:
    """Parse comma-separated ports/ranges without allocating unbounded input."""
    if not value or len(value) > 512:
        raise ValueError("Enter ports or ranges such as 554,8080,10000-10100.")
    ports: set[int] = set()
    for item in value.split(","):
        item = item.strip()
        if not re.fullmatch(r"[0-9]{1,5}(?:\s*-\s*[0-9]{1,5})?", item):
            raise ValueError("Enter ports or ranges such as 554,8080,10000-10100.")
        bounds = [int(part.strip()) for part in item.split("-")]
        start, end = bounds[0], bounds[-1]
        if start < 1 or end > 65535 or start > end:
            raise ValueError("Ports must be between 1 and 65535, with ranges in order.")
        ports.update(range(start, end + 1))
    # Visit familiar camera ports first even during an all-port scan, while
    # still scanning every selected port exactly once.
    priority = {port: index for index, port in enumerate(COMMON_PORTS)}
    return sorted(
        ports, key=lambda port: (0, priority[port]) if port in priority else (1, port)
    )


def _allowed_source(host: str) -> bool:
    try:
        address = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        return False
    return any(address in network for network in LOCAL_NETWORKS)


def local_interfaces() -> list[tuple[str, str]]:
    """Return up IPv4 interfaces and bounded subnet suggestions."""
    interfaces: list[tuple[str, str]] = []
    try:
        stats = psutil.net_if_stats()
        for name, addresses in psutil.net_if_addrs().items():
            if name in stats and not stats[name].isup:
                continue
            for address in addresses:
                if address.family != socket.AF_INET or not _allowed_source(
                    address.address
                ):
                    continue
                try:
                    network = ipaddress.IPv4Interface(
                        f"{address.address}/{address.netmask or '255.255.255.0'}"
                    ).network
                except ValueError:
                    continue
                if network.prefixlen < 24:
                    network = ipaddress.IPv4Network(
                        f"{address.address}/24", strict=False
                    )
                if any(network.subnet_of(allowed) for allowed in LOCAL_NETWORKS):
                    interfaces.append((address.address, str(network)))
    except (OSError, RuntimeError):
        logger.warning(
            "Could not enumerate interfaces for camera discovery", exc_info=True
        )
    # Prefer normal LANs to link-local addresses, without changing their order
    # otherwise. Several interfaces may share the same address.
    return sorted(
        set(interfaces), key=lambda item: (item[0].startswith("169.254."), item[0])
    )


def _probe_message(device_type: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl"
 xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
 <s:Header><a:MessageID>uuid:{uuid.uuid4()}</a:MessageID>
 <a:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>
 <a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action></s:Header>
 <s:Body><d:Probe><d:Types>{device_type}</d:Types></d:Probe></s:Body>
</s:Envelope>""".encode()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text_of(element: ET.Element, local_name: str) -> str:
    return next(
        (
            item.text or ""
            for item in element.iter()
            if _local_name(item.tag) == local_name
        ),
        "",
    )


def _scope_value(scopes: str, kind: str) -> str | None:
    prefix = f"onvif://www.onvif.org/{kind}/"
    for scope in scopes.split():
        if scope.lower().startswith(prefix):
            value = unquote(scope[len(prefix) :])
            value = "".join(char for char in value if char.isprintable()).strip()
            return value[:120] or None
    return None


@dataclass
class Service:
    protocol: str
    port: int
    scheme: str
    path: str = ""
    sources: list[str] = field(default_factory=list)
    requires_auth: bool = False

    def snapshot(self) -> dict:
        return {
            "protocol": self.protocol,
            "port": self.port,
            "scheme": self.scheme,
            "path": self.path,
            "sources": list(self.sources),
            "requires_auth": self.requires_auth,
        }


@dataclass
class Device:
    host: str
    name: str | None = None
    model: str | None = None
    services: list[Service] = field(default_factory=list)

    def add_service(self, service: Service) -> None:
        for existing in self.services:
            if (existing.protocol, existing.port, existing.scheme, existing.path) == (
                service.protocol,
                service.port,
                service.scheme,
                service.path,
            ):
                for source in service.sources:
                    if source not in existing.sources:
                        existing.sources.append(source)
                existing.requires_auth |= service.requires_auth
                return
        if len(self.services) < MAX_SERVICES_PER_DEVICE:
            self.services.append(service)

    def snapshot(self) -> dict:
        return {
            "host": self.host,
            "name": self.name,
            "model": self.model,
            "services": [
                service.snapshot()
                for service in sorted(
                    self.services,
                    key=lambda item: (item.protocol, item.port, item.scheme, item.path),
                )
            ],
        }


def parse_discovery_response(packet: bytes, source_host: str) -> list[Device]:
    """Extract ONVIF advertisements without following untrusted advertised URLs.

    The UDP sender is used as the host, not the URL's potentially forged host.
    DTDs are forbidden before parsing data from the network.
    """
    if (
        not _allowed_source(source_host)
        or len(packet) > MAX_PACKET_BYTES
        or b"\x00" in packet
    ):
        return []
    upper = packet.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        return []
    if b"ONVIF.ORG" not in upper and b"NETWORKVIDEOTRANSMITTER" not in upper:
        return []
    try:
        root = ET.fromstring(packet)
    except (ET.ParseError, ValueError):
        return []

    devices: list[Device] = []
    for match in root.iter():
        if _local_name(match.tag) != "ProbeMatch":
            continue
        scopes = _text_of(match, "Scopes")
        device = Device(
            host=source_host,
            name=_scope_value(scopes, "name"),
            model=_scope_value(scopes, "hardware"),
        )
        for addr in _text_of(match, "XAddrs").split():
            try:
                url = urlsplit(addr)
                if (
                    url.scheme not in ("http", "https")
                    or not url.hostname
                    or url.username is not None
                    or url.password is not None
                ):
                    continue
                port = url.port or (443 if url.scheme == "https" else 80)
                if not 1 <= port <= 65535:
                    continue
                path = url.path[:256] or "/"
                if any(not char.isprintable() for char in path):
                    continue
                device.add_service(
                    Service("onvif", port, url.scheme, path, ["ws-discovery"])
                )
            except ValueError:
                continue
        devices.append(device)
    return devices


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_device):
        self.on_device = on_device

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        for device in parse_discovery_response(data, addr[0]):
            self.on_device(device)


async def discover_onvif(on_device, interfaces: list[tuple[str, str]]) -> None:
    """Send WS-Discovery probes on every active interface, then collect replies."""
    loop = asyncio.get_running_loop()
    transports: list[asyncio.DatagramTransport] = []
    addresses = [address for address, _ in interfaces] or ["0.0.0.0"]
    try:
        for address in addresses:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
                if address != "0.0.0.0":
                    sock.setsockopt(
                        socket.IPPROTO_IP,
                        socket.IP_MULTICAST_IF,
                        socket.inet_aton(address),
                    )
                sock.bind((address, 0))
                sock.setblocking(False)
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: _DiscoveryProtocol(on_device), sock=sock
                )
                transports.append(transport)
                for device_type in ("dn:NetworkVideoTransmitter", "tds:Device"):
                    transport.sendto(_probe_message(device_type), DISCOVERY_ADDRESS)
            except OSError:
                sock.close()
                logger.debug("WS-Discovery unavailable on %s", address, exc_info=True)
        if not transports:
            raise OSError("No network interface could send the ONVIF discovery probe.")
        await asyncio.sleep(DISCOVERY_SECONDS)
    finally:
        for transport in transports:
            transport.close()


class ScanResourceError(Exception):
    """A local socket/resource error means the scan could not be completed."""


def _check_resource_error(error: OSError) -> None:
    if error.errno in RESOURCE_ERRNOS or getattr(error, "winerror", None) in (
        10024,  # WSAEMFILE
        10048,  # WSAEADDRINUSE
        10055,  # WSAENOBUFS
    ):
        raise ScanResourceError(
            "The system ran out of network socket resources."
        ) from error


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(OSError, asyncio.TimeoutError):
        await asyncio.wait_for(writer.wait_closed(), 0.5)


async def _open_connection(host: str, port: int):
    try:
        return await asyncio.wait_for(
            asyncio.open_connection(host, port), CONNECT_TIMEOUT
        )
    except OSError as error:
        _check_resource_error(error)
        return None
    except TimeoutError:
        return None


async def probe_port(host: str, port: int) -> Service | None:
    """Identify RTSP or standard-path ONVIF on an open TCP port.

    An HTTP 401 alone and an open socket are intentionally not camera evidence.
    An RTSP response (including 401) identifies a service, not necessarily a
    camera. TLS and vendor-specific protocols are not fingerprinted here.
    """
    connection = await _open_connection(host, port)
    if connection is None:
        return None
    reader, writer = connection
    try:
        request = (
            f"OPTIONS rtsp://{host}:{port}/ RTSP/1.0\r\n"
            "CSeq: 1\r\nUser-Agent: Gannet-Camera-Discovery\r\n\r\n"
        ).encode("ascii")
        writer.write(request)
        await asyncio.wait_for(writer.drain(), PROTOCOL_TIMEOUT)
        line = await asyncio.wait_for(reader.readline(), PROTOCOL_TIMEOUT)
        match = re.match(rb"^RTSP/\d+(?:\.\d+)?\s+(\d{3})\b", line, re.IGNORECASE)
        if match:
            return Service(
                "rtsp",
                port,
                "rtsp",
                sources=["tcp"],
                requires_auth=int(match.group(1)) in (401, 403),
            )
    except (TimeoutError, OSError, ValueError):
        pass
    finally:
        await _close_writer(writer)

    # Retry on a fresh connection: an HTTP server may close after the RTSP
    # request. No credentials are sent and redirects are never followed.
    connection = await _open_connection(host, port)
    if connection is None:
        return None
    reader, writer = connection
    try:
        headers = (
            f"POST /onvif/device_service HTTP/1.1\r\nHost: {host}:{port}\r\n"
            'Content-Type: application/soap+xml; charset=utf-8; action="http://www.onvif.org/ver10/device/wsdl/GetSystemDateAndTime"\r\n'
            f"Content-Length: {len(_SOAP_BODY)}\r\nConnection: close\r\n\r\n"
        ).encode("ascii")
        writer.write(headers + _SOAP_BODY)
        await asyncio.wait_for(writer.drain(), PROTOCOL_TIMEOUT)
        # Headers and SOAP body may arrive in separate packets. Bound the
        # response and the total read time, not merely each individual read.
        deadline = asyncio.get_running_loop().time() + PROTOCOL_TIMEOUT
        response = b""
        while len(response) < 16384:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            chunk = await asyncio.wait_for(
                reader.read(16384 - len(response)), remaining
            )
            if not chunk:
                break
            response += chunk
            # A 401 challenge by itself is indistinguishable from a generic
            # web UI. Require ONVIF SOAP evidence instead of guessing from ports.
            lower = response.lower()
            if (
                lower.startswith(b"http/")
                and b"onvif.org/ver10/device/wsdl" in lower
                and (b"envelope" in lower or b"getsystemdateandtime" in lower)
            ):
                return Service("onvif", port, "http", "/onvif/device_service", ["tcp"])
    except (TimeoutError, OSError, ValueError):
        pass
    finally:
        await _close_writer(writer)
    return None


@dataclass
class DiscoveryScan:
    id: str
    hosts: list[str]
    ports: list[int]
    interfaces: list[tuple[str, str]]
    status: str = "discovering"
    scanned: int = 0
    devices: dict[str, Device] = field(default_factory=dict)
    error: str | None = None
    warning: str | None = None
    last_poll: float = field(default_factory=time.monotonic)
    task: asyncio.Task | None = None

    @property
    def total(self) -> int:
        return len(self.hosts) * len(self.ports)

    def add_device(self, device: Device) -> None:
        if device.host not in self.devices:
            if len(self.devices) >= MAX_DEVICES:
                return
            self.devices[device.host] = device
            return
        existing = self.devices[device.host]
        existing.name = existing.name or device.name
        existing.model = existing.model or device.model
        for service in device.services:
            existing.add_service(service)

    def snapshot(self) -> dict:
        self.last_poll = time.monotonic()
        return {
            "id": self.id,
            "status": self.status,
            "scanned": self.scanned,
            "total": self.total,
            "networks": list(dict.fromkeys(network for _, network in self.interfaces)),
            "devices": [
                self.devices[host].snapshot()
                for host in sorted(self.devices, key=ipaddress.IPv4Address)
            ],
            "error": self.error,
            "warning": self.warning,
        }


class CameraDiscoveryManager:
    """One active scan per app; results remain until the next scan starts."""

    def __init__(self) -> None:
        self.current: DiscoveryScan | None = None

    def start(self, target: str | None, ports: str) -> DiscoveryScan:
        if self.current and self.current.status in ("discovering", "scanning"):
            raise RuntimeError("A camera scan is already running.")
        hosts = parse_target(target) if target else []
        selected_ports = parse_ports(ports) if hosts else []
        scan = DiscoveryScan(
            uuid.uuid4().hex, hosts, selected_ports, local_interfaces()
        )
        self.current = scan
        scan.task = asyncio.create_task(self._run(scan))
        return scan

    def get(self, scan_id: str) -> DiscoveryScan | None:
        return self.current if self.current and self.current.id == scan_id else None

    async def cancel(self, scan: DiscoveryScan) -> None:
        if scan.task and not scan.task.done():
            scan.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await scan.task
        if scan.status in ("discovering", "scanning"):
            scan.status = "cancelled"

    async def close(self) -> None:
        if self.current:
            await self.cancel(self.current)

    async def _run(self, scan: DiscoveryScan) -> None:
        try:
            try:
                await discover_onvif(scan.add_device, scan.interfaces)
            except OSError:
                # An active scan can still run if multicast is unavailable.
                scan.warning = "ONVIF multicast discovery could not be sent."
                if not scan.hosts:
                    raise
            if not scan.hosts:
                scan.status = "completed"
                return
            scan.status = "scanning"
            # Port-major order gives all addresses a chance to respond early.
            # This iterator and the fixed workers never materialize host*port
            # tasks, even for a whole subnet and all 65,535 ports.
            targets = iter((host, port) for port in scan.ports for host in scan.hosts)

            async def worker() -> None:
                while scan.status == "scanning":
                    if time.monotonic() - scan.last_poll > SCAN_LEASE_SECONDS:
                        scan.status = "expired"
                        return
                    try:
                        host, port = next(targets)
                    except StopIteration:
                        return
                    service = await probe_port(host, port)
                    scan.scanned += 1
                    if service:
                        scan.add_device(Device(host=host, services=[service]))

            workers = [asyncio.create_task(worker()) for _ in range(SCAN_CONCURRENCY)]
            try:
                await asyncio.gather(*workers)
            finally:
                for task in workers:
                    task.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
            if scan.status == "scanning":
                scan.status = "completed"
        except asyncio.CancelledError:
            scan.status = "cancelled"
            raise
        except Exception:
            logger.exception("Camera discovery scan failed")
            scan.status = "failed"
            scan.error = "The scan could not be completed. Check the server logs."
