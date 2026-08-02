"""
Placeholder tests for src/signals/iv_rank.py.

Once compute_iv_rank is implemented, the most important test is a
look-ahead check: iv_rank on date T must be identical whether computed
from a series ending at T or a series ending at T + 100 (i.e. future
data must not leak backwards).
"""

import pytest


@pytest.mark.skip(reason="compute_iv_rank not implemented yet")
def test_iv_rank_no_lookahead():
    pass


@pytest.mark.skip(reason="compute_iv_rank not implemented yet")
def test_iv_rank_bounded_0_to_100():
    pass
