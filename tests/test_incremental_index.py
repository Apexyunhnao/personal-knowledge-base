"""
增量索引单元测试 — SHA-256 去重 / 多文件追加 / 文件更新 / 会话隔离
用法: python -m pytest tests/test_incremental_index.py -v --tb=short

注意: 测试 mock 了 ChineseEmbedding，避免加载 text2vec 模型（网络被墙/太慢）
核心逻辑（哈希缓存/追加/更新/隔离）与 embedding 无关，mock 不影响测试有效性
"""
import pytest
import os
import sys
import tempfile
import shutil
import hashlib
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Dummy Embedding：符合 ChromaDB EmbeddingFunction 接口 ──

from chromadb.api.types import EmbeddingFunction

class DummyEmbedding(EmbeddingFunction):
    def __call__(self, input):
        # 每个 text 返回 768 维零向量（text2vec-base-chinese 维度）
        return [[0.0] * 768 for _ in input]

    @staticmethod
    def name():
        return "dummy"


@pytest.fixture(autouse=True)
def mock_embedding():
    """全局替换 ChineseEmbedding 为 dummy，避免加载模型"""
    with patch("rag_engine.ChineseEmbedding", return_value=DummyEmbedding()):
        yield


@pytest.fixture
def temp_engine():
    """RAGEngine + 临时 ChromaDB 目录，测试后清理"""
    from rag_engine import RAGEngine

    tmpdir = tempfile.mkdtemp(prefix="chroma_test_")
    engine = RAGEngine(db_dir=tmpdir)

    yield engine, tmpdir

    shutil.rmtree(tmpdir, ignore_errors=True)


def _make_file(content: str, prefix: str = "testfile") -> str:
    """创建临时文件，返回路径。调用方负责清理"""
    tmpdir = tempfile.mkdtemp(prefix=f"{prefix}_")
    filepath = os.path.join(tmpdir, "doc.txt")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath, tmpdir


@pytest.fixture
def test_file_path():
    filepath, tmpdir = _make_file(
        "这是测试文档A。\n它包含两段内容。\n\n第二段在这里，用于验证分块功能。\n这段应该能被检索到。"
    )
    yield filepath
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def test_file_b_path():
    filepath, tmpdir = _make_file(
        "文档B的内容。\n这是另一个独立文档，用于验证多文件追加。\n包含独特关键词：增量索引测试。",
        prefix="testfile_b"
    )
    yield filepath
    shutil.rmtree(tmpdir, ignore_errors=True)


# ═══════════════════════════════════════════════════
# 基础索引
# ═══════════════════════════════════════════════════

class TestBasicIngest:
    """基础摄入功能"""

    def test_ingest_single_file(self, temp_engine, test_file_path):
        engine, _ = temp_engine
        result = engine.ingest("session_1", test_file_path)

        assert result["skipped"] is False
        assert result["chunks"] >= 1
        assert result["total_chunks"] >= 1

    def test_document_count_reflects_ingest(self, temp_engine, test_file_path):
        engine, _ = temp_engine
        assert engine.document_count("session_1") == 0
        engine.ingest("session_1", test_file_path)
        assert engine.document_count("session_1") >= 1

    def test_document_count_zero_for_new_session(self, temp_engine):
        engine, _ = temp_engine
        assert engine.document_count("unknown_session") == 0

    def test_empty_file_raises(self, temp_engine):
        engine, _ = temp_engine
        filepath, tmpdir = _make_file("")
        try:
            with pytest.raises(ValueError, match="为空"):
                engine.ingest("session_1", filepath)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_nonexistent_file_raises(self, temp_engine):
        engine, _ = temp_engine
        with pytest.raises(FileNotFoundError):
            engine.load_document("/tmp/nonexistent_xyz_abc.txt")


# ═══════════════════════════════════════════════════
# SHA-256 哈希去重（核心场景）
# ═══════════════════════════════════════════════════

class TestHashDedup:
    """同文件同哈希 → 跳过，不重建"""

    def test_same_file_skipped_on_second_ingest(self, temp_engine, test_file_path):
        engine, _ = temp_engine

        r1 = engine.ingest("session_1", test_file_path)
        assert r1["skipped"] is False

        r2 = engine.ingest("session_1", test_file_path)
        assert r2["skipped"] is True, "同文件第二次摄入应跳过"
        assert r2["chunks"] == r1["chunks"]
        assert r2["total_chunks"] == r1["total_chunks"], "总数不变"

    def test_hash_cache_persists_across_engines(self, test_file_path):
        """重启后缓存恢复，已索引文件被跳过"""
        from rag_engine import RAGEngine

        tmpdir = tempfile.mkdtemp(prefix="chroma_persist_")
        try:
            # 注意：这里需要 patch 作用到每个 engine 的创建
            with patch("rag_engine.ChineseEmbedding", return_value=DummyEmbedding()):
                engine1 = RAGEngine(db_dir=tmpdir)
                r1 = engine1.ingest("session_1", test_file_path)
                assert r1["skipped"] is False

                engine2 = RAGEngine(db_dir=tmpdir)
                r2 = engine2.ingest("session_1", test_file_path)
                assert r2["skipped"] is True, "缓存持久化后重建 engine 应跳过"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_different_session_same_file_not_skipped(self, temp_engine, test_file_path):
        """不同 session 独立管理，各自都要索引"""
        engine, _ = temp_engine

        r1 = engine.ingest("session_a", test_file_path)
        assert r1["skipped"] is False

        r2 = engine.ingest("session_b", test_file_path)
        assert r2["skipped"] is False, "不同会话不应跳过"
        assert engine.document_count("session_a") >= 1
        assert engine.document_count("session_b") >= 1


# ═══════════════════════════════════════════════════
# 多文件追加（不重建 — 核心场景）
# ═══════════════════════════════════════════════════

class TestMultiFileAppend:
    """多文件追加：逐个摄入，chunk 累积，不重建"""

    def test_two_files_chunks_accumulate(self, temp_engine, test_file_path, test_file_b_path):
        engine, _ = temp_engine

        r1 = engine.ingest("session_1", test_file_path)
        c1 = r1["total_chunks"]

        r2 = engine.ingest("session_1", test_file_b_path)
        c2 = r2["total_chunks"]

        assert c2 > c1, f"追加后总数应增加: {c1} → {c2}"
        assert c2 == c1 + r2["chunks"], f"总数 = 旧{c1} + 新{r2['chunks']}"

    def test_three_files_cumulative(self, temp_engine, test_file_path, test_file_b_path):
        """三文件累计"""
        engine, _ = temp_engine
        filepath_c, tmpdir_c = _make_file("第三份文档。验证三文件累计。", "testfile_c")

        try:
            r1 = engine.ingest("session_1", test_file_path)
            r2 = engine.ingest("session_1", test_file_b_path)
            r3 = engine.ingest("session_1", filepath_c)

            total = engine.document_count("session_1")
            expected = r1["chunks"] + r2["chunks"] + r3["chunks"]
            assert total == expected, f"total={total} != expected={expected}"
        finally:
            shutil.rmtree(tmpdir_c, ignore_errors=True)

    def test_append_doesnt_invalidate_old_files(self, temp_engine, test_file_path, test_file_b_path):
        """追加新文件后，旧文件仍有效的哈希应被跳过"""
        engine, _ = temp_engine

        engine.ingest("session_1", test_file_path)
        engine.ingest("session_1", test_file_b_path)

        # 旧文件再摄入应跳过
        r = engine.ingest("session_1", test_file_path)
        assert r["skipped"] is True, "追加新文件不应使旧文件哈希失效"


# ═══════════════════════════════════════════════════
# 文件更新（同路径新内容 — 核心场景）
# ═══════════════════════════════════════════════════

class TestFileUpdate:
    """同路径内容变更 → 删旧 chunk + 加新 chunk"""

    def test_update_replaces_not_accumulates(self, temp_engine):
        """更新不应累加 chunk"""
        engine, _ = temp_engine
        filepath, tmpdir = _make_file("版本1：短内容。", "test_update")

        try:
            r1 = engine.ingest("session_1", filepath)
            count_before = r1["total_chunks"]

            # 覆盖写更长内容
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(("版本2：内容大幅变长了，确保chunk数不同。" * 50))

            r2 = engine.ingest("session_1", filepath)
            assert r2["skipped"] is False, "内容变更应重新索引"
            # 短→长，chunk 数大概率不同
            # 极端情况（都很短）下可能相同，关键是验证不累加：
            # 如果不累加，total_chunks == 新 chunks；如果累加，total > 新 chunks
            assert r2["total_chunks"] == r2["chunks"], \
                f"更新模式：total={r2['total_chunks']} == chunks={r2['chunks']}（不累加）"
            # 如果 chunk 数变了，确认 total 和之前不同（证明是替换而非追加）
            if r2["chunks"] != r1["chunks"]:
                assert r2["total_chunks"] != count_before, \
                    f"chunk 数从 {r1['chunks']} → {r2['chunks']}，total 也应变化"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_update_then_same_skipped(self, temp_engine):
        engine, _ = temp_engine
        filepath, tmpdir = _make_file("初始内容。", "test_update2")

        try:
            engine.ingest("session_1", filepath)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(("更新后的内容。" * 10))
            engine.ingest("session_1", filepath)

            # 第三次不修改
            r3 = engine.ingest("session_1", filepath)
            assert r3["skipped"] is True
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ═══════════════════════════════════════════════════
# 会话隔离
# ═══════════════════════════════════════════════════

class TestSessionIsolation:
    """不同 session_id 数据完全隔离"""

    def test_sessions_independent(self, temp_engine, test_file_path, test_file_b_path):
        engine, _ = temp_engine

        engine.ingest("alice", test_file_path)
        engine.ingest("bob", test_file_b_path)

        assert engine.document_count("alice") >= 1
        assert engine.document_count("bob") >= 1

    def test_clear_session_only_affects_target(self, temp_engine, test_file_path, test_file_b_path):
        engine, _ = temp_engine

        engine.ingest("alice", test_file_path)
        engine.ingest("bob", test_file_b_path)

        engine.clear_session("alice")

        assert engine.document_count("alice") == 0
        assert engine.document_count("bob") >= 1
        assert engine.session_files("alice") == []

    def test_clear_nonexistent_session_no_error(self, temp_engine):
        engine, _ = temp_engine
        engine.clear_session("nonexistent")  # 不抛异常


# ═══════════════════════════════════════════════════
# session_files / 哈希缓存
# ═══════════════════════════════════════════════════

class TestSessionFiles:
    """session_files 列出已索引文件"""

    def test_lists_indexed_files(self, temp_engine, test_file_path, test_file_b_path):
        engine, _ = temp_engine

        engine.ingest("session_1", test_file_path)
        engine.ingest("session_1", test_file_b_path)

        files = engine.session_files("session_1")
        assert len(files) == 2
        paths = [f["path"] for f in files]
        assert test_file_path in paths
        assert test_file_b_path in paths

        for f in files:
            assert "chunks" in f and isinstance(f["chunks"], int) and f["chunks"] >= 1
            assert "hash" in f and len(f["hash"]) == 8

    def test_empty_for_new_session(self, temp_engine):
        engine, _ = temp_engine
        assert engine.session_files("new_session") == []

    def test_clear_other_session_no_side_effect(self, temp_engine, test_file_path):
        engine, _ = temp_engine
        engine.ingest("keep", test_file_path)

        before = engine.session_files("keep")
        engine.clear_session("delete_me")
        after = engine.session_files("keep")
        assert len(before) == len(after), "不相关会话清除不应影响"


# ═══════════════════════════════════════════════════
# SHA-256 哈希计算
# ═══════════════════════════════════════════════════

class TestSHA256:
    """哈希计算正确性（不依赖 ChromaDB）"""

    def test_deterministic(self, test_file_path):
        from rag_engine import RAGEngine
        h1 = RAGEngine._compute_hash(test_file_path)
        h2 = RAGEngine._compute_hash(test_file_path)
        assert h1 == h2

    def test_different_files_different_hash(self, test_file_path, test_file_b_path):
        from rag_engine import RAGEngine
        h1 = RAGEngine._compute_hash(test_file_path)
        h2 = RAGEngine._compute_hash(test_file_b_path)
        assert h1 != h2

    def test_hex_format(self, test_file_path):
        from rag_engine import RAGEngine
        h = RAGEngine._compute_hash(test_file_path)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_binary_file(self):
        from rag_engine import RAGEngine
        filepath, tmpdir = _make_file("", "test_binary")
        try:
            with open(filepath, "wb") as f:
                f.write(bytes(range(256)) * 10)
            h = RAGEngine._compute_hash(filepath)
            assert len(h) == 64
            assert h != hashlib.sha256(b"").hexdigest()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
