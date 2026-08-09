from __future__ import annotations

import unittest
from unittest.mock import patch

from deskpet.weather import WeatherClient


class DomesticWeatherTests(unittest.TestCase):
    def test_domestic_weather_provider_parses_city_and_temperature_range(self) -> None:
        client = WeatherClient()
        payload = {
            "success": True,
            "city": "北京市",
            "data": {"type": "中雨", "low": "24°C", "high": "31°C"},
        }
        with patch.object(client, "_load_json", return_value=payload):
            result = client._fetch_domestic("北京")

        self.assertEqual(result.city, "北京市")
        self.assertEqual(result.summary, "中雨 24~31°C")
        self.assertEqual(result.temperature, 31.0)


if __name__ == "__main__":
    unittest.main()