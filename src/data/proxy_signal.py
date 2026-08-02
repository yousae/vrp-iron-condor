"""
Phase 2 target: a VIX/realized-volatility proxy for the IV-rank entry signal,
used to validate the timing signal directionally before paying for a full
historical SPX options chain provider.

See docs/project_spec.md section 6.
"""

import numpy as np
import pandas as pd
import yfinance as yf


def fetch_vix_history(start: str, end: str) -> pd.Series:
    """Fetch daily VIX close history for the given date range.

    Returns a pandas Series of closing prices indexed by date (tz-naive).
    """
    data = yf.download("^VIX", start=start, end=end, progress=False, auto_adjust=False)
    if data.empty:
        raise ValueError(f"No VIX data returned for {start}..{end}")
    series = data["Close"]
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    series = series.copy()
    series.index = series.index.tz_localize(None)
    series.name = "VIX"
    return series


def fetch_spx_history(start: str, end: str) -> pd.Series:
    """Fetch daily SPX close history for the given date range.

    Used to compute realized volatility as a sanity check against VIX.
    """
    data = yf.download("^GSPC", start=start, end=end, progress=False, auto_adjust=False)
    if data.empty:
        raise ValueError(f"No SPX data returned for {start}..{end}")
    series = data["Close"]
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    series = series.copy()
    series.index = series.index.tz_localize(None)
    series.name = "SPX"
    return series


def compute_realized_volatility(prices: pd.Series, window_days: int = 21) -> pd.Series:
    """Rolling annualized realized volatility from a price series.

    Computed as the rolling standard deviation of daily log returns,
    annualized by sqrt(252). Uses a trailing (right-aligned) rolling
    window, so the value on date T only reflects log returns through
    date T -- no look-ahead: this is critical since realized vol here
    is compared against VIX (a forward-looking, same-day quantity) to
    validate the IV-rank timing signal, and any leakage of future
    returns into a "trailing" vol figure would make the signal look
    better than it could actually have been traded.
    """
    log_returns = np.log(prices / prices.shift(1))
    rolling_std = log_returns.rolling(window=window_days, min_periods=window_days).std()
    annualized = rolling_std * np.sqrt(252)
    result = annualized * 100  # match VIX's convention of quoting vol in percentage points
    result.name = f"realized_vol_{window_days}d"
    return result


if __name__ == "__main__":
    start, end = "2015-01-01", "2024-01-01"
    vix = fetch_vix_history(start, end)
    spx = fetch_spx_history(start, end)
    rv = compute_realized_volatility(spx, window_days=21)

    print(f"VIX: {len(vix)} rows, {vix.index.min().date()} -> {vix.index.max().date()}")
    print(f"SPX: {len(spx)} rows, {spx.index.min().date()} -> {spx.index.max().date()}")
    print(f"Realized vol: {len(rv)} rows, {rv.dropna().shape[0]} non-NaN")
    print()
    print("Sample (last 5 rows):")
    combined = pd.DataFrame({"VIX": vix, "SPX": spx, "realized_vol_21d": rv}).dropna()
    print(combined.tail())
    print()
    print(f"Mean VIX: {vix.mean():.2f}  |  Mean realized vol (21d): {rv.mean():.2f}")
