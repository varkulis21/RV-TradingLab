import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import MetaTrader5 as mt5
from config.mt5_config import MT5_PATH, MT5_LOGIN, MT5_PASS, MT5_SERVER, SYMBOL

print("MetaTrader5 package version:", mt5.__version__)

# Step 1: Connect to the MT5 terminal
print("\nConnecting to MetaTrader 5...")
if not mt5.initialize(path=MT5_PATH, login=MT5_LOGIN, password=MT5_PASS, server=MT5_SERVER, timeout=10000):
    print("FAILED to connect:", mt5.last_error())
    quit()

print("Connected successfully!")

# Step 2: Terminal info
info = mt5.terminal_info()
print(f"  Broker:        {info.company}")
print(f"  Build:         {info.build}")
print(f"  Connected:     {info.connected}")
print(f"  AutoTrading:   {info.trade_allowed}")

# Step 3: Account info
account = mt5.account_info()
if account:
    print(f"\nAccount Info:")
    print(f"  Login:    {account.login}")
    print(f"  Server:   {account.server}")
    print(f"  Balance:  {account.currency} {account.balance:,.2f}")
    print(f"  Leverage: 1:{account.leverage}")
else:
    print("\nCould not get account info:", mt5.last_error())

# Step 4: Check XAUUSD is available and get live price
symbol_info = mt5.symbol_info(SYMBOL)
if symbol_info:
    print(f"\n{SYMBOL} Live Price:")
    print(f"  Bid:    {symbol_info.bid}")
    print(f"  Ask:    {symbol_info.ask}")
    print(f"  Spread: {symbol_info.spread} points")
else:
    print(f"\n{SYMBOL} not found:", mt5.last_error())

# Step 5: Clean disconnect
mt5.shutdown()
print("\nDisconnected. Connection test PASSED!")
