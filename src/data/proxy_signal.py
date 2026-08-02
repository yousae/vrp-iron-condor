"""
Phase 2 target: a VIX/realized-volatility proxy for the IV-rank entry signal,
used to validate the timing signal directionally before paying for a full
historical SPX options chain provider.

See docs/project_spec.md section 6.
"""

import pandas as pd


def fetch_vix_history(start: str, end: str) -> pd.Series:
    """Fetch daily VIX close history for the given date range.

    TODO: pull from a free source (e.g. yfinance ^VIX) to start.
    Returns a pandas Series indexed by date.
    """
    raise NotImplementedError


def fetch_spx_history(start: str, end: str) -> pd.Series:
    """Fetch daily SPX close history for the given date range.

    TODO: pull from a free source (e.g. yfinance ^GSPC) to start.
    Used to compute realized volatility as a sanity check against VIX.
    """
    raise NotImplementedError


def compute_realized_volatility(prices: pd.Series, window_days: int = 21) -> pd.Series:
    """Rolling annualized realized volatility from a price series.

    TODO: implement as rolling std of log returns, annualized by sqrt(252).
    """
    raise NotImplementedError
