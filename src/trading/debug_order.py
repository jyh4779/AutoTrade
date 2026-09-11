
import sys
import os
import requests
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.trading.kis_auth import KISAuth

def debug_order():
    auth = KISAuth()
    cano, prdt_cd = auth.get_account_info()
    
    # Try 1: Market Order with corrected payload (ORD_QTY, EXCG_ID_DVSN_CD)
    url = f"{auth.base_url}/uapi/domestic-stock/v1/trading/order-cash"
    headers = auth.get_headers("TTTC0802U") # Buy
    headers["custtype"] = "P" # Try with P
    
    payload = {
        "CANO": cano,
        "ACNT_PRDT_CD": prdt_cd,
        "PDNO": "005930", # Samsung Electronics
        "ORD_DVSN": "01",
        "ORD_QTY": "1", # Changed from ORD_SQTY
        "ORD_UNPR": "0",
        "EXCG_ID_DVSN_CD": "KRX", # Added
        "SLL_TYPE": "01",
        "CNDT_PRIC": ""
        # "CTAC_TLNO": "", # Removing extra fields not in example for now
        # "MGN_DVSN": "01",
    }
    
    print("--- Test 1: Market Order (Fixed Payload) ---")
    try:
        res = requests.post(url, headers=headers, json=payload)
        print(f"Status: {res.status_code}")
        print(f"Response: {res.text}")
    except Exception as e:
        print(e)

    # Try 2: Limit Order with price 0 (just to see error) without custtype
    headers.pop("custtype", None)
    payload["ORD_DVSN"] = "00"
    payload["ORD_UNPR"] = "50000"
    
    print("\n--- Test 2: Limit Order (NO custtype) ---")
    try:
        res = requests.post(url, headers=headers, json=payload)
        print(f"Status: {res.status_code}")
        print(f"Response: {res.text}")
    except Exception as e:
        print(e)

if __name__ == "__main__":
    debug_order()
