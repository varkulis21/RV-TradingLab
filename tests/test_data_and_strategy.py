import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.bot.providers import get_provider
from src.strategy.ma_crossover import add_signals, latest_signal
from config.mt5_config import SYMBOL, DATA_SOURCE

print("=" * 50)
print("  XAUUSD Data + Strategy Test")
print(f"  Data source: {DATA_SOURCE}")
print("=" * 50)

# Fetch data
print(f"\n[1] Fetching 500 H1 candles for {SYMBOL} via {DATA_SOURCE}...")
provider = get_provider()
df = provider.fetch_ohlcv(SYMBOL, timeframe="H1", bars=500)
print(f"    Got {len(df)} candles.")
print(f"    From: {df['time'].iloc[0]}")
print(f"    To:   {df['time'].iloc[-1]}")
print(f"\n    Last 5 candles:")
print(df[["time", "open", "high", "low", "close"]].tail(5).to_string(index=False))

# Run strategy
print(f"\n[2] Running EMA 20/50 crossover strategy...")
df_signals = add_signals(df)
total_buys  = (df_signals["signal"] ==  1).sum()
total_sells = (df_signals["signal"] == -1).sum()
print(f"    BUY  signals in {len(df)} bars: {total_buys}")
print(f"    SELL signals in {len(df)} bars: {total_sells}")

# Latest signal
print(f"\n[3] Latest signal (last closed candle):")
sig = latest_signal(df)
print(f"    Time:     {sig['time']}")
print(f"    Close:    {sig['close']}")
print(f"    EMA 20:   {sig['ema_fast']}")
print(f"    EMA 50:   {sig['ema_slow']}")
print(f"    Signal:   >>> {sig['label']} <<<")

print("\nAll tests PASSED!")
