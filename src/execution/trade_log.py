"""
Append-only trade log.

project_spec.md s5: "Log every simulated, paper, and live trade with
entry/exit reason. This log is the dataset the eventual write-up depends
on." This is that log.

JSONL (one JSON object per line) rather than a database, deliberately:
it is append-only so a bug can't silently rewrite history, diffable in
git, readable without tooling, and loads into pandas in one line for the
write-up. At ~3 trades/year the scale argument for anything heavier does
not apply.

Every record carries a `kind` so the file can hold the whole lifecycle --
signal checks that did NOT trade are logged too. Those non-events are
what make the signal-fidelity check possible: to show the live signal
fired when the backtest says it should have, you need the days it
declined to fire, not just the days it traded.
"""

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DEFAULT_LOG_PATH = Path(__file__).resolve().parents[2] / "logs" / "trades.jsonl"


def _json_default(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"not JSON-serializable: {type(obj).__name__}")


def append(record: dict, path: Path = DEFAULT_LOG_PATH) -> dict:
    """Append one record, stamping it with a UTC timestamp.

    Returns the stamped record so callers can log and inspect in one
    step. Creates the parent directory if needed.
    """
    if "kind" not in record:
        raise ValueError("every log record needs a 'kind' (e.g. 'signal_check', 'order_submitted')")

    stamped = {"logged_at": datetime.now(timezone.utc).isoformat(), **record}

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(stamped, default=_json_default) + "\n")
    return stamped


def read_all(path: Path = DEFAULT_LOG_PATH) -> list[dict]:
    """Every record, oldest first. Empty list if the log doesn't exist yet."""
    if not path.exists():
        return []
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def read_kind(kind: str, path: Path = DEFAULT_LOG_PATH) -> list[dict]:
    """Records of one kind, oldest first."""
    return [r for r in read_all(path) if r.get("kind") == kind]


def open_positions(path: Path = DEFAULT_LOG_PATH) -> list[dict]:
    """Submitted orders with no corresponding settlement record.

    Used to enforce the no-overlapping-positions rule the backtest
    assumes (BacktestEngine.run holds one position at a time). If live
    were allowed to stack positions the backtest would no longer
    describe what ran.
    """
    records = read_all(path)

    settled_ids = {r.get("order_id") for r in records if r.get("kind") == "settled"}

    # An order that never FILLED is not a position. Cancelled and rejected
    # orders must be excluded or they block the bot permanently -- once
    # automated, a single unfilled order would silently stop all future
    # trading, which is exactly the kind of failure that looks like "the
    # signal just never fired again".
    dead_ids = {
        r.get("order_id") for r in records
        if r.get("kind") == "plumbing_test_result"
        and any(s in str(r.get("order_status", "")).upper()
                for s in ("CANCEL", "REJECT", "NOT_FILLED", "EXPIRED"))
    }

    # Plumbing tests are tagged separately so they never pollute Phase 5
    # statistics, but a FILLED one opens a real paper position and must
    # still block a concurrent trade.
    submitted = [r for r in records if r.get("kind") in ("order_submitted", "plumbing_test")]
    return [
        r for r in submitted
        if r.get("order_id") not in settled_ids and r.get("order_id") not in dead_ids
    ]


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        demo = Path(tmp) / "demo.jsonl"

        append({"kind": "signal_check", "iv_rank": 12.4, "threshold": 50, "fired": False}, demo)
        append({"kind": "signal_check", "iv_rank": 61.2, "threshold": 50, "fired": True}, demo)
        append({"kind": "order_submitted", "order_id": "abc123", "symbol": "XSP",
                "expiration": date(2026, 9, 18), "contracts": 1}, demo)

        print(f"{len(read_all(demo))} records, {len(read_kind('signal_check', demo))} signal checks")
        print(f"open positions: {[p['order_id'] for p in open_positions(demo)]}")

        append({"kind": "settled", "order_id": "abc123", "realized_pnl_usd": 412.50}, demo)
        print(f"after settlement: {[p['order_id'] for p in open_positions(demo)]}")
