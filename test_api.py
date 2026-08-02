import urllib.request
import json

try:
    req = urllib.request.Request("http://127.0.0.1:8000/products/brands")
    with urllib.request.urlopen(req) as response:
        print("Status:", response.status)
        print("Body:", response.read().decode())
except Exception as e:
    print(e)
