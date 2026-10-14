from conftest import HDR
from engine.monitoring.pinger import PingResult
from engine.services.settings_service import SIMPLE_PRESET


def test_simple_mode_applies_presets_and_keeps_pro_values(c):
    c.settings.update({"settings_mode": "pro", "ping_interval_seconds": 120, "failure_threshold": 7})
    assert c.settings.all()["failure_threshold"] == 7
    eff = c.settings.update({"settings_mode": "simple"})
    assert eff["failure_threshold"] == SIMPLE_PRESET["failure_threshold"]
    assert eff["ping_interval_seconds"] == SIMPLE_PRESET["ping_interval_seconds"]
    assert c.settings.stored()["failure_threshold"] == 7  # pro value preserved
    assert c.settings.update({"settings_mode": "pro"})["failure_threshold"] == 7


def test_simple_mode_blocks_advanced_changes(client):
    assert client.put("/api/settings", json={"settings_mode": "simple"}, headers=HDR).status_code == 200
    r = client.put("/api/settings", json={"ping_retries": 5}, headers=HDR)
    assert r.status_code == 400 and "Simple mode" in r.get_json()["fields"]["ping_retries"]
    # basic settings still editable in simple mode
    ok = client.put("/api/settings", json={"discovery_engine": "nmap", "authorized_subnet": "192.168.0.0/24"}, headers=HDR)
    assert ok.status_code == 200 and ok.get_json()["settings"]["authorized_subnet"] == "192.168.0.0/24"


def test_mode_change_notifies_listeners(c):
    seen = []
    c.settings.on_change(lambda keys: seen.append(keys))
    c.settings.update({"settings_mode": "pro", "ping_interval_seconds": 120})
    c.settings.update({"settings_mode": "simple"})
    assert "ping_interval_seconds" in seen[-1]


def test_get_settings_exposes_presets(client):
    d = client.get("/api/settings").get_json()
    assert d["simple_preset"]["ping_retries"] == SIMPLE_PRESET["ping_retries"]
    assert "ping_retries" in d["advanced_keys"] and "pro_settings" in d


def test_reset_settings_keeps_devices(c, client):
    c.devices.create({"name": "Router", "ip_address": "192.168.0.1"})
    c.settings.update({"settings_mode": "pro", "ping_retries": 5, "authorized_subnet": "192.168.0.0/24"})
    assert client.post("/api/reset", json={"scope": "settings"}, headers=HDR).status_code == 400  # no confirmation
    r = client.post("/api/reset", json={"scope": "settings", "confirm": True}, headers=HDR)
    assert r.status_code == 200
    s = c.settings.all()
    assert s["authorized_subnet"] == "" and s["ping_retries"] == 2
    assert c.devices.counts()["total"] == 1


def test_factory_reset_requires_typed_confirmation_and_wipes_everything(c, client):
    d = c.devices.create({"name": "Router", "ip_address": "192.168.0.1"})
    c.monitor.record_results([(d, PingResult(True, 1.0))], 3)
    c.settings.update({"authorized_subnet": "192.168.0.0/24"})
    bad = client.post("/api/reset", json={"scope": "all", "confirm": "yes"}, headers=HDR)
    assert bad.status_code == 400 and "confirm" in bad.get_json()["fields"]
    assert c.devices.counts()["total"] == 1
    r = client.post("/api/reset", json={"scope": "all", "confirm": "RESET"}, headers=HDR)
    assert r.status_code == 200 and r.get_json()["deleted"]["devices"] == 1
    assert c.devices.counts()["total"] == 0
    with c.db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM monitor_logs").fetchone()[0] == 0
    assert c.settings.all()["authorized_subnet"] == ""
    # ids restart and the app keeps working
    assert c.devices.create({"name": "New", "ip_address": "192.168.0.2"})["id"] == 1


def test_factory_reset_blocked_during_scan(c, client):
    c.scans._lock.acquire()
    try:
        r = client.post("/api/reset", json={"scope": "all", "confirm": "RESET"}, headers=HDR)
        assert r.status_code == 409
    finally:
        c.scans._lock.release()
