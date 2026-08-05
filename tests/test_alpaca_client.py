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
    """Clearing the env is not enough once a real .env exists on disk --
    get_client() loads it. Stub the loader too, or this passes/fails
    depending on whether the developer has set up credentials."""
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="not found in environment"):
        get_client(paper=True)


# ---- paper-endpoint hard gate ----

def test_assert_paper_allows_a_paper_client():
    from alpaca.trading.client import TradingClient

    from src.execution.alpaca_client import assert_paper_client

    assert_paper_client(TradingClient("k", "s", paper=True))  # must not raise


def test_assert_paper_blocks_a_live_client():
    from alpaca.trading.client import TradingClient

    from src.execution.alpaca_client import assert_paper_client

    with pytest.raises(RuntimeError, match="REFUSING"):
        assert_paper_client(TradingClient("k", "s", paper=False))


def test_assert_paper_blocks_url_override_to_live():
    """A future edit could construct a client some other way; the gate
    checks the resolved URL, not the flag that was passed."""
    from alpaca.trading.client import TradingClient

    from src.execution.alpaca_client import assert_paper_client

    sneaky = TradingClient("k", "s", paper=True, url_override="https://api.alpaca.markets")
    with pytest.raises(RuntimeError, match="REFUSING"):
        assert_paper_client(sneaky)


def test_submit_order_refuses_a_live_client_before_any_network_call():
    """The gate must fire BEFORE submit_order touches the client, so a
    live client can never reach the wire even once."""
    from src.execution.alpaca_client import submit_order

    class ExplodingClient:
        _base_url = "https://api.alpaca.markets"
        _sandbox = False

        def submit_order(self, *a, **k):
            raise AssertionError("network call reached on a live client")

    with pytest.raises(RuntimeError, match="REFUSING"):
        submit_order(ExplodingClient(), object())


# ---- limit-price sign convention ----

def test_limit_credit_is_submitted_as_a_negative_price():
    """Alpaca signs a credit NEGATIVE. Submitting a positive number reads
    as a debit ceiling, which any credit satisfies -- the order then fills
    instantly at whatever the book offers instead of holding for the price.
    That is not an error, just a silently worse fill, so it needs a test."""
    from src.execution.alpaca_client import build_condor_order

    req = build_condor_order(_ticket(), "XSP", EXPIRY, limit_credit=5.46)

    assert float(req.limit_price) == -5.46


def test_build_condor_order_rejects_a_negative_limit_credit():
    """Callers pass the credit they want as a positive number; negating is
    this function's job. A caller pre-negating would double-negate."""
    from src.execution.alpaca_client import build_condor_order

    with pytest.raises(ValueError, match="positive credit"):
        build_condor_order(_ticket(), "XSP", EXPIRY, limit_credit=-5.46)


# ---- price walk ----

def test_price_schedule_walks_mid_down_to_floor():
    from src.execution.alpaca_client import price_schedule

    s = price_schedule(5.42, steps=5, floor_pct_of_mid=0.80)

    assert s[0] == 5.42                      # starts at mid
    assert s[-1] == pytest.approx(4.34, abs=0.01)  # ends at the floor
    assert s == sorted(s, reverse=True)      # monotonically decreasing


def test_price_schedule_never_goes_below_the_floor():
    """The floor encodes the pre-registered slippage limit. Going under it
    would accept a fill already declared disqualifying."""
    from src.execution.alpaca_client import price_schedule

    for steps in (1, 2, 5, 20):
        s = price_schedule(10.0, steps=steps, floor_pct_of_mid=0.80)
        assert min(s) >= 8.0 - 1e-9


def test_price_schedule_single_step_is_the_floor():
    from src.execution.alpaca_client import price_schedule

    assert price_schedule(10.0, steps=1, floor_pct_of_mid=0.80) == [8.0]


@pytest.mark.parametrize("kwargs", [
    {"steps": 0},
    {"floor_pct_of_mid": 0},
    {"floor_pct_of_mid": 1.5},
    {"mid_credit": 0},
])
def test_price_schedule_rejects_invalid(kwargs):
    from src.execution.alpaca_client import price_schedule

    args = {"mid_credit": 5.0, "steps": 5, "floor_pct_of_mid": 0.8}
    args.update(kwargs)
    with pytest.raises(ValueError):
        price_schedule(**args)


# ---- closing order ----

def test_close_all_legs_closes_shorts_before_longs():
    """Closing a long wing first leaves a naked short, which a Level 3
    account cannot hold -- Alpaca rejects it and the position is left
    half-closed and riskier than before. Shorts must go first."""
    from src.execution.alpaca_client import close_all_legs

    class Pos:
        def __init__(self, symbol, side):
            self.symbol, self.side, self.qty = symbol, side, "1"

    class FakeClient:
        _base_url = "https://paper-api.alpaca.markets"
        _sandbox = True

        def __init__(self):
            self.closed = []

        def get_all_positions(self):
            return [Pos("LONG_CALL", "PositionSide.LONG"),
                    Pos("SHORT_PUT", "PositionSide.SHORT"),
                    Pos("LONG_PUT", "PositionSide.LONG"),
                    Pos("SHORT_CALL", "PositionSide.SHORT")]

        def close_position(self, symbol):
            self.closed.append(symbol)

    client = FakeClient()
    close_all_legs(client, pause_seconds=0)

    assert client.closed[:2] == ["SHORT_PUT", "SHORT_CALL"]
    assert set(client.closed[2:]) == {"LONG_CALL", "LONG_PUT"}
