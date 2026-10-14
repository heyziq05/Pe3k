import sqlite3

import pytest

from engine.monitoring.discovery import DiscoveredHost
from engine.monitoring.pinger import PingResult
from engine.services import alert_service as A


def _count(c, **where):
    sql = "SELECT COUNT(*) FROM alerts WHERE 1=1" + "".join(f" AND {k} = ?" for k in where)
    with c.db.session() as conn:
        return conn.execute(sql, list(where.values())).fetchone()[0]


def _detect(c, ip="192.168.1.50", mac="02:11:22:33:44:55"):
    with c.db.transaction() as conn:
        return A.upsert_unknown_device(conn, ip=ip, mac=mac, engine="nmap")


def test_repeated_detection_is_deduplicated(c):
    a1, created1 = _detect(c)
    a2, created2 = _detect(c, ip="192.168.1.51")  # same MAC, new IP (DHCP)
    assert created1 and not created2
    assert a1["id"] == a2["id"] and a2["occurrences"] == 2 and a2["ip_address"] == "192.168.1.51"
    assert _count(c) == 1


def test_ignored_alert_suppresses_new_alerts(c):
    alert, _ = _detect(c)
    c.alerts.set_status(alert["id"], "ignore")
    again, created = _detect(c)
    assert not created and again["status"] == "ignored" and again["occurrences"] == 2
    assert _count(c, status="open") == 0


def test_resolved_alert_reopens_as_new_alert_on_next_detection(c):
    alert, _ = _detect(c)
    c.alerts.set_status(alert["id"], "resolve")
    new, created = _detect(c)
    assert created and new["id"] != alert["id"]
    assert _count(c) == 2 and _count(c, status="open") == 1


def test_missing_mac_dedups_by_ip(c):
    _detect(c, mac=None)
    _, created = _detect(c, mac=None)
    assert not created and _count(c) == 1


def test_database_enforces_single_active_alert(c):
    _detect(c)
    with pytest.raises(sqlite3.IntegrityError):
        with c.db.transaction() as conn:
            conn.execute(
                "INSERT INTO alerts(alert_type, status, dedup_key, message, first_seen, last_seen)"
                " VALUES ('unknown_device', 'open', 'unknown:02:11:22:33:44:55', 'dup', 'x', 'x')"
            )


def test_trust_creates_device_and_closes_alert(c):
    alert, _ = _detect(c)
    device = c.alerts.trust(alert["id"], {"name": "Kid's tablet", "device_type": "tablet"})
    assert device["mac_address"] == "02:11:22:33:44:55" and device["trusted"] == 1
    assert c.alerts.get(alert["id"])["status"] == "trusted"
    # Next scan sees the same MAC: no alert because it's now trusted.
    result = c.scans._process([DiscoveredHost("192.168.1.50", "02:11:22:33:44:55")], "192.168.1.0/24", "nmap")
    assert result["unknown_found"] == 0 and result["matched"] == 1


def test_scan_processing_dedups_across_scans_and_ignores_out_of_range(c):
    hosts = [DiscoveredHost("192.168.1.60", "02:00:00:00:00:60"), DiscoveredHost("10.9.9.9", "02:00:00:00:00:99")]
    r1 = c.scans._process(hosts, "192.168.1.0/24", "scapy")
    r2 = c.scans._process(hosts, "192.168.1.0/24", "scapy")
    assert (r1["new_alerts"], r2["new_alerts"]) == (1, 0)
    assert r1["hosts_found"] == 1  # 10.9.9.9 is outside the authorized range and never recorded
    assert _count(c) == 1


def test_offline_alert_only_after_threshold_and_auto_resolves(c):
    d = c.devices.create({"name": "Printer", "ip_address": "192.168.1.30"})
    fail, ok = PingResult(False, error="timeout"), PingResult(True, 3.0)
    c.monitor.record_results([(d, ok)], threshold=3)
    for _ in range(2):
        c.monitor.record_results([(d, fail)], threshold=3)
    assert _count(c, alert_type="device_offline") == 0  # lost pings, not yet offline
    assert c.devices.get(d["id"])["status"] == "unstable"
    for _ in range(3):
        c.monitor.record_results([(d, fail)], threshold=3)
    assert c.devices.get(d["id"])["status"] == "offline"
    assert _count(c, alert_type="device_offline") == 1  # still one alert after continued failures
    c.monitor.record_results([(d, ok)], threshold=3)
    assert _count(c, alert_type="device_offline", status="resolved") == 1
    assert c.devices.get(d["id"])["status"] == "online"
