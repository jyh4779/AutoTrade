import sqlite3
import pandas as pd
import os

DB_PATH = "D:\\ML\\data\\portfolio.db"

def check_db():
    if not os.path.exists(DB_PATH):
        print("DB not found")
        return
        
    conn = sqlite3.connect(DB_PATH)
    
    print("\n--- Balance ---")
    print(pd.read_sql("SELECT * FROM balance", conn))
    
    print("\n--- Holdings ---")
    print(pd.read_sql("SELECT * FROM holdings", conn))
    
    print("\n--- Last 5 Trade Logs ---")
    print(pd.read_sql("SELECT * FROM trade_log ORDER BY id DESC LIMIT 5", conn))
    
    conn.close()

if __name__ == "__main__":
    check_db()
