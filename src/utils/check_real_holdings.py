
import sys
import os
import json
import requests
import pandas as pd
from datetime import datetime
from pykrx import stock

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.trading.kis_api import KISApi

def check_real_holdings():
    print("Checking real account holdings from KIS API...")
    kis = KISApi()
    
    path = "D:\\ML\\data\\config.json"
    with open(path, 'r', encoding='utf-8') as f:
        config = json.load(f)
        
    app = config.get('app_key')
    sec = config.get('secret_key')
    acc = config.get('account_no')
    
    # Auth
    url = f"{kis.base_url}/oauth2/tokenP"
    res = requests.post(url, json={"grant_type": "client_credentials", "appkey": app, "appsecret": sec})
    if res.status_code != 200:
        print(f"Auth failed: {res.text}")
        return
    token = res.json().get('access_token')
    
    # Inquire Balance
    acc1, acc2 = (acc.split('-')[0], acc.split('-')[1]) if '-' in acc else (acc[:8], acc[8:])
    tr_id = "VTTC8434R" if kis.is_vts else "TTTC8434R"
    
    url = f"{kis.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "appkey": app,
        "appsecret": sec,
        "tr_id": tr_id
    }
    params = {
        "CANO": acc1, "ACNT_PRDT_CD": acc2, "AFHR_FLPR_YN": "N", "OVR_BUSI_DGNE_YN": "N", 
        "PRCS_DVSN": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    
    r = requests.get(url, headers=headers, params=params)
    data = r.json()
    if data.get('rt_cd') == '0':
        output1 = data.get('output1', [])
        output2 = data.get('output2', [{}])[0]
        
        print(f"\n[Real Balance Summary]")
        print(f"Total Asset: {output2.get('tot_evlu_amt')} KRW")
        print(f"Cash: {output2.get('dnca_tot_amt')} KRW")
        
        print("\n[Holdings List]")
        found = False
        for item in output1:
            qty = int(item.get('hldg_qty', 0))
            if qty > 0:
                print(f" - {item.get('prdt_name')} ({item.get('pdno')}): {qty} shares | Current: {item.get('prpr')} KRW")
                found = True
        if not found:
            print("No stocks found in account.")
    else:
        print(f"API Error: {data.get('msg1')}")

if __name__ == "__main__":
    check_real_holdings()
