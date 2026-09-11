
import sys
import os
import json
import requests
import pandas as pd
import sqlite3
from datetime import datetime

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.trading.kis_api import KISApi

def sync_real_portfolio():
    print("[SYNC] Synchronizing local DB with real KIS account...")
    kis = KISApi()
    
    # 1. Auth (Wait if rate limited)
    while not kis.auth():
        print("Auth rate limited. Waiting 10s...")
        time.sleep(10)
    
    config = kis._load_config()
    acc_no = config.get('account_no')
    acc1, acc2 = (acc_no.split('-')[0], acc_no.split('-')[1]) if '-' in acc_no else (acc_no[:8], acc_no[8:])
    
    # 2. Inquire Balance
    tr_id = "VTTC8434R" if kis.is_vts else "TTTC8434R"
    url = f"{kis.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {kis.access_token}",
        "appkey": config['app_key'],
        "appsecret": config['secret_key'],
        "tr_id": tr_id
    }
    params = {
        "CANO": acc1, "ACNT_PRDT_CD": acc2, "AFHR_FLPR_YN": "N", "OVR_BUSI_DGNE_YN": "N", 
        "PRCS_DVSN": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    
    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        data = r.json()
        if data.get('rt_cd') != '0':
            print(f"API Error: {data.get('msg1')}")
            return

        # 3. Update DB
        conn = sqlite3.connect("D:/ML/data/portfolio.db")
        c = conn.cursor()
        
        # A. Update Balance
        sum_data = data.get('output2', [{}])[0]
        real_cash = float(sum_data.get('dnca_tot_amt', 0))
        c.execute("UPDATE balance SET amount = ?, updated_at = CURRENT_TIMESTAMP WHERE id=1", (real_cash,))
        
        # B. Update Holdings
        # Clear existing local holdings first to match real account
        c.execute("DELETE FROM holdings")
        
        output1 = data.get('output1', [])
        for item in output1:
            qty = int(item.get('hldg_qty', 0))
            if qty > 0:
                code = item.get('pdno')
                name = item.get('prdt_name')
                avg_price = float(item.get('pchs_avg_pric', 0))
                c.execute("INSERT INTO holdings (code, name, qty, avg_price) VALUES (?, ?, ?, ?)",
                          (code, name, qty, avg_price))
                print(f" - Synced: {name} ({code}) {qty} shares")
        
        conn.commit()
        conn.close()
        print(f"[SUCCESS] Sync complete. Real Cash: {real_cash:,.0f} KRW")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    import time
    sync_real_portfolio()
