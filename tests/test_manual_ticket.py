"""
Tests for src/execution/manual_ticket.py.

thinkorswim paperMoney has no API, so there is no order-submission path
to test. What matters instead is that the ticket math is right (a wrong
strike typed by hand is a real loss) and that fill reconciliation
correctly flags disqualifying slippage -- that flag is Phase 5's
pre-registered kill condition.
"""

import pytest

from src.execution.manual_ticket import build_ticket, format_ticket, reconcile_fill

SPOT, IV, RATE, DTE = 760.0, 0.159, 0.04, 21


def _ticket(**overrides):
    kwargs = dict(spot=SPOT, implied_vol=IV, risk_free_rate=RATE,
                  short_delta=0.20, long_delta=0.05, dte_days=DTE)
    kwargs.update(overrides)
    return build_ticket(**kwargs)


def test_strikes_are_correctly_ordered():
    t = _ticket()
    assert t.long_put_strike < t.short_put_strike < SPOT < t.short_call_strike < t.long_call_strike


def test_wing_width_override_produces_exact_width():
    t = _ticket(wing_width_points=3.0)

    assert t.short_put_strike - t.long_put_strike == pytest.approx(3.0)
    assert t.long_call_strike - t.short_call_strike == pytest.approx(3.0)


def test_max_loss_uses_wider_wing_not_sum_of_both():
    """Only one side can finish ITM, so max loss is capped by the wider
    spread -- summing both sides would roughly double the true risk and
    would silently make every position-sizing decision too conservative."""
    t = _ticket()  # delta-based wings are asymmetric (put side is wider)
    put_wing = (t.short_put_strike - t.long_put_strike) * 100
    call_wing = (t.long_call_strike - t.short_call_strike) * 100

    assert put_wing != pytest.approx(call_wing)  # guard: asymmetry is what makes this test meaningful
    assert t.max_loss_usd == pytest.approx(max(put_wing, call_wing) - t.modeled_credit_usd)
    assert t.max_loss_usd < put_wing + call_wing - t.modeled_credit_usd


def test_credit_and_max_loss_are_positive():
    t = _ticket(wing_width_points=3.0)

    assert t.modeled_credit_usd > 0
    assert t.max_loss_usd > 0


def test_contracts_scale_credit_and_loss_linearly():
    one = _ticket(wing_width_points=3.0, contracts=1)
    three = _ticket(wing_width_points=3.0, contracts=3)

    assert three.modeled_credit_usd == pytest.approx(one.modeled_credit_usd * 3)
    assert three.max_loss_usd == pytest.approx(one.max_loss_usd * 3)


@pytest.mark.parametrize("bad", [
    {"implied_vol": 15.9},   # percent instead of decimal
    {"implied_vol": 0.0},
    {"contracts": 0},
])
def test_rejects_invalid_inputs(bad):
    with pytest.raises(ValueError):
        _ticket(**bad)


def test_reconcile_fill_at_mid_is_zero_slippage():
    t = _ticket(wing_width_points=3.0)
    rec = reconcile_fill(t, t.modeled_credit_usd, 0.10, 0.20)

    assert rec.slippage_pct_of_credit == pytest.approx(0.0)
    assert rec.within_model_assumption
    assert not rec.is_disqualifying


def test_reconcile_fill_within_model_assumption():
    t = _ticket(wing_width_points=3.0)
    rec = reconcile_fill(t, t.modeled_credit_usd * 0.92, 0.10, 0.20)

    assert rec.slippage_pct_of_credit == pytest.approx(0.08)
    assert rec.within_model_assumption
    assert not rec.is_disqualifying


def test_reconcile_fill_worse_than_model_but_not_disqualifying():
    t = _ticket(wing_width_points=3.0)
    rec = reconcile_fill(t, t.modeled_credit_usd * 0.85, 0.10, 0.20)

    assert not rec.within_model_assumption
    assert not rec.is_disqualifying


def test_reconcile_fill_flags_disqualifying_slippage():
    t = _ticket(wing_width_points=3.0)
    rec = reconcile_fill(t, t.modeled_credit_usd * 0.75, 0.10, 0.20)

    assert rec.slippage_pct_of_credit == pytest.approx(0.25)
    assert rec.is_disqualifying
    assert "DISQUALIFYING" in rec.summary()


def test_better_than_modeled_fill_reports_negative_slippage_not_zero():
    """A persistently better-than-modeled fill is also evidence the cost
    model is miscalibrated, so it must be visible rather than clamped."""
    t = _ticket(wing_width_points=3.0)
    rec = reconcile_fill(t, t.modeled_credit_usd * 1.05, 0.10, 0.20)

    assert rec.slippage_pct_of_credit < 0
    assert rec.within_model_assumption
    assert not rec.is_disqualifying


def test_format_ticket_contains_all_four_legs_and_symbol():
    t = _ticket(wing_width_points=3.0)
    out = format_ticket(t, symbol="XSP")

    assert out.count("XSP") >= 5  # header + 4 legs
    assert out.count("BUY") == 2
    assert out.count("SELL") == 2
    for strike in (t.long_put_strike, t.short_put_strike, t.short_call_strike, t.long_call_strike):
        assert f"{strike:,.2f}" in out
