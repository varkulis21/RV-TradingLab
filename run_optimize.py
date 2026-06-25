"""
GoldBot systematic optimizer.

Tests one improvement at a time against the current best config.
A change is ACCEPTED only if it improves ALL THREE of:
  - Profit factor  (higher is better)
  - Net profit     (higher is better)
  - Max drawdown   (lower is better)

Usage:
    python run_optimize.py            # 5000 H1 bars, $10,000 start
    python run_optimize.py --bars 3000
    python run_optimize.py --balance 50000
"""

import sys
import os
import argparse
import copy
import dataclasses

sys.path.insert(0, os.path.dirname(__file__))

from src.bot.providers import get_provider
from src.backtest.engine import (
    StrategyConfig, run_backtest, print_comparison,
)
from config.mt5_config import SYMBOL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_better(cand: dict, base: dict) -> bool:
    """True only when the candidate beats the baseline on all three criteria."""
    cm, bm = cand["metrics"], base["metrics"]
    return (
        cm["profit_factor"] > bm["profit_factor"]
        and cm["net_pnl"]   > bm["net_pnl"]
        and cm["max_drawdown"] < bm["max_drawdown"]
    )


def _run(df, cfg, balance):
    return run_backtest(df=df, cfg=cfg, initial_balance_usd=balance)


def _test(df, balance, baseline_result, baseline_cfg, candidate_cfg, test_label):
    """Run one test, print comparison, return (accepted, candidate_result)."""
    print(f"\n{'='*70}")
    print(f"  TEST: {test_label}")
    print(f"  Baseline : {baseline_cfg.label()}")
    print(f"  Candidate: {candidate_cfg.label()}")
    print(f"{'='*70}")

    cand_result = _run(df, candidate_cfg, balance)

    accepted = _is_better(cand_result, baseline_result)
    decision = (
        "ACCEPTED -- profit factor UP, net profit UP, drawdown DOWN"
        if accepted else
        "REJECTED -- at least one metric did not improve"
    )

    print_comparison(
        baseline_result, cand_result,
        base_label="Baseline",
        cand_label="Candidate",
        decision=decision,
    )
    return accepted, cand_result


def _sweep(df, balance, baseline_result, baseline_cfg, candidates: list, sweep_label: str):
    """
    Test a list of (label, cfg) candidates against the baseline.
    Returns the best (cfg, result) pair if it beats the baseline, else (None, None).
    """
    print(f"\n{'='*70}")
    print(f"  SWEEP: {sweep_label}")
    print(f"  Baseline: {baseline_cfg.label()}")
    print(f"{'='*70}")

    bm = baseline_result["metrics"]
    best_cfg    = None
    best_result = None
    best_pf     = bm["profit_factor"]

    rows = []
    for label, cfg in candidates:
        r   = _run(df, cfg, balance)
        m   = r["metrics"]
        pf  = m["profit_factor"]
        sgn = "+" if m["net_pnl"] >= 0 else ""
        rows.append((label,
                     f"${sgn}{m['net_pnl']:>8.0f} ({sgn}{m['net_pnl_pct']:.1f}%)",
                     f"{pf:.2f}" if pf < 999 else " inf",
                     f"{m['win_rate']:.0f}%",
                     f"{m['max_drawdown']:.1f}%",
                     str(m["total_trades"])))
        if _is_better(r, baseline_result) and pf > best_pf:
            best_pf     = pf
            best_cfg    = cfg
            best_result = r

    # Print sweep table
    bl_pf  = f"{bm['profit_factor']:.2f}" if bm["profit_factor"] < 999 else " inf"
    bl_sgn = "+" if bm["net_pnl"] >= 0 else ""
    print(f"\n  {'Config':<22}  {'Net P&L':>22}  {'PF':>5}  {'WR':>4}  {'DD':>5}  {'Trades':>6}")
    print("  " + "-" * 72)
    print(f"  {'Baseline':<22}  ${bl_sgn}{bm['net_pnl']:>8.0f} ({bl_sgn}{bm['net_pnl_pct']:.1f}%)"
          f"  {bl_pf:>5}  {bm['win_rate']:.0f}%  {bm['max_drawdown']:.1f}%  {bm['total_trades']:>6}")
    for (lbl, net, pf_s, wr, dd, tr) in rows:
        print(f"  {lbl:<22}  {net:>22}  {pf_s:>5}  {wr:>4}  {dd:>5}  {tr:>6}")
    print()

    if best_cfg is not None:
        bm2 = best_result["metrics"]
        pf2 = f"{bm2['profit_factor']:.2f}" if bm2["profit_factor"] < 999 else "inf"
        sign2 = "+" if bm2["net_pnl"] >= 0 else ""
        print(f"  ACCEPTED: best = {best_cfg.label()}")
        print(f"    Net ${sign2}{bm2['net_pnl']:.0f}  PF={pf2}  DD={bm2['max_drawdown']:.1f}%")
    else:
        print("  REJECTED: no candidate beat the baseline on all three criteria")

    return best_cfg, best_result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars",    type=int,   default=5000)
    parser.add_argument("--balance", type=float, default=10_000)
    args = parser.parse_args()

    balance = args.balance

    # -- Fetch data once so all runs share the same candles ---------------
    print(f"\nGoldBot Optimizer  |  bars={args.bars}  balance=${balance:,.0f}")
    print("Fetching H1 data from Yahoo Finance (once)...")
    provider = get_provider()
    df_raw   = provider.fetch_ohlcv(SYMBOL, timeframe="H1", bars=args.bars)
    print(f"  Got {len(df_raw)} candles  "
          f"({str(df_raw['time'].iloc[0])[:10]} to "
          f"{str(df_raw['time'].iloc[-1])[:10]})\n")

    # -- Establish baseline ------------------------------------------------
    best_cfg    = StrategyConfig()   # EMA 20/50 + EMA200 trend filter
    best_result = _run(df_raw, best_cfg, balance)
    bm          = best_result["metrics"]
    bl_pf       = f"{bm['profit_factor']:.2f}" if bm["profit_factor"] < 999 else "inf"
    bl_sign     = "+" if bm["net_pnl"] >= 0 else ""
    print(f"Baseline  [{best_cfg.label()}]")
    print(f"  Net ${bl_sign}{bm['net_pnl']:.0f} ({bl_sign}{bm['net_pnl_pct']:.1f}%)  "
          f"PF={bl_pf}  WR={bm['win_rate']:.0f}%  "
          f"DD={bm['max_drawdown']:.1f}%  Trades={bm['total_trades']}\n")

    # ======================================================================
    # TEST 1: RSI confirmation
    # ======================================================================
    def _mod(base, **kwargs):
        c = copy.copy(base)
        for k, v in kwargs.items():
            setattr(c, k, v)
        return c

    rsi_cfg = _mod(best_cfg, use_rsi=True, rsi_period=14, rsi_ob=70.0, rsi_os=30.0)
    accepted, rsi_result = _test(
        df_raw, balance, best_result, best_cfg, rsi_cfg,
        "RSI confirmation  (skip BUY when RSI>=70, skip SELL when RSI<=30)"
    )
    if accepted:
        best_cfg, best_result = rsi_cfg, rsi_result

    # ======================================================================
    # TEST 2: ADX trend strength
    # ======================================================================
    adx_cfg = _mod(best_cfg, use_adx=True, adx_period=14, adx_min=25.0)
    accepted, adx_result = _test(
        df_raw, balance, best_result, best_cfg, adx_cfg,
        "ADX trend strength  (only trade when ADX > 25)"
    )
    if accepted:
        best_cfg, best_result = adx_cfg, adx_result

    # ======================================================================
    # TEST 3: ATR volatility filter
    # ======================================================================
    atr_vol_cfg = _mod(best_cfg, use_atr_filter=True, atr_min_pct=0.20, atr_max_pct=1.50)
    accepted, atr_vol_result = _test(
        df_raw, balance, best_result, best_cfg, atr_vol_cfg,
        "ATR volatility filter  (skip if ATR/price outside 0.20%-1.50%)"
    )
    if accepted:
        best_cfg, best_result = atr_vol_cfg, atr_vol_result

    # ======================================================================
    # TEST 4: Session filter (London + New York: 07-21 UTC)
    # ======================================================================
    sess_cfg = _mod(best_cfg, use_session_filter=True,
                    session_start_utc=7, session_end_utc=21)
    accepted, sess_result = _test(
        df_raw, balance, best_result, best_cfg, sess_cfg,
        "Session filter  (only enter trades between 07:00-21:00 UTC)"
    )
    if accepted:
        best_cfg, best_result = sess_cfg, sess_result

    # ======================================================================
    # TEST 5: EMA length sweep
    # ======================================================================
    ema_candidates = [
        ("EMA 10/30",  _mod(best_cfg, ema_fast=10, ema_slow=30)),
        ("EMA 15/40",  _mod(best_cfg, ema_fast=15, ema_slow=40)),
        ("EMA 20/50",  _mod(best_cfg, ema_fast=20, ema_slow=50)),  # current
        ("EMA 25/60",  _mod(best_cfg, ema_fast=25, ema_slow=60)),
        ("EMA 30/80",  _mod(best_cfg, ema_fast=30, ema_slow=80)),
    ]
    new_cfg, new_result = _sweep(
        df_raw, balance, best_result, best_cfg, ema_candidates, "EMA length sweep"
    )
    if new_cfg is not None:
        best_cfg, best_result = new_cfg, new_result

    # ======================================================================
    # TEST 6: ATR stop-loss multiplier sweep
    # ======================================================================
    sl_candidates = [
        (f"SL 1.0x ATR", _mod(best_cfg, atr_sl_mult=1.0)),
        (f"SL 1.25x ATR",_mod(best_cfg, atr_sl_mult=1.25)),
        (f"SL 1.5x ATR", _mod(best_cfg, atr_sl_mult=1.5)),   # current
        (f"SL 2.0x ATR", _mod(best_cfg, atr_sl_mult=2.0)),
        (f"SL 2.5x ATR", _mod(best_cfg, atr_sl_mult=2.5)),
    ]
    new_cfg, new_result = _sweep(
        df_raw, balance, best_result, best_cfg, sl_candidates, "ATR stop-loss multiplier sweep"
    )
    if new_cfg is not None:
        best_cfg, best_result = new_cfg, new_result

    # ======================================================================
    # TEST 7: Risk-reward ratio sweep
    # ======================================================================
    rr_candidates = [
        (f"RR 1.5:1", _mod(best_cfg, rr_ratio=1.5)),
        (f"RR 2.0:1", _mod(best_cfg, rr_ratio=2.0)),   # current
        (f"RR 2.5:1", _mod(best_cfg, rr_ratio=2.5)),
        (f"RR 3.0:1", _mod(best_cfg, rr_ratio=3.0)),
    ]
    new_cfg, new_result = _sweep(
        df_raw, balance, best_result, best_cfg, rr_candidates, "Risk-reward ratio sweep"
    )
    if new_cfg is not None:
        best_cfg, best_result = new_cfg, new_result

    # ======================================================================
    # Final summary
    # ======================================================================
    fm = best_result["metrics"]
    fs = "+" if fm["net_pnl"] >= 0 else ""
    fp = f"{fm['profit_factor']:.2f}" if fm["profit_factor"] < 999 else "inf"

    print("\n" + "=" * 70)
    print("  OPTIMISATION COMPLETE")
    print("=" * 70)
    print(f"\n  Final config: {best_cfg.label()}")
    print(f"\n  Net P&L:        ${fs}{fm['net_pnl']:,.2f}  ({fs}{fm['net_pnl_pct']:.1f}%)")
    print(f"  Profit factor:  {fp}")
    print(f"  Win rate:       {fm['win_rate']:.0f}%")
    print(f"  Max drawdown:   {fm['max_drawdown']:.1f}%")
    print(f"  Avg trade P&L:  ${fs}{fm['avg_trade']:,.2f}")
    print(f"  Total trades:   {fm['total_trades']}")
    print()
    print("  Run the final 5-year report with:")
    print(f"    python run_final_report.py")
    print("=" * 70 + "\n")

    # Print the dataclass repr so the user can inspect it
    print("  Best StrategyConfig (copy into run_final_report.py if needed):")
    for f in dataclasses.fields(best_cfg):
        print(f"    {f.name} = {getattr(best_cfg, f.name)!r}")
    print()


if __name__ == "__main__":
    main()
