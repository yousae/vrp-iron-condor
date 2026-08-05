"""
Tests for src/execution/trade_log.py.

Kept separate from test_runner.py: that file autouse-stubs
open_positions() to isolate the decision tests, which would silently
neuter these.
"""

from datetime import date
from pathlib import Path

import pytest

from src.execution import trade_log


def test_log_roundtrip(tmp_path: Path):
    log = tmp_path / "t.jsonl"
    trade_log.append({"kind": "signal_check", "fired": False}, log)
    trade_log.append({"kind": "signal_check", "fired": True}, log)

    records = trade_log.read_all(log)
    assert len(records) == 2
    assert all("logged_at" in r for r in records)
    assert [r["fired"] for r in records] == [False, True]


def test_log_requires_a_kind(tmp_path: Path):
    with pytest.raises(ValueError, match="kind"):
        trade_log.append({"fired": True}, tmp_path / "t.jsonl")


def test_log_serializes_dates(tmp_path: Path):
    log = tmp_path / "t.jsonl"
    trade_log.append({"kind": "order_submitted", "expiration": date(2026, 9, 18)}, log)

    assert trade_log.read_all(log)[0]["expiration"] == "2026-09-18"


def test_read_all_on_missing_file_is_empty(tmp_path: Path):
    assert trade_log.read_all(tmp_path / "nope.jsonl") == []


def test_open_positions_excludes_settled(tmp_path: Path):
    log = tmp_path / "t.jsonl"
    trade_log.append({"kind": "order_submitted", "order_id": "a"}, log)
    trade_log.append({"kind": "order_submitted", "order_id": "b"}, log)
    trade_log.append({"kind": "settled", "order_id": "a"}, log)

    assert [p["order_id"] for p in trade_log.open_positions(log)] == ["b"]


def test_cancelled_order_is_not_an_open_position(tmp_path: Path):
    """An unfilled order is not a position. If it counted, one cancelled
    order would block all future trading forever once automated -- and it
    would look exactly like the signal never firing again."""
    log = tmp_path / "t.jsonl"
    trade_log.append({"kind": "plumbing_test", "order_id": "a", "order_status": "OrderStatus.NEW"}, log)
    trade_log.append({"kind": "plumbing_test_result", "order_id": "a",
                      "order_status": "CANCELED_UNFILLED"}, log)

    assert trade_log.open_positions(log) == []


def test_filled_order_still_counts_as_open(tmp_path: Path):
    log = tmp_path / "t.jsonl"
    trade_log.append({"kind": "plumbing_test", "order_id": "b", "order_status": "OrderStatus.NEW"}, log)
    trade_log.append({"kind": "plumbing_test_result", "order_id": "b",
                      "order_status": "FILLED"}, log)

    assert [p["order_id"] for p in trade_log.open_positions(log)] == ["b"]


def test_rejected_order_is_not_an_open_position(tmp_path: Path):
    log = tmp_path / "t.jsonl"
    trade_log.append({"kind": "plumbing_test", "order_id": "c"}, log)
    trade_log.append({"kind": "plumbing_test_result", "order_id": "c",
                      "order_status": "OrderStatus.REJECTED"}, log)

    assert trade_log.open_positions(log) == []
