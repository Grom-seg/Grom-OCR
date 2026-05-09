#!/usr/bin/env python
import requests
import time
import sys

time.sleep(2)

try:
    r = requests.get("http://127.0.0.1:8000/health", timeout=5)
    print(f"✓ Server OK! Status: {r.status_code}")
    print(f"  Response: {r.json()}")
except Exception as e:
    print(f"✗ Server NOT responding: {e}")
    sys.exit(1)
