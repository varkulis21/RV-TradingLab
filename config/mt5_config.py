MT5_PATH   = r"C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe"
MT5_LOGIN  = 62129001
MT5_PASS   = "gzu^os1Cvq"
MT5_SERVER = "PepperstoneUK-Demo"
SYMBOL     = "XAUUSD"

# "yfinance" = historical data via Yahoo Finance (GC=F Gold Futures)
# "mt5"      = live bar data from the running MT5 terminal
DATA_SOURCE = "mt5"

# ── Risk management ───────────────────────────────────────────────
RISK_PER_TRADE_PCT  = 0.5   # % of balance to risk on each trade
RR_RATIO            = 2.0   # take-profit = stop distance × this
ATR_PERIOD          = 14    # lookback for ATR (volatility measure)
ATR_SL_MULTIPLIER   = 1.5   # stop-loss = ATR × this multiplier
MAX_DAILY_LOSS_PCT  = 3.0   # halt all trading if day's loss hits this %
MAX_POSITIONS       = 1     # max concurrent open trades
MIN_LOT             = 0.01  # broker minimum lot size
MAX_LOT             = 5.0   # hard cap — never exceed this regardless of math

# XAUUSD contract spec (Pepperstone standard):
#   1 lot = 100 troy oz  →  price move of $0.01 = $1.00 profit/loss per lot
XAUUSD_OZ_PER_LOT  = 100
XAUUSD_POINT_SIZE  = 0.01

# ── Execution ─────────────────────────────────────────────────────
DRY_RUN             = True    # True = log only, no real orders sent
MAGIC_NUMBER        = 20260624  # unique tag so bot only manages its own trades
MAX_SLIPPAGE_POINTS = 20      # max acceptable price slippage on entry
TRADE_COMMENT       = "GoldBot"
TIMEFRAME           = "H1"    # candle timeframe the bot trades on
