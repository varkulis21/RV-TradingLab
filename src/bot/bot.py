"""
GoldBot — main execution loop.

Each H1 candle close the bot:
  1. Fetches the latest bars (yfinance or MT5 depending on DATA_SOURCE)
  2. Runs the EMA 20/50 crossover strategy to get a signal
  3. Runs risk evaluation (ATR sizing, daily loss guard, position count)
  4. Acts: opens a trade, closes the opposite, or holds
  5. Logs every decision whether DRY_RUN or live

Start with:
    python run_bot.py             # dry-run (default, no real orders)
    python run_bot.py --live      # live orders on your demo account
"""

import sys
import os
import time
import logging
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import MetaTrader5 as mt5

from src.bot.connector import connect, disconnect
from src.bot.providers import get_provider
from src.bot.executor import (
    place_market_order, close_position,
    get_open_positions, get_daily_pnl, get_account_info,
)
from src.strategy.ma_crossover import latest_signal
from src.risk.manager import evaluate
from config.mt5_config import (
    SYMBOL, TIMEFRAME, DRY_RUN, MAGIC_NUMBER,
)


# ── Logging setup ──────────────────────────────────────────────────

def _setup_logger(dry_run: bool) -> logging.Logger:
    os.makedirs("logs", exist_ok=True)
    log_file = os.path.join(
        "logs",
        f"goldbot_{datetime.now().strftime('%Y%m%d')}.log"
    )
    logger = logging.getLogger("GoldBot")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger  # already initialised (e.g. in tests)

    fmt = logging.Formatter("%(asctime)s [%(levelname)-5s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)

    mode = "DRY-RUN" if dry_run else "LIVE"
    logger.info(f"GoldBot starting — mode={mode}  symbol={SYMBOL}  tf={TIMEFRAME}")
    return logger


# ── Candle timing ──────────────────────────────────────────────────

def _seconds_until_next_candle_close(timeframe: str = "H1") -> float:
    """Return how many seconds until the next H1 (or other tf) candle closes."""
    tf_seconds = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                  "H1": 3600, "H4": 14400, "D1": 86400}
    period = tf_seconds.get(timeframe.upper(), 3600)
    now = datetime.now(timezone.utc)
    elapsed = (now.timestamp()) % period
    remaining = period - elapsed
    return remaining + 2   # +2 s buffer so the candle is fully closed


# ── Bot class ──────────────────────────────────────────────────────

class GoldBot:

    def __init__(self, dry_run: bool = True):
        self.dry_run  = dry_run
        self.log      = _setup_logger(dry_run)
        self.provider = get_provider()
        self._running = False

    # ── One tick: fetch → signal → risk → act ──────────────────────

    def _tick(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self.log.info(f"── Tick at {now} UTC ──────────────────────────")

        # 1. Account state
        acct = get_account_info()
        if not acct:
            self.log.warning("Could not retrieve account info — skipping tick")
            return

        balance   = acct["balance"]
        currency  = acct["currency"]
        positions = get_open_positions(SYMBOL)
        daily_pnl = get_daily_pnl(SYMBOL)

        self.log.info(
            f"Account: {currency} {balance:,.2f}  |  "
            f"Open positions: {len(positions)}  |  "
            f"Daily P&L: {currency} {daily_pnl:+.2f}"
        )

        # 2. Fetch bars and get signal
        try:
            df = self.provider.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, bars=200)
        except Exception as exc:
            self.log.error(f"Data fetch failed: {exc}")
            return

        sig = latest_signal(df)
        self.log.info(
            f"Signal: {sig['label']}  |  "
            f"Close: {sig['close']}  |  "
            f"EMA20: {sig['ema_fast']}  |  "
            f"EMA50: {sig['ema_slow']}"
        )

        # 3. Check if we need to close an opposing position
        if positions:
            open_pos   = positions[0]
            open_type  = open_pos.type   # 0=BUY, 1=SELL
            signal_int = sig["signal"]

            opposite = (open_type == 0 and signal_int == -1) or \
                       (open_type == 1 and signal_int == 1)

            if opposite:
                self.log.info(
                    f"Signal reversal — closing position #{open_pos.ticket} "
                    f"({'BUY' if open_type == 0 else 'SELL'})"
                )
                if not self.dry_run:
                    res = close_position(open_pos.ticket, SYMBOL)
                    if res["ok"]:
                        self.log.info(f"Position closed at {res['price']}")
                    else:
                        self.log.error(f"Close failed: {res['error']}")
                        return
                else:
                    self.log.info("[DRY-RUN] Would close position — no order sent")
                positions = []  # treat as flat for the new-entry logic below

        # 4. Risk evaluation
        tick = mt5.symbol_info_tick(SYMBOL)
        entry_price = tick.ask if sig["signal"] == 1 else tick.bid if tick else sig["close"]

        risk = evaluate(
            df            = df,
            signal        = sig["signal"],
            entry_price   = entry_price,
            balance       = balance,
            open_positions= len(positions),
            daily_pnl     = daily_pnl,
            account_currency = acct["currency"],
        )

        if not risk["approved"]:
            self.log.info(f"No trade: {risk['reason']}")
            return

        self.log.info(
            f"Trade approved — {sig['label']} {risk['lot_size']} lot(s)  |  "
            f"SL={risk['stop_loss']}  TP={risk['take_profit']}  |  "
            f"Risk={currency} {risk['risk_amount']}  ATR={risk['atr']}"
        )

        # 5. Execute
        if not self.dry_run:
            res = place_market_order(
                symbol     = SYMBOL,
                signal     = sig["signal"],
                lot_size   = risk["lot_size"],
                stop_loss  = risk["stop_loss"],
                take_profit= risk["take_profit"],
            )
            if res["ok"]:
                self.log.info(
                    f"Order placed — ticket #{res['ticket']}  "
                    f"entry={res['price']}"
                )
            else:
                self.log.error(f"Order failed: {res['error']}")
        else:
            self.log.info(
                f"[DRY-RUN] Would place {sig['label']} "
                f"{risk['lot_size']} lot(s) — no order sent"
            )

    # ── Main loop ──────────────────────────────────────────────────

    def run(self):
        self.log.info("Connecting to MT5...")
        if not connect():
            self.log.error("MT5 connection failed — cannot start bot")
            return

        self.log.info("Connected. Bot is running. Press Ctrl+C to stop.")
        self.log.info(
            "TIP: if this is a cold start, open the XAUUSD H1 chart in MT5 "
            "to pre-load history. First data fetch may take up to 2 minutes."
        )
        self._running = True

        try:
            while self._running:
                self._tick()

                wait = _seconds_until_next_candle_close(TIMEFRAME)
                next_time = datetime.now(timezone.utc) + timedelta(seconds=wait)
                self.log.info(
                    f"Next candle close: {next_time.strftime('%Y-%m-%d %H:%M:%S')} UTC  "
                    f"(sleeping {wait:.0f}s)"
                )
                time.sleep(wait)

        except KeyboardInterrupt:
            self.log.info("Shutdown requested by user (Ctrl+C)")
        finally:
            disconnect()
            self.log.info("Disconnected from MT5. Bot stopped.")

    def stop(self):
        self._running = False
