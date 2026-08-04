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

from src.execution.ticket import build_ticket
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

        # Backtest the instrument and structure that will ACTUALLY be traded.
        # Without this the backtest priced full-size SPX with delta-based
        # wings (median max loss ~$10,900, 5x over the 2% risk cap) while the
        # runner traded 1/10-size XSP with fixed wings -- so the reported
        # Sharpe, win rate, and the avg_win/avg_loss feeding Kelly all
        # described a strategy that would never be placed.
        execution = self.params.get("execution", {})
        symbol = execution.get("symbol") or self.params["structure"].get("underlying", "SPX")
        scale = 0.1 if symbol.upper() == "XSP" else 1.0
        wing_width = execution.get("wing_width_points")
        strike_increment = execution.get("strike_increment")
        skew = self.params.get("pricing_proxy", {}).get("skew_sensitivity", {}) or {}
        put_iv_adj = skew.get("put_iv_points", 0.0)
        call_iv_adj = skew.get("call_iv_points", 0.0)
        risk = self.params.get("risk", {})
        risk_budget = risk.get("starting_capital_usd", 0) * risk.get("max_risk_per_trade_pct", 0)

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
            S0 = float(spx.iloc[i]) * scale
            S_T = float(spx.iloc[i + dte]) * scale
            sigma = float(vix.iloc[i]) / 100.0
            r = float(risk_free_rate.iloc[i])

            # Construct the condor through the SAME function the live runner
            # uses. Previously this file re-implemented strike selection and
            # pricing, which let the backtest silently drift into describing
            # a different strategy than the one that would actually trade --
            # different instrument, different wing width, different risk per
            # trade. Sharing one code path makes that divergence impossible.
            ticket = build_ticket(
                spot=S0,
                implied_vol=sigma,
                risk_free_rate=r,
                short_delta=short_delta,
                long_delta=long_delta,
                dte_days=dte,
                contracts=1,
                multiplier=multiplier,
                wing_width_points=wing_width,
                strike_increment=strike_increment,
                put_iv_adjustment=put_iv_adj,
                call_iv_adjustment=call_iv_adj,
            )
            # Apply the same per-trade risk cap the live runner applies. A
            # trade whose single-contract max loss exceeds the budget is
            # DECLINED live, so counting it here would credit the backtest
            # with trades that could never be placed. Sized off the fixed cap
            # rather than Kelly to avoid circularity (Kelly needs these very
            # statistics as its input); at current edge estimates half-Kelly
            # is ~0.21 and the 2% cap binds first anyway.
            # Size against the worst case at the NET credit actually
            # collected, not the modeled mid -- a smaller credit means a
            # larger max loss, so checking the cap against the mid breaches
            # it by the size of the slippage haircut on every trade.
            worst_case = ticket.max_loss_at_credit(ticket.modeled_credit_usd * (1 - slippage_pct))
            contracts = int(risk_budget // worst_case) if risk_budget else 1
            if contracts < 1:
                i += 1
                continue

            short_put_K = ticket.short_put_strike
            long_put_K = ticket.long_put_strike
            short_call_K = ticket.short_call_strike
            long_call_K = ticket.long_call_strike

            gross_credit_usd = ticket.modeled_credit_usd * contracts
            net_credit_usd = gross_credit_usd * (1 - slippage_pct)

            put_side_loss = max(0.0, short_put_K - S_T) - max(0.0, long_put_K - S_T)
            call_side_loss = max(0.0, S_T - short_call_K) - max(0.0, S_T - long_call_K)
            loss_usd = (put_side_loss + call_side_loss) * multiplier * contracts

            costs_usd = cost_per_contract * 4 * contracts  # 4 legs per contract
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
