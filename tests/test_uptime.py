from engine.monitoring.pinger import PingResult
from engine.services.uptime import calculate_uptime, compute_outages, device_uptime, next_status, summarize_checks


def test_calculate_uptime():
    assert calculate_uptime(0, 0) is None
    assert calculate_uptime(10, 9) == 90.0
    assert calculate_uptime(3, 2) == 66.67
    assert calculate_uptime(4, 10) == 100.0  # clamped
    assert calculate_uptime(4, -1) == 0.0


def test_summarize_checks():
    s = summarize_checks([True, True, False, True])
    assert s == {"total_checks": 4, "successful_checks": 3, "failed_checks": 1, "uptime_percent": 75.0}


def test_next_status_requires_consecutive_failures():
    status, fails = "online", 0
    seq = []
    for ok in (False, False, False, False, True):
        status, fails = next_status(status, fails, ok, threshold=3)
        seq.append((status, fails))
    assert seq == [("unstable", 1), ("unstable", 2), ("offline", 3), ("offline", 4), ("online", 0)]


def test_next_status_single_lost_ping_is_not_offline():
    assert next_status("online", 0, False, 3) == ("unstable", 1)
    assert next_status("online", 1, True, 3) == ("online", 0)
    assert next_status("unknown", 0, False, 2) == ("unknown", 1)
    assert next_status("unknown", 1, False, 2) == ("offline", 2)
    assert next_status("online", 0, False, 1) == ("offline", 1)


def _log(ts, ok, status):
    return {"checked_at": f"2026-01-01T00:{ts:02d}:00Z", "success": ok, "status_after": status}


def test_compute_outages():
    logs = [_log(0, 1, "online"), _log(1, 0, "unstable"), _log(2, 0, "unstable"), _log(3, 0, "offline"),
            _log(4, 0, "offline"), _log(5, 1, "online"), _log(6, 0, "unstable"), _log(7, 1, "online"),
            _log(8, 0, "unstable"), _log(9, 0, "offline")]
    out = compute_outages(logs)
    assert len(out) == 2
    first, second = out
    assert first["start"] == "2026-01-01T00:01:00Z" and first["end"] == "2026-01-01T00:05:00Z"
    assert first["duration_seconds"] == 240 and first["failed_checks"] == 4 and not first["ongoing"]
    assert second["ongoing"] and second["end"] is None and second["duration_seconds"] is None


def test_device_uptime_from_db(c):
    d = c.devices.create({"name": "NAS", "ip_address": "192.168.1.20"})
    results = [PingResult(True, 2.0), PingResult(True, 4.0), PingResult(False), PingResult(True, 6.0)]
    for r in results:
        c.monitor.record_results([(d, r)], threshold=3)
    u = device_uptime(c.db, d["id"], "24h")
    assert (u["total_checks"], u["successful_checks"], u["failed_checks"]) == (4, 3, 1)
    assert u["uptime_percent"] == 75.0
    assert u["avg_latency_ms"] == 4.0 and u["min_latency_ms"] == 2.0 and u["max_latency_ms"] == 6.0
