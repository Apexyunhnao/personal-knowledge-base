"""附件/回收站/搜索/备份 Repository"""
from repositories.base import BaseRepository
from personal_db import (
    upload_document, list_documents, delete_document,
    trash_list, trash_restore, trash_empty, trash_count,
    search, stats,
    backup_db, list_backups, restore_db,
)


class DocumentRepository(BaseRepository):
    
    def upload(self, table, item_id, doc_type, filename, content):
        return upload_document(table, item_id, doc_type, filename, content)
    
    def list_for(self, table, item_id):
        return list_documents(table, item_id)
    
    def delete(self, doc_id):
        delete_document(doc_id)


class TrashRepository(BaseRepository):
    
    def list(self, limit=50):
        return trash_list(limit)
    
    def restore(self, table, item_id):
        trash_restore(table, item_id)
    
    def empty(self):
        trash_empty()
    
    def count(self):
        return trash_count()


class SearchRepository(BaseRepository):
    
    def search(self, keyword, limit=20):
        return search(keyword, limit)


class StatsRepository(BaseRepository):
    
    def get(self):
        return stats()


class BackupRepository(BaseRepository):
    
    def create(self):
        return backup_db()
    
    def list(self):
        return list_backups()
    
    def restore(self, filename):
        return restore_db(filename)


doc_repo = DocumentRepository()
trash_repo = TrashRepository()
search_repo = SearchRepository()
stats_repo = StatsRepository()
backup_repo = BackupRepository()
