"""Host bandwidth sampling with psutil.

Measures traffic of the computer running Pe3k only (not other LAN devices).
A short in-memory series powers the live chart; aggregated rows are written to
``bandwidth_logs`` every ``persist_seconds``.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from collections import deque

import psutil

from ..db import Database
from ..timeutil import now_iso

log = logging.getLogger("pe3k.bandwidth")

ALL = "all"


def _is_loopback(name: str, addrs) -> bool:
    if name.lower().startswith(("lo", "loopback")):
        return True
    ipv4 = [a.address for a in addrs if a.family == socket.AF_INET]
    return bool(ipv4) and all(a.startswith("127.") for a in ipv4)


def list_interfaces() -> list[dict]:
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    counters = psutil.net_io_counters(pernic=True)
    out = []
    for name in sorted(counters):
        a = addrs.get(name, [])
        s = stats.get(name)
        out.append(
            {
                "name": name,
                "is_up": bool(s.isup) if s else False,
                "speed_mbps": s.speed if s and s.speed else None,
                "loopback": _is_loopback(name, a),
                "ipv4": [x.address for x in a if x.family == socket.AF_INET],
                "bytes_recv": counters[name].bytes_recv,
                "bytes_sent": counters[name].bytes_sent,
            }
        )
    return out


class BandwidthMonitor:
    def __init__(self, db: Database, settings, sample_seconds: int = 5, persist_seconds: int = 60, live_points: int = 240):
        self.db = db
        self.settings = settings
        self.sample_seconds = sample_seconds
        self.persist_seconds = persist_seconds
        self.live: deque = deque(maxlen=live_points)
        self._lock = threading.Lock()
        self._interface: str | None = None
        self._prev: tuple[float, int, int] | None = None
        self._pending = {"rx": 0, "tx": 0, "secs": 0.0, "peak_rx": 0.0, "peak_tx": 0.0, "since": time.monotonic()}
        self.error: str | None = None
        self.current = {"rx_mbps": 0.0, "tx_mbps": 0.0, "counter_recv": None, "counter_sent": None, "at": None}

    # ---------------------------------------------------------------- state
    def interface(self) -> str:
        return self.settings.get("bandwidth_interface", ALL) or ALL

    def reset(self) -> None:
        """Forget the baseline (used when the interface changes)."""
        with self._lock:
            self._prev = None
            self.live.clear()
            self._pending = {"rx": 0, "tx": 0, "secs": 0.0, "peak_rx": 0.0, "peak_tx": 0.0, "since": time.monotonic()}

    def _read_counters(self, iface: str) -> tuple[int, int]:
        per = psutil.net_io_counters(pernic=True)
        if iface == ALL:
            addrs = psutil.net_if_addrs()
            rx = tx = 0
            for name, c in per.items():
                if not _is_loopback(name, addrs.get(name, [])):
                    rx += c.bytes_recv
                    tx += c.bytes_sent
            return rx, tx
        if iface not in per:
            raise LookupError(f"Network interface '{iface}' was not found. Pick another interface on the Bandwidth page.")
        return per[iface].bytes_recv, per[iface].bytes_sent

    # --------------------------------------------------------------- sample
    def sample(self) -> dict | None:
        iface = self.interface()
        with self._lock:
            if iface != self._interface:
                self._interface = iface
                self._prev = None
                self.live.clear()
            try:
                rx, tx = self._read_counters(iface)
                self.error = None
            except Exception as exc:
                if self.error != str(exc):
                    log.warning("bandwidth sample failed", extra={"event": "bandwidth_error", "error": str(exc)})
                self.error = str(exc)
                return None
            now_mono = time.monotonic()
            point = None
            if self._prev is not None:
                t0, rx0, tx0 = self._prev
                secs = max(now_mono - t0, 0.001)
                drx, dtx = rx - rx0, tx - tx0
                if drx < 0 or dtx < 0:  # counter wrap / adapter reset: re-baseline
                    log.info("bandwidth counters reset", extra={"event": "bandwidth_counter_reset", "interface": iface})
                else:
                    rx_mbps, tx_mbps = drx * 8 / secs / 1e6, dtx * 8 / secs / 1e6
                    point = {"t": now_iso(), "rx_mbps": round(rx_mbps, 3), "tx_mbps": round(tx_mbps, 3)}
                    self.live.append(point)
                    self.current.update(rx_mbps=point["rx_mbps"], tx_mbps=point["tx_mbps"], at=point["t"])
                    p = self._pending
                    p["rx"] += drx
                    p["tx"] += dtx
                    p["secs"] += secs
                    p["peak_rx"] = max(p["peak_rx"], rx_mbps)
                    p["peak_tx"] = max(p["peak_tx"], tx_mbps)
            self._prev = (now_mono, rx, tx)
            self.current.update(counter_recv=rx, counter_sent=tx)
            if self._pending["secs"] >= self.persist_seconds:
                self._persist(iface, rx, tx)
            return point

    def _persist(self, iface: str, counter_rx: int, counter_tx: int) -> None:
        p = self._pending
        secs = p["secs"]
        try:
            with self.db.session() as conn:
                conn.execute(
                    "INSERT INTO bandwidth_logs(recorded_at, interface, interval_seconds, bytes_recv, bytes_sent, rx_mbps, tx_mbps,"
                    " counter_recv, counter_sent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (now_iso(), iface, round(secs, 2), p["rx"], p["tx"], round(p["rx"] * 8 / secs / 1e6, 3),
                     round(p["tx"] * 8 / secs / 1e6, 3), counter_rx, counter_tx),
                )
        except Exception:
            log.exception("could not persist bandwidth sample", extra={"event": "bandwidth_persist_error"})
            return  # keep pending totals; try again next sample
        self._pending = {"rx": 0, "tx": 0, "secs": 0.0, "peak_rx": 0.0, "peak_tx": 0.0, "since": time.monotonic()}

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "interface": self.interface(),
                "error": self.error,
                "current": dict(self.current),
                "live": list(self.live),
                "sample_seconds": self.sample_seconds,
                "persist_seconds": self.persist_seconds,
            }
