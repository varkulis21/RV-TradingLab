"""
Backtest engine for GoldBot.

Core rules:
  - Enter at the close of the signal candle (or next candle with --confirmation).
  - Exits: SL / trailing-stop hit, TP hit (unless removed), reversal crossover.
  - When SL and TP both breach on the same candle, SL is assumed first.
  - One open position at a time.

StrategyConfig controls all strategy knobs including the new exit modes:
  use_trailing_stop  : trail the SL behind the best price seen since entry
  use_breakeven_stop : move SL to entry once price moves 1R in profit
  remove_fixed_tp    : disable fixed take-profit; rely on trailing/reversal exit
  use_confirmation   : require a second confirming bar before entering
  risk_pct           : % of balance to risk per trade (overrides config default)
"""

import sys
import os
import math
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.bot.providers import get_provider
from src.strategy.ma_crossover import add_signals
from src.strategy.indicators import add_rsi, add_adx
from src.risk.manager import calculate_atr, calculate_levels, calculate_lot_size
from config.mt5_config import SYMBOL, XAUUSD_OZ_PER_LOT, ATR_PERIOD


# ---------------------------------------------------------------------------
# Strategy configuration
# ---------------------------------------------------------------------------

@dataclass
class StrategyConfig:
    """All strategy knobs in one place. Defaults = current best baseline."""

    # EMA crossover
    ema_fast: int   = 5
    ema_slow: int   = 20

    # Trend filter: only trade in direction of EMA(200)
    use_trend_filter: bool = True

    # RSI confirmation
    use_rsi:    bool  = False
    rsi_period: int   = 14
    rsi_ob:     float = 70.0
    rsi_os:     float = 30.0

    # ADX strength filter
    use_adx:    bool  = False
    adx_period: int   = 14
    adx_min:    float = 25.0

    # ATR volatility filter
    use_atr_filter: bool  = True
    atr_min_pct:    float = 0.30
    atr_max_pct:    float = 3.00

    # Session filter (UTC hours, H1 only)
    use_session_filter: bool = False
    session_start_utc:  int  = 7
    session_end_utc:    int  = 21

    # --- Exit management ---

    # Trailing stop: trail the SL at stop_distance × trail_atr_mult behind
    # the best high (BUY) or best low (SELL) seen since entry.
    use_trailing_stop: bool  = False
    trail_atr_mult:    float = 1.0   # multiplier on the initial stop_distance

    # Breakeven stop: once price moves breakeven_r × stop_distance in profit,
    # advance the SL to the entry price so the trade cannot end in a full loss.
    use_breakeven_stop: bool  = False
    breakeven_r:        float = 1.0

    # Remove the fixed take-profit ceiling so the trailing stop (or a reversal
    # crossover) is the only exit. Only useful when use_trailing_stop=True.
    remove_fixed_tp: bool = False

    # Two-bar confirmation: only enter if the EMA position (fast above/below slow)
    # still holds one full bar after the crossover fired.
    use_confirmation: bool = False

    # Risk management
    atr_sl_mult: float = 1.5
    rr_ratio:    float = 2.0
    risk_pct:    float = 1.0   # % of account to risk per trade

    def label(self) -> str:
        parts = [f"EMA {self.ema_fast}/{self.ema_slow}"]
        if self.use_trend_filter:    parts.append("EMA200")
        if self.use_rsi:             parts.append(f"RSI{self.rsi_period}")
        if self.use_adx:             parts.append(f"ADX>{self.adx_min:.0f}")
        if self.use_atr_filter:      parts.append("ATRvol")
        if self.use_session_filter:  parts.append(f"Sess{self.session_start_utc}-{self.session_end_utc}")
        if self.use_confirmation:    parts.append("Confirm")
        if self.use_trailing_stop:   parts.append(f"Trail{self.trail_atr_mult}x")
        if self.use_breakeven_stop:  parts.append(f"BE@{self.breakeven_r}R")
        if self.remove_fixed_tp:     parts.append("NoTP")
        parts.append(f"SL={self.atr_sl_mult}x")
        if not self.remove_fixed_tp: parts.append(f"RR={self.rr_ratio}")
        parts.append(f"Risk={self.risk_pct}%")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

def run_backtest(
    df: pd.DataFrame = None,
    cfg: StrategyConfig = None,
    symbol: str = SYMBOL,
    timeframe: str = "D1",
    bars: int = 3000,
    initial_balance_usd: float = 10_000.0,
    verbose: bool = False,
) -> dict:
    """
    Simulate the strategy over historical data.

    Args:
        df:          Pre-fetched OHLCV DataFrame. If None, fetches from provider.
        cfg:         StrategyConfig. Defaults to current optimised baseline.
        initial_balance_usd: Starting capital in USD.
        verbose:     Print every trade entry/exit.

    Returns dict: trades, metrics, final_balance
    """
    if cfg is None:
        cfg = StrategyConfig()

    if df is None:
        provider = get_provider()
        df = provider.fetch_ohlcv(symbol, timeframe=timeframe, bars=bars)

    # Compute EMA signals and indicators
    df = add_signals(df, fast=cfg.ema_fast, slow=cfg.ema_slow).reset_index(drop=True)
    if cfg.use_rsi:
        df = add_rsi(df, period=cfg.rsi_period)
    if cfg.use_adx:
        df = add_adx(df, period=cfg.adx_period)

    atr_series = calculate_atr(df, period=ATR_PERIOD)
    WARMUP = max(200, ATR_PERIOD * 2)

    balance    = initial_balance_usd
    open_trade = None
    trades     = []

    for i in range(WARMUP, len(df)):
        row     = df.iloc[i]
        atr_val = float(atr_series.iloc[i])

        # -- Manage open trade --------------------------------------------
        if open_trade is not None:
            direction  = open_trade["direction"]
            init_sl    = open_trade["stop_loss"]
            tp         = open_trade["take_profit"]
            stop_dist  = open_trade["stop_distance"]
            entry      = open_trade["entry"]

            # Update trailing / breakeven stop
            effective_sl = init_sl
            if cfg.use_trailing_stop or cfg.use_breakeven_stop:
                trail_sl = open_trade.get("trail_stop", init_sl)

                if direction == 1:   # BUY
                    best = max(open_trade.get("best_price", entry), float(row["high"]))
                    open_trade["best_price"] = best

                    if cfg.use_trailing_stop:
                        trail_sl = max(trail_sl, best - stop_dist * cfg.trail_atr_mult)

                    if cfg.use_breakeven_stop and not open_trade.get("be_active"):
                        if best >= entry + cfg.breakeven_r * stop_dist:
                            trail_sl = max(trail_sl, entry)
                            open_trade["be_active"] = True

                else:                # SELL
                    best = min(open_trade.get("best_price", entry), float(row["low"]))
                    open_trade["best_price"] = best

                    if cfg.use_trailing_stop:
                        trail_sl = min(trail_sl, best + stop_dist * cfg.trail_atr_mult)

                    if cfg.use_breakeven_stop and not open_trade.get("be_active"):
                        if best <= entry - cfg.breakeven_r * stop_dist:
                            trail_sl = min(trail_sl, entry)
                            open_trade["be_active"] = True

                open_trade["trail_stop"] = trail_sl
                effective_sl = trail_sl

            # Check exits
            exit_price  = None
            exit_reason = None

            if direction == 1:
                if float(row["low"]) <= effective_sl:
                    exit_price  = effective_sl
                    exit_reason = "TRAIL" if effective_sl > init_sl else "SL"
                elif not cfg.remove_fixed_tp and float(row["high"]) >= tp:
                    exit_price, exit_reason = tp, "TP"
                elif int(row["signal"]) == -1:
                    exit_price, exit_reason = float(row["close"]), "REVERSAL"
            else:
                if float(row["high"]) >= effective_sl:
                    exit_price  = effective_sl
                    exit_reason = "TRAIL" if effective_sl < init_sl else "SL"
                elif not cfg.remove_fixed_tp and float(row["low"]) <= tp:
                    exit_price, exit_reason = tp, "TP"
                elif int(row["signal"]) == 1:
                    exit_price, exit_reason = float(row["close"]), "REVERSAL"

            if exit_price is not None:
                pnl = (direction
                       * (exit_price - entry)
                       * open_trade["lots"]
                       * XAUUSD_OZ_PER_LOT)
                balance += pnl
                trades.append({
                    **open_trade,
                    "exit_price":  round(exit_price, 2),
                    "exit_time":   row["time"],
                    "exit_reason": exit_reason,
                    "pnl_usd":     round(pnl, 2),
                    "balance":     round(balance, 2),
                })
                if verbose:
                    _print_close(trades[-1])
                open_trade = None

        # -- Determine effective signal (with optional confirmation) -------
        if cfg.use_confirmation and i > 0:
            prev_sig     = int(df.iloc[i - 1]["signal"])
            curr_pos     = int(row["position"])   # 1 = fast above slow
            if   prev_sig ==  1 and curr_pos ==  1:  eff_sig =  1
            elif prev_sig == -1 and curr_pos == -1:   eff_sig = -1
            else:                                      eff_sig =  0
        else:
            eff_sig = int(row["signal"])

        # -- Open new trade ------------------------------------------------
        if open_trade is None and eff_sig in (1, -1):
            signal = eff_sig

            # Entry filters
            if cfg.use_trend_filter:
                if signal ==  1 and float(row["close"]) < float(row["ema_trend"]): continue
                if signal == -1 and float(row["close"]) > float(row["ema_trend"]): continue

            if cfg.use_rsi:
                rsi_val = float(row.get(f"rsi_{cfg.rsi_period}", 50.0))
                if signal ==  1 and rsi_val >= cfg.rsi_ob: continue
                if signal == -1 and rsi_val <= cfg.rsi_os: continue

            if cfg.use_adx:
                if float(row.get(f"adx_{cfg.adx_period}", 99.0)) < cfg.adx_min: continue

            if cfg.use_atr_filter:
                atr_pct = atr_val / float(row["close"]) * 100
                if atr_pct < cfg.atr_min_pct: continue
                if atr_pct > cfg.atr_max_pct: continue

            if cfg.use_session_filter:
                hour = pd.Timestamp(row["time"]).hour
                if not (cfg.session_start_utc <= hour < cfg.session_end_utc): continue

            entry  = float(row["close"])
            levels = calculate_levels(entry, signal, atr_val,
                                      sl_multiplier=cfg.atr_sl_mult,
                                      rr_ratio=cfg.rr_ratio)
            lots   = calculate_lot_size(
                balance=balance,
                stop_distance=levels["stop_distance"],
                account_currency="USD",
                risk_pct=cfg.risk_pct,
            )
            open_trade = {
                "direction":     signal,
                "entry":         entry,
                "entry_time":    row["time"],
                "stop_loss":     levels["stop_loss"],
                "take_profit":   levels["take_profit"],
                "stop_distance": levels["stop_distance"],
                "lots":          lots,
                "atr":           round(atr_val, 2),
                "trail_stop":    levels["stop_loss"],   # initialised to initial SL
                "best_price":    entry,
                "be_active":     False,
            }
            if verbose:
                lbl = "BUY" if signal == 1 else "SELL"
                print(f"  OPEN  {lbl} @ {entry:.2f}  "
                      f"SL={levels['stop_loss']:.2f}  TP={levels['take_profit']:.2f}  "
                      f"lots={lots}  atr=${atr_val:.2f}")

    # Close any position still open at end of data
    if open_trade is not None:
        last = df.iloc[-1]
        ep   = float(last["close"])
        pnl  = (open_trade["direction"]
                * (ep - open_trade["entry"])
                * open_trade["lots"]
                * XAUUSD_OZ_PER_LOT)
        balance += pnl
        trades.append({
            **open_trade,
            "exit_price":  round(ep, 2),
            "exit_time":   last["time"],
            "exit_reason": "END",
            "pnl_usd":     round(pnl, 2),
            "balance":     round(balance, 2),
        })

    metrics = _build_metrics(trades, initial_balance_usd, balance, df)
    return {"trades": trades, "metrics": metrics, "final_balance": round(balance, 2)}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _print_close(t: dict):
    lbl  = "BUY " if t["direction"] == 1 else "SELL"
    sign = "+" if t["pnl_usd"] >= 0 else ""
    print(f"  CLOSE {lbl} @ {t['exit_price']:.2f}  "
          f"entry={t['entry']:.2f}  P&L=${sign}{t['pnl_usd']:.2f}  [{t['exit_reason']}]")


def _annual_return(initial: float, final: float, df: pd.DataFrame) -> float:
    try:
        t0 = pd.Timestamp(df["time"].iloc[0])
        t1 = pd.Timestamp(df["time"].iloc[-1])
        n  = (t1 - t0).days / 365.25
        if n > 0 and initial > 0 and final > 0:
            return round(((final / initial) ** (1 / n) - 1) * 100, 2)
    except Exception:
        pass
    return 0.0


def _build_metrics(trades: list, initial: float, final: float, df: pd.DataFrame) -> dict:
    period = (f"{str(df['time'].iloc[0])[:10]} to "
              f"{str(df['time'].iloc[-1])[:10]}")
    empty  = {
        "total_trades": 0, "net_pnl": 0.0, "net_pnl_pct": 0.0,
        "annual_return": 0.0, "profit_factor": 0.0, "win_rate": 0.0,
        "max_drawdown": 0.0, "avg_trade": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        "wins": 0, "losses": 0, "period": period,
        "total_candles": len(df), "initial_balance": initial,
        "final_balance": round(final, 2),
    }
    n = len(trades)
    if n == 0:
        return empty

    wins       = [t for t in trades if t["pnl_usd"] > 0]
    losses     = [t for t in trades if t["pnl_usd"] <= 0]
    total_won  = sum(t["pnl_usd"] for t in wins)
    total_lost = abs(sum(t["pnl_usd"] for t in losses))

    peak, max_dd, bal = initial, 0.0, initial
    for t in trades:
        bal    = t["balance"]
        peak   = max(peak, bal)
        max_dd = max(max_dd, (peak - bal) / peak * 100)

    net = final - initial
    pf  = (total_won / total_lost) if total_lost > 0 else 9999.0
    ann = _annual_return(initial, final, df)

    return {
        "period":          period,
        "total_candles":   len(df),
        "total_trades":    n,
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate":        round(len(wins) / n * 100, 1),
        "avg_win":         round(total_won  / len(wins)   if wins   else 0, 2),
        "avg_loss":        round(total_lost / len(losses) if losses else 0, 2),
        "avg_trade":       round(net / n, 2),
        "profit_factor":   round(pf, 2),
        "total_profit":    round(total_won, 2),
        "total_loss":      round(total_lost, 2),
        "net_pnl":         round(net, 2),
        "net_pnl_pct":     round(net / initial * 100, 2),
        "annual_return":   ann,
        "initial_balance": initial,
        "final_balance":   round(final, 2),
        "max_drawdown":    round(max_dd, 2),
    }


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def _pf_str(m):
    pf = m["profit_factor"]
    return "inf" if pf >= 999 else f"{pf:.2f}"

def _pnl_str(m):
    s = "+" if m["net_pnl"] >= 0 else ""
    return f"${s}{m['net_pnl']:,.0f} ({s}{m['net_pnl_pct']:.1f}%)"

def _ann_str(m):
    s = "+" if m["annual_return"] >= 0 else ""
    return f"{s}{m['annual_return']:.1f}%/yr"

def _avg_str(m):
    s = "+" if m["avg_trade"] >= 0 else ""
    return f"${s}{m['avg_trade']:,.0f}"


def print_report(result: dict, cfg: StrategyConfig = None):
    m = result["metrics"]; trades = result["trades"]
    sep = "=" * 62
    print(f"\n{sep}")
    print("  GoldBot - Backtest Report")
    if cfg:
        print(f"  {cfg.label()}")
    print(sep)
    if m["total_trades"] == 0:
        print("  No trades generated.\n" + sep + "\n"); return
    s = "+" if m["net_pnl"] >= 0 else ""
    print(f"\n  Period:          {m['period']}")
    print(f"  Candles:         {m['total_candles']:,}")
    print(f"  Starting:        ${m['initial_balance']:,.2f}")
    print(f"  Final:           ${m['final_balance']:,.2f}")
    print(f"  Net P&L:         ${s}{m['net_pnl']:,.2f}  ({s}{m['net_pnl_pct']:.1f}%)")
    print(f"  Annual return:   {_ann_str(m)}")
    print(f"  Profit factor:   {_pf_str(m)}")
    print(f"  Win rate:        {m['win_rate']:.0f}%  ({m['wins']}W / {m['losses']}L)")
    print(f"  Max drawdown:    {m['max_drawdown']:.1f}%")
    print(f"  Avg trade P&L:   {_avg_str(m)}")
    print(f"\n{sep}\n")


def print_comparison(base, cand,
                     base_label="Baseline", cand_label="Candidate",
                     decision=""):
    mo, mc = base["metrics"], cand["metrics"]
    sep = "=" * 70
    rows = [
        ("Net P&L",       _pnl_str(mo),        _pnl_str(mc)),
        ("Annual return", _ann_str(mo),         _ann_str(mc)),
        ("Profit factor", _pf_str(mo),          _pf_str(mc)),
        ("Win rate",      f"{mo['win_rate']:.0f}%", f"{mc['win_rate']:.0f}%"),
        ("Max drawdown",  f"{mo['max_drawdown']:.1f}%", f"{mc['max_drawdown']:.1f}%"),
        ("Avg trade",     _avg_str(mo),         _avg_str(mc)),
        ("Trades",        str(mo["total_trades"]), str(mc["total_trades"])),
    ]
    print(f"\n{sep}")
    print(f"  {'Metric':<18}  {base_label[:24]:<24}  {cand_label[:24]:<24}")
    print(f"  {'-'*66}")
    for name, ov, cv in rows:
        print(f"  {name:<18}  {ov:<24}  {cv:<24}")
    if decision:
        print(f"  {'-'*66}")
        print(f"  {decision}")
    print(f"{sep}\n")
