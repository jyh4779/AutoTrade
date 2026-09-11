import sys
import os
from datetime import datetime

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.runners.stock_trading import get_trader

def sell_all_holdings():
    print(f"\n[AUTO SELL ALL] Starting Liquidation Routine: {datetime.now()}")

    from src.markets.stocks.calendar import require_trading_day
    if not require_trading_day("청산 루틴"):
        return

    bot = get_trader()
    
    if hasattr(bot, 'sync_with_real_account'):
        if not bot.sync_with_real_account():
            raise RuntimeError('Account unavailable; liquidation not confirmed')
        bot.orders.reconcile()
    holdings = bot.get_holdings()
    if not holdings:
        from src.core.observability.events import audit
        audit().emit('LIQUIDATION_CHECK',confirmed=True,remaining=[],pending_orders=len(bot.orders.pending()) if hasattr(bot,'orders') else 0)
        print("[INFO] No holdings to sell.")
        return
        
    print(f"[INFO] Selling {len(holdings)} holdings...")
    
    # PaperTrader and KISTrader handle selling slightly differently in their sell_all, 
    # but the safest way is to trigger it via the unified interface or just call bot.sell_all()
    # Ensure traders have a robust sell_all method implemented.
    try:
        if hasattr(bot, 'sell_all'):
            bot.sell_all()
        else:
            for item in holdings:
                bot.sell(item['code'], item['name'], item['qty'])
    except Exception as e:
        print(f"[ERROR] Failed to execute sell_all: {e}")
        raise
        
    print(f"[AUTO SELL ALL] Liquidation Routine Complete: {datetime.now()}")

if __name__ == "__main__":
    sell_all_holdings()
