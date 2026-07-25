"""标签 Repository"""
from repositories.base import BaseRepository
from personal_db import list_all_tags, rename_tag, delete_tag


class TagRepository(BaseRepository):
    
    def list_all(self):
        return list_all_tags()
    
    def rename(self, tag_id: int, new_name: str):
        rename_tag(tag_id, new_name)
    
    def delete(self, tag_id: int):
        delete_tag(tag_id)


tag_repo = TagRepository()
