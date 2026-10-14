"""Safe demo data: sample devices plus a week of synthetic history.

Nothing here touches the network. Demo devices live in 192.168.88.0/24 and are
only pinged by the simulated pinger while ``PE3K_DEMO_MODE=true``.
"""
from __future__ import annotations

import logging
import math
import random
from datetime import timedelta

from .services.uptime import next_status
from .timeutil import to_iso, utcnow

log = logging.getLogger("pe3k.demo")

DEMO_SUBNET = "192.168.88.0/24"

DEMO_DEVICES = [
    ("Home Router", "192.168.88.1", "A4:2B:B0:11:22:01", "router", "Gateway / Wi-Fi access point"),
    ("Office NAS", "192.168.88.10", "00:11:32:AB:CD:10", "server", "Backups and file shares"),
    ("Study Laptop", "192.168.88.21", "3C:52:82:4F:61:21", "laptop", ""),
    ("Family Phone", "192.168.88.33", "F2:6E:0B:9D:33:33", "phone", "Randomised Wi-Fi MAC"),
    ("Living Room TV", "192.168.88.45", "70:2A:D5:0E:45:45", "iot", ""),
    ("Office Printer", "192.168.88.50", "00:1B:A9:7C:50:50", "printer", "Sleeps overnight"),
    ("Smart Thermostat", "192.168.88.63", "18:B4:30:2E:63:63", "iot", ""),
    ("Lab Server", "192.168.88.100", "52:54:00:12:34:64", "server", "Proxmox host"),
    ("Security Camera", "192.168.88.121", "9C:8E:CD:1A:21:79", "iot", "Garage camera"),
]


def seed_if_empty(container) -> bool:
    with container.db.session() as conn:
        count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    if count:
        return False
    seed_demo(container)
    return True


def seed_demo(container, days: int = 7, step_minutes: int = 5) -> dict:
    rng = random.Random(42)
    db = container.db
    end = utcnow()
    start = end - timedelta(days=days)
    steps = int(days * 24 * 60 / step_minutes)
    threshold = int(container.settings.get("failure_threshold", 3))

    container.settings.set_raw(
        {
            "authorized_subnet": DEMO_SUBNET,
            "discovery_engine": "demo" if container.demo_mode else "manual",
            "auto_scan_enabled": bool(container.demo_mode),
            "scan_authorized_ack": True,
            "strict_scope": True,
        }
    )

    with db.transaction() as conn:
        device_ids = []
        for i, (name, ip, mac, dtype, notes) in enumerate(DEMO_DEVICES):
            added = to_iso(start - timedelta(days=3 + i))
            cur = conn.execute(
                "INSERT OR IGNORE INTO devices(name, ip_address, mac_address, device_type, trusted, monitoring_enabled, notes,"
                " date_added, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)",
                # Outside demo mode the sample devices are not real, so live pinging is paused for them.
                (name, ip, mac, dtype, 1 if container.demo_mode else 0, notes, added, added),
            )
            if cur.lastrowid and cur.rowcount:
                device_ids.append((cur.lastrowid, name, ip, dtype))

        log_rows = []
        for device_id, name, ip, dtype in device_ids:
            base = {"router": 1.2, "server": 2.0, "laptop": 6.0, "phone": 18.0, "printer": 4.0, "iot": 9.0}.get(dtype, 5.0)
            status, failures, last_seen, last_lat = "unknown", 0, None, None
            for s in range(steps):
                ts = start + timedelta(minutes=s * step_minutes)
                hour = (ts.hour + 8) % 24  # rough local-time pattern
                ok = rng.random() > 0.01
                if dtype == "printer" and (hour >= 23 or hour < 6):
                    ok = False  # printer sleeps overnight
                if name == "Security Camera" and steps * 0.55 < s < steps * 0.55 + 40:
                    ok = False  # ~3h outage mid-week
                if dtype == "phone" and (hour < 7 or rng.random() < 0.06):
                    ok = rng.random() > 0.7
                latency = round(base * (0.7 + rng.random() * 0.8) + (rng.random() < 0.03) * base * 4, 2) if ok else None
                status, failures = next_status(status, failures, ok, threshold)
                iso = to_iso(ts)
                if ok:
                    last_seen, last_lat = iso, latency
                log_rows.append((device_id, iso, int(ok), latency, status, 1 if ok else 3, None if ok else "timeout (demo)"))
            conn.execute(
                "UPDATE devices SET status = ?, consecutive_failures = ?, last_seen = ?, last_latency_ms = ?, last_checked = ? WHERE id = ?",
                (status, failures, last_seen, last_lat, to_iso(end), device_id),
            )
        conn.executemany(
            "INSERT INTO monitor_logs(device_id, checked_at, success, latency_ms, status_after, attempts, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
            log_rows,
        )

        bw_rows = []
        iface = container.settings.get("bandwidth_interface", "all") or "all"
        for s in range(steps):
            ts = start + timedelta(minutes=s * step_minutes)
            hour = (ts.hour + 8) % 24
            diurnal = 0.15 + 0.85 * max(0.0, math.sin((hour - 6) / 24 * 2 * math.pi)) ** 1.5
            rx_mbps = max(0.05, diurnal * rng.uniform(4, 38) + (rng.random() < 0.04) * rng.uniform(40, 160))
            tx_mbps = max(0.02, rx_mbps * rng.uniform(0.08, 0.3))
            secs = step_minutes * 60
            bw_rows.append((to_iso(ts), iface, secs, int(rx_mbps * 1e6 / 8 * secs), int(tx_mbps * 1e6 / 8 * secs),
                            round(rx_mbps, 3), round(tx_mbps, 3)))
        conn.executemany(
            "INSERT INTO bandwidth_logs(recorded_at, interface, interval_seconds, bytes_recv, bytes_sent, rx_mbps, tx_mbps)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            bw_rows,
        )

        t_alert = to_iso(end - timedelta(hours=5))
        conn.execute(
            "INSERT OR IGNORE INTO alerts(alert_type, severity, status, dedup_key, ip_address, mac_address, hostname, vendor, engine,"
            " message, occurrences, first_seen, last_seen) VALUES ('unknown_device','warning','open','unknown:3E:A1:5C:7D:22:9B',"
            " '192.168.88.78','3E:A1:5C:7D:22:9B','unknown-android.lan','(randomised MAC)','demo',"
            " 'Unknown device 192.168.88.78 (3E:A1:5C:7D:22:9B) detected on the network', 14, ?, ?)",
            (t_alert, to_iso(end - timedelta(minutes=4))),
        )
        conn.execute(
            "INSERT OR IGNORE INTO alerts(alert_type, severity, status, dedup_key, ip_address, mac_address, vendor, engine, message,"
            " occurrences, first_seen, last_seen, resolution) VALUES ('unknown_device','warning','ignored','unknown:D8:F1:5B:00:AA:07',"
            " '192.168.88.140','D8:F1:5B:00:AA:07','Espressif Inc.','demo',"
            " 'Unknown device 192.168.88.140 (D8:F1:5B:00:AA:07) detected on the network', 52, ?, ?, 'Ignored by user')",
            (to_iso(end - timedelta(days=3)), to_iso(end - timedelta(hours=1))),
        )
        cam = next((d for d in device_ids if d[1] == "Security Camera"), None)
        if cam:
            o_start = start + timedelta(minutes=int(steps * 0.55 + 3) * step_minutes)
            conn.execute(
                "INSERT INTO alerts(alert_type, severity, status, dedup_key, device_id, ip_address, engine, message, occurrences,"
                " first_seen, last_seen, resolved_at, resolution) VALUES ('device_offline','critical','resolved',?,?,?,'ping',?,37,?,?,?,"
                " 'Device came back online')",
                (f"offline:{cam[0]}", cam[0], cam[2], f"{cam[1]} ({cam[2]}) is offline", to_iso(o_start),
                 to_iso(o_start + timedelta(hours=3)), to_iso(o_start + timedelta(hours=3, minutes=5))),
            )
        for k in range(6):
            t0 = end - timedelta(minutes=5 * (k + 1))
            conn.execute(
                "INSERT INTO scan_logs(started_at, finished_at, engine, subnet, trigger, status, hosts_found, unknown_found, duration_ms)"
                " VALUES (?, ?, 'demo', ?, 'scheduled', 'success', ?, 1, ?)",
                (to_iso(t0), to_iso(t0 + timedelta(seconds=4)), DEMO_SUBNET, 8 + (k % 2), 3800 + k * 120),
            )

    log.info("demo data seeded", extra={"event": "demo_seeded", "devices": len(device_ids), "monitor_rows": len(log_rows)})
    return {"devices": len(device_ids), "monitor_logs": len(log_rows), "bandwidth_logs": len(bw_rows)}
