"""
indicators.py — Reusable indicator functions for the backtesting system.

Each function takes in price data and returns a calculated value.
Think of these like building blocks that any strategy can plug into.

Building block covered here:
  SMA (Simple Moving Average)
    - Average price over the last N periods
    - Example usage: sma(prices, 20) → average of last 20 closing prices
"""

from __future__ import annotations


def sma(prices: list[float], window: int) -> float | None:
    """
    Simple Moving Average.

    What it does:
      Takes a list of prices and a window size, then returns the average
      of the last `window` prices. If there aren't enough prices yet,
      returns None.

    Parameters:
      prices : list of closing prices so far (oldest first, newest last)
      window : how many periods to average over

    Returns:
      The average as a float, or None if not enough data yet.

    Example:
      prices = [10, 11, 12, 13, 14]
      sma(prices, 3)  →  (12 + 13 + 14) / 3  →  13.0
      sma(prices, 10) →  None  (only 5 prices, need 10)
    """
    if len(prices) < window:
        return None

    # Grab the last `window` prices and average them
    recent_prices = prices[-window:]
    return sum(recent_prices) / window