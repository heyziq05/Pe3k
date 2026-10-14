"""Input validation for devices, settings and network ranges.

All functions raise :class:`ValidationError` with a ``{field: message}`` dict so
the API can return precise, user-friendly errors.
"""
from __future__ import annotations

import ipaddress
import os
import re
from typing import Any

DEVICE_TYPES = ("router", "laptop", "desktop", "phone", "tablet", "printer", "server", "iot", "other")
DEVICE_TYPE_LABELS = {
    "router": "Router",
    "laptop": "Laptop",
    "desktop": "Desktop",
    "phone": "Phone",
    "tablet": "Tablet",
    "printer": "Printer",
    "server": "Server",
    "iot": "IoT device",
    "other": "Other",
}
DISCOVERY_ENGINES = ("nmap", "scapy", "manual")
PING_METHODS = ("auto", "ping3", "system")

# Scan-size guard rails. Strict scope keeps scans to small private LANs.
STRICT_MIN_PREFIX = 22   # at most 1,024 addresses
RELAXED_MIN_PREFIX = 16  # at most 65,536 addresses

_MAC_HEX = re.compile(r"^[0-9a-f]{12}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ValidationError(ValueError):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


# ---------------------------------------------------------------- primitives
def normalize_mac(value: str | None) -> str | None:
    """Return ``AA:BB:CC:DD:EE:FF`` or ``None`` for empty input. Raises ValueError if malformed."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    hexonly = re.sub(r"[\s:\-\.]", "", raw).lower()
    if not _MAC_HEX.match(hexonly):
        raise ValueError("MAC address must look like AA:BB:CC:DD:EE:FF")
    if hexonly in ("000000000000", "ffffffffffff"):
        raise ValueError("MAC address cannot be all zeros or broadcast")
    return ":".join(hexonly[i : i + 2] for i in range(0, 12, 2)).upper()


def is_local_scope(ip: ipaddress._BaseAddress) -> bool:
    """True for addresses that belong to a private/local network."""
    return (ip.is_private or ip.is_link_local) and not (
        ip.is_loopback or ip.is_multicast or ip.is_unspecified or ip.is_reserved
    )


def validate_ip(value: Any, strict_scope: bool = True) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("IP address is required")
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        raise ValueError(f"'{text}' is not a valid IPv4 or IPv6 address") from None
    if ip.is_multicast or ip.is_unspecified or (ip.version == 4 and str(ip) == "255.255.255.255"):
        raise ValueError("Multicast, broadcast and unspecified addresses cannot be monitored")
    if strict_scope and not is_local_scope(ip):
        raise ValueError(
            "Strict scope is on: only private/local addresses (e.g. 10.x, 172.16-31.x, 192.168.x) "
            "can be monitored. Turn off Strict scope in Settings to monitor other hosts."
        )
    return str(ip)


def validate_subnet(value: Any, strict_scope: bool = True) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Authorized subnet is required for network scanning")
    if "/" not in text:
        raise ValueError(f"'{text}' is a single address. Add a prefix for the whole network, e.g. "
                         f"{'.'.join(text.split('.')[:3])}.0/24")
    try:
        net = ipaddress.ip_network(text, strict=False)
    except ValueError:
        raise ValueError(f"'{text}' is not a valid subnet. Use CIDR notation such as 192.168.1.0/24") from None
    if net.version != 4:
        raise ValueError("Only IPv4 subnets can be scanned (ARP/host discovery is IPv4)")
    if net.is_multicast or net.is_unspecified or net.is_loopback:
        raise ValueError("Subnet must be a real local network, not loopback/multicast")
    min_prefix = STRICT_MIN_PREFIX if strict_scope else RELAXED_MIN_PREFIX
    if net.prefixlen < min_prefix:
        raise ValueError(
            f"Subnet /{net.prefixlen} is too large ({net.num_addresses:,} addresses). "
            f"Use /{min_prefix} or smaller" + (" while Strict scope is on." if strict_scope else ".")
        )
    if strict_scope and not (net.is_private or net.is_link_local):
        raise ValueError("Strict scope is on: the authorized subnet must be a private/local range")
    return str(net)


def ip_in_subnet(ip: str, subnet: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        return False


def clean_text(value: Any, field: str, max_len: int, required: bool = False) -> str:
    text = _CONTROL.sub("", str(value or "")).strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if len(text) > max_len:
        raise ValueError(f"{field} must be {max_len} characters or fewer")
    return text


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int_in(value: Any, low: int, high: int, label: str) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a whole number") from None
    if not low <= number <= high:
        raise ValueError(f"{label} must be between {low} and {high}")
    return number


def _float_in(value: Any, low: float, high: float, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number") from None
    if not low <= number <= high:
        raise ValueError(f"{label} must be between {low:g} and {high:g}")
    return round(number, 2)


# ------------------------------------------------------------------- devices
def validate_device_payload(data: dict, strict_scope: bool = True, partial: bool = False) -> dict:
    """Validate a device create/update payload and return a cleaned dict."""
    if not isinstance(data, dict):
        raise ValidationError({"_": "Expected a JSON object"})
    errors: dict[str, str] = {}
    out: dict[str, Any] = {}

    def want(key: str) -> bool:
        return not partial or key in data

    if want("name"):
        try:
            out["name"] = clean_text(data.get("name"), "Name", 64, required=True)
        except ValueError as exc:
            errors["name"] = str(exc)
    if want("ip_address"):
        try:
            out["ip_address"] = validate_ip(data.get("ip_address"), strict_scope)
        except ValueError as exc:
            errors["ip_address"] = str(exc)
    if want("mac_address"):
        try:
            out["mac_address"] = normalize_mac(data.get("mac_address"))
        except ValueError as exc:
            errors["mac_address"] = str(exc)
    if want("device_type"):
        dtype = str(data.get("device_type") or "other").strip().lower()
        if dtype not in DEVICE_TYPES:
            errors["device_type"] = f"Device type must be one of: {', '.join(DEVICE_TYPES)}"
        else:
            out["device_type"] = dtype
    if want("trusted"):
        out["trusted"] = 1 if to_bool(data.get("trusted", True)) else 0
    if want("monitoring_enabled"):
        out["monitoring_enabled"] = 1 if to_bool(data.get("monitoring_enabled", True)) else 0
    if want("notes"):
        try:
            out["notes"] = clean_text(data.get("notes"), "Notes", 500)
        except ValueError as exc:
            errors["notes"] = str(exc)

    if errors:
        raise ValidationError(errors)
    return out


# ------------------------------------------------------------------ settings
def validate_nmap_path(value: Any) -> str:
    path = str(value or "").strip().strip('"')
    if not path:
        return ""
    base = os.path.basename(path).lower()
    if base not in ("nmap", "nmap.exe"):
        raise ValueError("Nmap path must point to the nmap / nmap.exe executable")
    if not os.path.isfile(path):
        raise ValueError(f"No file found at {path}")
    return path


def validate_settings_payload(data: dict, current: dict, engines: tuple[str, ...] = DISCOVERY_ENGINES) -> dict:
    """Validate a (partial) settings update against the current settings.

    ``engines`` lists the discovery engines allowed right now (``demo`` is only
    added when Pe3k runs in demo mode).
    """
    if not isinstance(data, dict):
        raise ValidationError({"_": "Expected a JSON object"})
    errors: dict[str, str] = {}
    out: dict[str, Any] = {}
    strict = to_bool(data["strict_scope"]) if "strict_scope" in data else bool(current.get("strict_scope", True))

    checks = {
        "scan_interval_seconds": lambda v: _int_in(v, 60, 86_400, "Scan interval"),
        "scan_timeout_seconds": lambda v: _int_in(v, 5, 600, "Scan timeout"),
        "ping_interval_seconds": lambda v: _int_in(v, 10, 3_600, "Ping interval"),
        "ping_timeout_seconds": lambda v: _float_in(v, 0.2, 10, "Ping timeout"),
        "ping_retries": lambda v: _int_in(v, 0, 5, "Ping retries"),
        "failure_threshold": lambda v: _int_in(v, 1, 20, "Consecutive-failure threshold"),
        "phone_ping_timeout_seconds": lambda v: _float_in(v, 0.5, 10, "Phone ping timeout"),
        "phone_ping_retries": lambda v: _int_in(v, 0, 8, "Phone ping retries"),
        "phone_retry_delay_seconds": lambda v: _float_in(v, 0, 5, "Phone retry delay"),
        "phone_failure_threshold": lambda v: _int_in(v, 1, 30, "Phone consecutive-failure threshold"),
        "nmap_path": validate_nmap_path,
        "bandwidth_interface": lambda v: clean_text(v, "Interface", 128) or "all",
    }
    for key, fn in checks.items():
        if key in data:
            try:
                out[key] = fn(data[key])
            except ValueError as exc:
                errors[key] = str(exc)

    if "discovery_engine" in data:
        engine = str(data["discovery_engine"]).strip().lower()
        if engine not in engines:
            errors["discovery_engine"] = "Choose Nmap, Scapy or Manual"
        else:
            out["discovery_engine"] = engine
    if "ping_method" in data:
        method = str(data["ping_method"]).strip().lower()
        if method not in PING_METHODS:
            errors["ping_method"] = "Ping method must be auto, ping3 or system"
        else:
            out["ping_method"] = method
    for flag in ("auto_scan_enabled", "scan_authorized_ack", "strict_scope", "offline_alerts_enabled", "use_arp_cache",
                 "phone_tuning_enabled"):
        if flag in data:
            out[flag] = to_bool(data[flag])

    # Subnet: validated against the strict-scope value that will be in effect.
    subnet_val = data.get("authorized_subnet", current.get("authorized_subnet", ""))
    if "authorized_subnet" in data or "strict_scope" in data:
        if str(subnet_val or "").strip():
            try:
                out["authorized_subnet"] = validate_subnet(subnet_val, strict)
            except ValueError as exc:
                errors["authorized_subnet"] = str(exc)
        else:
            out["authorized_subnet"] = ""

    # Cross-field rules
    engine = out.get("discovery_engine", current.get("discovery_engine"))
    auto = out.get("auto_scan_enabled", current.get("auto_scan_enabled"))
    if engine != "manual" and auto:
        if not out.get("authorized_subnet", current.get("authorized_subnet")) and "authorized_subnet" not in errors:
            errors["authorized_subnet"] = "Set the authorized subnet before enabling automatic scanning"
        if not out.get("scan_authorized_ack", current.get("scan_authorized_ack")):
            errors["scan_authorized_ack"] = "Confirm you own or are authorized to scan this network"
    # A phone check must finish well inside one ping interval, or cycles start skipping.
    if not any(k in errors for k in ("phone_ping_timeout_seconds", "phone_ping_retries", "phone_retry_delay_seconds",
                                     "ping_interval_seconds")):
        p_to = float(out.get("phone_ping_timeout_seconds", current.get("phone_ping_timeout_seconds", 3.0)))
        p_rt = int(out.get("phone_ping_retries", current.get("phone_ping_retries", 4)))
        p_dl = float(out.get("phone_retry_delay_seconds", current.get("phone_retry_delay_seconds", 0.75)))
        p_iv = int(out.get("ping_interval_seconds", current.get("ping_interval_seconds", 45)))
        worst = (p_rt + 1) * p_to + p_rt * p_dl
        if worst >= p_iv:
            errors["phone_ping_retries"] = (f"A phone check can take up to {worst:.0f}s, longer than the {p_iv}s ping "
                                            "interval. Lower the phone timeout/retries or raise the ping interval.")
    timeout = out.get("scan_timeout_seconds", current.get("scan_timeout_seconds", 60))
    interval = out.get("scan_interval_seconds", current.get("scan_interval_seconds", 300))
    if "scan_timeout_seconds" not in errors and "scan_interval_seconds" not in errors and timeout >= interval:
        errors["scan_timeout_seconds"] = "Scan timeout must be shorter than the scan interval"

    if errors:
        raise ValidationError(errors)
    return out
