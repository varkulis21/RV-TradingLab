"""
Technical indicators used as entry filters.
Each function accepts a DataFrame with OHLCV columns and returns
a new DataFrame with extra column(s) appended.
"""

import pandas as pd


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Relative Strength Index (0-100).
      RSI > 70  overbought — momentum may be exhausted, skip BUY
      RSI < 30  oversold   — momentum may be exhausted, skip SELL
    """
    df = df.copy()
    delta = df["close"].diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("inf"))
    df[f"rsi_{period}"] = 100 - (100 / (1 + rs))
    return df


def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Average Directional Index + DI lines.
      ADX > 25  market is trending     — crossover signals are reliable
      ADX < 20  market is ranging/flat — crossover signals are noise

    Columns added: adx_{period}, di_plus_{period}, di_minus_{period}
    """
    df = df.copy()
    high, low, close = df["high"], df["low"], df["close"]

    # True Range
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    # Raw directional movement
    up   = high - high.shift(1)
    down = low.shift(1) - low

    dm_plus  = pd.Series(0.0, index=df.index)
    dm_minus = pd.Series(0.0, index=df.index)
    dm_plus[ (up > down)   & (up   > 0)] = up  [(up > down)   & (up   > 0)]
    dm_minus[(down > up)   & (down > 0)] = down[(down > up)   & (down > 0)]

    # Wilder smoothing
    alpha   = 1 / period
    atr_w   = tr.ewm(alpha=alpha,      adjust=False).mean()
    dmp_w   = dm_plus.ewm(alpha=alpha, adjust=False).mean()
    dmm_w   = dm_minus.ewm(alpha=alpha,adjust=False).mean()

    di_plus  = 100 * dmp_w / atr_w.replace(0, float("inf"))
    di_minus = 100 * dmm_w / atr_w.replace(0, float("inf"))

    dx_denom = (di_plus + di_minus).replace(0, float("inf"))
    dx = 100 * (di_plus - di_minus).abs() / dx_denom

    df[f"adx_{period}"]      = dx.ewm(alpha=alpha, adjust=False).mean()
    df[f"di_plus_{period}"]  = di_plus
    df[f"di_minus_{period}"] = di_minus
    return df
