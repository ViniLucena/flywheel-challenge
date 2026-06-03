import requests

URL = "https://homodeus-flywheel.fly.dev/api/submit"
PAYLOAD = {
    "token": "fw_live_5bjrfaga745g6p67jxvx",
    "repo": "https://github.com/ViniLucena/flywheel-challenge.git",
    "writeup": """Agente Autônomo para Flywheel | Vinícius Lucena

O sistema orquestra o modelo fixo gemini-3-flash-preview através de uma arquitetura 
ReAct com RAG offline, memória persistente filtrada e um self_loop de reflexão. 

1. MCP de verdade
- Uso estrito das 5 tools (search_apis, api_doc, call_api, run_code, complete_task) via ctx.model 
e ctx.mcp.call.
- O agente não adivinha APIs: primeiro consulta um índice BM25 offline construído 
a partir das 457 documentações. O retriever.py tokeniza e indexa os manuais; 
a cada tarefa, o RAG injeta no prompt apenas os 7 documentos mais relevantes (truncados a 1500 caracteres).
- Se ocorre KeyError (ex: campo 'id' inexistente), o erro é reinjetado no histórico e 
o modelo executa print(list(objeto.keys())) para análise interna, 
corrigindo o nome do campo no próximo passo.

2. Sistema que aprende (Memory Viva)
- Uso de FLYWHEEL_MEMORY_DIR para salvar tokens de autenticação (ex: auth_spotify) e habilidades.
- Filtro de memory por app: antes de montar os prompts, o código analisa a instrução 
com um dicionário keywords_to_apps (ex: "pay" -> venmo, "song" -> spotify). 
Apenas os tokens dos apps necessários são injetados. Isso evita que tokens de Gmail ou 
Todoist distraiam o modelo em tarefas Spotify.
- Exemplo: na primeira tarefa do Spotify, o token é salvo; 
na segunda, o prompt já contém auth_spotify e o login é pulado.

3. Engenharia de Prompts
- O system_prompt atua como protocolo restritivo, não só como algo comportamental.
- Regras principais: "NÃO use apps de fora do escopo da tarefa"; 
"Prefira run_code a múltiplas call_api"; "Sempre pagine com while True e page_index"; 
"Tarefas de ação pura: answer vazia".
- Há uma interceptação do código: dentro do complete_task, se a instrução contém verbos 
de ação pura (send, pay, keep going) e nenhuma palavra de pergunta (how many, list), 
a estrutura força answer="" independentemente do que o modelo gerou, evitado falhas no oráculo.

4. Harness Agêntica e Self_Loop
- O self_loop principal (for passo in range(ctx.max_steps)) orquestra:
  1. Chamada ao modelo com tools=MCP_TOOLS.
  2. Despacho das tool_calls para as tools MCP (ctx.mcp.call).
  3. Adição de resultados ao histórico.
  4. Em caso de erro, adição de mensagem forçando reflexão.
  5. Encerramento ao chamar complete_task.
- Fallback de segurança: se o self_loop termina sem complete_task, a harness chama o encerramento com answer="".
- Resultado prático local: 9/10 acertos (TGC). A única falha foi por limite de passos, não por erro lógico estrutural.""",
    "systems": """Sistema implementado em Python. Loop ReAct principal no `solve(ctx)`. 
    5 ferramentas MCP definidas via `MCP_TOOLS` (JSON schema). 
    RAG offline: `API_Retriever` com BM25 indexa 457 documentações; 
    `search()` retorna string truncada injetada no prompt. 
    Memória: `ctx.memory.read/write` com filtro dinâmico: `keywords_to_apps` 
    analisa instrução e só passa tokens dos apps necessários. 
    Introspecção de esquemas: em caso de KeyError, o modelo imprime `.keys()` e corrige. 
    Interceptação de ações: no `complete_task`, detecta verbos de ação e força `answer=""`. 
    Fallback de segurança ao final do loop. 
    Testado localmente com `run_local.py --n 10` obtendo 90%' de acerto."""
}

print("Enviando submissão...")
response = requests.post(URL, json=PAYLOAD)

if response.status_code == 200:
    print("Submissão realizada")
    print(response.json())
else:
    print(f"Erro {response.status_code}: {response.text}")