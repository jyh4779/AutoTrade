import sqlite3
import pandas as pd
from datetime import datetime
from pykrx import stock

class PaperTraderDB:
    def __init__(self, db_path="D:\\ML\\data\\portfolio.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()

    def get_balance(self):
        self.cursor.execute("SELECT amount FROM balance WHERE id=1")
        res = self.cursor.fetchone()
        return res[0] if res else 0.0

    def update_balance(self, amount):
        self.cursor.execute("UPDATE balance SET amount = ? WHERE id=1", (amount,))
        self.conn.commit()

    def get_holdings(self):
        self.cursor.execute("SELECT code, name, qty, avg_price FROM holdings")
        return self.cursor.fetchall() # List of tuples

    def clear_holdings(self):
        self.cursor.execute("DELETE FROM holdings")
        self.conn.commit()

    def add_holding(self, code, name, qty, price):
        # Insert or Update
        # Ideally check existing, calculate avg price.
        # For sync, we assume replace or new
        self.cursor.execute("INSERT OR REPLACE INTO holdings (code, name, qty, avg_price) VALUES (?, ?, ?, ?)", 
                            (code, name, qty, price))
        self.conn.commit()
        
    def add_log(self, type_str, code, name, qty, price, profit=0, ret=0):
        total = qty * price
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute('''
            INSERT INTO trade_log (date, type, code, name, qty, price, total, profit, return_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (date_str, type_str, code, name, qty, price, total, profit, ret))
        self.conn.commit()

    def sync_manual_trades(self):
        print("Syncing Today's Trades (Manual Fix)...")
        
        # 1. Clear Old Holdings (Yesterday's)
        self.clear_holdings()
        
        # 2. Add New Holdings (Today's Top 3)
        # Assuming bought at 09:05 Market Price
        targets = [
            ("034020", "DoosanEnerbility"),
            ("000660", "SKHynix"),
            ("012330", "HyundaiMobis")
        ]
        
        today = datetime.now().strftime("%Y%m%d")
        total_invested = 0
        
        # Calculate Cash: Previous Balance + Profit from Yesterday - Investment Today
        # Let's approximate: 2.9M Cash + 2.1M Stock Sold = 5M. 
        # Invested 2.5M today. Remaining Cash ~ 2.5M.
        
        for code, name in targets:
            # Fetch today's open/current price to simulate buy price
            try:
                df = stock.get_market_ohlcv_by_date(today, today, code)
                if not df.empty:
                    buy_price = df.iloc[0]['시가'] # Buy at Open
                    if buy_price == 0: buy_price = df.iloc[-1]['종가']
                    
                    # Invest ~830k per stock
                    qty = int(830000 // buy_price)
                    
                    self.add_holding(code, name, qty, buy_price)
                    self.add_log("BUY", code, name, qty, buy_price)
                    
                    total_invested += (qty * buy_price)
                    print(f" - Added: {name} {qty}ea @ {buy_price}")
            except Exception as e:
                print(f"Error fetching {name}: {e}")
                
        # Update Balance
        # Assume start 5M + profit (~100k) = 5.1M -> Used total_invested
        current_balance = 5150000 - total_invested
        self.update_balance(current_balance)
        
        print(f"[SYNC COMPLETE] Balance: {current_balance:,.0f} KRW")

if __name__ == "__main__":
    trader = PaperTraderDB()
    trader.sync_manual_trades()
