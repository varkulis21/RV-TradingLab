import math
from datetime import datetime, timezone, timedelta

import pandas as pd
import yfinance as yf

from .base import DataProvider

# MT5 symbol  →  Yahoo Finance ticker
# GC=F (Gold Futures) is used for XAUUSD: cleaner OHLCV, same USD/troy-oz price
SYMBOL_MAP = {
    "XAUUSD": "GC=F",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",
    "USDCHF": "CHF=X",
}

# MT5 timeframe string  →  yfinance interval string
INTERVAL_MAP = {
    "M1":  "1m",
    "M5":  "5m",
    "M15": "15m",
    "M30": "30m",
    "H1":  "1h",
    "H4":  "1h",   # fetched as 1h then resampled to 4h
    "D1":  "1d",
}

# Minutes per bar for each timeframe (used to compute date window)
TF_MINUTES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440,
}

# yfinance only stores intraday data for a limited window
MAX_INTRADAY_DAYS = {
    "1m": 7, "5m": 60, "15m": 60, "30m": 60, "1h": 730,
}


class YFinanceProvider(DataProvider):

    def fetch_ohlcv(self, symbol: str, timeframe: str = "H1", bars: int = 500) -> pd.DataFrame:
        tf = timeframe.upper()
        ticker = SYMBOL_MAP.get(symbol, symbol)
        interval = INTERVAL_MAP.get(tf)
        if interval is None:
            raise ValueError(f"Unsupported timeframe '{timeframe}'")

        # Calculate how many calendar days to request (gold trades ~23h/day, 5 days/week)
        tf_min = TF_MINUTES[tf]
        trading_min_per_day = 23 * 60 * (5 / 7)
        days_needed = math.ceil(bars * tf_min / trading_min_per_day) + 14  # +14 day buffer

        # Respect yfinance's intraday history limit
        if interval in MAX_INTRADAY_DAYS:
            days_needed = min(days_needed, MAX_INTRADAY_DAYS[interval])

        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=days_needed)

        raw = yf.download(
            ticker,
            start=start,
            end=end,
            interval=interval,
            auto_adjust=True,
            progress=False,
        )

        if raw is None or raw.empty:
            raise RuntimeError(f"yfinance returned no data for {ticker} ({interval})")

        # Flatten MultiIndex columns produced when downloading a single ticker
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [col[0].lower() for col in raw.columns]
        else:
            raw.columns = [c.lower() for c in raw.columns]

        df = raw.rename(columns={"vol": "volume", "volume": "volume"})[
            ["open", "high", "low", "close", "volume"]
        ].copy()
        df.index.name = "time"
        df = df.reset_index()
        df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_localize(None)

        # Resample 1h → 4h if needed
        if tf == "H4":
            df = df.set_index("time").resample("4h").agg(
                open=("open", "first"), high=("high", "max"),
                low=("low", "min"), close=("close", "last"),
                volume=("volume", "sum"),
            ).dropna().reset_index()

        df = df.sort_values("time").reset_index(drop=True)
        return df.tail(bars).reset_index(drop=True)
