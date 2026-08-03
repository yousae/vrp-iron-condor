"""
VRP iron condor dashboard.

Unlike the earlier Claude Artifact version of this page, this is a live
Python process: every chart and stat here is computed by calling the
project's own src/ modules directly, not by embedding a pre-computed data
snapshot. st.cache_data's ttl gives automatic daily-ish freshness for free
-- no scheduled job, no separate regeneration script, no per-refresh
compute cost beyond a normal page load.

Run from the repo root: streamlit run app/streamlit_app.py
"""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import BacktestEngine
from src.data.proxy_signal import (
    compute_realized_volatility,
    fetch_risk_free_rate_history,
    fetch_spx_history,
    fetch_vix_history,
)
from src.signals.iv_rank import compute_iv_rank

REPO_ROOT = Path(__file__).resolve().parents[1]
CHART_FETCH_START = "2018-01-01"  # 1yr before display start: iv_rank needs 252d warmup
CHART_DISPLAY_START = "2019-01-01"
BACKTEST_START = "2005-01-01"

INK = "#DCE1E7"
INK_MUTED = "#7C8896"
GRID = "#1E2530"
PAPER = "#0B0E12"
CARD = "#12161C"
GOLD = "#C79A4B"
RISK = "#C25B45"
CALM = "#4C86B8"
GOOD = "#4E9A6E"
REGIME_PRE = "#C79A4B"
REGIME_POST = "#5B6472"

PLOTLY_LAYOUT = dict(
    paper_bgcolor=PAPER,
    plot_bgcolor=PAPER,
    font=dict(family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", color=INK, size=12),
    margin=dict(l=48, r=16, t=28, b=36),
    hoverlabel=dict(bgcolor=CARD, font=dict(family="ui-monospace, monospace", size=12, color=INK), bordercolor=GRID),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
)
AXIS_STYLE = dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID, tickfont=dict(color=INK_MUTED))


@st.cache_data(ttl=timedelta(hours=24), show_spinner="Pulling VIX / SPX history...")
def load_chart_data() -> pd.DataFrame:
    end = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    vix = fetch_vix_history(CHART_FETCH_START, end)
    spx = fetch_spx_history(CHART_FETCH_START, end)
    rv = compute_realized_volatility(spx, window_days=21)
    rank = compute_iv_rank(vix, lookback_days=252)

    df = pd.DataFrame({"vix": vix, "rv": rv, "rank": rank}).dropna()
    df = df[df.index >= CHART_DISPLAY_START]
    return df.resample("W").last().dropna()


@st.cache_data(ttl=timedelta(hours=24), show_spinner="Running the backtest...")
def load_backtest_data() -> dict:
    with open(REPO_ROOT / "config" / "params.yaml") as f:
        config = yaml.safe_load(f)

    end = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
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
        results[threshold] = engine.summary_stats()
    return results


def vrp_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["vix"], name="VIX (implied)", mode="lines",
                              line=dict(color=RISK, width=1.6), fill=None))
    fig.add_trace(go.Scatter(x=df.index, y=df["rv"], name="Realized vol (21d)", mode="lines",
                              line=dict(color=CALM, width=1.6), fill="tonexty",
                              fillcolor="rgba(199,154,75,0.12)"))
    fig.update_layout(**PLOTLY_LAYOUT, height=340, xaxis=AXIS_STYLE,
                       yaxis=dict(**AXIS_STYLE, title="annualized vol, %"))
    return fig


def rank_chart(df: pd.DataFrame, thresholds: list[int]) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["rank"], name="IV rank", mode="lines",
                              line=dict(color=GOLD, width=1.6), fill="tozeroy",
                              fillcolor="rgba(199,154,75,0.08)"))
    for t in thresholds:
        fig.add_hline(y=t, line=dict(color=INK_MUTED, width=1, dash="dot"),
                       annotation_text=f"{t}", annotation_font=dict(color=INK_MUTED, size=10),
                       annotation_position="right")
    fig.update_layout(**PLOTLY_LAYOUT, height=300, xaxis=AXIS_STYLE,
                       yaxis=dict(**AXIS_STYLE, title="IV rank (0-100)", range=[0, 100]))
    return fig


def payoff_chart(short_delta: float, long_delta: float) -> go.Figure:
    xs = [-15, -8, -4, 4, 8, 15]
    ys = [-2, -2, 1, 1, -2, -2]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[-8, -4], y=[-2, 1], mode="lines", line=dict(color=RISK, width=0),
                              fill="tozeroy", fillcolor="rgba(194,91,69,0.15)", hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=[4, 8], y=[1, -2], mode="lines", line=dict(color=RISK, width=0),
                              fill="tozeroy", fillcolor="rgba(194,91,69,0.15)", hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=[-4, 4], y=[1, 1], mode="lines", line=dict(color=GOOD, width=0),
                              fill="tozeroy", fillcolor="rgba(78,154,110,0.15)", hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=INK, width=2.5),
                              hovertemplate="P&L: %{y:.1f} units<extra></extra>", showlegend=False))

    strike_labels = [
        (-8, f"Long put (~{long_delta:.2f}Δ)", -2.75),
        (-4, f"Short put (~{short_delta:.2f}Δ)", -2.45),
        (4, f"Short call (~{short_delta:.2f}Δ)", -2.45),
        (8, f"Long call (~{long_delta:.2f}Δ)", -2.75),
    ]
    for x, label, y in strike_labels:
        fig.add_vline(x=x, line=dict(color=GRID, width=1, dash="dot"))
        fig.add_annotation(x=x, y=y, text=label, showarrow=False, font=dict(size=10, color=INK_MUTED))
    fig.add_vline(x=0, line=dict(color=GOLD, width=1.2))
    fig.add_annotation(x=0, y=1.5, text="Spot at entry", showarrow=False, font=dict(size=10, color=GOLD))

    fig.update_layout(**PLOTLY_LAYOUT, height=340,
                       xaxis=dict(**AXIS_STYLE, title="% move from entry", range=[-15, 15]),
                       yaxis=dict(**AXIS_STYLE, title="P&L (illustrative units)", range=[-3, 2.2]))
    return fig


def sharpe_bar_chart(backtest: dict) -> go.Figure:
    thresholds = list(backtest.keys())
    pre = [backtest[t]["pre_2010"].get("sharpe", float("nan")) for t in thresholds]
    post = [backtest[t]["post_2010"].get("sharpe", float("nan")) for t in thresholds]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=[f"> {t}" for t in thresholds], y=pre, name="Pre-2010", marker_color=REGIME_PRE))
    fig.add_trace(go.Bar(x=[f"> {t}" for t in thresholds], y=post, name="Post-2010", marker_color=REGIME_POST))
    fig.update_layout(**PLOTLY_LAYOUT, height=320, barmode="group",
                       xaxis=dict(**AXIS_STYLE, title="IV rank entry threshold"),
                       yaxis=dict(**AXIS_STYLE, title="Sharpe"))
    return fig


def inject_css() -> None:
    st.markdown(
        """
        <style>
        [data-testid="stMetricValue"] { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
        [data-testid="stDataFrame"] * { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
        h1, h2, h3 { letter-spacing: -0.01em; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title="VRP Iron Condor", page_icon="▢", layout="wide")
    inject_css()

    with open(REPO_ROOT / "config" / "params.yaml") as f:
        config = yaml.safe_load(f)
    thresholds = config["signal"]["iv_rank_thresholds_to_test"]

    chart_df = load_chart_data()
    backtest = load_backtest_data()
    latest = chart_df.iloc[-1]

    st.markdown("### VRP / SPX Iron Condor")
    st.caption(
        f"Underlying: SPX  ·  Structure: iron condor, monthly  ·  Phase 3/8  ·  research only, no live trading  ·  "
        f"data as of {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("VIX", f"{latest['vix']:.2f}")
    m1.caption("CBOE's index of S&P 500 option prices — the market's forecast of how much the index will move over the next 30 days.")
    m2.metric("Realized vol (21d)", f"{latest['rv']:.2f}")
    m2.caption("How much the S&P 500 actually moved over the last 21 trading days, annualized so it's on the same scale as VIX.")
    m3.metric("VRP (VIX - RV)", f"{latest['vix'] - latest['rv']:+.2f}")
    m3.caption("Volatility risk premium: the gap between what the market feared (VIX) and what actually happened (realized vol).")
    m4.metric("IV rank (252d)", f"{latest['rank']:.0f}")
    m4.caption("Where today's VIX sits within its own trailing 1-year range, 0-100. High = fear is unusually expensive right now.")

    st.divider()

    tab_vrp, tab_trade, tab_signal, tab_pipeline, tab_backtest = st.tabs(
        ["VRP", "The Trade", "The Signal", "Pipeline", "Backtest"]
    )

    with tab_vrp:
        col_chart, col_notes = st.columns([2.2, 1])
        with col_chart:
            st.plotly_chart(vrp_chart(chart_df), use_container_width=True)
            weeks = len(chart_df)
            mean_vix = chart_df["vix"].mean()
            mean_rv = chart_df["rv"].mean()
            pct_above = (chart_df["vix"] > chart_df["rv"]).mean() * 100
            st.caption(
                f"Over these {weeks} weeks: mean VIX {mean_vix:.1f}, mean realized vol {mean_rv:.1f}. "
                f"VIX exceeded realized vol in {pct_above:.1f}% of weeks."
            )
        with col_notes:
            st.markdown("**Intuition**")
            st.write(
                "VIX is priced like an insurance premium: it runs a bit richer than the risk it's "
                "covering, on average, because the seller needs compensation for the times it doesn't."
            )
            st.markdown("**Technical**")
            st.latex(r"RV = \sqrt{252} \times \operatorname{std}\!\left(\ln \frac{P_t}{P_{t-1}}\right)")
            st.caption("21-day trailing window. VRP is simply VIX minus RV.")

    with tab_trade:
        col_chart, col_notes = st.columns([2.2, 1])
        with col_chart:
            st.plotly_chart(
                payoff_chart(config["structure"]["short_delta"], config["structure"]["long_delta"]),
                use_container_width=True,
            )
        with col_notes:
            st.markdown("**Intuition**")
            st.write(
                "Sell the near strikes for most of the premium; buy the far strikes purely as insurance "
                "for yourself. Max loss is fixed the moment the trade opens."
            )
            st.markdown("**Technical**")
            st.latex(r"L_{max} = (K_{short} - K_{long}) - \text{credit}")
            st.caption("Bounded loss is what makes this Kelly-tractable, unlike a naked put.")

    with tab_signal:
        col_chart, col_notes = st.columns([2.2, 1])
        with col_chart:
            st.plotly_chart(rank_chart(chart_df, thresholds), use_container_width=True)
        with col_notes:
            st.markdown("**Intuition**")
            st.write("Only enter when implied vol is rich *relative to its own last year* — not a fixed VIX level.")
            st.markdown("**Technical**")
            st.latex(r"IV_{rank}(t) = 100 \times \frac{IV_t - Min_t}{Max_t - Min_t}")
            st.caption("Trailing 252-day window — day t never sees data from after day t.")

    with tab_pipeline:
        pipeline = pd.DataFrame([
            {"Stage": "Data", "File": "proxy_signal.py", "Status": "Built"},
            {"Stage": "Signal", "File": "iv_rank.py", "Status": "Built"},
            {"Stage": "Pricing", "File": "pricing.py", "Status": "Built"},
            {"Stage": "Backtest", "File": "engine.py", "Status": "Built"},
            {"Stage": "Risk", "File": "sizing.py", "Status": "Stub"},
            {"Stage": "Execution", "File": "alpaca_client.py", "Status": "Stub"},
            {"Stage": "Decision", "File": "go / no-go", "Status": "Not started"},
        ])
        status_color = {"Built": GOOD, "Stub": GOLD, "Not started": INK_MUTED}
        styled = pipeline.style.map(lambda v: f"color: {status_color.get(v, INK)}; font-weight: 600", subset=["Status"])
        st.dataframe(styled, use_container_width=True, hide_index=True)

    with tab_backtest:
        st.plotly_chart(sharpe_bar_chart(backtest), use_container_width=True)

        rows = []
        for t in thresholds:
            for regime_key, regime_label in [("pre_2010", "Pre-2010"), ("post_2010", "Post-2010")]:
                s = backtest[t][regime_key]
                if s.get("n_trades", 0) == 0:
                    continue
                rows.append({
                    "Threshold": f"> {t}", "Regime": regime_label, "Trades": s["n_trades"],
                    "Win rate": f"{s['win_rate']*100:.0f}%", "Sharpe": f"{s['sharpe']:.2f}",
                    "Sortino": f"{s['sortino']:.2f}",
                    "Worst trade": f"-${abs(s['worst_trade_pnl_usd']):,.0f}",
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.warning(
            "Proxy pricing (Black-Scholes off flat VIX, no skew) understates put-wing credit. "
            "1 contract vs. a $1,000 placeholder account -- position sizing (src/risk/sizing.py) is still a stub. "
            "Hold-to-expiration only.",
            icon="⚠",
        )


if __name__ == "__main__":
    main()
