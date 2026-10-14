"""Host discovery with a locally installed Nmap executable (``nmap -sn``)."""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

from ...validators import normalize_mac
from ..system import IS_WINDOWS, is_admin, no_window_flags, npcap_installed, privilege_hint
from .base import BaseScanner, DiscoveredHost, EngineHealth, HealthCheck, ScannerError

log = logging.getLogger("pe3k.scan.nmap")

INSTALL_STEPS = [
    "Download Nmap from https://nmap.org/download.html (Windows installer includes Npcap — keep it ticked).",
    "Make sure nmap is on your PATH (run `nmap --version` in a new terminal) or set the full path to nmap/nmap.exe in Settings.",
    "Linux: sudo apt install nmap  •  macOS: brew install nmap",
    "For MAC addresses (needed for unknown-device matching) run Pe3k with administrator/root privileges.",
]


class NmapScanner(BaseScanner):
    name = "nmap"
    label = "Nmap"

    def __init__(self, configured_path: str = ""):
        self.configured_path = (configured_path or "").strip()

    def resolve_path(self) -> str | None:
        if self.configured_path:
            return self.configured_path if os.path.isfile(self.configured_path) else None
        return shutil.which("nmap")

    def check(self) -> EngineHealth:
        checks: list[HealthCheck] = []
        path = self.resolve_path()
        version = None
        if not path:
            where = f"at {self.configured_path}" if self.configured_path else "on PATH"
            checks.append(HealthCheck("Nmap executable", False, f"Nmap was not found {where}."))
            return EngineHealth(self.name, self.label, False, "Nmap is not installed or not found.", checks, INSTALL_STEPS)
        try:
            proc = subprocess.run(
                [path, "--version"], capture_output=True, text=True, timeout=10, creationflags=no_window_flags(), errors="replace"
            )
            match = re.search(r"Nmap version ([\w.]+)", proc.stdout or "")
            version = match.group(1) if match else None
            ok = proc.returncode == 0 and version is not None
            checks.append(HealthCheck("Nmap executable", ok, f"{path} (version {version})" if ok else f"{path} did not run correctly"))
        except (OSError, subprocess.SubprocessError) as exc:
            checks.append(HealthCheck("Nmap executable", False, f"Could not run {path}: {exc}"))
            return EngineHealth(self.name, self.label, False, "Nmap could not be executed.", checks, INSTALL_STEPS)

        admin = is_admin()
        checks.append(
            HealthCheck(
                "Privileges", admin,
                "Running elevated: ARP discovery and MAC addresses available." if admin
                else "Not elevated: Nmap will use TCP/ICMP probes and cannot report MAC addresses. "
                     "Unknown devices are then matched by IP address. " + privilege_hint(),
                level="warning",
            )
        )
        if IS_WINDOWS:
            npcap = bool(npcap_installed())
            checks.append(
                HealthCheck("Npcap driver", npcap, "Npcap detected." if npcap else
                            "Npcap not detected — reinstall Nmap and keep the Npcap option ticked.", level="warning")
            )
        ready = all(c.ok for c in checks if c.level == "error")
        summary = "Ready" if ready and admin else ("Ready with limitations" if ready else "Not ready")
        return EngineHealth(self.name, self.label, ready, summary, checks, INSTALL_STEPS, version, sees_mac=admin)

    def scan(self, subnet: str, timeout: int) -> list[DiscoveredHost]:
        path = self.resolve_path()
        if not path:
            raise ScannerError("Nmap executable not found. See Settings → Dependency health.")
        network = ipaddress.ip_network(subnet, strict=False)  # re-validate: never pass unvalidated text
        host_timeout = max(5, int(timeout) // 2)
        cmd = [path, "-sn", "-oX", "-", "--host-timeout", f"{host_timeout}s", "--max-retries", "1", str(network)]
        log.info("nmap scan starting", extra={"event": "scan_cmd", "engine": "nmap", "subnet": str(network)})
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, creationflags=no_window_flags(), errors="replace"
            )
        except subprocess.TimeoutExpired:
            raise ScannerError(f"Nmap did not finish within {timeout}s. Increase the scan timeout or use a smaller subnet.") from None
        except OSError as exc:
            raise ScannerError(f"Could not start Nmap: {exc}") from exc
        if proc.returncode != 0:
            err = (proc.stderr or "").strip().splitlines()
            raise ScannerError(f"Nmap exited with code {proc.returncode}: {err[-1] if err else 'no error output'}")
        return parse_nmap_xml(proc.stdout, network)


def parse_nmap_xml(xml_text: str, network: ipaddress.IPv4Network | None = None) -> list[DiscoveredHost]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ScannerError(f"Could not parse Nmap output: {exc}") from exc
    hosts: list[DiscoveredHost] = []
    for host in root.findall("host"):
        status = host.find("status")
        if status is None or status.get("state") != "up":
            continue
        ip = mac = vendor = hostname = None
        for addr in host.findall("address"):
            kind = addr.get("addrtype")
            if kind == "ipv4":
                ip = addr.get("addr")
            elif kind == "mac":
                try:
                    mac = normalize_mac(addr.get("addr"))
                except ValueError:
                    mac = None
                vendor = addr.get("vendor")
        hn = host.find("hostnames/hostname")
        if hn is not None:
            hostname = hn.get("name")
        if not ip:
            continue
        if network is not None and ipaddress.ip_address(ip) not in network:
            continue
        hosts.append(DiscoveredHost(ip=ip, mac=mac, hostname=hostname, vendor=vendor))
    return hosts
