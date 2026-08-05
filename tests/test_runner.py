"""
Tests for the runner's decision step.

`decide()` is deliberately pure -- no network, no broker -- so the whole
trade/no-trade decision is testable offline. These cover the paths that
matter, especially the ones that REFUSE to trade: a silent failure to
trade is far likelier to go unnoticed than a spurious trade.
"""

from datetime import date

import pytest

from src.execution import trade_log
from src.execution.runner import decide, load_config

CONFIG = load_config()
MARKET = {
    "as_of": date(2026, 8, 3),
    "spot_spx": 7600.0,
    "vix": 15.9,
    "risk_free_rate": 0.04,
    "iv_rank": 62.0,
}
EDGE = {"n_trades": 48, "win_rate": 0.771, "avg_win_usd": 3365.0, "avg_loss_usd": 5267.0}


@pytest.fixture(autouse=True)
def _no_open_positions(monkeypatch):
    """decide() consults the real trade log; isolate tests from it."""
    monkeypatch.setattr(trade_log, "open_positions", lambda *a, **k: [])


# ---- decision ----

def test_trades_when_signal_fires_and_budget_allows():
    d = decide(CONFIG, MARKET, EDGE)

    assert d["trade"] is True
    assert d["contracts"] >= 1
    assert d["ticket"].max_loss_usd <= d["risk_budget_usd"]
    assert d["expiration"] > MARKET["as_of"]


def test_no_trade_below_threshold():
    d = decide(CONFIG, {**MARKET, "iv_rank": 12.0}, EDGE)

    assert d["trade"] is False
    assert "threshold" in d["reason"]


def test_no_trade_at_exactly_the_threshold():
    """entry_signal uses strict >, so the threshold itself must not fire."""
    threshold = CONFIG["paper_trading"]["paper_stream_threshold"]
    d = decide(CONFIG, {**MARKET, "iv_rank": float(threshold)}, EDGE)

    assert d["trade"] is False


def test_no_trade_when_a_position_is_already_open(monkeypatch):
    """v1 holds one position at a time -- the backtest assumes it, so live
    must too, or the backtest stops describing what ran."""
    monkeypatch.setattr(trade_log, "open_positions", lambda *a, **k: [{"order_id": "x"}])
    d = decide(CONFIG, MARKET, EDGE)

    assert d["trade"] is False
    assert "already open" in d["reason"]


def test_no_trade_when_budget_is_smaller_than_one_contract():
    """The risk cap binding is correct behavior, not a bug to round past."""
    tiny = {**CONFIG, "risk": {**CONFIG["risk"], "starting_capital_usd": 5000}}
    d = decide(tiny, MARKET, EDGE)

    assert d["trade"] is False
    assert "max loss" in d["reason"]


def test_max_loss_respects_the_per_trade_cap():
    d = decide(CONFIG, MARKET, EDGE)
    cap = CONFIG["risk"]["starting_capital_usd"] * CONFIG["risk"]["max_risk_per_trade_pct"]

    assert d["ticket"].max_loss_usd <= cap


def test_wing_width_has_headroom_across_market_regimes():
    """26pt wings sat within $6 of the cap and would flip in and out of
    tradeable as spot moved. Guard against that regressing."""
    cap = CONFIG["risk"]["starting_capital_usd"] * CONFIG["risk"]["max_risk_per_trade_pct"]

    for spot in (7000.0, 7600.0, 8200.0):
        for vix in (12.0, 16.0, 25.0, 40.0):
            d = decide(CONFIG, {**MARKET, "spot_spx": spot, "vix": vix}, EDGE)
            assert d["trade"] is True, f"declined to trade at spot={spot} vix={vix}"
            assert d["ticket"].max_loss_usd <= cap * 0.95, f"under 5% headroom at spot={spot} vix={vix}"


def test_decide_uses_real_strikes_when_given_them():
    """Snapping to the real grid changes wing width, hence max loss, hence
    how many contracts fit the cap. Sizing on an assumed grid and trading a
    real one sizes against a trade that does not exist."""
    coarse = [float(k) for k in range(600, 900, 5)]   # $5 grid, unlike the assumed $1
    d = decide(CONFIG, MARKET, EDGE, available_strikes=coarse)

    assert d["trade"] is True
    for strike in (d["ticket"].long_put_strike, d["ticket"].short_put_strike,
                   d["ticket"].short_call_strike, d["ticket"].long_call_strike):
        assert strike in coarse, f"{strike} is not a listed strike"


def test_decide_still_respects_the_cap_on_a_real_grid():
    coarse = [float(k) for k in range(600, 900, 5)]
    d = decide(CONFIG, MARKET, EDGE, available_strikes=coarse)
    cap = CONFIG["risk"]["starting_capital_usd"] * CONFIG["risk"]["max_risk_per_trade_pct"]

    assert d["ticket"].max_loss_usd <= cap
