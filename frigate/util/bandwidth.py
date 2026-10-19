# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Per-process network bandwidth sampling through ETW.

Upstream Frigate reads per-process bandwidth from ``nethogs``, a Linux
tool that needs root and ``CAP_NET_ADMIN``. The Windows equivalent is a
real-time ETW session on the NT Kernel Logger with the network TCPIP
flag, which delivers the classic ``TcpIp`` and ``UdpIp`` send and
receive events. Every one of those events carries the owning process id
and the transfer size as the first two ``uint32`` properties of its MOF
class (``TcpIp_SendIPV4``, ``TcpIp_TypeGroup1``, ``TcpIp_SendIPV6``,
``TcpIp_TypeGroup3`` and the ``UdpIp`` equivalents), so a single
callback accumulates bytes per process for both protocols and both
address families.

The kernel logger session needs elevation, exactly like ``nethogs``
needs root: a non-elevated process cannot start it, so the collector
reports nothing and warns once instead of failing the stats loop.
"""

import ctypes
import logging
import socket
import struct
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# The only session that can receive kernel events.
KERNEL_LOGGER_NAME = "NT Kernel Logger"

# SystemTraceControlGuid, the provider the kernel logger registers under.
SYSTEM_TRACE_CONTROL_GUID = "{9E814AAD-3204-11D2-9A82-006008A86939}"

# EVENT_TRACE_FLAG_NETWORK_TCPIP: TcpIp and UdpIp events.
NETWORK_TCPIP_FLAG = 0x0000010000

# EVENT_TRACE_REAL_TIME_MODE
REAL_TIME_MODE = 0x00000100

# PROCESS_TRACE_MODE_REAL_TIME | PROCESS_TRACE_MODE_EVENT_RECORD
PROCESS_TRACE_MODE = 0x10000100

# WNODE_FLAG_TRACED_GUID
WNODE_TRACED_GUID_FLAG = 0x00020000

EVENT_TRACE_CONTROL_STOP = 1

# Classic event types that carry a transfer size: send and receive for
# IPv4 (10, 11) and IPv6 (26, 27). TCP and UDP reuse the same types, and
# the collector counts both because both move camera bytes.
SEND_IPV4 = 10
RECEIVE_IPV4 = 11
SEND_IPV6 = 26
RECEIVE_IPV6 = 27
TRANSFER_EVENT_TYPES = frozenset((SEND_IPV4, RECEIVE_IPV4, SEND_IPV6, RECEIVE_IPV6))

INVALID_PROCESSTRACE_HANDLE = 0xFFFFFFFFFFFFFFFF


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_uint8 * 8),
    ]


def _guid_from_string(value: str) -> _GUID:
    """Build the ctypes GUID structure for a registry-formatted GUID."""
    digits = value.strip("{}").replace("-", "")
    guid = _GUID()
    guid.Data1 = int(digits[0:8], 16)
    guid.Data2 = int(digits[8:12], 16)
    guid.Data3 = int(digits[12:16], 16)
    for index in range(8):
        guid.Data4[index] = int(digits[16 + index * 2 : 18 + index * 2], 16)
    return guid


class _WNODE_HEADER(ctypes.Structure):
    _fields_ = [
        ("BufferSize", ctypes.c_uint32),
        ("ProviderId", ctypes.c_uint32),
        ("HistoricalContext", ctypes.c_uint64),
        ("TimeStamp", ctypes.c_int64),
        ("Guid", _GUID),
        ("ClientContext", ctypes.c_uint32),
        ("Flags", ctypes.c_uint32),
    ]


class _EVENT_TRACE_PROPERTIES(ctypes.Structure):
    _fields_ = [
        ("Wnode", _WNODE_HEADER),
        ("BufferSize", ctypes.c_uint32),
        ("MinimumBuffers", ctypes.c_uint32),
        ("MaximumBuffers", ctypes.c_uint32),
        ("MaximumFileSize", ctypes.c_uint32),
        ("LogFileMode", ctypes.c_uint32),
        ("FlushTimer", ctypes.c_uint32),
        ("EnableFlags", ctypes.c_uint32),
        ("AgeLimit", ctypes.c_int32),
        ("NumberOfBuffers", ctypes.c_uint32),
        ("FreeBuffers", ctypes.c_uint32),
        ("EventsLost", ctypes.c_uint32),
        ("BuffersWritten", ctypes.c_uint32),
        ("LogBuffersLost", ctypes.c_uint32),
        ("RealTimeBuffersLost", ctypes.c_uint32),
        ("LoggerThreadId", ctypes.c_uint64),
        ("LogFileNameOffset", ctypes.c_uint32),
        ("LoggerNameOffset", ctypes.c_uint32),
    ]


class _EVENT_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("Id", ctypes.c_uint16),
        ("Version", ctypes.c_uint8),
        ("Channel", ctypes.c_uint8),
        ("Level", ctypes.c_uint8),
        ("Opcode", ctypes.c_uint8),
        ("Task", ctypes.c_uint16),
        ("Keyword", ctypes.c_uint64),
    ]


class _EVENT_HEADER(ctypes.Structure):
    _fields_ = [
        ("Size", ctypes.c_uint16),
        ("HeaderType", ctypes.c_uint16),
        ("Flags", ctypes.c_uint16),
        ("EventProperty", ctypes.c_uint16),
        ("ThreadId", ctypes.c_uint32),
        ("ProcessId", ctypes.c_uint32),
        ("TimeStamp", ctypes.c_int64),
        ("ProviderId", _GUID),
        ("EventDescriptor", _EVENT_DESCRIPTOR),
        ("ProcessorTime", ctypes.c_uint64),
        ("ActivityId", _GUID),
    ]


class _EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("EventHeader", _EVENT_HEADER),
        ("BufferContext", ctypes.c_uint32),
        ("ExtendedDataCount", ctypes.c_uint32),
        ("UserDataLength", ctypes.c_uint32),
        ("ExtendedData", ctypes.c_void_p),
        ("UserData", ctypes.c_void_p),
        ("UserContext", ctypes.c_uint32),
    ]


class _EVENT_TRACE_LOGFILEW(ctypes.Structure):
    _fields_ = [
        ("LoggerName", ctypes.c_wchar_p),
        ("LogFileName", ctypes.c_wchar_p),
        ("CurrentTime", ctypes.c_int64),
        ("BuffersRead", ctypes.c_uint32),
        ("ProcessingMode", ctypes.c_uint32),
        ("CurrentEvent", ctypes.c_void_p),
        ("LogfileHeader", ctypes.c_void_p),
        ("BufferSize", ctypes.c_uint32),
        ("Filled", ctypes.c_uint32),
        ("EventsLost", ctypes.c_uint32),
        ("EventRecordCallback", ctypes.c_void_p),
        ("IsKernelTrace", ctypes.c_uint32),
        ("Context", ctypes.c_void_p),
    ]


_EVENT_RECORD_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.POINTER(_EVENT_RECORD))


class _EtwFunctions:
    """Late-bound ``advapi32`` ETW entry points.

    ``ctypes.WinDLL`` only exists on Windows, so the library is loaded on
    first use rather than at import time. That keeps this module
    importable on any platform for unit testing.
    """

    def __init__(self) -> None:
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

        start_trace = self._advapi32.StartTraceW
        start_trace.argtypes = [
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_wchar_p,
            ctypes.POINTER(_EVENT_TRACE_PROPERTIES),
        ]
        start_trace.restype = ctypes.c_uint32
        self.start_trace = start_trace

        open_trace = self._advapi32.OpenTraceW
        open_trace.argtypes = [ctypes.POINTER(_EVENT_TRACE_LOGFILEW)]
        open_trace.restype = ctypes.c_uint64
        self.open_trace = open_trace

        process_trace = self._advapi32.ProcessTrace
        process_trace.argtypes = [
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        process_trace.restype = ctypes.c_uint32
        self.process_trace = process_trace

        control_trace = self._advapi32.ControlTraceW
        control_trace.argtypes = [
            ctypes.c_uint64,
            ctypes.c_wchar_p,
            ctypes.POINTER(_EVENT_TRACE_PROPERTIES),
            ctypes.c_uint32,
        ]
        control_trace.restype = ctypes.c_uint32
        self.control_trace = control_trace

        close_trace = self._advapi32.CloseTrace
        close_trace.argtypes = [ctypes.c_uint64]
        close_trace.restype = ctypes.c_uint32
        self.close_trace = close_trace


class NetworkBandwidthMonitor:
    """Accumulate per-process network bytes from a real-time ETW session.

    The session starts lazily and stays up for the life of the process,
    because starting and stopping the kernel logger on every stats tick
    is expensive. :meth:`sample` reports the kilobytes per second each
    process moved since the previous call, matching the ``nethogs``
    semantics upstream relies on.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._totals: dict[int, int] = {}
        self._last_totals: dict[int, int] = {}
        self._last_time = 0.0
        self._address_filter: frozenset[bytes] | None = None
        self._session_handle: int | None = None
        self._trace_handle: int | None = None
        self._thread: threading.Thread | None = None
        self._callback: Any = None
        self._logfile: _EVENT_TRACE_LOGFILEW | None = None
        self._properties: _EVENT_TRACE_PROPERTIES | None = None
        self._buffer: ctypes.Array | None = None
        self._functions: _EtwFunctions | None = None
        self._started = False
        self._start_failed = False

    @property
    def is_running(self) -> bool:
        return self._started and self._thread is not None and self._thread.is_alive()

    def set_address_filter(self, addresses: frozenset[bytes] | None) -> None:
        """Restrict sampling to events touching the given packed IPs.

        ``None`` (the default) samples every interface.
        """
        self._address_filter = addresses

    def start(self) -> bool:
        """Start the kernel logger session and its consumer thread."""
        if self._started or self._start_failed:
            return self._started

        try:
            self._start()
            self._started = True
        except Exception as err:  # noqa: BLE001 - degrade to no stats
            self._start_failed = True
            logger.warning(
                "Per-process network bandwidth stats need an elevated "
                "session and are disabled: %s",
                err,
            )
        return self._started

    def _start(self) -> None:
        functions = _EtwFunctions()
        self._functions = functions

        properties_size = ctypes.sizeof(_EVENT_TRACE_PROPERTIES)
        logger_name = KERNEL_LOGGER_NAME.encode("utf-16-le") + b"\x00\x00"
        buffer_size = properties_size + len(logger_name) + 16
        buffer = ctypes.create_string_buffer(buffer_size)
        ctypes.memmove(buffer, logger_name, len(logger_name))

        properties = ctypes.cast(
            buffer, ctypes.POINTER(_EVENT_TRACE_PROPERTIES)
        ).contents
        properties.Wnode.BufferSize = buffer_size
        properties.Wnode.HistoricalContext = 0
        properties.Wnode.Guid = _guid_from_string(SYSTEM_TRACE_CONTROL_GUID)
        # WNODE_FLAG_TRACED_GUID on the standalone Flags member.
        properties.Wnode.Flags = WNODE_TRACED_GUID_FLAG
        properties.LogFileMode = REAL_TIME_MODE
        properties.EnableFlags = NETWORK_TCPIP_FLAG
        properties.LoggerNameOffset = properties_size
        self._properties = properties
        self._buffer = buffer

        session_handle = ctypes.c_uint64(0)
        status = functions.start_trace(
            ctypes.byref(session_handle),
            KERNEL_LOGGER_NAME,
            ctypes.byref(properties),
        )
        if status != 0:
            raise OSError(
                status,
                f"StartTraceW for {KERNEL_LOGGER_NAME} failed with status {status}",
            )
        self._session_handle = session_handle.value

        logfile = _EVENT_TRACE_LOGFILEW()
        logfile.LoggerName = KERNEL_LOGGER_NAME
        logfile.ProcessingMode = PROCESS_TRACE_MODE
        self._callback = _EVENT_RECORD_CALLBACK(self._on_record)
        logfile.EventRecordCallback = ctypes.cast(self._callback, ctypes.c_void_p)
        self._logfile = logfile

        trace_handle = functions.open_trace(ctypes.byref(logfile))
        if not trace_handle or trace_handle == INVALID_PROCESSTRACE_HANDLE:
            self._stop_session(functions)
            raise OSError(
                f"OpenTraceW for {KERNEL_LOGGER_NAME} failed with handle {trace_handle}"
            )
        self._trace_handle = trace_handle

        self._thread = threading.Thread(
            target=self._consume,
            name="bandwidth-etw",
            daemon=True,
        )
        self._thread.start()

    def _consume(self) -> None:
        functions = self._functions
        trace_handle = self._trace_handle
        if functions is None or trace_handle is None:
            return
        handles = (ctypes.c_uint64 * 1)(trace_handle)
        try:
            functions.process_trace(handles, 1, None, None)
        except Exception as err:  # noqa: BLE001 - consumer thread must not die loudly
            logger.debug("Bandwidth ETW consumer ended: %s", err)

    def _on_record(self, record_ptr: ctypes.POINTER(_EVENT_RECORD)) -> None:
        """ETW callback; runs on the consumer thread."""
        try:
            record = record_ptr.contents
            self._consume_event(
                record.EventHeader.EventDescriptor.Id,
                record.UserData,
                record.UserDataLength,
            )
        except Exception:  # noqa: BLE001 - never break the trace thread
            pass

    def _consume_event(
        self, event_type: int, user_data: int | None, user_data_length: int
    ) -> None:
        if event_type not in TRANSFER_EVENT_TYPES or not user_data:
            return
        if user_data_length < 8:
            return

        if self._address_filter is not None and not self._address_matches(
            event_type, user_data, user_data_length
        ):
            return

        payload = ctypes.string_at(user_data, 8)
        pid, size = struct.unpack_from("<II", payload)
        if pid and size:
            with self._lock:
                self._totals[pid] = self._totals.get(pid, 0) + size

    def _address_matches(
        self, event_type: int, user_data: int, user_data_length: int
    ) -> bool:
        """Whether an event touches one of the filtered interfaces."""
        if event_type in (SEND_IPV4, RECEIVE_IPV4):
            if user_data_length < 16:
                return False
            payload = ctypes.string_at(user_data, 16)
            destination = payload[8:12]
            source = payload[12:16]
        else:
            if user_data_length < 40:
                return False
            payload = ctypes.string_at(user_data, 40)
            destination = payload[8:24]
            source = payload[24:40]

        assert self._address_filter is not None  # narrowed by the caller
        return destination in self._address_filter or source in self._address_filter

    def sample(self) -> dict[str, dict]:
        """Return kilobytes per second per process since the last call."""
        with self._lock:
            now = time.monotonic()
            if self._last_time == 0.0:
                self._last_totals = dict(self._totals)
                self._last_time = now
                return {}

            elapsed = now - self._last_time
            usages: dict[str, dict] = {}
            if elapsed > 0:
                for pid, total in self._totals.items():
                    delta = total - self._last_totals.get(pid, 0)
                    if delta > 0:
                        usages[str(pid)] = {
                            "bandwidth": round(delta / 1024 / elapsed, 1)
                        }
            self._last_totals = dict(self._totals)
            self._last_time = now
        return usages

    def retain(self, pids: set[str]) -> None:
        """Forget every process that is no longer being reported.

        The kernel logger reports bytes for any process that moves
        them, so the accumulators would otherwise grow for the life
        of the run as short-lived processes come and go.
        """
        keep = {int(pid) for pid in pids if pid.isdigit()}
        with self._lock:
            self._totals = {
                pid: total for pid, total in self._totals.items() if pid in keep
            }
            self._last_totals = {
                pid: total for pid, total in self._last_totals.items() if pid in keep
            }

    def stop(self) -> None:
        """Stop the consumer thread and the kernel logger session."""
        functions = self._functions
        if not self._started:
            return

        # Stopping the session is what makes ProcessTrace return,
        # so it has to come before the consumer handle is closed.
        if self._session_handle is not None and functions is not None:
            self._stop_session(functions)

        trace_handle = self._trace_handle
        if functions is not None and trace_handle is not None:
            try:
                functions.close_trace(trace_handle)
            except Exception:  # noqa: BLE001 - best effort teardown
                pass
            self._trace_handle = None

        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

        self._started = False

    def _stop_session(self, functions: _EtwFunctions) -> None:
        session_handle = self._session_handle
        if session_handle is None or self._properties is None:
            return
        try:
            functions.control_trace(
                session_handle,
                KERNEL_LOGGER_NAME,
                ctypes.byref(self._properties),
                EVENT_TRACE_CONTROL_STOP,
            )
        except Exception:  # noqa: BLE001 - best effort teardown
            pass
        self._session_handle = None


def packed_interface_addresses(prefixes: list[str]) -> frozenset[bytes] | None:
    """Packed IP addresses of the interfaces whose name matches a prefix.

    An empty prefix list means every interface, so it returns ``None`` to
    signal "no filter".
    """
    if not prefixes:
        return None

    import psutil

    addresses: set[bytes] = set()
    wanted = [prefix.casefold() for prefix in prefixes]
    for interface, entries in psutil.net_if_addrs().items():
        if not any(interface.casefold().startswith(prefix) for prefix in wanted):
            continue
        for entry in entries:
            family = entry.family
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            try:
                addresses.add(socket.inet_pton(family, entry.address))
            except OSError:
                continue
    return frozenset(addresses)


_monitor: NetworkBandwidthMonitor | None = None
_monitor_lock = threading.Lock()


def get_network_bandwidth_monitor() -> NetworkBandwidthMonitor:
    """Return the process-wide bandwidth monitor."""
    global _monitor
    with _monitor_lock:
        if _monitor is None:
            _monitor = NetworkBandwidthMonitor()
        return _monitor
