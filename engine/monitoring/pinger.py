"""ICMP reachability checks with timeouts and retries.

``ping3`` is the primary implementation. Raw ICMP sockets need privileges on
some systems; in ``auto`` mode Pe3k switches to the operating system's ``ping``
command when ``ping3`` reports a permission error. The switch is logged and
shown on the Settings page so it never happens silently.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import math
import random
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

from .system import IS_MAC, IS_WINDOWS, no_window_flags

log = logging.getLogger("pe3k.ping")

_LATENCY_RE = re.compile(r"[=<]\s*([0-9]+(?:[.,][0-9]+)?)\s*ms", re.IGNORECASE)


@dataclass
class PingResult:
    success: bool
    latency_ms: float | None = None
    attempts: int = 1
    error: str | None = None


@dataclass
class PingerHealth:
    configured: str
    active: str
    ping3_available: bool
    system_ping_available: bool
    notes: list[str] = field(default_factory=list)


class Pinger:
    def __init__(self, method: str = "auto"):
        self.method = method
        self._forced_system_reason: str | None = None
        self._lock = threading.Lock()
        try:
            import ping3  # noqa: F401

            self._ping3_ok = True
        except Exception:  # pragma: no cover - dependency missing
            self._ping3_ok = False

    # ------------------------------------------------------------- public
    def set_method(self, method: str) -> None:
        with self._lock:
            self.method = method
            self._forced_system_reason = None

    @property
    def active_method(self) -> str:
        if self.method == "system":
            return "system"
        if self.method == "ping3":
            return "ping3"
        if not self._ping3_ok or self._forced_system_reason:
            return "system"
        return "ping3"

    def health(self) -> PingerHealth:
        notes = []
        if self._forced_system_reason:
            notes.append(f"ping3 unavailable ({self._forced_system_reason}); using the system ping command.")
        if not self._ping3_ok:
            notes.append("ping3 is not installed: pip install ping3")
        return PingerHealth(
            configured=self.method,
            active=self.active_method,
            ping3_available=self._ping3_ok,
            system_ping_available=shutil.which("ping") is not None,
            notes=notes,
        )

    def ping(self, ip: str, timeout: float = 1.5, retries: int = 2, retry_delay: float = 0.2) -> PingResult:
        """Ping ``ip``; succeeds if any of ``retries + 1`` attempts gets a reply.

        ``retry_delay`` spaces the attempts out, which gives devices that power-save
        their Wi-Fi (phones) time to wake up between attempts.
        """
        attempts = max(1, int(retries) + 1)
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                latency = self._once(ip, timeout)
            except Exception as exc:  # defensive: a single host must never break the cycle
                latency, last_error = None, f"{type(exc).__name__}: {exc}"
                log.debug("ping error", extra={"event": "ping_error", "ip": ip, "error": last_error})
            if latency is not None:
                return PingResult(True, round(latency, 2), attempt)
            last_error = last_error or "timeout"
            if attempt < attempts:
                time.sleep(max(0.0, retry_delay))
        return PingResult(False, None, attempts, last_error)

    # ------------------------------------------------------------ backends
    def _once(self, ip: str, timeout: float) -> float | None:
        version = ipaddress.ip_address(ip).version
        if self.active_method == "ping3" and version == 4:
            try:
                return self._ping3(ip, timeout)
            except PermissionError as exc:
                if self.method == "ping3":
                    raise PermissionError(
                        "ping3 needs raw-socket privileges. Run Pe3k elevated or set the ping method to 'auto'/'system'."
                    ) from exc
                with self._lock:
                    if not self._forced_system_reason:
                        self._forced_system_reason = "permission denied for raw ICMP sockets"
                        log.warning(
                            "ping3 lacks privileges; switching to system ping",
                            extra={"event": "ping_method_switch", "from": "ping3", "to": "system"},
                        )
        return self._system(ip, timeout, version)

    @staticmethod
    def _ping3(ip: str, timeout: float) -> float | None:
        import ping3

        result = ping3.ping(ip, timeout=timeout, unit="ms")
        if result is None or result is False:
            return None
        return float(result)

    @staticmethod
    def _system(ip: str, timeout: float, version: int = 4) -> float | None:
        exe = shutil.which("ping")
        if not exe:
            raise FileNotFoundError("system 'ping' command not found")
        if IS_WINDOWS:
            cmd = [exe, "-n", "1", "-w", str(int(timeout * 1000)), ip]
        elif IS_MAC:
            cmd = [exe, "-c", "1", "-W", str(int(timeout * 1000)), ip]
            if version == 6:
                cmd[0] = shutil.which("ping6") or exe
        else:
            cmd = [exe, "-c", "1", "-W", str(max(1, math.ceil(timeout))), ip]
        if version == 6 and not IS_MAC:
            cmd.insert(1, "-6")
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout + 3, creationflags=no_window_flags(), errors="replace"
            )
        except subprocess.TimeoutExpired:
            return None
        out = proc.stdout or ""
        if proc.returncode != 0:
            return None
        # Windows returns 0 for "Destination host unreachable" replies from a router; require a TTL.
        if IS_WINDOWS and version == 4 and "TTL=" not in out.upper():
            return None
        match = _LATENCY_RE.search(out)
        if match:
            return float(match.group(1).replace(",", "."))
        return 0.5  # replied, but latency could not be parsed (e.g. "<1ms" variants)


class SimulatedPinger(Pinger):
    """Demo-mode pinger: deterministic, realistic results without sending packets."""

    def __init__(self):
        super().__init__("simulated")

    @property
    def active_method(self) -> str:
        return "simulated"

    def health(self) -> PingerHealth:
        return PingerHealth("simulated", "simulated", self._ping3_ok, shutil.which("ping") is not None,
                            ["Demo mode: ping results are simulated; no packets are sent."])

    def ping(self, ip: str, timeout: float = 1.5, retries: int = 2, retry_delay: float = 0.2) -> PingResult:
        seed = int(hashlib.sha1(ip.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed + int(time.time() // 30))
        last_octet = int(ip.rsplit(".", 1)[-1]) if "." in ip else 1
        base = 0.8 + (seed % 30) / 3
        # A couple of devices are deliberately flaky so the demo shows warnings/outages.
        fail_rate = 0.35 if last_octet % 11 == 0 else (0.08 if last_octet % 7 == 0 else 0.01)
        if rng.random() < fail_rate:
            return PingResult(False, None, max(1, retries + 1), "timeout (simulated)")
        return PingResult(True, round(base + rng.random() * base * 0.6, 2), 1)
