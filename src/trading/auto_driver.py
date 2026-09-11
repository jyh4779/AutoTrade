
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.trading.paper_trader import PaperTrader
import time

def auto_trade_today():
    print("[AUTO BOT] Executing Today's Trades (2026-02-11)...")
    
    # Initialize with 5 Million KRW (Resetting for clean start if needed, or load existing)
    # User said "Assuming 500 Man Won"
    # We will reset balance if it's the first run of this new strategy to 5,000,000.
    
    bot = PaperTrader(initial_balance=5000000)
    
    # Check if we already have holdings (resume check)
    if bot.data["holdings"]:
        print(" - Holdings detected. Skipping reset.")
    else:
        print(" - New Portfolio. Setting Balance to 5,000,000 KRW.")
        bot.data["balance"] = 5000000
        bot.initial_balance = 5000000
        bot._save_portfolio()
    
    # Targets from Morning Screener
    targets = [
        {"code": "088350", "name": "HanwhaGenIns", "price": 4070},
        {"code": "003490", "name": "KoreanAir", "price": 24950},
        {"code": "001450", "name": "HyundaiMarine", "price": 32950}
    ]
    
    # Strategy: Invest 50% of Cash
    invest_cash = bot.data["balance"] * 0.5
    per_stock_cash = invest_cash / len(targets)
    
    print(f" - Investing: {invest_cash:,.0f} KRW (Per Stock: {per_stock_cash:,.0f} KRW)")
    
    for t in targets:
        # Calculate Qty
        qty = int(per_stock_cash // t['price'])
        if qty > 0:
            bot.buy(t['code'], t['name'], qty)
            
    bot.status()
    print("\n[AUTO BOT] Trades Executed. Will sell tomorrow morning.")

if __name__ == "__main__":
    auto_trade_today()