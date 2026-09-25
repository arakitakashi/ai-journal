from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Article(BaseModel):
    url: str
    title: str
    source: str
    published_at: datetime
    body: str = ""
    primary: bool = True


class Collection(BaseModel):
    since: datetime | None = None
    articles: list[Article] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checkpoints: dict[str, str] = Field(default_factory=dict)


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: int
    theme: Literal["ガバナンス", "評価", "AI基盤", "小売業のAI活用事例", "バックオフィス効率化事例"]
    title: str
    facts: str
    impact: str
    caveats: str
    evidence: str


class Digest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    overview: str
    items: list[Item] = Field(max_length=8)


class Published(BaseModel):
    day: str
    until: datetime
    urls: list[str]
    url: str
