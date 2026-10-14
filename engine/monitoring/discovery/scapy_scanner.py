"""ARP host discovery with Scapy (requires raw-socket privileges; Npcap on Windows)."""
from __future__ import annotations

import ipaddress
import logging
import sys
import threading

from ...validators import normalize_mac
from ..system import IS_WINDOWS, is_admin, npcap_installed, privilege_hint
from .base import BaseScanner, DiscoveredHost, EngineHealth, HealthCheck, ScannerError

log = logging.getLogger("pe3k.scan.scapy")

INSTALL_STEPS = [
    "Install Scapy: pip install scapy",
    "Windows: install Npcap from https://npcap.com (tick “Install Npcap in WinPcap API-compatible Mode”).",
    "Run Pe3k with administrator/root privileges — ARP scanning sends raw Ethernet frames.",
    "Linux alternative to sudo: sudo setcap cap_net_raw,cap_net_admin=eip $(readlink -f $(which python3))",
]

_scapy_lock = threading.Lock()
_scapy_mod = None
_scapy_error: str | None = None


def _load_scapy():
    """Import scapy lazily (it is slow and optional) and cache the outcome."""
    global _scapy_mod, _scapy_error
    with _scapy_lock:
        if _scapy_mod is None and _scapy_error is None:
            try:
                import logging as _logging

                _logging.getLogger("scapy.runtime").setLevel(_logging.ERROR)
                import scapy.all as scapy_all  # noqa: WPS433

                scapy_all.conf.verb = 0
                _scapy_mod = scapy_all
            except Exception as exc:  # ImportError or platform errors
                _scapy_error = f"{type(exc).__name__}: {exc}"
    return _scapy_mod, _scapy_error


class ScapyScanner(BaseScanner):
    name = "scapy"
    label = "Scapy (ARP)"

    def check(self) -> EngineHealth:
        checks: list[HealthCheck] = []
        mod, err = _load_scapy()
        version = getattr(sys.modules.get("scapy"), "__version__", None) if mod else None
        checks.append(HealthCheck("Scapy package", mod is not None, f"Scapy {version} importable" if mod else f"Cannot import scapy ({err})"))
        if IS_WINDOWS:
            npcap = bool(npcap_installed())
            checks.append(HealthCheck("Npcap driver", npcap, "Npcap detected." if npcap else "Npcap is required for Scapy on Windows."))
        admin = is_admin()
        checks.append(
            HealthCheck("Privileges", admin, "Running elevated." if admin else "ARP scanning needs elevated privileges. " + privilege_hint())
        )
        ready = all(c.ok for c in checks if c.level == "error")
        return EngineHealth(self.name, self.label, ready, "Ready" if ready else "Not ready", checks, INSTALL_STEPS, version)

    def scan(self, subnet: str, timeout: int) -> list[DiscoveredHost]:
        mod, err = _load_scapy()
        if mod is None:
            raise ScannerError(f"Scapy is not available: {err}")
        network = ipaddress.ip_network(subnet, strict=False)
        wait = max(2, min(10, int(timeout) // 3))
        result: dict = {}

        def worker():
            try:
                first = str(next(iter(network.hosts()), network.network_address))
                iface = mod.conf.route.route(first)[0]
                packet = mod.Ether(dst="ff:ff:ff:ff:ff:ff") / mod.ARP(pdst=str(network))
                answered, _ = mod.srp(packet, timeout=wait, retry=1, iface=iface, verbose=0)
                result["answered"] = answered
            except PermissionError:
                result["error"] = "Permission denied sending raw packets. " + privilege_hint()
            except OSError as exc:
                result["error"] = f"Network error during ARP scan: {exc}"
            except Exception as exc:  # scapy raises a variety of errors on misconfigured hosts
                result["error"] = f"{type(exc).__name__}: {exc}"

        thread = threading.Thread(target=worker, name="pe3k-scapy-scan", daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            raise ScannerError(f"Scapy ARP scan did not finish within {timeout}s.")
        if "error" in result:
            raise ScannerError(result["error"])

        hosts: dict[str, DiscoveredHost] = {}
        for _, received in result.get("answered", []):
            ip = received.psrc
            if ipaddress.ip_address(ip) not in network:
                continue
            try:
                mac = normalize_mac(received.hwsrc)
            except ValueError:
                mac = None
            vendor = None
            try:
                vendor = mod.conf.manufdb._get_manuf(received.hwsrc)  # best effort
                if vendor and vendor.replace(":", "").lower() == received.hwsrc.replace(":", "").lower():
                    vendor = None
            except Exception:
                vendor = None
            hosts[ip] = DiscoveredHost(ip=ip, mac=mac, vendor=vendor)
        return list(hosts.values())
