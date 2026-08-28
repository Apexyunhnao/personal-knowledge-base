# -*- coding: utf-8 -*-
"""
night_batch_pipeline.py — 夜间批量萃取流水线（v1.3.2 内容补卡）
按顺序处理多本微信读书导出的书：
  1. normalize_weread.py: md → txt 到 inputs/<书>/
  2. 改 batch_extract.py BOOK 常量 → 跑萃取（DeepSeek 计费，空闲半价时段）
  3. import_to_kb.py --book <书> --no-merge 入库
全部完成后调 build_all_embeddings 全量重建向量 + 校验。

用法: python night_batch_pipeline.py
配置: BOOKS 列表 (书名, md输出目录, bookId)
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, "/mnt/e/Projects/rag-qa-project")
os.chdir("/mnt/e/Projects/rag-qa-project")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

PROJ = "/mnt/e/Projects/rag-qa-project"
EXPORTER = os.path.join(PROJ, "tmp_weread_exporter/weread-exporter-main")
NORMALIZE = os.path.join(PROJ, "normalize_weread.py")
BATCH = os.path.join(PROJ, "batch_extract.py")
IMPORT = os.path.join(PROJ, "import_to_kb.py")
PY = "/home/her91/rag-qa-venv/bin/python"
PY_WEREAD = os.path.join(PROJ, "weread-venv/bin/python")

# (书名, 微信读书输出目录(含书名的md), bookId) — 按需增删
BOOKS = [
    ("原子习惯", os.path.join(EXPORTER, "output", "bcb32150719afe3bbcbad52", "chapters"), "bcb32150719afe3bbcbad52"),
    ("自控力", os.path.join(EXPORTER, "output", "22632650726da6982262012", "chapters"), "22632650726da6982262012"),
    ("非暴力沟通", os.path.join(EXPORTER, "output", "ce7325b0813ab9558g014d3a", "chapters"), "ce7325b0813ab9558g014d3a"),
    ("学会提问", os.path.join(EXPORTER, "output", "42932ec07186d83d429d640", "chapters"), "42932ec07186d83d429d640"),
]


def run(cmd, desc):
    print(f"\n{'='*60}\n▶ {desc}\n  {' '.join(cmd[:4])}...")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if r.returncode != 0:
        print(f"❌ {desc} 失败 (exit {r.returncode})")
        print(r.stdout[-500:] if r.stdout else "")
        print(r.stderr[-800:] if r.stderr else "")
        return False
    print(r.stdout[-300:] if r.stdout else "OK")
    return True


def main():
    for name, md_dir, book_id in BOOKS:
        print(f"\n{'#'*70}\n# 处理: {name} (bookId={book_id})\n{'#'*70}")

        # 0. 导出（Playwright 不花 LLM 钱；已导出则跳过）
        if not os.path.isdir(md_dir) or not os.listdir(md_dir):
            print(f"▶ 导出 {name} (bookId={book_id})...")
            r = subprocess.run(
                [PY_WEREAD, os.path.join(EXPORTER, "export_v5.py"), book_id],
                capture_output=True, text=True, timeout=7200,
                cwd=EXPORTER,
            )
            if r.returncode != 0 or "新增0章" in r.stdout:
                print(f"⚠️ 导出 {name} 异常: {r.stdout[-300:]} {r.stderr[-300:]}")
                continue
            print(r.stdout[-200:])
        else:
            print(f"⏭ 导出目录已存在，跳过导出: {name}")

        if not os.path.isdir(md_dir) or not os.listdir(md_dir):
            print(f"⏭ 跳过 {name}: 导出目录仍为空 {md_dir}")
            continue

        # 1. normalize: md → txt 到 inputs/<name>/（位置参数: src book）
        if not run([PY, NORMALIZE, md_dir, name], f"normalize {name}"):
            continue

        # 2. 改 batch_extract BOOK 常量（全局写死，每本改一次）
        src = open(BATCH, encoding="utf-8").read()
        import re
        new_src = re.sub(r'BOOK = ".*?"', f'BOOK = "{name}"', src, count=1)
        if new_src == src:
            print(f"⚠️ 无法定位 BOOK 常量（已改过？当前: {re.search(r'BOOK = .*', src).group(0) if re.search(r'BOOK = .*', src) else '?'}）")
        open(BATCH, "w", encoding="utf-8").write(new_src)
        print(f"BOOK 常量 → {name}")

        # 3. 萃取（DeepSeek 计费）
        if not run([PY, BATCH, "--all"], f"萃取 {name}"):
            print("⚠️ 萃取失败，继续下一本")

        # 4. 入库
        if not run([PY, IMPORT, "--book", name, "--no-merge"], f"入库 {name}"):
            print("⚠️ 入库失败，继续下一本")

    # 5. 全量重建向量 + 校验
    print("\n" + "="*60)
    print("▶ 全量重建向量")
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

    print("\n✅ 夜间流水线结束")


if __name__ == "__main__":
    main()
