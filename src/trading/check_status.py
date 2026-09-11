
import sys
import os
from datetime import datetime

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.trading.paper_trader import PaperTrader

def run_report():
    print(f"[REPORT] Generating Asset Status at {datetime.now()}")
    bot = PaperTrader()
    bot.status()

if __name__ == "__main__":
    run_report()
