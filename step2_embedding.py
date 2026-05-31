"""向量化入库 + 检索（TF-IDF，零下载）"""
import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
from sklearn.feature_extraction.text import TfidfVectorizer
import numpy as np
import os, shutil

# ── 自定义Embedding函数：用TF-IDF ──
class TfidfEmbedding(EmbeddingFunction):
    def __init__(self):
        self.vectorizer = TfidfVectorizer(max_features=512)
        self.fitted = False
    
    def __call__(self, texts: Documents) -> Embeddings:
        if not self.fitted:
            self.vectorizer.fit(texts)
            self.fitted = True
        vectors = self.vectorizer.transform(texts).toarray()
        # 归一化
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return (vectors / norms).tolist()

# ── 1. 读取PDF + 切片 ──
pdf_path = "/home/her91/.hermes/cache/documents/doc_0df36ac1b566_简历 .pdf"
doc = pymupdf.open(pdf_path)
full_text = "\n".join([page.get_text() for page in doc])

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500, chunk_overlap=100,
    separators=["\n\n", "\n", "。", ".", " "],
)
chunks = splitter.split_text(full_text)
print(f"📄 {len(doc)}页 → ✂️ {len(chunks)}个文本块")

# ── 2. 向量化入库 ──
db_dir = "/home/her91/rag-qa-project/chroma_db"
if os.path.exists(db_dir):
    shutil.rmtree(db_dir)

embedding_fn = TfidfEmbedding()
client = chromadb.PersistentClient(path=db_dir)
collection = client.get_or_create_collection(
    name="resume",
    embedding_function=embedding_fn,
)

ids = [f"chunk_{i}" for i in range(len(chunks))]
collection.add(documents=chunks, ids=ids)
print(f"💾 入库: {collection.count()}条")

# ── 4. 检索测试 ──
questions = ["参加过什么竞赛？", "会什么编程语言？", "项目经历", "有什么证书？"]
for q in questions:
    results = collection.query(query_texts=[q], n_results=2)
    print(f"\n🔍 问: {q}")
    for i, (doc_text, dist) in enumerate(zip(results["documents"][0], results["distances"][0])):
        preview = doc_text.replace("\n", " ")[:120]
        print(f"  结果{i+1} (距离{dist:.3f}): {preview}...")
