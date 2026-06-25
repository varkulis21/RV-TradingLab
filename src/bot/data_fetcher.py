import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime


# Timeframe shortcuts — maps a plain string to the MT5 constant
TIMEFRAMES = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}


def fetch_ohlcv(symbol: str, timeframe: str = "H1", bars: int = 500) -> pd.DataFrame:
    """
    Fetch historical OHLCV candles from MT5.

    Returns a DataFrame with columns:
        time, open, high, low, close, tick_volume
    Rows are sorted oldest → newest.
    """
    tf = TIMEFRAMES.get(timeframe.upper())
    if tf is None:
        raise ValueError(f"Unknown timeframe '{timeframe}'. Choose from: {list(TIMEFRAMES)}")

    # Ensure the symbol is visible in Market Watch so MT5 streams its data
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"Could not select symbol '{symbol}': {mt5.last_error()}")

    rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No data returned for {symbol} {timeframe}: {mt5.last_error()}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df[["time", "open", "high", "low", "close", "tick_volume"]]
    df = df.rename(columns={"tick_volume": "volume"})
    df = df.sort_values("time").reset_index(drop=True)
    return df
