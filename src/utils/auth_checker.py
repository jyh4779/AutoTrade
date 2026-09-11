
import json
import requests
import os
import time

def test_auth():
    path = "D:\\ML\\data\\config.json"
    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    
    app = cfg['app_key']
    sec = cfg['secret_key']
    
    # KIS has rate limit for auth (1 per min for same key usually)
    # But let's try.
    
    servers = [
        ("REAL", "https://openapi.koreainvestment.com:9443"),
        ("VIRTUAL", "https://openapivts.koreainvestment.com:29443")
    ]
    
    for name, url in servers:
        print(f"Checking {name} server...")
        try:
            r = requests.post(f"{url}/oauth2/tokenP", json={
                "grant_type": "client_credentials",
                "appkey": app,
                "appsecret": sec
            }, timeout=10)
            print(f" - Status: {r.status_code}")
            print(f" - Body: {r.text}")
        except Exception as e:
            print(f" - Error: {e}")
        time.sleep(2)

if __name__ == "__main__":
    test_auth()
