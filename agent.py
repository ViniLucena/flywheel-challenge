import time
import random
import json
from retriever import API_Retriever, APP_KEYWORD_MAP

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

def call_with_retry(func, *args, max_retries=4, base_delay=2, **kwargs):
  for attempt in range(max_retries):
    try:
      # 1 executa a funcao
      resultado = func(*args, **kwargs)
            
      # 2 verifica se a funcao retornou um dicionario com erro (comportamento do ctx.model)
      if isinstance(resultado, dict) and "error" in resultado:
        erro_msg = str(resultado["error"])
        if "429" in erro_msg or "budget exhausted" in erro_msg.lower() or "too many requests" in erro_msg.lower():
          # força a ida para o catch levantando a excecao
          raise Exception(erro_msg)
        else:
          # se for um erro de prompt (ex: content vazio), nao eh falha de rede, entao devolve o erro
          return resultado
            
      # se deu tudo certo, retorna o resultado
      return resultado

    except Exception as e:
      # 3 detecta 429 ou outros erros transitorios (captura do ctx.mcp.call ou do raise acima)
      if "429" in str(e) or "budget exhausted" in str(e).lower() or "too many requests" in str(e).lower():
        if attempt < max_retries - 1: # nao dorme na ultima tentativa falha
          delay = base_delay * (2 ** attempt) + random.uniform(0, 1.0)
          print(f"[RETRY] Tentativa {attempt+1}/{max_retries} falhou com 429. Aguardando {delay:.2f}s...")
          time.sleep(delay)
          continue
            
      # se nao for 429 ou se acabaram as tentativas, explode o erro para o log
      if attempt == max_retries - 1:
        return {"error": f"Falha após {max_retries} tentativas. Erro original: {str(e)}"}

      # para erros nao-transitorios, retorna imediatamente
      return {"error": str(e)}  # remove o continue implicito

def solve(ctx):
  api_schema_cache = {}
  import os
  override = os.getenv("APPWORLD_TASK_OVERRIDE")
  if override:
    ctx.instruction = override
    print(f"[OVERRIDE] Tarefa forçada: {override}")
  instruction = ctx.instruction
  print(f"\n[NOVA TAREFA] {instruction}\n")

  # memoria: carrega o que foi aprendido em tarefas passadas
  memoria_sessao = ctx.memory.read()
  if not isinstance(memoria_sessao, dict):
    memoria_sessao = {}
    
  instruction_lower = instruction.lower()
  # Usa o mapeamento expandido do retriever (muito mais completo que hardcoded terms)
  apps_necessarios = set()
  for app, keywords in APP_KEYWORD_MAP.items():
      if any(kw in instruction_lower for kw in keywords):
          apps_necessarios.add(app)

   # RAG: busca as ferramentas usando o indice local com query expansion e app boosting
  context_docs = rag_retriever.search(instruction, boost_relevant_apps=list(apps_necessarios))
  

  #print(f"\n[DIAGNOSTICO ANTES DO FILTRO] memoria total no disco: {memoria_sessao.keys()}\n")


          
  memoria_filtrada = {}
  for chave, valor in memoria_sessao.items():
    if chave.startswith("auth_"):
      app_name = chave.replace("auth_", "")
      if app_name in apps_necessarios:
        memoria_filtrada[chave] = valor
    else:
      # Filter learned skills by app relevance too
      # Assume skill keys follow pattern: "skill_<app>_<description>"
      # Or check if the skill content mentions irrelevant apps
      should_keep = any(app in chave.lower() for app in apps_necessarios)
      if should_keep or not any(app in str(valor).lower() for app in APP_KEYWORD_MAP.keys()):
          memoria_filtrada[chave] = valor

  #print(f"[DIAGNOSTICO DEPOIS DO FILTRO] apps deduzidos: {apps_necessarios}")
  #print(f"[DIAGNOSTICO DEPOIS DO FILTRO] memoria injetada: {memoria_filtrada.keys()}\n")

  system_prompt = f"""You are an expert software engineer in AppWorld. Solve tasks efficiently and precisely.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 CORE PRINCIPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. **Minimalism**: Use only apps explicitly mentioned or required by the task
2. **Verification**: Always inspect API schemas before calling
3. **Efficiency**: Prefer single run_code scripts over multiple call_api calls
4. **Precision**: Never invent parameters, field names, or credentials

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 EXECUTION WORKFLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1 — ANALYZE & RESTRICT
- Identify ONLY the apps needed for this specific task
- IGNORE all other apps, even if tokens exist in memory
- Example: "Venmo payment" → ONLY Venmo APIs allowed

STEP 2 — CHECK MEMORY
- Review session memory for existing auth tokens and learned patterns
- If token exists but email mismatch (verify via supervisor.show_profile()), re-login

STEP 3 — AUTHENTICATE (if needed)
- If no valid token in memory:
  • Call supervisor.show_profile() and supervisor.show_account_passwords()
  • Login via call_api with real credentials
  • Save full response dict as auth_{{app}}

STEP 4 — DISCOVER APIS
- Use search_apis to find relevant endpoints
- ALWAYS call api_doc BEFORE using any API to see exact parameters
- For list APIs: plan pagination (page_index=0,1,... until empty)

STEP 5 — INSPECT SCHEMAS
- First time seeing API output? Run: print(list(result[0].keys()))
- Look for "*_ids" or "*_items" keys for nested data access
- Use .get('field', None) for safe field access
- For missing attributes, call detail APIs (show_*, get_details)

STEP 6 — EXECUTE
- Single operations (login, create, delete): use call_api
- Complex ops (pagination, filtering, aggregation): use run_code
- In run_code: use ONLY apis.<app>.<api>(...) syntax, NEVER apis.call_api()
- Use datetime.now() for dynamic dates ("last 7 days", "this week")

STEP 7 — FINALIZE IMMEDIATELY
- Once you have the exact answer, call complete_task
- NO extra exploration unless explicitly requested
- Action-only tasks (send, pay, create, delete): complete_task with answer=""
- Question tasks (what, list, how many): complete_task with exact answer

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ CRITICAL CONSTRAINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- **App Isolation**: Task mentions Spotify? ONLY use Spotify APIs. Period.
- **No Hallucination**: Never guess field names or parameters
- **Step Limit**: You have {ctx.max_steps} steps — be efficient
- **Error Recovery**: On KeyError, inspect keys with .keys(), fix, retry ONCE
- **Post-Answer Silence**: After printing final answer in run_code, stop. Next step: complete_task.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🧠 SKILL MEMORY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When you solve something successfully, save the pattern:
Example: "Amazon cheap books → search_products(sort_by='+price', filter product_type contains 'book')"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📚 AVAILABLE KNOWLEDGE (RAG)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{context_docs}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💾 SESSION MEMORY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{json.dumps(memoria_filtrada)}
"""

  messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": "Analyze the task. If required tokens are already in Session Memory, use them directly. Solve efficiently and stop as soon as you have the answer."}
  ]
  encerrou = False
  
  # harness agentica: loop principal
  for passo in range(ctx.max_steps):
    print(f"\n--- Passo {passo+1}/{ctx.max_steps} ---")

      
    # chama o modelo usando o metodo do SDK passando o schema das ferramentas
    resposta = call_with_retry(ctx.model, messages, tools=MCP_TOOLS)

    if isinstance(resposta, dict) and resposta.get("error"):
      print(f"erro de conexao: {resposta['error']}")
      break
    elif isinstance(resposta, list):
      print(f"erro da API: {resposta}")
      break
    elif not isinstance(resposta, dict):
      print(f"Resposta inesperada do modelo: {type(resposta)} - {resposta}")
      break

    # extrai a mensagem do modelo (agora resposta é garantidamente um dict)
    msg = resposta.get("choices", [{}])[0].get("message", {})

    # garantindo que a mensagem que volta para o historico eh um dict valido
    if hasattr(msg, "model_dump"):
      msg_dict = msg.model_dump(exclude_none=True)
    else:
      msg_dict = msg if isinstance(msg, dict) else dict(msg)
    
    # se content for vazio ou None, injeta um texto padrão
    if not msg_dict.get("content"):
      msg_dict["content"] = "executing tool"
    
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

      if t_name == "complete_task":
          instruction_lower = ctx.instruction.lower()
          question_words = ["how many", "list", "what", "which", "give me", "tell me", "show me"]
          action_verbs = ["send", "pay", "move", "go", "keep going", "reach", "create", "delete", "follow", "like", "comment", "post", "add", "remove", "curtir", "comentar"]
          
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
          
          resultado = call_with_retry(ctx.mcp.call, t_name, t_args)
          encerrou = True
        
      else:
          if t_name == "call_api":
            app = t_args.get("app")
            api = t_args.get("api")
            cache_key = f"{app}:{api}"
            if cache_key not in api_schema_cache:
              print(f"[INTROSPECÇÃO] Obtendo documentação de {app}.{api}...")
              doc_result = call_with_retry(ctx.mcp.call, "api_doc", {"app": app, "api": api})
              api_schema_cache[cache_key] = doc_result
              # Injeta o schema no histórico como mensagem de sistema
              messages.append({
                  "role": "system",
                  "content": f"Parâmetros da API {app}.{api}:\n{json.dumps(doc_result, indent=2)[:1500]}"
                })
            resultado = call_with_retry(ctx.mcp.call, t_name, t_args)
          elif t_name in ["run_code", "search_apis", "api_doc"]:
            resultado = call_with_retry(ctx.mcp.call, t_name, t_args)
          else:
            resultado = ctx.mcp.call(t_name, t_args)

                
      
      # adiciona o resultado da ferramenta ao historico de mensagens
      conteudo_json = json.dumps(resultado, default=str)
      # se a serialização ficar vazia, devolve uma confirmação ---
      if not conteudo_json or conteudo_json == '""' or conteudo_json.isspace():
        conteudo_json = '"ok"'
          
      messages.append({
        "role":"tool",
        "tool_call_id": t_id,
        "content":conteudo_json
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

