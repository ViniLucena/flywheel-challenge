import requests

URL = "https://homodeus-flywheel.fly.dev/api/submit"
PAYLOAD = {
    "token": "fw_live_5bjrfaga745g6p67jxvx",
    "repo": "https://github.com/ViniLucena/flywheel-challenge.git",
    "writeup": """Homo Deus | Writeup | Vinícius Lucena

1. MCP de verdade:
Para triangular a ferramenta certa entre as 457 disponíveis sem estourar os tokens, 
implementei um retriever local offline usando BM25 (rank_bm25). 
O RAG injeta apenas os manuais truncados relevantes no prompt. 
Se o modelo erra, o agente intercepta o erro via Python 
e obriga o modelo a usar .keys() no primeiro item para analisar o esquema 
antes de tentar novamente, recuperando-se sozinho no loop.

2. Um sistema que aprende:
Construí uma Memória Viva com "Visão em Túnel". O agente não joga a memória 
inteira no prompt (o que diluiria a atenção do modelo cego). 
Antes de rodar, um filtro no agent.py avalia as palavras-chave da instrução, 
deduz os aplicativos estritamente necessários e injeta apenas os tokens e 
aprendizados referentes aos apps (ex: se é Venmo, esconde credenciais do Spotify).

3. Engenharia de prompt:
O system_prompt não é um guia de comportamento, é um guia restritivo. 
Ele dita regras estritas de paginação (forçando loops dentro de run_code 
em vez de múltiplos call_api) e foca na proibição de alucinações de parâmetros. 

4. Uma harness agêntica:
O agente valida ações determinísticas no nível do código para evitar alucinações. 
Se o prompt de entrada contém verbos de ação puros (ex: "send", "pay", "move") e não perguntas, 
o agent.py intercepta a chamada do complete_task e força a submissão de um answer="". 
Isso evita que o modelo seja reprovado por tentar ser prestativo demais 
(como: "A música foi alterada com sucesso") quando o estado do AppWorld espera null.""",
    "systems": """Agente ReAct com loop principal em Python. 
    Orquestra 5 ferramentas MCP via ctx.model e ctx.mcp.call. 
    RAG offline com BM25 indexando 457 documentações. 
    Memória persistente usando ctx.memory.write/read, 
    com filtro por app (só injeta tokens relevantes para a tarefa). 
    Análise interna de esquemas via print(keys()). 
    Fallback para answer="" em tarefas de ação pura. 
    Limite de passos respeitado e complete_task forçado ao final."""
}

print("enviando submissão")
response = requests.post(URL, json=PAYLOAD)

if response.status_code == 200:
    print("submissão realizada")
    print(response.json())
else:
    print(f"erro {response.status_code}: {response.text}")