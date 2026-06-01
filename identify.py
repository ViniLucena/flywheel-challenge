import requests
import os

URL = "https://homodeus-flywheel.fly.dev/api/identify"
PAYLOAD = {
    "token":"fw_live_5bjrfaga745g6p67jxvx",
    "name":"Vinicius Lucena"
}

response = requests.post(URL, json=PAYLOAD)

if response.status_code == 200:
    print("identification succesful")
else:
    print(f"error {response.status_code}: {response.text}")
