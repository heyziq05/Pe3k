"""Reset operations: settings only, or a full factory reset."""
from __future__ import annotations

import logging

log = logging.getLogger("pe3k.maintenance")

# Data tables emptied by a factory reset (order respects foreign keys).
DATA_TABLES = ("monitor_logs", "alerts", "bandwidth_logs", "scan_logs", "devices", "settings")


class ResetBlocked(RuntimeError):
    pass


def reset_settings(container) -> dict:
    """Restore every setting to its default. Devices, history and alerts are kept."""
    return container.settings.reset()


def factory_reset(container) -> dict:
    """Delete all Pe3k data (devices, history, alerts, bandwidth, scans, settings).

    The database file and schema stay in place, so Pe3k keeps running and behaves
    like a fresh install. Refused while a discovery scan is running.
    """
    if container.scans.running:
        raise ResetBlocked("A network scan is running. Wait for it to finish, then try again.")
    # Wait for an in-progress ping cycle so it doesn't write rows for deleted devices.
    got_lock = container.monitor._cycle_lock.acquire(timeout=30)
    try:
        counts = {}
        with container.db.transaction() as conn:
            for table in DATA_TABLES:
                counts[table] = conn.execute(f"DELETE FROM {table}").rowcount  # fixed identifiers
            try:
                conn.execute("DELETE FROM sqlite_sequence")  # restart ids at 1
            except Exception:  # table absent when nothing was ever inserted
                pass
    finally:
        if got_lock:
            container.monitor._cycle_lock.release()
    container.monitor.last_cycle = None
    container.bandwidth_monitor.reset()
    container.scans.invalidate_health()
    settings = container.settings.reset()
    log.warning("factory reset", extra={"event": "factory_reset", **{f"deleted_{k}": v for k, v in counts.items()}})
    return {"deleted": counts, "settings": settings}
