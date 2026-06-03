import requests



URL = "https://homodeus-flywheel.fly.dev/api/submit"
PAYLOAD = {
    "token": "fw_live_5bjrfaga745g6p67jxvx",
    "repo": "https://github.com/ViniLucena/flywheel-challenge.git",
    "writeup": """Agente Autônomo para Flywheel | Vinícius Lucena


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
- Filtro de memória por app: antes de montar os prompts, o código analisa a instrução 
com um dicionário keywords_to_apps (ex: "pay" -> venmo, "song" -> spotify). 
Apenas os tokens dos apps necessários são injetados. Isso evita que tokens de Gmail ou 
Todoist distraiam o modelo em tarefas Spotify, por exemplo.
- Exemplo: na primeira tarefa do Spotify, o token é salvo; 
na segunda, o prompt já contém auth_spotify e o login é pulado.

3. Engenharia de Prompts
- O system_prompt atua como protocolo restritivo, não só como algo comportamental.
- Regras principais: "NÃO use apps de fora do escopo da tarefa"; 
"Prefira run_code a múltiplas call_api"; "Sempre pagine com while True e page_index"; 
"Tarefas de ação pura: answer vazia".
- Há uma interceptação do código: dentro do complete_task, se a instrução contém verbos 
de ação pura (send, pay, keep going) e nenhuma palavra de pergunta (how many, list), 
a estrutura força answer="" independentemente do que o modelo gerou.

4. Harness Agêntica e Self_Loop
- O self_loop principal (for passo in range(ctx.max_steps)) orquestra:
  1. Chamada ao modelo com tools=MCP_TOOLS.
  2. Despacho das tool_calls para as tools MCP (ctx.mcp.call).
  3. Adição de resultados ao histórico.
  4. Em caso de erro, adição de mensagem forçando reflexão.
  5. Encerramento ao chamar complete_task.
- Fallback de segurança: se o self_loop termina sem complete_task, a harness chama o encerramento com answer="".
- Resultado prático local: 9/10 acertos (TGC). A única falha foi por limite de passos, não por erro lógico estrutural.""",
    "systems": {
        "mcp": "Orquestração estrita das 5 ferramentas (search_apis, api_doc, call_api, run_code, complete_task) via ctx.mcp.call. Priorização absoluta do run_code para processar paginações massivas localmente no interpretador Python do container.",
        "rag": "Implementação totalmente offline via rank_bm25. O sistema indexa as 457 documentações localmente. O retriever tokeniza a query da tarefa e injeta no prompt apenas os manuais relevantes, com trava de 1500 caracteres, resolvendo o discovery sem LLMs auxiliares.",
        "memory": "Filtro com 'Visão em Túnel'. Para evitar diluição de atenção e alucinação, o agent.py deduz os apps necessários por keywords na instrução (ex: 'pay'-> venmo) e injeta estritamente os tokens de auth úteis. Tokens de outros apps são escondidos do prompt.",
        "self_loop": "Loop principal que despacha ações e força a reflexão. Se ocorre KeyError, reinjeta o erro e obriga o modelo a rodar print(list(obj.keys())) para introspecção. Se a tarefa é de ação pura (ex: send), intercepta e força answer='', garantindo o bypass de formatações erradas e o PASS no oráculo.",
        "tools": "Mecanismo de fallback e interceptação programado no nível do código Python, não dependendo puramente da obediência do modelo ao prompt.",
        "prompts": "O system_prompt atua como protocolo de compilação restritivo: proíbe uso de apps fora do escopo, dita regras de while True para paginação e proíbe alucinação de esquemas."
    }
}

print("Enviando submissão...")
response = requests.post(URL, json=PAYLOAD)

if response.status_code == 200:
    print("Submissão realizada")
    print(response.json())
else:
    print(f"Erro {response.status_code}: {response.text}")