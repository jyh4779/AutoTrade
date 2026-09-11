
import requests
import json
import pandas as pd
import time
from .kis_auth import KISAuth
from src.utils.decorators import retry

class KISAccount:
    def __init__(self):
        self.auth = KISAuth()

    @retry(max_tries=3, delay_sec=1.0)
    def get_balance(self):
        url = f"{self.auth.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        tr_id = "VTTC8434R" if self.auth.is_vts else "TTTC8434R"
        headers = self.auth.get_headers(tr_id)
        cano, prdt_cd = self.auth.get_account_info()
        
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OVR_BUSI_DGNE_YN": "N",
            "PRCS_DVSN": "01",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        
        # VTS(Virtual) usually requires OFL_YN
        if self.auth.is_vts:
            params["OFL_YN"] = ""

        try:
            items = []
            seen = set()
            for _ in range(20):
                for attempt in range(3):
                    res = requests.get(url, headers=headers, params=params, timeout=15)
                    data = res.json()
                    if data.get('rt_cd') == '0':
                        break
                    if attempt < 2:
                        time.sleep(1+attempt)
                if data.get('rt_cd') != '0':
                    return data
                items.extend(data.get('output1', []))
                if res.headers.get('tr_cont') not in ('M', 'F'):
                    data['output1'] = items
                    return data
                key = (data.get('ctx_area_fk100', ''), data.get('ctx_area_nk100', ''))
                if key in seen or not any(str(v).strip() for v in key):
                    break
                seen.add(key)
                params['CTX_AREA_FK100'], params['CTX_AREA_NK100'] = key
                headers['tr_cont'] = 'N'
            return {'rt_cd': '9', 'msg1': 'incomplete balance pagination'}
        except Exception as e:
            return {"rt_cd": "9", "msg1": str(e)}

    @retry(max_tries=3, delay_sec=1.0)
    def get_buyable_cash(self):
        url = f"{self.auth.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        tr_id = "VTTC8908R" if self.auth.is_vts else "TTTC8908R"
        headers = self.auth.get_headers(tr_id)
        cano, prdt_cd = self.auth.get_account_info()
        
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": prdt_cd,
            "PDNO": "005930",
            "ORD_UNPR": "100000",
            "ORD_DVSN": "01",
            "CMA_EVLU_AMT_ICLD_YN": "Y",
            "OVRS_ICLD_YN": "N"
        }
        
        # VTS(Virtual) usually requires OFL_YN
        if self.auth.is_vts:
            params["OFL_YN"] = ""

        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get('rt_cd') == '0':
                return float(data['output'].get('nrcy_buy_psbl_amt', 0))
        except: pass
        return 0.0
