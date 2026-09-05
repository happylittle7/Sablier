"""Fetch and cache compact weather data for the clock screen."""

from __future__ import annotations

import json
import logging
import os
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CWA_API_BASE = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
CWA_FORECAST_DATASET = "F-D0047-069"
CWA_OBSERVATION_DATASET = "O-A0001-001"
CWA_STATION_NAME = "板橋"
BANQIAO_LATITUDE = 25.0114
BANQIAO_LONGITUDE = 121.4618
TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_CACHE_PATH = Path("output/weather-cache.json")
DEFAULT_MAX_AGE_SECONDS = 15 * 60


class WeatherError(RuntimeError):
    """Weather data could not be fetched or parsed."""


@dataclass(frozen=True)
class WeatherSnapshot:
    temperature: float
    weather_code: int
    is_day: bool
    high: float
    low: float
    rain_probability: int
    fetched_at: int
    source: str = "open-meteo"

    def to_dict(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "weather_code": self.weather_code,
            "is_day": self.is_day,
            "high": self.high,
            "low": self.low,
            "rain_probability": self.rain_probability,
            "fetched_at": self.fetched_at,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, value: Any) -> WeatherSnapshot | None:
        if not isinstance(value, dict):
            return None
        try:
            return cls(
                temperature=float(value["temperature"]),
                weather_code=int(value["weather_code"]),
                is_day=bool(value["is_day"]),
                high=float(value["high"]),
                low=float(value["low"]),
                rain_probability=max(0, min(100, int(value["rain_probability"]))),
                fetched_at=int(value["fetched_at"]),
                source=str(value.get("source", "open-meteo")),
            )
        except (KeyError, TypeError, ValueError):
            return None


def weather_kind(code: int, is_day: bool = True) -> str:
    if code == 0:
        return "clear" if is_day else "night"
    if code in (1, 2):
        return "partly_cloudy"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "thunder"
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    return "cloudy"


def weather_label(code: int, is_day: bool = True) -> str:
    return {
        "clear": "CLEAR",
        "night": "CLEAR NIGHT",
        "partly_cloudy": "PARTLY CLOUDY",
        "cloudy": "CLOUDY",
        "fog": "FOG",
        "rain": "RAIN",
        "snow": "SNOW",
        "thunder": "THUNDERSTORM",
    }[weather_kind(code, is_day)]


def _parse_payload(payload: Any, fetched_at: int) -> WeatherSnapshot:
    try:
        current = payload["current"]
        daily = payload["daily"]
        return WeatherSnapshot(
            temperature=float(current["temperature_2m"]),
            weather_code=int(current["weather_code"]),
            is_day=bool(current["is_day"]),
            high=float(daily["temperature_2m_max"][0]),
            low=float(daily["temperature_2m_min"][0]),
            rain_probability=max(
                0, min(100, int(daily["precipitation_probability_max"][0]))
            ),
            fetched_at=fetched_at,
            source="open-meteo",
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise WeatherError("Open-Meteo returned incomplete weather data") from exc


def fetch_open_meteo_weather(now: int | None = None) -> WeatherSnapshot:
    timestamp = int(time.time()) if now is None else now
    query = urllib.parse.urlencode(
        {
            "latitude": BANQIAO_LATITUDE,
            "longitude": BANQIAO_LONGITUDE,
            "current": "temperature_2m,weather_code,is_day",
            "daily": (
                "temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max"
            ),
            "timezone": "Asia/Taipei",
            "forecast_days": 1,
        }
    )
    request = urllib.request.Request(
        f"{FORECAST_URL}?{query}",
        headers={"Accept": "application/json", "User-Agent": "Sablier/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise WeatherError("Could not reach the weather service") from exc
    return _parse_payload(payload, timestamp)


def _cwa_ssl_context() -> ssl.SSLContext:
    """Keep CA/hostname checks while relaxing Python 3.13's strict SKI check."""
    context = ssl.create_default_context()
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def _cwa_request(dataset: str, params: dict[str, str], api_key: str) -> Any:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{CWA_API_BASE}/{dataset}?{query}",
        headers={
            "Authorization": api_key,
            "Accept": "application/json",
            "User-Agent": "Sablier/1.0",
        },
    )
    try:
        with urllib.request.urlopen(
            request, timeout=20, context=_cwa_ssl_context()
        ) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise WeatherError("Could not reach the CWA weather service") from exc
    if not isinstance(payload, dict) or str(payload.get("success")).lower() != "true":
        raise WeatherError("CWA rejected the weather request")
    return payload


def _forecast_element(location: Any, name: str) -> list[Any]:
    try:
        elements = location["WeatherElement"]
        match = next(item for item in elements if item["ElementName"] == name)
        return match["Time"]
    except (KeyError, StopIteration, TypeError) as exc:
        raise WeatherError(f"CWA forecast is missing {name}") from exc


def _number(record: Any, key: str) -> float:
    try:
        return float(record["ElementValue"][0][key])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise WeatherError(f"CWA forecast is missing {key}") from exc


def _valid_observation(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > -90 else None


def _cwa_code(weather: str) -> int:
    if "雷" in weather:
        return 95
    if "雪" in weather:
        return 71
    if "霧" in weather:
        return 45
    if "雨" in weather:
        return 61
    if "陰" in weather:
        return 3
    if "多雲" in weather:
        return 2
    if "晴" in weather:
        return 0
    return 3


def _parse_cwa_payloads(
    forecast: Any,
    observation: Any | None,
    fetched_at: int,
) -> WeatherSnapshot:
    current = datetime.fromtimestamp(fetched_at, TAIPEI)
    try:
        location = forecast["records"]["Locations"][0]["Location"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise WeatherError("CWA returned no Banqiao forecast") from exc

    temperatures = _forecast_element(location, "溫度")
    temperature_points = [
        (datetime.fromisoformat(item["DataTime"]), _number(item, "Temperature"))
        for item in temperatures
    ]
    today_values = [
        value
        for timestamp, value in temperature_points
        if timestamp.date() == current.date()
    ]
    if not today_values:
        raise WeatherError("CWA returned no temperatures for today")
    nearest_forecast = min(
        temperature_points,
        key=lambda item: abs((item[0] - current).total_seconds()),
    )[1]

    observed_temperature: float | None = None
    observed_high: float | None = None
    observed_low: float | None = None
    if observation is not None:
        try:
            station = observation["records"]["Station"][0]
            observed_at = datetime.fromisoformat(station["ObsTime"]["DateTime"])
            elements = station["WeatherElement"]
            if abs((current - observed_at).total_seconds()) <= 2 * 60 * 60:
                observed_temperature = _valid_observation(elements["AirTemperature"])
            extremes = elements["DailyExtreme"]
            for kind, target in (("DailyHigh", "high"), ("DailyLow", "low")):
                info = extremes[kind]["TemperatureInfo"]
                occurred_at = datetime.fromisoformat(info["Occurred_at"]["DateTime"])
                if occurred_at.date() == current.date():
                    value = _valid_observation(info["AirTemperature"])
                    if target == "high":
                        observed_high = value
                    else:
                        observed_low = value
        except (KeyError, IndexError, TypeError, ValueError):
            pass

    high_candidates = today_values + (
        [observed_high] if observed_high is not None else []
    )
    low_candidates = today_values + ([observed_low] if observed_low is not None else [])
    if observed_temperature is not None:
        high_candidates.append(observed_temperature)
        low_candidates.append(observed_temperature)

    rain_periods = _forecast_element(location, "3小時降雨機率")
    rain_values = [
        _number(item, "ProbabilityOfPrecipitation")
        for item in rain_periods
        if datetime.fromisoformat(item["StartTime"]).date() == current.date()
    ]
    conditions = _forecast_element(location, "天氣現象")
    active = next(
        (
            item
            for item in conditions
            if datetime.fromisoformat(item["StartTime"])
            <= current
            < datetime.fromisoformat(item["EndTime"])
        ),
        conditions[0] if conditions else None,
    )
    try:
        description = str(active["ElementValue"][0]["Weather"])
    except (KeyError, IndexError, TypeError) as exc:
        raise WeatherError("CWA returned no current weather condition") from exc

    return WeatherSnapshot(
        temperature=(
            observed_temperature
            if observed_temperature is not None
            else nearest_forecast
        ),
        weather_code=_cwa_code(description),
        is_day=6 <= current.hour < 18,
        high=max(high_candidates),
        low=min(low_candidates),
        rain_probability=round(max(rain_values)) if rain_values else 0,
        fetched_at=fetched_at,
        source="cwa",
    )


def fetch_cwa_weather(api_key: str, now: int | None = None) -> WeatherSnapshot:
    timestamp = int(time.time()) if now is None else now
    forecast = _cwa_request(
        CWA_FORECAST_DATASET, {"locationName": "板橋區"}, api_key
    )
    try:
        observation = _cwa_request(
            CWA_OBSERVATION_DATASET, {"StationName": CWA_STATION_NAME}, api_key
        )
    except WeatherError:
        observation = None
    return _parse_cwa_payloads(forecast, observation, timestamp)


def fetch_weather(now: int | None = None) -> WeatherSnapshot:
    """Use Taiwan CWA when configured, falling back to Open-Meteo."""
    api_key = os.environ.get("CWA_API_KEY", "").strip()
    if api_key:
        try:
            return fetch_cwa_weather(api_key, now)
        except WeatherError as exc:
            logging.warning("CWA weather refresh failed; using Open-Meteo: %s", exc)
    return fetch_open_meteo_weather(now)


def load_weather(path: Path = DEFAULT_CACHE_PATH) -> WeatherSnapshot | None:
    try:
        return WeatherSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def save_weather(snapshot: WeatherSnapshot, path: Path = DEFAULT_CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(snapshot.to_dict(), output, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def get_weather(
    *,
    force: bool = False,
    cache_path: Path = DEFAULT_CACHE_PATH,
    max_age: int = DEFAULT_MAX_AGE_SECONDS,
    now: int | None = None,
) -> tuple[WeatherSnapshot | None, bool]:
    """Return weather and whether its latest network refresh failed."""
    timestamp = int(time.time()) if now is None else now
    cached = load_weather(cache_path)
    if not force and cached and timestamp - cached.fetched_at < max_age:
        return cached, False
    try:
        fresh = fetch_weather(timestamp)
        save_weather(fresh, cache_path)
        return fresh, False
    except WeatherError:
        return cached, True
