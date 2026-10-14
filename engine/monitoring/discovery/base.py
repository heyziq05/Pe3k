"""Common types for discovery engines."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class DiscoveredHost:
    ip: str
    mac: str | None = None
    hostname: str | None = None
    vendor: str | None = None
    source: str | None = None  # e.g. "arp-cache" when merged from the OS neighbour table


@dataclass
class HealthCheck:
    name: str
    ok: bool
    detail: str
    level: str = "error"  # error | warning | info  (severity when ok is False)


@dataclass
class EngineHealth:
    engine: str
    label: str
    ready: bool
    summary: str
    checks: list[HealthCheck] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    version: str | None = None
    sees_mac: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


class ScannerError(RuntimeError):
    """A scan could not be performed or did not complete. Message is shown to the user."""


class BaseScanner:
    name = "base"
    label = "Base"

    def check(self) -> EngineHealth:  # pragma: no cover - interface
        raise NotImplementedError

    def scan(self, subnet: str, timeout: int) -> list[DiscoveredHost]:  # pragma: no cover - interface
        raise NotImplementedError
