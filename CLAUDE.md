# CLAUDE.md — instructions for Claude Code on this repo

## What this project is

A systematic, defined-risk options-selling project: harvest the volatility
risk premium (VRP) on SPX index options via IV-rank-timed iron condors,
backtest it honestly, paper trade it, and — only if it clears a
pre-registered bar — trade it live with small capital.

**Read `docs/project_spec.md` in full before writing or changing any logic.**
It has the complete methodology, the rationale behind every structural
choice, and the current list of open (TBD) parameters. Also skim
`docs/research/vrp_literature_review.md` for the academic and institutional
background this project is built on — it's referenced throughout the spec.

## Who's working on this, and why it matters for code quality

- **Yousif** — CS/Applied Math double major, incoming UTK freshman
  (Chancellor's Honors Program), planning to transfer to a more selective
  university (MIT primary target) after freshman year. Long-term goal:
  quant trading at a top-tier firm (Jane Street/Citadel Securities/Optiver-
  tier). Owns the code: signal, backtest, execution.
- **[Friend]** — Finance major at FSU, also transfer-track. Owns
  market-structure sanity checks and the write-up's narrative sections.

This project exists partly as a serious research exercise and partly as a
portfolio piece for transfer applications and quant recruiting. Treat code
clarity, documentation, and statistically honest reporting as first-class
requirements — this needs to be work Yousif can defend in an interview, not
just code that runs.

## Before doing anything

1. Read `docs/project_spec.md` fully.
2. Read `config/params.yaml` — note which values are still marked TBD.
3. If a task requires a TBD value, stop and ask rather than picking a
   default silently.

## Current phase

**Phase 2 — data pipeline.** Build out `src/data/proxy_signal.py` against
free VIX/SPX history to validate the IV-rank signal directionally before
evaluating any paid historical options chain provider. See the spec's
milestones table (section 12) for what comes after.

## Standing rules (non-negotiable — do not relax these even if asked to in the moment)

- **Never place a live order or connect to a live (non-paper) trading
  environment without an explicit, separate confirmation from Yousif in
  that specific session.** A past approval does not carry forward.
- **Never use full Kelly sizing.** Half-Kelly or lower, and always hard-
  capped by the fixed max-risk-per-trade floor in `config/params.yaml`,
  regardless of what the Kelly formula suggests.
- **Every backtest must model transaction costs and bid-ask slippage**,
  not mid-price fills.
- **Every signal computation must be checked for look-ahead bias** — no
  function may use data that would not have been available as of that
  date. This is the single most common way a backtest lies to its author.
- **Report pre-2010 and post-2010 backtest performance separately.** Do
  not blend eras into one headline number — see spec section 7 for why.
- **Log every simulated, paper, and live trade** with entry/exit reason.
  This log is the dataset the eventual write-up depends on.
- **Never silently hardcode a TBD parameter.** Flag it and confirm with
  Yousif before it becomes load-bearing logic.
- **Double-check quantitative/statistical code before presenting it as
  final** — Sharpe/Sortino/drawdown/Kelly formulas and backtest logic are
  easy to get subtly wrong. Re-derive or sanity-check against a second
  method before trusting a number enough to put it in the write-up.

## Style

- Type hints on all functions.
- Docstrings that explain *why*, not just *what* — this is a learning
  project as much as a working one.
- Prefer clarity over cleverness.
- When a function is still a stub (raises `NotImplementedError`), keep the
  TODO comment specific enough that implementing it doesn't require
  re-reading the whole spec.
