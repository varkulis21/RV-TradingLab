import MetaTrader5 as mt5
import pandas as pd
import subprocess
import pickle
import sys
import os
import tempfile


TIMEFRAMES = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}

_HELPER = os.path.join(os.path.dirname(__file__), "_fetch_helper.py")
_FETCH_TIMEOUT = 90   # seconds per subprocess attempt
_FETCH_RETRIES = 5    # 5 x 90s + 4 x 15s sleep = up to 7.5 min on cold start


def _fetch_subprocess(symbol: str, timeframe: str, bars: int) -> list:
    """
    Run the fetch in a separate OS process so a blocking C call in the MT5
    library cannot freeze the main bot process (the GIL is not shared across
    processes, so subprocess.communicate(timeout=...) always fires on time).
    """
    out_file = tempfile.mktemp(suffix=".pkl")
    try:
        proc = subprocess.Popen(
            [sys.executable, _HELPER, symbol, timeframe, str(bars), out_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            _, stderr = proc.communicate(timeout=_FETCH_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise RuntimeError(
                f"MT5 data fetch timed out after {_FETCH_TIMEOUT}s "
                "(terminal still syncing historical bars from broker)"
            )

        if proc.returncode != 0:
            raise RuntimeError(
                f"MT5 fetch helper exited {proc.returncode}: "
                f"{stderr.decode(errors='replace').strip()}"
            )

        with open(out_file, "rb") as f:
            return pickle.load(f)

    finally:
        if os.path.exists(out_file):
            os.unlink(out_file)


def fetch_ohlcv(symbol: str, timeframe: str = "H1", bars: int = 500) -> pd.DataFrame:
    """
    Fetch historical OHLCV candles from MT5.

    Uses a subprocess so that a cold-start MT5 sync (which blocks
    copy_rates_from_pos for minutes) cannot hang the bot process.
    Retries up to _FETCH_RETRIES times with 10s between attempts.

    Returns a DataFrame: time, open, high, low, close, volume (oldest first).
    """
    if timeframe.upper() not in TIMEFRAMES:
        raise ValueError(f"Unknown timeframe '{timeframe}'. Choose from: {list(TIMEFRAMES)}")

    last_err = None
    for attempt in range(1, _FETCH_RETRIES + 1):
        try:
            rates = _fetch_subprocess(symbol, timeframe, bars)
            break
        except RuntimeError as e:
            last_err = e
            if attempt < _FETCH_RETRIES:
                import time as _time
                _time.sleep(15)
    else:
        raise last_err

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df[["time", "open", "high", "low", "close", "tick_volume"]]
    df = df.rename(columns={"tick_volume": "volume"})
    df = df.sort_values("time").reset_index(drop=True)
    return df
