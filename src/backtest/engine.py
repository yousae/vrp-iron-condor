"""
Backtest engine: simulates the strategy against historical data.

See docs/project_spec.md sections 4 and 7. Key requirements to preserve
as this gets built out:
  - No look-ahead: IV rank on any date must only use data available by
    that date.
  - Model transaction costs and bid-ask slippage, not mid-price fills.
  - Report pre-2010 and post-2010 performance separately.
  - Log every trade (entry date, strikes, premium collected, exit date/
    reason) -- this log becomes the dataset for the write-up.
"""

from dataclasses import dataclass
import pandas as pd


@dataclass
class Trade:
    entry_date: str
    expiration_date: str
    short_put_strike: float
    long_put_strike: float
    short_call_strike: float
    long_call_strike: float
    premium_collected: float
    exit_date: str | None = None
    exit_reason: str | None = None
    pnl: float | None = None


class BacktestEngine:
    """Runs the iron condor strategy over historical data and logs trades.

    TODO: this is the core Phase 3 deliverable. Build out once the data
    pipeline (Phase 2) and signal (src/signals/iv_rank.py) are working.
    """

    def __init__(self, params: dict):
        self.params = params
        self.trades: list[Trade] = []

    def run(self, price_history: pd.DataFrame, iv_history: pd.Series) -> list[Trade]:
        """Simulate the strategy and return the full trade log.

        TODO: implement the monthly roll loop -- check entry_signal each
        roll date, construct a Trade if triggered, carry to expiration
        (v1) or manage per config (v2), append to self.trades.
        """
        raise NotImplementedError

    def summary_stats(self) -> dict:
        """Compute Sharpe, Sortino, max drawdown, win rate, etc. from
        self.trades, split by pre-2010 / post-2010 per config.

        TODO: implement. Cross-check formulas against quant-verify skill
        before reporting any number in the write-up.
        """
        raise NotImplementedError
