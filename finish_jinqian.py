# -*- coding: utf-8 -*-
"""
finish_jinqian.py — 金钱心理学补卡流水线（2026-08-28）
normalize → 改BOOK → 萃取 → 入库 → 全量重建 → 对抗集复测
"""
import os, re, subprocess, sys

sys.path.insert(0, "/mnt/e/Projects/rag-qa-project")
os.chdir("/mnt/e/Projects/rag-qa-project")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

PROJ = "/mnt/e/Projects/rag-qa-project"
PY = "/home/her91/rag-qa-venv/bin/python"
NORMALIZE = os.path.join(PROJ, "normalize_weread.py")
BATCH = os.path.join(PROJ, "batch_extract.py")
IMPORT = os.path.join(PROJ, "import_to_kb.py")
MD_DIR = os.path.join(PROJ, "tmp_weread_exporter/weread-exporter-main/output/63132920813abb66eg010015/chapters")
NAME = "金钱心理学"

def run(cmd, desc):
    print(f"\n▶ {desc}", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10800)
    if r.returncode != 0:
        print(f"❌ {desc} 失败: {r.stderr[-800:]}", flush=True)
        return False
    print(r.stdout[-500:] if r.stdout else "OK", flush=True)
    return True

# 1. normalize（位置参数：md目录 + 书名）
run([PY, NORMALIZE, MD_DIR, NAME], "normalize 金钱心理学")

# 2. 改 BOOK 常量
src = open(BATCH, encoding="utf-8").read()
src = re.sub(r'BOOK = ".*?"', f'BOOK = "{NAME}"', src, count=1)
open(BATCH, "w", encoding="utf-8").write(src)
print(f"BOOK 常量 → {NAME}", flush=True)

# 3. 萃取（DeepSeek 计费，12:00-14:00 半价时段）
run([PY, BATCH, "--all"], "萃取 金钱心理学")

# 4. 入库（纯本地，不花 LLM 钱）
run([PY, IMPORT, "--book", NAME, "--no-merge"], "入库 金钱心理学")

# 5. 全量重建向量
print("\n▶ 全量重建向量", flush=True)
r = subprocess.run([PY, "-c", """
import sys, os, time
sys.path.insert(0, '/mnt/e/Projects/rag-qa-project')
os.chdir('/mnt/e/Projects/rag-qa-project')
os.environ.setdefault('HF_HUB_OFFLINE', '1')
from hybrid_search import build_all_embeddings, _get_notes_collection
t0 = time.time()
build_all_embeddings()
print(f'重建完成: {_get_notes_collection().count()} 条, {time.time()-t0:.0f}s')
"""], capture_output=True, text=True, timeout=10800)
print(r.stdout[-300:] if r.stdout else "", flush=True)
if r.returncode != 0:
    print("❌ 重建失败", r.stderr[-500:], flush=True)

# 6. 对抗集复测（53条）
print("\n▶ 53条对抗集复测", flush=True)
r = subprocess.run([PY, "eval_adversarial.py"], capture_output=True, text=True, timeout=10800)
out = r.stdout + r.stderr
idx = out.find("=== 对抗集指标 ===")
print(out[idx:idx+1800] if idx >= 0 else out[-1000:], flush=True)

print("\n✅ 金钱心理学补卡结束", flush=True)
