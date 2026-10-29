from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Platform = Literal["x", "tiktok", "instagram", "telegram"]
PostStatus = Literal[
    "new", "filtering", "pending_review", "ignored", "approved", "queued",
    "processing", "ready", "publishing", "published", "publish_unknown",
    "rejected", "failed",
]


@dataclass(slots=True)
class MediaItem:
    kind: Literal["image", "video"]
    url: str
    local_path: str | None = None
    processed_path: str | None = None
    width: int | None = None
    height: int | None = None


@dataclass(slots=True)
class DiscoveredPost:
    external_id: str
    url: str
    author: str
    text: str
    published_at: datetime | None = None
    media: list[MediaItem] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class AIClassification(BaseModel):
    decision: Literal["publish", "ignore", "review"]
    reason: str = Field(min_length=1, max_length=700)
    category: str = Field(default="general", max_length=80)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    important: bool = False
    replace_phone: bool = False
    cleaned_text: str | None = Field(default=None, max_length=12000)

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision(cls, value: object) -> object:
        mapping = {
            "نشر": "publish", "تجاهل": "ignore", "مراجعة": "review",
            "post": "publish", "skip": "ignore", "reject": "ignore",
        }
        return mapping.get(str(value).strip().lower(), value)


class AccountInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    platform: Platform
    username: str = Field(default="", max_length=150)
    proxy_url: str | None = Field(default=None, max_length=1000)
    phone_replacement: str = Field(default="", max_length=40)
    monitor_interval_sec: int = Field(default=900, ge=60, le=86400)
    min_delay_sec: int = Field(default=45, ge=0, le=86400)
    max_delay_sec: int = Field(default=180, ge=0, le=86400)
    review_required: bool = True
    auto_publish: bool = False
    enabled: bool = False
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("max_delay_sec")
    @classmethod
    def validate_delays(cls, value: int, info: Any) -> int:
        minimum = info.data.get("min_delay_sec", 0)
        if value < minimum:
            raise ValueError("max_delay_sec يجب أن يكون أكبر من أو يساوي min_delay_sec")
        return value


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    username: str | None = Field(default=None, max_length=150)
    proxy_url: str | None = Field(default=None, max_length=1000)
    phone_replacement: str | None = Field(default=None, max_length=40)
    monitor_interval_sec: int | None = Field(default=None, ge=60, le=86400)
    min_delay_sec: int | None = Field(default=None, ge=0, le=86400)
    max_delay_sec: int | None = Field(default=None, ge=0, le=86400)
    review_required: bool | None = None
    auto_publish: bool | None = None
    enabled: bool | None = None
    settings: dict[str, Any] | None = None


class SourceInput(BaseModel):
    platform: Literal["x", "tiktok", "instagram"]
    handle: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=8, max_length=2000)
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class SourcePatch(BaseModel):
    handle: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, min_length=8, max_length=2000)
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class ReviewInput(BaseModel):
    action: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=2000)
    processed_text: str | None = Field(default=None, max_length=12000)


class ChatInput(BaseModel):
    account_id: str | None = None
    message: str = Field(min_length=1, max_length=3000)


class AIConfigInput(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=150)
    timeout_seconds: float = Field(default=60, ge=5, le=300)


class AIConfigPatch(BaseModel):
    base_url: str | None = Field(default=None, min_length=8, max_length=500)
    model: str | None = Field(default=None, min_length=1, max_length=150)
    timeout_seconds: float | None = Field(default=None, ge=5, le=300)
