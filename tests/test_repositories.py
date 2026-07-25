"""Repository 层单元测试 — CRUD / 标签 / 软删除 / WikiLinks"""
import pytest


class TestCRUD:
    """基础增删改查"""
    
    def test_create_and_get(self, temp_db, sample_data):
        item = temp_db._get("projects", sample_data["project_id"])
        assert item["name"] == "测试项目"
        assert item["tech_stack"] == "Python,SQLite"
    
    def test_list(self, temp_db, sample_data):
        items = temp_db._list("projects")
        assert len(items) >= 1
        assert items[0]["name"] == "测试项目"
    
    def test_update(self, temp_db, sample_data):
        temp_db._update("projects", sample_data["project_id"], {"name": "更新后的项目"})
        item = temp_db._get("projects", sample_data["project_id"])
        assert item["name"] == "更新后的项目"
    
    def test_delete_soft(self, temp_db, sample_data):
        temp_db._delete("projects", sample_data["project_id"])
        # 查询不含已删除
        items = temp_db._list("projects")
        assert all(i["id"] != sample_data["project_id"] for i in items)


class TestTags:
    """标签系统"""
    
    def test_tags_synced_on_create(self, temp_db, sample_data):
        tags = temp_db.list_all_tags()
        tag_names = [t["name"] for t in tags]
        assert "Python" in tag_names
        assert "测试" in tag_names
    
    def test_tag_rename(self, temp_db, sample_data):
        tags = temp_db.list_all_tags()
        py_tag = next(t for t in tags if t["name"] == "Python")
        temp_db.rename_tag(py_tag["id"], "Python开发")
        
        tags = temp_db.list_all_tags()
        assert any(t["name"] == "Python开发" for t in tags)
        assert not any(t["name"] == "Python" for t in tags)
        
        # 验证关联记录的tags字段也更新了
        item = temp_db._get("projects", sample_data["project_id"])
        assert "Python开发" in item["tags"]
    
    def test_tag_filter(self, temp_db, sample_data):
        items = temp_db._list("projects", tag="Python")
        assert len(items) >= 1


class TestSoftDelete:
    """软删除与回收站"""
    
    def test_trash_count(self, temp_db, sample_data):
        assert temp_db.trash_count() == 0
        temp_db._delete("projects", sample_data["project_id"])
        assert temp_db.trash_count() == 1
    
    def test_trash_restore(self, temp_db, sample_data):
        temp_db._delete("projects", sample_data["project_id"])
        temp_db.trash_restore("projects", sample_data["project_id"])
        assert temp_db.trash_count() == 0
        item = temp_db._get("projects", sample_data["project_id"])
        assert item is not None
    
    def test_permanent_delete(self, temp_db, sample_data):
        temp_db._delete("projects", sample_data["project_id"])
        temp_db._permanent_delete("projects", sample_data["project_id"])
        assert temp_db.trash_count() == 0
        assert temp_db._get("projects", sample_data["project_id"]) is None


class TestWikiLinks:
    """双向链接"""
    
    def test_wikilink_parsed(self, temp_db):
        from personal_db import _parse_wikilinks
        links = _parse_wikilinks("参考 [[笔记A]] 和 [[笔记B]] 的内容")
        assert links == ["笔记A", "笔记B"]
    
    def test_wikilink_empty(self, temp_db):
        from personal_db import _parse_wikilinks
        assert _parse_wikilinks("") == []
        assert _parse_wikilinks(None) == []
    
    def test_backlinks(self, temp_db, sample_data):
        """笔记引用了项目，项目应该有反向链接"""
        bl = temp_db.get_backlinks("projects", sample_data["project_id"])
        assert len(bl) >= 1
        assert bl[0]["link_text"] == "测试项目"
    
    def test_graph_data(self, temp_db, sample_data):
        graph = temp_db.get_graph_data()
        assert len(graph["nodes"]) >= 3
        assert len(graph["edges"]) >= 1


class TestSearch:
    """FTS5 全文搜索"""
    
    def test_fts5_search(self, temp_db, sample_data):
        results = temp_db.search("SQLite")
        assert "notes" in results or "projects" in results
    
    def test_search_excludes_deleted(self, temp_db, sample_data):
        temp_db._delete("notes", sample_data["note_id"])
        results = temp_db.search("SQLite")
        # 已删除的不应出现在搜索中
        if "notes" in results:
            ids = [n["id"] for n in results["notes"]]
            assert sample_data["note_id"] not in ids


class TestStats:
    """统计"""
    
    def test_stats(self, temp_db, sample_data):
        s = temp_db.stats()
        assert s["projects"] >= 1
        assert s["applications"] >= 1
        assert s["notes"] >= 1
        assert "tags" in s
        assert "trash" in s
