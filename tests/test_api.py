from conftest import HDR


def test_pages_render(client):
    for path in ("/", "/devices", "/alerts", "/history", "/bandwidth", "/settings"):
        assert client.get(path, follow_redirects=True).status_code == 200


def test_mutations_require_csrf_header(client):
    r = client.post("/api/devices", json={"name": "x", "ip_address": "192.168.1.5"})
    assert r.status_code == 403


def test_device_crud_and_validation(client):
    r = client.post("/api/devices", json={"name": "Router", "ip_address": "192.168.1.1", "mac_address": "aa:bb:cc:dd:ee:01",
                                          "device_type": "router"}, headers=HDR)
    assert r.status_code == 201
    dev = r.get_json()["device"]
    bad = client.post("/api/devices", json={"name": "", "ip_address": "8.8.8.8"}, headers=HDR)
    assert bad.status_code == 400 and {"name", "ip_address"} <= set(bad.get_json()["fields"])
    upd = client.put(f"/api/devices/{dev['id']}", json={"name": "Main router"}, headers=HDR)
    assert upd.get_json()["device"]["name"] == "Main router"
    assert client.get("/api/devices?search=main").get_json()["devices"][0]["id"] == dev["id"]
    assert client.delete(f"/api/devices/{dev['id']}", headers=HDR).status_code == 200
    assert client.get(f"/api/devices/{dev['id']}").status_code == 404


def test_csv_exports_escape_formulas(client):
    client.post("/api/devices", json={"name": "=HYPERLINK(\"x\")", "ip_address": "192.168.1.7"}, headers=HDR)
    r = client.get("/export/devices.csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    body = r.get_data(as_text=True)
    assert body.startswith("﻿ID,Name,IP address")
    assert "'=HYPERLINK" in body
    for path in ("/export/alerts.csv", "/export/bandwidth.csv", "/export/uptime.csv", "/export/devices/1/history.csv"):
        assert client.get(path).status_code == 200


def test_settings_validation_errors(client):
    r = client.put("/api/settings", json={"discovery_engine": "nmap", "auto_scan_enabled": True}, headers=HDR)
    assert r.status_code == 400 and "scan_authorized_ack" in r.get_json()["fields"]
    ok = client.put("/api/settings", json={"ping_interval_seconds": 30, "failure_threshold": 4}, headers=HDR)
    assert ok.status_code == 200 and ok.get_json()["settings"]["failure_threshold"] == 4


def test_manual_scan_request_in_manual_mode_is_refused(client):
    r = client.post("/api/scan/run", headers=HDR)
    assert r.status_code == 422 and "Manual mode" in r.get_json()["error"]


def test_health_endpoint(client):
    data = client.get("/api/health").get_json()
    assert {"nmap", "scapy", "manual"} <= set(data["engines"])
    assert "Flask" in data["packages"]
