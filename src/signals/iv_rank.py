"""
IV rank signal: the entry gate for the strategy. Only enter a trade when
IV rank clears the configured threshold.

See docs/project_spec.md section 3. Thresholds and lookback come from
config/params.yaml -- do not hardcode them here.
"""

import numpy as np
import pandas as pd


def compute_iv_rank(iv_series: pd.Series, lookback_days: int) -> pd.Series:
    """Compute IV rank: where today's IV sits within its own trailing
    lookback window, expressed 0-100.

    IMPORTANT: must only use data available up to each date (no look-ahead).
    Uses a trailing rolling() window (rows T-lookback_days+1 .. T) rather
    than the full series' min/max, so iv_rank on date T is unaffected by
    any data after T -- the same requirement enforced in
    src/data/proxy_signal.py's realized-vol calc.

    Days before lookback_days of history exist are NaN (undefined rank,
    not a fabricated one), and any day where the trailing window's high
    equals its low (zero range) is also NaN rather than raising, since
    0/0 is undefined -- this should be rare on real IV data.
    """
    rolling_min = iv_series.rolling(window=lookback_days, min_periods=lookback_days).min()
    rolling_max = iv_series.rolling(window=lookback_days, min_periods=lookback_days).max()
    rolling_range = rolling_max - rolling_min

    with np.errstate(invalid="ignore", divide="ignore"):
        rank = (iv_series - rolling_min) / rolling_range * 100
    rank = rank.where(rolling_range != 0)

    rank.name = f"iv_rank_{lookback_days}d"
    return rank


def entry_signal(iv_rank: pd.Series, threshold: float) -> pd.Series:
    """Boolean series: True on days where iv_rank clears the threshold
    and a new position may be opened.

    Deliberately trivial (a single comparison) so the threshold sweep in
    config/params.yaml (iv_rank_thresholds_to_test) can call this once
    per threshold with no hidden logic to keep in sync across variants.
    NaN iv_rank (insufficient history) naturally compares False, so no
    signal fires before there's enough data to trust the rank.
    """
    signal = iv_rank > threshold
    signal.name = f"entry_signal_gt{threshold}"
    return signal


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from src.data.proxy_signal import fetch_vix_history

    vix = fetch_vix_history("2015-01-01", "2024-01-01")
    lookback_days = 252

    rank = compute_iv_rank(vix, lookback_days)
    print(f"IV rank ({lookback_days}d): {rank.dropna().shape[0]} non-NaN of {len(rank)} rows")
    print(f"Range: {rank.min():.1f} - {rank.max():.1f}")
    print()

    for threshold in [50, 70, 80]:
        signal = entry_signal(rank, threshold)
        pct_days = signal.mean() * 100
        print(f"threshold > {threshold}: signal True on {signal.sum()} days ({pct_days:.1f}% of history)")

    print()
    print("Sample (last 5 rows):")
    print(pd.DataFrame({"VIX": vix, "iv_rank": rank, "signal_gt70": entry_signal(rank, 70)}).tail())
