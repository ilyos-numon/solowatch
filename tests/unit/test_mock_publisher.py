from __future__ import annotations

import json
import sys
import time
import types
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from solowatch import mock_publisher
from solowatch.contracts import SLOT, Reading
from solowatch.contracts_mvp import DEFAULT_HOME

EXAMPLE = Path(__file__).resolve().parents[2] / "config" / "solowatch.example.toml"


def test_broker_down_exits_2_quickly(tmp_path: Path) -> None:
    cfg = tmp_path / "c.toml"
    cfg.write_text(EXAMPLE.read_text(encoding="utf-8").replace("port = 57883", "port = 57884"),
                   encoding="utf-8")
    t0 = time.monotonic()
    assert mock_publisher.main(["--config", str(cfg), "--limit-days", "1"]) == 2
    assert time.monotonic() - t0 < 10


class _Info:
    def wait_for_publish(self, timeout: float | None = None) -> None:
        pass

    def is_published(self) -> bool:
        return True


class _FakeClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, int]] = []

    def publish(self, topic: str, payload: str, qos: int = 0) -> _Info:
        self.published.append((topic, payload, qos))
        return _Info()

    def disconnect(self) -> None:
        pass

    def loop_stop(self) -> None:
        pass


def test_publish_scenario_order_payload_limit(monkeypatch: pytest.MonkeyPatch,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    start = DEFAULT_HOME.start_dt
    n = 2 * 288

    def fake_simulate_home(scenario: Any) -> dict[str, list[Reading]]:
        return {s.sensor_id: [Reading(s.sensor_id, start + i * SLOT, float(i)) for i in range(n)]
                for s in scenario.sensors}

    fake = _FakeClient()
    monkeypatch.setitem(sys.modules, "solowatch.simulate_home",
                        types.SimpleNamespace(simulate_home=fake_simulate_home))
    monkeypatch.setattr(mock_publisher, "_connect", lambda cfg: fake)

    assert mock_publisher.main(["--config", str(EXAMPLE), "--limit-days", "1"]) == 0
    assert capsys.readouterr().out.strip() == "PUBLISHED 1152 messages for 4 sensors"

    assert len(fake.published) == 1152
    assert {q for _, _, q in fake.published} == {1}
    topics = {t for t, _, _ in fake.published}
    assert topics == {f"solowatch/home-demo/{s}/state"
                      for s in ("water_main", "plug_fridge", "plug_tv", "plug_light")}
    first = json.loads(fake.published[0][1])
    assert first == {"ts": start.isoformat(), "value": 0.0, "unit": "L"}
    assert json.loads(fake.published[1][1])["unit"] == "W"
    stamps = [json.loads(p)["ts"] for _, p, _ in fake.published]
    assert stamps == sorted(stamps)
    assert stamps[-1] == (start + timedelta(days=1) - SLOT).isoformat()
