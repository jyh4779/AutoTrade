import sqlite3
import json
import os
import pandas as pd

DB_PATH = "D:\\ML\\data\\portfolio.db"
JSON_PATH = "D:\\ML\\portfolio.json"

def migrate_portfolio_to_db():
    print("Migrating Portfolio JSON to SQLite DB...")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. Create Tables
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
        return_pct REAL
    )
    ''')
    
    # 2. Load JSON
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Balance
        balance = data.get('balance', 5000000)
        c.execute("INSERT OR REPLACE INTO balance (id, amount) VALUES (1, ?)", (balance,))
        
        # Holdings
        holdings = data.get('holdings', {})
        for code, h in holdings.items():
            c.execute("INSERT OR REPLACE INTO holdings (code, name, qty, avg_price) VALUES (?, ?, ?, ?)",
                      (code, h['name'], h['qty'], h['avg_price']))
            
        # History
        history = data.get('history', [])
        for log in history:
            c.execute('''
            INSERT INTO trade_log (date, type, code, name, qty, price, total, profit, return_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                log.get('date'), log.get('type'), log.get('code'), log.get('name'), 
                log.get('qty'), log.get('price'), log.get('total'), 
                log.get('profit', 0), log.get('return_pct', 0)
            ))
            
        print(f"[SUCCESS] Migrated Balance: {balance:,.0f}, Holdings: {len(holdings)}, Logs: {len(history)}")
        
    else:
        print("[INFO] No JSON file found. Initialized empty DB.")
        # Init balance
        c.execute("INSERT OR IGNORE INTO balance (id, amount) VALUES (1, 5000000)")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrate_portfolio_to_db()
