"""
Tests for src/backtest/pricing.py -- the Black-Scholes proxy pricing used
until real historical SPX options chain data is available.
"""

import numpy as np

from src.backtest.pricing import bs_delta, bs_price, strike_from_delta

S, T, R, SIGMA = 5000.0, 21 / 252, 0.05, 0.18


def test_put_call_parity():
    K = 4900.0
    call = bs_price(S, K, T, R, SIGMA, "call")
    put = bs_price(S, K, T, R, SIGMA, "put")

    assert np.isclose(call - put, S - K * np.exp(-R * T))


def test_delta_matches_numerical_derivative():
    K = 4900.0
    h = 0.01
    for option_type in ("call", "put"):
        numerical = (
            bs_price(S + h, K, T, R, SIGMA, option_type) - bs_price(S - h, K, T, R, SIGMA, option_type)
        ) / (2 * h)
        assert np.isclose(bs_delta(S, K, T, R, SIGMA, option_type), numerical, atol=1e-6)


def test_strike_from_delta_round_trips():
    for target, option_type in [(-0.20, "put"), (-0.05, "put"), (0.20, "call"), (0.05, "call")]:
        K = strike_from_delta(S, T, R, SIGMA, target, option_type)
        assert np.isclose(bs_delta(S, K, T, R, SIGMA, option_type), target, atol=1e-6)


def test_condor_strike_ordering():
    long_put_K = strike_from_delta(S, T, R, SIGMA, -0.05, "put")
    short_put_K = strike_from_delta(S, T, R, SIGMA, -0.20, "put")
    short_call_K = strike_from_delta(S, T, R, SIGMA, 0.20, "call")
    long_call_K = strike_from_delta(S, T, R, SIGMA, 0.05, "call")

    assert long_put_K < short_put_K < S < short_call_K < long_call_K


def test_prices_are_bounded():
    for K in [3000, 4500, 5000, 5500, 7000]:
        call = bs_price(S, K, T, R, SIGMA, "call")
        put = bs_price(S, K, T, R, SIGMA, "put")
        assert 0 <= call <= S
        assert 0 <= put <= K * np.exp(-R * T)


def test_expiry_collapses_to_intrinsic_value():
    assert bs_price(5100, 5000, 0, R, SIGMA, "call") == 100
    assert bs_price(4900, 5000, 0, R, SIGMA, "call") == 0
    assert bs_price(4900, 5000, 0, R, SIGMA, "put") == 100
    assert bs_delta(5100, 5000, 0, R, SIGMA, "call") == 1.0
    assert bs_delta(5100, 5000, 0, R, SIGMA, "put") == 0.0
