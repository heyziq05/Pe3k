"""Discovery-engine selection.

The engine is whatever the user picked in Settings. Pe3k never substitutes a
different engine when the chosen one is unavailable — the scan fails with a
clear, actionable error instead.
"""
from __future__ import annotations

import ipaddress
import time

from .base import BaseScanner, DiscoveredHost, EngineHealth, HealthCheck, ScannerError
from .nmap_scanner import NmapScanner
from .scapy_scanner import ScapyScanner

ENGINE_LABELS = {"nmap": "Nmap", "scapy": "Scapy (ARP)", "manual": "Manual", "demo": "Demo (simulated)"}


class ManualMode(BaseScanner):
    """Placeholder engine: automatic discovery disabled, manual device entry only."""

    name = "manual"
    label = "Manual"

    def check(self) -> EngineHealth:
        return EngineHealth(
            self.name, self.label, True, "Automatic scanning disabled",
            [HealthCheck("Network scanning", True, "Disabled — only manually entered devices are monitored.", "info")],
            ["No dependencies required. Add devices on the Trusted Devices page."], sees_mac=False,
        )

    def scan(self, subnet: str, timeout: int) -> list[DiscoveredHost]:
        raise ScannerError("Manual mode is selected: automatic network scanning is disabled.")


class DemoScanner(BaseScanner):
    """Demo-mode engine: returns simulated hosts. Only offered when PE3K_DEMO_MODE=true."""

    name = "demo"
    label = "Demo (simulated)"

    def __init__(self, known_hosts_provider=None):
        self.known_hosts_provider = known_hosts_provider or (lambda: [])

    def check(self) -> EngineHealth:
        return EngineHealth(
            self.name, self.label, True, "Simulated scanner (no packets sent)",
            [HealthCheck("Simulation", True, "Demo mode — discovery results are generated, not real.", "info")],
            ["Set PE3K_DEMO_MODE=false and choose Nmap or Scapy for real discovery."],
        )

    def scan(self, subnet: str, timeout: int) -> list[DiscoveredHost]:
        network = ipaddress.ip_network(subnet, strict=False)
        hosts = [DiscoveredHost(ip=d["ip_address"], mac=d.get("mac_address"), hostname=None)
                 for d in self.known_hosts_provider()
                 if d.get("status") != "offline" and ipaddress.ip_address(d["ip_address"]) in network]
        base = int(network.network_address)
        size = max(1, network.num_addresses - 2)
        # One persistent stranger and one that appears now and then.
        hosts.append(DiscoveredHost(ip=str(ipaddress.ip_address(base + 1 + (77 % size))), mac="3E:A1:5C:7D:22:9B",
                                    hostname="unknown-android.lan", vendor="(randomised MAC)"))
        if int(time.time() // 900) % 3 == 0:
            hosts.append(DiscoveredHost(ip=str(ipaddress.ip_address(base + 1 + (143 % size))), mac="B8:27:EB:41:0C:5D",
                                        hostname=None, vendor="Raspberry Pi Foundation"))
        return hosts


def get_scanner(engine: str, settings: dict, demo_mode: bool = False, known_hosts_provider=None) -> BaseScanner:
    """Return the scanner for the selected engine. Raises ``ValueError`` for unknown/disallowed engines."""
    engine = (engine or "").strip().lower()
    if engine == "nmap":
        return NmapScanner(settings.get("nmap_path", ""))
    if engine == "scapy":
        return ScapyScanner()
    if engine == "manual":
        return ManualMode()
    if engine == "demo":
        if not demo_mode:
            raise ValueError("The demo engine is only available when PE3K_DEMO_MODE=true")
        return DemoScanner(known_hosts_provider)
    raise ValueError(f"Unknown discovery engine '{engine}'")


__all__ = [
    "BaseScanner", "DemoScanner", "DiscoveredHost", "EngineHealth", "HealthCheck", "ManualMode", "NmapScanner",
    "ScannerError", "ScapyScanner", "ENGINE_LABELS", "get_scanner",
]
