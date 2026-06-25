from .base import DataProvider
from .yfinance_provider import YFinanceProvider
from .mt5_provider import MT5Provider


def get_provider() -> DataProvider:
    """
    Return the configured data provider.
    Change DATA_SOURCE in config/mt5_config.py to swap sources:
        "yfinance"  →  YFinanceProvider  (historical backtest data)
        "mt5"       →  MT5Provider        (live MT5 terminal data)
    """
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from config.mt5_config import DATA_SOURCE

    if DATA_SOURCE == "yfinance":
        return YFinanceProvider()
    if DATA_SOURCE == "mt5":
        return MT5Provider()
    raise ValueError(f"Unknown DATA_SOURCE '{DATA_SOURCE}'. Use 'yfinance' or 'mt5'.")
