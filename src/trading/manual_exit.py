
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.trading.paper_trader import PaperTrader

def manual_exit():
    bot = PaperTrader()
    print("Executing Manual Stop Loss for Hanmi Semi (042700)...")
    bot.sell('042700')
    bot.status()

if __name__ == "__main__":
    manual_exit()
