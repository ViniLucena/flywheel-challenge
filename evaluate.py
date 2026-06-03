import requests

URL_IDENTIFY = "https://homodeus-flywheel.fly.dev/api/identify"
URL_EVALUATE = "https://homodeus-flywheel.fly.dev/api/evaluate"
TOKEN = "fw_live_5bjrfaga745g6p67jxvx"

print("Vinculando identidade...")
requests.post(URL_IDENTIFY, json={"token": TOKEN, "name": "Vinícius Lucena"})

print("Iniciando avaliação oficial (Tentativa 3/3)")
resposta = requests.post(URL_EVALUATE, json={"token": TOKEN})
print(resposta.json())