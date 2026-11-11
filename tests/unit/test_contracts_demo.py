from __future__ import annotations

from typing import get_args

from solowatch.contracts_demo import (
    DEMO_EVENT_FOCUS,
    DEMO_EVENT_KINDS,
    DEMO_EVENT_LABEL_KO,
    DEMO_HOUSEHOLD_ID,
    DemoEventKind,
    DemoState,
    InjectResult,
    OutboxEntry,
    ScoreEntry,
    VirtualHomeLike,
)
from solowatch.contracts_mvp import DEMO_HOUSEHOLD_ID as MVP_HOUSEHOLD_ID


def _score(sensor_id: str = "water_main", window: str = "morning") -> ScoreEntry:
    return ScoreEntry(sensor_id, window, "weekday", 0.42, 30.1, 0.0, True)


def _inject() -> InjectResult:
    return InjectResult(
        kind="no_morning_water", day="2026-11-02", day_type="weekday", readings=1152,
        alerts=[{"remote_id": "r1", "sentence": "s", "window_start": "2026-11-02T06:00:00+09:00"}],
        scores=[_score()], previous_scores=[], daily_sent=True, auto_reset=False)


def _outbox() -> OutboxEntry:
    return OutboxEntry("2026-11-03T00:00:00+00:00", "out", "alerts", "문장", {"kind": "anomaly"})


def test_event_kinds() -> None:
    assert len(DEMO_EVENT_KINDS) == 5
    assert set(DEMO_EVENT_KINDS) == set(get_args(DemoEventKind))
    assert set(DEMO_EVENT_FOCUS) == set(DEMO_EVENT_KINDS)
    assert set(DEMO_EVENT_LABEL_KO) == set(DEMO_EVENT_KINDS)
    assert DEMO_EVENT_FOCUS["normal"] == ()


def test_household_reexport() -> None:
    assert DEMO_HOUSEHOLD_ID == MVP_HOUSEHOLD_ID


def test_score_entry_to_dict() -> None:
    d = _score().to_dict()
    assert set(d) == {"sensor_id", "window", "day_type", "score", "expected", "actual", "flagged"}
    assert d["flagged"] is True and d["score"] == 0.42


def test_outbox_entry_to_dict() -> None:
    d = _outbox().to_dict()
    assert set(d) == {"at", "direction", "table", "summary", "row"}
    assert d["row"] == {"kind": "anomaly"}


def test_inject_result_to_dict() -> None:
    d = _inject().to_dict()
    assert set(d) == {"kind", "day", "day_type", "readings", "alerts", "scores",
                      "previous_scores", "daily_sent", "auto_reset"}
    assert d["scores"] == [_score().to_dict()]
    assert d["previous_scores"] == []


def test_demo_state_to_dict() -> None:
    st = DemoState(
        ready=True, virtual_now="2026-11-02T00:00:00+09:00", day_index=0,
        household_id=DEMO_HOUSEHOLD_ID, readings_total=32256,
        recent={"water_main": [["2026-11-01T23:55:00+09:00", 0.0]]},
        outbox=[_outbox()], last_inject=_inject(), history=[], error=None)
    d = st.to_dict()
    assert set(d) == {"ready", "virtual_now", "day_index", "household_id", "readings_total",
                      "recent", "outbox", "last_inject", "history", "error"}
    assert d["outbox"] == [_outbox().to_dict()]
    assert d["last_inject"] == _inject().to_dict()
    empty = DemoState(False, "", 0, DEMO_HOUSEHOLD_ID, 0, {}, [], None, [], "x").to_dict()
    assert empty["last_inject"] is None and empty["error"] == "x"


def test_virtual_home_like_protocol() -> None:
    assert {"reset", "inject", "state", "close"} <= set(dir(VirtualHomeLike))
