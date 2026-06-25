import pandas as pd


# Strategy parameters
FAST  = 20    # fast EMA period
SLOW  = 50    # slow EMA period
TREND = 200   # long-term trend EMA — price above = bullish bias, below = bearish


def add_signals(df: pd.DataFrame, fast: int = FAST, slow: int = SLOW) -> pd.DataFrame:
    """
    Add EMA columns and a trade signal to the DataFrame.

    Args:
        fast: fast EMA period (default 20)
        slow: slow EMA period (default 50)

    Columns added:
        ema_fast  : EMA(fast)
        ema_slow  : EMA(slow)
        ema_trend : EMA(200) — long-term trend direction
        signal    : 1 (BUY crossover), -1 (SELL crossover), 0 (no change)

    The trend filter is NOT applied here; the backtest engine and live bot
    decide whether to respect it at the point of entry.
    """
    df = df.copy()

    df["ema_fast"]  = df["close"].ewm(span=fast,  adjust=False).mean()
    df["ema_slow"]  = df["close"].ewm(span=slow,  adjust=False).mean()
    df["ema_trend"] = df["close"].ewm(span=TREND, adjust=False).mean()

    # 1 when fast is above slow, -1 when below
    df["position"] = (df["ema_fast"] > df["ema_slow"]).astype(int) * 2 - 1

    # Signal fires only on the candle where the crossover actually happens
    df["signal"] = df["position"].diff().apply(
        lambda x: 1 if x > 0 else (-1 if x < 0 else 0)
    )

    return df


def latest_signal(df: pd.DataFrame, fast: int = FAST, slow: int = SLOW) -> dict:
    """
    Return the signal on the most recent fully-closed candle.

    Returns a dict with:
        signal    : 1 (buy), -1 (sell), or 0 (hold)
        label     : "BUY", "SELL", or "HOLD"
        time      : candle timestamp
        close     : closing price
        ema_fast  : fast EMA value
        ema_slow  : slow EMA value
        ema_trend : EMA(200) value — compare to close to judge trend direction
    """
    df = add_signals(df, fast=fast, slow=slow)
    # index -2 = last fully-closed candle (-1 is still forming)
    row = df.iloc[-2]
    signal = int(row["signal"])
    return {
        "signal":    signal,
        "label":     {1: "BUY", -1: "SELL", 0: "HOLD"}[signal],
        "time":      row["time"],
        "close":     round(row["close"], 2),
        "ema_fast":  round(row["ema_fast"], 2),
        "ema_slow":  round(row["ema_slow"], 2),
        "ema_trend": round(row["ema_trend"], 2),
    }
