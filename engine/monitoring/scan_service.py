"""Runs discovery scans: pre-flight checks, overlap prevention, result processing."""
from __future__ import annotations

import logging
import threading
import time

from ..db import Database
from ..services import alert_service
from ..timeutil import now_iso
from ..validators import ip_in_subnet, normalize_mac, validate_subnet
from .discovery import ENGINE_LABELS, DiscoveredHost, EngineHealth, ScannerError, get_scanner
from .discovery.arp_cache import arp_cache_hosts

log = logging.getLogger("pe3k.scan")

HEALTH_CACHE_SECONDS = 30


class ScanInProgress(RuntimeError):
    pass


def merge_arp_cache(scanned: list[DiscoveredHost], cached: list[DiscoveredHost]) -> tuple[list[DiscoveredHost], int]:
    """Combine live scan results with the OS neighbour cache.

    * Hosts the scanner found without a MAC (e.g. Nmap without admin rights) get it from the cache.
    * Cache-only hosts (devices that were awake recently but asleep during the scan) are added,
      tagged ``source="arp-cache"`` so alerts show where they came from.
    Returns the merged list and how many hosts came only from the cache.
    """
    by_ip = {h.ip: h for h in cached}
    merged, seen = [], set()
    for h in scanned:
        if not h.mac and h.ip in by_ip:
            h = DiscoveredHost(ip=h.ip, mac=by_ip[h.ip].mac, hostname=h.hostname, vendor=h.vendor, source=h.source)
        merged.append(h)
        seen.add(h.ip)
    extra = [DiscoveredHost(ip=h.ip, mac=h.mac, source="arp-cache") for h in cached if h.ip not in seen]
    return merged + extra, len(extra)


class ScanService:
    def __init__(self, db: Database, settings, devices, demo_mode: bool = False):
        self.db = db
        self.settings = settings
        self.devices = devices
        self.demo_mode = demo_mode
        self._lock = threading.Lock()
        self._running_since: str | None = None
        self._health_cache: dict[str, tuple[float, EngineHealth]] = {}

    # ----------------------------------------------------------- helpers
    def scanner_for(self, engine: str, cfg: dict):
        return get_scanner(engine, cfg, self.demo_mode, known_hosts_provider=self.devices.monitored)

    def health(self, engine: str | None = None, refresh: bool = False) -> EngineHealth:
        cfg = self.settings.all()
        engine = engine or cfg["discovery_engine"]
        cache_key = f"{engine}:{cfg.get('nmap_path', '')}"
        cached = self._health_cache.get(cache_key)
        if cached and not refresh and time.monotonic() - cached[0] < HEALTH_CACHE_SECONDS:
            return cached[1]
        try:
            health = self.scanner_for(engine, cfg).check()
        except Exception as exc:
            health = EngineHealth(engine, ENGINE_LABELS.get(engine, engine), False, f"Health check failed: {exc}")
        self._health_cache[cache_key] = (time.monotonic(), health)
        return health

    def invalidate_health(self) -> None:
        self._health_cache.clear()

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def preflight(self, cfg: dict) -> str:
        """Validate everything needed before a scan. Returns the normalised subnet or raises ScannerError."""
        engine = cfg["discovery_engine"]
        if engine == "manual":
            raise ScannerError("Manual mode is selected: automatic network scanning is disabled.")
        if not cfg.get("scan_authorized_ack"):
            raise ScannerError("Scanning is blocked until you confirm in Settings that you own or are authorized to scan this network.")
        try:
            subnet = validate_subnet(cfg.get("authorized_subnet"), bool(cfg.get("strict_scope", True)))
        except ValueError as exc:
            raise ScannerError(str(exc)) from None
        health = self.health(engine, refresh=True)
        if not health.ready:
            failed = "; ".join(c.detail for c in health.checks if not c.ok and c.level == "error")
            raise ScannerError(f"{health.label} is not ready: {failed or health.summary}")
        return subnet

    def status(self) -> dict:
        cfg = self.settings.all()
        with self.db.session() as conn:
            last = conn.execute("SELECT * FROM scan_logs WHERE status != 'running' ORDER BY started_at DESC, id DESC LIMIT 1").fetchone()
            last_ok = conn.execute("SELECT finished_at, hosts_found FROM scan_logs WHERE status = 'success' ORDER BY started_at DESC, id DESC LIMIT 1").fetchone()
        health = self.health(cfg["discovery_engine"])
        engine = cfg["discovery_engine"]
        return {
            "engine": engine,
            "engine_label": ENGINE_LABELS.get(engine, engine),
            "running": self.running,
            "running_since": self._running_since if self.running else None,
            "auto_scan_enabled": bool(cfg.get("auto_scan_enabled")) and engine != "manual",
            "authorized_subnet": cfg.get("authorized_subnet") or None,
            "authorized_ack": bool(cfg.get("scan_authorized_ack")),
            "ready": health.ready,
            "health_summary": health.summary,
            "last_scan": dict(last) if last else None,
            "last_success_at": last_ok["finished_at"] if last_ok else None,
            "last_hosts_found": last_ok["hosts_found"] if last_ok else None,
        }

    def recent(self, limit: int = 20) -> list[dict]:
        with self.db.session() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM scan_logs ORDER BY started_at DESC, id DESC LIMIT ?", (max(1, min(limit, 200)),))]

    # -------------------------------------------------------------- run
    def start_async(self, trigger: str = "manual") -> None:
        """Start a scan in the background. Raises ScanInProgress / ScannerError before starting."""
        if self.running:
            raise ScanInProgress("A scan is already running.")
        cfg = self.settings.all()
        self.preflight(cfg)  # fail fast with a clear message for the UI
        threading.Thread(target=self._safe_run, args=(trigger,), name="pe3k-scan-manual", daemon=True).start()

    def _safe_run(self, trigger: str) -> None:
        try:
            self.run(trigger)
        except ScanInProgress:
            pass
        except Exception:
            log.exception("scan crashed", extra={"event": "scan_crash"})

    def run(self, trigger: str = "scheduled") -> dict:
        if not self._lock.acquire(blocking=False):
            log.info("scan skipped: another scan is running", extra={"event": "scan_overlap"})
            raise ScanInProgress("A scan is already running.")
        started_mono = time.monotonic()
        self._running_since = now_iso()
        cfg = self.settings.all()
        engine = cfg["discovery_engine"]
        subnet_raw = cfg.get("authorized_subnet") or None
        with self.db.session() as conn:
            scan_id = conn.execute(
                "INSERT INTO scan_logs(started_at, engine, subnet, trigger, status) VALUES (?, ?, ?, ?, 'running')",
                (self._running_since, engine, subnet_raw, trigger),
            ).lastrowid
        try:
            subnet = self.preflight(cfg)
            scanner = self.scanner_for(engine, cfg)
            hosts = scanner.scan(subnet, int(cfg["scan_timeout_seconds"]))
            cached = 0
            if cfg.get("use_arp_cache", True) and engine in ("nmap", "scapy"):
                hosts, cached = merge_arp_cache(hosts, arp_cache_hosts(subnet))
            result = self._process(hosts, subnet, engine)
            result["from_arp_cache"] = cached
            self._finish(scan_id, "success", started_mono, result["hosts_found"], result["unknown_found"], None, cached)
            log.info("scan finished", extra={"event": "scan_finished", "engine": engine, "subnet": subnet, **result})
            return {"status": "success", **result}
        except ScannerError as exc:
            self._finish(scan_id, "error", started_mono, 0, 0, str(exc))
            log.warning("scan failed", extra={"event": "scan_failed", "engine": engine, "error": str(exc)})
            return {"status": "error", "error": str(exc)}
        except Exception as exc:
            msg = f"Unexpected error: {type(exc).__name__}: {exc}"
            self._finish(scan_id, "error", started_mono, 0, 0, msg)
            log.exception("scan error", extra={"event": "scan_error", "engine": engine})
            return {"status": "error", "error": msg}
        finally:
            self._running_since = None
            self._lock.release()

    def _finish(self, scan_id: int, status: str, started_mono: float, hosts: int, unknown: int, error: str | None,
                cached: int = 0) -> None:
        with self.db.session() as conn:
            conn.execute(
                "UPDATE scan_logs SET finished_at = ?, status = ?, hosts_found = ?, unknown_found = ?, duration_ms = ?, error = ?,"
                " cached_found = ? WHERE id = ?",
                (now_iso(), status, hosts, unknown, int((time.monotonic() - started_mono) * 1000), error, cached, scan_id),
            )

    def _process(self, hosts, subnet: str, engine: str) -> dict:
        """Match discovered hosts against trusted devices; raise de-duplicated unknown-device alerts."""
        now = now_iso()
        unknown = new_alerts = matched = 0
        with self.db.transaction() as conn:
            trusted = [dict(r) for r in conn.execute("SELECT id, ip_address, mac_address FROM devices WHERE trusted = 1")]
            by_mac = {d["mac_address"]: d for d in trusted if d["mac_address"]}
            by_ip = {d["ip_address"]: d for d in trusted}
            seen_ips = set()
            for host in hosts:
                if not ip_in_subnet(host.ip, subnet) or host.ip in seen_ips:
                    continue  # never record anything outside the authorized range
                seen_ips.add(host.ip)
                try:
                    mac = normalize_mac(host.mac)
                except ValueError:
                    mac = None
                device = by_mac.get(mac) if mac else by_ip.get(host.ip)
                if device is not None:
                    matched += 1
                    if device["ip_address"] != host.ip and host.ip not in by_ip:
                        conn.execute("UPDATE devices SET ip_address = ?, last_seen = ?, updated_at = ? WHERE id = ?",
                                     (host.ip, now, now, device["id"]))
                        log.info("trusted device changed IP", extra={"event": "device_ip_changed", "device_id": device["id"],
                                                                     "old_ip": device["ip_address"], "new_ip": host.ip})
                    else:
                        conn.execute("UPDATE devices SET last_seen = ? WHERE id = ?", (now, device["id"]))
                    continue
                unknown += 1
                _, created = alert_service.upsert_unknown_device(
                    conn, ip=host.ip, mac=mac, engine=f"{engine}+{host.source}" if host.source else engine, hostname=host.hostname, vendor=host.vendor, seen_at=now
                )
                new_alerts += int(created)
        return {"hosts_found": len(seen_ips), "matched": matched, "unknown_found": unknown, "new_alerts": new_alerts}
