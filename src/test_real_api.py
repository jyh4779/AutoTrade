
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.trading.kis_api import KISApi
import json

def test_real_api():
    config_path = "D:\\ML\\data\\config.json"
    if not os.path.exists(config_path):
        print("Config not found")
        return
        
    kis = KISApi()
    print("Testing Auth...")
    if kis.auth():
        print("Auth Success!")
        print("Testing Balance...")
        balance = kis.get_balance()
        print(f"Balance: {balance}")
    else:
        print("Auth Failed")

if __name__ == "__main__":
    test_real_api()
