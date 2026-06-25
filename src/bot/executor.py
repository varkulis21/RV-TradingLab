"""
MT5 order operations — place, close, query positions and daily P&L.
All functions assume mt5.initialize() has already been called.
"""

import sys
import os
from datetime import datetime, timezone

import MetaTrader5 as mt5

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config.mt5_config import (
    MAGIC_NUMBER, MAX_SLIPPAGE_POINTS, TRADE_COMMENT,
    MIN_LOT, MAX_LOT,
)


def _filling_mode(symbol: str) -> int:
    """Return the filling mode supported by this symbol on this broker."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return mt5.ORDER_FILLING_IOC
    fm = info.filling_mode
    if fm & 1:
        return mt5.ORDER_FILLING_FOK
    if fm & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def place_market_order(
    symbol: str,
    signal: int,
    lot_size: float,
    stop_loss: float,
    take_profit: float,
) -> dict:
    """
    Send a market BUY (signal=1) or SELL (signal=-1) order.

    Returns:
        {"ok": True,  "ticket": int, "price": float}
        {"ok": False, "error": str}
    """
    if not stop_loss or not take_profit or stop_loss <= 0 or take_profit <= 0:
        return {"ok": False, "error": f"Order rejected: SL={stop_loss} TP={take_profit} must both be non-zero"}

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"ok": False, "error": f"No tick data for {symbol}"}

    order_type = mt5.ORDER_TYPE_BUY if signal == 1 else mt5.ORDER_TYPE_SELL
    price      = tick.ask              if signal == 1 else tick.bid

    lot_size = max(MIN_LOT, min(MAX_LOT, round(lot_size, 2)))

    request = {
        "action":        mt5.TRADE_ACTION_DEAL,
        "symbol":        symbol,
        "volume":        lot_size,
        "type":          order_type,
        "price":         price,
        "sl":            stop_loss,
        "tp":            take_profit,
        "deviation":     MAX_SLIPPAGE_POINTS,
        "magic":         MAGIC_NUMBER,
        "comment":       TRADE_COMMENT,
        "type_time":     mt5.ORDER_TIME_GTC,
        "type_filling":  _filling_mode(symbol),
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        code  = result.retcode if result else -1
        descr = result.comment if result else str(mt5.last_error())
        return {"ok": False, "error": f"order_send retcode={code}: {descr}"}

    return {"ok": True, "ticket": result.order, "price": result.price}


def close_position(ticket: int, symbol: str) -> dict:
    """
    Close an open position by ticket number.

    Returns:
        {"ok": True,  "price": float}
        {"ok": False, "error": str}
    """
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        return {"ok": False, "error": f"Position {ticket} not found"}

    pos  = positions[0]
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"ok": False, "error": f"No tick for {symbol}"}

    # To close a BUY we sell; to close a SELL we buy
    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price      = tick.bid             if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       pos.volume,
        "type":         close_type,
        "position":     ticket,
        "price":        price,
        "deviation":    MAX_SLIPPAGE_POINTS,
        "magic":        MAGIC_NUMBER,
        "comment":      TRADE_COMMENT + "-close",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": _filling_mode(symbol),
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        code  = result.retcode if result else -1
        descr = result.comment if result else str(mt5.last_error())
        return {"ok": False, "error": f"close retcode={code}: {descr}"}

    return {"ok": True, "price": result.price}


def get_open_positions(symbol: str) -> list:
    """
    Return a list of open positions for this symbol placed by this bot.
    Each entry is a named tuple from MT5 with: ticket, type, volume, price_open, sl, tp, profit.
    """
    positions = mt5.positions_get(symbol=symbol)
    if positions is None:
        return []
    return [p for p in positions if p.magic == MAGIC_NUMBER]


def get_daily_pnl(symbol: str) -> float:
    """
    Sum of realised profit/loss on closed trades placed by this bot today (UTC).
    Returns 0.0 if no deals found or history unavailable.
    """
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    deals = mt5.history_deals_get(today_start, datetime.now(timezone.utc))
    if deals is None:
        return 0.0
    return sum(
        d.profit for d in deals
        if d.magic == MAGIC_NUMBER and d.symbol == symbol
    )


def get_account_info() -> dict:
    """Return key account fields as a plain dict."""
    info = mt5.account_info()
    if info is None:
        return {}
    return {
        "balance":   info.balance,
        "equity":    info.equity,
        "currency":  info.currency,
        "leverage":  info.leverage,
        "margin_free": info.margin_free,
    }
