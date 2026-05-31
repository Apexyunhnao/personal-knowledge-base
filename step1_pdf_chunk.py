"""PDF解析 + 文本切片"""
import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 1. 读取PDF
pdf_path = "/home/her91/简历_黄文浩_修改版.md"  # 先用markdown测，后面换真实PDF
doc = pymupdf.open("/home/her91/.hermes/cache/documents/doc_0df36ac1b566_简历 .pdf")

full_text = ""
for page in doc:
    full_text += page.get_text()

print(f"📄 读取PDF: {len(doc)}页, 共{len(full_text)}字符")

# 2. 切片
splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,      # 每块500字符
    chunk_overlap=100,   # 重叠100字符，避免切断语义
    separators=["\n\n", "\n", "。", ".", " "],
)

chunks = splitter.split_text(full_text)

print(f"✂️ 切片: {len(chunks)}块")
print("\n--- 前3块预览 ---")
for i, chunk in enumerate(chunks[:3]):
    print(f"\n[块 {i+1}] ({len(chunk)}字符)")
    print(chunk[:200] + "..." if len(chunk) > 200 else chunk)
