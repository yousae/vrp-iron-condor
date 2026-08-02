"""
IV rank signal: the entry gate for the strategy. Only enter a trade when
IV rank clears the configured threshold.

See docs/project_spec.md section 3. Thresholds and lookback come from
config/params.yaml -- do not hardcode them here.
"""

import pandas as pd


def compute_iv_rank(iv_series: pd.Series, lookback_days: int) -> pd.Series:
    """Compute IV rank: where today's IV sits within its own trailing
    lookback window, expressed 0-100.

    IMPORTANT: must only use data available up to each date (no look-ahead).
    Use pandas rolling() with a fixed window, not the full series' min/max.

    TODO: implement as (today's IV - rolling min) / (rolling max - rolling min) * 100
    """
    raise NotImplementedError


def entry_signal(iv_rank: pd.Series, threshold: float) -> pd.Series:
    """Boolean series: True on days where iv_rank clears the threshold
    and a new position may be opened.

    TODO: implement as a simple comparison; keep this function trivial so
    the sweep in config/params.yaml (iv_rank_thresholds_to_test) can call
    it once per threshold without any hidden logic.
    """
    raise NotImplementedError
