
import sqlite3
import datetime

def check_db():
    conn = sqlite3.connect('D:\\ML\\data\\portfolio.db')
    c = conn.cursor()
    
    print("=== [DATABASE CHECK] ===")
    
    # 1. Today's Trades
    print("\n[Today's Trade Logs]")
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT date, type, code, name, qty, price FROM trade_log WHERE date LIKE ?", (f"{today}%",))
    rows = c.fetchall()
    if rows:
        for r in rows:
            print(f" - {r[0]} | {r[1]} | {r[2]} ({r[3]}) | Qty: {r[4]} | Price: {r[5]:,.0f}")
    else:
        print(" - No trade logs found for today.")

    # 2. Current Holdings
    print("\n[Current Holdings]")
    c.execute("SELECT code, name, qty, avg_price FROM holdings")
    rows = c.fetchall()
    if rows:
        for r in rows:
            print(f" - {r[0]} ({r[1]}) | Qty: {r[2]} | Avg Price: {r[3]:,.0f}")
    else:
        print(" - No holdings currently.")

    # 3. Balance
    print("\n[Balance Status]")
    c.execute("SELECT amount, updated_at FROM balance WHERE id=1")
    row = c.fetchone()
    if row:
        print(f" - Cash: {row[0]:,.0f} KRW (Updated: {row[1]})")

    conn.close()

if __name__ == "__main__":
    check_db()
