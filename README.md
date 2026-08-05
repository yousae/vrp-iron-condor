# SPX volatility risk premium — iron condor research

A systematic, defined-risk options-selling study: harvest the volatility risk
premium on S&P 500 index options via IV-rank-timed iron condors, backtest it
honestly, and paper trade it end to end.

**[▶ Live dashboard](DASHBOARD_URL_HERE)** · [Methodology](docs/project_spec.md) · [Literature review](docs/research/vrp_literature_review.md)

Executed on **XSP** (Mini-SPX — cash-settled, European, 1/10 the size of SPX),
which is what makes a position small enough to respect a 2%-of-capital risk cap.
Signal, backtest, sizing, and execution are one codebase; the bot places real
4-leg orders on Alpaca paper and logs every decision, including the ones where
it declines to trade.

---

## What was hard about it

The interesting parts of this project were not building it — they were catching
the ways it was quietly wrong.

**The backtest was measuring a different strategy than the executor traded.**
The engine priced full-size SPX with delta-based wings — median max loss
$10,879, five times over the 2% risk cap — while the live runner traded
1/10-size XSP. Every reported Sharpe, win rate, and Kelly input described a
position that could never have been placed. Fixed by making both paths build
condors through the same function, so that class of divergence is now
structurally impossible rather than merely unintended.

**The pre-registered success criterion was unreachable, and it was retired
before seeing results.** The original bar was "beat SPY and CNDR on Sharpe and
Sortino." At the measured trade frequency (~3/year), the standard error on a
Sharpe estimate means ~100 trades are needed before a 95% interval excludes
zero — roughly **62 years**. A gate that cannot be satisfied guarantees the
decision gets made on unstated grounds, which is the exact failure
pre-registration exists to prevent. The paper phase now validates *execution*
against explicit disqualifying conditions instead. ([§9.1](docs/project_spec.md))

**The flat-VIX pricing bias is quantified, not hand-waved.** With no volatility
skew, the nominal 0.20-delta short put is really ~**0.24 delta** and its premium
is understated ~49%; the call errs oppositely. The consequences are stated
precisely rather than as a blanket disclaimer: win rates stay *empirically
valid* (payoff is computed against actual SPX paths, not modelled
probabilities), P&L is biased *low* rather than merely uncertain, and the
strategy runs **more aggressively than CNDR's stated methodology** — which must
be disclosed when reporting against that benchmark. A sensitivity parameter
makes the assumption testable rather than asserted. ([§7.1](docs/project_spec.md))

**Live paper testing contradicted the cost model.** Two independent fills showed
real slippage of **17.7–20.3%** against an assumed 10%. At 20%, backtest Sharpe
falls from 0.61 to 0.45 — the edge survives but thins by a quarter. The
assumption was deliberately *not* updated: n=2, in a paper environment, and part
of the gap may be pricing-model error rather than true spread. The evidence is
recorded so the number moves on data rather than on one surprising result.

---

## Results

Backtested 2005–2026 on XSP with 22-point wings, sized to the 2% per-trade cap,
with transaction costs and bid-ask slippage modelled. Pre- and post-2010 are
reported separately because the premium compressed after 2010 — blending them
would misrepresent the current opportunity.

| IV-rank threshold | Pre-2010 Sharpe | Post-2010 Sharpe | Post-2010 win rate | Post-2010 trades |
|---|---|---|---|---|
| > 50 | 0.82 | **0.61** | 80% | 40 |
| > 70 | 0.57 | 0.50 | 86% | 21 |
| > 80 | 0.42 | 0.26 | 76% | 17 |

All three thresholds were **pre-registered before running**, and all three are
reported — no selecting the best in hindsight. Sharpe is consistently lower
post-2010, matching the crowding/decay pattern documented for CBOE's own CNDR
index.

**These are directional, not decisive.** 40 trades is a small sample, the
options are priced with a proxy rather than real chain data, and the slippage
measured above suggests the figures are optimistic on cost.

---

## How it works

```
VIX / SPX / T-bill (yfinance)
        │
        ▼
  IV rank — 252-day trailing percentile      only trade when premium is rich
        │
        ▼
  Black-Scholes strike solve → snap to the real listed strike grid
        │
        ▼
  Fractional Kelly, hard-capped at 2% of capital   half-Kelly ceiling in code
        │
        ▼
  4-leg XSP order, price-walked from mid toward the bid
        │
        ▼
  Append-only trade log — every decision, including non-trades
```

| Stage | Module | State |
|---|---|---|
| Data | `src/data/proxy_signal.py` | VIX / SPX / ^IRX / ^SKEW via yfinance |
| Signal | `src/signals/iv_rank.py` | 252-day trailing IV rank, look-ahead tested |
| Pricing | `src/backtest/pricing.py` | Black-Scholes; put-call parity and delta round-trip verified |
| Backtest | `src/backtest/engine.py` | Pre/post-2010 split; shares the live code path |
| Risk | `src/risk/sizing.py` | Fractional Kelly; half-Kelly ceiling enforced |
| Execution | `src/execution/` | Runner, tickets, expirations, price walk, Alpaca paper |
| Automation | `.github/workflows/` | Weekday scheduled run; tests gate every trade |

**120 tests**, ~3,600 lines. The suite runs *before* the workflow is allowed to
trade, so a broken commit cannot place an order.

---

## Running it

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # Alpaca PAPER keys
```

```bash
python -m src.execution.runner --check       # read-only account and connectivity check
python -m src.execution.runner               # dry run: decide and log, submit nothing
python -m src.execution.runner --submit      # place the signal-gated order
streamlit run app/streamlit_app.py           # dashboard
python -m pytest tests/ -q                   # 120 tests
```

**Live trading is blocked in code**, not by convention: `get_client()` hardcodes
the paper endpoint and rejects `paper=False`, and `submit_order()` independently
re-checks the resolved base URL before every submission — including against a
client redirected via `url_override`.

Automation runs weekdays at 19:30 UTC, a single time chosen because GitHub cron
has no DST handling and that lands inside market hours year-round. Holidays and
early closes are handled at runtime via Alpaca's clock. Requires
`ALPACA_API_KEY` and `ALPACA_SECRET_KEY` as repository secrets.

---

## Limitations, stated upfront

- **No real options chain data.** Legs are priced with Black-Scholes off a flat
  VIX, so there is no volatility skew. Magnitude measured in [§7.1](docs/project_spec.md).
- **Costs are assumed, and the assumption looks optimistic.** Live fills showed
  17.7–20.3% slippage against a modelled 10%.
- **The sample is small by construction.** ~3 trades/year gives 40 post-2010
  observations. Every risk-adjusted figure should be read with that in mind.
- **Live trading is out of scope**, decided before seeing paper results and
  enforced in code rather than documented as an intention.

---

*Yousif — signal, backtest, risk, execution. Carter — market-structure review,
trade construction, write-up narrative.*
*Project context and standing rules for AI assistance: [`CLAUDE.md`](CLAUDE.md).*
