from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sablier.weather import (
    WeatherError,
    WeatherSnapshot,
    _parse_cwa_payloads,
    _parse_payload,
    get_weather,
    save_weather,
    weather_kind,
)


class WeatherTests(unittest.TestCase):
    def test_parses_cwa_forecast_and_station_observation(self) -> None:
        forecast = {
            "records": {
                "Locations": [
                    {
                        "Location": [
                            {
                                "WeatherElement": [
                                    {
                                        "ElementName": "溫度",
                                        "Time": [
                                            {
                                                "DataTime": "2026-09-06T00:00:00+08:00",
                                                "ElementValue": [{"Temperature": "26"}],
                                            },
                                            {
                                                "DataTime": "2026-09-06T12:00:00+08:00",
                                                "ElementValue": [{"Temperature": "31"}],
                                            },
                                        ],
                                    },
                                    {
                                        "ElementName": "3小時降雨機率",
                                        "Time": [
                                            {
                                                "StartTime": "2026-09-06T00:00:00+08:00",
                                                "EndTime": "2026-09-06T03:00:00+08:00",
                                                "ElementValue": [
                                                    {"ProbabilityOfPrecipitation": "40"}
                                                ],
                                            }
                                        ],
                                    },
                                    {
                                        "ElementName": "天氣現象",
                                        "Time": [
                                            {
                                                "StartTime": "2026-09-06T00:00:00+08:00",
                                                "EndTime": "2026-09-06T03:00:00+08:00",
                                                "ElementValue": [
                                                    {"Weather": "多雲", "WeatherCode": "04"}
                                                ],
                                            }
                                        ],
                                    },
                                ]
                            }
                        ]
                    }
                ]
            }
        }
        observation = {
            "records": {
                "Station": [
                    {
                        "ObsTime": {"DateTime": "2026-09-06T00:00:00+08:00"},
                        "WeatherElement": {
                            "AirTemperature": "24.7",
                            "DailyExtreme": {
                                "DailyHigh": {
                                    "TemperatureInfo": {
                                        "AirTemperature": "-99",
                                        "Occurred_at": {"DateTime": "-99"},
                                    }
                                },
                                "DailyLow": {
                                    "TemperatureInfo": {
                                        "AirTemperature": "-99",
                                        "Occurred_at": {"DateTime": "-99"},
                                    }
                                },
                            },
                        },
                    }
                ]
            }
        }
        snapshot = _parse_cwa_payloads(forecast, observation, 1788624300)
        self.assertEqual(snapshot.temperature, 24.7)
        self.assertEqual(snapshot.high, 31)
        self.assertEqual(snapshot.low, 24.7)
        self.assertEqual(snapshot.rain_probability, 40)
        self.assertEqual(snapshot.source, "cwa")

    def test_parses_current_and_daily_weather(self) -> None:
        snapshot = _parse_payload(
            {
                "current": {
                    "temperature_2m": 27.4,
                    "weather_code": 2,
                    "is_day": 1,
                },
                "daily": {
                    "temperature_2m_max": [31.2],
                    "temperature_2m_min": [24.8],
                    "precipitation_probability_max": [60],
                },
            },
            1000,
        )
        self.assertEqual(snapshot.temperature, 27.4)
        self.assertEqual(snapshot.rain_probability, 60)
        self.assertEqual(weather_kind(snapshot.weather_code), "partly_cloudy")

    def test_fresh_cache_avoids_network(self) -> None:
        snapshot = WeatherSnapshot(27, 1, True, 31, 25, 20, 1000)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weather.json"
            save_weather(snapshot, path)
            with patch("sablier.weather.fetch_weather") as fetch:
                actual, warning = get_weather(cache_path=path, now=1100)
            self.assertEqual(actual, snapshot)
            self.assertFalse(warning)
            fetch.assert_not_called()

    def test_failed_refresh_returns_stale_cache_with_warning(self) -> None:
        snapshot = WeatherSnapshot(27, 1, True, 31, 25, 20, 1000)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weather.json"
            save_weather(snapshot, path)
            with patch(
                "sablier.weather.fetch_weather", side_effect=WeatherError("offline")
            ):
                actual, warning = get_weather(cache_path=path, now=3000)
            self.assertEqual(actual, snapshot)
            self.assertTrue(warning)


if __name__ == "__main__":
    unittest.main()
