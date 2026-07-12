# indicators.py

import numpy as np
import pandas as pd

def rma(series, period):
    """Wilder's smoothing (RMA) – matches Pine's ta.atr."""
    alpha = 1.0 / period
    return series.ewm(alpha=alpha, adjust=False).mean()

def atr(high, low, close, period):
    tr = np.maximum(high - low, np.maximum(abs(high - close.shift()), abs(low - close.shift())))
    return rma(tr, period)

def rsi(close, period):
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def ema(close, period):
    return close.ewm(span=period, adjust=False).mean()

def lr_channel(close, length):
    """
    Returns (slope, intercept, stdev, R) for the last 'length' bars.
    Matches Pine's lrCalc() exactly.
    """
    if len(close) < length:
        return None, None, None, None
    y = close[-length:].values
    x = np.arange(length)
    n = length

    sx = x.sum()
    sy = y.sum()
    sxy = (x * y).sum()
    sx2 = (x * x).sum()
    sy2 = (y * y).sum()

    denom = n * sx2 - sx * sx
    if denom == 0:
        return None, None, None, None

    m = (n * sxy - sx * sy) / denom
    b = (sy - m * sx) / n

    yhat = m * x + b
    sd = np.sqrt(((y - yhat) ** 2).mean())

    # Pearson R
    r_num = n * sxy - sx * sy
    r_den = np.sqrt((n * sx2 - sx * sx) * (n * sy2 - sy * sy))
    r = r_num / r_den if r_den != 0 else 0.0

    return m, b, sd, r

def find_pivots(high, low, left, right):
    """
    Returns two arrays: (pivot_high_prices, pivot_high_indices, pivot_low_prices, pivot_low_indices)
    Matches Pine's ta.pivothigh() and ta.pivotlow().
    """
    high_vals = []
    high_idx = []
    low_vals = []
    low_idx = []

    n = len(high)
    for i in range(left, n - right):
        # High pivot
        is_high = True
        for j in range(1, left + 1):
            if high[i - j] >= high[i]:
                is_high = False
                break
        if is_high:
            for j in range(1, right + 1):
                if high[i + j] >= high[i]:
                    is_high = False
                    break
        if is_high:
            high_vals.append(high[i])
            high_idx.append(i)

        # Low pivot
        is_low = True
        for j in range(1, left + 1):
            if low[i - j] <= low[i]:
                is_low = False
                break
        if is_low:
            for j in range(1, right + 1):
                if low[i + j] <= low[i]:
                    is_low = False
                    break
        if is_low:
            low_vals.append(low[i])
            low_idx.append(i)

    return high_vals, high_idx, low_vals, low_idx