# SPX volatility risk premium iron condor

A systematic, defined-risk options-selling project: harvest the volatility risk
premium on SPX index options via IV-rank-timed iron condors, backtest it
honestly, paper trade it, and — only if it clears a pre-registered bar —
trade it live with small capital.

Full methodology, rationale, and open parameters: [`docs/project_spec.md`](docs/project_spec.md).
Supporting academic/institutional research: [`docs/research/vrp_literature_review.md`](docs/research/vrp_literature_review.md).
If you're working on this with Claude Code, it reads [`CLAUDE.md`](CLAUDE.md) automatically for project context and standing rules.

## Current phase

**Phase 2 — data pipeline.** See the spec's milestones table for what's next.

## Setup

```bash
git clone <this-repo-url>
cd vrp-iron-condor
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # then fill in your Alpaca paper API keys
```

## Project structure

```
config/           parameters from the spec (config/params.yaml)
docs/              project spec and future write-up drafts
src/data/          data ingestion (VIX/RV proxy first, options chain provider later)
src/signals/       IV rank and entry signal logic
src/risk/          position sizing (fractional Kelly, fixed-risk caps)
src/backtest/      backtest engine
src/execution/     Alpaca API integration for paper/live trading
tests/             unit tests
```

## Contributors

- Yousif — engineering (signal, backtest, execution)
- Carter — market thesis review, trade construction sanity checks, write-up narrative

## Status

Everything in `src/` is currently a scaffold — function signatures and TODOs,
not working code yet. See `config/params.yaml` for the open parameters that
need to be finalized before the backtest engine gets built out.
