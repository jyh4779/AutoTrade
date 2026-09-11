
import json, requests, os

def debug_auth():
    path = "D:\\ML\\data\\config.json"
    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    
    app = cfg.get('app_key', '')
    sec = cfg.get('secret_key', '')
    
    is_vts = app.startswith('PS')
    url = "https://openapivts.koreainvestment.com:29443" if is_vts else "https://openapi.koreainvestment.com:9443"
    
    print(f"Key starts with: {app[:2]}")
    print(f"Using URL: {url}")
    
    r = requests.post(f"{url}/oauth2/tokenP", json={
        "grant_type": "client_credentials",
        "appkey": app,
        "appsecret": sec
    })
    
    print(f"Status: {r.status_code}")
    print(f"Body: {r.text}")

if __name__ == "__main__":
    debug_auth()
