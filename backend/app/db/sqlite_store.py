from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.config import Settings
from app.schemas import IngestRequest, SearchRequest


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryEventRecord:
    event_id: int
    source: str
    content: str
    content_hash: str
    captured_at: datetime
    metadata: dict[str, Any]
    app_name: str | None = None
    window_title: str | None = None
    url: str | None = None
    process_name: str | None = None
    device_id: str | None = None
    timezone: str | None = None
    privacy_level: str = "normal"
    tags: list[str] | None = None


@dataclass(frozen=True)
class EmbeddingJobRecord:
    job_id: int
    event: MemoryEventRecord
    attempts: int


class SQLiteStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._connection = self._connect(settings.sqlite_path)
        self._initialize_schema()

    @staticmethod
    def _connect(sqlite_path: Path) -> sqlite3.Connection:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(sqlite_path),
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_schema(self) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    app_name TEXT,
                    window_title TEXT,
                    url TEXT,
                    process_name TEXT,
                    device_id TEXT,
                    timezone TEXT,
                    privacy_level TEXT NOT NULL DEFAULT 'normal',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    captured_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS embedding_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    embedded_at TEXT,
                    FOREIGN KEY(event_id) REFERENCES memory_events(id) ON DELETE CASCADE
                )
                """
            )
            self._connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_events_fts
                USING fts5(
                    content,
                    source,
                    app_name,
                    window_title,
                    url,
                    metadata_json,
                    content='memory_events',
                    content_rowid='id',
                    tokenize='unicode61'
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_events_captured_at ON memory_events (captured_at)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_events_source ON memory_events (source, captured_at)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_events_hash ON memory_events (content_hash)"
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_embedding_jobs_status ON embedding_jobs (status, updated_at)"
            )
            self._migrate_legacy_ingest_buffer()

    def _migrate_legacy_ingest_buffer(self) -> None:
        cursor = self._connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'ingest_buffer'
            """
        )
        if cursor.fetchone() is None:
            return

        already_migrated = self._connection.execute(
            "SELECT COUNT(*) AS total FROM memory_events"
        ).fetchone()
        if already_migrated and int(already_migrated["total"]) > 0:
            return

        rows = self._connection.execute(
            """
            SELECT source, content, metadata_json, captured_at
            FROM ingest_buffer
            ORDER BY id
            """
        ).fetchall()
        for row in rows:
            payload = IngestRequest(
                source=row["source"],
                content=row["content"],
                metadata=json.loads(row["metadata_json"] or "{}"),
                captured_at=datetime.fromisoformat(row["captured_at"]),
            )
            self.insert_event(payload)

        logger.info("Migrated %s legacy ingest_buffer row(s)", len(rows))

    def insert_event(self, payload: IngestRequest) -> MemoryEventRecord:
        captured_at = payload.captured_at_utc()
        metadata_json = json.dumps(payload.metadata, ensure_ascii=False)
        tags_json = json.dumps(payload.tags, ensure_ascii=False)
        content_hash = self._hash_content(
            source=str(payload.source),
            content=payload.content,
            captured_at=captured_at,
        )

        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT INTO memory_events (
                    source,
                    content,
                    content_hash,
                    app_name,
                    window_title,
                    url,
                    process_name,
                    device_id,
                    timezone,
                    privacy_level,
                    tags_json,
                    metadata_json,
                    captured_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(payload.source),
                    payload.content,
                    content_hash,
                    payload.app_name,
                    payload.window_title,
                    payload.url,
                    payload.process_name,
                    payload.device_id,
                    payload.timezone,
                    payload.privacy_level,
                    tags_json,
                    metadata_json,
                    captured_at.isoformat(),
                ),
            )
            event_id = int(cursor.lastrowid)
            self._connection.execute(
                """
                INSERT INTO memory_events_fts (
                    rowid,
                    content,
                    source,
                    app_name,
                    window_title,
                    url,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    payload.content,
                    str(payload.source),
                    payload.app_name or "",
                    payload.window_title or "",
                    payload.url or "",
                    metadata_json,
                ),
            )
            self._connection.execute(
                "INSERT INTO embedding_jobs (event_id, status) VALUES (?, 'pending')",
                (event_id,),
            )

        return MemoryEventRecord(
            event_id=event_id,
            source=str(payload.source),
            content=payload.content,
            content_hash=content_hash,
            captured_at=captured_at,
            metadata=payload.metadata,
            app_name=payload.app_name,
            window_title=payload.window_title,
            url=payload.url,
            process_name=payload.process_name,
            device_id=payload.device_id,
            timezone=payload.timezone,
            privacy_level=payload.privacy_level,
            tags=payload.tags,
        )

    def claim_embedding_jobs(self, limit: int) -> list[EmbeddingJobRecord]:
        with self._lock, self._connection:
            rows = self._connection.execute(
                """
                SELECT
                    j.id AS job_id,
                    j.attempts AS attempts,
                    e.*
                FROM embedding_jobs j
                JOIN memory_events e ON e.id = j.event_id
                WHERE j.status = 'pending'
                ORDER BY j.created_at
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            if not rows:
                return []

            job_ids = [int(row["job_id"]) for row in rows]
            placeholders = ",".join("?" for _ in job_ids)
            now = datetime.now(timezone.utc).isoformat()
            self._connection.execute(
                f"""
                UPDATE embedding_jobs
                SET status = 'processing',
                    attempts = attempts + 1,
                    updated_at = ?
                WHERE id IN ({placeholders})
                """,
                (now, *job_ids),
            )

        return [
            EmbeddingJobRecord(
                job_id=int(row["job_id"]),
                event=self._row_to_event(row),
                attempts=int(row["attempts"]) + 1,
            )
            for row in rows
        ]

    def mark_jobs_embedded(self, job_ids: Iterable[int]) -> None:
        ids = list(job_ids)
        if not ids:
            return

        with self._lock, self._connection:
            placeholders = ",".join("?" for _ in ids)
            now = datetime.now(timezone.utc).isoformat()
            self._connection.execute(
                f"""
                UPDATE embedding_jobs
                SET status = 'embedded',
                    updated_at = ?,
                    embedded_at = ?,
                    last_error = NULL
                WHERE id IN ({placeholders})
                """,
                (now, now, *ids),
            )

    def mark_jobs_failed(self, job_ids: Iterable[int], error: str) -> None:
        ids = list(job_ids)
        if not ids:
            return

        with self._lock, self._connection:
            placeholders = ",".join("?" for _ in ids)
            now = datetime.now(timezone.utc).isoformat()
            self._connection.execute(
                f"""
                UPDATE embedding_jobs
                SET status = CASE
                        WHEN attempts >= ? THEN 'failed'
                        ELSE 'pending'
                    END,
                    updated_at = ?,
                    last_error = ?
                WHERE id IN ({placeholders})
                """,
                (
                    self._settings.max_embedding_attempts,
                    now,
                    error[:2000],
                    *ids,
                ),
            )

    def requeue_failed_jobs(self) -> int:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE embedding_jobs
                SET status = 'pending',
                    attempts = 0,
                    updated_at = ?,
                    last_error = NULL
                WHERE status = 'failed'
                """,
                (datetime.now(timezone.utc).isoformat(),),
            )
            return int(cursor.rowcount)

    def requeue_all_embedding_jobs(self) -> int:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM embedding_jobs")
            cursor = self._connection.execute(
                """
                INSERT INTO embedding_jobs (event_id, status)
                SELECT id, 'pending'
                FROM memory_events
                ORDER BY id
                """
            )
            return int(cursor.rowcount)

    def keyword_search(self, payload: SearchRequest, limit: int) -> list[MemoryEventRecord]:
        query = payload.query.strip()
        records: list[MemoryEventRecord] = []
        try:
            records = self._keyword_search_fts(payload, limit, query)
        except sqlite3.Error as exc:
            logger.warning("FTS search failed, falling back to LIKE: %s", exc)

        if len(records) < limit:
            merged = {record.event_id: record for record in records}
            for record in self._keyword_search_like(payload, limit, query):
                merged.setdefault(record.event_id, record)
            records = list(merged.values())

        return records[:limit]

    def get_events_by_ids(self, event_ids: Iterable[int]) -> dict[int, MemoryEventRecord]:
        ids = list(dict.fromkeys(int(event_id) for event_id in event_ids))
        if not ids:
            return {}

        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT *
                FROM memory_events
                WHERE id IN ({placeholders})
                """,
                ids,
            ).fetchall()
        return {record.event_id: record for record in map(self._row_to_event, rows)}

    def count_events(self) -> int:
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) AS total FROM memory_events").fetchone()
        return int(row["total"] if row else 0)

    def embedding_job_counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM embedding_jobs
                GROUP BY status
                """
            ).fetchall()
        counts = {row["status"]: int(row["total"]) for row in rows}
        for status in ("pending", "processing", "embedded", "failed"):
            counts.setdefault(status, 0)
        return counts

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _keyword_search_fts(
        self,
        payload: SearchRequest,
        limit: int,
        query: str,
    ) -> list[MemoryEventRecord]:
        match_query = self._build_fts_query(query)
        where_clauses, params = self._build_event_filters(payload, table_alias="e")
        where_sql = f"AND {' AND '.join(where_clauses)}" if where_clauses else ""

        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT e.*
                FROM memory_events_fts f
                JOIN memory_events e ON e.id = f.rowid
                WHERE memory_events_fts MATCH ?
                {where_sql}
                ORDER BY bm25(memory_events_fts), e.captured_at DESC
                LIMIT ?
                """,
                (match_query, *params, limit),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def _keyword_search_like(
        self,
        payload: SearchRequest,
        limit: int,
        query: str,
    ) -> list[MemoryEventRecord]:
        terms = self._build_like_terms(query)
        where_clauses, params = self._build_event_filters(payload, table_alias="e")
        term_clauses: list[str] = []
        for term in terms:
            term_clauses.append(
                """
                (
                    e.content LIKE ?
                    OR e.source LIKE ?
                    OR COALESCE(e.app_name, '') LIKE ?
                    OR COALESCE(e.window_title, '') LIKE ?
                    OR COALESCE(e.url, '') LIKE ?
                    OR COALESCE(e.metadata_json, '') LIKE ?
                )
                """
            )
            like_term = f"%{term}%"
            params.extend([like_term, like_term, like_term, like_term, like_term, like_term])

        where_clauses.append(f"({' OR '.join(term_clauses)})")

        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT e.*
                FROM memory_events e
                WHERE {' AND '.join(where_clauses)}
                ORDER BY e.captured_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _build_like_terms(query: str) -> list[str]:
        terms: list[str] = [query]

        for token in re.findall(r"[A-Za-z0-9_#.+-]{2,}", query):
            terms.append(token)

        seen: set[str] = set()
        unique_terms: list[str] = []
        for term in terms:
            normalized = term.strip()
            key = normalized.casefold()
            if len(normalized) < 2 or key in seen:
                continue
            seen.add(key)
            unique_terms.append(normalized)

        return unique_terms

    @staticmethod
    def _build_event_filters(
        payload: SearchRequest,
        table_alias: str,
    ) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        prefix = f"{table_alias}."

        if payload.source:
            clauses.append(f"{prefix}source = ?")
            params.append(payload.source)
        if payload.app_name:
            clauses.append(f"{prefix}app_name = ?")
            params.append(payload.app_name)
        if payload.start_at:
            clauses.append(f"{prefix}captured_at >= ?")
            params.append(SQLiteStore._as_utc_iso(payload.start_at))
        if payload.end_at:
            clauses.append(f"{prefix}captured_at <= ?")
            params.append(SQLiteStore._as_utc_iso(payload.end_at))

        return clauses, params

    @staticmethod
    def _build_fts_query(query: str) -> str:
        escaped = query.replace('"', '""')
        return f'"{escaped}"'

    @staticmethod
    def _hash_content(source: str, content: str, captured_at: datetime) -> str:
        value = f"{source}\n{captured_at.isoformat()}\n{content}".encode("utf-8")
        return hashlib.sha256(value).hexdigest()

    @staticmethod
    def _as_utc_iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> MemoryEventRecord:
        captured_at = datetime.fromisoformat(row["captured_at"])
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)

        return MemoryEventRecord(
            event_id=int(row["id"]),
            source=row["source"],
            content=row["content"],
            content_hash=row["content_hash"],
            captured_at=captured_at,
            metadata=json.loads(row["metadata_json"] or "{}"),
            app_name=row["app_name"],
            window_title=row["window_title"],
            url=row["url"],
            process_name=row["process_name"],
            device_id=row["device_id"],
            timezone=row["timezone"],
            privacy_level=row["privacy_level"],
            tags=json.loads(row["tags_json"] or "[]"),
        )
