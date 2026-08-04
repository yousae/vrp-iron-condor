# SPX volatility risk premium iron condor

A systematic, defined-risk options-selling project: harvest the volatility risk
premium on S&P 500 index options via IV-rank-timed iron condors, backtest it
honestly, and paper trade it. Executed on **XSP** (Mini-SPX — cash-settled,
European, 1/10 the size of SPX), which is what makes the position small enough
to respect a 2%-of-capital risk cap.

**Live trading is out of scope.** At the measured trade frequency (~3/year) no
realistic paper window can produce a statistically meaningful sample, so the
paper phase validates *execution*, not profitability — see
[spec §9](docs/project_spec.md) for the power calculation behind that.

Full methodology, rationale, and open parameters: [`docs/project_spec.md`](docs/project_spec.md).
Supporting academic/institutional research: [`docs/research/vrp_literature_review.md`](docs/research/vrp_literature_review.md).
If you're working on this with Claude Code, it reads [`CLAUDE.md`](CLAUDE.md) automatically for project context and standing rules.

## Current phase

**Phase 5 — paper trading.** Phases 1–4 are built and tested (96 tests). The
runner places automated XSP iron condors on Alpaca paper; no live trading, ever
(that's [out of scope](docs/project_spec.md), and blocked in code).

## Setup

```bash
git clone <this-repo-url>
cd vrp-iron-condor
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # then fill in your Alpaca PAPER API keys
```

## Project structure

```
config/           parameters from the spec (config/params.yaml)
docs/              project spec and future write-up drafts
src/data/          data ingestion (VIX/RV proxy first, options chain provider later)
src/signals/       IV rank and entry signal logic
src/risk/          position sizing (fractional Kelly, fixed-risk caps)
src/backtest/      backtest engine
src/execution/     runner, condor tickets, expirations, trade log, Alpaca paper
tests/             unit tests
```

## Contributors

- Yousif — engineering (signal, backtest, execution)
- Carter — market thesis review, trade construction sanity checks, write-up narrative

## Running it

```bash
python3 -m src.execution.runner --check          # read-only: connectivity, paper endpoint, options level
python3 -m src.execution.runner --plumbing-test  # ONE flagged test order, bypasses the signal
python3 -m src.execution.runner                  # dry run: decide + print, submit nothing
python3 -m src.execution.runner --submit         # place the signal-gated order on Alpaca paper
streamlit run app/streamlit_app.py               # live dashboard
python3 -m pytest tests/ -q                      # 100 tests
```

Run them in that order the first time. `--check` verifies the account before
anything is placed; `--plumbing-test` verifies the execution path without
waiting months for the signal (it fires ~3x/year), and is logged as
`kind: "plumbing_test"` so it can never enter the Phase 5 statistics.

**Live trading is blocked in code**, not just by convention: `get_client()`
hardcodes the paper endpoint and rejects `paper=False`, and `submit_order()`
independently re-checks the resolved base URL before every submission.

## Status

| Stage | Module | State |
|---|---|---|
| Data | `src/data/proxy_signal.py` | Built — VIX/SPX/T-bill via yfinance |
| Signal | `src/signals/iv_rank.py` | Built — 252d trailing IV rank, look-ahead tested |
| Pricing | `src/backtest/pricing.py` | Built — Black-Scholes, put-call parity verified |
| Backtest | `src/backtest/engine.py` | Built — pre/post-2010 split, shares the live code path |
| Risk | `src/risk/sizing.py` | Built — fractional Kelly, half-Kelly ceiling enforced |
| Execution | `src/execution/` | Built — runner, tickets, expirations, trade log, Alpaca |

All parameters in `config/params.yaml` are resolved; none are TBD.

### Known limitations, stated upfront

- **No real options chain data.** Legs are priced with Black-Scholes off a flat
  VIX, so there is **no volatility skew**. Measured effect: the nominal
  "0.20 delta" short put is really ~**0.24 delta**, and its premium is
  understated ~49%. Win rates stay empirically valid (payoff is computed
  against actual SPX paths); P&L is biased *low*, so the reported numbers are
  conservative. Quantified in full, with a sensitivity run, in
  [spec §7.1](docs/project_spec.md).
- **Costs are assumed, not measured.** $0.65/contract and a 10% credit haircut
  for slippage; neither has been verified against real XSP fills yet.
- **The sample is small by construction.** ~3 trades/year means the backtest's
  post-2010 sample is 42 trades. Treat every risk-adjusted number accordingly.
