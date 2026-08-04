"""
Monthly options expiration dates.

Standard monthly index options expire on the third Friday. The backtest
approximates the cycle as a fixed 21 trading days (config
pricing_proxy.dte_trading_days), but a live order needs a real listed
expiration date, so this resolves the actual one nearest that target.

That mismatch is a real, disclosed inconsistency between backtest and
live. The backtest always holds exactly 21 trading days (~30 calendar);
live holds however long it is until the next monthly expiration, which
ranges roughly 25-46 calendar days depending on where in the cycle the
signal fires. The floor in next_monthly_expiration() prevents the
worse error (entering something much SHORTER than modeled), but the
upper spread remains and is inherent to signal-driven entry on a monthly
grid. Every trade's actual DTE is logged so the Phase 5 signal-fidelity
check can measure whether it mattered, rather than assuming it didn't.
"""

from datetime import date, timedelta

FRIDAY = 4  # date.weekday(): Monday=0


def third_friday(year: int, month: int) -> date:
    """The third Friday of the given month -- standard monthly expiration."""
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1-12, got {month}")

    first = date(year, month, 1)
    days_to_first_friday = (FRIDAY - first.weekday()) % 7
    return first + timedelta(days=days_to_first_friday + 14)


def next_monthly_expiration(
    from_date: date,
    target_calendar_days: int = 30,
    min_calendar_days: int = 21,
) -> date:
    """The listed monthly expiration closest to `target_calendar_days` out,
    subject to being at least `min_calendar_days` away.

    The floor matters. The backtest prices a fixed 21 TRADING days (~30
    calendar). Without a floor, a signal firing a few days before a third
    Friday would enter an ~18-day trade that the model never priced --
    materially less time premium, different risk, and an unmodeled
    deviation that would pollute the signal-fidelity check. When the near
    expiration is too close, this rolls to the next month instead.

    Considers this month and the following three, so it works regardless
    of where in the month `from_date` falls.
    """
    if target_calendar_days < 1:
        raise ValueError(f"target_calendar_days must be positive, got {target_calendar_days}")
    if min_calendar_days < 1:
        raise ValueError(f"min_calendar_days must be positive, got {min_calendar_days}")

    target = from_date + timedelta(days=target_calendar_days)

    candidates = []
    year, month = from_date.year, from_date.month
    for offset in range(5):
        m = month + offset
        candidates.append(third_friday(year + (m - 1) // 12, (m - 1) % 12 + 1))

    eligible = [d for d in candidates if (d - from_date).days >= min_calendar_days]
    if not eligible:
        raise RuntimeError(f"no expiration at least {min_calendar_days} days after {from_date}")

    return min(eligible, key=lambda d: abs((d - target).days))


def calendar_days_to(expiration: date, from_date: date) -> int:
    """Calendar days between two dates, for logging what was actually traded."""
    return (expiration - from_date).days


if __name__ == "__main__":
    today = date.today()
    exp = next_monthly_expiration(today, 30)
    print(f"today:                  {today}")
    print(f"next monthly expiry:    {exp}  ({calendar_days_to(exp, today)} calendar days out)")
    print()
    print("Third Fridays, next 6 months:")
    for offset in range(6):
        m = today.month + offset
        y, mm = today.year + (m - 1) // 12, (m - 1) % 12 + 1
        print(f"  {y}-{mm:02d}: {third_friday(y, mm)}")
