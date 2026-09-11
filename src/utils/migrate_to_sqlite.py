
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import sqlite3
import pandas as pd
import os

def migrate_to_sqlite():
    db_path = "D:\\ML\\data\\stock_data.db"
    csv_dir = "D:\\ML\\data"
    stocks_dir = "D:\\ML\\data\\stocks"
    
    print(f"[MIGRATE] Converting CSVs to SQLite ({db_path})...")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Create Tables
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS stocks (
        code TEXT,
        date TEXT,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        PRIMARY KEY (code, date)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS news (
        code TEXT,
        date TEXT,
        title TEXT,
        sentiment REAL,
        link TEXT
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        type TEXT,
        code TEXT,
        name TEXT,
        qty INTEGER,
        price REAL,
        profit REAL,
        return_pct REAL
    )
    ''')
    conn.commit()
    
    # 2. Migrate Stock Data (From D:\ML\data\stocks\*.csv)
    print("Migrating Stocks Data...")
    if os.path.exists(stocks_dir):
        files = [f for f in os.listdir(stocks_dir) if f.endswith(".csv")]
        for i, f in enumerate(files):
            code = f.replace(".csv", "")
            try:
                # Try cp949 first (pykrx default), fallback to utf-8 if needed
                try:
                    df = pd.read_csv(os.path.join(stocks_dir, f), encoding='utf-8')
                except UnicodeDecodeError:
                    df = pd.read_csv(os.path.join(stocks_dir, f), encoding='cp949')

                # Rename cols by Index (Safest)
                # Usually: Date, Open, High, Low, Close, Volume
                df.columns = ['date', 'open', 'high', 'low', 'close', 'volume']
                
                df['code'] = code
                # Convert date to string YYYY-MM-DD
                df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
                
                df.to_sql('stocks', conn, if_exists='append', index=False)
                
                if i % 50 == 0:
                    print(f"[{i}/{len(files)}] Imported {code}...")
            except Exception as e:
                print(f"Error importing {f}: {e}")
                
    # 3. Migrate News Data (From samsung_news_sentiment_5y_fast.csv etc.)
    print("Migrating News Data...")
    news_files = [
        ("samsung_news_sentiment_5y_fast.csv", "005930"),
        ("skhynix_news_sentiment.csv", "000660")
    ]
    
    for fname, code in news_files:
        fpath = os.path.join(csv_dir, fname)
        if os.path.exists(fpath):
            try:
                df = pd.read_csv(fpath)
                # Map columns
                # CSV: Date, Title, Link, Sentiment_Score
                # DB: code, date, title, sentiment, link
                df['code'] = code
                df.rename(columns={'Date': 'date', 'Title': 'title', 'Link': 'link', 'Sentiment_Score': 'sentiment'}, inplace=True)
                
                df.to_sql('news', conn, if_exists='append', index=False)
                print(f"Imported news for {code} ({len(df)} rows)")
            except Exception as e:
                print(f"Error news {fname}: {e}")
                
    # 4. Create Indexes
    print("Creating Indexes...")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocks_date ON stocks (date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocks_code ON stocks (code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_news_date ON news (date)")
    
    conn.commit()
    conn.close()
    print("[SUCCESS] Migration Complete!")

if __name__ == "__main__":
    migrate_to_sqlite()