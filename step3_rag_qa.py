"""RAG核心链路 — 中文语义Embedding + 多格式支持"""
import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
from sentence_transformers import SentenceTransformer
from openai import OpenAI
from dotenv import load_dotenv
import os, shutil

load_dotenv()

# ── 中文语义Embedding ──
class ChineseEmbedding(EmbeddingFunction):
    def __init__(self):
        print("⏳ 加载中文语义模型...")
        self.model = SentenceTransformer("shibing624/text2vec-base-chinese")
        print("✅ 模型加载完成")
    
    def __call__(self, texts: Documents) -> Embeddings:
        return self.model.encode(texts, normalize_embeddings=True).tolist()

# ── 文档加载（支持PDF/MD/TXT） ──
def load_document(path: str) -> str:
    if path.endswith(".pdf"):
        doc = pymupdf.open(path)
        return "\n".join([page.get_text() for page in doc])
    else:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

# ── 1. 加载 + 切片 ──
# 用修改版简历（含优必选实习经历）
doc_path = "/home/her91/简历_黄文浩_修改版.md"
full_text = load_document(doc_path)

splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
chunks = splitter.split_text(full_text)
print(f"📄 {doc_path} → ✂️ {len(chunks)}个文本块")

# ── 2. 向量化入库 ──
db_dir = "/home/her91/rag-qa-project/chroma_db"
if os.path.exists(db_dir):
    shutil.rmtree(db_dir)

client = chromadb.PersistentClient(path=db_dir)
collection = client.get_or_create_collection(
    name="resume", embedding_function=ChineseEmbedding()
)
collection.add(documents=chunks, ids=[f"chunk_{i}" for i in range(len(chunks))])
print(f"💾 入库: {collection.count()}条")

# ── 3. 检索测试 ──
questions = ["参加过什么竞赛？", "会什么编程语言？", "有什么证书？", "实习经历是什么？"]
for q in questions:
    results = collection.query(query_texts=[q], n_results=2)
    print(f"\n🔍 检索「{q}」")
    for i, (doc_text, dist) in enumerate(zip(results["documents"][0], results["distances"][0])):
        preview = doc_text.replace("\n", " ")[:120]
        print(f"  {i+1}. 距离{dist:.4f}: {preview}...")

# ── 4. RAG问答 ──
deepseek = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

print("\n" + "="*50)
print("RAG问答测试")
print("="*50)

for q in questions:
    results = collection.query(query_texts=[q], n_results=3)
    context = "\n\n---\n\n".join(results["documents"][0])
    
    prompt = f"""根据以下简历内容回答问题。

简历内容：
{context}

问题：{q}
请直接回答，简历中没有的信息就说"未提及"。
"""
    resp = deepseek.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    print(f"\n❓ {q}")
    print(f"💬 {resp.choices[0].message.content}")
