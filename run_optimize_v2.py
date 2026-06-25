"""
GoldBot systematic optimiser v2 — walk-forward edition.

Data: ~12 years of D1 Gold (GC=F) from Yahoo Finance.

Hard split:
  IN-SAMPLE     : everything before 2023-01-01  (~9 years, 2014-2022)
  OUT-OF-SAMPLE : 2023-01-01 onwards             (~3.5 years, unseen)

Acceptance rule (strict, avoids overfitting):
  A change is kept ONLY when it improves ALL THREE in-sample metrics:
    - Profit factor    (higher is better)
    - Annual return    (higher is better)
    - Max drawdown     (lower is better)
  AND does not completely break out-of-sample (OOS PF > 1.0, OOS annual > 0).

Targets: PF > 1.8  |  Annual return > 15%  |  Max drawdown < 10%

Usage:
    python run_optimize_v2.py
    python run_optimize_v2.py --balance 50000
"""

import sys
import os
import copy
import argparse
import dataclasses

sys.path.insert(0, os.path.dirname(__file__))

from src.bot.providers import get_provider
from src.backtest.engine import StrategyConfig, run_backtest, print_comparison
from config.mt5_config import SYMBOL

CUTOFF = "2023-01-01"   # IS / OOS boundary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mod(base: StrategyConfig, **kwargs) -> StrategyConfig:
    c = copy.copy(base)
    for k, v in kwargs.items():
        setattr(c, k, v)
    return c


def _run(df: "pd.DataFrame", cfg: StrategyConfig, balance: float) -> dict:
    return run_backtest(df=df, cfg=cfg, initial_balance_usd=balance)


def _split(df):
    """Return (df_is, df_oos) split at CUTOFF date."""
    import pandas as pd
    mask = pd.to_datetime(df["time"]) < pd.Timestamp(CUTOFF)
    return df[mask].reset_index(drop=True), df[~mask].reset_index(drop=True)


def _is_better_is(cand, base) -> bool:
    cm, bm = cand["metrics"], base["metrics"]
    return (
        cm["profit_factor"]  > bm["profit_factor"]
        and cm["annual_return"] > bm["annual_return"]
        and cm["max_drawdown"]  < bm["max_drawdown"]
    )


def _oos_ok(oos_result) -> bool:
    m = oos_result["metrics"]
    return m["profit_factor"] > 1.0 and m["annual_return"] > 0


def _two_col_table(is_base, is_cand, oos_base, oos_cand,
                   base_label="Baseline", cand_label="Candidate",
                   decision=""):
    """Print a 4-column IS/OOS comparison table."""
    from src.backtest.engine import _pf_str, _ann_str, _pnl_str, _avg_str
    sep = "=" * 78

    def _row(name, bv, cv, bv2, cv2):
        print(f"  {name:<16}  {bv:<18}  {cv:<18}  {bv2:<12}  {cv2:<12}")

    print(f"\n{sep}")
    print(f"  {'Metric':<16}  {'IS '+base_label:<18}  {'IS '+cand_label:<18}  "
          f"{'OOS '+base_label:<12}  {'OOS '+cand_label:<12}")
    print(f"  {'-'*74}")

    def _m(r): return r["metrics"]
    mo_i, mc_i = _m(is_base), _m(is_cand)
    mo_o, mc_o = _m(oos_base), _m(oos_cand)

    rows = [
        ("Annual return",  _ann_str(mo_i), _ann_str(mc_i), _ann_str(mo_o), _ann_str(mc_o)),
        ("Profit factor",  _pf_str(mo_i),  _pf_str(mc_i),  _pf_str(mo_o),  _pf_str(mc_o)),
        ("Win rate",       f"{mo_i['win_rate']:.0f}%", f"{mc_i['win_rate']:.0f}%",
                           f"{mo_o['win_rate']:.0f}%", f"{mc_o['win_rate']:.0f}%"),
        ("Max drawdown",   f"{mo_i['max_drawdown']:.1f}%", f"{mc_i['max_drawdown']:.1f}%",
                           f"{mo_o['max_drawdown']:.1f}%", f"{mc_o['max_drawdown']:.1f}%"),
        ("Avg trade",      _avg_str(mo_i), _avg_str(mc_i), _avg_str(mo_o), _avg_str(mc_o)),
        ("Trades",         str(mo_i["total_trades"]), str(mc_i["total_trades"]),
                           str(mo_o["total_trades"]), str(mc_o["total_trades"])),
    ]
    for r in rows:
        _row(*r)

    if decision:
        print(f"  {'-'*74}")
        print(f"  {decision}")
    print(f"{sep}\n")


def _test(df_is, df_oos, balance,
          is_base_r, oos_base_r,
          base_cfg, cand_cfg, label):
    """Run one test, show IS+OOS table, return (accepted, is_result, oos_result)."""
    print(f"\n  TEST: {label}")
    print(f"  Baseline : {base_cfg.label()}")
    print(f"  Candidate: {cand_cfg.label()}")

    is_r  = _run(df_is,  cand_cfg, balance)
    oos_r = _run(df_oos, cand_cfg, balance)

    acc_is  = _is_better_is(is_r, is_base_r)
    acc_oos = _oos_ok(oos_r)
    accepted = acc_is and acc_oos

    if accepted:
        decision = "ACCEPTED -- IS improved on all 3 metrics AND OOS profitable"
    elif not acc_is:
        decision = "REJECTED -- IS did not improve all 3 metrics simultaneously"
    else:
        decision = "REJECTED -- IS improved but OOS failed (overfitting signal)"

    _two_col_table(is_base_r, is_r, oos_base_r, oos_r,
                   decision=decision)
    return accepted, is_r, oos_r


def _sweep(df_is, df_oos, balance,
           is_base_r, oos_base_r,
           base_cfg, candidates, label):
    """
    Sweep a list of (label, cfg) variants. Print a compact multi-row table.
    Return (best_cfg, best_is_r, best_oos_r) or (None, None, None).
    """
    from src.backtest.engine import _pf_str, _ann_str
    sep = "=" * 78
    print(f"\n  SWEEP: {label}")
    print(f"  Baseline: {base_cfg.label()}")

    results = []
    for lbl, cfg in candidates:
        is_r  = _run(df_is,  cfg, balance)
        oos_r = _run(df_oos, cfg, balance)
        results.append((lbl, cfg, is_r, oos_r))

    # Header
    print(f"\n  {'Config':<22}  {'IS AnnRet':>9}  {'IS PF':>6}  {'IS DD':>6}"
          f"  {'OOS AnnRet':>10}  {'OOS PF':>7}  {'OOS DD':>7}  {'Trades':>7}")
    print("  " + "-" * 78)

    # Baseline row
    mi = is_base_r["metrics"]; mo = oos_base_r["metrics"]
    print(f"  {'[BASELINE]':<22}  {_ann_str(mi):>9}  {_pf_str(mi):>6}"
          f"  {mi['max_drawdown']:>5.1f}%  {_ann_str(mo):>10}  {_pf_str(mo):>7}"
          f"  {mo['max_drawdown']:>6.1f}%  {mi['total_trades']:>7}")

    best_cfg = None; best_is_r = None; best_oos_r = None
    best_pf  = is_base_r["metrics"]["profit_factor"]

    for lbl, cfg, is_r, oos_r in results:
        mi2 = is_r["metrics"]; mo2 = oos_r["metrics"]
        print(f"  {lbl:<22}  {_ann_str(mi2):>9}  {_pf_str(mi2):>6}"
              f"  {mi2['max_drawdown']:>5.1f}%  {_ann_str(mo2):>10}  {_pf_str(mo2):>7}"
              f"  {mo2['max_drawdown']:>6.1f}%  {mi2['total_trades']:>7}")
        if (_is_better_is(is_r, is_base_r) and _oos_ok(oos_r)
                and mi2["profit_factor"] > best_pf):
            best_pf  = mi2["profit_factor"]
            best_cfg = cfg; best_is_r = is_r; best_oos_r = oos_r

    if best_cfg:
        m2 = best_is_r["metrics"]
        print(f"\n  ACCEPTED: best = {best_cfg.label()}")
        print(f"    IS: {_ann_str(m2)}, PF={_pf_str(m2)}, DD={m2['max_drawdown']:.1f}%")
    else:
        print("\n  REJECTED: no variant beat baseline on all criteria")
    print()
    return best_cfg, best_is_r, best_oos_r


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--balance", type=float, default=10_000)
    args = parser.parse_args()
    balance = args.balance

    # -- Fetch full history ------------------------------------------------
    print(f"\nGoldBot Optimizer v2  |  IS/OOS split at {CUTOFF}  |  ${balance:,.0f}")
    print("Fetching 12+ years of D1 Gold data from Yahoo Finance...")
    provider = get_provider()
    df_full  = provider.fetch_ohlcv(SYMBOL, timeframe="D1", bars=3500)
    df_is, df_oos = _split(df_full)
    print(f"  Full  : {len(df_full)} candles "
          f"({str(df_full['time'].iloc[0])[:10]} to {str(df_full['time'].iloc[-1])[:10]})")
    print(f"  IS    : {len(df_is)} candles "
          f"({str(df_is['time'].iloc[0])[:10]} to {str(df_is['time'].iloc[-1])[:10]})")
    print(f"  OOS   : {len(df_oos)} candles "
          f"({str(df_oos['time'].iloc[0])[:10]} to {str(df_oos['time'].iloc[-1])[:10]})\n")

    # -- Baseline ----------------------------------------------------------
    # Use the v1 final config: EMA 5/20 + EMA200 + ATRvol
    best_cfg    = StrategyConfig()   # defaults = EMA 5/20 + EMA200 + ATRvol
    is_base_r   = _run(df_is,  best_cfg, balance)
    oos_base_r  = _run(df_oos, best_cfg, balance)

    from src.backtest.engine import _pf_str, _ann_str
    bm_i = is_base_r["metrics"]; bm_o = oos_base_r["metrics"]
    print(f"Baseline [{best_cfg.label()}]")
    print(f"  IS:  {_ann_str(bm_i)},  PF={_pf_str(bm_i)},  "
          f"WR={bm_i['win_rate']:.0f}%,  DD={bm_i['max_drawdown']:.1f}%,  "
          f"Trades={bm_i['total_trades']}")
    print(f"  OOS: {_ann_str(bm_o)},  PF={_pf_str(bm_o)},  "
          f"WR={bm_o['win_rate']:.0f}%,  DD={bm_o['max_drawdown']:.1f}%,  "
          f"Trades={bm_o['total_trades']}\n")

    # ======================================================================
    # TEST 1: Two-bar confirmation
    # ======================================================================
    cand = _mod(best_cfg, use_confirmation=True)
    ok, is_r, oos_r = _test(df_is, df_oos, balance,
                             is_base_r, oos_base_r, best_cfg, cand,
                             "Two-bar confirmation (enter 1 bar after crossover is confirmed)")
    if ok:
        best_cfg = cand; is_base_r = is_r; oos_base_r = oos_r

    # ======================================================================
    # TEST 2: Trailing stop (trail at 1x initial stop distance)
    # ======================================================================
    cand = _mod(best_cfg, use_trailing_stop=True, trail_atr_mult=1.0)
    ok, is_r, oos_r = _test(df_is, df_oos, balance,
                             is_base_r, oos_base_r, best_cfg, cand,
                             "Trailing stop at 1.0x ATR (trail SL behind best price)")
    if ok:
        best_cfg = cand; is_base_r = is_r; oos_base_r = oos_r

    # ======================================================================
    # TEST 3: Trailing stop + remove fixed TP (let winners run freely)
    # ======================================================================
    cand = _mod(best_cfg, use_trailing_stop=True, trail_atr_mult=1.0,
                remove_fixed_tp=True)
    ok, is_r, oos_r = _test(df_is, df_oos, balance,
                             is_base_r, oos_base_r, best_cfg, cand,
                             "Trailing stop + no fixed TP (exit only on trail or reversal)")
    if ok:
        best_cfg = cand; is_base_r = is_r; oos_base_r = oos_r

    # ======================================================================
    # TEST 4: Breakeven stop (move SL to entry once 1R in profit)
    # ======================================================================
    cand = _mod(best_cfg, use_breakeven_stop=True, breakeven_r=1.0)
    ok, is_r, oos_r = _test(df_is, df_oos, balance,
                             is_base_r, oos_base_r, best_cfg, cand,
                             "Breakeven stop (SL moves to entry once 1R in profit)")
    if ok:
        best_cfg = cand; is_base_r = is_r; oos_base_r = oos_r

    # ======================================================================
    # TEST 5: Trailing multiplier sweep (find optimal trail distance)
    # ======================================================================
    # Only meaningful if trailing stop is already enabled
    if best_cfg.use_trailing_stop:
        trail_candidates = [
            ("Trail 0.75x", _mod(best_cfg, trail_atr_mult=0.75)),
            ("Trail 1.0x",  _mod(best_cfg, trail_atr_mult=1.0)),
            ("Trail 1.25x", _mod(best_cfg, trail_atr_mult=1.25)),
            ("Trail 1.5x",  _mod(best_cfg, trail_atr_mult=1.5)),
            ("Trail 2.0x",  _mod(best_cfg, trail_atr_mult=2.0)),
        ]
        new_cfg, new_is, new_oos = _sweep(df_is, df_oos, balance,
                                           is_base_r, oos_base_r,
                                           best_cfg, trail_candidates,
                                           "Trailing-stop distance sweep")
        if new_cfg:
            best_cfg = new_cfg; is_base_r = new_is; oos_base_r = new_oos
    else:
        # ======================================================================
        # TEST 5b: RR ratio sweep (only if not using pure trailing)
        # ======================================================================
        rr_candidates = [
            ("RR 1.5:1", _mod(best_cfg, rr_ratio=1.5)),
            ("RR 2.0:1", _mod(best_cfg, rr_ratio=2.0)),
            ("RR 2.5:1", _mod(best_cfg, rr_ratio=2.5)),
            ("RR 3.0:1", _mod(best_cfg, rr_ratio=3.0)),
            ("RR 4.0:1", _mod(best_cfg, rr_ratio=4.0)),
        ]
        new_cfg, new_is, new_oos = _sweep(df_is, df_oos, balance,
                                           is_base_r, oos_base_r,
                                           best_cfg, rr_candidates,
                                           "Risk-reward ratio sweep")
        if new_cfg:
            best_cfg = new_cfg; is_base_r = new_is; oos_base_r = new_oos

    # ======================================================================
    # TEST 6: EMA period sweep on 10-year data
    # ======================================================================
    ema_candidates = [
        ("EMA 3/15",   _mod(best_cfg, ema_fast=3,  ema_slow=15)),
        ("EMA 5/20",   _mod(best_cfg, ema_fast=5,  ema_slow=20)),
        ("EMA 8/21",   _mod(best_cfg, ema_fast=8,  ema_slow=21)),
        ("EMA 5/30",   _mod(best_cfg, ema_fast=5,  ema_slow=30)),
        ("EMA 10/30",  _mod(best_cfg, ema_fast=10, ema_slow=30)),
        ("EMA 8/34",   _mod(best_cfg, ema_fast=8,  ema_slow=34)),
    ]
    new_cfg, new_is, new_oos = _sweep(df_is, df_oos, balance,
                                       is_base_r, oos_base_r,
                                       best_cfg, ema_candidates,
                                       "EMA period sweep")
    if new_cfg:
        best_cfg = new_cfg; is_base_r = new_is; oos_base_r = new_oos

    # ======================================================================
    # TEST 7: ATR stop-loss multiplier sweep
    # ======================================================================
    sl_candidates = [
        ("SL 1.0x ATR",  _mod(best_cfg, atr_sl_mult=1.0)),
        ("SL 1.25x ATR", _mod(best_cfg, atr_sl_mult=1.25)),
        ("SL 1.5x ATR",  _mod(best_cfg, atr_sl_mult=1.5)),
        ("SL 2.0x ATR",  _mod(best_cfg, atr_sl_mult=2.0)),
        ("SL 2.5x ATR",  _mod(best_cfg, atr_sl_mult=2.5)),
    ]
    new_cfg, new_is, new_oos = _sweep(df_is, df_oos, balance,
                                       is_base_r, oos_base_r,
                                       best_cfg, sl_candidates,
                                       "ATR stop-loss multiplier sweep")
    if new_cfg:
        best_cfg = new_cfg; is_base_r = new_is; oos_base_r = new_oos

    # ======================================================================
    # TEST 8: Risk per trade sweep (direct lever on returns & drawdown)
    # ======================================================================
    risk_candidates = [
        ("Risk 1.0%", _mod(best_cfg, risk_pct=1.0)),
        ("Risk 1.5%", _mod(best_cfg, risk_pct=1.5)),
        ("Risk 2.0%", _mod(best_cfg, risk_pct=2.0)),
        ("Risk 2.5%", _mod(best_cfg, risk_pct=2.5)),
    ]
    new_cfg, new_is, new_oos = _sweep(df_is, df_oos, balance,
                                       is_base_r, oos_base_r,
                                       best_cfg, risk_candidates,
                                       "Risk-per-trade sweep")
    if new_cfg:
        best_cfg = new_cfg; is_base_r = new_is; oos_base_r = new_oos

    # ======================================================================
    # TEST 9: ADX trend strength (test on final config)
    # ======================================================================
    cand = _mod(best_cfg, use_adx=True, adx_period=14, adx_min=20.0)
    ok, is_r, oos_r = _test(df_is, df_oos, balance,
                             is_base_r, oos_base_r, best_cfg, cand,
                             "ADX filter (ADX > 20 = trending market)")
    if ok:
        best_cfg = cand; is_base_r = is_r; oos_base_r = oos_r

    # ======================================================================
    # FINAL SUMMARY
    # ======================================================================
    fm_i = is_base_r["metrics"]; fm_o = oos_base_r["metrics"]
    sep  = "=" * 78

    # Check against targets
    def _target(label, val, target, better_func):
        status = "OK" if better_func(val, target) else "MISS"
        return f"    {label:<20} IS={val:<10}  target={target}  [{status}]"

    print(f"\n{sep}")
    print("  OPTIMISATION COMPLETE")
    print(f"{sep}")
    print(f"\n  Final config: {best_cfg.label()}")
    print(f"\n  IN-SAMPLE ({str(df_is['time'].iloc[0])[:10]} to "
          f"{str(df_is['time'].iloc[-1])[:10]})")
    print(f"    Annual return  : {_ann_str(fm_i)}")
    print(f"    Profit factor  : {_pf_str(fm_i)}")
    print(f"    Win rate       : {fm_i['win_rate']:.0f}%")
    print(f"    Max drawdown   : {fm_i['max_drawdown']:.1f}%")
    print(f"    Total trades   : {fm_i['total_trades']}")
    print(f"\n  OUT-OF-SAMPLE ({str(df_oos['time'].iloc[0])[:10]} to "
          f"{str(df_oos['time'].iloc[-1])[:10]})")
    print(f"    Annual return  : {_ann_str(fm_o)}")
    print(f"    Profit factor  : {_pf_str(fm_o)}")
    print(f"    Win rate       : {fm_o['win_rate']:.0f}%")
    print(f"    Max drawdown   : {fm_o['max_drawdown']:.1f}%")
    print(f"    Total trades   : {fm_o['total_trades']}")

    print(f"\n  TARGET CHECK (IS):")
    print(_target("PF > 1.8",        _pf_str(fm_i), "1.8",  lambda a, b: float(a) > float(b) if a != 'inf' else True))
    print(_target("Annual ret > 15%", f"{fm_i['annual_return']:.1f}%", "15%", lambda a, b: float(a[:-1]) > 15))
    print(_target("DD < 10%",         f"{fm_i['max_drawdown']:.1f}%",  "10%", lambda a, b: float(a[:-1]) < 10))

    print(f"\n  Best StrategyConfig parameters:")
    for f in dataclasses.fields(best_cfg):
        print(f"    {f.name} = {getattr(best_cfg, f.name)!r}")

    print(f"\n  Run the final report with:")
    print(f"    python run_final_report.py")
    print(f"{sep}\n")


if __name__ == "__main__":
    main()
