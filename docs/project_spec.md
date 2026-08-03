# Project spec: SPX volatility risk premium iron condor strategy

**Status:** draft v1 — parameters marked TBD to be finalized before backtesting begins
**Authors:** Yousif (quant/engineering), [friend] (market thesis/practitioner review)

## 1. Thesis

Implied volatility on S&P 500 index options tends to exceed the volatility that
actually materializes. This gap — the volatility risk premium (VRP) — has been
documented across multiple independent methodologies over several decades
(Coval & Shumway 2001; Bakshi & Kapadia 2003; Carr & Wu 2009; Bondarenko
2003/2014) and is empirically visible in CBOE's own benchmark data (average
VIX of 19.3% vs. average realized volatility of 15.1%, 1990–2018).

This project tests whether a defined-risk, systematically-timed strategy for
harvesting that premium can produce a positive, risk-adjusted return after
realistic costs — and does so transparently enough to report an honest answer
either way.

**This is not a claim that the edge is large, certain, or easy.** The premium
is compensation for bearing crash risk, is negatively skewed by nature, and
has shown signs of compressing since 2010 as the trade became more crowded.
The write-up will report results in that context, not as a discovery.

## 2. Instrument and strategy structure

| Parameter | Choice | Rationale |
|---|---|---|
| Underlying | SPX | Cash-settled, European-style — no early-assignment risk, cleaner accounting than SPY |
| Structure | Iron condor | Defined risk on both sides; matches CBOE's own CNDR benchmark methodology |
| Short strikes | ~0.20 delta put, ~0.20 delta call | Matches CNDR's published methodology directly — makes our results comparable to a real institutional benchmark |
| Long strikes (wings) | ~0.05 delta put, ~0.05 delta call | Same as CNDR; caps max loss |
| Cycle | Monthly (v1) | Matches CNDR cadence; weekly is a v2 extension once v1 is validated |

## 3. Entry signal

Only open a new position when **IV rank is elevated** relative to its own
recent history — this is the piece with direct peer-reviewed support
(Malkiel, Rinaudo & Saha 2018, *Journal of Derivatives*, found VIX-conditioned
selling beat both the market and unconditional selling, 1990–2018).

- **IV rank definition:** current IV percentile rank within a trailing lookback window
- **Lookback window (TBD, default to test first): 252 trading days**
- **Entry threshold (TBD — this is a parameter to sweep, not guess once):** start by testing IV rank > 50, > 70, and > 80 as separate backtested variants, and report all three rather than picking the best in hindsight

## 4. Exit rules

- **v1 (backtest first):** hold to expiration. Simplest to backtest correctly and matches the CNDR reference methodology exactly.
- **v2 (documented refinement, test after v1 works):** close early at 50% of max profit. Practitioner sources report this improves risk-adjusted returns, but it is not yet validated in our own data — treat it as a hypothesis, not a default.
- **Standing rule regardless of version:** no rolling a losing position for a credit, no adding size to a position that's moving against you. This is the specific failure mode that broke LJM and Malachite.

## 5. Position sizing and risk management

- **Sizing method:** fractional Kelly (half-Kelly to start), computed from backtested win rate and average payoff — never full Kelly, since it assumes the edge is known exactly, which it isn't.
- **Fallback/floor rule:** regardless of what Kelly suggests, no single trade risks more than **2% of account capital (TBD — confirm together)**.
- **Portfolio heat cap:** total capital at risk across all open positions simultaneously ≤ **[TBD]%** of account.
- **Starting capital (placeholder, confirm together):** ~$1,000 combined. Small enough that a full max-loss month doesn't hurt either of you; treat the number itself as secondary to the sizing discipline around it.

## 6. Data

- **Live/paper execution and current chain data (greeks, IV):** Alpaca Trading API — commission-free, supports multi-leg options orders, and paper environment now includes SPX index options.
- **Historical options chain data for backtesting:** this is the known gap. Full historical SPX chains are the expensive part of this project. Plan:
  1. Start with a **VIX/realized-volatility proxy** to validate the IV-rank timing signal directionally before paying for anything.
  2. Evaluate a proper historical options data provider only once the signal shows enough promise on the proxy to justify the cost.
  3. Document this limitation explicitly in the write-up rather than hiding it — it's a legitimate, disclosed constraint, not a flaw to paper over.

## 7. Backtesting methodology

- **Report pre-2010 and post-2010 performance separately.** CBOE's own CNDR index was strong pre-2010 and roughly flat after — presenting a blended long-run average would misrepresent the current opportunity.
- **Model realistic transaction costs and bid-ask slippage**, not mid-price fills. Options spreads are wide; this is where paper backtests most often lie to their authors.
- **Explicitly check for look-ahead bias** — the IV rank on any given day must only use data available up to that day.
- **Pre-register the entry threshold sweep** (Section 3) before running it against the full backtest, so results aren't quietly cherry-picked after the fact.

## 8. Benchmarks

Every result gets compared against:
1. **SPY buy-and-hold** — the baseline any strategy has to beat to be worth the added complexity.
2. **CBOE CNDR index** — the real, passive, mechanically-run iron condor benchmark. This is the comparison that actually matters: it isolates whether our IV-rank *timing* adds value over just running condors every month with no signal at all.

## 9. Go/no-go criteria (pre-registered before paper trading starts)

Decide this now, before seeing any paper-trading results, so the eventual decision can't be quietly rationalized after the fact.

### 9.1 Why the original criterion was replaced (finalized 2026-08-03)

The draft criterion was *"advance to live capital only if paper results beat both SPY and CNDR on Sharpe **and** Sortino."* Once the backtest was built, we measured the strategy's actual trade frequency and found that criterion is **not reachable at any realistic paper-trading duration**. Recording the arithmetic here, because the decision to change a pre-registered criterion is exactly the kind of thing that has to be justified in the open rather than quietly edited:

| Threshold | Trades/yr (post-2010) | Months to 10 trades | Months to 30 trades |
|---|---|---|---|
| IV rank > 50 | 3.22 | 37 | 112 |
| IV rank > 70 | 1.61 | 75 | 224 |
| IV rank > 80 | 1.21 | 99 | 298 |

Three independent statistics all point the same direction:

- **Minimum backtest length.** Justifying our 3 pre-registered threshold variants requires ~4.2 years of data at the best observed Sharpe (0.72), and ~8.8 years at a more typical 0.5.
- **Trials the sample can support.** One year of paper trading statistically supports ~1.3 trials. We are testing 3.
- **Power.** Using Lo (2002), the standard error of a Sharpe estimate is `SE ≈ √((1 + SR²/2) / n)`. At 30 trades, a per-trade Sharpe of 0.20 carries a 95% CI of **[−0.16, +0.56]** — it still contains zero. Roughly 100 trades are needed before the interval excludes zero, which is **~62 years** at the >70 trade rate.

A gate that cannot be satisfied is worse than no gate: it guarantees the eventual decision gets made on unstated grounds. So the paper phase is reframed from a *statistical* test to an *operational* one. **This does not lower the bar for claiming an edge — it removes a claim we were never going to be able to make, and says so.**

### 9.2 The criteria

**Sample required before any go/no-go decision:** at least **5 trades** and at least **6 expiration cycles** (whichever comes later; ~19 months expected).

Paper trade the **loosest threshold (>50) only**, tagging each trade with its entry IV rank. The thresholds are nested — every >80 trade is also a >70 and a >50 — so a single stream evaluates all three variants at 3x the data rate of running three separate books.

**What the paper phase actually tests (all must pass):**

1. **Execution works end-to-end.** 4-leg orders submit, fill, and settle without manual intervention.
2. **Fills match the model.** Median realized slippage stays within the modeled 10% haircut on net credit.
3. **Signal fidelity.** The live signal fires on the dates the backtest says it would, given the same data.
4. **Sim-to-live reconciliation.** Each closed trade's realized P&L matches what the pricing model predicts given the actual settlement price. *(This is the step most often skipped; persistent divergence means the simulator is wrong, which would make every backtest run through it suspect.)*

**Disqualifying conditions — any one of these stops the live phase regardless of P&L:**

- Median realized slippage exceeds **20% of gross credit** (2x the modeled assumption). This would materially invalidate the backtest's cost model, not just reduce returns.
- The live signal diverges from what the backtest would have generated.
- Settlement or P&L reconciliation fails.

**On benchmarks:** SPY and CNDR comparisons are still computed and **reported** in the write-up for context. They are no longer a pass/fail gate, because the sample cannot support the comparison. The write-up must state this limitation directly rather than presenting an underpowered comparison as if it were evidence.

**If the operational criteria fail, or the results are inconclusive:** that is a legitimate, reportable finding. The write-up does not require a live-trading phase to be a strong project — an honest null result, properly explained, is more credible than a forced live phase.

## 10. Roles

- **Yousif:** signal definition and calibration, backtest engine, data pipeline, execution code, risk framework implementation.
- **[Friend]:** trade construction review, market-structure sanity checks (does the thesis make economic sense, not just curve-fit sense), practitioner framing for the write-up's narrative sections.
- **Joint:** parameter decisions marked TBD above, go/no-go criteria, final write-up.

## 11. Known risks and limitations (for the write-up, stated upfront)

- The VRP is compensation for crash risk — it is expected to lose money in exactly the environments where losing money hurts most.
- Every real-world blow-up in this space (LJM/Volmageddon 2018, Allianz Structured Alpha 2020, Malachite 2020) shared the same root causes: leverage, undefined or under-hedged tail risk, and oversizing relative to capital. Our structure is specifically designed to avoid all three — unlevered, defined-risk wings, small fractional-Kelly sizing — and the write-up should state this explicitly as the design rationale, not just assert safety.
- A single semester of live trading will not produce a statistically meaningful sample. The write-up will say this directly rather than presenting a P&L figure as proof of anything.

## 12. Milestones

| Phase | Deliverable |
|---|---|
| 1 | This spec, finalized (resolve all TBDs) |
| 2 | Data pipeline (proxy signal first, chain data provider decision second) |
| 3 | Backtest engine |
| 4 | Signal calibration + benchmark comparison (pre-2010 / post-2010 split) |
| 5 | Paper trading (pre-registered duration and criteria) |
| 6 | Go/no-go decision |
| 7 | Live trading (small capital) — only if Phase 6 passes |
| 8 | Write-up |

## References

- Bakshi, G. & Kapadia, N. (2003). "Delta-Hedged Gains and the Negative Market Volatility Risk Premium." *Review of Financial Studies* 16(2).
- Coval, J. & Shumway, T. (2001). "Expected Option Returns." *Journal of Finance* 56(3).
- Carr, P. & Wu, L. (2009). "Variance Risk Premiums." *Review of Financial Studies* 22(3).
- Bondarenko, O. (2003/2014). "Why Are Put Options So Expensive?" *Quarterly Journal of Finance* 4(1).
- Malkiel, B., Rinaudo, A. & Saha, S. (2018). "Option Writing: Using VIX to Improve Returns." *Journal of Derivatives* 26(2).
- Black, K. & Szado, E. (2016). "Performance Analysis of CBOE S&P 500 Options-Selling Indices." CBOE-commissioned study.
- CBOE. "S&P 500 Iron Condor Index (CNDR) Methodology."
- AQR Capital Management (2018). "Understanding the Volatility Risk Premium."

---

## Open parameters — all resolved as of 2026-08-03

- [x] IV rank lookback window — **252 days**
- [x] IV rank entry threshold(s) to test — **sweep 50 / 70 / 80**, pre-registered, reported in full
- [x] Max risk per trade — **2% of capital**
- [x] Portfolio heat cap (total concurrent risk) — **6%** (~3x the per-trade cap)
- [x] Starting capital amount — **$1,000** (small enough that a full max-loss month doesn't hurt either of us)
- [x] Paper-trading duration/trade-count before go/no-go — **5 trades and 6 cycles minimum**, against operational criteria rather than a Sharpe comparison (see §9)

Parameters added after the spec's first draft, as the build surfaced the need for them:

- [x] Proxy pricing method — Black-Scholes off flat VIX, `^IRX` risk-free rate, 21-trading-day DTE (see §6; no real chain data yet)
- [x] Transaction costs — **$0.65/contract** (4 legs) + **10%** haircut on net credit for bid-ask slippage
- [x] Kelly multiplier — **0.5** (half-Kelly ceiling, enforced in code in `src/risk/sizing.py`)
