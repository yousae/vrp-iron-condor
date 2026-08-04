"""
Manual execution support for thinkorswim paperMoney.

thinkorswim paperMoney has no API -- the Schwab Trader API that replaced
TD Ameritrade's covers live funded accounts only, and cannot place
paperMoney orders (verified 2026-08-03). So orders are typed into the
platform by hand. This module handles the parts that should NOT be
manual: computing target strikes from the model, printing a ticket to
enter, and reconciling what actually filled against what was predicted.

That last part is the point. Phase 5's most important deliverable is
sim-to-live reconciliation (project_spec.md section 9.2, criterion 4):
if realized fills persistently diverge from the model, the backtest's
cost assumptions are wrong -- which would make every backtest number
this project has produced suspect, not merely optimistic. Manual entry
is actually an advantage here, since the operator sees the real bid/ask
and per-strike IV (the skew the flat-VIX proxy can't model) at fill time.

Nothing in this module talks to a broker. It cannot place an order.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

# needed so `from src...` resolves whether this file is run directly
# (python src/execution/manual_ticket.py) or imported from elsewhere
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.backtest.pricing import bs_price, strike_from_delta


@dataclass
class Ticket:
    """A condor to enter by hand, priced at the model's mid."""

    spot: float
    implied_vol: float
    dte_days: int
    contracts: int
    short_put_strike: float
    long_put_strike: float
    short_call_strike: float
    long_call_strike: float
    modeled_credit_usd: float
    max_loss_usd: float


@dataclass
class FillReconciliation:
    """Actual fill vs. the model -- the Phase 5 pass/fail evidence."""

    modeled_credit_usd: float
    actual_credit_usd: float
    slippage_usd: float
    slippage_pct_of_credit: float
    within_model_assumption: bool
    is_disqualifying: bool

    def summary(self) -> str:
        verdict = (
            "DISQUALIFYING" if self.is_disqualifying
            else "within model" if self.within_model_assumption
            else "worse than modeled, not disqualifying"
        )
        return (
            f"modeled ${self.modeled_credit_usd:,.2f} -> actual ${self.actual_credit_usd:,.2f} "
            f"(slippage ${self.slippage_usd:,.2f} = {self.slippage_pct_of_credit:.1%}) -- {verdict}"
        )


def build_ticket(
    spot: float,
    implied_vol: float,
    risk_free_rate: float,
    short_delta: float,
    long_delta: float,
    dte_days: int,
    contracts: int = 1,
    multiplier: int = 100,
    wing_width_points: float | None = None,
) -> Ticket:
    """Compute the strikes and modeled credit for one condor entry.

    implied_vol is a decimal (0.16, not 16). short_delta/long_delta are
    positive magnitudes (0.20, 0.05) and get signed internally.

    wing_width_points overrides delta-based wing selection with a fixed
    width. This exists because delta-based CNDR wings produce a max loss
    far too large for a small account (~$20k/contract on SPX at 2026
    levels), so a fixed narrower wing may be required -- an open
    structural decision, see project_spec.md section 2. Passing None
    keeps the CNDR-comparable delta-based behavior.
    """
    if not 0 < implied_vol < 5:
        raise ValueError(f"implied_vol should be a decimal like 0.16, got {implied_vol}")
    if contracts < 1:
        raise ValueError("contracts must be >= 1")

    t_years = dte_days / 252.0

    short_put = strike_from_delta(spot, t_years, risk_free_rate, implied_vol, -short_delta, "put")
    short_call = strike_from_delta(spot, t_years, risk_free_rate, implied_vol, short_delta, "call")

    if wing_width_points is None:
        long_put = strike_from_delta(spot, t_years, risk_free_rate, implied_vol, -long_delta, "put")
        long_call = strike_from_delta(spot, t_years, risk_free_rate, implied_vol, long_delta, "call")
    else:
        long_put = short_put - wing_width_points
        long_call = short_call + wing_width_points

    credit_per_unit = (
        (bs_price(spot, short_put, t_years, risk_free_rate, implied_vol, "put")
         - bs_price(spot, long_put, t_years, risk_free_rate, implied_vol, "put"))
        + (bs_price(spot, short_call, t_years, risk_free_rate, implied_vol, "call")
           - bs_price(spot, long_call, t_years, risk_free_rate, implied_vol, "call"))
    )
    modeled_credit = credit_per_unit * multiplier * contracts

    # Max loss is set by the WIDER wing -- only one side can finish in the
    # money, so the loss is capped by whichever spread is wider, not their sum.
    widest_wing = max(short_put - long_put, long_call - short_call)
    max_loss = widest_wing * multiplier * contracts - modeled_credit

    return Ticket(
        spot=spot,
        implied_vol=implied_vol,
        dte_days=dte_days,
        contracts=contracts,
        short_put_strike=short_put,
        long_put_strike=long_put,
        short_call_strike=short_call,
        long_call_strike=long_call,
        modeled_credit_usd=modeled_credit,
        max_loss_usd=max_loss,
    )


def format_ticket(ticket: Ticket, symbol: str = "XSP") -> str:
    """Human-readable order ticket to type into thinkorswim.

    Leg order matches how an iron condor is conventionally entered
    (long put, short put, short call, long call -- low strike to high).
    """
    n = ticket.contracts
    return "\n".join([
        f"IRON CONDOR  {symbol}  {ticket.dte_days} DTE  x{n}",
        f"  spot {ticket.spot:,.2f}   IV {ticket.implied_vol:.1%}",
        "  ---------------------------------------------",
        f"  BUY  {n}  {symbol} PUT   {ticket.long_put_strike:>9,.2f}",
        f"  SELL {n}  {symbol} PUT   {ticket.short_put_strike:>9,.2f}",
        f"  SELL {n}  {symbol} CALL  {ticket.short_call_strike:>9,.2f}",
        f"  BUY  {n}  {symbol} CALL  {ticket.long_call_strike:>9,.2f}",
        "  ---------------------------------------------",
        f"  modeled credit (mid):  ${ticket.modeled_credit_usd:>10,.2f}",
        f"  max loss:              ${ticket.max_loss_usd:>10,.2f}",
        "",
        "  Enter as a single 4-leg order. Record the ACTUAL fill credit and",
        "  pass it to reconcile_fill() -- do not assume the mid filled.",
    ])


def reconcile_fill(
    ticket: Ticket,
    actual_credit_usd: float,
    modeled_slippage_pct: float,
    disqualifying_slippage_pct: float,
) -> FillReconciliation:
    """Compare an actual fill against the model. Phase 5's core measurement.

    modeled_slippage_pct is the backtest's assumption (config
    backtest.slippage_pct_of_credit, currently 0.10);
    disqualifying_slippage_pct is the pre-registered kill threshold
    (config paper_trading.disqualifying_conditions, currently 0.20).

    Slippage is signed: a fill BETTER than the model gives a negative
    percentage, which is reported honestly rather than clamped to zero,
    since a persistently-better-than-modeled fill is also evidence the
    cost model is miscalibrated.
    """
    slippage_usd = ticket.modeled_credit_usd - actual_credit_usd
    slippage_pct = slippage_usd / ticket.modeled_credit_usd

    return FillReconciliation(
        modeled_credit_usd=ticket.modeled_credit_usd,
        actual_credit_usd=actual_credit_usd,
        slippage_usd=slippage_usd,
        slippage_pct_of_credit=slippage_pct,
        within_model_assumption=slippage_pct <= modeled_slippage_pct,
        is_disqualifying=slippage_pct > disqualifying_slippage_pct,
    )


if __name__ == "__main__":
    # XSP at 1/10 SPX, narrowed wings -- the only structure that fits a
    # $10k paper account under the 2% per-trade cap. See project_spec s2.
    ticket = build_ticket(
        spot=760.0,
        implied_vol=0.159,
        risk_free_rate=0.04,
        short_delta=0.20,
        long_delta=0.05,
        dte_days=21,
        contracts=1,
        wing_width_points=3.0,
    )
    print(format_ticket(ticket, symbol="XSP"))
    print()

    for label, actual in [("filled at mid", ticket.modeled_credit_usd),
                          ("8% worse", ticket.modeled_credit_usd * 0.92),
                          ("25% worse", ticket.modeled_credit_usd * 0.75)]:
        rec = reconcile_fill(ticket, actual, modeled_slippage_pct=0.10,
                             disqualifying_slippage_pct=0.20)
        print(f"  {label:<16} {rec.summary()}")
