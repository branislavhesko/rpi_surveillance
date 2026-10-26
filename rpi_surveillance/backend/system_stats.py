"""Raspberry Pi health metrics (SoC temperature, CPU and RAM usage).

Read straight from ``/sys`` and ``/proc`` so no extra dependency is needed.
Every reader returns ``None`` when the metric is unavailable (e.g. off-Pi).
"""

import shutil
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

THERMAL_ZONE = Path("/sys/class/thermal/thermal_zone0/temp")
PROC_STAT = Path("/proc/stat")
PROC_MEMINFO = Path("/proc/meminfo")

GIB = 1024**3


@dataclass
class SystemStats:
    temperature_c: float | None
    cpu_percent: float | None
    ram_percent: float | None
    ram_used_gb: float | None
    ram_total_gb: float | None
    disk_percent: float | None
    disk_free_gb: float | None


def read_temperature(path: Path = THERMAL_ZONE) -> float | None:
    """SoC temperature in °C (the kernel reports millidegrees)."""
    try:
        return int(path.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def _read_cpu_times(path: Path = PROC_STAT) -> tuple[int, int] | None:
    """Return ``(idle, total)`` jiffies from the aggregate ``cpu`` line."""
    try:
        fields = path.read_text().splitlines()[0].split()
    except (OSError, IndexError):
        return None
    if not fields or fields[0] != "cpu":
        return None
    values = [int(v) for v in fields[1:9]]  # user..steal; guest is already in user
    idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
    return idle, sum(values)


class CpuUsage:
    """CPU utilisation since the previous call, from ``/proc/stat`` deltas."""

    def __init__(self, path: Path = PROC_STAT):
        self._path = path
        self._lock = threading.Lock()
        self._last = _read_cpu_times(path)
        self._percent: float | None = None

    def percent(self) -> float | None:
        with self._lock:
            current = _read_cpu_times(self._path)
            if current is None:
                return None
            if self._last is not None:
                idle = current[0] - self._last[0]
                total = current[1] - self._last[1]
                if total > 0:
                    self._percent = max(0.0, min(100.0, 100.0 * (1 - idle / total)))
                    self._last = current
            else:
                self._last = current
            return self._percent


def read_memory(path: Path = PROC_MEMINFO) -> tuple[int, int] | None:
    """Return ``(used, total)`` RAM in bytes, using ``MemAvailable``."""
    try:
        info = {}
        for line in path.read_text().splitlines():
            key, _, rest = line.partition(":")
            info[key] = int(rest.split()[0]) * 1024
        total = info["MemTotal"]
        return total - info["MemAvailable"], total
    except (OSError, KeyError, ValueError, IndexError):
        return None


def read_disk(path: str | Path) -> tuple[int, int] | None:
    """Return ``(used, total)`` bytes of the filesystem holding ``path``."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return usage.total - usage.free, usage.total


_cpu = CpuUsage()


def get_system_stats(disk_path: str | Path = "/") -> SystemStats:
    memory = read_memory()
    disk = read_disk(disk_path)
    return SystemStats(
        temperature_c=read_temperature(),
        cpu_percent=_cpu.percent(),
        ram_percent=100.0 * memory[0] / memory[1] if memory and memory[1] else None,
        ram_used_gb=memory[0] / GIB if memory else None,
        ram_total_gb=memory[1] / GIB if memory else None,
        disk_percent=100.0 * disk[0] / disk[1] if disk and disk[1] else None,
        disk_free_gb=(disk[1] - disk[0]) / GIB if disk else None,
    )


def stats_dict(stats: SystemStats) -> dict:
    return {k: round(v, 1) if v is not None else None for k, v in asdict(stats).items()}
