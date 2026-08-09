"""天气后台任务：优先使用国内可直连来源，海外来源仅作备用。"""

from __future__ import annotations

import json
import queue
import re
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class WeatherResult:
    city: str
    summary: str
    temperature: float | None = None
    error: str | None = None


class WeatherClient:
    """异步获取天气，不阻塞桌宠动画。"""

    def __init__(self) -> None:
        self._requests: queue.Queue[str] = queue.Queue()
        self._results: queue.Queue[WeatherResult] = queue.Queue()
        threading.Thread(target=self._run, name="DeskPetWeather", daemon=True).start()

    def refresh(self, city: str) -> None:
        self._requests.put(city.strip()[:80])

    def poll(self) -> list[WeatherResult]:
        values: list[WeatherResult] = []
        while True:
            try:
                values.append(self._results.get_nowait())
            except queue.Empty:
                return values

    @staticmethod
    def _load_json(url: str) -> dict[str, object]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "LineDogDeskPet/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read(256000).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("天气服务返回格式无效")
        return data

    @staticmethod
    def _temperature(value: object) -> float | None:
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        return float(match.group()) if match else None

    def _fetch_domestic(self, city: str) -> WeatherResult:
        """国内城市名天气接口，不需要用户申请密钥。"""
        query = urllib.parse.urlencode({"city": city})
        payload = self._load_json("https://api.vvhan.com/api/weather?" + query)
        if payload.get("success") is not True:
            raise ValueError(str(payload.get("message") or "未找到城市"))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("天气服务未返回实况")
        condition = str(data.get("type") or "天气变化").strip()
        high = self._temperature(data.get("high"))
        low = self._temperature(data.get("low"))
        if high is not None and low is not None and high != low:
            temperature_text = f"{low:g}~{high:g}°C"
        elif high is not None:
            temperature_text = f"{high:g}°C"
        elif low is not None:
            temperature_text = f"{low:g}°C"
        else:
            temperature_text = ""
        result_city = str(payload.get("city") or city).strip()[:80]
        return WeatherResult(
            result_city,
            " ".join(part for part in (condition, temperature_text) if part),
            high if high is not None else low,
        )

    def _fetch_open_meteo(self, city: str) -> WeatherResult:
        """国内来源不可用时的备用来源。"""
        query = urllib.parse.urlencode(
            {"name": city, "count": 1, "language": "zh", "format": "json"}
        )
        places = self._load_json(
            "https://geocoding-api.open-meteo.com/v1/search?" + query
        ).get("results") or []
        if not isinstance(places, list) or not places:
            raise ValueError("未找到城市")
        place = places[0]
        if not isinstance(place, dict):
            raise ValueError("城市定位结果无效")
        query = urllib.parse.urlencode(
            {
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,weather_code",
                "timezone": "auto",
            }
        )
        current = self._load_json("https://api.open-meteo.com/v1/forecast?" + query)[
            "current"
        ]
        if not isinstance(current, dict):
            raise ValueError("天气服务未返回实况")
        code = int(current.get("weather_code", -1))
        labels = {
            0: "晴朗", 1: "大致晴朗", 2: "多云", 3: "阴天", 45: "有雾",
            51: "毛毛雨", 61: "小雨", 63: "中雨", 65: "大雨", 71: "小雪",
            80: "阵雨", 95: "雷雨",
        }
        temperature = float(current["temperature_2m"])
        return WeatherResult(city, f"{labels.get(code, '天气变化')} {temperature:.0f}°C", temperature)

    def _run(self) -> None:
        while True:
            city = self._requests.get()
            try:
                try:
                    result = self._fetch_domestic(city)
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    result = self._fetch_open_meteo(city)
                self._results.put(result)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
                self._results.put(WeatherResult(city, "", error=str(error)[:120]))