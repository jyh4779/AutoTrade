
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import feedparser
import pandas as pd
import os
import time
import requests
import re
from datetime import datetime, timedelta
import sys
from src.utils.llm_client import OllamaSentimentClient

# Force utf-8
sys.stdout.reconfigure(encoding='utf-8')

class NightCrawler:
    def __init__(self):
        self.stock_dir = "D:\\ML\\data\\stocks"
        self.news_db_path = "D:\\ML\\data\\stock_news_db.csv"
        self._name_cache = {}
        self.targets = self.get_target_codes()
        self.llm_client = OllamaSentimentClient()
        
    def get_target_codes(self):
        # Scan csv files in directory
        codes = []
        if os.path.exists(self.stock_dir):
            for f in os.listdir(self.stock_dir):
                if f.endswith(".csv"):
                    codes.append(f.replace(".csv", ""))
        print(f"[INIT] Found {len(codes)} target stocks.")
        return codes

    def _resolve_name(self, code):
        """[D1] 종목코드를 종목명으로 바꾼다. 실패하면 코드를 그대로 쓴다."""
        if code in self._name_cache:
            return self._name_cache[code]
        name = code
        try:
            from pykrx import stock as _krx
            got = _krx.get_market_ticker_name(code)
            if got:
                name = got
        except Exception:
            pass
        self._name_cache[code] = name
        return name

    def analyze_sentiment_local(self, text, code="unknown"):
        """헤드라인 텍스트의 감성 점수를 반환. 실패 시 0.0."""
        result = self.llm_client.score_headlines(
            name=self._resolve_name(code), code=code, headlines=[text]
        )
        return result.score if result is not None else 0.0

    def fetch_news(self, code, start_date, end_date):
        # [D1] 종목코드("005930")로 구글 뉴스를 검색하면 의미 있는 결과가 나오지
        #      않는다. 종목명("삼성전자")으로 검색해야 한다. LLM 프롬프트의 종목명
        #      자리에도 코드가 들어가고 있었으므로 함께 고친다.
        name = self._resolve_name(code)
        rss_url = (
            f"https://news.google.com/rss/search?q={name}"
            f"+after:{start_date}+before:{end_date}&hl=ko&gl=KR&ceid=KR:ko"
        )
        try:
            feed = feedparser.parse(rss_url)
            return feed.entries
        except Exception:
            return []

    def run_night_job(self):
        print("[NIGHT JOB] Starting 350 Stocks News Collection (Last 1 Month)...")
        
        # Date Range: Last 30 days
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=30)
        
        # Split into 3 chunks (10 days each) to be safe
        chunks = [
            (start_dt, start_dt + timedelta(days=10)),
            (start_dt + timedelta(days=10), start_dt + timedelta(days=20)),
            (start_dt + timedelta(days=20), end_dt)
        ]
        
        total_collected = 0
        
        # Load existing db
        if os.path.exists(self.news_db_path):
            existing_df = pd.read_csv(self.news_db_path)
            processed_keys = set(existing_df['Code'] + "_" + existing_df['Date']) # Simple dedup key
        else:
            processed_keys = set()

        for chunk_idx, (s, e) in enumerate(chunks):
            s_str = s.strftime("%Y-%m-%d")
            e_str = e.strftime("%Y-%m-%d")
            print(f"\n>>> Processing Chunk {chunk_idx+1}/3: {s_str} ~ {e_str}")
            
            for i, code in enumerate(self.targets):
                # Progress Log
                if i % 10 == 0:
                    print(f"[{i}/{len(self.targets)}] Scanning stocks...")
                
                entries = self.fetch_news(code, s_str, e_str)
                
                new_items = []
                for entry in entries:
                    try:
                        pub_date = datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %Z').strftime("%Y-%m-%d")
                    except:
                        pub_date = s_str # Fallback
                        
                    key = f"{code}_{pub_date}"
                    if key in processed_keys: continue
                    
                    # Analyze Sentiment immediately
                    score = self.analyze_sentiment_local(entry.title, code=code)
                    
                    new_items.append({
                        'Code': code,
                        'Date': pub_date,
                        'Title': entry.title,
                        'Sentiment': score
                    })
                    processed_keys.add(key)
                
                if new_items:
                    # Save immediately (Append mode)
                    df = pd.DataFrame(new_items)
                    hdr = not os.path.exists(self.news_db_path)
                    df.to_csv(self.news_db_path, mode='a', index=False, header=hdr, encoding='utf-8-sig')
                    total_collected += len(new_items)
                
                time.sleep(0.5) # Sleep between stocks
                
        print(f"\n[COMPLETE] Total new items collected: {total_collected}")

if __name__ == "__main__":
    crawler = NightCrawler()
    crawler.run_night_job()