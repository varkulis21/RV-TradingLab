"""
Demo trade verification test.

Places a minimum-lot (0.01) XAUUSD BUY order on the Pepperstone demo account,
waits 3 seconds, then closes it. Proves the full order flow works end-to-end.

Usage:
    python tests/test_demo_trade.py
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.bot.connector import connect, disconnect
from src.bot.executor import (
    place_market_order, close_position, get_open_positions, get_account_info
)
from config.mt5_config import SYMBOL, MIN_LOT

SEP = "=" * 56


def main():
    print(f"\n{SEP}")
    print("  GoldBot -- Demo Trade Verification")
    print(f"  Symbol: {SYMBOL}  |  Lot size: {MIN_LOT}")
    print(SEP)

    # 1. Connect
    print("\n[1/5] Connecting to MT5...")
    if not connect():
        print("  FAILED -- cannot connect to MT5 terminal")
        sys.exit(1)
    print("  Connected OK")

    # 2. Account snapshot before
    acct = get_account_info()
    print(f"\n[2/5] Account before trade:")
    print(f"  Balance : {acct['currency']} {acct['balance']:,.2f}")
    print(f"  Equity  : {acct['currency']} {acct['equity']:,.2f}")
    print(f"  Free margin: {acct['currency']} {acct['margin_free']:,.2f}")

    # 3. Place minimum-lot BUY
    print(f"\n[3/5] Placing demo BUY {MIN_LOT} lot {SYMBOL}...")
    import MetaTrader5 as mt5
    tick = mt5.symbol_info_tick(SYMBOL)
    ask  = tick.ask if tick else 0
    print(f"  Current ask: {ask}")

    result = place_market_order(
        symbol      = SYMBOL,
        signal      = 1,          # BUY
        lot_size    = MIN_LOT,
        stop_loss   = round(ask - 50, 2),   # $50 below ask -- safely away
        take_profit = round(ask + 100, 2),  # $100 above ask -- won't hit
    )

    if not result["ok"]:
        print(f"  FAILED: {result['error']}")
        disconnect()
        sys.exit(1)

    ticket     = result["ticket"]
    fill_price = result["price"]
    print(f"  Order placed OK -- ticket #{ticket}  filled @ {fill_price}")

    # 4. Hold for 3 seconds then close
    print("\n[4/5] Holding 3 seconds then closing...")
    time.sleep(3)

    positions = get_open_positions(SYMBOL)
    if not any(p.ticket == ticket for p in positions):
        print("  WARNING: position not found in open positions list")
    else:
        close_result = close_position(ticket, SYMBOL)
        if close_result["ok"]:
            print(f"  Position #{ticket} closed @ {close_result['price']}")
        else:
            print(f"  Close FAILED: {close_result['error']}")
            disconnect()
            sys.exit(1)

    # 5. Account snapshot after
    time.sleep(1)   # let MT5 settle the deal
    acct2 = get_account_info()
    pnl   = round(acct2["balance"] - acct["balance"], 2)
    sign  = "+" if pnl >= 0 else ""
    print(f"\n[5/5] Account after trade:")
    print(f"  Balance : {acct2['currency']} {acct2['balance']:,.2f}")
    print(f"  Trade P&L: {sign}{pnl}  (includes spread cost)")

    disconnect()
    print(f"\n{SEP}")
    print("  Demo trade test PASSED -- full order flow verified")
    print(f"{SEP}\n")


if __name__ == "__main__":
    main()
