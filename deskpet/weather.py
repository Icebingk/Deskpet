"""Optional Open-Meteo weather worker. No request is made until enabled with a city."""

from __future__ import annotations

import json
import queue
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

    def _run(self) -> None:
        while True:
            city = self._requests.get()
            try:
                query = urllib.parse.urlencode({"name": city, "count": 1, "language": "zh", "format": "json"})
                with urllib.request.urlopen("https://geocoding-api.open-meteo.com/v1/search?" + query, timeout=12) as r:
                    places = json.loads(r.read(256000).decode("utf-8")).get("results") or []
                if not places:
                    raise ValueError("未找到城市")
                place = places[0]
                url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({"latitude": place["latitude"], "longitude": place["longitude"], "current": "temperature_2m,weather_code", "timezone": "auto"})
                with urllib.request.urlopen(url, timeout=12) as r:
                    current = json.loads(r.read(256000).decode("utf-8"))["current"]
                code = int(current.get("weather_code", -1))
                labels = {0:"晴朗",1:"大致晴朗",2:"多云",3:"阴天",45:"有雾",51:"毛毛雨",61:"小雨",63:"中雨",65:"大雨",71:"小雪",80:"阵雨",95:"雷雨"}
                temp = float(current["temperature_2m"])
                self._results.put(WeatherResult(city, f"{labels.get(code, '天气变化')} {temp:.0f}°C", temp))
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
                self._results.put(WeatherResult(city, "", error=str(e)[:120]))
