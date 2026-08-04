"""
Tests for src/execution/alpaca_client.py.

No network and no credentials: everything here exercises the pure
order-construction path, which is where an order can come out *wrong but
valid* and get silently accepted by the broker. The single most important
case is leg sides -- a flipped side turns a short condor (collects credit,
capped risk) into a long one (pays a debit, inverted payoff), and the API
would happily accept it.
"""

from datetime import date, timedelta

import pytest

from src.execution.alpaca_client import (
    EUROPEAN_CASH_SETTLED,
    condor_legs,
    get_client,
    occ_symbol,
)
from src.execution.ticket import build_ticket

EXPIRY = date.today() + timedelta(days=30)


def _ticket(**kw):
    kwargs = dict(spot=760.0, implied_vol=0.159, risk_free_rate=0.04, short_delta=0.20,
                  long_delta=0.05, dte_days=21, wing_width_points=26.0, strike_increment=1.0)
    kwargs.update(kw)
    return build_ticket(**kwargs)


# ---- OCC symbol encoding ----

def test_occ_symbol_known_examples():
    assert occ_symbol("XSP", date(2026, 8, 21), "put", 734.0) == "XSP260821P00734000"
    assert occ_symbol("XSP", date(2026, 8, 21), "call", 794.0) == "XSP260821C00794000"
    assert occ_symbol("SPX", date(2026, 12, 18), "call", 7600.0) == "SPX261218C07600000"


def test_occ_symbol_encodes_fractional_strike():
    assert occ_symbol("XSP", date(2026, 8, 21), "put", 734.5) == "XSP260821P00734500"


def test_occ_symbol_uppercases_root():
    assert occ_symbol("xsp", date(2026, 8, 21), "put", 734.0).startswith("XSP")


@pytest.mark.parametrize("bad", [
    {"option_type": "putt"},
    {"strike": 0},
    {"strike": -100},
    {"strike": 734.0001},  # finer than a cent -- not a listed contract
])
def test_occ_symbol_rejects_invalid(bad):
    kwargs = dict(root="XSP", expiration=date(2026, 8, 21), option_type="put", strike=734.0)
    kwargs.update(bad)
    with pytest.raises(ValueError):
        occ_symbol(**kwargs)


# ---- leg construction ----

def test_condor_legs_encode_a_SHORT_condor():
    """Buy the wings, sell the inner strikes. Reversed, this becomes a
    long condor that pays a debit -- valid to the API, wrong strategy."""
    legs = condor_legs(_ticket(), "XSP", EXPIRY)
    sides = [leg["side"] for leg in legs]

    assert sides == ["buy", "sell", "sell", "buy"]


def test_condor_legs_are_ordered_low_strike_to_high():
    legs = condor_legs(_ticket(), "XSP", EXPIRY)
    strikes = [int(leg["symbol"][-8:]) for leg in legs]

    assert strikes == sorted(strikes)


def test_condor_legs_put_legs_precede_call_legs():
    legs = condor_legs(_ticket(), "XSP", EXPIRY)
    kinds = [leg["symbol"][-9] for leg in legs]

    assert kinds == ["P", "P", "C", "C"]


def test_condor_legs_carry_contract_count():
    legs = condor_legs(_ticket(contracts=3), "XSP", EXPIRY)

    assert all(leg["ratio_qty"] == 3 for leg in legs)


def test_condor_legs_reject_american_style_underlying():
    """SPY would reintroduce the early-assignment risk spec s2 chose an
    index product to avoid."""
    with pytest.raises(ValueError, match="early-assignment"):
        condor_legs(_ticket(), "SPY", EXPIRY)


def test_condor_legs_reject_past_expiration():
    with pytest.raises(ValueError, match="future"):
        condor_legs(_ticket(), "XSP", date.today() - timedelta(days=1))


def test_xsp_and_spx_are_allowed_underlyings():
    assert {"XSP", "SPX"} <= EUROPEAN_CASH_SETTLED


# ---- live-trading gate ----

def test_get_client_blocks_live():
    """Live is out of scope (spec s12) and gated in code, not just docs --
    same pattern as the half-Kelly ceiling in src/risk/sizing.py."""
    with pytest.raises(ValueError, match="out of scope"):
        get_client(paper=False)


def test_get_client_requires_credentials(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="not found in environment"):
        get_client(paper=True)
