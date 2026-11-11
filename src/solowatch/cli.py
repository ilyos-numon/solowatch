"""`solowatch <command>`: one entry point that hands the remaining argv to each module's `main`."""
from __future__ import annotations

import argparse
import importlib
import sys
from datetime import timedelta
from pathlib import Path

from solowatch.contracts_mvp import DEFAULT_HOME, HomeScenario

SCENARIOS: dict[str, HomeScenario] = {"default": DEFAULT_HOME}

# command -> (module whose main(argv) runs it, help). Imported lazily so a missing optional
# module (or its dependency, e.g. matplotlib) only breaks its own command.
COMMANDS: dict[str, tuple[str, str]] = {
    "smoke": ("solowatch.pipeline", "simulate water -> store -> detect, JSON report"),
    "simulate-home": ("solowatch.cli", "write the simulated 4-sensor home into a SQLite store"),
    "publish-mock": ("solowatch.mock_publisher", "replay the simulated home over MQTT"),
    "daemon": ("solowatch.daemon", "home device loop: MQTT -> detect -> alerts -> feedback"),
    "ops-report": ("solowatch.ops_report", "Markdown operations record from the device store"),
    "render-rhythm": ("solowatch.render_rhythm", "rhythm heat-map PNG from the device store"),
    "demo-server": ("solowatch.demo_server", "cloud virtual home: demo HTTP API + web app"),
}


def simulate_home_main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="solowatch simulate-home")
    ap.add_argument("--db", required=True, help="SQLite path (readings are added)")
    ap.add_argument("--scenario", default="default", choices=sorted(SCENARIOS))
    ap.add_argument("--limit-days", type=int, default=None)
    args = ap.parse_args(argv)
    simulate_home = importlib.import_module("solowatch.simulate_home").simulate_home
    store_mod = importlib.import_module("solowatch.store")
    scenario = SCENARIOS[args.scenario]
    end = None if args.limit_days is None else scenario.start_dt + timedelta(days=args.limit_days)
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    store = store_mod.SqliteStore(args.db)
    try:
        n = 0
        by_sensor = simulate_home(scenario)
        for readings in by_sensor.values():
            n += store.insert_readings(r for r in readings if end is None or r.ts < end)
    finally:
        store.close()
    print(f"SIMULATED {n} readings for {len(by_sensor)} sensors")
    return 0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="solowatch", description="홀로안심 (SoloWatch) commands")
    sub = ap.add_subparsers(dest="command", metavar="command")
    for name, (_, text) in COMMANDS.items():
        sub.add_parser(name, help=text, add_help=False)
    return ap


def _run(command: str, rest: list[str]) -> int:
    module, _ = COMMANDS[command]
    if command == "simulate-home":
        return simulate_home_main(rest)
    if command == "smoke":
        rest = ["smoke", *rest]   # pipeline's parser owns the `smoke` sub-command
    try:
        target = importlib.import_module(module)
    except ImportError as e:
        print(f"solowatch {command}: cannot load {module}: {e}", file=sys.stderr)
        return 2
    try:
        return int(target.main(rest))
    except SystemExit as e:   # argparse --help / usage errors inside the module
        return e.code if isinstance(e.code, int) else 2


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in COMMANDS:
        return _run(args[0], args[1:])
    parser = _parser()
    try:
        parser.parse_args(args)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2
    parser.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
