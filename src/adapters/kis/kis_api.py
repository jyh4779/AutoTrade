
import requests
import json
import os
from datetime import datetime

class KISApi:
    def __init__(self, config_path="D:\\ML\\data\\config.json"):
        self.config_path = config_path
        self.access_token = None
        self.base_url = None
        self.is_vts = False
        self._load_and_init()
        
    def _load_and_init(self):
        if not os.path.exists(self.config_path):
            self.base_url = "https://openapi.koreainvestment.com:9443"
            return

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Priority: Use 'server_type' if exists, otherwise fallback to startswith check but more carefully
            server_type = config.get('server_type', 'REAL')
            if server_type == 'VIRTUAL':
                self.base_url = "https://openapivts.koreainvestment.com:29443"
                self.is_vts = True
            else:
                self.base_url = "https://openapi.koreainvestment.com:9443"
                self.is_vts = False
        except:
            self.base_url = "https://openapi.koreainvestment.com:9443"

    def auth(self):
        try:
            if not os.path.exists(self.config_path): return False
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            if not config.get('app_key') or not config.get('secret_key'): return False
            
            url = f"{self.base_url}/oauth2/tokenP"
            payload = {"grant_type": "client_credentials", "appkey": config['app_key'], "appsecret": config['secret_key']}
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                self.access_token = res.json().get('access_token')
                return True
            return False
        except: return False

    def get_price(self, code):
        if not self.access_token and not self.auth(): return None
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.access_token}", "appkey": config['app_key'], "appsecret": config['secret_key'], "tr_id": "FHKST01010100"}
            params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": code}
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get('rt_cd') == '0' and 'output' in data:
                return float(data['output'].get('stck_prpr', 0))
        except: pass
        return None

    def get_balance(self):
        if not self.access_token and not self.auth(): return 0.0
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            acc_no = config.get('account_no', '')
            acc1, acc2 = (acc_no.split('-')[0], acc_no.split('-')[1]) if '-' in acc_no else (acc_no[:8], acc_no[8:])
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
            tr_id = "VTTC8908R" if self.is_vts else "TTTC8908R"
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.access_token}", "appkey": config['app_key'], "appsecret": config['secret_key'], "tr_id": tr_id}
            params = {"CANO": acc1, "ACNT_PRDT_CD": acc2, "PDNO": "005930", "ORD_UNPR": "100000", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "Y", "OVRS_ICLD_YN": "N"}
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get('rt_cd') == '0' and 'output' in data:
                return float(data['output'].get('nrcy_buy_psbl_amt', 0))
        except: pass
        return 0.0
