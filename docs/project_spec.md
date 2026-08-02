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

Decide this now, before seeing any paper-trading results, so the eventual decision can't be quietly rationalized after the fact:

- Paper trade for **[TBD: one full expiration cycle minimum, or N trades — confirm together]**.
- Advance to live capital only if the paper-traded results beat both SPY and CNDR on Sharpe **and** Sortino ratio over that window.
- If results are inconclusive or worse than benchmarks: that is a legitimate, reportable finding. The write-up does not require a live-trading phase to be a strong project — an honest null result, properly explained, is more credible than a forced live phase.

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

## Open parameters to finalize together before Phase 2

- [ ] IV rank lookback window (default: 252 days)
- [ ] IV rank entry threshold(s) to test (default: sweep 50 / 70 / 80)
- [ ] Max risk per trade (default: 2% of capital)
- [ ] Portfolio heat cap (total concurrent risk)
- [ ] Starting capital amount
- [ ] Paper-trading duration/trade-count before go/no-go decision
