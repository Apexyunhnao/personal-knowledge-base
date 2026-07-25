"""Repository 基类"""
from db import get_conn


class BaseRepository:
    """所有 Repository 的基类，提供连接获取"""
    
    @staticmethod
    def conn():
        return get_conn()
