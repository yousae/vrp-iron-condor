"""
Tests for src/signals/iv_rank.py.

The most important test is a look-ahead check: iv_rank on date T must be
identical whether computed from a series ending at T or a series ending
at T + 100 (i.e. future data must not leak backwards).
"""

import numpy as np
import pandas as pd

from src.signals.iv_rank import compute_iv_rank, entry_signal


def _sample_series() -> pd.Series:
    return pd.Series(
        [20, 25, 15, 30, 22, 18, 18, 18, 18, 40],
        index=pd.date_range("2020-01-01", periods=10),
    )


def test_iv_rank_no_lookahead():
    iv = _sample_series()
    lookback = 4

    rank_short = compute_iv_rank(iv, lookback)

    future = pd.Series([5, 200, 1], index=pd.date_range("2020-01-11", periods=3))
    iv_extended = pd.concat([iv, future])
    rank_extended = compute_iv_rank(iv_extended, lookback)

    pd.testing.assert_series_equal(
        rank_short, rank_extended.loc[iv.index], check_names=False
    )


def test_iv_rank_bounded_0_to_100():
    iv = _sample_series()
    rank = compute_iv_rank(iv, lookback_days=4)
    valid = rank.dropna()

    assert (valid >= 0).all()
    assert (valid <= 100).all()


def test_iv_rank_matches_hand_calc():
    iv = _sample_series()
    rank = compute_iv_rank(iv, lookback_days=4)

    # window = iv[0:4] = [20, 25, 15, 30]; today (row 3) = 30, the window max
    assert rank.iloc[3] == 100.0
    # window = iv[1:5] = [25, 15, 30, 22]; today (row 4) = 22
    assert np.isclose(rank.iloc[4], 46.666666666666664)


def test_iv_rank_flat_window_is_nan_not_error():
    iv = _sample_series()
    rank = compute_iv_rank(iv, lookback_days=4)

    # window at row 8 = iv[5:9] = [18, 18, 18, 18] -- zero range, should be NaN
    assert np.isnan(rank.iloc[8])


def test_entry_signal_false_on_nan_rank():
    iv = _sample_series()
    rank = compute_iv_rank(iv, lookback_days=4)
    signal = entry_signal(rank, threshold=50)

    assert not signal[rank.isna()].any()


def test_entry_signal_threshold_comparison():
    rank = pd.Series([10.0, 50.0, 50.1, 90.0, np.nan])
    signal = entry_signal(rank, threshold=50)

    assert signal.tolist() == [False, False, True, True, False]
