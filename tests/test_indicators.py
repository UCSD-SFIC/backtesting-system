"""
Tests for the SMA indicator function.

These verify that sma() correctly calculates averages
and handles edge cases like not enough data.
"""

from __future__ import annotations

import pytest

from strategy.indicators import sma


def test_sma_basic_calculation():
    """sma of [10, 20, 30] with window 3 should be 20.0"""
    prices = [10.0, 20.0, 30.0]
    assert sma(prices, 3) == pytest.approx(20.0)


def test_sma_uses_last_n_prices():
    """With 5 prices and window=3, only the last 3 should be averaged."""
    prices = [1.0, 2.0, 10.0, 20.0, 30.0]
    # Should average 10 + 20 + 30 = 60 / 3 = 20.0
    assert sma(prices, 3) == pytest.approx(20.0)


def test_sma_returns_none_when_not_enough_data():
    """If we only have 2 prices but need 5, return None."""
    prices = [10.0, 20.0]
    assert sma(prices, 5) is None


def test_sma_returns_none_for_empty_list():
    """Empty price list should return None."""
    assert sma([], 3) is None


def test_sma_window_of_one():
    """Window of 1 should just return the latest price."""
    prices = [5.0, 10.0, 15.0]
    assert sma(prices, 1) == pytest.approx(15.0)


def test_sma_exact_window_size():
    """When prices length equals window exactly, average all of them."""
    prices = [10.0, 20.0, 30.0, 40.0, 50.0]
    # Average of all 5 = 150 / 5 = 30.0
    assert sma(prices, 5) == pytest.approx(30.0)