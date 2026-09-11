
import json, requests, os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from src.trading.kis_api import KISApi

def full_diag():
    kis = KISApi()
    # Wait for rate limit
    print("Waiting for rate limit reset...")
    time.sleep(30)
    
    if not kis.auth():
        print("Auth failed")
        return
        
    cfg = kis._load_config()
    acc = cfg['account_no']
    acc1, acc2 = (acc.split('-')[0], acc.split('-')[1]) if '-' in acc else (acc[:8], acc[8:])
    
    # Try Inquire Balance
    url = f"{kis.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
    tr_id = "VTTC8434R" if kis.is_vts else "TTTC8434R"
    h = {"Content-Type":"application/json", "Authorization":f"Bearer {kis.access_token}", "appkey":cfg['app_key'], "appsecret":cfg['secret_key'], "tr_id":tr_id}
    p = {"CANO":acc1, "ACNT_PRDT_CD":acc2, "AFHR_FLPR_YN":"N", "OVR_BUSI_DGNE_YN":"N", "PRCS_DVSN":"01", "CTX_AREA_FK100":"", "CTX_AREA_NK100":""}
    
    r = requests.get(url, headers=h, params=p)
    print("\n[DEBUG] Balance Response Status:", r.status_code)
    print("[DEBUG] Balance Response Body:", r.text)

if __name__ == "__main__":
    import time
    full_diag()
