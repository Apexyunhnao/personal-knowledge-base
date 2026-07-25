"""pytest 配置 — 临时数据库 + 测试数据"""
import pytest
import os
import sys
import tempfile
import shutil

# 确保项目根目录在 path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def temp_db():
    """创建临时数据库，测试后自动清理"""
    # 备份原数据库路径
    from personal_db import DB_PATH as _orig_path
    import personal_db as pdb
    
    tmpdir = tempfile.mkdtemp()
    tmp_db = os.path.join(tmpdir, "test.db")
    
    # 重定向数据库路径
    pdb.DB_PATH = tmp_db
    pdb.BACKUP_DIR = os.path.join(tmpdir, "backups")
    pdb.UPLOAD_DIR = os.path.join(tmpdir, "uploads")
    
    # 重新初始化
    pdb.init_db()
    
    yield pdb
    
    # 清理
    shutil.rmtree(tmpdir, ignore_errors=True)
    pdb.DB_PATH = _orig_path


@pytest.fixture
def sample_data(temp_db):
    """预填充测试数据"""
    pdb = temp_db
    
    # 创建项目
    pid = pdb._create("projects", {
        "name": "测试项目",
        "tech_stack": "Python,SQLite",
        "description": "这是一个[[测试笔记]]项目",
        "category": "个人项目",
        "tags": "Python, 测试",
    })
    
    # 创建求职
    aid = pdb._create("applications", {
        "company": "测试公司",
        "position": "后端开发",
        "status": "已投递",
        "tags": "大厂, 深圳",
    })
    
    # 创建笔记（含WikiLink）
    nid = pdb._create("notes", {
        "title": "测试笔记",
        "topic": "数据库",
        "content": "SQLite FTS5 [[测试项目]] 全文搜索",
        "tags": "SQLite, 搜索",
        "format": "markdown",
    })
    
    return {"project_id": pid, "application_id": aid, "note_id": nid}
