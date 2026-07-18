"""SystemMonitor : métriques système du Raspberry Pi (dashboard).

Lecture directe de ``/proc`` et ``/sys`` (aucune dépendance externe). Toutes
les métriques dégradent proprement (valeur ``None``) si indisponibles, afin de
rester utilisable hors Raspberry Pi.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SystemMonitor:
    """Fournit un instantané des ressources système."""

    def get_stats(self) -> Dict[str, Any]:
        """Retourne un dictionnaire de métriques prêtes à afficher."""
        return {
            "hostname": self.hostname(),
            "ip": self.ip_address(),
            "cpu_percent": self.cpu_percent(),
            "load_average": self.load_average(),
            "memory": self.memory(),
            "disk": self.disk(),
            "cpu_temp": self.cpu_temp(),
            "uptime_seconds": self.uptime_seconds(),
            "throttled": self.throttled(),
        }

    # ------------------------------------------------------------------ #
    def hostname(self) -> str:
        try:
            return socket.gethostname()
        except OSError:
            return ""

    def ip_address(self) -> Optional[str]:
        """Adresse IP locale principale (sans connexion réseau réelle)."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(0.5)
                sock.connect(("192.168.255.255", 1))
                return sock.getsockname()[0]
        except OSError:
            return None

    def load_average(self) -> Optional[list]:
        try:
            return list(os.getloadavg())
        except (OSError, AttributeError):
            return None

    def cpu_percent(self) -> Optional[float]:
        """Estimation de charge CPU à partir du load average sur 1 min."""
        load = self.load_average()
        cores = os.cpu_count() or 1
        if not load:
            return None
        return round(min(100.0, (load[0] / cores) * 100.0), 1)

    def memory(self) -> Optional[Dict[str, int]]:
        try:
            info: Dict[str, int] = {}
            with open("/proc/meminfo", "r", encoding="utf-8") as handle:
                for line in handle:
                    key, _, rest = line.partition(":")
                    info[key.strip()] = int(rest.strip().split()[0]) * 1024  # kB -> o
            total = info.get("MemTotal", 0)
            available = info.get("MemAvailable", 0)
            used = total - available
            percent = round(used / total * 100.0, 1) if total else None
            return {"total": total, "used": used, "available": available, "percent": percent}
        except (OSError, ValueError):
            return None

    def disk(self) -> Optional[Dict[str, Any]]:
        try:
            usage = shutil.disk_usage("/")
            percent = round(usage.used / usage.total * 100.0, 1) if usage.total else None
            return {
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": percent,
            }
        except OSError:
            return None

    def cpu_temp(self) -> Optional[float]:
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as handle:
                return round(int(handle.read().strip()) / 1000.0, 1)
        except (OSError, ValueError):
            return None

    def uptime_seconds(self) -> Optional[float]:
        try:
            with open("/proc/uptime", "r", encoding="utf-8") as handle:
                return float(handle.read().split()[0])
        except (OSError, ValueError):
            return None

    def throttled(self) -> Optional[str]:
        """État throttling/voltage via ``vcgencmd`` (Raspberry Pi uniquement)."""
        try:
            out = subprocess.run(
                ["vcgencmd", "get_throttled"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if out.returncode == 0:
                return out.stdout.strip().split("=", 1)[-1]
        except (OSError, subprocess.SubprocessError):
            pass
        return None
