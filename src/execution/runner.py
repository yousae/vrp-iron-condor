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

    return {
        "as_of": vix.index[-1].date(),
        "spot_spx": float(spx.iloc[-1]),
        "vix": float(vix.iloc[-1]),
        "risk_free_rate": float(rate.iloc[-1]),
        "iv_rank": float(iv_rank.iloc[-1]),
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

    contracts = int(budget // probe.max_loss_usd)
    if contracts < 1:
        return {
            "trade": False,
            "reason": (f"risk budget ${budget:,.0f} < one contract's max loss "
                       f"${probe.max_loss_usd:,.0f}; cap is binding, not a bug"),
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
        "strikes": {
            "long_put": ticket.long_put_strike, "short_put": ticket.short_put_strike,
            "short_call": ticket.short_call_strike, "long_call": ticket.long_call_strike,
        },
        "modeled_credit_usd": round(ticket.modeled_credit_usd, 2),
        "max_loss_usd": round(ticket.max_loss_usd, 2),
    })

    return {"submitted": True, "order": order, **decision}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one paper-trading decision cycle.")
    parser.add_argument("--submit", action="store_true",
                        help="actually submit to Alpaca paper (default is a dry run)")
    args = parser.parse_args()

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
