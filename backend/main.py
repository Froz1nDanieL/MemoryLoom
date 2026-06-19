from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field


APP_VERSION = "0.1.0"
BASE_DIR = Path(__file__).resolve().parent
DATABASE_DIR = BASE_DIR / "database"
DEFAULT_SQLITE_PATH = DATABASE_DIR / "buffer.sqlite3"

logger = logging.getLogger("memoryloom.backend")
logging.basicConfig(
    level=os.getenv("MEMORYLOOM_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)


class IngestRequest(BaseModel):
    source: str = Field(..., min_length=1, max_length=128)
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime | None = None


class IngestResponse(BaseModel):
    id: int
    status: str


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)


class SearchResult(BaseModel):
    id: str
    source: str
    content: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    captured_at: datetime


class SearchResponse(BaseModel):
    query: str
    backend: str
    results: list[SearchResult]


class SQLiteBuffer:
    def __init__(self, database_target: str) -> None:
        self._database_target = database_target
        self._lock = threading.RLock()
        self._connection = self._connect(database_target)
        self._initialize_schema()

    @staticmethod
    def _connect(database_target: str) -> sqlite3.Connection:
        if database_target != ":memory:":
            Path(database_target).parent.mkdir(parents=True, exist_ok=True)

        connection = sqlite3.connect(
            database_target,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")

        if database_target != ":memory:":
            connection.execute("PRAGMA journal_mode = WAL")

        return connection

    def _initialize_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ingest_buffer (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    captured_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    embedded INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ingest_buffer_embedded
                ON ingest_buffer (embedded, created_at)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ingest_buffer_source
                ON ingest_buffer (source, captured_at)
                """
            )

    def insert(self, payload: IngestRequest) -> int:
        captured_at = payload.captured_at or datetime.now(timezone.utc)
        metadata_json = json.dumps(payload.metadata, ensure_ascii=False)

        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO ingest_buffer (source, content, metadata_json, captured_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    payload.source,
                    payload.content,
                    metadata_json,
                    captured_at.astimezone(timezone.utc).isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def keyword_search(self, query: str, limit: int) -> list[sqlite3.Row]:
        like_query = f"%{query}%"

        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT id, source, content, metadata_json, captured_at
                FROM ingest_buffer
                WHERE content LIKE ?
                ORDER BY captured_at DESC
                LIMIT ?
                """,
                (like_query, limit),
            )
            return list(cursor.fetchall())

    def count_pending_embeddings(self) -> int:
        with self._lock:
            cursor = self._connection.execute(
                "SELECT COUNT(*) AS total FROM ingest_buffer WHERE embedded = 0"
            )
            row = cursor.fetchone()
            return int(row["total"] if row else 0)

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def get_sqlite_target() -> str:
    return os.getenv("MEMORYLOOM_SQLITE_PATH", str(DEFAULT_SQLITE_PATH))


def build_scheduler(buffer: SQLiteBuffer) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        lambda: run_embedding_batch(buffer),
        trigger="interval",
        minutes=5,
        id="embedding-batch",
        max_instances=1,
        replace_existing=True,
    )
    return scheduler


def run_embedding_batch(buffer: SQLiteBuffer) -> None:
    pending_count = buffer.count_pending_embeddings()
    if pending_count:
        logger.info("Embedding batch placeholder: %s pending item(s)", pending_count)


@asynccontextmanager
async def lifespan(app: FastAPI):
    buffer = SQLiteBuffer(get_sqlite_target())
    scheduler = build_scheduler(buffer)

    app.state.buffer = buffer
    app.state.scheduler = scheduler

    scheduler.start()
    logger.info("Memory Loom backend started")

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        buffer.close()
        logger.info("Memory Loom backend stopped")


app = FastAPI(
    title="Memory Loom Backend",
    version=APP_VERSION,
    description="Local ingest and retrieval service for Memory Loom.",
    lifespan=lifespan,
)


def buffer_from_app() -> SQLiteBuffer:
    return app.state.buffer


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        pending = buffer_from_app().count_pending_embeddings()
    except Exception as exc:
        logger.exception("Health check failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="backend health check failed",
        ) from exc

    return {
        "status": "ok",
        "version": APP_VERSION,
        "pending_embeddings": pending,
    }


@app.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
def ingest(payload: IngestRequest) -> IngestResponse:
    try:
        event_id = buffer_from_app().insert(payload)
    except sqlite3.Error as exc:
        logger.exception("Failed to write ingest payload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to buffer ingest payload",
        ) from exc

    return IngestResponse(id=event_id, status="accepted")


@app.post("/search", response_model=SearchResponse)
def search(payload: SearchRequest) -> SearchResponse:
    query = payload.query.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="query must not be empty",
        )

    try:
        rows = buffer_from_app().keyword_search(query, payload.top_k)
    except sqlite3.Error as exc:
        logger.exception("Search failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="search failed",
        ) from exc

    results = [
        SearchResult(
            id=str(row["id"]),
            source=row["source"],
            content=row["content"],
            score=0.0,
            metadata=json.loads(row["metadata_json"] or "{}"),
            captured_at=datetime.fromisoformat(row["captured_at"]),
        )
        for row in rows
    ]

    return SearchResponse(query=query, backend="sqlite-buffer", results=results)


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("MEMORYLOOM_BACKEND_HOST", "127.0.0.1")
    port = int(os.getenv("MEMORYLOOM_BACKEND_PORT", "8765"))
    uvicorn.run("main:app", host=host, port=port, reload=False)
