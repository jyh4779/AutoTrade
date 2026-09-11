
import requests
import json
import os
from datetime import datetime

# Standard Config Path based on official guide style
CONFIG_PATH = "D:\\ML\\data\\config.json"
TOKEN_TMP = "D:\\ML\\data\\kis_token.json"

class KISAuth:
    def __init__(self):
        self.config_path = CONFIG_PATH
        self.config = self._load_config()
        self.is_vts = False
        self.base_url = "https://openapi.koreainvestment.com:9443"
        self.access_token = None
        self._load_and_init()
        
    def _load_config(self):
        if not os.path.exists(CONFIG_PATH):
            return {}
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}

    def _load_and_init(self):
        app_key = self.config.get('app_key', '')
        server_type = self.config.get('server_type')
        
        # Respect explicit server_type if provided
        if server_type == 'VIRTUAL':
            self.base_url = "https://openapivts.koreainvestment.com:29443"
            self.is_vts = True
        elif server_type == 'REAL':
            self.base_url = "https://openapi.koreainvestment.com:9443"
            self.is_vts = False
        else:
            # Default to REAL for the boss's account
            self.base_url = "https://openapi.koreainvestment.com:9443"
            self.is_vts = False

    def get_token(self):
        # 1. Check existing token and its expiration
        if os.path.exists(TOKEN_TMP):
            try:
                with open(TOKEN_TMP, 'r') as f:
                    t_data = json.load(f)
                    access_token = t_data.get('access_token')
                    expired_at = t_data.get('access_token_token_expired') # Format: "2026-02-21 09:49:51"
                    
                    if access_token and expired_at:
                        exp_dt = datetime.strptime(expired_at, '%Y-%m-%d %H:%M:%S')
                        # Check if token is still valid (with 1 hour buffer)
                        if (exp_dt - datetime.now()).total_seconds() > 3600:
                            return access_token
                        else:
                            print("[INFO] KIS Token expired. Requesting a new one...")
            except Exception as e:
                print(f"[DEBUG] Token check error: {e}")
                pass

        # 2. Issue new token (Official Logic)
        url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.config.get('app_key'),
            "appsecret": self.config.get('secret_key')
        }
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                data = res.json()
                with open(TOKEN_TMP, 'w') as f:
                    json.dump(data, f)
                return data.get('access_token')
        except: pass
        return None

    def auth(self):
        # Compatibility helper for existing scripts
        self.access_token = self.get_token()
        return self.access_token is not None

    def get_headers(self, tr_id):
        if not self.access_token:
            self.auth()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
            "appkey": self.config.get('app_key'),
            "appsecret": self.config.get('secret_key'),
            "tr_id": tr_id,
            "custtype": "P"
        }

    def get_account_info(self):
        acc = self.config.get('account_no', '')
        if '-' in acc:
            parts = acc.split('-')
            return parts[0], parts[1]
        return acc[:8], acc[8:]
