"""M3 低频系统监测；不可用数据明确标记，不伪造温度。"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

try:
    import psutil
except ImportError:  # 源码环境缺少可选依赖时仍可启动桌宠。
    psutil = None


@dataclass(frozen=True)
class SystemSnapshot:
    cpu_percent: float | None = None
    memory_percent: float | None = None
    battery_percent: float | None = None
    charging: bool | None = None
    download_kbps: float | None = None
    upload_kbps: float | None = None
    temperature: str = "系统未提供"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SystemMonitor:
    POLL_SECONDS = 2.0
    ALERT_COOLDOWN = 20 * 60

    def __init__(self) -> None:
        self.snapshot = SystemSnapshot()
        self.next_poll = 0.0
        self.last_network_time = time.monotonic()
        self.last_sent = 0
        self.last_received = 0
        self.memory_high_since: float | None = None
        self.last_memory_alert = 0.0
        self.last_battery_alert = 0.0
        if psutil is not None:
            counters = psutil.net_io_counters()
            self.last_sent = int(counters.bytes_sent)
            self.last_received = int(counters.bytes_recv)
            psutil.cpu_percent(interval=None)

    def update(self, now: float | None = None) -> tuple[SystemSnapshot, list[str]]:
        now = now if now is not None else time.monotonic()
        if now < self.next_poll:
            return self.snapshot, []
        self.next_poll = now + self.POLL_SECONDS
        if psutil is None:
            return self.snapshot, []

        cpu = float(psutil.cpu_percent(interval=None))
        memory = float(psutil.virtual_memory().percent)
        battery = psutil.sensors_battery()
        battery_percent = float(battery.percent) if battery else None
        charging = bool(battery.power_plugged) if battery else None

        network = psutil.net_io_counters()
        network_now = time.monotonic()
        elapsed = max(0.1, network_now - self.last_network_time)
        upload = max(0.0, (int(network.bytes_sent) - self.last_sent) / 1024 / elapsed)
        download = max(
            0.0, (int(network.bytes_recv) - self.last_received) / 1024 / elapsed
        )
        self.last_network_time = network_now
        self.last_sent = int(network.bytes_sent)
        self.last_received = int(network.bytes_recv)

        temperature = "系统未提供"
        try:
            temperatures = psutil.sensors_temperatures()
        except (AttributeError, OSError, NotImplementedError):
            temperatures = {}
        if temperatures:
            first_group = next(iter(temperatures.values()), [])
            if first_group:
                temperature = f"{float(first_group[0].current):.0f}°C"

        self.snapshot = SystemSnapshot(
            cpu_percent=cpu,
            memory_percent=memory,
            battery_percent=battery_percent,
            charging=charging,
            download_kbps=download,
            upload_kbps=upload,
            temperature=temperature,
        )

        alerts: list[str] = []
        if memory >= 90:
            self.memory_high_since = self.memory_high_since or now
            if (
                now - self.memory_high_since >= 30
                and now - self.last_memory_alert >= self.ALERT_COOLDOWN
            ):
                alerts.append("内存占用持续超过 90%，我先安静待一会儿。")
                self.last_memory_alert = now
        else:
            self.memory_high_since = None
        if (
            battery_percent is not None
            and battery_percent < 15
            and charging is False
            and now - self.last_battery_alert >= self.ALERT_COOLDOWN
        ):
            alerts.append(f"电量只剩 {battery_percent:.0f}% 啦，记得接上电源～")
            self.last_battery_alert = now
        return self.snapshot, alerts
