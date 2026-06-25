"""
GoldBot entry point.

Usage:
    python run_bot.py           # dry-run: logs decisions, no real orders
    python run_bot.py --live    # live: places real orders on demo account
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.bot.bot import GoldBot

if __name__ == "__main__":
    live = "--live" in sys.argv
    bot  = GoldBot(dry_run=not live)
    bot.run()
