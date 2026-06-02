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
  instruction = ctx.instruction
  print(f"\n[NOVA TAREFA] {instruction}\n")

  # RAG: busca as ferramentas usando o indice local
  context_docs = rag_retriever.search(instruction)

  # memoria: carrega o que foi aprendido em tarefas passadas
  memoria_sessao = ctx.memory.read()
  if not isinstance(memoria_sessao, dict):
    memoria_sessao = {}

  print(f"\n[DIAGNOSTICO] Memória carregada do disco: {memoria_sessao}\n")

  # PROMPT DO SISTEMA:
  system_prompt = f"""Você é um Engenheiro de Software Autônomo operando no AppWorld.
    Sua tarefa: {instruction}

    === REGRAS ===
    1. Você tem no máximo {ctx.max_steps} passos. NÃO gaste turnos com `search_apis` ou `api_doc` se a informação já estiver no CONHECIMENTO INICIAL abaixo.
    2. Sempre que possível, escreva um único script em `run_code` para fazer todo o processamento de dados, paginação e filtragem de uma vez só.
    3. Assim que obtiver o resultado final via print do `run_code`, chame IMEDIATAMENTE a ferramenta `complete_task` informando a resposta. Não faça checagens repetitivas.

    === REGRAS ESTRITAS ===
    1. PAGINAÇÃO: Se uma API retornar uma lista, SEMPRE use o `run_code` para fazer paginação (page_index=0, 1...) até vir vazio.
    2. PREVENÇÃO DE DANO: NUNCA delete ou altere um registro a menos que a instrução peça explicitamente.
    3. LOGIN E ATALHOS MENTAIS: Verifique a MEMÓRIA DA SESSÃO. 
       - Se NÃO houver token do app alvo: use `supervisor.show_account_passwords` via `call_api` para descobrir a senha e faça o login.
       - Se o token JÁ ESTIVER na memória: É EXTREMAMENTE PROIBIDO usar `search_apis` ou `api_doc`. Vá direto para a escrita do script em `run_code`! 
       - ATALHOS CONHECIDOS (Use via apis.nome_do_app.nome_da_api): Para o Spotify, você já conhece `show_song_library`, `show_album_library`, `show_playlist_library`, `show_song`, `show_genres`.

    === CONHECIMENTO INICIAL (RAG) ===
    {context_docs}

    === MEMÓRIA DA SESSÃO (TOKENS SALVOS) ===
    {json.dumps(memoria_sessao)}
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

    if msg_dict.get("content"):
      print(f"[pensamento]: {msg_dict.get('content')}")

    tool_calls = msg_dict.get("tool_calls")
    if not tool_calls:
      print("[aviso]: modelo nao chamou ferramenta, forçando continuacao...")
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

      # chama a ferramenta real no simulator
      try:
        if t_name == "complete_task":
          resultado = ctx.mcp.call("complete_task", t_args if t_args else {"answer":""})
          encerrou = True
        else:
          resultado = ctx.mcp.call(t_name, t_args)
          
          print("\n[DEBUG]")
          print(f"API chamada: {t_name}")
          print(f"tipo do retorno: {type(resultado)}")
                    
          # Limita o tamanho do output na tela para não travar o terminal se for um JSON gigante
          res_str = str(resultado)
          print(f"Conteúdo: {res_str[:200]} {'...' if len(res_str) > 200 else ''}\n")
          
          if t_name == "call_api" and isinstance(resultado, dict):
            token_val = None
            
            # extraindo os dados da chave 'result'
            dados = resultado.get("result", resultado)
            
            # caso a API de login retorne a string direto dentro do 'result'
            if isinstance(dados, str) and t_args.get("api") == "login":
              token_val = dados
              
            # caso a API retorne um dicionário aninhado
            elif isinstance(dados, dict):
              # vasculha as chaves procurando padroes de credenciais
              for k,v in dados.items():
                if isinstance(v, str) and ('token'in k.lower() or 'key' in k.lower()):
                  token_val = v
                  break
                
            # salva
            if token_val:
              app_alvo = t_args.get("app", "unknown")
              print(f"[memoria] token detectado para '{app_alvo}'. Salvando...")
              
              ctx.memory.write(f"token_{app_alvo}", token_val)
                
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

