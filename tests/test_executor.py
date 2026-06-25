"""
Executor test — verifies the full pipeline in dry-run mode.
No real orders are placed. Checks that each component connects
to the others correctly and produces sensible output.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.bot.connector import connect, disconnect
from src.bot.executor import (
    get_account_info, get_open_positions, get_daily_pnl,
)
from src.bot.providers import get_provider
from src.strategy.ma_crossover import latest_signal
from src.risk.manager import evaluate
from config.mt5_config import SYMBOL, TIMEFRAME

print("=" * 55)
print("  Executor Dry-Run Test")
print("=" * 55)

# 1. Connect
print("\n[1] Connecting to MT5...")
assert connect(), "MT5 connection failed"
print("    Connected.")

# 2. Account
print("\n[2] Account info:")
acct = get_account_info()
assert acct, "Could not retrieve account info"
print(f"    Balance:  {acct['currency']} {acct['balance']:,.2f}")
print(f"    Equity:   {acct['currency']} {acct['equity']:,.2f}")
print(f"    Leverage: 1:{acct['leverage']}")

# 3. Open positions
print(f"\n[3] Open positions for {SYMBOL} (bot-managed):")
positions = get_open_positions(SYMBOL)
if positions:
    for p in positions:
        direction = "BUY" if p.type == 0 else "SELL"
        print(f"    #{p.ticket}  {direction}  {p.volume} lot(s)  "
              f"open={p.price_open}  P&L={p.profit:+.2f}")
else:
    print("    None")

# 4. Daily P&L
print(f"\n[4] Today's realised P&L for {SYMBOL}: "
      f"{acct['currency']} {get_daily_pnl(SYMBOL):+.2f}")

# 5. Fetch data + signal
print(f"\n[5] Fetching {TIMEFRAME} data and computing signal...")
provider = get_provider()
df = provider.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, bars=200)
print(f"    {len(df)} candles  |  latest close = {df['close'].iloc[-1]:.2f}")

sig = latest_signal(df)
print(f"    Signal: {sig['label']}  |  "
      f"EMA20={sig['ema_fast']}  EMA50={sig['ema_slow']}")

# 6. Risk evaluation
print(f"\n[6] Risk evaluation (signal={sig['label']}, "
      f"balance={acct['currency']} {acct['balance']:,.0f}):")

import MetaTrader5 as mt5
tick = mt5.symbol_info_tick(SYMBOL)
entry = (tick.ask if sig["signal"] == 1 else tick.bid) if tick else sig["close"]

risk = evaluate(
    df             = df,
    signal         = sig["signal"],
    entry_price    = entry,
    balance        = acct["balance"],
    open_positions = len(positions),
    daily_pnl      = get_daily_pnl(SYMBOL),
    account_currency = acct["currency"],
)

print(f"    Approved:    {risk['approved']}")
print(f"    Reason:      {risk['reason']}")
if risk["approved"]:
    print(f"    Lot size:    {risk['lot_size']}")
    print(f"    Stop-loss:   {risk['stop_loss']}")
    print(f"    Take-profit: {risk['take_profit']}")
    print(f"    Risk amount: {acct['currency']} {risk['risk_amount']}")
    print(f"    ATR:         ${risk['atr']}")
    print(f"\n    [DRY-RUN] Would send: {sig['label']} {risk['lot_size']} lot(s) "
          f"on {SYMBOL}  SL={risk['stop_loss']}  TP={risk['take_profit']}")

# 7. Disconnect
disconnect()
print("\n[7] Disconnected.")
print("\nDry-run test PASSED — no orders were placed.")
