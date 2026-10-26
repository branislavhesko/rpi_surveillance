from rpi_surveillance.backend.system_stats import (
    CpuUsage,
    read_disk,
    read_memory,
    read_temperature,
)


def test_read_temperature(tmp_path):
    zone = tmp_path / "temp"
    zone.write_text("52345\n")
    assert read_temperature(zone) == 52.345


def test_read_temperature_missing(tmp_path):
    assert read_temperature(tmp_path / "missing") is None


def test_read_memory_uses_mem_available(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:        4000000 kB\n"
        "MemFree:          500000 kB\n"
        "MemAvailable:    3000000 kB\n"
        "Buffers:           10000 kB\n"
    )
    used, total = read_memory(meminfo)
    assert total == 4000000 * 1024
    assert used == 1000000 * 1024


def test_read_memory_missing(tmp_path):
    assert read_memory(tmp_path / "missing") is None


def _write_stat(path, user, idle):
    # cpu user nice system idle iowait irq softirq steal guest guest_nice
    path.write_text(f"cpu  {user} 0 0 {idle} 0 0 0 0 0 0\ncpu0 1 2 3 4\n")


def test_cpu_usage_from_deltas(tmp_path):
    stat = tmp_path / "stat"
    _write_stat(stat, user=100, idle=900)
    cpu = CpuUsage(stat)
    _write_stat(stat, user=175, idle=925)  # 75 busy of 100 jiffies
    assert cpu.percent() == 75.0
    # No time elapsed: keep the last value instead of dividing by zero.
    assert cpu.percent() == 75.0


def test_cpu_usage_missing(tmp_path):
    assert CpuUsage(tmp_path / "missing").percent() is None


def test_read_disk(tmp_path):
    used, total = read_disk(tmp_path)
    assert 0 <= used <= total
    assert read_disk(tmp_path / "missing") is None
