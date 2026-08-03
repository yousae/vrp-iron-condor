"""
Refreshes docs/visual_guide.html in place with current market data and a
fresh backtest run -- rewrites the embedded DATA/BACKTEST/META JS objects,
nothing else in the file. Does not touch git; publishing the refreshed file
as the live Claude Artifact is a separate step (see the scheduled routine
that calls this script).

Run from the repo root: python3 scripts/regenerate_visual_guide.py
"""

import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from src.backtest.engine import BacktestEngine
from src.data.proxy_signal import (
    compute_realized_volatility,
    fetch_risk_free_rate_history,
    fetch_spx_history,
    fetch_vix_history,
)
from src.signals.iv_rank import compute_iv_rank

REPO_ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = REPO_ROOT / "docs" / "visual_guide.html"

CHART_DISPLAY_START = "2019-01-01"
# fetch a year earlier than the intended display start: compute_iv_rank needs
# 252 trading days of trailing history before it produces a non-NaN value, so
# fetching from CHART_DISPLAY_START directly would silently drop ~all of 2019.
CHART_FETCH_START = "2018-01-01"
BACKTEST_START = "2005-01-01"


def build_chart_data(end: str) -> dict:
    vix = fetch_vix_history(CHART_FETCH_START, end)
    spx = fetch_spx_history(CHART_FETCH_START, end)
    rv = compute_realized_volatility(spx, window_days=21)
    rank = compute_iv_rank(vix, lookback_days=252)

    import pandas as pd

    df = pd.DataFrame({"vix": vix, "rv": rv, "rank": rank}).dropna()
    weekly = df.resample("W").last().dropna()

    return {
        "dates": [d.strftime("%Y-%m-%d") for d in weekly.index],
        "vix": [round(float(x), 2) for x in weekly["vix"]],
        "rv": [round(float(x), 2) for x in weekly["rv"]],
        "rank": [round(float(x), 1) for x in weekly["rank"]],
    }


def build_backtest_data(end: str) -> dict:
    with open(REPO_ROOT / "config" / "params.yaml") as f:
        config = yaml.safe_load(f)

    spx = fetch_spx_history(BACKTEST_START, end)
    vix = fetch_vix_history(BACKTEST_START, end)
    rate = fetch_risk_free_rate_history(BACKTEST_START, end)
    idx = spx.index.intersection(vix.index).intersection(rate.index)
    spx, vix, rate = spx.loc[idx], vix.loc[idx], rate.loc[idx]

    results = {}
    for threshold in config["signal"]["iv_rank_thresholds_to_test"]:
        params = dict(config)
        params["threshold"] = threshold
        engine = BacktestEngine(params)
        engine.run(spx, vix, rate)
        stats = engine.summary_stats()

        results[str(threshold)] = {
            "pre": {
                "n": stats["pre_2010"].get("n_trades", 0),
                "win": stats["pre_2010"].get("win_rate", 0),
                "sharpe": stats["pre_2010"].get("sharpe", float("nan")),
                "sortino": stats["pre_2010"].get("sortino", float("nan")),
                "worst": stats["pre_2010"].get("worst_trade_pnl_usd", 0),
            },
            "post": {
                "n": stats["post_2010"].get("n_trades", 0),
                "win": stats["post_2010"].get("win_rate", 0),
                "sharpe": stats["post_2010"].get("sharpe", float("nan")),
                "sortino": stats["post_2010"].get("sortino", float("nan")),
                "worst": stats["post_2010"].get("worst_trade_pnl_usd", 0),
            },
        }
    return results


def replace_js_var(html: str, var_name: str, value: dict) -> str:
    payload = json.dumps(value, separators=(",", ":"))
    pattern = re.compile(r"var " + re.escape(var_name) + r" = .*?;", re.DOTALL)
    replacement = f"var {var_name} = {payload};"
    new_html, count = pattern.subn(replacement, html, count=1)
    if count != 1:
        raise RuntimeError(f"expected exactly one 'var {var_name} = ...;' block, found {count}")
    return new_html


def main() -> None:
    today = date.today()
    end = (today + timedelta(days=1)).strftime("%Y-%m-%d")  # yfinance end is exclusive

    chart_data = build_chart_data(end)
    backtest_data = build_backtest_data(end)
    meta = {
        "generated_at": today.strftime("%Y-%m-%d"),
        "backtest_start": BACKTEST_START,
        "backtest_end": end,
    }

    html = HTML_PATH.read_text()
    html = replace_js_var(html, "DATA", chart_data)
    html = replace_js_var(html, "BACKTEST", backtest_data)
    html = replace_js_var(html, "META", meta)
    HTML_PATH.write_text(html)

    print(f"Refreshed {HTML_PATH} as of {meta['generated_at']}")
    print(f"  chart: {len(chart_data['dates'])} weekly points, {chart_data['dates'][0]} -> {chart_data['dates'][-1]}")
    for threshold, regimes in backtest_data.items():
        print(f"  threshold>{threshold}: pre sharpe={regimes['pre']['sharpe']:.2f} post sharpe={regimes['post']['sharpe']:.2f}")


if __name__ == "__main__":
    main()
