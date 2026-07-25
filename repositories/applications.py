"""求职 Repository"""
from repositories.base import BaseRepository
from personal_db import _list, _get, _create, _update, _delete

TABLE = "applications"


class ApplicationRepository(BaseRepository):
    
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


application_repo = ApplicationRepository()
