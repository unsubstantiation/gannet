# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Discovery must find services by protocol, including nonstandard ports."""

import asyncio
import errno
import runpy
import socket
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from gannet.util import camera_discovery as discovery


class TestScanValidation(unittest.TestCase):
    def test_target_bounds_and_addresses(self):
        self.assertEqual(discovery.parse_target("192.168.5.12"), ["192.168.5.12"])
        self.assertEqual(len(discovery.parse_target("192.168.5.0/24")), 254)
        self.assertEqual(
            discovery.parse_target("10.1.2.0/31"), ["10.1.2.0", "10.1.2.1"]
        )
        self.assertEqual(discovery.parse_target("100.64.1.10"), ["100.64.1.10"])
        self.assertEqual(discovery.parse_target("169.254.1.10"), ["169.254.1.10"])

    def test_rejects_nonlocal_oversized_and_malformed_targets(self):
        for target in (
            "192.168.0.0/23",
            "127.0.0.1",
            "8.8.8.8",
            "224.0.0.1",
            "0.0.0.0",
            "::1",
            "camera.local",
            "192.168.1.2:554",
            "",
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                discovery.parse_target(target)

    def test_ports_include_nonstandard_ranges_and_deduplicate(self):
        ports = discovery.parse_ports("9999-10001,554,9999")
        self.assertEqual(ports, [554, 9999, 10000, 10001])
        all_ports = discovery.parse_ports("1-65535")
        self.assertEqual(len(all_ports), 65535)
        self.assertEqual(set(all_ports), set(range(1, 65536)))
        self.assertLess(all_ports.index(554), all_ports.index(1))

    def test_rejects_invalid_ports(self):
        for ports in ("", "0", "65536", "9-3", "80,", "1-70000", "1;2", "1" * 513):
            with self.subTest(ports=ports), self.assertRaises(ValueError):
                discovery.parse_ports(ports)

    def test_import_does_not_require_platform_specific_errno(self):
        with patch.dict(vars(errno)):
            vars(errno).pop("ENFILE", None)
            module = runpy.run_path(discovery.__file__)
        self.assertIn(errno.EMFILE, module["RESOURCE_ERRNOS"])

    def test_interface_suggestions_use_live_interfaces_and_bound_subnets(self):
        def address(ip, mask="255.255.0.0"):
            return SimpleNamespace(family=socket.AF_INET, address=ip, netmask=mask)

        with (
            patch.object(
                discovery.psutil,
                "net_if_addrs",
                return_value={
                    "lan": [address("192.168.12.3")],
                    "down": [address("10.0.0.2")],
                    "loopback": [address("127.0.0.1")],
                    "link": [address("169.254.10.1", "255.255.255.0")],
                },
            ),
            patch.object(
                discovery.psutil,
                "net_if_stats",
                return_value={
                    "lan": SimpleNamespace(isup=True),
                    "down": SimpleNamespace(isup=False),
                    "link": SimpleNamespace(isup=True),
                },
            ),
        ):
            self.assertEqual(
                discovery.local_interfaces(),
                [
                    ("192.168.12.3", "192.168.12.0/24"),
                    ("169.254.10.1", "169.254.10.0/24"),
                ],
            )


WS_RESPONSE = b"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
 <s:Body><d:ProbeMatches><d:ProbeMatch>
 <d:Types>dn:NetworkVideoTransmitter</d:Types>
 <d:Scopes>onvif://www.onvif.org/name/Front%20Door onvif://www.onvif.org/hardware/Model%201</d:Scopes>
 <d:XAddrs>http://192.168.1.99:23145/onvif/device_service https://192.168.1.99:23146/onvif/device_service</d:XAddrs>
 </d:ProbeMatch></d:ProbeMatches></s:Body>
</s:Envelope>"""


class TestOnvifAdvertisements(unittest.TestCase):
    def test_discovers_nonstandard_service_ports_and_scope_metadata(self):
        [device] = discovery.parse_discovery_response(WS_RESPONSE, "192.168.1.7")
        # The sender is authoritative: do not follow or trust the advertised host.
        self.assertEqual(device.host, "192.168.1.7")
        self.assertEqual(device.name, "Front Door")
        self.assertEqual(device.model, "Model 1")
        self.assertEqual(
            [(s.scheme, s.port) for s in device.services],
            [("http", 23145), ("https", 23146)],
        )
        self.assertEqual(device.services[0].sources, ["ws-discovery"])

    def test_no_address_still_reports_a_device(self):
        packet = WS_RESPONSE.replace(
            b"<d:XAddrs>http://192.168.1.99:23145/onvif/device_service https://192.168.1.99:23146/onvif/device_service</d:XAddrs>",
            b"",
        )
        [device] = discovery.parse_discovery_response(packet, "10.0.0.3")
        self.assertEqual(device.services, [])

    def test_ignores_bad_urls_and_uses_default_port(self):
        packet = WS_RESPONSE.replace(
            b"http://192.168.1.99:23145/onvif/device_service https://192.168.1.99:23146/onvif/device_service",
            b"http://user:password@192.168.1.99/onvif/device_service ftp://host/x http://host:99999/x http://host/onvif/device_service",
        )
        [device] = discovery.parse_discovery_response(packet, "10.0.0.3")
        self.assertEqual([(s.port, s.scheme) for s in device.services], [(80, "http")])

    def test_rejects_untrusted_invalid_or_dangerous_xml(self):
        for packet, host in (
            (WS_RESPONSE, "8.8.8.8"),
            (WS_RESPONSE[:100], "192.168.1.7"),
            (b"<!DOCTYPE x [<!ENTITY a 'abc'>]>" + WS_RESPONSE, "192.168.1.7"),
            (WS_RESPONSE + b" " * discovery.MAX_PACKET_BYTES, "192.168.1.7"),
            (WS_RESPONSE.decode().encode("utf-16"), "192.168.1.7"),
            (b"<ProbeMatch><XAddrs>http://x:554</XAddrs></ProbeMatch>", "192.168.1.7"),
        ):
            with self.subTest(host=host, packet=packet[:20]):
                self.assertEqual(discovery.parse_discovery_response(packet, host), [])

    def test_deduplicates_services_from_both_discovery_methods(self):
        [device] = discovery.parse_discovery_response(WS_RESPONSE, "192.168.1.7")
        device.add_service(
            discovery.Service("onvif", 23145, "http", "/onvif/device_service", ["tcp"])
        )
        self.assertEqual(len(device.services), 2)
        self.assertEqual(device.services[0].sources, ["ws-discovery", "tcp"])


class TestDiscoveryDatagrams(unittest.IsolatedAsyncioTestCase):
    async def test_real_udp_probes_collect_responses_on_each_interface(self):
        probes = []

        class Responder(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, addr):
                probes.append(data)
                self.transport.sendto(WS_RESPONSE, addr)

        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            Responder, local_addr=("127.0.0.1", 0)
        )
        found = []
        try:
            port = transport.get_extra_info("sockname")[1]
            with (
                patch.object(discovery, "DISCOVERY_ADDRESS", ("127.0.0.1", port)),
                patch.object(discovery, "DISCOVERY_SECONDS", 0.25),
                patch.object(discovery, "_allowed_source", return_value=True),
            ):
                await discovery.discover_onvif(
                    found.append, [("127.0.0.1", "127.0.0.0/24")]
                )
        finally:
            transport.close()
        self.assertEqual(len(probes), 2)
        self.assertIn(b"dn:NetworkVideoTransmitter", probes[0])
        self.assertIn(b"tds:Device", probes[1])
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0].services[0].port, 23145)


class TestProtocolFingerprints(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.servers = []

    async def asyncTearDown(self):
        for server in self.servers:
            server.close()
            await server.wait_closed()

    async def _serve(self, handler):
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        self.servers.append(server)
        return server.sockets[0].getsockname()[1]

    async def test_finds_authenticated_rtsp_on_an_arbitrary_tcp_port(self):
        requests = []

        async def camera(reader, writer):
            requests.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(b"RTSP/1.0 401 Unauthorized\r\nCSeq: 1\r\n\r\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        port = await self._serve(camera)
        service = await discovery.probe_port("127.0.0.1", port)
        self.assertIsNotNone(service)
        self.assertEqual((service.protocol, service.port), ("rtsp", port))
        self.assertTrue(service.requires_auth)
        self.assertIn(
            f"OPTIONS rtsp://127.0.0.1:{port}/ RTSP/1.0".encode(), requests[0]
        )
        self.assertEqual(len(requests), 1)

    async def test_finds_rtsp_that_only_responds_to_describe(self):
        requests = []

        async def camera(reader, writer):
            request = await reader.readuntil(b"\r\n\r\n")
            requests.append(request)
            if request.startswith(b"DESCRIBE "):
                writer.write(b"RTSP/1.0 401 Unauthorized\r\nCSeq: 1\r\n\r\n")
                await writer.drain()
            writer.close()
            await writer.wait_closed()

        port = await self._serve(camera)
        service = await discovery.probe_port("127.0.0.1", port)
        self.assertIsNotNone(service)
        self.assertEqual((service.protocol, service.port), ("rtsp", port))
        self.assertTrue(service.requires_auth)
        self.assertEqual(len(requests), 2)
        self.assertTrue(requests[0].startswith(b"OPTIONS "))
        self.assertTrue(requests[1].startswith(b"DESCRIBE "))
        self.assertIn(b"Accept: application/sdp", requests[1])
        for request in requests:
            self.assertNotIn(b"Authorization:", request)

    async def test_finds_http_onvif_even_when_headers_and_body_are_split(self):
        requests = []

        async def camera(reader, writer):
            request = await reader.readuntil(b"\r\n\r\n")
            requests.append(request)
            if request.startswith(b"OPTIONS"):
                writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            else:
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/soap+xml\r\n\r\n"
                )
                await writer.drain()
                await asyncio.sleep(0.02)
                writer.write(
                    b'<s:Envelope xmlns:tds="http://www.onvif.org/ver10/device/wsdl"><tds:GetSystemDateAndTimeResponse/></s:Envelope>'
                )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        port = await self._serve(camera)
        service = await discovery.probe_port("127.0.0.1", port)
        self.assertIsNotNone(service)
        self.assertEqual((service.protocol, service.port), ("onvif", port))
        self.assertEqual(service.path, "/onvif/device_service")
        self.assertTrue(requests[1].startswith(b"POST /onvif/device_service HTTP/1.1"))
        self.assertNotIn(b"Authorization:", requests[1])

    async def test_does_not_report_generic_http_authentication_as_camera(self):
        async def webserver(reader, writer):
            await reader.readuntil(b"\r\n\r\n")
            writer.write(
                b'HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: Basic realm="web"\r\nContent-Length: 0\r\n\r\n'
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        port = await self._serve(webserver)
        self.assertIsNone(await discovery.probe_port("127.0.0.1", port))

    async def test_reports_windows_socket_exhaustion(self):
        for code in (10024, 10048, 10055):
            error = OSError("Windows socket exhaustion")
            error.winerror = code
            with (
                self.subTest(code=code),
                self.assertRaises(discovery.ScanResourceError),
            ):
                discovery._check_resource_error(error)
        refused = OSError("Connection refused")
        refused.winerror = 10061
        discovery._check_resource_error(refused)

    async def test_reports_local_socket_exhaustion_instead_of_silent_failure(self):
        with patch(
            "asyncio.open_connection",
            new=AsyncMock(side_effect=OSError(errno.EMFILE, "exhausted")),
        ):
            with self.assertRaises(discovery.ScanResourceError):
                await discovery.probe_port("10.0.0.1", 12345)


class TestDiscoveryManager(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_and_active_scan_merge_and_complete(self):
        async def multicast(callback, interfaces):
            for device in discovery.parse_discovery_response(
                WS_RESPONSE, "192.168.1.7"
            ):
                callback(device)

        async def fingerprint(host, port):
            if port == 23145:
                return discovery.Service(
                    "onvif", port, "http", "/onvif/device_service", ["tcp"]
                )
            if port == 12345:
                return discovery.Service("rtsp", port, "rtsp", sources=["tcp"])
            return None

        with (
            patch.object(discovery, "discover_onvif", side_effect=multicast),
            patch.object(discovery, "probe_port", side_effect=fingerprint),
            patch.object(
                discovery,
                "local_interfaces",
                return_value=[("192.168.1.1", "192.168.1.0/24")],
            ),
        ):
            manager = discovery.CameraDiscoveryManager()
            scan = manager.start("192.168.1.7", "12345,23145,554")
            await scan.task
            result = scan.snapshot()

        self.assertEqual(result["status"], "completed")
        self.assertEqual((result["scanned"], result["total"]), (3, 3))
        self.assertEqual(result["networks"], ["192.168.1.0/24"])
        [device] = result["devices"]
        self.assertEqual(device["host"], "192.168.1.7")
        onvif = next(
            service for service in device["services"] if service["port"] == 23145
        )
        self.assertEqual(onvif["sources"], ["ws-discovery", "tcp"])
        self.assertTrue(any(service["port"] == 12345 for service in device["services"]))

    async def test_fixed_worker_limit_cancel_and_conflict(self):
        entered = 0
        all_busy = asyncio.Event()
        blocker = asyncio.Event()

        async def fingerprint(host, port):
            nonlocal entered
            entered += 1
            if entered == discovery.SCAN_CONCURRENCY:
                all_busy.set()
            try:
                await blocker.wait()
            finally:
                entered -= 1
            return None

        with (
            patch.object(discovery, "discover_onvif", new=AsyncMock()),
            patch.object(discovery, "probe_port", side_effect=fingerprint),
            patch.object(discovery, "local_interfaces", return_value=[]),
        ):
            manager = discovery.CameraDiscoveryManager()
            scan = manager.start("10.0.0.1", "1-65535")
            await asyncio.wait_for(all_busy.wait(), 2)
            self.assertEqual(entered, discovery.SCAN_CONCURRENCY)
            with self.assertRaises(RuntimeError):
                manager.start(None, "554")
            await manager.cancel(scan)
            self.assertEqual(entered, 0)
            self.assertEqual(scan.status, "cancelled")
            self.assertEqual(scan.scanned, 0)
            self.assertEqual(scan.total, 65535)
            self.assertIsNone(manager.get("wrong-id"))
            self.assertIs(manager.get(scan.id), scan)

    async def test_scan_without_polling_expires(self):
        with (
            patch.object(discovery, "discover_onvif", new=AsyncMock()),
            patch.object(discovery, "local_interfaces", return_value=[]),
        ):
            manager = discovery.CameraDiscoveryManager()
            scan = manager.start("10.0.0.1", "554")
            scan.last_poll = time.monotonic() - discovery.SCAN_LEASE_SECONDS - 1
            await scan.task
            self.assertEqual(scan.status, "expired")
            self.assertEqual(scan.scanned, 0)

    async def test_multicast_failure_is_a_warning_for_active_scan(self):
        with (
            patch.object(
                discovery,
                "discover_onvif",
                new=AsyncMock(side_effect=OSError("blocked")),
            ),
            patch.object(discovery, "probe_port", new=AsyncMock(return_value=None)),
            patch.object(discovery, "local_interfaces", return_value=[]),
        ):
            manager = discovery.CameraDiscoveryManager()
            scan = manager.start("10.0.0.1", "554")
            await scan.task
            self.assertEqual(scan.status, "completed")
            self.assertIsNotNone(scan.warning)
            self.assertEqual(scan.scanned, 1)

    async def test_closing_manager_stops_discovery(self):
        started = asyncio.Event()

        async def multicast(callback, interfaces):
            started.set()
            await asyncio.Event().wait()

        with (
            patch.object(discovery, "discover_onvif", side_effect=multicast),
            patch.object(discovery, "local_interfaces", return_value=[]),
        ):
            manager = discovery.CameraDiscoveryManager()
            scan = manager.start(None, "")
            await started.wait()
            await manager.close()
            self.assertEqual(scan.status, "cancelled")


if __name__ == "__main__":
    unittest.main()
