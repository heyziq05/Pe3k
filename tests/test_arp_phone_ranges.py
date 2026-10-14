import sqlite3

import pytest

from conftest import HDR
from engine.db import Database
from engine.monitoring.discovery import DiscoveredHost
from engine.monitoring.discovery.arp_cache import arp_cache_hosts
from engine.monitoring.monitor import ping_profile
from engine.monitoring.pinger import PingResult
from engine.monitoring.scan_service import merge_arp_cache
from engine.services import alert_service as A
from engine.timeutil import resolve_range

WINDOWS_ARP = """
Interface: 192.168.0.105 --- 0x5
  Internet Address      Physical Address      Type
  192.168.0.1           a4-2b-b0-11-22-01     dynamic
  192.168.0.23          3e-a1-5c-7d-22-9b     dynamic
  192.168.0.255         ff-ff-ff-ff-ff-ff     static
  224.0.0.22            01-00-5e-00-00-16     static
  10.0.0.5              00-11-22-33-44-55     dynamic
"""
LINUX_NEIGH = """192.168.0.1 dev wlan0 lladdr a4:2b:b0:11:22:01 router REACHABLE
192.168.0.23 dev wlan0 lladdr 3e:a1:5c:7d:22:9b STALE
192.168.0.40 dev wlan0  FAILED
fe80::1 dev wlan0 lladdr a4:2b:b0:11:22:01 router STALE
"""
MAC_ARP = """? (192.168.0.1) at a4:2b:b0:11:22:1 on en0 ifscope [ethernet]
? (192.168.0.23) at 3e:a1:5c:7d:22:9b on en0 ifscope [ethernet]
? (192.168.0.50) at (incomplete) on en0 ifscope [ethernet]
"""


@pytest.mark.parametrize("raw", [WINDOWS_ARP, LINUX_NEIGH, MAC_ARP])
def test_arp_cache_parsing_all_platforms(raw):
    hosts = arp_cache_hosts("192.168.0.0/24", raw)
    assert {(h.ip, h.mac) for h in hosts} == {("192.168.0.1", "A4:2B:B0:11:22:01"), ("192.168.0.23", "3E:A1:5C:7D:22:9B")}


def test_merge_adds_sleepers_and_fills_missing_macs():
    scanned = [DiscoveredHost("192.168.0.1", None, "router.lan"), DiscoveredHost("192.168.0.30", "02:00:00:00:00:30")]
    cached = [DiscoveredHost("192.168.0.1", "A4:2B:B0:11:22:01"), DiscoveredHost("192.168.0.23", "3E:A1:5C:7D:22:9B")]
    merged, added = merge_arp_cache(scanned, cached)
    by_ip = {h.ip: h for h in merged}
    assert added == 1
    assert by_ip["192.168.0.1"].mac == "A4:2B:B0:11:22:01" and by_ip["192.168.0.1"].hostname == "router.lan"
    assert by_ip["192.168.0.23"].source == "arp-cache"
    assert by_ip["192.168.0.30"].source is None


def test_cache_only_device_alert_is_labelled(c):
    c.scans._process([DiscoveredHost("192.168.0.23", "3E:A1:5C:7D:22:9B", source="arp-cache")], "192.168.0.0/24", "scapy")
    assert c.alerts.list()[0]["engine"] == "scapy+arp-cache"


def test_phone_profile_is_gentler(c):
    cfg = c.settings.all()
    phone = ping_profile({"device_type": "phone"}, cfg)
    laptop = ping_profile({"device_type": "laptop"}, cfg)
    assert phone.name == "phone" and phone.timeout > laptop.timeout and phone.retries > laptop.retries
    assert phone.threshold > laptop.threshold
    cfg["phone_tuning_enabled"] = False
    assert ping_profile({"device_type": "phone"}, cfg).name == "default"


def test_phone_not_offline_at_normal_threshold(c):
    phone = c.devices.create({"name": "iPhone", "ip_address": "192.168.0.23", "device_type": "phone"})
    laptop = c.devices.create({"name": "Laptop", "ip_address": "192.168.0.24", "device_type": "laptop"})
    cfg = c.settings.all()
    th = {phone["id"]: ping_profile(phone, cfg).threshold, laptop["id"]: ping_profile(laptop, cfg).threshold}
    for _ in range(4):
        c.monitor.record_results([(phone, PingResult(False)), (laptop, PingResult(False))], 3, True, th)
    assert c.devices.get(laptop["id"])["status"] == "offline"
    assert c.devices.get(phone["id"])["status"] != "offline"


def test_phone_settings_must_fit_ping_interval(client):
    r = client.put("/api/settings", json={"phone_ping_timeout_seconds": 10, "phone_ping_retries": 8,
                                          "ping_interval_seconds": 30}, headers=HDR)
    assert r.status_code == 400 and "phone_ping_retries" in r.get_json()["fields"]


def test_resolve_range():
    assert resolve_range("all") == (None, None, "all")
    start, end, label = resolve_range("1h")
    assert start and end is None and label == "1h"
    assert resolve_range("custom", "2026-01-01T00:00:00.000Z", "2026-01-02T00:00:00Z") == (
        "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "custom")
    with pytest.raises(ValueError):
        resolve_range("custom", "2026-01-02T00:00:00Z", "2026-01-01T00:00:00Z")
    with pytest.raises(ValueError):
        resolve_range("3y")


def _alert(c, mac, first, last):
    with c.db.transaction() as conn:
        A.upsert_unknown_device(conn, ip="192.168.0.9", mac=mac, engine="nmap", seen_at=first)
        A.upsert_unknown_device(conn, ip="192.168.0.9", mac=mac, engine="nmap", seen_at=last)


def test_alert_list_and_export_honour_time_range(c, client):
    _alert(c, "02:00:00:00:00:01", "2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z")   # old
    _alert(c, "02:00:00:00:00:02", "2099-01-01T00:00:00Z", "2099-01-01T00:00:00Z")   # "recent" (future-dated)
    assert len(client.get("/api/alerts?status=all&window=all").get_json()["alerts"]) == 2
    assert len(client.get("/api/alerts?status=all&window=24h").get_json()["alerts"]) == 1
    r = client.get("/api/alerts?status=all&window=custom&since=2019-12-31T00:00:00Z&until=2020-01-02T00:00:00Z")
    assert [a["mac_address"] for a in r.get_json()["alerts"]] == ["02:00:00:00:00:01"]
    csv = client.get("/export/alerts.csv?status=all&window=custom&since=2019-12-31T00:00:00Z&until=2020-01-02T00:00:00Z")
    body = csv.get_data(as_text=True)
    assert "02:00:00:00:00:01" in body and "02:00:00:00:00:02" not in body
    assert "alerts-all-custom" in csv.headers["Content-Disposition"]
    assert client.get("/export/alerts.csv?window=bogus").status_code == 400
    assert client.get("/api/alerts?window=bogus").status_code == 400


def test_old_database_gets_migrated(tmp_path):
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE scan_logs (id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, engine TEXT NOT NULL,"
                 " subnet TEXT, trigger TEXT NOT NULL DEFAULT 'scheduled', status TEXT NOT NULL, hosts_found INTEGER NOT NULL DEFAULT 0,"
                 " unknown_found INTEGER NOT NULL DEFAULT 0, duration_ms INTEGER, error TEXT)")
    conn.commit()
    conn.close()
    Database(path).init_schema()
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(scan_logs)")}
    assert "cached_found" in cols
