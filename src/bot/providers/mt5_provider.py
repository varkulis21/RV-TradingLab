from .base import DataProvider
import pandas as pd


class MT5Provider(DataProvider):
    """
    Fetches historical OHLCV bars from the running MT5 terminal.
    Requires an active connection via src.bot.connector.connect().
    """

    def fetch_ohlcv(self, symbol: str, timeframe: str = "H1", bars: int = 500) -> pd.DataFrame:
        # Import here so MT5 package is only loaded when this provider is active
        from src.bot.data_fetcher import fetch_ohlcv as _mt5_fetch
        return _mt5_fetch(symbol, timeframe=timeframe, bars=bars)
