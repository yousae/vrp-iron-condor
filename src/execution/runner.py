"""
Paper-trading runner: the loop that actually trades the strategy.

One invocation = one decision. Fetch data, compute the signal, and if it
fires, size a position, build the condor, and submit it to Alpaca paper.
Intended to be run once per trading day (cron, or by hand); it is
idempotent in the sense that it refuses to open a second position while
one is already open.

SAFETY: dry_run defaults to True everywhere. Nothing is ever submitted
unless a caller explicitly passes dry_run=False, and live trading is
blocked separately in alpaca_client.get_client(). Running this module
directly is always a dry run -- placing a real paper order requires the
--submit flag.

Sizing note: contracts are floor-divided from the per-trade risk budget,
so a budget smaller than one contract's max loss yields ZERO contracts
and no trade. That is the correct behavior -- it is the risk cap doing
its job, not a bug to route around by rounding up.
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.backtest.engine import BacktestEngine
from src.data.proxy_signal import (
    fetch_risk_free_rate_history,
    fetch_skew_history,
    fetch_spx_history,
    fetch_vix_history,
)
from src.execution import trade_log
from src.execution.expiration import calendar_days_to, next_monthly_expiration
from src.execution.ticket import build_ticket, format_ticket
from src.risk.sizing import kelly_fraction, position_size
from src.signals.iv_rank import compute_iv_rank

REPO_ROOT = Path(__file__).resolve().parents[2]
SIGNAL_HISTORY_START = "2018-01-01"  # enough warmup for a 252d IV-rank window


def load_config(path: Path = REPO_ROOT / "config" / "params.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def current_market(as_of: date | None = None) -> dict:
    """Latest VIX / SPX / risk-free rate, plus today's IV rank.

    IV rank is computed from the full trailing series rather than a
    stored value, so the live signal uses exactly the same code path as
    the backtest -- which is what makes the signal-fidelity check
    meaningful rather than circular.
    """
    end = ((as_of or date.today()) + timedelta(days=1)).strftime("%Y-%m-%d")
    vix = fetch_vix_history(SIGNAL_HISTORY_START, end)
    spx = fetch_spx_history(SIGNAL_HISTORY_START, end)
    rate = fetch_risk_free_rate_history(SIGNAL_HISTORY_START, end)

    iv_rank = compute_iv_rank(vix, lookback_days=252).dropna()
    if iv_rank.empty:
        raise RuntimeError("not enough history to compute IV rank")

    # Logged for context only -- nothing is priced off it. See
    # fetch_skew_history() and project_spec.md section 7.
    try:
        skew = float(fetch_skew_history(SIGNAL_HISTORY_START, end).iloc[-1])
    except Exception:
        skew = None

    return {
        "as_of": vix.index[-1].date(),
        "spot_spx": float(spx.iloc[-1]),
        "vix": float(vix.iloc[-1]),
        "risk_free_rate": float(rate.iloc[-1]),
        "iv_rank": float(iv_rank.iloc[-1]),
        "skew": skew,
    }


def backtest_edge(config: dict) -> dict:
    """Win rate and average win/loss from the backtest, for Kelly sizing.

    Uses the POST-2010 regime only. Pre-2010 numbers are stronger, and
    sizing off them would size against an edge the literature (and this
    project's own results) say has since compressed -- the optimistic
    half of a bimodal history is exactly the wrong input to a bet-sizing
    formula.
    """
    end = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    spx = fetch_spx_history("2005-01-01", end)
    vix = fetch_vix_history("2005-01-01", end)
    rate = fetch_risk_free_rate_history("2005-01-01", end)
    idx = spx.index.intersection(vix.index).intersection(rate.index)

    params = dict(config)
    params["threshold"] = config["paper_trading"]["paper_stream_threshold"]
    engine = BacktestEngine(params)
    trades = engine.run(spx.loc[idx], vix.loc[idx], rate.loc[idx])

    post = [t for t in trades if t.entry_date.year >= config["backtest"]["regime_split_year"]]
    wins = [t.pnl for t in post if t.pnl > 0]
    losses = [-t.pnl for t in post if t.pnl <= 0]
    if not wins or not losses:
        raise RuntimeError("post-2010 backtest has no wins or no losses -- cannot size with Kelly")

    return {
        "n_trades": len(post),
        "win_rate": len(wins) / len(post),
        "avg_win_usd": sum(wins) / len(wins),
        "avg_loss_usd": sum(losses) / len(losses),
    }


def decide(config: dict, market: dict, edge: dict) -> dict:
    """Pure decision step: should we trade, and if so, what exactly?

    No network, no side effects -- so the whole decision is testable
    without credentials or a live market.
    """
    threshold = config["paper_trading"]["paper_stream_threshold"]
    execution = config["execution"]
    risk = config["risk"]

    if market["iv_rank"] <= threshold:
        return {"trade": False, "reason": f"iv_rank {market['iv_rank']:.1f} <= threshold {threshold}"}

    open_now = trade_log.open_positions()
    if open_now:
        return {"trade": False, "reason": f"{len(open_now)} position(s) already open; v1 holds one at a time"}

    kf = kelly_fraction(edge["win_rate"], edge["avg_win_usd"], edge["avg_loss_usd"])
    budget = position_size(
        account_capital=risk["starting_capital_usd"],
        kelly_frac=kf,
        kelly_multiplier=risk["kelly_fraction"],
        max_risk_per_trade_pct=risk["max_risk_per_trade_pct"],
    )

    spot = market["spot_spx"] / 10 if execution["symbol"] == "XSP" else market["spot_spx"]
    probe = build_ticket(
        spot=spot,
        implied_vol=market["vix"] / 100,
        risk_free_rate=market["risk_free_rate"],
        short_delta=config["structure"]["short_delta"],
        long_delta=config["structure"]["long_delta"],
        dte_days=config["pricing_proxy"]["dte_trading_days"],
        contracts=1,
        wing_width_points=execution["wing_width_points"],
        strike_increment=execution["strike_increment"],
    )

    slippage = config["backtest"]["slippage_pct_of_credit"]
    worst_case = probe.max_loss_at_credit(probe.modeled_credit_usd * (1 - slippage))
    contracts = int(budget // worst_case)
    if contracts < 1:
        return {
            "trade": False,
            "reason": (f"risk budget ${budget:,.0f} < one contract's max loss "
                       f"${worst_case:,.0f} (at net credit); cap is binding, not a bug"),
        }

    ticket = build_ticket(
        spot=spot,
        implied_vol=market["vix"] / 100,
        risk_free_rate=market["risk_free_rate"],
        short_delta=config["structure"]["short_delta"],
        long_delta=config["structure"]["long_delta"],
        dte_days=config["pricing_proxy"]["dte_trading_days"],
        contracts=contracts,
        wing_width_points=execution["wing_width_points"],
        strike_increment=execution["strike_increment"],
    )
    expiration = next_monthly_expiration(
        market["as_of"], execution["target_calendar_days_to_expiry"]
    )

    return {
        "trade": True,
        "reason": f"iv_rank {market['iv_rank']:.1f} > threshold {threshold}",
        "ticket": ticket,
        "expiration": expiration,
        "contracts": contracts,
        "kelly_fraction": kf,
        "risk_budget_usd": budget,
    }


def run(dry_run: bool = True, config: dict | None = None) -> dict:
    """One decision cycle. Logs whatever happens, trade or not."""
    config = config or load_config()
    market = current_market()
    edge = backtest_edge(config)
    decision = decide(config, market, edge)

    trade_log.append({
        "kind": "signal_check",
        "as_of": market["as_of"],
        "iv_rank": round(market["iv_rank"], 2),
        "vix": round(market["vix"], 2),
        "skew": round(market["skew"], 2) if market.get("skew") else None,
        "threshold": config["paper_trading"]["paper_stream_threshold"],
        "fired": decision["trade"],
        "reason": decision["reason"],
    })

    if not decision["trade"]:
        return {"submitted": False, **decision}

    ticket, expiration = decision["ticket"], decision["expiration"]
    symbol = config["execution"]["symbol"]

    if dry_run:
        return {"submitted": False, "dry_run": True, **decision}

    from src.execution.alpaca_client import build_condor_order, get_client, submit_order

    client = get_client(paper=True)
    order_request = build_condor_order(
        ticket, symbol, expiration,
        limit_credit=round(ticket.modeled_credit_usd / (100 * ticket.contracts), 2),
    )
    order = submit_order(client, order_request)

    trade_log.append({
        "kind": "order_submitted",
        "order_id": str(getattr(order, "id", "unknown")),
        "as_of": market["as_of"],
        "symbol": symbol,
        "expiration": expiration,
        "dte_calendar_days": calendar_days_to(expiration, market["as_of"]),
        "contracts": ticket.contracts,
        "iv_rank_at_entry": round(market["iv_rank"], 2),
        "skew_at_entry": round(market["skew"], 2) if market.get("skew") else None,
        "strikes": {
            "long_put": ticket.long_put_strike, "short_put": ticket.short_put_strike,
            "short_call": ticket.short_call_strike, "long_call": ticket.long_call_strike,
        },
        "modeled_credit_usd": round(ticket.modeled_credit_usd, 2),
        "max_loss_usd": round(ticket.max_loss_usd, 2),
    })

    return {"submitted": True, "order": order, **decision}


def check_account() -> dict:
    """Read-only connectivity + approval check. Places nothing."""
    from src.execution.alpaca_client import describe_preflight, get_client, preflight

    info = preflight(get_client(paper=True))
    print("PREFLIGHT")
    print(describe_preflight(info))
    return info


def plumbing_test(config: dict | None = None) -> dict:
    """Submit ONE deliberately-flagged order to verify the execution path.

    This exists because the signal fires ~3x/year, so waiting for it is a
    hopeless way to discover that an OCC symbol is malformed or that the
    limit-price convention is inverted. It bypasses the signal ON PURPOSE.

    Logged as kind="plumbing_test", never "order_submitted", so it can
    never be counted in Phase 5 trade statistics -- but trade_log's
    open_positions() does count it, because it opens a real paper
    position that must block a concurrent signal trade.

    Always 1 contract: the goal is to learn whether the plumbing works,
    not to take a position.
    """
    from src.execution.alpaca_client import (
        build_condor_order,
        describe_preflight,
        fetch_listed_strikes,
        get_client,
        get_order,
        preflight,
        submit_order,
    )

    config = config or load_config()
    client = get_client(paper=True)

    info = preflight(client)
    print("PREFLIGHT")
    print(describe_preflight(info))
    if not info["options_level_sufficient"]:
        raise RuntimeError(
            f"options level too low for a 4-leg spread (need >= 3). "
            "Raise it in the Alpaca dashboard before retrying."
        )
    if info["account_blocked"] or info["trading_blocked"]:
        raise RuntimeError("account or trading is blocked; resolve in the Alpaca dashboard.")

    open_now = trade_log.open_positions()
    if open_now:
        raise RuntimeError(f"{len(open_now)} position(s) already open -- close them first.")

    market = current_market()
    execution = config["execution"]
    expiration = next_monthly_expiration(
        market["as_of"], execution["target_calendar_days_to_expiry"]
    )
    # Read the real strike grid rather than assuming one. XSP lists ~$1
    # apart near the money but $5/$10 further out, so a computed wing can
    # land on a strike that does not exist.
    strikes = fetch_listed_strikes(client, execution["symbol"], expiration)
    print(f"\n  {len(strikes)} strikes listed for {expiration}")

    spot = market["spot_spx"] / 10 if execution["symbol"] == "XSP" else market["spot_spx"]
    ticket = build_ticket(
        spot=spot,
        implied_vol=market["vix"] / 100,
        risk_free_rate=market["risk_free_rate"],
        short_delta=config["structure"]["short_delta"],
        long_delta=config["structure"]["long_delta"],
        dte_days=config["pricing_proxy"]["dte_trading_days"],
        contracts=1,
        wing_width_points=execution["wing_width_points"],
        strike_increment=execution["strike_increment"],
        available_strikes=strikes,
    )
    limit_credit = round(ticket.modeled_credit_usd / 100, 2)

    print()
    print(format_ticket(ticket, symbol=execution["symbol"]))
    print(f"\n  expiration:   {expiration}")
    print(f"  limit price:  {limit_credit}  (interpreted as a per-spread CREDIT -- "
          "this is the convention under test)")
    print("\nSUBMITTING ONE PLUMBING-TEST ORDER...")

    order = submit_order(client, build_condor_order(
        ticket, execution["symbol"], expiration, limit_credit=limit_credit))
    order_id = str(getattr(order, "id", "unknown"))

    fetched = get_order(client, order_id)
    status = str(getattr(fetched, "status", "unknown"))
    filled_qty = getattr(fetched, "filled_qty", None)
    filled_price = getattr(fetched, "filled_avg_price", None)

    record = trade_log.append({
        "kind": "plumbing_test",
        "order_id": order_id,
        "as_of": market["as_of"],
        "symbol": execution["symbol"],
        "expiration": expiration,
        "contracts": 1,
        "limit_credit_submitted": limit_credit,
        "modeled_credit_usd": round(ticket.modeled_credit_usd, 2),
        "max_loss_usd": round(ticket.max_loss_usd, 2),
        "order_status": status,
        "filled_qty": str(filled_qty) if filled_qty is not None else None,
        "filled_avg_price": str(filled_price) if filled_price is not None else None,
        "note": "signal bypassed on purpose; excluded from Phase 5 statistics",
    })

    print(f"\n  order id:     {order_id}")
    print(f"  status:       {status}")
    print(f"  filled qty:   {filled_qty}")
    print(f"  fill price:   {filled_price}")
    print("\nWHAT TO CHECK NOW:")
    print("  1. Do the four legs in the Alpaca dashboard match the ticket above?")
    print("  2. Is the position SHORT the inner strikes (credit received, not paid)?")
    print("  3. If filled: is the credit positive and near the modeled value?")
    print("     A large negative or near-zero fill means the limit convention is inverted.")
    print("  4. Close the position in the dashboard when done -- it is not a real trade.")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one paper-trading decision cycle.")
    parser.add_argument("--submit", action="store_true",
                        help="actually submit to Alpaca paper (default is a dry run)")
    parser.add_argument("--check", action="store_true",
                        help="read-only preflight: connectivity, paper endpoint, options level")
    parser.add_argument("--plumbing-test", action="store_true",
                        help="submit ONE flagged test order, bypassing the signal, to verify "
                             "symbols and the limit-price convention")
    args = parser.parse_args()

    if args.check:
        check_account()
        return
    if args.plumbing_test:
        plumbing_test()
        return

    config = load_config()
    result = run(dry_run=not args.submit, config=config)

    print(f"signal: {result['reason']}")
    if not result["trade"]:
        print("no trade.")
        return

    ticket = result["ticket"]
    print(f"\nKelly f*={result['kelly_fraction']:.3f} -> risk budget ${result['risk_budget_usd']:,.0f}"
          f" -> {result['contracts']} contract(s)")
    print(f"expiration: {result['expiration']}\n")
    print(format_ticket(ticket, symbol=config["execution"]["symbol"]))

    if result["submitted"]:
        print(f"\nSUBMITTED. order id: {getattr(result['order'], 'id', 'unknown')}")
    else:
        print("\nDRY RUN -- nothing submitted. Re-run with --submit to place this order.")


if __name__ == "__main__":
    main()
