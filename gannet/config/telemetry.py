from pydantic import Field

from .base import FrigateBaseModel

__all__ = ["TelemetryConfig", "StatsConfig"]


class StatsConfig(FrigateBaseModel):
    nvidia_gpu_stats: bool = Field(
        default=True,
        title="NVIDIA GPU stats",
        description="Collect utilization, encoder, decoder, memory, and temperature through NVML when an NVIDIA GPU is present.",
    )
    intel_gpu_stats: bool = Field(
        default=True,
        title="Intel GPU stats",
        description="Collect utilization and memory through Windows WMI performance counters when an Intel GPU is present.",
    )
    amd_gpu_stats: bool = Field(
        default=True,
        title="AMD GPU stats",
        description="Collect utilization and memory through Windows WMI performance counters when an AMD GPU is present.",
    )
    network_bandwidth: bool = Field(
        default=False,
        title="Network bandwidth",
        description="Enable per-process network bandwidth monitoring for camera ffmpeg processes and go2rtc (requires an elevated session).",
    )


class TelemetryConfig(FrigateBaseModel):
    network_interfaces: list[str] = Field(
        default=[],
        title="Network interfaces",
        description="List of network interface name prefixes to monitor for bandwidth statistics. Empty monitors every interface.",
    )
    stats: StatsConfig = Field(
        default_factory=StatsConfig,
        title="System stats",
        description="Native Windows hardware-statistics options.",
    )
    version_check: bool = Field(
        default=True,
        title="Version check",
        description="Enable an outbound check to detect if a newer application version is available.",
    )
