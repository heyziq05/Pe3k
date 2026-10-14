"""Read the operating system's ARP / neighbour cache.

The OS remembers the MAC address of every LAN device it has exchanged traffic
with recently. Merging that list into each scan catches devices that were
awake a moment ago but asleep during the scan itself (typically iPhones, which
power down Wi-Fi when locked). It needs no admin rights and sends no packets.

* Windows: ``arp -a``
* Linux:   ``ip neigh show`` (falls back to ``arp -an``)
* macOS:   ``arp -an``
"""
from __future__ import annotations

import ipaddress
import logging
import re
import shutil
import subprocess

from ...validators import normalize_mac
from ..system import IS_WINDOWS, no_window_flags
from .base import DiscoveredHost

log = logging.getLogger("pe3k.scan.arp")

_WIN_LINE = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})\s+(\w+)", re.M)
_LINUX_LINE = re.compile(
    r"^(\d{1,3}(?:\.\d{1,3}){3})\s+.*?lladdr\s+([0-9a-fA-F:]{11,17})(?:\s+\w+)*?\s+([A-Z]+)\s*$", re.M
)
_BSD_LINE = re.compile(r"\((\d{1,3}(?:\.\d{1,3}){3})\)\s+at\s+([0-9a-fA-F:]{11,17})\s", re.M)

# Neighbour states that do not represent a real, recently seen device.
_BAD_LINUX_STATES = {"FAILED", "INCOMPLETE", "NOARP"}


def _pad_mac(mac: str) -> str:
    """macOS prints ``a4:2b:b0:1:2:3``; pad each octet to two digits."""
    parts = re.split(r"[:-]", mac)
    return ":".join(p.zfill(2) for p in parts) if len(parts) == 6 else mac


def _usable_mac(mac: str | None) -> str | None:
    try:
        norm = normalize_mac(_pad_mac(mac or ""))
    except ValueError:
        return None
    if norm is None:
        return None
    first_octet = int(norm[:2], 16)
    if first_octet & 0x01:  # multicast / broadcast addresses (01:00:5E:…, 33:33:…, FF:…)
        return None
    return norm


def parse_windows(text: str) -> list[tuple[str, str]]:
    # Skip "static" rows (localised: statisch, statique, estático…) — they are broadcast/multicast entries.
    return [(ip, mac) for ip, mac, kind in _WIN_LINE.findall(text) if not kind.lower().startswith(("stat", "est"))]


def parse_linux(text: str) -> list[tuple[str, str]]:
    return [(ip, mac) for ip, mac, state in _LINUX_LINE.findall(text) if state not in _BAD_LINUX_STATES]


def parse_bsd(text: str) -> list[tuple[str, str]]:
    return [(ip, mac) for ip, mac in _BSD_LINE.findall(text) if "incomplete" not in mac]


def parse_arp_output(text: str) -> list[tuple[str, str]]:
    """Parse output from any supported platform (format is detected from the text)."""
    if "lladdr" in text:
        return parse_linux(text)
    if _WIN_LINE.search(text):
        return parse_windows(text)
    return parse_bsd(text)


def _run(cmd: list[str], timeout: int = 5) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          creationflags=no_window_flags(), errors="replace")
    return proc.stdout or ""


def read_arp_cache() -> str:
    """Return raw neighbour-table text, or an empty string if no tool is available."""
    try:
        if IS_WINDOWS:
            return _run(["arp", "-a"])
        if shutil.which("ip"):
            return _run(["ip", "neigh", "show"])
        if shutil.which("arp"):
            return _run(["arp", "-an"])
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("could not read ARP cache", extra={"event": "arp_cache_error", "error": str(exc)})
    return ""


def arp_cache_hosts(subnet: str, raw: str | None = None) -> list[DiscoveredHost]:
    """Hosts from the OS neighbour cache that fall inside the authorized subnet."""
    network = ipaddress.ip_network(subnet, strict=False)
    text = read_arp_cache() if raw is None else raw
    hosts: dict[str, DiscoveredHost] = {}
    for ip, mac in parse_arp_output(text):
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr not in network or addr in (network.network_address, network.broadcast_address):
            continue
        norm = _usable_mac(mac)
        if norm:
            hosts[ip] = DiscoveredHost(ip=ip, mac=norm, vendor=None, hostname=None)
    return list(hosts.values())
