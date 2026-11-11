"""Load `config/solowatch.toml` into `AppConfig`. `"env:NAME"` strings are read from the env."""
from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from datetime import date
from typing import Any

from solowatch.contracts_mvp import (
    AppConfig,
    ConfigError,
    DetectorConfig,
    MqttConfig,
    SensorSpec,
    SupabaseConfig,
)

_ENV_PREFIX = "env:"
_KINDS = ("water", "plug")
_UNITS = ("L", "W")


def _resolve(value: Any, env: Mapping[str, str]) -> Any:
    if isinstance(value, str) and value.startswith(_ENV_PREFIX):
        name = value[len(_ENV_PREFIX):]
        try:
            return env[name]
        except KeyError:
            raise ConfigError(name) from None
    if isinstance(value, dict):
        return {k: _resolve(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, env) for v in value]
    return value


def _req(table: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in table:
        raise ConfigError(f"{where}.{key}")
    return table[key]


def _sensor(raw: Mapping[str, Any]) -> SensorSpec:
    kind = _req(raw, "kind", "sensor")
    unit = _req(raw, "unit", "sensor")
    if kind not in _KINDS:
        raise ConfigError(f"sensor.kind={kind!r}")
    if unit not in _UNITS:
        raise ConfigError(f"sensor.unit={unit!r}")
    return SensorSpec(
        sensor_id=str(_req(raw, "sensor_id", "sensor")),
        kind=kind,
        unit=unit,
        min_deviation=float(_req(raw, "min_deviation", "sensor")),
        active_threshold=float(_req(raw, "active_threshold", "sensor")),
        topic=str(_req(raw, "topic", "sensor")),
        value_path=str(raw.get("value_path", "value")),
        ts_path=str(raw.get("ts_path", "ts")),
    )


def load_config(path: str, env: Mapping[str, str] | None = None) -> AppConfig:
    env = os.environ if env is None else env
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(path) from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None
    data: dict[str, Any] = _resolve(raw, env)

    household = _req(data, "household", "")
    mqtt = _req(data, "mqtt", "")
    store = _req(data, "store", "")
    det = data.get("detector", {})
    install_start = household.get("install_start")
    if install_start is not None and not isinstance(install_start, date):
        install_start = date.fromisoformat(str(install_start))

    supabase: SupabaseConfig | None = None
    if "supabase" in data:
        sb = data["supabase"]
        supabase = SupabaseConfig(
            url=str(_req(sb, "url", "supabase")),
            anon_key=str(_req(sb, "anon_key", "supabase")),
            device_email=str(_req(sb, "device_email", "supabase")),
            device_password=str(_req(sb, "device_password", "supabase")),
        )

    urls = data.get("apprise", {}).get("urls", "")
    parts = urls if isinstance(urls, list) else str(urls).split(",")
    apprise_urls = tuple(u.strip() for u in parts if str(u).strip())

    sensors_raw = data.get("sensor", [])
    if not sensors_raw:
        raise ConfigError("sensor")

    defaults = DetectorConfig()
    return AppConfig(
        household_id=str(_req(household, "id", "household")),
        slug=str(_req(household, "slug", "household")),
        name=str(household.get("name", "")),
        mqtt=MqttConfig(
            host=str(_req(mqtt, "host", "mqtt")),
            port=int(_req(mqtt, "port", "mqtt")),
            username=str(mqtt.get("username", "")),
            password=str(mqtt.get("password", "")),
        ),
        store_path=str(_req(store, "path", "store")),
        detector=DetectorConfig(
            learn_days=int(det.get("learn_days", defaults.learn_days)),
            threshold=float(det.get("threshold", defaults.threshold)),
            tick_seconds=int(det.get("tick_seconds", defaults.tick_seconds)),
            daily_report_hour=int(det.get("daily_report_hour", defaults.daily_report_hour)),
        ),
        supabase=supabase,
        apprise_urls=apprise_urls,
        sensors=tuple(_sensor(s) for s in sensors_raw),
        install_start=install_start,
    )
