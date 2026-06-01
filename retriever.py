import os
import glob
import re
from rank_bm25 import BM25Okapi

class API_Retriever:
    def __init__(self, dump_dir="api_docs_dump/apis"):
        """
        inicializa o RAG lendo os arquivos estaticos gerados pelo dump_api_docs.py
        e construindo o índice vetorial BM25 
        """
        self.docs = []
        self.filenames = []
        
        # onde o dump_api_docs.py salvou os resumos
        search_pattern = os.path.join(dump_dir, "*.txt")

        # carrega o conteúdo de todos os 457 arquivos
        for filepath in glob.glob(search_pattern):
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                self.docs.append(content)
                self.filenames.append(os.path.basename(filepath))

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

    def search(self, query, top_k=7):
        """
        metodo a ser plugado no 'ctx.retrieve(query)'
        retorna as documentacoes formatadas em uma string pronta para o prompt
        """
        tokenized_query = self._tokenize(query)

        # pega as pontuacoes e extrai os melhores indices 
        scores = self.bm25.get_scores(tokenized_query)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        # concatena tudo em uma unica string para o LLM (mais facil do LLM ler)
        result_str = "=== MANUAIS DE API RECUPERADOS PARA ESTA TAREFA ===\n\n"

        for i, idx in enumerate(top_indices):
            doc_content = self.docs[idx]
            # truncamento de seguranca para NAO ESTOURAR O LIMITE de tokens
            safe_doc = doc_content[:1500] + ("...\n[TRUNCADO]" if len(doc_content) > 1500 else "")
            result_str += f"--- FERRAMENTA {i+1} ---\n{safe_doc}\n\n"

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