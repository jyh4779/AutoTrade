
import sys
import os
import requests
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.trading.kis_auth import KISAuth

def get_hashkey(auth, payload):
    url = f"{auth.base_url}/uapi/hashkey"
    headers = {
        "content-type": "application/json",
        "appkey": auth.config.get('app_key'),
        "appsecret": auth.config.get('secret_key')
    }
    try:
        res = requests.post(url, headers=headers, json=payload)
        return res.json().get('HASH')
    except Exception as e:
        print(e)
        return None

def debug_order_with_hash():
    auth = KISAuth()
    cano, prdt_cd = auth.get_account_info()
    
    url = f"{auth.base_url}/uapi/domestic-stock/v1/trading/order-cash"
    tr_id = "TTTC0802U"
    
    payload = {
        "CANO": cano,
        "ACNT_PRDT_CD": prdt_cd,
        "PDNO": "005930",
        "ORD_DVSN": "01",
        "ORD_SQTY": "1",
        "ORD_UNPR": "0",
        # Including all fields just in case
        "CTAC_TLNO": "",
        "MGN_DVSN": "01",
        "LOAN_DT": "",
        "ORD_OBJT_CBLC_DVSN_CD": "",
        "LOAN_CLS_CODE": "",
        "RFLG_CONF_NO": "",
        "ALGO_NO": ""
    }
    
    # Get Hashkey
    hashkey = get_hashkey(auth, payload)
    print(f"Hashkey: {hashkey}")
    
    headers = auth.get_headers(tr_id)
    headers["custtype"] = "P"
    if hashkey:
        headers["hashkey"] = hashkey
        
    try:
        res = requests.post(url, headers=headers, json=payload)
        print(f"Status: {res.status_code}")
        print(f"Response: {res.text}")
    except Exception as e:
        print(e)

if __name__ == "__main__":
    debug_order_with_hash()
