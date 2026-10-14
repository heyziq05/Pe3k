"""APScheduler lifecycle for Pe3k's background jobs.

* Jobs: ping cycle, discovery scan (only when enabled), bandwidth sampling and
  daily maintenance (retention pruning).
* ``coalesce`` + ``max_instances=1`` stop overlapping runs; each job is wrapped
  so an exception is logged and the next run still happens.
* The scheduler is a process-wide singleton: ``start()`` is idempotent and it is
  shut down via ``atexit`` (and on SIGTERM/SIGINT through the server).
"""
from __future__ import annotations

import atexit
import logging
import threading
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from ..timeutil import iso_ago

log = logging.getLogger("pe3k.scheduler")

_start_lock = threading.Lock()
_instance: "Pe3kScheduler | None" = None

JOB_LABELS = {
    "ping": "Device ping cycle",
    "scan": "Network discovery scan",
    "bandwidth": "Bandwidth sampling",
    "maintenance": "Data retention cleanup",
}


class Pe3kScheduler:
    def __init__(self, container, config):
        self.c = container
        self.config = config
        self.scheduler = BackgroundScheduler(
            timezone=timezone.utc,
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 30},
        )
        self.started = False
        self.last_errors: dict[str, str] = {}
        self.last_runs: dict[str, str] = {}

    # --------------------------------------------------------------- wrappers
    def _wrap(self, job_id: str, fn):
        def runner():
            from ..timeutil import now_iso

            try:
                fn()
                self.last_errors.pop(job_id, None)
            except Exception as exc:
                self.last_errors[job_id] = f"{type(exc).__name__}: {exc}"
                log.exception("job failed", extra={"event": "job_failed", "job": job_id})
            finally:
                self.last_runs[job_id] = now_iso()

        runner.__name__ = f"pe3k_{job_id}"
        return runner

    def _scan_job(self):
        from .scan_service import ScanInProgress

        try:
            self.c.scans.run("scheduled")
        except ScanInProgress:
            pass

    def _maintenance(self):
        cfg = self.config
        with self.c.db.transaction() as conn:
            m = conn.execute("DELETE FROM monitor_logs WHERE checked_at < ?", (iso_ago(days=cfg.MONITOR_RETENTION_DAYS),)).rowcount
            b = conn.execute("DELETE FROM bandwidth_logs WHERE recorded_at < ?", (iso_ago(days=cfg.BANDWIDTH_RETENTION_DAYS),)).rowcount
            s = conn.execute("DELETE FROM scan_logs WHERE started_at < ?", (iso_ago(days=cfg.SCAN_LOG_RETENTION_DAYS),)).rowcount
            # Scans left 'running' by a crash/restart are closed out.
            conn.execute("UPDATE scan_logs SET status = 'error', error = 'Interrupted (Pe3k restarted)' WHERE status = 'running'"
                         " AND started_at < ?", (iso_ago(hours=1),))
        log.info("retention cleanup", extra={"event": "maintenance", "monitor_logs": m, "bandwidth_logs": b, "scan_logs": s})

    # ------------------------------------------------------------------ jobs
    def _scan_should_run(self, cfg: dict) -> bool:
        return (
            cfg.get("discovery_engine") != "manual"
            and bool(cfg.get("auto_scan_enabled"))
            and bool(cfg.get("scan_authorized_ack"))
            and bool(cfg.get("authorized_subnet"))
        )

    def configure_jobs(self) -> None:
        cfg = self.c.settings.all()
        now = datetime.now(timezone.utc)
        self.scheduler.add_job(
            self._wrap("ping", self.c.monitor.run_cycle), "interval", id="ping",
            seconds=int(cfg["ping_interval_seconds"]), next_run_time=now + timedelta(seconds=3), replace_existing=True,
        )
        self.scheduler.add_job(
            self._wrap("bandwidth", self.c.bandwidth_monitor.sample), "interval", id="bandwidth",
            seconds=self.config.BANDWIDTH_SAMPLE_SECONDS, next_run_time=now, replace_existing=True,
        )
        self.scheduler.add_job(
            self._wrap("maintenance", self._maintenance), "interval", id="maintenance",
            hours=24, next_run_time=now + timedelta(minutes=2), replace_existing=True,
        )
        self._configure_scan(cfg)

    def _configure_scan(self, cfg: dict) -> None:
        if self._scan_should_run(cfg):
            self.scheduler.add_job(
                self._wrap("scan", self._scan_job), "interval", id="scan",
                seconds=int(cfg["scan_interval_seconds"]),
                next_run_time=datetime.now(timezone.utc) + timedelta(seconds=10), replace_existing=True,
            )
        elif self.scheduler.get_job("scan"):
            self.scheduler.remove_job("scan")

    def on_settings_changed(self, keys: set[str]) -> None:
        if not self.started:
            return
        cfg = self.c.settings.all()
        if "ping_interval_seconds" in keys:
            self.scheduler.reschedule_job("ping", trigger="interval", seconds=int(cfg["ping_interval_seconds"]))
        if keys & {"discovery_engine", "auto_scan_enabled", "scan_authorized_ack", "authorized_subnet", "scan_interval_seconds", "strict_scope"}:
            self._configure_scan(cfg)
        log.info("scheduler reconfigured", extra={"event": "scheduler_reconfigured", "keys": ",".join(sorted(keys))})

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.configure_jobs()
        self.scheduler.start()
        self.started = True
        atexit.register(self.shutdown)
        log.info("scheduler started", extra={"event": "scheduler_started", "jobs": ",".join(j.id for j in self.scheduler.get_jobs())})

    def shutdown(self) -> None:
        if self.started:
            self.started = False
            try:
                self.scheduler.shutdown(wait=False)
                log.info("scheduler stopped", extra={"event": "scheduler_stopped"})
            except Exception:  # pragma: no cover
                pass

    def run_now(self, job_id: str) -> None:
        job = self.scheduler.get_job(job_id) if self.started else None
        if job is None:
            raise LookupError(f"Job '{job_id}' is not scheduled")
        job.modify(next_run_time=datetime.now(timezone.utc))

    def status(self) -> dict:
        jobs = []
        if self.started:
            for job in self.scheduler.get_jobs():
                nrt = job.next_run_time
                jobs.append({
                    "id": job.id,
                    "label": JOB_LABELS.get(job.id, job.id),
                    "interval_seconds": int(job.trigger.interval.total_seconds()) if hasattr(job.trigger, "interval") else None,
                    "next_run": nrt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if nrt else None,
                    "last_run": self.last_runs.get(job.id),
                    "last_error": self.last_errors.get(job.id),
                })
        return {"running": self.started, "jobs": jobs}


def start_scheduler(container, config) -> Pe3kScheduler:
    """Create and start the scheduler exactly once per process."""
    global _instance
    with _start_lock:
        if _instance is None:
            _instance = Pe3kScheduler(container, config)
            container.settings.on_change(_instance.on_settings_changed)
            _instance.start()
        return _instance


def get_scheduler() -> "Pe3kScheduler | None":
    return _instance
