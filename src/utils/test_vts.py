
import json, requests, os

def check_vts():
    cfg_path = "D:\\ML\\data\\config.json"
    with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    
    app = cfg['app_key']
    sec = cfg['secret_key']
    acc = cfg['account_no']
    acc1, acc2 = (acc.split('-')[0], acc.split('-')[1]) if '-' in acc else (acc[:8], acc[8:])
    
    # Auth
    url_auth = "https://openapivts.koreainvestment.com:29443/oauth2/tokenP"
    res = requests.post(url_auth, json={"grant_type":"client_credentials","appkey":app,"appsecret":sec})
    print("Auth status:", res.status_code)
    print("Auth body:", res.text)
    if res.status_code != 200: return
    token = res.json()['access_token']
    
    # Inquire Balance
    url = "https://openapivts.koreainvestment.com:29443/uapi/domestic-stock/v1/trading/inquire-balance"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "appkey": app,
        "appsecret": sec,
        "tr_id": "VTTC8434R"
    }
    # Minimal params for VTS
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
    print("Response:", r.json())

if __name__ == "__main__":
    check_vts()
