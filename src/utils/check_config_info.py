
import json
import os

def check():
    path = "D:\\ML\\data\\config.json"
    if not os.path.exists(path):
        print("File not found")
        return
    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    
    app = cfg.get('app_key', '')
    acc = cfg.get('account_no', '')
    
    print(f"App Key Prefix: {app[:4]}")
    print(f"Account Number: {acc}")
    print(f"Account Length: {len(acc)}")

if __name__ == "__main__":
    check()
