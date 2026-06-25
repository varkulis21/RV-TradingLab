"""
Risk management for GoldBot.

Responsibilities:
  1. Calculate ATR (Average True Range) — measures current volatility.
  2. Size positions so a losing trade costs exactly RISK_PER_TRADE_PCT of balance.
  3. Derive stop-loss and take-profit price levels from ATR.
  4. Guard against daily over-loss and too many open positions.

Key concept for beginners:
  ATR tells us how many dollars gold typically moves per candle.
  We place the stop-loss 1.5 × ATR away from entry so normal noise
  doesn't knock us out, then size the lot so that distance costs exactly 1%.
"""

import sys
import os
import math
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config.mt5_config import (
    RISK_PER_TRADE_PCT,
    RR_RATIO,
    ATR_PERIOD,
    ATR_SL_MULTIPLIER,
    MAX_DAILY_LOSS_PCT,
    MAX_POSITIONS,
    MIN_LOT,
    MAX_LOT,
    XAUUSD_OZ_PER_LOT,
    XAUUSD_POINT_SIZE,
)


# ── ATR ────────────────────────────────────────────────────────────

def calculate_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """
    Wilder's Average True Range.
    True Range = largest of:
        high - low
        |high - previous close|
        |low  - previous close|
    """
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Wilder's smoothing (equivalent to EMA with alpha = 1/period)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    return atr


def latest_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    """Return the ATR value on the last fully-closed candle (index -2)."""
    return float(calculate_atr(df, period).iloc[-2])


# ── Position sizing ────────────────────────────────────────────────

def calculate_lot_size(
    balance: float,
    stop_distance: float,
    account_currency: str = "GBP",
    price_usd: float = 4000.0,
    gbpusd_rate: float = 1.27,
    risk_pct: float = None,
) -> float:
    """
    Return the number of lots to trade so the stop-loss costs RISK_PER_TRADE_PCT.

    For XAUUSD (1 lot = 100 oz):
        P&L per lot per $1 move = 100 × $1 = $100
        P&L per lot per 1 point (XAUUSD_POINT_SIZE = $0.01) = $1

    Args:
        balance:          account equity in account currency
        stop_distance:    distance from entry to stop in price units (e.g. $30)
        account_currency: "GBP" or "USD"
        price_usd:        current XAUUSD price (used only if account is USD)
        gbpusd_rate:      live GBPUSD rate for GBP→USD conversion
    """
    effective_risk_pct = risk_pct if risk_pct is not None else RISK_PER_TRADE_PCT
    risk_amount = balance * (effective_risk_pct / 100)

    # Convert risk amount to USD (the denomination of XAUUSD P&L)
    if account_currency == "GBP":
        risk_amount_usd = risk_amount * gbpusd_rate
    else:
        risk_amount_usd = risk_amount

    # Dollar risk per standard lot for this stop distance
    # stop_distance is in USD (gold price units); 1 lot = 100 oz
    dollar_risk_per_lot = (stop_distance / XAUUSD_POINT_SIZE) * XAUUSD_POINT_SIZE * XAUUSD_OZ_PER_LOT
    # simplified: dollar_risk_per_lot = stop_distance * XAUUSD_OZ_PER_LOT

    if dollar_risk_per_lot <= 0:
        return MIN_LOT

    raw_lots = risk_amount_usd / dollar_risk_per_lot

    # Round down to nearest 0.01 lot, then enforce min/max
    lots = math.floor(raw_lots / 0.01) * 0.01
    lots = max(MIN_LOT, min(MAX_LOT, lots))
    return lots


# ── Trade levels ───────────────────────────────────────────────────

def calculate_levels(
    entry: float,
    signal: int,
    atr_value: float,
    sl_multiplier: float = None,
    rr_ratio: float = None,
) -> dict:
    """
    Compute stop-loss and take-profit prices for a trade.

    Args:
        entry:         proposed entry price
        signal:        1 = BUY, -1 = SELL
        atr_value:     current ATR (from latest_atr)
        sl_multiplier: override ATR_SL_MULTIPLIER from config (optional)
        rr_ratio:      override RR_RATIO from config (optional)

    Returns dict with:
        stop_loss, take_profit, stop_distance, rr_ratio
    """
    sl_mult = sl_multiplier if sl_multiplier is not None else ATR_SL_MULTIPLIER
    rr      = rr_ratio      if rr_ratio      is not None else RR_RATIO
    stop_distance = round(atr_value * sl_mult, 2)
    tp_distance   = round(stop_distance * rr, 2)

    if signal == 1:   # BUY: SL below entry, TP above
        stop_loss   = round(entry - stop_distance, 2)
        take_profit = round(entry + tp_distance, 2)
    elif signal == -1:  # SELL: SL above entry, TP below
        stop_loss   = round(entry + stop_distance, 2)
        take_profit = round(entry - tp_distance, 2)
    else:
        raise ValueError("signal must be 1 (BUY) or -1 (SELL)")

    return {
        "entry":         entry,
        "stop_loss":     stop_loss,
        "take_profit":   take_profit,
        "stop_distance": stop_distance,
        "tp_distance":   tp_distance,
        "rr_ratio":      rr,
    }


# ── Safety guards ──────────────────────────────────────────────────

def check_daily_loss(balance: float, daily_pnl: float) -> tuple[bool, str]:
    """
    Return (safe_to_trade, reason).
    Blocks trading if today's realised loss exceeds MAX_DAILY_LOSS_PCT.
    """
    if daily_pnl >= 0:
        return True, "No daily loss"

    loss_pct = abs(daily_pnl) / balance * 100
    if loss_pct >= MAX_DAILY_LOSS_PCT:
        return False, f"Daily loss {loss_pct:.1f}% exceeds limit {MAX_DAILY_LOSS_PCT}%"
    return True, f"Daily loss {loss_pct:.1f}% within limit"


def check_position_count(open_positions: int) -> tuple[bool, str]:
    """Block new trades if MAX_POSITIONS is already reached."""
    if open_positions >= MAX_POSITIONS:
        return False, f"Already {open_positions} open position(s) — limit is {MAX_POSITIONS}"
    return True, "Position count OK"


# ── Main evaluation entry point ────────────────────────────────────

def evaluate(
    df: pd.DataFrame,
    signal: int,
    entry_price: float,
    balance: float,
    open_positions: int = 0,
    daily_pnl: float = 0.0,
    account_currency: str = "GBP",
    gbpusd_rate: float = 1.27,
) -> dict:
    """
    Full risk evaluation for a potential trade.

    Returns a dict with:
        approved      : True if all guards pass and trade is sized
        reason        : why the trade was blocked (if approved=False)
        lot_size      : lots to trade
        stop_loss     : SL price
        take_profit   : TP price
        stop_distance : distance from entry to SL
        risk_amount   : estimated £/$ at risk
        atr           : ATR value used
    """
    # Guard checks first
    pos_ok, pos_msg = check_position_count(open_positions)
    if not pos_ok:
        return {"approved": False, "reason": pos_msg}

    loss_ok, loss_msg = check_daily_loss(balance, daily_pnl)
    if not loss_ok:
        return {"approved": False, "reason": loss_msg}

    if signal not in (1, -1):
        return {"approved": False, "reason": f"No actionable signal (signal={signal})"}

    # Size the trade
    atr_val = latest_atr(df)
    levels  = calculate_levels(entry_price, signal, atr_val)
    lots    = calculate_lot_size(
        balance, levels["stop_distance"],
        account_currency=account_currency,
        gbpusd_rate=gbpusd_rate,
    )
    risk_amount = round(balance * RISK_PER_TRADE_PCT / 100, 2)

    return {
        "approved":      True,
        "reason":        "All risk checks passed",
        "lot_size":      lots,
        "stop_loss":     levels["stop_loss"],
        "take_profit":   levels["take_profit"],
        "stop_distance": levels["stop_distance"],
        "tp_distance":   levels["tp_distance"],
        "rr_ratio":      RR_RATIO,
        "risk_amount":   risk_amount,
        "atr":           round(atr_val, 2),
    }
