import pytest

from engine.monitoring import discovery
from engine.monitoring.discovery import DemoScanner, ManualMode, NmapScanner, ScannerError, ScapyScanner, get_scanner
from engine.monitoring.discovery.nmap_scanner import parse_nmap_xml
from engine.monitoring.scan_service import ScanInProgress


def test_get_scanner_returns_selected_engine():
    assert isinstance(get_scanner("nmap", {}), NmapScanner)
    assert isinstance(get_scanner("scapy", {}), ScapyScanner)
    assert isinstance(get_scanner("manual", {}), ManualMode)
    assert isinstance(get_scanner("demo", {}, demo_mode=True), DemoScanner)


def test_get_scanner_rejects_unknown_or_disallowed():
    with pytest.raises(ValueError):
        get_scanner("masscan", {})
    with pytest.raises(ValueError):
        get_scanner("demo", {}, demo_mode=False)


def test_manual_mode_never_scans():
    with pytest.raises(ScannerError):
        ManualMode().scan("192.168.1.0/24", 10)
    assert ManualMode().check().ready


def test_nmap_missing_reports_not_ready(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    health = NmapScanner("").check()
    assert not health.ready and health.instructions
    assert not NmapScanner(str(tmp_path / "nmap.exe")).check().ready


def _configure(c, **values):
    base = {"discovery_engine": "nmap", "authorized_subnet": "192.168.1.0/24", "scan_authorized_ack": True}
    base.update(values)
    c.settings.set_raw(base)


def test_unavailable_engine_fails_without_fallback(c, monkeypatch):
    _configure(c, nmap_path="")
    monkeypatch.setattr("shutil.which", lambda _name: None)

    def boom(*_a, **_k):
        raise AssertionError("Scapy must never be used as a silent fallback")

    monkeypatch.setattr(ScapyScanner, "scan", boom)
    result = c.scans.run("manual")
    assert result["status"] == "error" and "Nmap" in result["error"]
    log = c.scans.recent(1)[0]
    assert log["engine"] == "nmap" and log["status"] == "error"


def test_scan_blocked_without_authorization(c):
    _configure(c, scan_authorized_ack=False)
    with pytest.raises(ScannerError, match="authorized"):
        c.scans.start_async("manual")


def test_scan_blocked_in_manual_mode(c):
    _configure(c, discovery_engine="manual")
    with pytest.raises(ScannerError, match="Manual mode"):
        c.scans.start_async("manual")


def test_scan_rejects_invalid_or_oversized_subnet(c):
    _configure(c, authorized_subnet="10.0.0.0/8")
    with pytest.raises(ScannerError, match="too large"):
        c.scans.preflight(c.settings.all())


def test_overlapping_scans_are_prevented(c):
    _configure(c)
    c.scans._lock.acquire()
    try:
        with pytest.raises(ScanInProgress):
            c.scans.run("scheduled")
        with pytest.raises(ScanInProgress):
            c.scans.start_async("manual")
    finally:
        c.scans._lock.release()


def test_successful_scan_uses_selected_engine(c, monkeypatch):
    _configure(c)
    from engine.monitoring.discovery.base import EngineHealth

    monkeypatch.setattr(NmapScanner, "check", lambda self: EngineHealth("nmap", "Nmap", True, "Ready"))
    monkeypatch.setattr(NmapScanner, "scan", lambda self, subnet, timeout: [discovery.DiscoveredHost("192.168.1.9", "02:AA:BB:CC:DD:09")])
    result = c.scans.run("manual")
    assert result["status"] == "success" and result["unknown_found"] == 1
    assert c.scans.recent(1)[0]["engine"] == "nmap"


NMAP_XML = """<?xml version="1.0"?><nmaprun>
<host><status state="up"/><address addr="192.168.1.1" addrtype="ipv4"/><address addr="a4:2b:b0:11:22:01" addrtype="mac" vendor="TP-Link"/>
<hostnames><hostname name="router.lan"/></hostnames></host>
<host><status state="down"/><address addr="192.168.1.2" addrtype="ipv4"/></host>
<host><status state="up"/><address addr="192.168.1.3" addrtype="ipv4"/></host>
<host><status state="up"/><address addr="10.0.0.3" addrtype="ipv4"/></host>
</nmaprun>"""


def test_parse_nmap_xml():
    import ipaddress

    hosts = parse_nmap_xml(NMAP_XML, ipaddress.ip_network("192.168.1.0/24"))
    assert [(h.ip, h.mac, h.vendor, h.hostname) for h in hosts] == [
        ("192.168.1.1", "A4:2B:B0:11:22:01", "TP-Link", "router.lan"),
        ("192.168.1.3", None, None, None),
    ]
    with pytest.raises(ScannerError):
        parse_nmap_xml("<not xml")
