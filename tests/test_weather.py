from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sablier.weather import (
    CWA_FORECAST_DATASET,
    CWA_FORECAST_LOCATION,
    CWA_OBSERVATION_DATASET,
    CWA_STATION_NAME,
    WeatherError,
    WeatherPeriod,
    WeatherSnapshot,
    _open_meteo_periods,
    _parse_cwa_payloads,
    _parse_payload,
    fetch_cwa_weather,
    get_weather,
    save_weather,
    weather_kind,
)


class WeatherTests(unittest.TestCase):
    def test_cwa_fetch_uses_wenshan_forecast_and_station(self) -> None:
        snapshot = WeatherSnapshot(26, 2, True, 30, 23, 40, 1000, source="cwa")
        with (
            patch("sablier.weather._cwa_request", side_effect=[{}, {}]) as request,
            patch("sablier.weather._parse_cwa_payloads", return_value=snapshot),
        ):
            actual = fetch_cwa_weather("test-key", now=1000)

        self.assertEqual(actual, snapshot)
        self.assertEqual(
            request.call_args_list[0].args,
            (CWA_FORECAST_DATASET, {"LocationName": CWA_FORECAST_LOCATION}, "test-key"),
        )
        self.assertEqual(
            request.call_args_list[1].args,
            (CWA_OBSERVATION_DATASET, {"StationName": CWA_STATION_NAME}, "test-key"),
        )

    def test_parses_cwa_forecast_and_station_observation(self) -> None:
        forecast = {
            "records": {
                "Locations": [
                    {
                        "Location": [
                            {
                                "LocationName": "松山區",
                                "WeatherElement": [],
                            },
                            {
                                "LocationName": "文山區",
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
                                        "ElementName": "體感溫度",
                                        "Time": [
                                            {
                                                "DataTime": "2026-09-06T00:00:00+08:00",
                                                "ElementValue": [
                                                    {"ApparentTemperature": "29"}
                                                ],
                                            }
                                        ],
                                    },
                                    {
                                        "ElementName": "相對濕度",
                                        "Time": [
                                            {
                                                "DataTime": "2026-09-06T00:00:00+08:00",
                                                "ElementValue": [{"RelativeHumidity": "82"}],
                                            }
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
                                            },
                                            {
                                                "StartTime": "2026-09-06T03:00:00+08:00",
                                                "EndTime": "2026-09-06T06:00:00+08:00",
                                                "ElementValue": [
                                                    {"ProbabilityOfPrecipitation": "80"}
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
                            "RelativeHumidity": "79",
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
        self.assertEqual(snapshot.rain_period_start, 1788624000)
        self.assertEqual(snapshot.rain_period_end, 1788634800)
        self.assertEqual(snapshot.apparent_temperature, 29)
        self.assertEqual(snapshot.humidity, 79)
        self.assertEqual(len(snapshot.forecast_periods), 2)
        self.assertEqual(snapshot.forecast_periods[0].rain_probability, 40)
        self.assertEqual(snapshot.forecast_periods[0].weather_code, 2)

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
        self.assertIsNone(snapshot.rain_period_start)
        self.assertEqual(weather_kind(snapshot.weather_code), "partly_cloudy")

    def test_open_meteo_fallback_builds_the_full_day(self) -> None:
        periods = _open_meteo_periods(
            {
                "hourly": {
                    "time": [f"2026-09-14T{hour:02d}:00" for hour in range(24)],
                    "temperature_2m": list(range(24)),
                    "weather_code": [2] * 24,
                    "precipitation_probability": list(range(24)),
                }
            },
            0,
        )
        self.assertEqual(len(periods), 8)
        self.assertEqual(periods[0].temperature, 1)
        self.assertEqual(periods[0].rain_probability, 2)
        self.assertEqual(periods[-1].rain_probability, 23)

    def test_fresh_cache_avoids_network(self) -> None:
        snapshot = WeatherSnapshot(
            27,
            1,
            True,
            31,
            25,
            20,
            1000,
            apparent_temperature=29,
            humidity=75,
            forecast_periods=(WeatherPeriod(900, 1200, 27, 1, 20),),
        )
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

    def test_weather_mode_upgrades_a_fresh_legacy_cache(self) -> None:
        legacy = WeatherSnapshot(27, 1, True, 31, 25, 20, 1000)
        fresh = WeatherSnapshot(
            28,
            2,
            True,
            32,
            26,
            40,
            1100,
            forecast_periods=(WeatherPeriod(900, 1200, 28, 2, 40),),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weather.json"
            save_weather(legacy, path)
            with patch("sablier.weather.fetch_weather", return_value=fresh) as fetch:
                actual, warning = get_weather(
                    cache_path=path,
                    now=1100,
                    require_forecast=True,
                )
            self.assertEqual(actual, fresh)
            self.assertFalse(warning)
            fetch.assert_called_once_with(1100)


if __name__ == "__main__":
    unittest.main()
