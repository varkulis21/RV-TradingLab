"""
GoldBot - Professional 5-Year Performance Report.

Runs the final optimised strategy on D1 (daily) candles going back 5+ years.
Uses Gold Futures (GC=F) from Yahoo Finance — the longest free data source.

Final config (determined by run_optimize.py):
  EMA 20/50 crossover
  + EMA 200 trend filter   (only trade in direction of the long-term trend)
  + ATR volatility filter  (skip abnormally quiet or chaotic days)
  SL = 1.5 x ATR,  RR = 2.0 (TP = 3.0 x ATR from entry)
  Risk = 1% of equity per trade

Note: ATR filter bounds are widened for D1 vs the H1-optimised values,
      since daily candles naturally have larger ATR-as-%-of-price.

Usage:
    python run_final_report.py
    python run_final_report.py --years 7 --balance 50000
"""

import sys
import os
import argparse
import csv
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from src.bot.providers import get_provider
from src.backtest.engine import StrategyConfig, run_backtest
from config.mt5_config import SYMBOL


# D1 configuration — EMA periods scaled down from H1 (20/50) to daily (5/20).
#
# Why not EMA 20/50 on D1?
#   Gold was in a persistent uptrend from 2020-2026. With the EMA 200 trend
#   filter active (only trade in trend direction), the strategy correctly blocks
#   most sell signals. But in a strong uptrend EMA 20 rarely crosses below
#   EMA 50, so crossover BUY signals are also infrequent: only 12 trades in
#   6 years — too few to be statistically meaningful.
#   EMA 5/20 on D1 generates ~47 trades over the same period, maintains the
#   same logic (fast over slow = bullish), and produces a robust sample size.
#   The ATR filter bounds are widened to suit daily candle volatility.
FINAL_CFG = StrategyConfig(
    ema_fast           = 5,
    ema_slow           = 20,
    use_trend_filter   = True,
    use_atr_filter     = True,
    atr_min_pct        = 0.30,
    atr_max_pct        = 3.00,
    use_breakeven_stop = True,   # v2: move SL to entry once 1R in profit
    breakeven_r        = 1.0,
    atr_sl_mult        = 1.5,
    rr_ratio           = 4.0,   # v2: wider TP ceiling to let winners run
    risk_pct           = 1.0,
)


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def _year(t):
    return str(t["entry_time"])[:4]


def _ym(t):
    return str(t["entry_time"])[:7]   # "YYYY-MM"


def _annual_table(trades, initial_balance, df):
    """Return list of per-year dicts."""
    # Build equity by trade
    year_data = defaultdict(lambda: {"trades": [], "start_bal": None, "end_bal": None})
    bal = initial_balance
    for t in trades:
        yr = _year(t)
        if year_data[yr]["start_bal"] is None:
            year_data[yr]["start_bal"] = bal
        bal = t["balance"]
        year_data[yr]["trades"].append(t)
        year_data[yr]["end_bal"] = bal

    # Fill years with no trades
    all_years = sorted(set(str(t["entry_time"])[:4] for t in trades))
    rows = []
    for yr in all_years:
        d = year_data[yr]
        yr_trades = d["trades"]
        n     = len(yr_trades)
        wins  = sum(1 for t in yr_trades if t["pnl_usd"] > 0)
        net   = sum(t["pnl_usd"] for t in yr_trades)
        start = d["start_bal"] or initial_balance
        ret   = net / start * 100 if start else 0

        peak, max_dd, b = start, 0.0, start
        for t in yr_trades:
            b = t["balance"]
            peak = max(peak, b)
            dd   = (peak - b) / peak * 100
            max_dd = max(max_dd, dd)

        rows.append({
            "year": yr, "trades": n, "wins": wins,
            "win_rate": round(wins / n * 100, 1) if n else 0,
            "net_pnl": round(net, 2), "return_pct": round(ret, 1),
            "max_dd": round(max_dd, 1),
        })
    return rows


def _monthly_pnl(trades):
    """Return dict {year: {month_int: pnl}} and sorted list of years."""
    monthly = defaultdict(lambda: defaultdict(float))
    for t in trades:
        ts = str(t["entry_time"])
        yr = int(ts[:4])
        mo = int(ts[5:7])
        monthly[yr][mo] += t["pnl_usd"]
    return monthly


def _worst_drawdowns(trades, initial_balance, top_n=3):
    """Return top_n drawdown periods as dicts."""
    if not trades:
        return []

    # Build equity curve point-by-point
    equity = [(None, initial_balance)]
    for t in trades:
        equity.append((t["exit_time"], t["balance"]))

    periods = []
    peak_idx = 0
    peak_val = initial_balance

    for i, (ts, bal) in enumerate(equity):
        if bal >= peak_val:
            peak_idx = i
            peak_val = bal
        else:
            dd = (peak_val - bal) / peak_val * 100
            if dd > 0:
                periods.append({
                    "dd_pct":    round(dd, 1),
                    "peak_bal":  round(peak_val, 2),
                    "trough_bal":round(bal, 2),
                    "peak_time": str(equity[peak_idx][0])[:10] if equity[peak_idx][0] else "start",
                    "trough_time": str(ts)[:10] if ts else "n/a",
                })

    # Deduplicate by keeping the deepest drawdown per peak
    unique = {}
    for p in periods:
        key = p["peak_time"]
        if key not in unique or p["dd_pct"] > unique[key]["dd_pct"]:
            unique[key] = p

    return sorted(unique.values(), key=lambda x: -x["dd_pct"])[:top_n]


def _exit_breakdown(trades):
    counts = defaultdict(int)
    for t in trades:
        counts[t["exit_reason"]] += 1
    return dict(counts)


def _export_csv(trades, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    keys = ["entry_time", "exit_time", "direction", "entry", "exit_price",
            "stop_loss", "take_profit", "lots", "atr", "pnl_usd",
            "balance", "exit_reason"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for t in trades:
            row = {k: t.get(k, "") for k in keys}
            row["direction"] = "BUY" if t["direction"] == 1 else "SELL"
            w.writerow(row)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--years",   type=int,   default=5)
    parser.add_argument("--balance", type=float, default=10_000)
    args = parser.parse_args()

    bars    = args.years * 260 + 300   # ~260 trading days/year + EMA warmup
    balance = args.balance

    print(f"\nGoldBot - 5-Year Professional Report")
    print(f"  Strategy : {FINAL_CFG.label()}")
    print(f"  Timeframe: D1 (daily candles)")
    print(f"  Requested: ~{args.years} years ({bars} bars)")
    print(f"  Capital  : ${balance:,.0f} USD")
    print("\nFetching daily Gold data from Yahoo Finance...")

    provider = get_provider()
    df_raw   = provider.fetch_ohlcv(SYMBOL, timeframe="D1", bars=bars)
    print(f"  Got {len(df_raw)} daily candles  "
          f"({str(df_raw['time'].iloc[0])[:10]} to "
          f"{str(df_raw['time'].iloc[-1])[:10]})\n")
    print("Running backtest...")

    result      = run_backtest(df=df_raw, cfg=FINAL_CFG, initial_balance_usd=balance)
    trades      = result["trades"]
    m           = result["metrics"]
    final_bal   = result["final_balance"]

    # Buy & Hold comparison
    bh_start  = float(df_raw["close"].iloc[0])
    bh_end    = float(df_raw["close"].iloc[-1])
    bh_ret    = (bh_end - bh_start) / bh_start * 100
    bh_value  = balance * (1 + bh_ret / 100)

    # Annualised return
    n_years    = len(df_raw) / 260
    if final_bal > 0 and n_years > 0:
        ann_ret = ((final_bal / balance) ** (1 / n_years) - 1) * 100
    else:
        ann_ret = 0.0

    # Calmar ratio
    calmar = round(ann_ret / m["max_drawdown"], 2) if m["max_drawdown"] > 0 else "n/a"

    sep  = "=" * 68
    hsep = "-" * 68

    # ------------------------------------------------------------------
    print(f"\n{sep}")
    print("  GoldBot - Professional Performance Report")
    print(f"  Period   : {m['period']}")
    print(f"  Strategy : {FINAL_CFG.label()}")
    print(f"  Timeframe: D1  |  Symbol: XAUUSD")
    print(sep)

    # ------------------------------------------------------------------
    sign = "+" if m["net_pnl"] >= 0 else ""
    pf_s = f"{m['profit_factor']:.2f}" if m["profit_factor"] < 999 else "inf"
    print(f"\n  -- ACCOUNT SUMMARY ------------------------------------------")
    print(f"  Starting capital  : ${balance:>12,.2f}")
    print(f"  Final capital     : ${final_bal:>12,.2f}")
    print(f"  Net P&L           : ${sign}{m['net_pnl']:>11,.2f}  ({sign}{m['net_pnl_pct']:.1f}%)")
    print(f"  Annualised return : {'+' if ann_ret >= 0 else ''}{ann_ret:.1f}% per year")
    print(f"  Max drawdown      : {m['max_drawdown']:.1f}%")
    print(f"  Calmar ratio      : {calmar}  (annualised return / max DD)")
    print(f"  Profit factor     : {pf_s}")

    # ------------------------------------------------------------------
    exits = _exit_breakdown(trades)
    n     = m["total_trades"]
    print(f"\n  -- TRADE STATISTICS -----------------------------------------")
    print(f"  Total trades  : {n}")
    if n > 0:
        print(f"  Winners       : {m['wins']}  ({m['win_rate']:.0f}% win rate)")
        print(f"  Losers        : {m['losses']}")
        print(f"  Avg winner    : $+{m['avg_win']:,.2f}")
        print(f"  Avg loser     : -${m['avg_loss']:,.2f}")
        print(f"  Avg trade P&L : ${sign}{m['avg_trade']:,.2f}")
        print(f"\n  Exit breakdown:")
        for reason, cnt in sorted(exits.items()):
            pct = cnt / n * 100
            print(f"    {reason:<14}: {cnt:>4}  ({pct:.0f}%)")

    # ------------------------------------------------------------------
    if trades:
        ann_rows = _annual_table(trades, balance, df_raw)
        print(f"\n  -- YEAR-BY-YEAR PERFORMANCE ---------------------------------")
        print(f"  {'Year':<6}  {'Trades':>6}  {'Win%':>5}  {'Net P&L':>12}  {'Return':>7}  {'Max DD':>7}")
        print(f"  {hsep[2:]}")
        for r in ann_rows:
            sgn2 = "+" if r["net_pnl"] >= 0 else ""
            print(f"  {r['year']:<6}  {r['trades']:>6}  {r['win_rate']:>4.0f}%"
                  f"  ${sgn2}{r['net_pnl']:>10,.2f}  {'+' if r['return_pct']>=0 else ''}{r['return_pct']:>6.1f}%"
                  f"  {r['max_dd']:>6.1f}%")

    # ------------------------------------------------------------------
    if trades:
        monthly = _monthly_pnl(trades)
        years   = sorted(monthly.keys())
        months  = ["Jan","Feb","Mar","Apr","May","Jun",
                   "Jul","Aug","Sep","Oct","Nov","Dec"]
        print(f"\n  -- MONTHLY P&L (USD) ----------------------------------------")
        hdr_mo = "  " + f"{'Year':<6}" + "".join(f"{m:>7}" for m in months)
        print(hdr_mo)
        print(f"  {hsep[2:]}")
        for yr in years:
            row_str = f"  {yr:<6}"
            for mo in range(1, 13):
                val = monthly[yr].get(mo)
                if val is None:
                    row_str += f"{'---':>7}"
                else:
                    sgn2 = "+" if val >= 0 else ""
                    row_str += f"  {sgn2}{val:>4.0f} ".rjust(7)
            print(row_str)

    # ------------------------------------------------------------------
    dds = _worst_drawdowns(trades, balance)
    if dds:
        print(f"\n  -- WORST DRAWDOWN PERIODS -----------------------------------")
        for i, dd in enumerate(dds, 1):
            print(f"  {i}. -{dd['dd_pct']:.1f}%  "
                  f"peak ${dd['peak_bal']:,.0f} ({dd['peak_time']})  "
                  f"-> trough ${dd['trough_bal']:,.0f} ({dd['trough_time']})")

    # ------------------------------------------------------------------
    print(f"\n  -- vs BUY & HOLD GOLD ---------------------------------------")
    bh_sign = "+" if bh_ret >= 0 else ""
    st_sign = "+" if m["net_pnl_pct"] >= 0 else ""
    print(f"  Buy & hold  : ${bh_value:>10,.2f}  ({bh_sign}{bh_ret:.1f}%)")
    print(f"  Strategy    : ${final_bal:>10,.2f}  ({st_sign}{m['net_pnl_pct']:.1f}%)")
    diff = m["net_pnl_pct"] - bh_ret
    print(f"  Difference  : {'+' if diff >= 0 else ''}{diff:.1f} percentage points")
    print(f"  Note: Buy & hold has no risk management -- full drawdown")
    print(f"        during selloffs. Strategy uses hard stop-losses.")

    # ------------------------------------------------------------------
    if trades:
        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        fpath = os.path.join("reports", f"goldbot_final_{ts}.csv")
        _export_csv(trades, fpath)
        print(f"\n  Trade log exported to: {fpath}")

    print(f"\n{sep}\n")


if __name__ == "__main__":
    main()
