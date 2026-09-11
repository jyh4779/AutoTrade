
import json
import requests
import os
import sys

# Setup for KIS API
def diag_kis():
    config_path = "D:\\ML\\data\\config.json"
    if not os.path.exists(config_path):
        print("Config not found")
        return
        
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
        
    app_key = config.get('app_key')
    secret_key = config.get('secret_key')
    acc_no = config.get('account_no')
    
    # Determine if Virtual (Mock) or Real
    # Mock keys often start with 'PS'
    is_vts = app_key.startswith('PS') if app_key else False
    base_url = "https://openapivts.koreainvestment.com:29443" if is_vts else "https://openapi.koreainvestment.com:9443"
    
    print(f"Mode: {'VIRTUAL' if is_vts else 'REAL'}")
    
    # 1. Auth
    url = f"{base_url}/oauth2/tokenP"
    res = requests.post(url, json={"grant_type": "client_credentials", "appkey": app_key, "appsecret": secret_key})
    token = res.json().get('access_token')
    if not token:
        print("Auth failed")
        return

    # 2. Inquire Balance (Detailed)
    acc1, acc2 = (acc_no.split('-')[0], acc_no.split('-')[1]) if '-' in acc_no else (acc_no[:8], acc_no[8:])
    url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": secret_key,
        "tr_id": "VTTC8434R" if is_vts else "TTTC8434R"
    }
    params = {
        "CANO": acc1, "ACNT_PRDT_CD": acc2, "AFHR_FLPR_YN": "N", "OVR_BUSI_DGNE_YN": "N", 
        "PRCS_DVSN": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    
    res = requests.get(url, headers=headers, params=params)
    data = res.json()
    if data.get('rt_cd') == '0':
        output2 = data.get('output2', [{}])[0]
        print(f"dnca_tot_amt (Actual Cash): {output2.get('dnca_tot_amt')}")
        print(f"tot_evlu_amt (Total Asset): {output2.get('tot_evlu_amt')}")
        print(f"prvs_rcdl_exca_amt (D+2 Settled): {output2.get('prvs_rcdl_exca_amt')}")
    else:
        print(f"Balance Error: {data.get('msg1')}")

    # 3. Inquire Possible
    url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
    headers["tr_id"] = "VTTC8908R" if is_vts else "TTTC8908R"
    params = {
        "CANO": acc1, "ACNT_PRDT_CD": acc2, "PDNO": "005930",
        "ORD_UNPR": "100000", # Specific price
        "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "Y", "OVRS_ICLD_YN": "N"
    }
    res = requests.get(url, headers=headers, params=params)
    data = res.json()
    if data.get('rt_cd') == '0':
        print(f"nrcy_buy_psbl_amt (Available): {data.get('output', {}).get('nrcy_buy_psbl_amt')}")
    else:
        print(f"Psbl Error: {data.get('msg1')}")

if __name__ == "__main__":
    diag_kis()
