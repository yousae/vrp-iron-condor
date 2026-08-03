"""
Position sizing: fractional Kelly with a hard fixed-risk floor.

See docs/project_spec.md section 5. Never use full Kelly -- it assumes the
edge (win rate, payoff) is known exactly, which it never is from a backtest.
"""


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Full Kelly fraction of capital to risk, given backtested stats.

    avg_win and avg_loss are dollar magnitudes (average P&L per winning
    trade, average |P&L| per losing trade) -- e.g. straight from
    BacktestEngine.summary_stats(). f* = win_rate - (1 - win_rate) / b,
    where b = avg_win / avg_loss is the win/loss payoff ratio.

    NOTE: this replaces this function's original TODO note, which
    suggested f* = win_rate/avg_loss - (1-win_rate)/avg_win. That formula
    is only correct when avg_win/avg_loss are fractions of amount-at-risk
    (dimensionless), not raw dollar magnitudes -- with dollar inputs it
    produces a result in units of 1/dollars, not a valid capital fraction.
    Re-derived from maximizing E[log(wealth)] and verified via
    quant-verify (see commit) before use.

    Returns 0 (never negative) when the backtested edge is non-positive --
    a negative raw Kelly result means "don't trade this", not "bet against
    it", since there's no way to invert an iron condor entry signal here.
    """
    if not 0.0 <= win_rate <= 1.0:
        raise ValueError(f"win_rate must be in [0, 1], got {win_rate}")
    if avg_win <= 0 or avg_loss <= 0:
        raise ValueError("avg_win and avg_loss must both be positive magnitudes")

    payoff_ratio = avg_win / avg_loss
    f_star = win_rate - (1.0 - win_rate) / payoff_ratio
    return max(0.0, f_star)


def position_size(
    account_capital: float,
    kelly_frac: float,
    kelly_multiplier: float,
    max_risk_per_trade_pct: float,
) -> float:
    """Dollar amount to risk on a single trade.

    Applies kelly_multiplier (e.g. 0.5 for half-Kelly) to the raw Kelly
    fraction, then hard-caps the result at max_risk_per_trade_pct of
    account_capital regardless of what Kelly suggests.

    kelly_multiplier > 0.5 raises -- CLAUDE.md's standing rule ("never use
    full Kelly, half-Kelly or lower") is enforced here in code, not just
    in documentation, so a future caller can't silently violate it.
    """
    if kelly_multiplier > 0.5:
        raise ValueError(
            f"kelly_multiplier={kelly_multiplier} exceeds the half-Kelly ceiling -- "
            "never use full Kelly sizing (standing rule, see CLAUDE.md)"
        )
    if account_capital <= 0:
        raise ValueError("account_capital must be positive")

    fraction = min(kelly_frac * kelly_multiplier, max_risk_per_trade_pct)
    fraction = max(fraction, 0.0)
    return fraction * account_capital


def portfolio_heat(open_position_risks: list[float], account_capital: float) -> float:
    """Total capital currently at risk across all open positions, as a
    fraction of account capital. Compare against portfolio_heat_cap_pct
    in config/params.yaml before allowing a new position to open.

    portfolio_heat_cap_pct is still unset (null) in config/params.yaml as
    of this writing -- this function only computes the metric; enforcing
    a cap against it is the caller's job, once that value is confirmed.
    """
    if account_capital <= 0:
        raise ValueError("account_capital must be positive")
    return sum(open_position_risks) / account_capital


if __name__ == "__main__":
    win_rate, avg_win, avg_loss = 0.75, 1200.0, 2500.0
    kf = kelly_fraction(win_rate, avg_win, avg_loss)
    print(f"win_rate={win_rate}, avg_win=${avg_win}, avg_loss=${avg_loss}")
    print(f"full Kelly fraction: {kf:.4f}")

    for capital in [1000, 10000]:
        size = position_size(capital, kf, kelly_multiplier=0.5, max_risk_per_trade_pct=0.02)
        print(f"  half-Kelly position size on ${capital}: ${size:.2f}")

    heat = portfolio_heat([120.0, 85.0], account_capital=1000.0)
    print(f"portfolio heat with $120 + $85 at risk on $1000 capital: {heat:.2%}")

    print()
    print("No-edge case (win_rate below breakeven) clamps to 0, not negative:")
    print(f"  kelly_fraction(0.3, 1000, 1000) = {kelly_fraction(0.3, 1000, 1000)}")
