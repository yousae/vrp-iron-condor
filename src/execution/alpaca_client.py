"""
Alpaca paper-trading execution for the condor.

Alpaca supports XSP/SPX index options with up to 4-leg multi-leg orders,
European-style with no early assignment -- which preserves the reason
project_spec.md s2 chose an index product over SPY. Index options are
PAPER ONLY on Alpaca at present, which suits this project: live trading
is explicitly out of scope (spec s12).

Design note: order construction is separated from submission on purpose.
`build_condor_order()` is pure -- no network, fully testable -- and does
the fiddly part (OCC symbol encoding, leg sides, ratios). `submit_order()`
is a thin wrapper around the one network call. That split means the logic
that can silently produce a *wrong but valid* order is under test, rather
than hidden behind an API boundary that can't be exercised without
credentials.

!! UNVERIFIED AGAINST A LIVE API !!
The alpaca-py request shapes and the OCC symbol format below are written
from the documented spec but have NOT been round-tripped against a real
Alpaca response in this project yet. Before relying on them, submit one
order in paper and confirm: (a) the symbols resolve to real contracts,
(b) leg sides/ratios produce a short condor rather than a long one, and
(c) the fill credit is positive. Treat the first paper order as a test of
this module, not of the strategy.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.execution.ticket import Ticket

# Underlyings whose options are cash-settled and European-style. Trading
# anything outside this set reintroduces the early-assignment risk that
# spec s2 specifically chose an index product to avoid.
EUROPEAN_CASH_SETTLED = frozenset({"SPX", "SPXW", "XSP", "DJX", "VIX", "VIXW"})


def occ_symbol(root: str, expiration: date, option_type: str, strike: float) -> str:
    """Build an OCC-format option symbol, e.g. XSP260821P00734000.

    Format is root + YYMMDD + C/P + strike*1000 zero-padded to 8 digits.

    Rejects any strike finer than a cent. That guard exists to catch an
    unrounded delta-solved strike (e.g. 734.4237) being passed straight
    through -- it would otherwise silently encode a contract that does
    not exist, or worse, round to one that does but isn't the intended
    one. Strikes must already be snapped to the listed grid by
    build_ticket()'s strike_increment.
    """
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")
    if strike <= 0:
        raise ValueError(f"strike must be positive, got {strike}")

    # Check cent-alignment BEFORE rounding -- rounding first would destroy
    # the very discrepancy this is meant to detect.
    if abs(strike * 100 - round(strike * 100)) > 1e-6:
        raise ValueError(
            f"strike {strike} is finer than $0.01 and cannot be a listed contract "
            "-- pass strikes already snapped to the listed grid"
        )

    strike_thousandths = round(strike * 1000)

    return (
        f"{root.upper()}"
        f"{expiration.strftime('%y%m%d')}"
        f"{'C' if option_type == 'call' else 'P'}"
        f"{strike_thousandths:08d}"
    )


def condor_legs(ticket: Ticket, underlying: str, expiration: date) -> list[dict]:
    """The four legs of a short iron condor, as plain dicts.

    Returned in conventional low-strike-to-high order. Sides encode a
    SHORT condor (net credit): buy the wings, sell the inner strikes.
    Getting a side backwards would build a long condor that PAYS a debit
    and has inverted risk, so this is the single most important thing
    the tests cover.
    """
    if underlying.upper() not in EUROPEAN_CASH_SETTLED:
        raise ValueError(
            f"{underlying!r} is not a cash-settled European underlying "
            f"{sorted(EUROPEAN_CASH_SETTLED)}. American-style options reintroduce "
            "early-assignment risk -- see project_spec.md section 2."
        )
    if expiration <= date.today():
        raise ValueError(f"expiration {expiration} must be in the future")

    return [
        {"symbol": occ_symbol(underlying, expiration, "put", ticket.long_put_strike),
         "side": "buy", "ratio_qty": ticket.contracts},
        {"symbol": occ_symbol(underlying, expiration, "put", ticket.short_put_strike),
         "side": "sell", "ratio_qty": ticket.contracts},
        {"symbol": occ_symbol(underlying, expiration, "call", ticket.short_call_strike),
         "side": "sell", "ratio_qty": ticket.contracts},
        {"symbol": occ_symbol(underlying, expiration, "call", ticket.long_call_strike),
         "side": "buy", "ratio_qty": ticket.contracts},
    ]


def get_client(paper: bool = True):
    """Return an authenticated Alpaca trading client.

    Reads ALPACA_API_KEY / ALPACA_SECRET_KEY from the environment; see
    .env.example. Credentials are never accepted as arguments so they
    can't end up in a traceback, a log line, or source control.

    paper=False RAISES. Live trading is out of scope for this project
    (spec s12), and CLAUDE.md carries a standing rule that a live
    environment requires explicit per-session confirmation. Enforcing
    that here means no caller can reach live by passing a flag -- same
    pattern as the half-Kelly ceiling in src/risk/sizing.py.
    """
    if not paper:
        raise ValueError(
            "Live trading is out of scope for this project and is blocked here by design. "
            "See project_spec.md section 12 and the standing rules in CLAUDE.md."
        )

    import os

    # Load .env if present. Without this, keys placed in .env are silently
    # ignored and the error below is misleading ("not found in environment"
    # when they are plainly sitting in the file the docs told you to fill).
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    except ImportError:
        pass

    api_key = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise RuntimeError(
            "ALPACA_API_KEY / ALPACA_SECRET_KEY not found in environment. "
            "Copy .env.example to .env and fill them in."
        )

    # Catch the paste mistakes that otherwise surface as an opaque 401.
    # Error messages never include the value itself, only its shape.
    for name, value in (("ALPACA_API_KEY", api_key), ("ALPACA_SECRET_KEY", secret_key)):
        if value != value.strip():
            raise RuntimeError(f"{name} has leading/trailing whitespace -- remove it from .env")
        if value[:1] in {'"', "'"} or value[-1:] in {'"', "'"}:
            raise RuntimeError(f"{name} is wrapped in quotes -- .env values take no quotes")
        if " " in value:
            raise RuntimeError(f"{name} contains a space -- looks like extra text was pasted")
        if "=" in value:
            raise RuntimeError(
                f"{name} contains '=' -- looks like the whole line was pasted, "
                "not just the value after the ="
            )

    from alpaca.trading.client import TradingClient

    return TradingClient(api_key, secret_key, paper=True)


REQUIRED_OPTIONS_LEVEL = 3  # multi-leg spreads need Level 3 on Alpaca


def preflight(client) -> dict:
    """Read-only account check. Places nothing.

    Run this before the first order. It answers the questions that would
    otherwise surface as a confusing rejection: is the account reachable,
    is it actually the paper account, is options approval high enough for
    a 4-leg spread, and is anything blocked.
    """
    assert_paper_client(client)
    acct = client.get_account()

    approved = getattr(acct, "options_approved_level", None)
    trading = getattr(acct, "options_trading_level", None)
    effective = min([lvl for lvl in (approved, trading) if lvl is not None], default=None)

    return {
        "account_number": getattr(acct, "account_number", None),
        "status": str(getattr(acct, "status", None)),
        "is_paper": True,  # assert_paper_client would have raised otherwise
        "options_approved_level": approved,
        "options_trading_level": trading,
        "options_level_sufficient": effective is not None and effective >= REQUIRED_OPTIONS_LEVEL,
        "equity": getattr(acct, "equity", None),
        "options_buying_power": getattr(acct, "options_buying_power", None),
        "account_blocked": getattr(acct, "account_blocked", None),
        "trading_blocked": getattr(acct, "trading_blocked", None),
    }


def describe_preflight(info: dict) -> str:
    """Human-readable preflight summary."""
    ok = "OK " if info["options_level_sufficient"] else "!! "
    lines = [
        f"  account:            {info['account_number']}  ({info['status']})",
        f"  endpoint:           PAPER (verified)",
        f"  equity:             {info['equity']}",
        f"  options buying pwr: {info['options_buying_power']}",
        f"{ok}options level:      approved={info['options_approved_level']} "
        f"trading={info['options_trading_level']}  (need >= {REQUIRED_OPTIONS_LEVEL} for 4-leg spreads)",
    ]
    if info["account_blocked"] or info["trading_blocked"]:
        lines.append(f"!! BLOCKED: account_blocked={info['account_blocked']} "
                     f"trading_blocked={info['trading_blocked']}")
    return "\n".join(lines)


def get_order(client, order_id):
    """Fetch a submitted order back, to see status and actual fill."""
    assert_paper_client(client)
    return client.get_order_by_id(order_id)


def build_condor_order(ticket: Ticket, underlying: str, expiration: date, limit_credit: float | None = None):
    """Build (but do NOT submit) the multi-leg order request.

    limit_credit is the minimum acceptable net credit per spread, in
    dollars-per-contract terms. Passing None sends a market order, which
    is a bad idea on a 4-leg index spread -- wide books mean a market
    order can fill far off mid, which is exactly the slippage this
    project is trying to measure rather than incur. Prefer a limit.
    """
    from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
    from alpaca.trading.requests import (
        LimitOrderRequest,
        MarketOrderRequest,
        OptionLegRequest,
    )

    legs = [
        OptionLegRequest(
            symbol=leg["symbol"],
            side=OrderSide.BUY if leg["side"] == "buy" else OrderSide.SELL,
            ratio_qty=leg["ratio_qty"],
        )
        for leg in condor_legs(ticket, underlying, expiration)
    ]

    common = dict(
        qty=1,
        order_class=OrderClass.MLEG,
        time_in_force=TimeInForce.DAY,
        legs=legs,
    )
    if limit_credit is None:
        return MarketOrderRequest(**common)
    return LimitOrderRequest(limit_price=round(limit_credit, 2), **common)


PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def assert_paper_client(client) -> None:
    """Hard gate: refuse to act on anything but the paper endpoint.

    Defence in depth. get_client() already hardcodes paper=True and
    rejects paper=False, but this sits at the actual mutating call, so a
    future edit that constructs a client some other way still cannot
    reach live. Checks the resolved base URL rather than a flag, because
    the URL is what actually determines where the order goes.
    """
    base = str(getattr(getattr(client, "_base_url", ""), "value", getattr(client, "_base_url", "")))
    if base != PAPER_BASE_URL:
        raise RuntimeError(
            f"REFUSING to submit: client points at {base!r}, not the paper endpoint "
            f"({PAPER_BASE_URL!r}). Live trading is out of scope for this project."
        )
    if not getattr(client, "_sandbox", False):
        raise RuntimeError("REFUSING to submit: client is not in sandbox/paper mode.")


def submit_order(client, order_request):
    """Submit a prepared order. The only network call in this module.

    Kept deliberately thin -- everything that can be wrong is decided in
    build_condor_order(), which is testable without credentials -- except
    the paper-endpoint assertion, which belongs here precisely because
    this is the line that has consequences.
    """
    assert_paper_client(client)
    return client.submit_order(order_request)


if __name__ == "__main__":
    from datetime import timedelta

    from src.execution.ticket import build_ticket, format_ticket

    ticket = build_ticket(
        spot=760.0, implied_vol=0.159, risk_free_rate=0.04,
        short_delta=0.20, long_delta=0.05, dte_days=21,
        wing_width_points=26.0, strike_increment=1.0,
    )
    expiration = date.today() + timedelta(days=30)

    print(format_ticket(ticket, symbol="XSP"))
    print("\nOCC legs that would be submitted:")
    for leg in condor_legs(ticket, "XSP", expiration):
        print(f"  {leg['side'].upper():<4} x{leg['ratio_qty']}  {leg['symbol']}")
    print("\n(No order was submitted -- this block only builds and prints.)")
