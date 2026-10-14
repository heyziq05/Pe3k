"""Availability monitoring: pings every monitored device and records results."""
from __future__ import annotations

import ipaddress
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from ..db import Database
from ..services import alert_service
from ..services.uptime import next_status
from ..timeutil import now_iso
from ..validators import is_local_scope
from .pinger import Pinger, PingResult

log = logging.getLogger("pe3k.monitor")

MAX_WORKERS = 32

# Phones and tablets put Wi-Fi to sleep when locked, so they get a gentler ping profile.
POWER_SAVING_TYPES = ("phone", "tablet")


@dataclass(frozen=True)
class PingProfile:
    timeout: float
    retries: int
    retry_delay: float
    threshold: int
    name: str = "default"


def ping_profile(device: dict, cfg: dict) -> PingProfile:
    """Ping settings for one device: the phone profile for phones/tablets, otherwise the defaults."""
    if device.get("device_type") in POWER_SAVING_TYPES and cfg.get("phone_tuning_enabled", True):
        return PingProfile(
            timeout=float(cfg.get("phone_ping_timeout_seconds", 3.0)),
            retries=int(cfg.get("phone_ping_retries", 4)),
            retry_delay=float(cfg.get("phone_retry_delay_seconds", 0.75)),
            threshold=int(cfg.get("phone_failure_threshold", 6)),
            name="phone",
        )
    return PingProfile(float(cfg["ping_timeout_seconds"]), int(cfg["ping_retries"]), 0.2, int(cfg["failure_threshold"]))


class MonitorService:
    def __init__(self, db: Database, settings, devices, pinger: Pinger):
        self.db = db
        self.settings = settings
        self.devices = devices
        self.pinger = pinger
        self._cycle_lock = threading.Lock()
        self.last_cycle: dict | None = None

    def _in_scope(self, ip: str, strict: bool) -> bool:
        if not strict:
            return True
        try:
            return is_local_scope(ipaddress.ip_address(ip))
        except ValueError:
            return False

    def run_cycle(self) -> dict:
        """Ping all monitored devices once. Overlapping cycles are skipped, never queued."""
        if not self._cycle_lock.acquire(blocking=False):
            log.info("ping cycle skipped: previous cycle still running", extra={"event": "ping_cycle_skipped"})
            return {"skipped": True}
        started = time.monotonic()
        try:
            cfg = self.settings.all()
            devices = self.devices.monitored()
            strict = bool(cfg.get("strict_scope", True))
            targets, out_of_scope = [], []
            for d in devices:
                (targets if self._in_scope(d["ip_address"], strict) else out_of_scope).append(d)
            for d in out_of_scope:
                log.warning(
                    "device outside strict scope not pinged",
                    extra={"event": "ping_out_of_scope", "device_id": d["id"], "ip": d["ip_address"]},
                )
            profiles = {d["id"]: ping_profile(d, cfg) for d in targets}
            results = self._ping_many(targets, profiles)
            summary = self.record_results(results, int(cfg["failure_threshold"]), bool(cfg.get("offline_alerts_enabled", True)),
                                          {i: p.threshold for i, p in profiles.items()})
            summary.update(
                skipped=False, out_of_scope=len(out_of_scope), duration_ms=int((time.monotonic() - started) * 1000),
                finished_at=now_iso(), method=self.pinger.active_method,
            )
            self.last_cycle = summary
            log.info("ping cycle finished", extra={"event": "ping_cycle", **{k: v for k, v in summary.items() if k != "transitions"}})
            return summary
        finally:
            self._cycle_lock.release()

    def check_device(self, device: dict) -> dict:
        cfg = self.settings.all()
        if not self._in_scope(device["ip_address"], bool(cfg.get("strict_scope", True))):
            raise ValueError("Device is outside the private/local scope allowed while Strict scope is on")
        profile = ping_profile(device, cfg)
        results = self._ping_many([device], {device["id"]: profile})
        return self.record_results(results, int(cfg["failure_threshold"]), bool(cfg.get("offline_alerts_enabled", True)),
                                   {device["id"]: profile.threshold})

    def _ping_many(self, devices: list[dict], profiles: dict[int, PingProfile]) -> list[tuple[dict, PingResult]]:
        if not devices:
            return []

        def work(device: dict) -> tuple[dict, PingResult]:
            p = profiles[device["id"]]
            try:
                return device, self.pinger.ping(device["ip_address"], timeout=p.timeout, retries=p.retries,
                                                retry_delay=p.retry_delay)
            except Exception as exc:  # pragma: no cover - Pinger.ping already guards
                return device, PingResult(False, None, p.retries + 1, f"{type(exc).__name__}: {exc}")

        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(devices)), thread_name_prefix="pe3k-ping") as pool:
            return list(pool.map(work, devices))

    def record_results(self, results: list[tuple[dict, PingResult]], threshold: int, offline_alerts: bool = True,
                       thresholds: dict[int, int] | None = None) -> dict:
        """Persist results and update device state/alerts in one transaction.

        ``thresholds`` optionally overrides the consecutive-failure threshold per device id.
        """
        thresholds = thresholds or {}
        now = now_iso()
        online = offline = 0
        transitions = []
        with self.db.transaction() as conn:
            for device, res in results:
                row = conn.execute(
                    "SELECT id, name, ip_address, mac_address, status, consecutive_failures FROM devices WHERE id = ?",
                    (device["id"],),
                ).fetchone()
                if row is None:  # deleted while we were pinging
                    continue
                prev = row["status"]
                status, failures = next_status(prev, row["consecutive_failures"], res.success,
                                               thresholds.get(row["id"], threshold))
                conn.execute(
                    "UPDATE devices SET status = ?, consecutive_failures = ?, last_checked = ?,"
                    " last_latency_ms = CASE WHEN ? THEN ? ELSE last_latency_ms END,"
                    " last_seen = CASE WHEN ? THEN ? ELSE last_seen END WHERE id = ?",
                    (status, failures, now, res.success, res.latency_ms, res.success, now, row["id"]),
                )
                conn.execute(
                    "INSERT INTO monitor_logs(device_id, checked_at, success, latency_ms, status_after, attempts, error)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (row["id"], now, 1 if res.success else 0, res.latency_ms, status, res.attempts,
                     None if res.success else (res.error or "no reply")[:300]),
                )
                if status == "offline":
                    offline += 1
                    if prev != "offline":
                        transitions.append({"device_id": row["id"], "from": prev, "to": "offline"})
                        if offline_alerts:  # one alert per outage, created on the transition
                            alert_service.upsert_offline(conn, dict(row), now)
                    else:
                        alert_service.touch_offline(conn, row["id"], now)
                else:
                    if status in ("online", "unstable"):
                        online += 1
                    if prev == "offline" and status == "online":
                        transitions.append({"device_id": row["id"], "from": prev, "to": "online"})
                        alert_service.auto_resolve_offline(conn, row["id"], now)
                        log.info("device recovered", extra={"event": "device_recovered", "device_id": row["id"]})
        return {"checked": len(results), "online": online, "offline": offline, "transitions": transitions}
