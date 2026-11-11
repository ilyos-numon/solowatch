"""`publish-mock`: replay a simulated home over MQTT on the native topics, instead of hardware."""
from __future__ import annotations

import argparse
import heapq
import importlib
import json
import os
import sys
import threading
import time
from collections.abc import Iterator, Mapping
from datetime import timedelta
from typing import Any

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from solowatch.contracts import TZ, Reading
from solowatch.contracts_mvp import DEFAULT_HOME, AppConfig, ConfigError, HomeScenario, native_topic
from solowatch.mqtt_ingest import BrokerUnreachable
from solowatch.sensors_config import load_config

CONNECT_TIMEOUT = 5.0
ACK_TIMEOUT = 60.0
SCENARIOS: dict[str, HomeScenario] = {"default": DEFAULT_HOME}


class _LenientEnv(Mapping[str, str]):
    """os.environ where unset names read as "" — the publisher needs no Supabase/Apprise secrets."""

    def __init__(self, base: Mapping[str, str]) -> None:
        self._base = base

    def __getitem__(self, key: str) -> str:
        return self._base.get(key, "")

    def __iter__(self) -> Iterator[str]:
        return iter(self._base)

    def __len__(self) -> int:
        return len(self._base)


def _connect(cfg: AppConfig) -> mqtt.Client:
    connected = threading.Event()
    result: dict[str, Any] = {}

    def on_connect(client: Any, userdata: Any, flags: Any, reason_code: Any,
                   properties: Any) -> None:
        result["rc"] = reason_code
        if not reason_code.is_failure:
            connected.set()

    client = mqtt.Client(CallbackAPIVersion.VERSION2, clean_session=True)
    if cfg.mqtt.username:
        client.username_pw_set(cfg.mqtt.username, cfg.mqtt.password or None)
    client.on_connect = on_connect
    client.connect_timeout = CONNECT_TIMEOUT
    where = f"{cfg.mqtt.host}:{cfg.mqtt.port}"
    try:
        client.connect(cfg.mqtt.host, cfg.mqtt.port)
    except OSError as e:
        raise BrokerUnreachable(f"{where}: {e}") from e
    client.loop_start()
    if not connected.wait(CONNECT_TIMEOUT):
        client.loop_stop()
        raise BrokerUnreachable(f"{where}: {result.get('rc', 'no CONNACK')}")
    return client


def publish_scenario(cfg: AppConfig, scenario: HomeScenario, qos: int = 1,
                     limit_days: int | None = None) -> int:
    """Publish every reading in time order; return once the broker acked the last one."""
    client = _connect(cfg)
    try:
        # S3 module, imported lazily so the broker check works without it.
        simulate_home = importlib.import_module("solowatch.simulate_home").simulate_home
        by_sensor: dict[str, list[Reading]] = simulate_home(scenario)
        units = {s.sensor_id: s.unit for s in scenario.sensors}
        end = None if limit_days is None else scenario.start_dt + timedelta(days=limit_days)
        streams = [
            [r for r in by_sensor[s.sensor_id] if end is None or r.ts < end]
            for s in scenario.sensors if s.sensor_id in by_sensor
        ]
        infos = []
        for r in heapq.merge(*streams, key=lambda x: x.ts):
            payload = json.dumps({"ts": r.ts.astimezone(TZ).isoformat(), "value": r.value,
                                  "unit": units[r.sensor_id]})
            infos.append(client.publish(native_topic(cfg.slug, r.sensor_id), payload, qos=qos))
        deadline = time.monotonic() + ACK_TIMEOUT
        for info in infos:
            info.wait_for_publish(max(0.1, deadline - time.monotonic()))
            if not info.is_published():
                raise BrokerUnreachable("broker did not acknowledge all messages")
        return len(infos)
    finally:
        client.disconnect()
        client.loop_stop()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="publish-mock", description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--scenario", default="default", choices=sorted(SCENARIOS))
    ap.add_argument("--qos", type=int, default=1, choices=(0, 1, 2))
    ap.add_argument("--limit-days", type=int, default=None)
    args = ap.parse_args(argv)
    try:
        cfg = load_config(args.config, env=_LenientEnv(os.environ))
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    scenario = SCENARIOS[args.scenario]
    try:
        n = publish_scenario(cfg, scenario, qos=args.qos, limit_days=args.limit_days)
    except BrokerUnreachable as e:
        print(f"broker unreachable: {e}", file=sys.stderr)
        return 2
    print(f"PUBLISHED {n} messages for {len(scenario.sensors)} sensors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
