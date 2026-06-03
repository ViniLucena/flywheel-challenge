import json
from retriever import API_Retriever

rag_retriever = API_Retriever()

# definicao dos schemas das 5 ferramentas do appworld
# orienta o que o gemini pode fazer e quais argumentos enviar

MCP_TOOLS = [
  {
      "type":"function",
      "function":{
          "name":"search_apis",
          "description":"busca nos 457 docs de API. Acha a ferramenta certa",
          "parameters":{
              "type":"object",
              "properties":{"query":{"type":"string", "description":"Termo de busca"}},
              "required":["query"]
          }
      }
  },
  {
    "type":"function",
    "function":{
      "name":"api_doc",
      "description":"Lê os parâmetros exatos de uma API antes de chamar",
      "parameters":{
          "type":"object",
          "properties":{
            "app": {"type": "string", "description": "Nome do app (ex: spotify)"},
            "api": {"type": "string", "description": "Nome da api (ex: login)"}
          },
              "required":["app", "api"]
      }
    }
  },
  {
      "type":"function",
      "function":{
          "name":"call_api",
          "description":"Faz uma chamada precisa a uma API única",
          "parameters":{
              "type":"object",
              "properties":{
                  "app": {"type": "string"},
                  "api": {"type": "string"},
                  "arguments": {"type": "object", "description": "Dicionário com os argumentos da API (ex: {'username': '...', 'password': '...'})"}
              },
              "required":["app", "api", "arguments"]
          }
      }
  },
  {
      "type":"function",
      "function":{
          "name":"run_code",
          "description":"Executa Python com o objeto 'apis' no escopo",
          "parameters":{
              "type":"object",
              "properties": {"code": {"type": "string", "description": "Código Python a ser executado"}},
              "required": ["code"]
          }
      }
  },
  {
      "type":"function",
      "function":{
          "name":"complete_task",
          "description":"OBRIGATÓRIO para encerrar a tarefa. Envia a resposta final ao Oráculo",
          "parameters":{
              "type":"object",
              "properties": {"answer": {"type": "string", "description": "A resposta final exata (deixe em branco se for tarefa apenas de ação)"}}
          }
      }
  }
]

def solve(ctx):
  import os
  override = os.getenv("APPWORLD_TASK_OVERRIDE")
  if override:
    ctx.instruction = override
    print(f"[OVERRIDE] Tarefa forçada: {override}")
  instruction = ctx.instruction
  print(f"\n[NOVA TAREFA] {instruction}\n")

  # RAG: busca as ferramentas usando o indice local
  context_docs = rag_retriever.search(instruction)

  # memoria: carrega o que foi aprendido em tarefas passadas
  memoria_sessao = ctx.memory.read()
  if not isinstance(memoria_sessao, dict):
    memoria_sessao = {}

  #print(f"\n[DIAGNOSTICO ANTES DO FILTRO] memoria total no disco: {memoria_sessao.keys()}\n")

  instruction_lower = instruction.lower()
  
  # dict de mapeamento de intencao para o respectivo app
  keywords_to_apps = {
      "spotify": ["spotify", "song", "album", "playlist", "music", "track"],
      "venmo": ["venmo", "pay", "paid", "owed money", "send money", "transaction"],
      "phone": ["phone", "text", "message", "contact", "sms"],
      "gmail": ["gmail", "email", "inbox", "thread"],
      "todoist": ["todoist", "task", "project", "todo"],
      "file_system": ["file", "directory", "folder", "system"],
      "simple_note": ["note", "simple_note"],
      "splitwise": ["splitwise", "expense", "owe", "balance", "group"],
      "amazon": ["amazon", "order", "buy", "product", "cart"]
  }
  
  apps_necessarios = set()
  for app, keywords in keywords_to_apps.items():
      if any(kw in instruction_lower for kw in keywords):
          apps_necessarios.add(app)
          
  memoria_filtrada = {}
  for chave, valor in memoria_sessao.items():
      # se for token de autenticação, passa se o app for necessário
      if chave.startswith("auth_"):
          app_name = chave.replace("auth_", "")
          if app_name in apps_necessarios:
              memoria_filtrada[chave] = valor
      else:
          # mantem na memoria aprendizados gerais ou regras que nao sao tokens
          memoria_filtrada[chave] = valor

  #print(f"[DIAGNOSTICO DEPOIS DO FILTRO] apps deduzidos: {apps_necessarios}")
  #print(f"[DIAGNOSTICO DEPOIS DO FILTRO] memoria injetada: {memoria_filtrada.keys()}\n")

  system_prompt = f"""Você é um engenheiro de software no AppWorld. Resolva a tarefa com eficiência.

=== PROTOCOLO OBRIGATÓRIO ===

1. ENTENDA a tarefa e identifique quais aplicativos são necessários.
2. Consulte a MEMÓRIA DA SESSÃO (tokens e habilidades salvas) antes de qualquer ação.
3. Para qualquer app que precise de autenticação:
   - Se não houver token na memória, chame supervisor.show_profile() e supervisor.show_account_passwords() para obter credenciais reais.
   - Faça login usando call_api. NUNCA invente credenciais.
   - Salve o dicionário completo de resposta (access_token, refresh_token, etc.) como auth_{{app}}.
4. DESCOBERTA DE APIS:
   - Use search_apis para encontrar endpoints relevantes.
   - Leia api_doc antes de usar uma API desconhecida.
5. INTROSPECÇÃO DE ESQUEMAS:
   - No primeiro resultado de qualquer listagem, execute um pequeno run_code para imprimir as chaves do primeiro item: print(list(resultado[0].keys())).
   - Use .get('chave', fallback) para acessar campos.
   - Se um item de resumo contiver uma chave que termina em "_ids" ou "_items", use-a diretamente para obter IDs aninhados (ex: album['song_ids']).
6. EXECUÇÃO:
   - Para operações pontuais (login, criar um item, deletar), use call_api.
   - Para paginação, filtros, agregações ou operações em massa, escreva um único script em run_code.
   - Todas as APIs de listagem devem ser paginadas: page_index = 0,1,... até resposta vazia.
7. FINALIZAÇÃO:
   - Assim que obtiver a resposta exata solicitada (ex: o produto mais barato, a lista de músicas), chame complete_task com a resposta.
   - NÃO faça passos adicionais (explorar outros termos, adicionar ao carrinho, etc.) a menos que a tarefa peça explicitamente.
8. RECUPERAÇÃO DE ERROS:
   - Se run_code falhar com KeyError, trace o erro, inspecione as chaves do objeto (print(objeto.keys())) e corrija o nome do campo.
   - Retry no máximo uma vez. Se falhar novamente, ajuste o plano e chame complete_task com uma explicação.
9. MEMÓRIA DE HABILIDADES:
   - Quando você resolver uma tarefa com sucesso, registre o procedimento (ex: "para buscar livros baratos na Amazon, use search_products com sort_by='+price' e filtre product_type contendo 'book'").
   - Ao iniciar uma tarefa semelhante, recupere essa habilidade da memória.
   

=== LIMITES ===
- Você tem no máximo {ctx.max_steps} passos.
- Prefira run_code a múltiplas call_api para economizar passos.
- Nunca invente parâmetros ou nomes de campos.
- **PROIBIDO: NÃO use Gmail, Todoist, Simple Note, File System ou qualquer outro app não mencionado na tarefa.** Mesmo que a memória contenha tokens para eles, ignore-os completamente. Se a tarefa fala apenas de Spotify, apenas APIs do Spotify são permitidas.
- **Verificação de identidade:** No início da tarefa, chame supervisor.show_profile(). Se o email retornado for diferente do email associado ao token salvo (ex: token_spotify foi gerado para outro usuário), ignore o token e faça um novo login.
- **Dentro de run_code, use APENAS a sintaxe `apis.<app>.<api>(...)`. NUNCA use `apis.call_api()` (ela não funciona).**
- APÓS IMPRIMIR A RESPOSTA FINAL no run_code, NÃO execute mais nenhum comando. No passo seguinte, chame complete_task com a resposta. Se você já tem a resposta e ainda há passos restantes, ignore-os e finalize.
- **Tarefas de ação pura:** Se a instrução não pedir explicitamente uma resposta textual (ex: "send", "go to", "keep going", "pay", "text"), chame `complete_task` com `""` (string vazia). Não invente respostas descritivas.

=== FONTES DE DADOS DO SPOTIFY ===
- "song library" → use show_song_library. Cada item tem campo 'song_id'.
- "album library" → use show_album_library. Cada item tem campo 'song_ids' (lista de IDs).
- "playlist library" → use show_playlist_library. Cada item tem campo 'song_ids' (lista de IDs).
- "liked songs" → use show_liked_songs (apenas se a tarefa mencionar "liked" ou "curtidas").
- Para tarefas que pedem "top N most played" de um gênero específico:
   1. Colete todos os song_ids das três primeiras fontes (SEM liked, a menos que pedido).
   2. Para cada ID, chame show_song para obter genre e play_count.
   3. Filtre pelo gênero exato (case-insensitive).
   4. Ordene por play_count decrescente e pegue os N primeiros.
   5. Retorne os títulos em CSV e chame complete_task IMEDIATAMENTE.
- Para tarefas de contagem ("How many unique songs"):
   1. Colete os song_ids das três primeiras fontes (song_library, album_library, playlist_library).
   2. Conte os IDs únicos.
   3. Responda APENAS com o número (ex: "81").
- **Para tarefas que pedem uma lista ou número (ex: "top N", "how many", "list of"):** retorne a resposta e chame `complete_task` com ela.
- **Para tarefas que são apenas ações (ex: "send", "keep going", "pay"):** execute as ações e chame `complete_task` com `""`.

=== CONHECIMENTO INICIAL (RAG) ===
{context_docs}

=== MEMÓRIA DA SESSÃO ===
{json.dumps(memoria_filtrada)}
"""
  
  messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": "Analise a tarefa. Se os tokens necessários já estiverem na Memória da Sessão, use-os direto. Resolva de forma direta e rápida."}
  ]

  encerrou = False
  
  # harness agentica: loop principal
  for passo in range(ctx.max_steps):
    print(f"\n--- Passo {passo+1}/{ctx.max_steps} ---")

      
    # chama o modelo usando o metodo do SDK passando o schema das ferramentas
    resposta = ctx.model(messages,tools=MCP_TOOLS)

    if isinstance(resposta, dict) and resposta.get("error"):
      print(f"erro de conexao: {resposta['error']}")
      break
    elif isinstance(resposta, list):
      print(f"erro da API: {resposta}")
      break
      

    # extrai a mensagem do modelo
    msg = resposta.get("choices", [{}])[0].get("message", {})

    # garantindo que a mensagem que volta para o historico eh um dict valido
    if hasattr(msg, "model_dump"):
      msg_dict = msg.model_dump(exclude_none=True)
    else:
      msg_dict = msg if isinstance(msg, dict) else dict(msg)
    
    messages.append(msg_dict)

    #if msg_dict.get("content"):
      #print(f"[pensamento]: {msg_dict.get('content')}")

    tool_calls = msg_dict.get("tool_calls")
    if not tool_calls:
      #print("[aviso]: modelo nao chamou ferramenta, forçando continuacao...")
      messages.append({"role":"user", "content":"você nao executou nenhuma acao. Use uma ferramenta ou chame complete_task"})
      continue
    
    # execucao das ferramentas
    for tc in tool_calls:
      t_id = tc["id"]
      t_name = tc["function"]["name"]

      # tenta decodificar os argumentos JSON gerados pelo modelo
      try:
        t_args = json.loads(tc["function"]["arguments"])
      except json.JSONDecodeError:
        t_args = {}

      print(f"executando: {t_name} com {t_args}")

      try:
        if t_name == "complete_task":
          instruction_lower = ctx.instruction.lower()
          question_words = ["how many", "list", "what", "which", "give me", "tell me", "show me"]
          action_verbs = ["send", "pay", "move", "go", "keep going", "reach", "create", "delete"]
          
          is_action = False
          # se nao tem palavra de pergunta explícita E tem verbo de acao forte
          if not any(qw in instruction_lower for qw in question_words):
              if any(av in instruction_lower for av in action_verbs):
                  is_action = True
                  
          if is_action:
              print("[INTERCEPTAÇÃO] tarefa identificada como AÇÃO pura. Forçando answer=''")
              if isinstance(t_args, dict):
                  t_args["answer"] = ""
              else:
                  t_args = {"answer": ""}
          
          resultado = ctx.mcp.call("complete_task", t_args if t_args else {"answer":""})
          encerrou = True
        
        else:
          # para todas as outras ferramentas (search_apis, api_doc, call_api, run_code)
          resultado = ctx.mcp.call(t_name, t_args)
                
      except Exception as e:
        resultado = {"error":f"exceção interna: {str(e)}"}

      # adiciona o resultado da ferramenta ao historico de mensagens
      messages.append({
        "role":"tool",
        "tool_call_id": t_id,
        "content":json.dumps(resultado, default=str)
      })

      # erros com a API: se a API reclamar (ex: token faltando), avisa o modelo
      if isinstance(resultado, dict) and "error" in resultado:
        erro_msg = resultado["error"]
        print(f"erro na ferramenta: {erro_msg}")
        ctx.reflect(f"erro em {t_name}:{erro_msg}")
        messages.append({
          "role": "user", 
          "content": f"A chamada falhou com o erro: '{erro_msg}'. Analise o problema (ex: falta de access_token, parâmetro errado), corrija e tente novamente."
        })

      # se o agente chama a complete_task, sai do loop
    if encerrou:
      print("tarefa finalizada")
      break

  # se estourar o limite de 50 passos sem encerrar, força o encerramento
  if not encerrou:
    print("limite de passos atingido, printando resposta vazia")
    ctx.mcp.call("complete_task", {"answer":""})      

