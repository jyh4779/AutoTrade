
import requests
import sys

try:
    r = requests.get("http://localhost:8501", timeout=5)
    print(f"Status Code: {r.status_code}")
    if r.status_code == 200:
        print("Success: Streamlit is reachable!")
    else:
        print(f"Failed: Server returned {r.status_code}")
except Exception as e:
    print(f"Error: {e}")
