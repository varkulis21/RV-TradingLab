"""
GoldBot backtester entry point.

Simulates the EMA 20/50 crossover strategy over historical XAUUSD data.
No real orders are ever sent.

Usage:
    python run_backtest.py                     # original strategy
    python run_backtest.py --filter            # with EMA 200 trend filter
    python run_backtest.py --compare           # both side by side (recommended)
    python run_backtest.py --bars 2000         # custom bar count
    python run_backtest.py --balance 50000     # custom starting balance (USD)
    python run_backtest.py --compare --verbose # compare + print every trade
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(__file__))

from src.backtest.engine import run_backtest, print_report, print_comparison


def main():
    parser = argparse.ArgumentParser(description="GoldBot backtest runner")
    parser.add_argument("--bars",    type=int,   default=5000,
                        help="H1 candles to test (default: 5000)")
    parser.add_argument("--balance", type=float, default=10_000,
                        help="Starting balance in USD (default: 10000)")
    parser.add_argument("--filter",  action="store_true",
                        help="Apply the EMA 200 trend filter")
    parser.add_argument("--compare", action="store_true",
                        help="Run both strategies and show a comparison table")
    parser.add_argument("--verbose", action="store_true",
                        help="Print every trade entry and exit")
    args = parser.parse_args()

    common = dict(bars=args.bars, initial_balance_usd=args.balance, verbose=args.verbose)

    if args.compare:
        print(f"\nRunning both strategies over {args.bars:,} bars "
              f"(starting balance ${args.balance:,.0f} USD)...")
        print("Fetching historical data...\n")

        orig = run_backtest(use_trend_filter=False, **common)
        filt = run_backtest(use_trend_filter=True,  **common)

        print_comparison(orig, filt)

    else:
        label = "EMA 200 trend filter ON" if args.filter else "no trend filter"
        print(f"\nRunning backtest ({label}) over {args.bars:,} bars "
              f"(starting balance ${args.balance:,.0f} USD)...")
        print("Fetching historical data...\n")

        result = run_backtest(use_trend_filter=args.filter, **common)
        print_report(result)


if __name__ == "__main__":
    main()
