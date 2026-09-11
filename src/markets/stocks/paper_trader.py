
import sqlite3
import os
from datetime import datetime
import pandas as pd
from pykrx import stock
import sys

# Force utf-8 for stdout
sys.stdout.reconfigure(encoding='utf-8')

class PaperTrader:
    def __init__(self, initial_balance=5000000, db_path="D:\\ML\\data\\portfolio.db"):
        self.db_path = db_path
        self.initial_balance = initial_balance
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
        CREATE TABLE IF NOT EXISTS balance (
            id INTEGER PRIMARY KEY,
            amount REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        c.execute('''
        CREATE TABLE IF NOT EXISTS holdings (
            code TEXT PRIMARY KEY,
            name TEXT,
            qty INTEGER,
            avg_price REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        c.execute('''
        CREATE TABLE IF NOT EXISTS trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            type TEXT,
            code TEXT,
            name TEXT,
            qty INTEGER,
            price REAL,
            total REAL,
            profit REAL,
            return_pct REAL,
            score REAL DEFAULT 0
        )
        ''')
        # 기존 DB에 score 컬럼이 없을 경우 자동 추가
        c.execute("PRAGMA table_info(trade_log)")
        columns = [row[1] for row in c.fetchall()]
        if 'score' not in columns:
            c.execute("ALTER TABLE trade_log ADD COLUMN score REAL DEFAULT 0")

        # Init balance if empty
        c.execute("SELECT count(*) FROM balance")
        if c.fetchone()[0] == 0:
            c.execute("INSERT INTO balance (id, amount) VALUES (1, ?)", (self.initial_balance,))
        conn.commit()
        conn.close()

    def get_balance(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT amount FROM balance WHERE id=1")
        res = c.fetchone()
        conn.close()
        return res[0] if res else 0.0

    def get_holdings(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT code, name, qty, avg_price FROM holdings")
        res = c.fetchall()
        conn.close()
        return res

    def _update_balance(self, amount):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("UPDATE balance SET amount = ?, updated_at = CURRENT_TIMESTAMP WHERE id=1", (amount,))
        conn.commit()
        conn.close()

    def get_current_price(self, code):
        today = datetime.now().strftime("%Y%m%d")
        try:
            from_date = (datetime.now() - pd.Timedelta(days=5)).strftime("%Y%m%d")
            df = stock.get_market_ohlcv_by_date(from_date, today, code)
            if df.empty: return None
            return float(df.iloc[-1]['종가'])
        except:
            return None

    def buy(self, code, name, quantity, score=0.0):
        price = self.get_current_price(code)
        if not price:
            print(f"[Fail] Could not get price for {name}")
            return

        balance = self.get_balance()
        total_cost = price * quantity
        fee = total_cost * 0.00015

        if balance < (total_cost + fee):
            print(f"[Fail] Insufficient funds for {name}. Balance: {balance:,.0f}")
            return

        new_balance = balance - (total_cost + fee)
        self._update_balance(new_balance)

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        # Check existing
        c.execute("SELECT qty, avg_price FROM holdings WHERE code=?", (code,))
        res = c.fetchone()
        if res:
            curr_qty, curr_avg = res
            new_qty = curr_qty + quantity
            new_avg = ((curr_qty * curr_avg) + total_cost) / new_qty
            c.execute("UPDATE holdings SET qty=?, avg_price=?, updated_at=CURRENT_TIMESTAMP WHERE code=?",
                      (new_qty, new_avg, code))
        else:
            c.execute("INSERT INTO holdings (code, name, qty, avg_price) VALUES (?, ?, ?, ?)",
                      (code, name, quantity, price))

        # Log
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute('''
            INSERT INTO trade_log (date, type, code, name, qty, price, total, profit, return_pct, score)
            VALUES (?, 'BUY', ?, ?, ?, ?, ?, 0, 0, ?)
        ''', (date_str, code, name, quantity, price, total_cost, score))

        conn.commit()
        conn.close()
        print(f"[BUY SUCCESS] {name} {quantity} shares at {price:,.0f} KRW")

    def sell(self, code, quantity=None, score=0.0):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT name, qty, avg_price FROM holdings WHERE code=?", (code,))
        res = c.fetchone()
        if not res:
            conn.close()
            return
        
        name, curr_qty, avg_price = res
        if quantity is None or quantity > curr_qty:
            quantity = curr_qty

        price = self.get_current_price(code)
        if not price:
            print(f"[Fail] Could not get price for {name}")
            conn.close()
            return

        total_revenue = price * quantity
        tax_fee = total_revenue * 0.0023
        
        balance = self.get_balance()
        self._update_balance(balance + total_revenue - tax_fee)
        
        # Update holdings
        if quantity == curr_qty:
            c.execute("DELETE FROM holdings WHERE code=?", (code,))
        else:
            c.execute("UPDATE holdings SET qty = qty - ? WHERE code=?", (quantity, code))
            
        # P&L
        denom = (avg_price * quantity)
        profit = (price - avg_price) * quantity - tax_fee
        ret_pct = (profit / denom * 100) if denom != 0 else 0
        
        # Log
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute('''
            INSERT INTO trade_log (date, type, code, name, qty, price, total, profit, return_pct, score)
            VALUES (?, 'SELL', ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (date_str, code, name, quantity, price, total_revenue, profit, ret_pct, score))
        
        conn.commit()
        conn.close()
        print(f"[SELL SUCCESS] {name} {quantity} shares at {price:,.0f} KRW (Profit: {profit:,.0f}, {ret_pct:.2f}%)")

    def _get_buy_score(self, code: str) -> float:
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute(
                "SELECT score FROM trade_log WHERE code=? AND type='BUY' ORDER BY date DESC LIMIT 1",
                (code,)
            )
            row = c.fetchone()
            conn.close()
            return row[0] if row else 0.0
        except Exception:
            return 0.0

    def sell_all(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT code FROM holdings")
        codes = [row[0] for row in c.fetchall()]
        conn.close()
        for code in codes:
            self.sell(code, score=self._get_buy_score(code))

    def status(self):
        balance = self.get_balance()
        conn = sqlite3.connect(self.db_path)
        df_holdings = pd.read_sql("SELECT * FROM holdings", conn)
        conn.close()
        
        print("\n--- Portfolio Status ---")
        print(f"Cash Balance: {balance:,.0f} KRW")
        total_value = balance
        
        if not df_holdings.empty:
            print("\nHoldings:")
            for _, row in df_holdings.iterrows():
                curr = self.get_current_price(row['code']) or row['avg_price']
                val = curr * row['qty']
                total_value += val
                pnl = (curr - row['avg_price']) * row['qty']
                pnl_p = (pnl / (row['avg_price'] * row['qty'])) * 100
                print(f" - {row['name']}: {row['qty']} shares | Avg: {row['avg_price']:,.0f} | Cur: {curr:,.0f} | P&L: {pnl_p:.2f}%")
        
        total_ret = ((total_value - self.initial_balance) / self.initial_balance) * 100
        print(f"\nTotal Asset: {total_value:,.0f} KRW (Total Return: {total_ret:.2f}%)")

if __name__ == "__main__":
    bot = PaperTrader()
    bot.status()
