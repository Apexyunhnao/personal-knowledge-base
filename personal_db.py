"""个人资料库引擎 — SQLite + FTS5 + 标签系统 + 软删除 + Markdown导入导出"""
import sqlite3
import logging
import os
import re
import shutil
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
import json

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "personal.db")
BACKUP_DIR = os.path.join(os.path.dirname(__file__), "backups")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")

# ── 枚举约束 ──

APP_STATUSES = ["已投递", "筛选中", "面试", "笔试", "offer", "已拒", "已接受"]
NOTE_TOPICS = ["数据库", "Python", "前端", "AI/ML", "面试", "系统设计", "工具", "其他"]

# ── 表名映射 ──

TABLE_MAP = {
    "projects": "projects",
    "applications": "job_applications",
    "notes": "learning_notes",
}
REVERSE_MAP = {v: k for k, v in TABLE_MAP.items()}

# 每个表的合法列名白名单（不含 id/created_at/updated_at/deleted_at 等系统列）
COLUMN_WHITELIST = {
    "projects": {
        "name", "tech_stack", "description", "github_url", "highlights",
        "start_date", "end_date", "category", "tags",
    },
    "job_applications": {
        "company", "position", "location", "status", "apply_date",
        "notes", "salary_range", "contact_info", "tags",
    },
    "learning_notes": {
        "title", "topic", "tags", "content", "source", "format",
    },
}

def _real_table(short_name: str) -> str:
    """严格映射表名。不在白名单则抛出 ValueError（fail-closed 原则）。"""
    real = TABLE_MAP.get(short_name)
    if real is None:
        raise ValueError(f"无效的表名: {short_name}")
    return real

def _validate_columns(table: str, columns: list[str]) -> list[str]:
    """验证列名白名单。不在白名单的列名抛出 ValueError。"""
    allowed = COLUMN_WHITELIST.get(table, set())
    for col in columns:
        if col not in allowed:
            raise ValueError(f"无效的列名 '{col}'（表 {table} 不支持此字段）")
    return columns


# ── 数据库连接 ──

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


# ── 初始化 ──

def init_db():
    """初始化表结构（幂等）"""
    with _conn() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            tech_stack TEXT,
            description TEXT,
            github_url TEXT,
            highlights TEXT,
            start_date TEXT,
            end_date TEXT,
            category TEXT DEFAULT '个人项目' CHECK(category IN ('个人项目','实习项目','课程项目','开源贡献')),
            tags TEXT DEFAULT '',
            deleted_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS job_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            position TEXT,
            location TEXT,
            status TEXT DEFAULT '已投递' CHECK(status IN ('已投递','筛选中','面试','笔试','offer','已拒','已接受')),
            apply_date TEXT,
            notes TEXT,
            salary_range TEXT,
            contact_info TEXT,
            tags TEXT DEFAULT '',
            deleted_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS learning_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            topic TEXT CHECK(topic IN ('数据库','Python','前端','AI/ML','面试','系统设计','工具','其他') OR topic IS NULL),
            tags TEXT DEFAULT '',
            content TEXT,
            source TEXT,
            format TEXT DEFAULT 'plain' CHECK(format IN ('plain','markdown')),
            frontmatter TEXT DEFAULT '{}',
            deleted_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 全局标签表
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 标签关联表（通用：table_name + item_id）
        CREATE TABLE IF NOT EXISTS item_tags (
            table_name TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY (table_name, item_id, tag_id),
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );

        -- 附件表
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            related_table TEXT NOT NULL,
            related_id INTEGER NOT NULL,
            doc_type TEXT NOT NULL CHECK(doc_type IN ('简历','求职信','作品集','证书','其他')),
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- 双向链接表
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_table TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            target_table TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            link_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_table, source_id, target_table, target_id)
        );

        -- FTS5 索引
        CREATE VIRTUAL TABLE IF NOT EXISTS projects_fts USING fts5(
            name, tech_stack, description, highlights, tags,
            content='projects', content_rowid='id'
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS applications_fts USING fts5(
            company, position, location, notes, tags,
            content='job_applications', content_rowid='id'
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
            title, topic, tags, content,
            content='learning_notes', content_rowid='id'
        );
        """)

        # FTS5 触发器
        _ensure_fts_triggers(db, "projects", "projects_fts", ["name", "tech_stack", "description", "highlights", "tags"])
        _ensure_fts_triggers(db, "job_applications", "applications_fts", ["company", "position", "location", "notes", "tags"])
        _ensure_fts_triggers(db, "learning_notes", "notes_fts", ["title", "topic", "tags", "content"])

        # 重建FTS5索引
        db.execute("INSERT INTO projects_fts(projects_fts) VALUES('rebuild')")
        db.execute("INSERT INTO applications_fts(applications_fts) VALUES('rebuild')")
        db.execute("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')")

        # 迁移：给旧表加新列
        _migrate_add_column(db, "projects", "tags", "TEXT DEFAULT ''")
        _migrate_add_column(db, "projects", "deleted_at", "TIMESTAMP NULL")
        _migrate_add_column(db, "job_applications", "tags", "TEXT DEFAULT ''")
        _migrate_add_column(db, "job_applications", "deleted_at", "TIMESTAMP NULL")
        _migrate_add_column(db, "learning_notes", "tags", "TEXT DEFAULT ''")
        _migrate_add_column(db, "learning_notes", "deleted_at", "TIMESTAMP NULL")
        _migrate_add_column(db, "learning_notes", "format", "TEXT DEFAULT 'plain'")
        _migrate_add_column(db, "learning_notes", "frontmatter", "TEXT DEFAULT '{}'")

        db.commit()


def _migrate_add_column(db, table: str, column: str, col_type: str):
    """安全加列（忽略已存在的列）"""
    try:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except sqlite3.OperationalError:
        pass


def _ensure_fts_triggers(db, table: str, fts_table: str, columns: list):
    """确保FTS5触发器存在"""
    col_str = ", ".join(columns)
    db.executescript(f"""
        CREATE TRIGGER IF NOT EXISTS {fts_table}_ai AFTER INSERT ON {table} BEGIN
            INSERT INTO {fts_table}(rowid, {col_str})
            VALUES (new.id, {', '.join('new.' + c for c in columns)});
        END;
        CREATE TRIGGER IF NOT EXISTS {fts_table}_ad AFTER DELETE ON {table} BEGIN
            INSERT INTO {fts_table}({fts_table}, rowid, {col_str})
            VALUES('delete', old.id, {', '.join('old.' + c for c in columns)});
        END;
        CREATE TRIGGER IF NOT EXISTS {fts_table}_au AFTER UPDATE ON {table} BEGIN
            INSERT INTO {fts_table}({fts_table}, rowid, {col_str})
            VALUES('delete', old.id, {', '.join('old.' + c for c in columns)});
            INSERT INTO {fts_table}(rowid, {col_str})
            VALUES (new.id, {', '.join('new.' + c for c in columns)});
        END;
    """)


# ── 标签管理 ──

def _sync_tags(table: str, item_id: int, tag_names_str: str):
    """同步标签：从逗号字符串 → 标签表 + 关联表"""
    tag_names = [t.strip() for t in tag_names_str.split(",") if t.strip()] if tag_names_str else []
    
    with _conn() as db:
        # 清除旧关联
        db.execute("DELETE FROM item_tags WHERE table_name=? AND item_id=?", (table, item_id))
        
        for name in tag_names:
            # 确保标签存在
            db.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            tag_row = db.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
            if tag_row:
                db.execute(
                    "INSERT OR IGNORE INTO item_tags (table_name, item_id, tag_id) VALUES (?, ?, ?)",
                    (table, item_id, tag_row["id"])
                )
        db.commit()


def _load_item_tags(table: str, item_id: int) -> list:
    """加载某条记录的所有标签"""
    with _conn() as db:
        rows = db.execute(
            "SELECT t.id, t.name FROM tags t "
            "INNER JOIN item_tags it ON t.id = it.tag_id "
            "WHERE it.table_name=? AND it.item_id=? ORDER BY t.name",
            (table, item_id)
        ).fetchall()
        return [dict(r) for r in rows]


# ── WikiLink 双向链接 ──

import re as _re
WIKILINK_RE = _re.compile(r'\[\[([^\]]+)\]\]')


def _parse_wikilinks(content: str) -> list:
    """从内容中提取 [[WikiLink]] 列表"""
    if not content:
        return []
    return WIKILINK_RE.findall(content)


def _sync_links(table: str, item_id: int, content: str):
    """同步双向链接：解析 WikiLinks → 查找目标 → 更新 links 表"""
    link_texts = _parse_wikilinks(content)
    
    with _conn() as db:
        # 清除旧链接
        db.execute("DELETE FROM links WHERE source_table=? AND source_id=?", (table, item_id))
        
        for link_text in link_texts:
            # 在所有表中按标题查找目标
            for target_table in ["projects", "job_applications", "learning_notes"]:
                title_col = {"projects": "name", "job_applications": "company", "learning_notes": "title"}[target_table]
                target = db.execute(
                    f"SELECT id FROM {target_table} WHERE {title_col}=? AND deleted_at IS NULL LIMIT 1",
                    (link_text,)
                ).fetchone()
                if target:
                    db.execute(
                        "INSERT OR IGNORE INTO links (source_table, source_id, target_table, target_id, link_text) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (table, item_id, target_table, target["id"], link_text)
                    )
                    break  # 找到第一个匹配就停止
        db.commit()


def get_backlinks(table: str, item_id: int) -> list:
    """获取指向当前条目的所有反向链接"""
    with _conn() as db:
        rows = db.execute(
            "SELECT l.*, "
            "CASE l.source_table "
            "  WHEN 'projects' THEN (SELECT name FROM projects WHERE id=l.source_id) "
            "  WHEN 'job_applications' THEN (SELECT company FROM job_applications WHERE id=l.source_id) "
            "  WHEN 'learning_notes' THEN (SELECT title FROM learning_notes WHERE id=l.source_id) "
            "END as source_title "
            "FROM links l WHERE l.target_table=? AND l.target_id=? "
            "ORDER BY l.created_at DESC",
            (table, item_id)
        ).fetchall()
        return [dict(r) for r in rows]


def get_forward_links(table: str, item_id: int) -> list:
    """获取当前条目指向的所有链接"""
    with _conn() as db:
        rows = db.execute(
            "SELECT l.*, "
            "CASE l.target_table "
            "  WHEN 'projects' THEN (SELECT name FROM projects WHERE id=l.target_id) "
            "  WHEN 'job_applications' THEN (SELECT company FROM job_applications WHERE id=l.target_id) "
            "  WHEN 'learning_notes' THEN (SELECT title FROM learning_notes WHERE id=l.target_id) "
            "END as target_title "
            "FROM links l WHERE l.source_table=? AND l.source_id=? "
            "ORDER BY l.created_at DESC",
            (table, item_id)
        ).fetchall()
        return [dict(r) for r in rows]


def get_graph_data() -> dict:
    """获取知识图谱数据（节点+边）"""
    with _conn() as db:
        nodes = []
        # 收集所有未被删除的条目作为节点
        for table, title_col, short in [
            ("projects", "name", "projects"),
            ("job_applications", "company", "applications"),
            ("learning_notes", "title", "notes"),
        ]:
            rows = db.execute(
                f"SELECT id, {title_col} as title FROM {table} WHERE deleted_at IS NULL"
            ).fetchall()
            for r in rows:
                nodes.append({"id": f"{short}:{r['id']}", "title": r["title"], "group": short})
        
        edges = []
        link_rows = db.execute(
            "SELECT l.source_table, l.source_id, l.target_table, l.target_id "
            "FROM links l "
            "WHERE (SELECT deleted_at FROM projects WHERE id=l.source_id) IS NULL "
            "  AND (SELECT deleted_at FROM job_applications WHERE id=l.source_id) IS NULL "
            "  AND (SELECT deleted_at FROM learning_notes WHERE id=l.source_id) IS NULL"
        ).fetchall()
        
        for r in link_rows:
            src_short = {"projects": "projects", "job_applications": "applications", "learning_notes": "notes"}[r["source_table"]]
            tgt_short = {"projects": "projects", "job_applications": "applications", "learning_notes": "notes"}[r["target_table"]]
            edges.append({
                "source": f"{src_short}:{r['source_id']}",
                "target": f"{tgt_short}:{r['target_id']}",
            })
        
        return {"nodes": nodes, "edges": edges}


def list_all_tags() -> list:
    """列出所有标签及使用次数"""
    with _conn() as db:
        rows = db.execute("""
            SELECT t.id, t.name, COUNT(it.item_id) as count
            FROM tags t
            LEFT JOIN item_tags it ON t.id = it.tag_id
            GROUP BY t.id
            ORDER BY count DESC, t.name
        """).fetchall()
        return [dict(r) for r in rows]


def rename_tag(tag_id: int, new_name: str):
    """重命名标签（同步更新所有关联记录中的tags字符串）"""
    with _conn() as db:
        old = db.execute("SELECT name FROM tags WHERE id=?", (tag_id,)).fetchone()
        if not old:
            raise ValueError(f"标签不存在: {tag_id}")
        old_name = old["name"]
        
        # 更新标签名（唯一约束可能冲突，先检查）
        existing = db.execute("SELECT id FROM tags WHERE name=?", (new_name,)).fetchone()
        if existing and existing["id"] != tag_id:
            # 合并标签
            db.execute("UPDATE OR IGNORE item_tags SET tag_id=? WHERE tag_id=?", (existing["id"], tag_id))
            db.execute("DELETE FROM item_tags WHERE tag_id=?", (tag_id,))
            db.execute("DELETE FROM tags WHERE id=?", (tag_id,))
        else:
            db.execute("UPDATE tags SET name=? WHERE id=?", (new_name, tag_id))
        
        # 同步更新主表中的 tags 字段
        items = db.execute("SELECT table_name, item_id FROM item_tags WHERE tag_id=?", 
                          (existing["id"] if existing and existing["id"] != tag_id else tag_id,)).fetchall()
        for item in items:
            tag_rows = db.execute(
                "SELECT t.name FROM tags t INNER JOIN item_tags it ON t.id=it.tag_id "
                "WHERE it.table_name=? AND it.item_id=? ORDER BY t.name",
                (item["table_name"], item["item_id"])
            ).fetchall()
            tag_str = ", ".join(r["name"] for r in tag_rows)
            db.execute(f"UPDATE {item['table_name']} SET tags=? WHERE id=?", (tag_str, item["item_id"]))
        
        db.commit()


def delete_tag(tag_id: int):
    """删除标签"""
    with _conn() as db:
        # 更新关联记录
        items = db.execute("SELECT table_name, item_id FROM item_tags WHERE tag_id=?", (tag_id,)).fetchall()
        db.execute("DELETE FROM item_tags WHERE tag_id=?", (tag_id,))
        db.execute("DELETE FROM tags WHERE id=?", (tag_id,))
        
        for item in items:
            tag_rows = db.execute(
                "SELECT t.name FROM tags t INNER JOIN item_tags it ON t.id=it.tag_id "
                "WHERE it.table_name=? AND it.item_id=? ORDER BY t.name",
                (item["table_name"], item["item_id"])
            ).fetchall()
            tag_str = ", ".join(r["name"] for r in tag_rows)
            db.execute(f"UPDATE {item['table_name']} SET tags=? WHERE id=?", (tag_str, item["item_id"]))
        
        db.commit()


# ── CRUD（含软删除）──

def _list(table: str, limit: int = 50, offset: int = 0, include_deleted: bool = False, tag: str = None):
    table = _real_table(table)
    with _conn() as db:
        conditions = []
        params = []
        
        if not include_deleted:
            conditions.append("deleted_at IS NULL")
        
        if tag:
            conditions.append("id IN (SELECT item_id FROM item_tags it "
                            "INNER JOIN tags t ON it.tag_id=t.id "
                            "WHERE it.table_name=? AND t.name=?)")
            params.extend([table, tag])
        
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"SELECT * FROM {table} {where} ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        rows = db.execute(sql, params).fetchall()
        return [_enrich_item(db, table, dict(r)) for r in rows]


def _get(table: str, item_id: int):
    table = _real_table(table)
    with _conn() as db:
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (item_id,)).fetchone()
        if row:
            return _enrich_item(db, table, dict(row))
        return None


def _enrich_item(db, table: str, item: dict) -> dict:
    """给item附加标签列表和附件列表"""
    # 标签
    tag_rows = db.execute(
        "SELECT t.id, t.name FROM tags t "
        "INNER JOIN item_tags it ON t.id = it.tag_id "
        "WHERE it.table_name=? AND it.item_id=? ORDER BY t.name",
        (table, item["id"])
    ).fetchall()
    item["tag_list"] = [dict(r) for r in tag_rows]
    
    # 附件
    docs = db.execute(
        "SELECT * FROM documents WHERE related_table=? AND related_id=? ORDER BY uploaded_at DESC",
        (table, item["id"])
    ).fetchall()
    item["documents"] = [dict(d) for d in docs]
    
    # 反向链接
    backlinks = db.execute(
        "SELECT l.*, "
        "CASE l.source_table "
        "  WHEN 'projects' THEN (SELECT name FROM projects WHERE id=l.source_id) "
        "  WHEN 'job_applications' THEN (SELECT company FROM job_applications WHERE id=l.source_id) "
        "  WHEN 'learning_notes' THEN (SELECT title FROM learning_notes WHERE id=l.source_id) "
        "END as source_title "
        "FROM links l WHERE l.target_table=? AND l.target_id=? "
        "ORDER BY l.created_at DESC LIMIT 10",
        (table, item["id"])
    ).fetchall()
    item["backlinks"] = [dict(r) for r in backlinks]
    
    return item


def _create(table: str, data: dict) -> int:
    table = _real_table(table)
    columns = [k for k in data.keys() if k not in ("id", "updated_at", "created_at", "documents", "tag_list", "deleted_at")]
    _validate_columns(table, columns)
    placeholders = ", ".join(["?" for _ in columns])
    cols = ", ".join(columns)
    
    with _conn() as db:
        cur = db.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
            [data[c] for c in columns]
        )
        item_id = cur.lastrowid
        db.commit()
    
    # 在事务外同步标签（避免锁冲突）
    tags_value = data.get("tags", "")
    _sync_tags(table, item_id, tags_value)
    
    # 同步 WikiLinks（笔记/项目/求职的内容字段）
    content = data.get("content") or data.get("description") or data.get("notes")
    if content:
        _sync_links(table, item_id, content)

    # 同步向量索引（仅笔记表）
    if table == "learning_notes":
        try:
            from hybrid_search import sync_note_embedding
            sync_note_embedding(item_id, data.get("title", ""), data.get("content", ""))
        except Exception:
            pass

    return item_id


def _update(table: str, item_id: int, data: dict):
    table = _real_table(table)
    columns = [k for k in data.keys() if k not in ("id", "updated_at", "created_at", "documents", "tag_list", "deleted_at")]
    _validate_columns(table, columns)
    columns.append("updated_at")
    sets = ", ".join([f"{c}=?" for c in columns])
    values = [data.get(c) for c in columns[:-1]] + [datetime.now().isoformat()]
    
    with _conn() as db:
        db.execute(
            f"UPDATE {table} SET {sets} WHERE id=?",
            values + [item_id]
        )
        db.commit()
    
    # 在事务外同步标签
    if "tags" in data:
        _sync_tags(table, item_id, data["tags"])
    
    # 同步 WikiLinks
    content = data.get("content") or data.get("description") or data.get("notes")
    if content:
        _sync_links(table, item_id, content)

    # 同步向量索引（仅笔记表）
    if table == "learning_notes":
        try:
            from hybrid_search import sync_note_embedding
            title = data.get("title") or ""
            content = data.get("content") or ""
            if title or content:
                sync_note_embedding(item_id, title, content)
        except Exception:
            pass


def _delete(table: str, item_id: int):
    """软删除：设置 deleted_at 时间戳"""
    table = _real_table(table)
    with _conn() as db:
        db.execute(
            f"UPDATE {table} SET deleted_at=?, updated_at=? WHERE id=?",
            (datetime.now().isoformat(), datetime.now().isoformat(), item_id)
        )
        db.commit()
        # 同步删除向量索引
        if table == "learning_notes":
            from hybrid_search import remove_note_embedding
            remove_note_embedding(item_id)


def _permanent_delete(table: str, item_id: int):
    """永久删除"""
    table = _real_table(table)
    with _conn() as db:
        docs = db.execute(
            "SELECT file_path FROM documents WHERE related_table=? AND related_id=?",
            (table, item_id)
        ).fetchall()
        for d in docs:
            try:
                os.remove(d["file_path"])
            except OSError:
                pass
        db.execute("DELETE FROM documents WHERE related_table=? AND related_id=?", (table, item_id))
        db.execute("DELETE FROM item_tags WHERE table_name=? AND item_id=?", (table, item_id))
        db.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
        db.commit()
        # 同步删除向量索引
        if table == "learning_notes":
            from hybrid_search import remove_note_embedding
            remove_note_embedding(item_id)


# ── 回收站 ──

def trash_list(limit: int = 50):
    """列出所有软删除的记录"""
    results = []
    for short, real in TABLE_MAP.items():
        with _conn() as db:
            rows = db.execute(
                f"SELECT *, '{real}' as _table FROM {real} WHERE deleted_at IS NOT NULL "
                f"ORDER BY deleted_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            for r in rows:
                item = dict(r)
                item["_table_short"] = short
                results.append(item)
    
    results.sort(key=lambda x: x.get("deleted_at", ""), reverse=True)
    return results[:limit]


def trash_restore(table: str, item_id: int):
    """从回收站恢复"""
    table = _real_table(table)
    with _conn() as db:
        db.execute(
            f"UPDATE {table} SET deleted_at=NULL, updated_at=? WHERE id=?",
            (datetime.now().isoformat(), item_id)
        )
        db.commit()


def trash_empty():
    """清空回收站（永久删除所有软删除记录）"""
    for short, real in TABLE_MAP.items():
        with _conn() as db:
            rows = db.execute(f"SELECT id FROM {real} WHERE deleted_at IS NOT NULL").fetchall()
            for r in rows:
                _permanent_delete(short, r["id"])


def trash_count() -> int:
    with _conn() as db:
        total = 0
        for real in TABLE_MAP.values():
            total += db.execute(f"SELECT COUNT(*) FROM {real} WHERE deleted_at IS NOT NULL").fetchone()[0]
        return total


# ── FTS5 全文搜索 ──

def search(keyword: str, limit: int = 20) -> dict:
    """FTS5全文搜索（排除已删除）"""
    results = {}
    fts_query = keyword.replace('"', '""')
    
    fts_tables = {
        "projects": ("projects_fts", "projects", "deleted_at IS NULL"),
        "applications": ("applications_fts", "job_applications", "deleted_at IS NULL"),
        "notes": ("notes_fts", "learning_notes", "deleted_at IS NULL"),
    }
    
    with _conn() as db:
        for short, (fts_table, real_table, filter_clause) in fts_tables.items():
            try:
                rows = db.execute(
                    f"SELECT t.* FROM {real_table} t "
                    f"INNER JOIN {fts_table} f ON t.id = f.rowid "
                    f"WHERE {fts_table} MATCH ? AND {filter_clause} ORDER BY rank LIMIT ?",
                    (fts_query, limit)
                ).fetchall()
                if rows:
                    results[short] = [_enrich_item(db, real_table, dict(r)) for r in rows]
            except Exception:
                pass
    
    return results


# ── 统计 ──

def stats() -> dict:
    with _conn() as db:
        return {
            "projects": db.execute("SELECT COUNT(*) FROM projects WHERE deleted_at IS NULL").fetchone()[0],
            "applications": db.execute("SELECT COUNT(*) FROM job_applications WHERE deleted_at IS NULL").fetchone()[0],
            "notes": db.execute("SELECT COUNT(*) FROM learning_notes WHERE deleted_at IS NULL").fetchone()[0],
            "documents": db.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "tags": db.execute("SELECT COUNT(*) FROM tags").fetchone()[0],
            "trash": trash_count(),
        }


# ── 附件管理 ──

def upload_document(related_table: str, related_id: int, doc_type: str, file_name: str, file_content: bytes) -> int:
    related_table = _real_table(related_table)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    timestamp = int(time.time())
    safe_name = f"{related_table}_{related_id}_{timestamp}_{file_name}"
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(file_path, "wb") as f:
        f.write(file_content)
    
    file_size = os.path.getsize(file_path)
    
    with _conn() as db:
        cur = db.execute(
            "INSERT INTO documents (related_table, related_id, doc_type, file_name, file_path, file_size) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (related_table, related_id, doc_type, file_name, file_path, file_size)
        )
        db.commit()
        return cur.lastrowid


def list_documents(related_table: str, related_id: int) -> list:
    related_table = _real_table(related_table)
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM documents WHERE related_table=? AND related_id=? ORDER BY uploaded_at DESC",
            (related_table, related_id)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_document(doc_id: int):
    with _conn() as db:
        doc = db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if doc:
            try:
                os.remove(doc["file_path"])
            except OSError:
                pass
            db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
            db.commit()


# ── Markdown 导入/导出（YAML frontmatter）──

FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.MULTILINE | re.DOTALL)


def export_note_markdown(note_id: int) -> Optional[str]:
    """导出笔记为 Markdown（含 YAML frontmatter）"""
    note = _get("notes", note_id)
    if not note:
        return None
    
    lines = ["---"]
    lines.append(f"title: {note.get('title', '')}")
    if note.get('topic'):
        lines.append(f"topic: {note['topic']}")
    if note.get('tags'):
        lines.append(f"tags: [{note['tags']}]")
    if note.get('source'):
        lines.append(f"source: {note['source']}")
    lines.append(f"created: {note.get('created_at', '')}")
    lines.append("---")
    lines.append("")
    lines.append(note.get("content", ""))
    
    return "\n".join(lines)


def import_note_markdown(markdown_text: str) -> dict:
    """从 Markdown（含 YAML frontmatter）解析为笔记数据"""
    data = {}
    body = markdown_text
    
    match = FRONTMATTER_RE.search(markdown_text)
    if match:
        try:
            import yaml
            frontmatter = yaml.safe_load(match.group(1)) or {}
        except Exception:
            # 无yaml库时手动解析简单字段
            frontmatter = _parse_simple_frontmatter(match.group(1))
        
        if isinstance(frontmatter, dict):
            data["title"] = frontmatter.get("title", "")
            data["topic"] = frontmatter.get("topic", "")
            tags = frontmatter.get("tags", "")
            if isinstance(tags, list):
                tags = ", ".join(tags)
            data["tags"] = tags
            data["source"] = frontmatter.get("source", "")
            # 序列化 frontmatter（处理 datetime 等非JSON类型）
            def _json_safe(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                return str(obj)
            data["frontmatter"] = json.dumps(frontmatter, ensure_ascii=False, default=_json_safe)
        
        body = markdown_text[match.end():].strip()
    
    data["content"] = body
    data["format"] = "markdown"
    
    return data


def _parse_simple_frontmatter(yaml_text: str) -> dict:
    """简易 YAML 解析（无需pyyaml）"""
    result = {}
    for line in yaml_text.strip().split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            # 列表处理: [a, b, c]
            if val.startswith("[") and val.endswith("]"):
                val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",")]
            result[key] = val
    return result


# ── 备份/恢复 ──

def backup_db() -> dict:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"personal_{timestamp}.db")
    
    with _conn() as src:
        dst = sqlite3.connect(backup_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    
    size = os.path.getsize(backup_path)
    _prune_backups()
    
    return {"path": backup_path, "size": size, "timestamp": timestamp}


def _prune_backups(keep: int = 20):
    if not os.path.exists(BACKUP_DIR):
        return
    backups = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.startswith("personal_") and f.endswith(".db")],
        reverse=True
    )
    for old in backups[keep:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            pass


def list_backups() -> list:
    if not os.path.exists(BACKUP_DIR):
        return []
    backups = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if f.startswith("personal_") and f.endswith(".db"):
            path = os.path.join(BACKUP_DIR, f)
            backups.append({
                "filename": f,
                "size": os.path.getsize(path),
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path))),
            })
    return backups


def restore_db(filename: str) -> bool:
    backup_path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"备份文件不存在: {filename}")
    
    if os.path.exists(DB_PATH):
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        pre_restore = os.path.join(BACKUP_DIR, f"pre_restore_{timestamp}.db")
        shutil.copy2(DB_PATH, pre_restore)
    
    src = sqlite3.connect(backup_path)
    try:
        with _conn() as dst:
            src.backup(dst)
    finally:
        src.close()
    
    return True


# 启动时初始化
init_db()
