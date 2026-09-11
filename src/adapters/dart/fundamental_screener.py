
import OpenDartReader
import json
import os
import pandas as pd
from src.core.observability.events import audit, now_kst

class FundamentalScreener:
    def __init__(self, config_path="D:\\ML\\data\\config.json"):
        self.api_key = None
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.api_key = config.get("opendart_api_key")
        
        self.dart = None
        if self.api_key and "YOUR_OPENDART_API_KEY" not in self.api_key:
            try:
                # OpenDartReader creates 'docs_cache' in the current working directory.
                # When run via Task Scheduler, CWD might be C:\Windows\System32 leading to PermissionError (WinError 5).
                # Force CWD to project directory before initializing.
                original_cwd = os.getcwd()
                os.chdir("D:\\ML")
                
                self.dart = OpenDartReader(self.api_key)
                
                # Restore original CWD just in case
                os.chdir(original_cwd)
            except Exception as e:
                print(f"[WARN] OpenDART initialization failed: {e}. Fundamental scoring will be neutral.")
        else:
            print("[WARN] OpenDART API Key missing or placeholder in config.json. Fundamental scoring will be neutral.")

    def get_financial_score(self, code):
        """
        Calculate a fundamental score (0.0 to 1.0) based on key financial metrics.
        - Stability: Debt-to-Equity ratio
        - Profitability: Operating Profit Margin
        - Growth: YoY Revenue/Profit Growth (if available)
        """
        if not self.dart:
            audit().emit('FA_EVALUATED',symbol=code,score=.5,reason='NEUTRAL_NO_SOURCE',source_verified=False)
            return 0.5 # Neutral if no API access
            
        try:
            # 1. Get recent financial statements
            # [B9] 연도가 "2024" 로 박혀 있어 2026년에 2년 묵은 보고서를 봤다.
            #      직전 회계연도를 쓰되, 아직 공시 전이면 그 전 해로 한 번 물러선다.
            from datetime import datetime as _dt
            year = str(_dt.now().year - 1)
            
            # OpenDartReader used finstate() for financial statements
            # 'reprt_code' (11011: Annual, 11012: half, 11013: 1q, 11014: 3q)
            df = self.dart.finstate(code, year, "11011")
            if df is None or df.empty:
                # 직전 회계연도 사업보고서가 아직 공시 전일 수 있다 (통상 3월 말).
                df = self.dart.finstate(code, str(int(year) - 1), "11011")
                year = str(int(year)-1)
            if df is None or df.empty:
                audit().emit('FA_EVALUATED',symbol=code,score=.5,reason='NEUTRAL_MISSING_STATEMENT',source_verified=False)
                return 0.5
            
            # Simplified Scoring Logic
            # - Stability: Debt Ratio
            debt = self.extract_value(df, '부채총계')
            equity = self.extract_value(df, '자본총계')
            debt_ratio = (debt / equity) if equity > 0 else 999
            
            stability_score = 1.0 if debt_ratio < 1.5 else (0.5 if debt_ratio < 3.0 else 0.2)
            
            # - Profitability: Operating Profit
            op_profit = self.extract_value(df, '영업이익')
            revenue = self.extract_value(df, '매출액')
            
            margin = (op_profit / revenue) if revenue > 0 else 0
            profit_score = 1.0 if margin > 0.05 else (0.5 if margin > 0.0 else 0.2)
            
            composite_fa_score = (stability_score * 0.5) + (profit_score * 0.5)
            audit().emit('FA_EVALUATED',symbol=code,score=composite_fa_score,source_verified=True,
                         snapshot_id=audit().snapshot(dict(year=year,report_code='11011',debt=debt,equity=equity,
                             operating_profit=op_profit,revenue=revenue,retrieved_at=now_kst().isoformat(),
                             records=df.to_dict('records'))))
            return composite_fa_score
            
        except Exception as e:
            audit().emit('FA_EVALUATED',symbol=code,score=.5,reason='NEUTRAL_SOURCE_ERROR',source_verified=False)
            print(f"[ERROR] FA Scoring failed for {code}: {e}")
            return 0.5

    def extract_value(self, df, account_name):
        if df is None or df.empty: return 0
        target = df[df['account_nm'].str.contains(account_name, na=False)]
        if not target.empty:
            val = target.iloc[0]['thstrm_amount']
            try:
                # Remove commas and convert to float
                return float(str(val).replace(',', ''))
            except:
                return 0
        return 0

if __name__ == "__main__":
    # Test with a known code (e.g., LG Display 034220)
    fs = FundamentalScreener()
    # score = fs.get_financial_score('034220')
    # print(f"Score for 034220: {score}")
