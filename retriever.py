import os
import glob
import re
from collections import defaultdict
from rank_bm25 import BM25Okapi

_query_rewrite_cache = {}

def _rewrite_query_with_llm(query, ctx=None):
    """
    Reescreve query usando LLM. Usado apenas como fallback se BM25 falhar.
    """
    if query in _query_rewrite_cache:
        return _query_rewrite_cache[query]

    if ctx is None or not hasattr(ctx, 'model'):
        return query

    try:
        prompt = f"""Convert this task to technical API keywords (app, method, params).
Task: {query}
Keywords:"""
        messages = [{"role": "user", "content": prompt}]
        # Chamada simples sem tools
        response = ctx.model(messages, max_tokens=40)

        if isinstance(response, dict) and "choices" in response:
            rewritten = response["choices"][0]["message"]["content"].strip().replace('"', '')
            _query_rewrite_cache[query] = rewritten
            print(f"[RAG] LLM Rewrote: '{query}' -> '{rewritten}'")
            return rewritten
    except Exception:
        pass # Falha silenciosa
    
    return query

def _rerank_results(query, docs, filenames, scores, top_k=7):
    if len(docs) <= top_k:
        return list(range(len(docs)))

    # Pega top-20 para re-ranquear
    top_20_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:20]
    candidates = []
    query_terms = set(query.lower().split())

    for idx in top_20_idx:
        # Overlap semântico simples
        doc_terms = set(docs[idx][:500].lower().split())
        overlap = len(query_terms & doc_terms) / max(len(query_terms), 1)
        candidates.append({
            'idx': idx,
            'score': (0.5 * scores[idx]) + (0.5 * overlap * 10) # Peso 50/50
        })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return [c['idx'] for c in candidates[:top_k]]

APP_KEYWORD_MAP = {
    "spotify": ["spotify", "song", "album", "playlist", "music", "track", "artist", "play", "podcast"],
    "venmo": ["venmo", "pay", "money", "transaction", "transfer", "request", "split", "balance"],
    "phone": ["phone", "text", "message", "contact", "sms", "call", "inbox"],
    "gmail": ["gmail", "email", "inbox", "thread", "mail", "attachment", "spam"],
    "todoist": ["todoist", "task", "project", "todo", "deadline", "due", "priority"],
    "file_system": ["file", "directory", "folder", "path", "read", "write", "delete"],
    "simple_note": ["note", "memo", "sticky", "journal"],
    "splitwise": ["splitwise", "expense", "owe", "balance", "group", "split", "debt"],
    "amazon": ["amazon", "order", "product", "cart", "purchase", "wishlist", "tracking"],
    "supervisor": ["supervisor", "profile", "account", "password", "login", "auth"]
}

class API_Retriever:
    def __init__(self, dump_dir="api_docs_dump/apis"):
        self.docs = []
        self.filenames = []
        self.app_to_doc_indices = defaultdict(list)
        self._docs_cache = {}

        search_pattern = os.path.join(dump_dir, "*.txt")
        for filepath in glob.glob(search_pattern):
            filename = os.path.basename(filepath)
            if filepath in self._docs_cache:
                content = self._docs_cache[filepath]
            else:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    self._docs_cache[filepath] = content
            
            self.docs.append(content)
            self.filenames.append(filename)
            app_name = filename.split('_')[0] if '_' in filename else filename.replace('.txt', '')
            self.app_to_doc_indices[app_name].append(len(self.docs) - 1)

        if not self.docs:
            raise RuntimeError(f"Nenhum doc em {dump_dir}")

        self.bm25 = BM25Okapi([self._tokenize(d) for d in self.docs])

    def _tokenize(self, text):
        return re.sub(r'[^\w\s]', ' ', text.lower()).split()

    def _expand_query(self, query):
        terms = [query]
        ql = query.lower()
        for app, kws in APP_KEYWORD_MAP.items():
            if any(k in ql for k in kws):
                terms.extend(kws)
                terms.append(app)
        return " ".join(terms)

    def search(self, query, top_k=7, boost_relevant_apps=None, ctx=None):
        # 1. Tentativa rápida com Keywords
        expanded_query = self._expand_query(query)
        tokenized = self._tokenize(expanded_query)
        scores = self.bm25.get_scores(tokenized)

        # App Boosting
        if boost_relevant_apps:
            for app in boost_relevant_apps:
                for idx in self.app_to_doc_indices.get(app.lower(), []):
                    scores[idx] *= 1.5

        # 2. Verifica se achou algo relevante (Threshold simples)
        max_score = max(scores)
        final_query = expanded_query

        # Se score muito baixo (< 2.0), tenta LLM como fallback
        if max_score < 2.0 and ctx is not None:
            print(f"[RAG] Score baixo ({max_score:.2f}). Tentando LLM rewrite...")
            llm_query = _rewrite_query_with_llm(query, ctx)
            if llm_query != query:
                tokenized_llm = self._tokenize(llm_query)
                scores_llm = self.bm25.get_scores(tokenized_llm)
                # Aplica boosting novamente no score do LLM
                if boost_relevant_apps:
                    for app in boost_relevant_apps:
                        for idx in self.app_to_doc_indices.get(app.lower(), []):
                            scores_llm[idx] *= 1.5
                
                # Usa o score do LLM se for melhor
                if max(scores_llm) > max_score:
                    scores = scores_llm
                    final_query = llm_query

        top_indices = _rerank_results(final_query, self.docs, self.filenames, scores, top_k=top_k)

        result_str = "=== API DOCS ===\n\n"
        for i, idx in enumerate(top_indices):
            doc = self.docs[idx][:1500] + ("..." if len(self.docs[idx])>1500 else "")
            result_str += f"--- {self.filenames[idx]} ---\n{doc}\n\n"
        return result_str

    def __call__(self, query):
        return self.search(query)