import MetaTrader5 as mt5
import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config.mt5_config import MT5_PATH, MT5_LOGIN, MT5_PASS, MT5_SERVER


def connect():
    """Open a connection to the MT5 terminal. Returns True on success.

    Note: MT5 must already be open and logged in for this to succeed quickly.
    If called with the terminal closed, mt5.initialize() may hang for 60+ seconds
    while it tries to launch the terminal process.
    """
    print("  (MT5 terminal must be open and logged in before starting the bot)")
    ok = mt5.initialize(path=MT5_PATH, login=MT5_LOGIN, password=MT5_PASS,
                        server=MT5_SERVER, timeout=30000)
    if not ok:
        err = mt5.last_error()
        print(f"MT5 connect failed: {err}")
        print("  Tip: open Pepperstone MetaTrader 5 manually, wait for the green")
        print("  connection indicator, then run: python run_bot.py --live")
        return False
    info = mt5.terminal_info()
    if not info.connected:
        print("MT5 terminal launched but not connected to broker — check internet/login")
        mt5.shutdown()
        return False
    if not info.trade_allowed:
        print("MT5 connected but AutoTrading is disabled — enable it in MT5 toolbar")
        mt5.shutdown()
        return False
    # Brief pause so the terminal finishes syncing data before the first fetch
    time.sleep(3)
    return True


def disconnect():
    mt5.shutdown()
