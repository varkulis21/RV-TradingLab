import MetaTrader5 as mt5
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config.mt5_config import MT5_PATH, MT5_LOGIN, MT5_PASS, MT5_SERVER


def connect():
    """Open a connection to the MT5 terminal. Returns True on success."""
    if not mt5.initialize(path=MT5_PATH, login=MT5_LOGIN, password=MT5_PASS,
                          server=MT5_SERVER, timeout=10000):
        print("MT5 connect failed:", mt5.last_error())
        return False
    return True


def disconnect():
    mt5.shutdown()
