"""Pydantic 数据模型 — API 契约层"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ── 项目 ──
class ProjectCreate(BaseModel):
    name: str
    tech_stack: Optional[str] = None
    description: Optional[str] = None
    github_url: Optional[str] = None
    highlights: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    category: str = "个人项目"
    tags: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    tech_stack: Optional[str] = None
    description: Optional[str] = None
    github_url: Optional[str] = None
    highlights: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[str] = None


# ── 求职 ──
class ApplicationCreate(BaseModel):
    company: str
    position: Optional[str] = None
    location: Optional[str] = None
    status: str = "已投递"
    apply_date: Optional[str] = None
    notes: Optional[str] = None
    salary_range: Optional[str] = None
    contact_info: Optional[str] = None
    tags: str = ""


class ApplicationUpdate(BaseModel):
    company: Optional[str] = None
    position: Optional[str] = None
    location: Optional[str] = None
    status: Optional[str] = None
    apply_date: Optional[str] = None
    notes: Optional[str] = None
    salary_range: Optional[str] = None
    contact_info: Optional[str] = None
    tags: Optional[str] = None


# ── 笔记 ──
class NoteCreate(BaseModel):
    title: str
    topic: Optional[str] = None
    tags: str = ""
    content: Optional[str] = None
    source: Optional[str] = None
    format: str = "plain"


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    topic: Optional[str] = None
    tags: Optional[str] = None
    content: Optional[str] = None
    source: Optional[str] = None
    format: Optional[str] = None


# ── 通用 ──
class TagItem(BaseModel):
    id: int
    name: str
    count: Optional[int] = None

class StatsResponse(BaseModel):
    projects: int
    applications: int
    notes: int
    documents: int
    tags: int
    trash: int

class BackupInfo(BaseModel):
    path: str
    size: int
    timestamp: str
