"""MQTT -> 5-minute `Reading`s -> Store. Protocol handling is paho-mqtt's; this is mapping glue."""
from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from solowatch.contracts import SLOT, TZ, Reading, Store
from solowatch.contracts_mvp import AppConfig, SensorSpec

QOS = 1


def topic_matches(pattern: str, topic: str) -> bool:
    """MQTT `+`/`#` wildcard match (paho's implementation)."""
    return bool(mqtt.topic_matches_sub(pattern, topic))


def _walk(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(obj, dict) or part not in obj:
            raise KeyError(path)
        obj = obj[part]
    return obj


def _number(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    if not math.isfinite(f) or f < 0:
        return None
    return f


def _parse_ts(v: Any) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)


def extract(payload: bytes, spec: SensorSpec, now: datetime) -> tuple[datetime, float] | None:
    """(ts, value) from a payload per `spec.value_path`/`ts_path`; None means drop."""
    try:
        obj = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return None
    now = now.astimezone(TZ) if now.tzinfo is not None else now.replace(tzinfo=TZ)
    if not isinstance(obj, dict):
        if spec.value_path != "value":
            return None
        value = _number(obj)
        return None if value is None else (now, value)
    try:
        value = _number(_walk(obj, spec.value_path))
    except KeyError:
        return None
    if value is None:
        return None
    try:
        raw_ts = _walk(obj, spec.ts_path)
    except KeyError:
        return now, value
    ts = _parse_ts(raw_ts)
    return None if ts is None else (ts, value)


def _slot_of(ts: datetime) -> datetime:
    ts = ts.astimezone(TZ)
    minutes = int(SLOT.total_seconds() // 60)
    return ts.replace(minute=ts.minute - ts.minute % minutes, second=0, microsecond=0)


class SlotAccumulator:
    """Per-sensor open 5-minute slot. unit L sums, unit W averages."""

    def __init__(self, sensors: Iterable[SensorSpec]) -> None:
        self._units = {s.sensor_id: s.unit for s in sensors}
        self._open: dict[str, tuple[datetime, float, int]] = {}

    def _reading(self, sensor_id: str, slot: datetime, total: float, n: int) -> Reading:
        value = total / n if self._units[sensor_id] == "W" else total
        return Reading(sensor_id, slot, value)

    def add(self, sensor_id: str, ts: datetime, value: float) -> list[Reading]:
        if sensor_id not in self._units:
            raise KeyError(sensor_id)
        slot = _slot_of(ts)
        cur = self._open.get(sensor_id)
        if cur is None:
            self._open[sensor_id] = (slot, value, 1)
            return []
        cur_slot, total, n = cur
        if slot == cur_slot:
            self._open[sensor_id] = (slot, total + value, n + 1)
            return []
        if slot > cur_slot:
            self._open[sensor_id] = (slot, value, 1)
            return [self._reading(sensor_id, cur_slot, total, n)]
        # Late message for an older slot: emit on its own (store ignores an existing slot).
        return [self._reading(sensor_id, slot, value, 1)]

    def flush(self) -> list[Reading]:
        out = [self._reading(sid, slot, total, n) for sid, (slot, total, n) in self._open.items()]
        self._open.clear()
        return out


@dataclass
class IngestStats:
    received: int = 0
    dropped: int = 0
    stored: int = 0


class BrokerUnreachable(RuntimeError):
    pass


class Ingester:
    """Subscribes to every sensor topic and feeds a SlotAccumulator.

    paho callbacks run on its network thread; closed readings are buffered and written to the
    store only in `flush()` (called from the owner's thread, as sqlite3 requires).
    """

    def __init__(self, cfg: AppConfig, store: Store) -> None:
        self.stats = IngestStats()
        self._cfg = cfg
        self._store = store
        self._sensors = cfg.sensors
        self._acc = SlotAccumulator(cfg.sensors)
        self._pending: list[Reading] = []
        self._lock = threading.Lock()
        self._last_rx = time.monotonic()
        self._connected = threading.Event()
        self._connect_rc: Any = None
        self._started = False
        self._client = mqtt.Client(CallbackAPIVersion.VERSION2, clean_session=True)
        if cfg.mqtt.username:
            self._client.username_pw_set(cfg.mqtt.username, cfg.mqtt.password or None)
        self._client.on_connect = self.on_connect
        self._client.on_message = self.on_message

    def _topics(self) -> list[tuple[str, int]]:
        return [(t, QOS) for t in dict.fromkeys(s.topic for s in self._sensors)]

    def on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any,
                   properties: Any) -> None:
        self._connect_rc = reason_code
        if reason_code.is_failure:
            return
        self._connected.set()
        if self._started:
            client.subscribe(self._topics())

    def on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        now = datetime.now(TZ)
        with self._lock:
            self.stats.received += 1
            self._last_rx = time.monotonic()
            specs = [s for s in self._sensors if topic_matches(s.topic, msg.topic)]
            if not specs:
                self.stats.dropped += 1
                return
            for spec in specs:
                got = extract(msg.payload, spec, now)
                if got is None:
                    self.stats.dropped += 1
                    continue
                self._pending.extend(self._acc.add(spec.sensor_id, got[0], got[1]))

    def connect(self, timeout: float = 15.0) -> None:
        self._client.connect_timeout = timeout
        try:
            self._client.connect(self._cfg.mqtt.host, self._cfg.mqtt.port)
        except OSError as e:
            raise BrokerUnreachable(f"{self._cfg.mqtt.host}:{self._cfg.mqtt.port}: {e}") from e
        deadline = time.monotonic() + timeout
        while not self._connected.is_set() and time.monotonic() < deadline:
            rc = self._client.loop(timeout=0.1)
            if self._connect_rc is not None and self._connect_rc.is_failure:
                break
            if rc != mqtt.MQTT_ERR_SUCCESS:
                break
        if not self._connected.is_set():
            reason = self._connect_rc if self._connect_rc is not None else "no CONNACK"
            raise BrokerUnreachable(f"{self._cfg.mqtt.host}:{self._cfg.mqtt.port}: {reason}")

    def start(self) -> None:
        self._started = True
        self._client.subscribe(self._topics())
        self._client.loop_start()

    def stop(self) -> None:
        self._client.disconnect()
        self._client.loop_stop()

    def flush(self) -> int:
        with self._lock:
            readings = self._pending + self._acc.flush()
            self._pending = []
        stored = self._store.insert_readings(readings)
        with self._lock:
            self.stats.stored += stored
        return stored

    def idle_for(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_rx
