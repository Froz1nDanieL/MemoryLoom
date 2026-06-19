from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


MemorySource = Literal[
    "clipboard",
    "window",
    "browser",
    "wechat",
    "manual",
    "system",
]
PrivacyLevel = Literal["normal", "sensitive", "private"]
SearchBackend = Literal["hybrid", "keyword", "vector"]


class IngestRequest(BaseModel):
    source: MemorySource | str = Field(..., min_length=1, max_length=128)
    content: str = Field(..., min_length=1)
    app_name: str | None = Field(default=None, max_length=256)
    window_title: str | None = Field(default=None, max_length=512)
    url: str | None = Field(default=None, max_length=2048)
    process_name: str | None = Field(default=None, max_length=256)
    device_id: str | None = Field(default=None, max_length=128)
    timezone: str | None = Field(default=None, max_length=64)
    privacy_level: PrivacyLevel = "normal"
    tags: list[str] = Field(default_factory=list, max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime | None = None

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content must not be empty")
        return normalized

    def captured_at_utc(self) -> datetime:
        captured_at = self.captured_at or datetime.now(timezone.utc)
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        return captured_at.astimezone(timezone.utc)


class IngestResponse(BaseModel):
    id: int
    status: str
    queued_for_embedding: bool
    content_hash: str


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)
    backend: SearchBackend = "hybrid"
    source: str | None = Field(default=None, max_length=128)
    app_name: str | None = Field(default=None, max_length=256)
    start_at: datetime | None = None
    end_at: datetime | None = None

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query must not be empty")
        return normalized


class SearchResult(BaseModel):
    event_id: int
    chunk_id: str | None = None
    source: str
    content: str
    score: float
    score_kind: str
    captured_at: datetime
    app_name: str | None = None
    window_title: str | None = None
    url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    backend: str
    results: list[SearchResult]


class EmbedNowResponse(BaseModel):
    claimed_jobs: int
    embedded_events: int
    embedded_chunks: int
    failed_jobs: int
    message: str


class HealthResponse(BaseModel):
    status: str
    version: str
    sqlite_path: str
    lancedb_uri: str
    model_reference: str
    model_loaded: bool
    lancedb_ready: bool
    total_events: int
    embedding_jobs: dict[str, int]
