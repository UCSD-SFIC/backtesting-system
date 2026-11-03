"""
Cross-sectional ranking signals and portfolio construction helpers.

Every signal takes a price matrix of shape (bars, tickers), oldest bar first,
with NaN where a ticker has no price, and returns one score per ticker using
only the rows it is given. A NaN score means the ticker is not eligible.
"""

from __future__ import annotations

import numpy as np


def momentum(prices: np.ndarray, lookback: int = 252, skip: int = 21) -> np.ndarray:
    """
    Traditional (Jegadeesh-Titman) momentum: return from `lookback` bars ago
    to `skip` bars ago. Skipping the most recent month avoids short-term
    reversal. The default is 12-1 month momentum on daily bars.
    """
    if not 0 <= skip < lookback:
        raise ValueError("skip must be at least 0 and less than lookback")
    if prices.shape[0] <= lookback:
        return np.full(prices.shape[1], np.nan)

    start = prices[-1 - lookback]
    end = prices[-1 - skip]
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(start > 0, end / start - 1, np.nan)


def high_52_week(prices: np.ndarray, window: int = 252) -> np.ndarray:
    """
    George-Hwang 52-week-high ratio: latest price divided by the highest price
    over the last `window` bars. Values near 1 are close to their high.
    """
    if prices.shape[0] < window:
        return np.full(prices.shape[1], np.nan)

    recent = prices[-window:]
    # A ticker with any gap in the window is not eligible.
    complete = ~np.isnan(recent).any(axis=0)
    with np.errstate(invalid="ignore"):
        peak = np.where(complete, recent.max(axis=0), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(peak > 0, prices[-1] / peak, np.nan)


SIGNALS = {
    "momentum": momentum,
    "high_52_week": high_52_week,
}


def top_n(scores: np.ndarray, n: int) -> np.ndarray:
    """Indices of the `n` highest finite scores, best first; ties keep ticker order."""
    eligible = np.flatnonzero(np.isfinite(scores))
    order = eligible[np.argsort(-scores[eligible], kind="stable")]
    return order[:n]


def cap_weights(weights: np.ndarray, max_weight: float) -> np.ndarray:
    """
    Clip each weight to `max_weight` and give the excess to the uncapped names
    pro rata. Whatever cannot be placed without breaking the cap stays in cash.
    """
    if not 0 < max_weight <= 1:
        raise ValueError("max_weight must be in (0, 1]")

    capped = weights.astype(float).copy()
    for _ in range(len(capped)):
        over = capped > max_weight + 1e-12
        if not over.any():
            break
        excess = float((capped[over] - max_weight).sum())
        capped[over] = max_weight
        room = (capped > 0) & (capped < max_weight - 1e-12)
        if not room.any():
            break
        capped[room] += excess * capped[room] / capped[room].sum()
    return capped
