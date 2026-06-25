from abc import ABC, abstractmethod
import pandas as pd


class DataProvider(ABC):
    """
    Common interface for historical OHLCV data.
    Implementations: YFinanceProvider (backtest), MT5Provider (live).
    To swap sources change DATA_SOURCE in config/mt5_config.py.
    """

    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str = "H1", bars: int = 500) -> pd.DataFrame:
        """
        Return a DataFrame sorted oldest→newest with columns:
            time (datetime), open, high, low, close, volume (float)
        Raise RuntimeError if data cannot be fetched.
        """
        ...
