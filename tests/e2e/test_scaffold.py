from datetime import date, datetime

import river

from solowatch.contracts import DEFAULT_SCENARIO, TZ, day_type, window_of


def test_scaffold_stack_and_contracts() -> None:
    assert river.__version__
    assert DEFAULT_SCENARIO.days == 28
    assert DEFAULT_SCENARIO.seed == 42
    assert len(DEFAULT_SCENARIO.anomalies) == 3
    assert window_of(datetime(2026, 10, 23, 7, 0, tzinfo=TZ)) == "morning"
    sat = date(2026, 10, 31)
    assert day_type(datetime(sat.year, sat.month, sat.day, tzinfo=TZ)) == "weekend"
