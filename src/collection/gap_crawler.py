import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import feedparser
import pandas as pd
import time
import re
from datetime import datetime, timedelta
from src.utils.llm_client import OllamaSentimentClient

# Force utf-8
sys.stdout.reconfigure(encoding='utf-8')

class GapCrawler:
    def __init__(self):
        self.stock_dir = "D:\\ML\\data\\stocks"
        self.news_db_path = "D:\\ML\\data\\stock_news_db.csv"
        self.targets = self.get_target_codes()
        self.processed_keys = set()
        self.load_processed_keys()
        self.llm_client = OllamaSentimentClient()
        
    def get_target_codes(self):
        codes = []
        if os.path.exists(self.stock_dir):
            for f in os.listdir(self.stock_dir):
                if f.endswith(".csv"):
                    codes.append(f.replace(".csv", ""))
        return codes

    def load_processed_keys(self):
        if os.path.exists(self.news_db_path):
            try:
                df = pd.read_csv(self.news_db_path)
                # Key: Code_YYYY-MM-DD
                self.processed_keys = set(df['Code'].astype(str) + "_" + df['Date'].astype(str))
                print(f"[INIT] Loaded {len(self.processed_keys)} existing records.")
            except: pass

    def analyze_sentiment_local(self, text, code="unknown"):
        """헤드라인 텍스트의 감성 점수를 반환. 실패 시 0.0."""
        result = self.llm_client.score_headlines(name=code, code=code, headlines=[text])
        return result.score if result is not None else 0.0

    def fetch_news(self, code, start_date, end_date):
        rss_url = f"https://news.google.com/rss/search?q={code}+after:{start_date}+before:{end_date}&hl=ko&gl=KR&ceid=KR:ko"
        try:
            feed = feedparser.parse(rss_url)
            return feed.entries
        except:
            return []

    def run(self):
        print("[GAP CRAWLER] Filling missing news data (2021-2025)...")
        
        # Define ranges (Monthly chunks for 5 years)
        # 2021.01 ~ 2025.12
        start_year = 2021
        end_year = 2025
        
        chunks = []
        for y in range(start_year, end_year + 1):
            for m in range(1, 13):
                s = datetime(y, m, 1)
                # Next month
                if m == 12: n = datetime(y+1, 1, 1)
                else: n = datetime(y, m+1, 1)
                e = n - timedelta(days=1)
                chunks.append((s, e))
                
        # Reverse order (Recent first might be better, but user wants to fill gaps)
        # Let's go forward
        
        total_collected = 0
        
        for s, e in chunks:
            s_str = s.strftime("%Y-%m-%d")
            e_str = e.strftime("%Y-%m-%d")
            print(f"\n>>> Processing Month: {s_str} ~ {e_str}")
            
            for i, code in enumerate(self.targets):
                try:
                    entries = self.fetch_news(code, s_str, e_str)
                    new_items = []
                    
                    for entry in entries:
                        try:
                            # Handle different date formats
                            pub_date = datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %Z').strftime("%Y-%m-%d")
                        except:
                            pub_date = s_str
                            
                        key = f"{code}_{pub_date}"
                        if key in self.processed_keys: continue
                        
                        score = self.analyze_sentiment_local(entry.title, code=code)
                        
                        new_items.append({
                            'Code': code,
                            'Date': pub_date,
                            'Title': entry.title,
                            'Sentiment': score
                        })
                        self.processed_keys.add(key)
                    
                    if new_items:
                        df = pd.DataFrame(new_items)
                        hdr = not os.path.exists(self.news_db_path)
                        df.to_csv(self.news_db_path, mode='a', index=False, header=hdr, encoding='utf-8-sig')
                        total_collected += len(new_items)
                        print(f" + {code}: {len(new_items)} items")
                    
                    time.sleep(0.3) 
                except Exception as e:
                    print(f" [ERROR] Failed processing {code} in {s_str}: {e}")
                    time.sleep(1) # Wait a bit before next
            
            print(f" [Month Complete] Total collected so far: {total_collected}")

if __name__ == "__main__":
    crawler = GapCrawler()
    crawler.run()
