import pytest

from engine.validators import (
    ValidationError, normalize_mac, validate_device_payload, validate_ip, validate_settings_payload, validate_subnet,
)

BASE_SETTINGS = {"discovery_engine": "manual", "auto_scan_enabled": False, "scan_authorized_ack": False,
                 "authorized_subnet": "", "strict_scope": True, "scan_interval_seconds": 300, "scan_timeout_seconds": 60}


@pytest.mark.parametrize("raw", ["aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", "aabb.ccdd.eeff", " aabbccddeeff "])
def test_mac_normalisation(raw):
    assert normalize_mac(raw) == "AA:BB:CC:DD:EE:FF"


@pytest.mark.parametrize("raw", ["zz:bb:cc:dd:ee:ff", "aa:bb:cc", "ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"])
def test_mac_rejects_invalid(raw):
    with pytest.raises(ValueError):
        normalize_mac(raw)


def test_mac_empty_is_none():
    assert normalize_mac("") is None and normalize_mac(None) is None


def test_ip_strict_scope_allows_private_only():
    assert validate_ip("192.168.1.10") == "192.168.1.10"
    assert validate_ip("10.0.0.1") == "10.0.0.1"
    with pytest.raises(ValueError, match="Strict scope"):
        validate_ip("8.8.8.8", strict_scope=True)
    assert validate_ip("8.8.8.8", strict_scope=False) == "8.8.8.8"


@pytest.mark.parametrize("raw", ["", "999.1.1.1", "hello", "224.0.0.1", "0.0.0.0", "255.255.255.255"])
def test_ip_rejects_bad(raw):
    with pytest.raises(ValueError):
        validate_ip(raw, strict_scope=False)


def test_subnet_rules():
    assert validate_subnet("192.168.1.77/24") == "192.168.1.0/24"
    with pytest.raises(ValueError, match="too large"):
        validate_subnet("10.0.0.0/16", strict_scope=True)
    assert validate_subnet("10.0.0.0/16", strict_scope=False) == "10.0.0.0/16"
    with pytest.raises(ValueError, match="too large"):
        validate_subnet("10.0.0.0/8", strict_scope=False)
    with pytest.raises(ValueError, match="private"):
        validate_subnet("8.8.8.0/24", strict_scope=True)
    with pytest.raises(ValueError):
        validate_subnet("fd00::/64")
    with pytest.raises(ValueError):
        validate_subnet("not-a-subnet")


def test_device_payload_valid_and_cleaned():
    out = validate_device_payload({"name": "  Router ", "ip_address": "192.168.1.1", "mac_address": "aa-bb-cc-dd-ee-01",
                                   "device_type": "ROUTER", "trusted": "true"})
    assert out == {"name": "Router", "ip_address": "192.168.1.1", "mac_address": "AA:BB:CC:DD:EE:01",
                   "device_type": "router", "trusted": 1, "monitoring_enabled": 1, "notes": ""}


def test_device_payload_collects_all_errors():
    with pytest.raises(ValidationError) as exc:
        validate_device_payload({"name": "", "ip_address": "nope", "mac_address": "xx", "device_type": "toaster"})
    assert set(exc.value.errors) == {"name", "ip_address", "mac_address", "device_type"}


def test_device_partial_update_only_validates_given_fields():
    assert validate_device_payload({"name": "New"}, partial=True) == {"name": "New"}


def test_settings_auto_scan_requires_subnet_and_ack():
    with pytest.raises(ValidationError) as exc:
        validate_settings_payload({"discovery_engine": "nmap", "auto_scan_enabled": True}, BASE_SETTINGS)
    assert {"authorized_subnet", "scan_authorized_ack"} <= set(exc.value.errors)
    ok = validate_settings_payload({"discovery_engine": "nmap", "auto_scan_enabled": True, "scan_authorized_ack": True,
                                    "authorized_subnet": "192.168.0.0/24"}, BASE_SETTINGS)
    assert ok["authorized_subnet"] == "192.168.0.0/24"


def test_settings_ranges_and_cross_field():
    with pytest.raises(ValidationError) as exc:
        validate_settings_payload({"ping_interval_seconds": 2, "failure_threshold": 0, "scan_timeout_seconds": 400,
                                   "scan_interval_seconds": 300}, BASE_SETTINGS)
    assert {"ping_interval_seconds", "failure_threshold", "scan_timeout_seconds"} <= set(exc.value.errors)


def test_settings_rejects_unknown_engine_and_demo_unless_allowed():
    with pytest.raises(ValidationError):
        validate_settings_payload({"discovery_engine": "masscan"}, BASE_SETTINGS)
    with pytest.raises(ValidationError):
        validate_settings_payload({"discovery_engine": "demo"}, BASE_SETTINGS)
    assert validate_settings_payload({"discovery_engine": "demo"}, BASE_SETTINGS, ("manual", "demo"))["discovery_engine"] == "demo"


def test_settings_nmap_path_must_be_nmap(tmp_path):
    other = tmp_path / "calc.exe"
    other.write_text("x")
    with pytest.raises(ValidationError):
        validate_settings_payload({"nmap_path": str(other)}, BASE_SETTINGS)


def test_device_service_rejects_duplicates(c):
    c.devices.create({"name": "A", "ip_address": "192.168.1.2", "mac_address": "AA:BB:CC:00:00:01"})
    with pytest.raises(ValidationError) as exc:
        c.devices.create({"name": "B", "ip_address": "192.168.1.2", "mac_address": "aa:bb:cc:00:00:01"})
    assert set(exc.value.errors) == {"ip_address", "mac_address"}
