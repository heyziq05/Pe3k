"""Platform helpers: privilege detection, Npcap detection, safe subprocess flags."""
from __future__ import annotations

import os
import platform
import subprocess
from functools import lru_cache

IS_WINDOWS = os.name == "nt"
IS_MAC = platform.system() == "Darwin"


def is_admin() -> bool:
    """True when running as root (POSIX) or as an elevated Administrator (Windows)."""
    try:
        if IS_WINDOWS:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        return os.geteuid() == 0
    except Exception:
        return False


@lru_cache(maxsize=1)
def npcap_installed() -> bool | None:
    """Windows only: detect the Npcap driver. Returns ``None`` on other platforms."""
    if not IS_WINDOWS:
        return None
    system_root = os.environ.get("SystemRoot", "")
    candidates = [os.path.join(system_root, "System32", "Npcap"), os.path.join(system_root, "SysWOW64", "Npcap")]
    return any(os.path.isdir(p) for p in candidates if system_root)


def privilege_hint() -> str:
    if IS_WINDOWS:
        return "Run the terminal that starts Pe3k as Administrator (right-click → Run as administrator)."
    return "Start Pe3k with sudo, or grant the Python binary capabilities: sudo setcap cap_net_raw,cap_net_admin=eip $(readlink -f $(which python3))"


def no_window_flags() -> int:
    """Prevent console windows flashing on Windows when running subprocesses."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0
