import time
import random
import json
import hashlib
from retriever import API_Retriever, APP_KEYWORD_MAP

rag_retriever = API_Retriever()

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
            "app": {"type": "string", "description": "Nome do app"},
            "api": {"type": "string", "description": "Nome da api"}
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
                  "arguments": {"type": "object", "description": "Dicionário com os argumentos da API"}
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
              "properties": {"code": {"type": "string", "description": "Código Python"}},
              "required": ["code"]
          }
      }
  },
  {
      "type":"function",
      "function":{
          "name":"complete_task",
          "description":"OBRIGATÓRIO para encerrar a tarefa.",
          "parameters":{
              "type":"object",
              "properties": {"answer": {"type": "string", "description": "Resposta final"}}
          }
      }
  }
]

def _limpar_memoria(memoria, max_entries=100):
    """
    Higiene de memória: deduplica, consolida e trunca.
    Lida com formatos mistos (strings legacy e dicts novos).
    """
    if not isinstance(memoria, dict) or not memoria:
        return memoria

    limpa = {}
    tokens_auth = {}
    skills = {}
    workflows = {}
    outros = []

    for chave, valor in memoria.items():
        # Normalização: converte string legacy para dict padronizado
        if isinstance(valor, str):
            valor = {"token": valor, "timestamp": 0}
        
        if not isinstance(valor, dict):
            continue
            
        ts = valor.get("timestamp", 0)
        
        # 1. Tokens de Auth
        if chave.startswith("auth_"):
            app = chave.replace("auth_", "")
            # Mantém o mais recente. Se timestamps iguais (0), mantém o que processou por último (ok)
            if app not in tokens_auth or ts > tokens_auth[app][2]:
                tokens_auth[app] = (chave, valor, ts)
        
        # 2. Skills (Consolidação Corrigida)
        elif chave.startswith("skill_"):
            partes = chave.split("_", 2)
            if len(partes) >= 3:
                skill_id = f"{partes[1]}_{partes[2]}"
                
                # Estratégia: Sempre manter a base da mais recente, mas fundir dados da mais antiga
                if skill_id in skills:
                    existente = skills[skill_id]
                    ts_existente = existente.get("timestamp", 0)
                    
                    # Define qual é a base (mais recente) e qual é a complementar (mais antiga)
                    if ts >= ts_existente:
                        base, complementar = valor, existente
                    else:
                        base, complementar = existente, valor
                    
                    # Funde argumentos e capacidades na base
                    args_base = set(base.get("arguments_pattern", []))
                    args_comp = set(complementar.get("arguments_pattern", []))
                    base["arguments_pattern"] = list(args_base | args_comp)
                    
                    caps_base = base.get("capabilities", {})
                    caps_comp = complementar.get("capabilities", {})
                    base["capabilities"] = {**caps_base, **caps_comp}
                    
                    # Garante que o timestamp seja o maior
                    base["timestamp"] = max(ts, ts_existente)
                    
                    skills[skill_id] = base
                else:
                    skills[skill_id] = valor

        # 3. Workflows e Outros
        elif chave.startswith("workflow_"):
            workflows[chave] = valor
        else:
            outros.append((chave, valor, ts))

    # Reconstrução
    for app, (chave, valor, ts) in tokens_auth.items():
        limpa[chave] = valor

    for skill_id, valor in skills.items():
        limpa[f"skill_{skill_id}"] = valor

    for chave, valor in workflows.items():
        limpa[chave] = valor

    outros.sort(key=lambda x: x[2], reverse=True)
    for chave, valor, ts in outros:
        limpa[chave] = valor

    # Truncamento
    if len(limpa) > max_entries:
        todos = [(k, v) for k, v in limpa.items()]
        todos.sort(key=lambda x: x[1].get("timestamp", 0), reverse=True)
        limpa = dict(todos[:max_entries])
        print(f"[HYGIENE] Memória truncada para {max_entries} entries")

    return limpa

def call_with_retry(func, *args, max_retries=2, base_delay=2, **kwargs):
  for attempt in range(max_retries):
    try:
      resultado = func(*args, **kwargs)
      if isinstance(resultado, dict) and "error" in resultado:
        erro_msg = str(resultado["error"])
        if "429" in erro_msg or "budget exhausted" in erro_msg.lower():
          raise Exception(erro_msg)
        return resultado
      return resultado
    except Exception as e:
      if "429" in str(e) or "budget exhausted" in str(e).lower():
        if attempt < max_retries - 1:
          delay = base_delay * (2 ** attempt) + random.uniform(0, 1.0)
          print(f"[RETRY] 429 detected. Waiting {delay:.2f}s...")
          time.sleep(delay)
          continue
      if attempt == max_retries - 1:
        return {"error": f"Falha após {max_retries} tentativas: {str(e)}"}
      return {"error": str(e)}

def solve(ctx):
  api_schema_cache = {}
  import os
  override = os.getenv("APPWORLD_TASK_OVERRIDE")
  if override:
    ctx.instruction = override
    print(f"[OVERRIDE] {override}")
  
  instruction = ctx.instruction
  print(f"\n[NOVA TAREFA] {instruction}\n")

  memoria_sessao = ctx.memory.read()
  if not isinstance(memoria_sessao, dict):
    memoria_sessao = {}

  instruction_lower = instruction.lower()
  apps_necessarios = set()
  for app, keywords in APP_KEYWORD_MAP.items():
      if any(kw in instruction_lower for kw in keywords):
          apps_necessarios.add(app)

  # RAG com fallback inteligente (não chama LLM se keywords funcionarem)
  context_docs = rag_retriever.search(instruction, boost_relevant_apps=list(apps_necessarios), ctx=ctx)

  # Filtra memória
  memoria_filtrada = {}
  for chave, valor in memoria_sessao.items():
    if chave.startswith("auth_"):
      app_name = chave.replace("auth_", "")
      if app_name in apps_necessarios:
        memoria_filtrada[chave] = valor
    else:
      should_keep = any(app in chave.lower() for app in apps_necessarios)
      if should_keep or not any(app in str(valor).lower() for app in APP_KEYWORD_MAP.keys()):
          memoria_filtrada[chave] = valor

  system_prompt = f"""You are an expert AppWorld engineer.
Principles: Minimalism, Verification, Efficiency, Precision.
Workflow: Analyze -> Check Memory -> Auth (if needed) -> Discover (api_doc) -> Inspect Keys -> Execute -> Finalize.
Constraints: App Isolation (ONLY use mentioned apps), No Hallucination, Step Limit ({ctx.max_steps}).
Error Recovery: On KeyError, inspect keys first.

AVAILABLE KNOWLEDGE (RAG):
{context_docs}

SESSION MEMORY (Filtered):
{json.dumps(memoria_filtrada)}
"""

  messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": "Solve efficiently. Use memory tokens if available."}
  ]
  encerrou = False
  
  for passo in range(ctx.max_steps):
    print(f"\n--- Passo {passo+1}/{ctx.max_steps} ---")
    resposta = call_with_retry(ctx.model, messages, tools=MCP_TOOLS)

    if isinstance(resposta, dict) and resposta.get("error"):
      print(f"Erro conexão: {resposta['error']}")
      break
    elif not isinstance(resposta, dict):
      break

    msg = resposta.get("choices", [{}])[0].get("message", {})
    if hasattr(msg, "model_dump"): msg_dict = msg.model_dump(exclude_none=True)
    else: msg_dict = msg if isinstance(msg, dict) else dict(msg)
    
    if not msg_dict.get("content"): msg_dict["content"] = "executing"
    messages.append(msg_dict)

    tool_calls = msg_dict.get("tool_calls")
    if not tool_calls:
      messages.append({"role":"user", "content":"Execute a tool or complete_task."})
      continue
    
    for tc in tool_calls:
      t_id = tc["id"]
      t_name = tc["function"]["name"]
      try: t_args = json.loads(tc["function"]["arguments"])
      except: t_args = {}

      print(f"-> {t_name}")

      if t_name == "complete_task":
          # Detecção de ação pura (verbs em inglês apenas)
          question_words = ["how many", "list", "what", "which", "give me", "tell me", "show me"]
          action_verbs = ["send", "pay", "move", "go", "reach", "create", "delete", "follow", "like", "comment", "post", "add", "remove"]
          
          is_action = not any(qw in instruction_lower for qw in question_words) and \
                      any(av in instruction_lower for av in action_verbs)
                  
          if is_action:
            t_args["answer"] = ""
          
          resultado = call_with_retry(ctx.mcp.call, t_name, t_args)
          encerrou = True
      else:
          if t_name == "call_api":
            app, api = t_args.get("app"), t_args.get("api")
            cache_key = f"{app}:{api}"
            if cache_key not in api_schema_cache:
              doc_result = call_with_retry(ctx.mcp.call, "api_doc", {"app": app, "api": api})
              api_schema_cache[cache_key] = doc_result
              messages.append({"role": "system", "content": f"Schema {app}.{api}: {json.dumps(doc_result)[:1000]}"})
            resultado = call_with_retry(ctx.mcp.call, t_name, t_args)
          else:
            resultado = call_with_retry(ctx.mcp.call, t_name, t_args)

      conteudo_json = json.dumps(resultado, default=str)
      if not conteudo_json or conteudo_json == '""': conteudo_json = '"ok"'
      messages.append({"role":"tool", "tool_call_id": t_id, "content":conteudo_json})

      # RECUPERAÇÃO DE ERROS (Sem ctx.reflect)
      if isinstance(resultado, dict) and "error" in resultado:
        erro_msg = str(resultado["error"])
        recovery_prompt = ""
        
        if "401" in erro_msg or "unauthorized" in erro_msg.lower():
          recovery_prompt = f"⚠️ 401 Error in {t_args.get('app')}. ACTION: Re-login via supervisor.show_profile() + show_account_passwords(), then retry."
        elif "keyerror" in erro_msg.lower() or "attribute" in erro_msg.lower():
          recovery_prompt = "⚠️ Data Error. ACTION: Stop. Use run_code to print(result.keys()). Inspect and fix field name."
        elif "429" in erro_msg:
          recovery_prompt = "⚠️ Rate Limit. ACTION: Wait or batch operations in run_code."
        elif "404" in erro_msg:
          recovery_prompt = "⚠️ 404 Not Found. ACTION: Verify IDs or check pagination."
        else:
          recovery_prompt = f"⚠️ Error: {erro_msg}. Analyze and fix."

        messages.append({"role": "user", "content": recovery_prompt})
        print(f"[RECOVERY] Injected prompt for error.")

    if encerrou:
      print("Tarefa finalizada. Salvando memória...")
      memoria_atual = ctx.memory.read()
      if not isinstance(memoria_atual, dict): memoria_atual = {}

      # Salva tokens com formato PADRONIZADO
      for chave, valor in memoria_filtrada.items():
        if chave.startswith("auth_"):
          # Garante formato dict com timestamp
          token_val = valor if isinstance(valor, str) else valor.get("token", str(valor))
          memoria_atual[chave] = {
            "token": token_val,
            "timestamp": time.time(),
            "source": "current_task"
          }

      # Skill Extraction
      for i, msg in enumerate(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
          for tc in msg["tool_calls"]:
            if tc["function"]["name"] == "call_api":
              t_args = json.loads(tc["function"]["arguments"])
              app, api = t_args.get("app"), t_args.get("api")
              arguments = t_args.get("arguments", {})
              
              # Verifica sucesso
              for j in range(i+1, min(i+3, len(messages))):
                if messages[j].get("role") == "tool":
                  try:
                    result = json.loads(messages[j].get("content", "{}"))
                    if isinstance(result, dict) and "error" not in result:
                      skill_key = f"skill_{app}_{api}"
                      # Cria ou atualiza skill (a limpeza fará a fusão depois)
                      if skill_key not in memoria_atual:
                        skill_data = {
                          "timestamp": time.time(),
                          "arguments_pattern": list(arguments.keys()),
                          "result_keys": list(result.keys())[:10] if isinstance(result, dict) else [],
                          "capabilities": {}
                        }
                        if "page_index" in arguments: skill_data["capabilities"]["supports_pagination"] = True
                        if "sort_by" in arguments: skill_data["capabilities"]["supports_sorting"] = True
                        memoria_atual[skill_key] = skill_data
                  except: pass
                  break

      # Workflow Saving (Chave mais única)
      if instruction_lower:
        workflow_details = []
        apps_used = set()
        for msg in messages:
          if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
              t_args = json.loads(tc["function"]["arguments"])
              if tc["function"]["name"] == "call_api" and t_args.get("app"):
                apps_used.add(t_args["app"])
                workflow_details.append(f"{t_args['app']}.{t_args.get('api')}")
        
        if apps_used:
          # Hash dos apps + primeiras palavras para unicidade
          apps_hash = hashlib.md5(str(sorted(apps_used)).encode()).hexdigest()[:6]
          instr_preview = "_".join(instruction_lower.split()[:4])
          workflow_key = f"workflow_{apps_hash}_{instr_preview}"
          
          if workflow_key not in memoria_atual:
            memoria_atual[workflow_key] = {
              "apps_used": list(apps_used),
              "api_sequence": workflow_details[:10],
              "completed": True,
              "timestamp": time.time()
            }

      # Limpeza e Escrita
      memoria_limpa = _limpar_memoria(memoria_atual, max_entries=100)
      for chave, valor in memoria_limpa.items():
        ctx.memory.write(chave, valor)
      print(f"[MEMÓRIA] {len(memoria_limpa)} entries salvas.")
      break

  if not encerrou:
    print("Timeout. Forçando complete_task.")
    ctx.mcp.call("complete_task", {"answer":""})
    # Fallback também salva memória padronizada
    memoria_atual = ctx.memory.read()
    if not isinstance(memoria_atual, dict): memoria_atual = {}
    for chave, valor in memoria_filtrada.items():
      if chave.startswith("auth_"):
        token_val = valor if isinstance(valor, str) else valor.get("token", str(valor))
        memoria_atual[chave] = {"token": token_val, "timestamp": time.time()}
    
    memoria_limpa = _limpar_memoria(memoria_atual, max_entries=100)
    for chave, valor in memoria_limpa.items():
      ctx.memory.write(chave, valor)