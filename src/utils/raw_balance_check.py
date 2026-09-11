
import requests
import json
import os

def check_raw_balance():
    path = "D:/ML/data/config.json"
    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    
    app = cfg['app_key']
    sec = cfg['secret_key']
    acc = cfg['account_no']
    acc1 = acc[:8]
    acc2 = acc[8:]
    
    # 1. Use existing token if possible
    token_path = "D:/ML/data/kis_token.json"
    if os.path.exists(token_path):
        with open(token_path, 'r') as f:
            token = json.load(f).get('access_token')
            print("Using existing token from file")
    else:
        auth_url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
        res = requests.post(auth_url, json={
            "grant_type": "client_credentials",
            "appkey": app,
            "appsecret": sec
        })
        print("Auth Response:", res.text)
        token = res.json().get('access_token')
    
    if not token:
        print("No token available")
        return
    
    # 2. Inquire Balance
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/trading/inquire-balance"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "appkey": app,
        "appsecret": sec,
        "tr_id": "TTTC8434R"
    }
    params = {
        "CANO": acc1,
        "ACNT_PRDT_CD": acc2,
        "AFHR_FLPR_YN": "N",
        "OVR_BUSI_DGNE_YN": "N",
        "PRCS_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }
    
    r = requests.get(url, headers=headers, params=params)
    print(f"Status: {r.status_code}")
    print(f"Body: {r.text}")

if __name__ == "__main__":
    check_raw_balance()
