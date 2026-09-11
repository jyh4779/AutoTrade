
import sys
import os
from datetime import datetime
import json

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.trading.kis_trader import KISTrader

def run_manual_picks():
    print(f"\n[MANUAL EXEC] Starting Trade Execution: {datetime.now()}")
    
    bot = KISTrader()
    
    # 1. Clear current holdings to refresh portfolio (Standard Routine)
    print("[STEP 1] Selling current holdings to refresh portfolio...")
    bot.sell_all()
    
    # Wait a bit for KIS server to update balance
    import time
    time.sleep(2)
    
    bot.sync_with_real_account()
    
    picks = [
        {'code': '036830', 'name': '솔브레인홀딩스'},
        {'code': '083650', 'name': '비에이치아이'},
        {'code': '319660', 'name': '피에스케이'}
    ]
    
    balance = bot.get_balance()
    print(f"Current Buyable Balance: {balance:,.0f} KRW")
    
    if balance < 100000:
        print("Balance too low for new buys.")
        return

    invest_budget = balance * 0.9 # Use 90% of available cash
    per_stock_budget = invest_budget / len(picks)
    
    print(f"Allocating ~{per_stock_budget:,.0f} KRW per stock.")

    for pick in picks:
        code = pick['code']
        name = pick['name']
        
        price = bot.get_current_price(code)
        if not price:
            print(f" - Could not get price for {name} ({code})")
            continue
            
        qty = int(per_stock_budget // price)
        if qty > 0:
            print(f" -> Order: {name} ({code}) x {qty} shares @ ~{price:,.0f}")
            bot.buy(code, name, qty)
        else:
            print(f" -> Budget too low to buy {name} (Price: {price:,.0f})")
            
    print(f"\n[MANUAL EXEC] Routine Complete: {datetime.now()}")

if __name__ == "__main__":
    run_manual_picks()
