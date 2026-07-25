"""数据库连接 + Schema 初始化"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "personal.db")


def get_conn():
    """获取数据库连接"""
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def init_db():
    """初始化表结构（幂等，从 personal_db 迁移而来）"""
    from personal_db import init_db as _old_init
    _old_init()
