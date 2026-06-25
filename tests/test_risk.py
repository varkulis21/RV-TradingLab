import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.bot.providers import get_provider
from src.strategy.ma_crossover import add_signals
from src.risk.manager import evaluate, latest_atr, calculate_levels, check_daily_loss
from config.mt5_config import SYMBOL

print("=" * 55)
print("  Risk Management Module Test")
print("=" * 55)

# ── Load real market data ──────────────────────────────────────────
print(f"\n[1] Loading 200 H1 candles for {SYMBOL}...")
provider = get_provider()
df = provider.fetch_ohlcv(SYMBOL, timeframe="H1", bars=200)
print(f"    Loaded {len(df)} candles  (latest close: {df['close'].iloc[-1]:.2f})")

# ── ATR ───────────────────────────────────────────────────────────
atr = latest_atr(df)
print(f"\n[2] ATR(14) on last closed candle: ${atr:.2f}")
print(f"    This means gold moved ~${atr:.2f} on average per H1 candle.")

# ── Trade levels (BUY example) ────────────────────────────────────
entry = round(df["close"].iloc[-2], 2)
print(f"\n[3] Trade levels for a BUY at {entry}:")
levels_buy = calculate_levels(entry, signal=1, atr_value=atr)
print(f"    Entry:         {levels_buy['entry']}")
print(f"    Stop-loss:     {levels_buy['stop_loss']}  (-${levels_buy['stop_distance']} = 1.5 × ATR)")
print(f"    Take-profit:   {levels_buy['take_profit']}  (+${levels_buy['tp_distance']} = {levels_buy['rr_ratio']}× risk)")

print(f"\n[4] Trade levels for a SELL at {entry}:")
levels_sell = calculate_levels(entry, signal=-1, atr_value=atr)
print(f"    Entry:         {levels_sell['entry']}")
print(f"    Stop-loss:     {levels_sell['stop_loss']}  (+${levels_sell['stop_distance']})")
print(f"    Take-profit:   {levels_sell['take_profit']}  (-${levels_sell['tp_distance']})")

# ── Full evaluation: trade approved ───────────────────────────────
print(f"\n[5] Full evaluate() — BUY signal, balance £50,000:")
result = evaluate(
    df=df,
    signal=1,
    entry_price=entry,
    balance=50_000,
    open_positions=0,
    daily_pnl=0.0,
    account_currency="GBP",
    gbpusd_rate=1.27,
)
print(f"    Approved:      {result['approved']}")
print(f"    Reason:        {result['reason']}")
print(f"    Lot size:      {result['lot_size']} lots")
print(f"    Stop-loss:     {result['stop_loss']}")
print(f"    Take-profit:   {result['take_profit']}")
print(f"    Risk amount:   £{result['risk_amount']} (1% of balance)")
print(f"    ATR used:      ${result['atr']}")

# ── Guard: max positions ───────────────────────────────────────────
print(f"\n[6] Guard — already 1 position open (limit = 1):")
blocked = evaluate(df=df, signal=1, entry_price=entry, balance=50_000, open_positions=1)
print(f"    Approved: {blocked['approved']}  — {blocked['reason']}")

# ── Guard: daily loss limit ────────────────────────────────────────
print(f"\n[7] Guard — daily loss of £1,600 (3.2% of £50,000):")
blocked2 = evaluate(df=df, signal=1, entry_price=entry, balance=50_000,
                    open_positions=0, daily_pnl=-1_600)
print(f"    Approved: {blocked2['approved']}  — {blocked2['reason']}")

# ── Guard: HOLD signal ─────────────────────────────────────────────
print(f"\n[8] Guard — signal=0 (HOLD, no trade):")
blocked3 = evaluate(df=df, signal=0, entry_price=entry, balance=50_000)
print(f"    Approved: {blocked3['approved']}  — {blocked3['reason']}")

print("\nAll risk tests PASSED!")
