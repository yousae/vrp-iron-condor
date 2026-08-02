"""
Synthetic Black-Scholes option pricing for the Phase-3 proxy backtest.

This stands in for real historical SPX options chain data, which the
project doesn't have yet (docs/project_spec.md section 6) -- it prices
iron condor legs off VIX as a single flat implied vol rather than a real
observed chain. Config for this proxy lives in config/params.yaml under
pricing_proxy; see that file for what was confirmed and when.

Known simplifications (call these out wherever backtest numbers get
reported, not just here):
  - No volatility skew: real SPX puts trade at a higher IV than calls at
    the same delta. Pricing both sides off the same VIX number will
    UNDERSTATE the credit collected on the put wing relative to reality.
  - No dividend yield (q=0): SPX's real ~1.3-1.7% yield is ignored.
  - European exercise, cash-settled -- this part matches SPX's actual
    contract spec, so it's not a simplification.
"""

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm


def bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes price of a European option (no dividend yield).

    S: spot price. K: strike. T: time to expiry in years. r: continuously
    compounded risk-free rate (decimal). sigma: annualized IV (decimal).
    """
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

    if T <= 0 or sigma <= 0:
        # At/after expiry, or degenerate vol: price collapses to intrinsic value.
        return max(0.0, S - K) if option_type == "call" else max(0.0, K - S)

    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    if option_type == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """Black-Scholes delta. Calls in [0, 1], puts in [-1, 0].

    Delta is monotonic (decreasing) in K for both calls and puts, which
    is what makes strike_from_delta()'s root-find well-posed.
    """
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

    if T <= 0 or sigma <= 0:
        if option_type == "call":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0

    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return norm.cdf(d1) if option_type == "call" else norm.cdf(d1) - 1.0


def strike_from_delta(
    S: float, T: float, r: float, sigma: float, target_delta: float, option_type: str
) -> float:
    """Solve for the strike whose Black-Scholes delta equals target_delta.

    Puts: target_delta must be negative (e.g. -0.20). Calls: positive
    (e.g. 0.20). Brackets the root over a wide strike range and relies
    on delta's monotonicity in K for a unique solution.
    """
    def delta_gap(K: float) -> float:
        return bs_delta(S, K, T, r, sigma, option_type) - target_delta

    lo, hi = S * 0.1, S * 3.0
    return brentq(delta_gap, lo, hi)
