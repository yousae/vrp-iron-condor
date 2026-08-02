"""
Backtest engine: simulates the strategy against historical data.

See docs/project_spec.md sections 4 and 7. Key requirements preserved here:
  - No look-ahead: IV rank on any date must only use data available by
    that date. (This applies to the ENTRY decision only -- reading a
    trade's SETTLEMENT price at its future expiration date is not
    look-ahead, it's how backtesting a completed historical trade works.
    The entry_signal for day T never sees anything past day T.)
  - Model transaction costs and bid-ask slippage, not mid-price fills.
  - Report pre-2010 and post-2010 performance separately -- never blended.
  - Log every trade (entry date, strikes, premium collected, exit date/
    reason) -- this log becomes the dataset for the write-up.

Phase 3 status: real historical SPX options chain data isn't available
yet (project_spec.md section 6), so trade legs are priced synthetically
via Black-Scholes off VIX (see src/backtest/pricing.py and the
pricing_proxy section of config/params.yaml for the caveats this
introduces -- most importantly, no volatility skew).

v1 uses a fixed 1 contract per trade, not Kelly sizing -- Kelly needs
this backtest's own win rate / payoff stats as its input (src/risk/sizing.py),
so raw 1-lot statistics have to come first.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# needed so `from src...` resolves whether this file is run directly
# (python src/backtest/engine.py) or imported from elsewhere
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.backtest.pricing import bs_price, strike_from_delta
from src.signals.iv_rank import compute_iv_rank, entry_signal


@dataclass
class Trade:
    entry_date: pd.Timestamp
    expiration_date: pd.Timestamp
    entry_spx: float
    expiration_spx: float
    iv_rank_at_entry: float
    short_put_strike: float
    long_put_strike: float
    short_call_strike: float
    long_call_strike: float
    gross_credit_usd: float
    net_credit_usd: float
    costs_usd: float
    pnl: float
    exit_date: pd.Timestamp
    exit_reason: str = "expiration"  # only exit path in v1 (hold to expiration)


class BacktestEngine:
    """Runs the iron condor strategy over historical data and logs trades.

    params must include (see config/params.yaml):
      signal.iv_rank_lookback_days, threshold (single value -- the sweep
      calls this engine once per threshold, per iv_rank.py's design),
      structure.short_delta, structure.long_delta,
      pricing_proxy.dte_trading_days, pricing_proxy.contract_multiplier,
      backtest.cost_per_contract_usd, backtest.slippage_pct_of_credit.
    """

    def __init__(self, params: dict):
        self.params = params
        self.trades: list[Trade] = []

    def run(self, spx: pd.Series, vix: pd.Series, risk_free_rate: pd.Series) -> list[Trade]:
        """Simulate the strategy and return the full trade log.

        Monthly-cycle roll loop: scans forward day by day, and whenever
        entry_signal fires with no position currently open, constructs a
        condor priced off that day's VIX/SPX/rate, holds it to expiration
        dte_trading_days later (v1: no early management), and logs the
        Trade. Then skips ahead past that expiration before looking for
        the next entry -- v1 never holds more than one position at once.
        """
        lookback_days = self.params["signal"]["iv_rank_lookback_days"]
        threshold = self.params["threshold"]
        short_delta = self.params["structure"]["short_delta"]
        long_delta = self.params["structure"]["long_delta"]
        dte = self.params["pricing_proxy"]["dte_trading_days"]
        multiplier = self.params["pricing_proxy"]["contract_multiplier"]
        cost_per_contract = self.params["backtest"]["cost_per_contract_usd"]
        slippage_pct = self.params["backtest"]["slippage_pct_of_credit"]

        iv_rank = compute_iv_rank(vix, lookback_days)
        signal = entry_signal(iv_rank, threshold)

        self.trades = []
        i = 0
        n = len(spx)
        while i < n - dte:
            if not signal.iloc[i]:
                i += 1
                continue

            entry_date = spx.index[i]
            expiration_date = spx.index[i + dte]
            S0 = float(spx.iloc[i])
            S_T = float(spx.iloc[i + dte])
            sigma = float(vix.iloc[i]) / 100.0
            r = float(risk_free_rate.iloc[i])
            T = dte / 252.0

            short_put_K = strike_from_delta(S0, T, r, sigma, -short_delta, "put")
            long_put_K = strike_from_delta(S0, T, r, sigma, -long_delta, "put")
            short_call_K = strike_from_delta(S0, T, r, sigma, short_delta, "call")
            long_call_K = strike_from_delta(S0, T, r, sigma, long_delta, "call")

            short_put_price = bs_price(S0, short_put_K, T, r, sigma, "put")
            long_put_price = bs_price(S0, long_put_K, T, r, sigma, "put")
            short_call_price = bs_price(S0, short_call_K, T, r, sigma, "call")
            long_call_price = bs_price(S0, long_call_K, T, r, sigma, "call")

            gross_credit = (short_put_price - long_put_price) + (short_call_price - long_call_price)
            gross_credit_usd = gross_credit * multiplier
            net_credit_usd = gross_credit_usd * (1 - slippage_pct)

            put_side_loss = max(0.0, short_put_K - S_T) - max(0.0, long_put_K - S_T)
            call_side_loss = max(0.0, S_T - short_call_K) - max(0.0, S_T - long_call_K)
            loss_usd = (put_side_loss + call_side_loss) * multiplier

            costs_usd = cost_per_contract * 4  # 4 legs
            pnl = net_credit_usd - loss_usd - costs_usd

            self.trades.append(Trade(
                entry_date=entry_date,
                expiration_date=expiration_date,
                entry_spx=S0,
                expiration_spx=S_T,
                iv_rank_at_entry=float(iv_rank.iloc[i]),
                short_put_strike=short_put_K,
                long_put_strike=long_put_K,
                short_call_strike=short_call_K,
                long_call_strike=long_call_K,
                gross_credit_usd=gross_credit_usd,
                net_credit_usd=net_credit_usd,
                costs_usd=costs_usd,
                pnl=pnl,
                exit_date=expiration_date,
            ))

            i += dte + 1  # no overlapping positions -- resume scanning after this trade closes

        return self.trades

    def summary_stats(self) -> dict:
        """Compute Sharpe, Sortino, max drawdown, win rate, etc. from
        self.trades, split by pre-2010 / post-2010 per config.

        Returns {"pre_2010": {...}, "post_2010": {...}} -- deliberately
        no blended/combined entry, per the standing rule against
        presenting one headline number across both regimes.
        """
        regime_split_year = self.params["backtest"]["regime_split_year"]
        starting_capital = self.params["risk"]["starting_capital_usd"]

        pre = [t for t in self.trades if t.entry_date.year < regime_split_year]
        post = [t for t in self.trades if t.entry_date.year >= regime_split_year]

        return {
            "pre_2010": self._regime_stats(pre, starting_capital),
            "post_2010": self._regime_stats(post, starting_capital),
        }

    @staticmethod
    def _regime_stats(trades: list[Trade], starting_capital: float) -> dict:
        n = len(trades)
        if n == 0:
            return {"n_trades": 0}

        trades = sorted(trades, key=lambda t: t.entry_date)
        pnls = np.array([t.pnl for t in trades])
        returns = pnls / starting_capital  # constant divisor: doesn't affect Sharpe/Sortino ratios

        win_rate = float((pnls > 0).mean())
        total_pnl = float(pnls.sum())

        span_years = (trades[-1].entry_date - trades[0].entry_date).days / 365.25
        trades_per_year = n / span_years if span_years > 0 else float("nan")

        sharpe = _sharpe_ratio(returns, trades_per_year)
        sortino = _sortino_ratio(returns, trades_per_year)

        # Dollar drawdown on the raw cumulative-pnl curve (high-water mark
        # starts at 0, before any trades), NOT starting_capital + cumsum(pnl)
        # as a %. v1 trades a fixed 1 contract regardless of account size
        # (see module docstring), and 1 full-size SPX contract's pnl swings
        # ($500-$2,000+ per trade) dwarf the $1,000 starting_capital
        # placeholder -- so equity goes negative almost immediately and a
        # %-of-equity drawdown is meaningless until real position sizing
        # (src/risk/sizing.py) scales trade size to actual account capital.
        cum_pnl = np.cumsum(pnls)
        high_water_mark = np.maximum.accumulate(np.insert(cum_pnl, 0, 0.0))[1:]
        max_drawdown_usd = float((cum_pnl - high_water_mark).min())

        return {
            "n_trades": n,
            "win_rate": win_rate,
            "total_pnl_usd": total_pnl,
            "avg_pnl_usd": float(pnls.mean()),
            "worst_trade_pnl_usd": float(pnls.min()),
            "trades_per_year": trades_per_year,
            "sharpe": sharpe,
            "sortino": sortino,
            "max_drawdown_usd": max_drawdown_usd,
        }


def _sharpe_ratio(returns: np.ndarray, trades_per_year: float) -> float:
    """mean(returns) / std(returns, ddof=1) * sqrt(trades_per_year).

    Needs >=2 points to get a std at all; NaN (not an error, not a
    silent 0/inf) when there isn't enough data.
    """
    if len(returns) < 2 or np.isnan(trades_per_year):
        return float("nan")
    std = returns.std(ddof=1)
    if std == 0:
        return float("nan")
    return float(returns.mean() / std * np.sqrt(trades_per_year))


def _sortino_ratio(returns: np.ndarray, trades_per_year: float, mar: float = 0.0) -> float:
    """(mean(returns) - MAR) / downside_deviation * sqrt(trades_per_year).

    downside_deviation is the standard textbook definition:
    sqrt(mean(min(r - MAR, 0)^2)) over ALL returns -- NOT std() of just
    the losing-trade subset around its own mean, which is a common but
    non-standard shortcut that gives a materially different number
    (verified: 0.177 vs 0.136 on a 5-trade hand-check) since it centers
    on the subset's mean instead of MAR, and uses ddof=1 over only the
    losing-trade count instead of RMS over the full sample.
    """
    if len(returns) < 2 or np.isnan(trades_per_year):
        return float("nan")
    downside_deviation = np.sqrt(np.mean(np.minimum(returns - mar, 0.0) ** 2))
    if downside_deviation == 0:
        return float("nan")
    return float((returns.mean() - mar) / downside_deviation * np.sqrt(trades_per_year))


if __name__ == "__main__":
    import yaml

    from src.data.proxy_signal import fetch_risk_free_rate_history, fetch_spx_history, fetch_vix_history

    with open(Path(__file__).resolve().parents[2] / "config" / "params.yaml") as f:
        config = yaml.safe_load(f)

    start, end = "2005-01-01", "2024-01-01"
    spx = fetch_spx_history(start, end)
    vix = fetch_vix_history(start, end)
    rate = fetch_risk_free_rate_history(start, end)

    # align all three series on shared trading days (yfinance sources can differ slightly)
    idx = spx.index.intersection(vix.index).intersection(rate.index)
    spx, vix, rate = spx.loc[idx], vix.loc[idx], rate.loc[idx]

    for threshold in config["signal"]["iv_rank_thresholds_to_test"]:
        params = dict(config)
        params["threshold"] = threshold
        engine = BacktestEngine(params)
        trades = engine.run(spx, vix, rate)
        stats = engine.summary_stats()

        print(f"=== threshold > {threshold} ({len(trades)} trades) ===")
        for regime, s in stats.items():
            print(f"  {regime}: {s}")
        print()
