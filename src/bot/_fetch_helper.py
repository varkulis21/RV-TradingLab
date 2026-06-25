"""
Standalone MT5 data-fetch helper.

Called as a subprocess by data_fetcher.py so that a blocking
copy_rates_from_pos() call cannot freeze the main bot process.

Usage (internal — do not call directly):
    python _fetch_helper.py <symbol> <timeframe> <bars> <output_pickle>
"""

import sys
import os
import pickle

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import MetaTrader5 as mt5
from config.mt5_config import MT5_PATH, MT5_LOGIN, MT5_PASS, MT5_SERVER

TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

def main():
    symbol, tf_str, bars_str, out_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    bars = int(bars_str)
    tf   = TIMEFRAMES[tf_str.upper()]

    if not mt5.initialize(path=MT5_PATH, login=MT5_LOGIN,
                          password=MT5_PASS, server=MT5_SERVER, timeout=15000):
        print(f"HELPER_ERROR: mt5.initialize failed: {mt5.last_error()}", file=sys.stderr)
        sys.exit(1)

    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        print(f"HELPER_ERROR: no data for {symbol} {tf_str}", file=sys.stderr)
        sys.exit(2)

    with open(out_path, "wb") as f:
        pickle.dump(rates, f)

if __name__ == "__main__":
    main()
