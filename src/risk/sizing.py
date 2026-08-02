"""
Position sizing: fractional Kelly with a hard fixed-risk floor.

See docs/project_spec.md section 5. Never use full Kelly -- it assumes the
edge (win rate, payoff) is known exactly, which it never is from a backtest.
"""


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Full Kelly fraction of capital to risk, given backtested stats.

    avg_loss should be a positive number (magnitude of the average loss).

    TODO: implement classic Kelly formula: f* = (win_rate / avg_loss) -
    ((1 - win_rate) / avg_win), or the equivalent b/p/q form. Cross-check
    against quant-verify skill before trusting this for real sizing.
    """
    raise NotImplementedError


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

    TODO: implement min(kelly_frac * kelly_multiplier, max_risk_per_trade_pct) * account_capital
    """
    raise NotImplementedError


def portfolio_heat(open_position_risks: list[float], account_capital: float) -> float:
    """Total capital currently at risk across all open positions, as a
    fraction of account capital. Compare against portfolio_heat_cap_pct
    in config/params.yaml before allowing a new position to open.

    TODO: implement as sum(open_position_risks) / account_capital
    """
    raise NotImplementedError
