import os
import glob
import re
from collections import defaultdict
from rank_bm25 import BM25Okapi

# Mapeamento expandido de palavras-chave para apps (vai além dos hardcoded terms)
APP_KEYWORD_MAP = {
    "spotify": ["spotify", "song", "album", "playlist", "music", "track", "artist", "play", "pause", "skip", "shuffle", "repeat", "volume", "queue", "radio", "podcast", "episode"],
    "venmo": ["venmo", "pay", "paid", "owed money", "send money", "transaction", "transfer", "request money", "split bill", "friend payment", "balance"],
    "phone": ["phone", "text", "message", "contact", "sms", "call", "voicemail", "inbox", "sent items", "draft", "mobile"],
    "gmail": ["gmail", "email", "inbox", "thread", "mail", "send email", "receive email", "attachment", "spam", "trash", "archive", "label", "folder"],
    "todoist": ["todoist", "task", "project", "todo", "deadline", "due date", "priority", "reminder", "subtask", "section", "label", "filter"],
    "file_system": ["file", "directory", "folder", "system", "path", "read", "write", "delete", "move", "copy", "rename", "list", "mkdir", "rmdir"],
    "simple_note": ["note", "simple_note", "memo", "sticky note", "annotation", "bookmark", "journal"],
    "splitwise": ["splitwise", "expense", "owe", "balance", "group", "split", "debt", "settle up", "borrow", "lend", "shared expense", "roommate"],
    "amazon": ["amazon", "order", "buy", "product", "cart", "purchase", "wishlist", "prime", "delivery", "tracking", "return", "refund", "review", "rating"],
    "supervisor": ["supervisor", "profile", "account", "password", "credentials", "login", "auth", "authentication"]
}
class API_Retriever:
    def __init__(self, dump_dir="api_docs_dump/apis"):
        """
        Inicializa o RAG lendo os arquivos estáticos gerados pelo dump_api_docs.py
        e construindo o índice vetorial BM25 com cache em memória.
        """
        self.docs = []
        self.filenames = []
        self.app_to_doc_indices = defaultdict(list)  # Mapeia app -> lista de índices de docs

        # Cache para evitar leitura repetida de arquivos
        self._docs_cache = {}
        self._cache_enabled = True
        
        # onde o dump_api_docs.py salvou os resumos
        search_pattern = os.path.join(dump_dir, "*.txt")

        # carrega o conteúdo de todos os arquivos
        for filepath in glob.glob(search_pattern):
            filename = os.path.basename(filepath)

            # Tenta usar cache primeiro
            if self._cache_enabled and filepath in self._docs_cache:
                content = self._docs_cache[filepath]
            else:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if self._cache_enabled:
                        self._docs_cache[filepath] = content

            self.docs.append(content)
            self.filenames.append(filename)

            # Mapeia qual app este doc pertence (extrai do nome do arquivo)
            # Exemplo: "spotify_search_products.txt" -> app: "spotify"
            app_name = filename.split('_')[0] if '_' in filename else filename.replace('.txt', '')
            self.app_to_doc_indices[app_name].append(len(self.docs) - 1)

        if not os.path.isdir(dump_dir):
            raise RuntimeError(f"diretorio {dump_dir} nao encontrado")
        if not self.docs:
            raise RuntimeError(f"Nao foi encontrado nenhum arquivo em {dump_dir}. Rode o dump_api_docs.py")
        
        # tokenizacao: remove pontuacao para espacos, pontos e etc nao atrapalharem a busca
        tokenized_corpus = [self._tokenize(doc) for doc in self.docs]

        # cria o motor de busca instantanea
        self.bm25 = BM25Okapi(tokenized_corpus)

    def _tokenize(self, text):
        """limpa pontuacao e converte para minusculas antes de separar as palavras"""
        text = text.lower()
        # substitui qualquer coisa que nao seja palavra (\w) ou espaco (\s) por um espaco
        text = re.sub(r'[^\w\s]', ' ', text)
        return text.split()


    def _expand_query(self, query):
        """
        Expande a query com sinônimos e termos relacionados baseados no mapeamento de apps.
        Isso melhora o recall do BM25 ao incluir termos semanticamente relacionados.
        """
        expanded_terms = [query]
        query_lower = query.lower()

        # Para cada app, se algum keyword aparecer na query, adiciona todos os outros keywords
        for app, keywords in APP_KEYWORD_MAP.items():
            matching_keywords = [kw for kw in keywords if kw in query_lower]
            if matching_keywords:
                # Adiciona todos os keywords deste app para expandir a busca
                expanded_terms.extend(keywords)
                # Também adiciona o nome do app
                expanded_terms.append(app)

        return " ".join(expanded_terms)

    def search(self, query, top_k=7, boost_relevant_apps=None):
        """
        metodo a ser plugado no 'ctx.retrieve(query)'
        retorna as documentacoes formatadas em uma string pronta para o prompt
        """
        # Expansão de query com sinônimos e termos relacionados
        expanded_query = self._expand_query(query)
        tokenized_query = self._tokenize(expanded_query)
        tokenized_original_query = self._tokenize(query)

        # pega as pontuacoes e extrai os melhores indices 
        scores = self.bm25.get_scores(tokenized_query)
        # App boosting: aumenta o score de docs pertencentes aos apps relevantes
        if boost_relevant_apps:
            for app in boost_relevant_apps:
                app_lower = app.lower()
                # Encontra todos os indices de docs deste app
                doc_indices = self.app_to_doc_indices.get(app_lower, [])
                for idx in doc_indices:
                    # Boost de 50% no score original
                    scores[idx] *= 1.5

        # Extrai os melhores indices combinando scores originais e boosted
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        # Concatena tudo em uma unica string para o LLM (mais facil do LLM ler)
        result_str = "=== MANUAIS DE API RECUPERADOS PARA ESTA TAREFA ===\n\n"

        for i, idx in enumerate(top_indices):
            doc_content = self.docs[idx]
            filename = self.filenames[idx]
            # Truncamento de seguranca para NAO ESTOURAR O LIMITE de tokens
            safe_doc = doc_content[:1500] + ("...\n[TRUNCADO]" if len(doc_content) > 1500 else "")
            result_str += f"--- FERRAMENTA {i+1} ({filename}) ---\n{safe_doc}\n\n"

        return result_str
    
    def __call__(self, query):
        """
        permite que a classe seja chamada como uma funcao: retriever("busca")
        """
        return self.search(query)
    
# bloco de teste rapido
if __name__ == "__main__":
    retriever = API_Retriever()
    print("buscando ferramentas para fazer login no spotify'")
    print(retriever("fazer login no spotify e pegar token"))