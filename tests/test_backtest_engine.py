"""
Tests for src/backtest/engine.py (Phase 3 proxy backtest).

Covers: no-lookahead on entry decisions, correct P&L construction against
src/backtest/pricing.py directly, no-overlapping-positions in the roll
loop, and the summary_stats formulas (Sharpe/Sortino/drawdown).
"""

import numpy as np
import pandas as pd
import pytest

from src.backtest.engine import BacktestEngine, Trade
from src.backtest.pricing import bs_price, strike_from_delta

PARAMS = {
    "signal": {"iv_rank_lookback_days": 5},
    "threshold": -1,  # effectively always-on once iv_rank is defined
    "structure": {"short_delta": 0.20, "long_delta": 0.05},
    "pricing_proxy": {"dte_trading_days": 3, "contract_multiplier": 100},
    "backtest": {"cost_per_contract_usd": 0.65, "slippage_pct_of_credit": 0.10, "regime_split_year": 2010},
    "risk": {"starting_capital_usd": 1000},
}


def _market_data(n_days: int):
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    spx = pd.Series(5000.0, index=dates)  # flat price -> deterministic zero-loss expirations
    vix = pd.Series(15.0 + 0.01 * np.arange(n_days), index=dates)  # slight drift avoids flat rolling windows
    rate = pd.Series(0.03, index=dates)
    return spx, vix, rate


def test_no_overlapping_positions():
    spx, vix, rate = _market_data(60)
    trades = BacktestEngine(PARAMS).run(spx, vix, rate)

    assert len(trades) >= 2
    for a, b in zip(trades, trades[1:]):
        entry_pos = spx.index.get_loc(b.entry_date)
        expiration_pos = spx.index.get_loc(a.expiration_date)
        assert entry_pos > expiration_pos  # next trade only opens after the previous one settles


def test_pnl_matches_pricing_module_directly():
    spx, vix, rate = _market_data(60)
    trades = BacktestEngine(PARAMS).run(spx, vix, rate)
    trade = trades[0]

    i = spx.index.get_loc(trade.entry_date)
    S0, sigma, r = float(spx.iloc[i]), float(vix.iloc[i]) / 100.0, float(rate.iloc[i])
    T = PARAMS["pricing_proxy"]["dte_trading_days"] / 252

    short_put_K = strike_from_delta(S0, T, r, sigma, -0.20, "put")
    long_put_K = strike_from_delta(S0, T, r, sigma, -0.05, "put")
    short_call_K = strike_from_delta(S0, T, r, sigma, 0.20, "call")
    long_call_K = strike_from_delta(S0, T, r, sigma, 0.05, "call")

    gross_credit = (
        bs_price(S0, short_put_K, T, r, sigma, "put") - bs_price(S0, long_put_K, T, r, sigma, "put")
        + bs_price(S0, short_call_K, T, r, sigma, "call") - bs_price(S0, long_call_K, T, r, sigma, "call")
    ) * 100

    assert np.isclose(trade.short_put_strike, short_put_K)
    assert np.isclose(trade.long_put_strike, long_put_K)
    assert np.isclose(trade.short_call_strike, short_call_K)
    assert np.isclose(trade.long_call_strike, long_call_K)
    assert np.isclose(trade.gross_credit_usd, gross_credit)

    net_credit = gross_credit * 0.90  # 10% slippage haircut
    assert np.isclose(trade.net_credit_usd, net_credit)

    # SPX flat at 5000, strikes all outside that -> both wings expire worthless -> zero loss
    expected_pnl = net_credit - 0.0 - 4 * 0.65
    assert np.isclose(trade.pnl, expected_pnl)
    assert trade.exit_reason == "expiration"
    assert trade.exit_date == trade.expiration_date


def test_entry_decisions_have_no_lookahead():
    spx_full, vix_full, rate_full = _market_data(60)
    trades_full = BacktestEngine(PARAMS).run(spx_full, vix_full, rate_full)

    # truncate to a window that still fully contains the first trade's settlement
    cutoff = spx_full.index.get_loc(trades_full[0].expiration_date) + 1
    spx_short, vix_short, rate_short = spx_full.iloc[:cutoff], vix_full.iloc[:cutoff], rate_full.iloc[:cutoff]
    trades_short = BacktestEngine(PARAMS).run(spx_short, vix_short, rate_short)

    assert len(trades_short) == 1
    assert trades_short[0] == trades_full[0]


def _trade(entry_date: str, pnl: float) -> Trade:
    ts = pd.Timestamp(entry_date)
    return Trade(
        entry_date=ts, expiration_date=ts, entry_spx=5000.0, expiration_spx=5000.0,
        iv_rank_at_entry=75.0, short_put_strike=4900, long_put_strike=4800,
        short_call_strike=5100, long_call_strike=5200,
        gross_credit_usd=abs(pnl) + 100, net_credit_usd=abs(pnl) + 100, costs_usd=2.6,
        pnl=pnl, exit_date=ts,
    )


def test_summary_stats_hand_traced():
    trades = [
        _trade("2015-01-01", 100), _trade("2015-07-01", -50), _trade("2016-01-01", 200),
        _trade("2016-07-01", 150), _trade("2017-01-01", -300),
    ]
    stats = BacktestEngine._regime_stats(trades, starting_capital=1000)

    assert stats["n_trades"] == 5
    assert stats["win_rate"] == 0.6
    assert stats["total_pnl_usd"] == 100.0
    assert np.isclose(stats["sharpe"], 0.15659850624709365)
    assert np.isclose(stats["sortino"], 0.2324157511376166)
    assert stats["max_drawdown_usd"] == -300.0


def test_sharpe_sortino_invariant_to_starting_capital_placeholder():
    trades = [_trade("2015-01-01", 100), _trade("2015-07-01", -50), _trade("2016-01-01", 200)]
    a = BacktestEngine._regime_stats(trades, starting_capital=1000)
    b = BacktestEngine._regime_stats(trades, starting_capital=500)

    assert np.isclose(a["sharpe"], b["sharpe"])
    assert np.isclose(a["sortino"], b["sortino"])


def test_first_trade_loss_sets_drawdown_not_masked():
    trades = [_trade("2020-01-01", -1000), _trade("2020-06-01", 50), _trade("2020-12-01", 30)]
    stats = BacktestEngine._regime_stats(trades, starting_capital=1000)

    assert stats["max_drawdown_usd"] == -1000.0


def test_edge_cases_no_crash():
    assert BacktestEngine._regime_stats([], 1000) == {"n_trades": 0}

    one = BacktestEngine._regime_stats([_trade("2020-01-01", 400)], 1000)
    assert np.isnan(one["sharpe"])
    assert np.isnan(one["sortino"])
    assert one["max_drawdown_usd"] == 0.0

    all_positive = [_trade(f"2020-0{i}-01", 100.0) for i in range(1, 6)]
    stats = BacktestEngine._regime_stats(all_positive, 1000)
    assert np.isnan(stats["sortino"])  # no downside observed -- undefined, not 0 or inf
