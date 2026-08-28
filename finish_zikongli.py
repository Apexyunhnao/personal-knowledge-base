# -*- coding: utf-8 -*-
"""
finish_zikongli.py — 自控力补卡收尾（一次性脚本）
normalize → 改BOOK → 萃取 → 入库 → 全量重建 → 复测
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
MD_DIR = os.path.join(PROJ, "tmp_weread_exporter/weread-exporter-main/output/d2f32b705cc7f2d2ff135f6/chapters")
NAME = "自控力"

def run(cmd, desc):
    print(f"\n▶ {desc}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if r.returncode != 0:
        print(f"❌ {desc} 失败: {r.stderr[-500:]}")
        return False
    print(r.stdout[-400:] if r.stdout else "OK")
    return True

# 1. normalize
run([PY, NORMALIZE, MD_DIR, NAME], "normalize 自控力")

# 2. 改 BOOK 常量
src = open(BATCH, encoding="utf-8").read()
src = re.sub(r'BOOK = ".*?"', f'BOOK = "{NAME}"', src, count=1)
open(BATCH, "w", encoding="utf-8").write(src)
print(f"BOOK 常量 → {NAME}")

# 3. 萃取
run([PY, BATCH, "--all"], "萃取 自控力")

# 4. 入库
run([PY, IMPORT, "--book", NAME, "--no-merge"], "入库 自控力")

# 5. 全量重建
print("\n▶ 全量重建向量")
r = subprocess.run([PY, "-c", """
import sys, os, time
sys.path.insert(0, '/mnt/e/Projects/rag-qa-project')
os.chdir('/mnt/e/Projects/rag-qa-project')
os.environ.setdefault('HF_HUB_OFFLINE', '1')
from hybrid_search import build_all_embeddings, _get_notes_collection
t0 = time.time()
build_all_embeddings()
print(f'重建完成: {_get_notes_collection().count()} 条, {time.time()-t0:.0f}s')
"""], capture_output=True, text=True, timeout=7200)
print(r.stdout[-300:] if r.stdout else "")
if r.returncode != 0:
    print("❌ 重建失败", r.stderr[-500:])

# 6. 复测对抗集
print("\n▶ 53条对抗集复测")
r = subprocess.run([PY, "eval_adversarial.py"], capture_output=True, text=True, timeout=7200)
out = r.stdout + r.stderr
# 打印指标部分
idx = out.find("=== 对抗集指标 ===")
print(out[idx:idx+1500] if idx >= 0 else out[-800:])

print("\n✅ 自控力补卡结束")
