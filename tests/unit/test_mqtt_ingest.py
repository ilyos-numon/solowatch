from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest

from solowatch.contracts import TZ, Reading
from solowatch.contracts_mvp import DEFAULT_SENSORS, ConfigError, SensorSpec
from solowatch.mqtt_ingest import Ingester, SlotAccumulator, extract, topic_matches
from solowatch.sensors_config import load_config
from solowatch.store import SqliteStore

EXAMPLE = str(Path(__file__).resolve().parents[2] / "config" / "solowatch.example.toml")
ENV = {
    "SUPABASE_URL": "http://localhost:57321",
    "SUPABASE_ANON_KEY": "anon",
    "SOLOWATCH_DEVICE_EMAIL": "device@example.com",
    "SOLOWATCH_DEVICE_PASSWORD": "pw",
    "SOLOWATCH_APPRISE_URLS": "json://localhost:8842/a, ,json://localhost:8842/b",
}
NOW = datetime(2026, 10, 5, 12, 0, 7, tzinfo=TZ)
WATER = DEFAULT_SENSORS[0]
TV = DEFAULT_SENSORS[2]
TASMOTA = SensorSpec("plug_tv", "plug", "W", 300.0, 60.0, "tele/tv/SENSOR",
                     value_path="ENERGY.Power", ts_path="Time")
Z2M = SensorSpec("plug_light", "plug", "W", 300.0, 30.0, "zigbee2mqtt/living_light",
                 value_path="power")


def at(h: int, m: int) -> datetime:
    return datetime(2026, 10, 5, h, m, tzinfo=TZ)


# --- topic_matches -------------------------------------------------------------------------

@pytest.mark.parametrize(("pattern", "topic", "ok"), [
    ("solowatch/home-demo/water_main/state", "solowatch/home-demo/water_main/state", True),
    ("solowatch/+/water_main/state", "solowatch/home-demo/water_main/state", True),
    ("solowatch/+/state", "solowatch/home-demo/water_main/state", False),
    ("solowatch/#", "solowatch/home-demo/water_main/state", True),
    ("tele/+/SENSOR", "tele/tv/SENSOR", True),
    ("tele/+/SENSOR", "tele/tv/STATE", False),
])
def test_topic_matches(pattern: str, topic: str, ok: bool) -> None:
    assert topic_matches(pattern, topic) is ok


# --- extract -------------------------------------------------------------------------------

def test_extract_native() -> None:
    got = extract(b'{"ts":"2026-10-05T06:30:00+09:00","value":12.5,"unit":"L"}', WATER, NOW)
    assert got == (at(6, 30), 12.5)


def test_extract_native_without_ts_uses_receive_time() -> None:
    assert extract(b'{"value": 3, "unit": "L"}', WATER, NOW) == (NOW, 3.0)


def test_extract_tasmota_naive_time_gets_tz() -> None:
    got = extract(b'{"Time":"2026-10-05T19:00:00","ENERGY":{"Power":80}}', TASMOTA, NOW)
    assert got is not None
    assert got == (at(19, 0), 80.0)
    assert got[0].utcoffset() == at(0, 0).utcoffset()


def test_extract_zigbee2mqtt() -> None:
    assert extract(b'{"power": 10, "state": "ON"}', Z2M, NOW) == (NOW, 10.0)


def test_extract_bare_number() -> None:
    assert extract(b"12.5", WATER, NOW) == (NOW, 12.5)
    assert extract(b"12.5", Z2M, NOW) is None


@pytest.mark.parametrize("payload", [
    b"not json",                      # not JSON
    b'{"unit": "L"}',                 # value path missing
    b'{"value": "lots"}',             # not numeric
    b'{"value": true}',               # bool is not a number
    b'{"value": -1}',                 # negative
])
def test_extract_drops(payload: bytes) -> None:
    assert extract(payload, WATER, NOW) is None


# --- SlotAccumulator -----------------------------------------------------------------------

def test_slot_plug_average_and_close() -> None:
    acc = SlotAccumulator(DEFAULT_SENSORS)
    assert acc.add("plug_tv", at(19, 1), 60.0) == []
    assert acc.add("plug_tv", at(19, 3), 100.0) == []
    assert acc.add("plug_tv", at(19, 6), 80.0) == [Reading("plug_tv", at(19, 0), 80.0)]
    assert acc.flush() == [Reading("plug_tv", at(19, 5), 80.0)]
    assert acc.flush() == []


def test_slot_water_sum_per_sensor() -> None:
    acc = SlotAccumulator(DEFAULT_SENSORS)
    acc.add("water_main", at(6, 30), 1.5)
    acc.add("water_main", at(6, 34), 2.0)
    acc.add("plug_tv", at(6, 36), 5.0)          # another sensor does not close water's slot
    assert acc.add("water_main", at(6, 35), 1.0) == [Reading("water_main", at(6, 30), 3.5)]
    assert sorted(acc.flush(), key=lambda r: r.sensor_id) == [
        Reading("plug_tv", at(6, 35), 5.0), Reading("water_main", at(6, 35), 1.0)]


# --- load_config ---------------------------------------------------------------------------

def test_load_config_env_substitution() -> None:
    cfg = load_config(EXAMPLE, env=ENV)
    assert cfg.slug == "home-demo"
    assert cfg.mqtt.host == "localhost" and cfg.mqtt.port == 57883
    assert cfg.supabase is not None
    assert cfg.supabase.anon_key == "anon"
    assert cfg.supabase.url == "http://localhost:57321"
    assert cfg.apprise_urls == ("json://localhost:8842/a", "json://localhost:8842/b")
    assert cfg.sensors == DEFAULT_SENSORS
    assert cfg.install_start is not None and cfg.install_start.isoformat() == "2026-10-05"
    assert cfg.detector.daily_report_hour == 20


def test_load_config_missing_env() -> None:
    env = {k: v for k, v in ENV.items() if k != "SUPABASE_ANON_KEY"}
    with pytest.raises(ConfigError) as e:
        load_config(EXAMPLE, env=env)
    assert str(e.value) == "SUPABASE_ANON_KEY"


def test_load_config_mapping_and_empty_apprise(tmp_path: Path) -> None:
    p = tmp_path / "c.toml"
    p.write_text(
        '[household]\nid = "h"\nslug = "s"\n[mqtt]\nhost = "localhost"\nport = 1883\n'
        '[store]\npath = ":memory:"\n[apprise]\nurls = "env:SOLOWATCH_APPRISE_URLS"\n'
        '[[sensor]]\nsensor_id = "plug_tv"\nkind = "plug"\nunit = "W"\nmin_deviation = 300.0\n'
        'active_threshold = 60.0\ntopic = "tele/tv/SENSOR"\nvalue_path = "ENERGY.Power"\n'
        'ts_path = "Time"\n', encoding="utf-8")
    cfg = load_config(str(p), env={"SOLOWATCH_APPRISE_URLS": ""})
    assert cfg.supabase is None
    assert cfg.apprise_urls == ()
    assert cfg.install_start is None
    assert cfg.sensors == (TASMOTA,)


# --- Ingester.on_message (no broker) -------------------------------------------------------

@dataclass
class FakeMsg:
    topic: str
    payload: bytes


def test_ingester_on_message_writes_store() -> None:
    cfg = load_config(EXAMPLE, env=ENV)
    store = SqliteStore(":memory:")
    try:
        ing = Ingester(cfg, store)
        t = "solowatch/home-demo/water_main/state"
        ing.on_message(None, None, FakeMsg(t, b'{"ts":"2026-10-05T06:30:00+09:00","value":1.5}'))
        ing.on_message(None, None, FakeMsg(t, b'{"ts":"2026-10-05T06:32:00+09:00","value":2}'))
        ing.on_message(None, None, FakeMsg(t, b'{"ts":"2026-10-05T06:35:00+09:00","value":1}'))
        ing.on_message(None, None, FakeMsg(t, b"not json"))
        ing.on_message(None, None, FakeMsg("other/topic", b'{"value": 1}'))
        assert store.count_readings() == 0           # nothing written until flush
        assert ing.flush() == 2
        assert ing.stats.received == 5
        assert ing.stats.dropped == 2
        assert ing.stats.stored == 2
        usage = store.hourly_usage("water_main", at(6, 0), at(7, 0))
        assert usage[0].value == pytest.approx(4.5)
        assert ing.idle_for() >= 0.0
    finally:
        store.close()
