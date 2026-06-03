import requests
import time

URL = "https://homodeus-flywheel.fly.dev/api/result"
PAYLOAD = {"token": "fw_live_5bjrfaga745g6p67jxvx"}

print("Verificando o status da avaliação no servidor do Flywheel..........\n")

while True:
    response = requests.post(URL, json=PAYLOAD)
    
    if response.status_code != 200:
        print(f"Erro na requisição: {response.status_code} - {response.text}")
        break
        
    data = response.json()
    status = data.get("status")
    
    if status == "done":
        print("\nAVALIAÇÃO CONCLUÍDA")
        print(f"Nota (Score): {data.get('score')}")
        print(f"Detalhes: {data}")
        break
    else:
        print(f"O agente ainda está rodando as tarefas... (Status atual: {status})")
        time.sleep(10)