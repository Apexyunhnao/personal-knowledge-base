"""笔记 Repository"""
from repositories.base import BaseRepository
from personal_db import _list, _get, _create, _update, _delete

TABLE = "notes"


class NoteRepository(BaseRepository):
    
    def list(self, limit=50, offset=0, tag=None):
        return _list(TABLE, limit, offset, tag=tag)
    
    def get(self, item_id: int):
        return _get(TABLE, item_id)
    
    def create(self, data: dict) -> int:
        return _create(TABLE, data)
    
    def update(self, item_id: int, data: dict):
        _update(TABLE, item_id, data)
    
    def delete(self, item_id: int):
        _delete(TABLE, item_id)
    
    def permanent_delete(self, item_id: int):
        from personal_db import _permanent_delete
        _permanent_delete(TABLE, item_id)
    
    def export_markdown(self, note_id: int):
        from personal_db import export_note_markdown
        return export_note_markdown(note_id)
    
    def import_markdown(self, markdown_text: str) -> dict:
        from personal_db import import_note_markdown
        return import_note_markdown(markdown_text)


note_repo = NoteRepository()
