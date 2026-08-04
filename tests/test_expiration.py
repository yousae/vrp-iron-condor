"""Tests for src/execution/expiration.py."""

from datetime import date

import pytest

from src.execution.expiration import calendar_days_to, next_monthly_expiration, third_friday


@pytest.mark.parametrize("year,month,expected", [
    (2026, 8, date(2026, 8, 21)),
    (2026, 9, date(2026, 9, 18)),
    (2026, 12, date(2026, 12, 18)),
    (2027, 1, date(2027, 1, 15)),
    (2026, 5, date(2026, 5, 15)),   # month starting on a Friday
])
def test_third_friday_known_dates(year, month, expected):
    assert third_friday(year, month) == expected


def test_third_friday_is_always_a_friday():
    for month in range(1, 13):
        assert third_friday(2026, month).weekday() == 4


def test_third_friday_rejects_bad_month():
    with pytest.raises(ValueError):
        third_friday(2026, 13)


def test_never_returns_expiration_closer_than_the_floor():
    """The backtest prices 21 trading days (~30 calendar). Entering a much
    shorter-dated trade would be an unmodeled deviation."""
    for day in range(1, 29):
        from_date = date(2026, 8, day)
        exp = next_monthly_expiration(from_date, target_calendar_days=30, min_calendar_days=21)
        assert calendar_days_to(exp, from_date) >= 21


def test_rolls_to_next_month_when_near_expiration_is_too_close():
    # Aug 18 2026 -> Aug 21 is only 3 days out, so it must skip to September
    assert next_monthly_expiration(date(2026, 8, 18), 30, 21) == date(2026, 9, 18)


def test_picks_nearest_eligible_to_target():
    # Aug 3 -> Aug 21 (18d) is below the floor; Sep 18 (46d) is the nearest eligible
    assert next_monthly_expiration(date(2026, 8, 3), 30, 21) == date(2026, 9, 18)


def test_handles_year_rollover():
    exp = next_monthly_expiration(date(2026, 12, 20), 30, 21)
    assert exp == date(2027, 1, 15)


def test_result_is_always_a_third_friday():
    for day in (1, 10, 20, 28):
        exp = next_monthly_expiration(date(2026, 8, day), 30, 21)
        assert exp == third_friday(exp.year, exp.month)


@pytest.mark.parametrize("kwargs", [
    {"target_calendar_days": 0},
    {"min_calendar_days": 0},
])
def test_rejects_invalid_arguments(kwargs):
    with pytest.raises(ValueError):
        next_monthly_expiration(date(2026, 8, 3), **kwargs)
