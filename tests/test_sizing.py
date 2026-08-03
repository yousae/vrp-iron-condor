"""
Tests for src/risk/sizing.py.

kelly_fraction is cross-checked against the textbook closed-form
f* = p - q/b (b = win/loss payoff ratio), not just its own code path --
see the quant-verify pass in the commit history for the full derivation.
"""

import pytest

from src.risk.sizing import kelly_fraction, portfolio_heat, position_size


def test_kelly_fraction_matches_textbook_formula():
    win_rate, avg_win, avg_loss = 0.75, 1200.0, 2500.0
    b = avg_win / avg_loss
    expected = win_rate - (1 - win_rate) / b

    assert kelly_fraction(win_rate, avg_win, avg_loss) == pytest.approx(expected)


def test_kelly_fraction_certain_win_bets_everything():
    assert kelly_fraction(1.0, 100.0, 50.0) == 1.0


def test_kelly_fraction_certain_loss_clamps_to_zero():
    assert kelly_fraction(0.0, 100.0, 50.0) == 0.0


def test_kelly_fraction_below_breakeven_clamps_to_zero_not_negative():
    avg_win, avg_loss = 1200.0, 2500.0
    breakeven = avg_loss / (avg_win + avg_loss)

    assert kelly_fraction(breakeven, avg_win, avg_loss) == pytest.approx(0.0, abs=1e-9)
    assert kelly_fraction(breakeven - 0.05, avg_win, avg_loss) == 0.0


@pytest.mark.parametrize("win_rate,avg_win,avg_loss", [
    (-0.1, 100, 50),
    (1.1, 100, 50),
    (0.5, 0, 50),
    (0.5, 100, 0),
    (0.5, -10, 50),
])
def test_kelly_fraction_rejects_invalid_inputs(win_rate, avg_win, avg_loss):
    with pytest.raises(ValueError):
        kelly_fraction(win_rate, avg_win, avg_loss)


def test_position_size_applies_multiplier_and_cap():
    kf = kelly_fraction(0.75, 1200.0, 2500.0)  # ~0.229, so half-Kelly (~0.115) exceeds the 2% cap
    size = position_size(account_capital=1000, kelly_frac=kf, kelly_multiplier=0.5, max_risk_per_trade_pct=0.02)

    assert size == pytest.approx(20.0)  # cap binds: 0.02 * 1000


def test_position_size_rejects_full_kelly_multiplier():
    with pytest.raises(ValueError):
        position_size(account_capital=1000, kelly_frac=0.2, kelly_multiplier=0.75, max_risk_per_trade_pct=0.02)


def test_position_size_accepts_half_kelly_multiplier():
    position_size(account_capital=1000, kelly_frac=0.2, kelly_multiplier=0.5, max_risk_per_trade_pct=0.02)


def test_position_size_rejects_nonpositive_capital():
    with pytest.raises(ValueError):
        position_size(account_capital=0, kelly_frac=0.2, kelly_multiplier=0.5, max_risk_per_trade_pct=0.02)


def test_portfolio_heat_is_sum_of_risks_over_capital():
    assert portfolio_heat([120.0, 85.0], account_capital=1000.0) == pytest.approx(0.205)


def test_portfolio_heat_rejects_nonpositive_capital():
    with pytest.raises(ValueError):
        portfolio_heat([10.0], account_capital=0)
