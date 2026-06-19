from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config import Settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VectorSearchMatch:
    chunk_id: str
    event_id: int
    chunk_index: int
    content: str
    source: str
    captured_at: datetime
    score: float
    metadata: dict[str, Any]
    app_name: str | None = None
    window_title: str | None = None
    url: str | None = None


class LanceVectorStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._settings.lancedb_uri.mkdir(parents=True, exist_ok=True)
        self._db = None

    def table_exists(self) -> bool:
        try:
            db = self._connect()
            return self._settings.lancedb_table in db.table_names()
        except Exception:
            return False

    def upsert_chunks(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0

        table = self._open_or_create_table(rows)
        event_ids = sorted({int(row["event_id"]) for row in rows})
        for event_id in event_ids:
            try:
                table.delete(f"event_id = {event_id}")
            except Exception as exc:
                logger.debug("Ignoring LanceDB delete miss for event %s: %s", event_id, exc)

        table.add(rows)
        return len(rows)

    def search(self, query_vector: list[float], limit: int) -> list[VectorSearchMatch]:
        if not query_vector or not self.table_exists():
            return []

        table = self._connect().open_table(self._settings.lancedb_table)
        raw_results = table.search(query_vector).limit(limit).to_list()
        matches: list[VectorSearchMatch] = []

        for row in raw_results:
            distance = float(row.get("_distance", row.get("_score", 0.0)) or 0.0)
            score = 1.0 / (1.0 + max(distance, 0.0))
            metadata = row.get("metadata")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    metadata = {}

            matches.append(
                VectorSearchMatch(
                    chunk_id=str(row["chunk_id"]),
                    event_id=int(row["event_id"]),
                    chunk_index=int(row["chunk_index"]),
                    content=str(row["content"]),
                    source=str(row["source"]),
                    captured_at=datetime.fromisoformat(str(row["captured_at"])),
                    score=score,
                    metadata=metadata or {},
                    app_name=row.get("app_name"),
                    window_title=row.get("window_title"),
                    url=row.get("url"),
                )
            )

        return matches

    def _connect(self):
        if self._db is not None:
            return self._db

        try:
            import lancedb
        except ImportError as exc:
            raise RuntimeError(
                "lancedb is not installed. Install backend dependencies with "
                "`python -m pip install -r requirements.txt`."
            ) from exc

        self._db = lancedb.connect(str(self._settings.lancedb_uri))
        return self._db

    def _open_or_create_table(self, rows: list[dict[str, Any]]):
        db = self._connect()
        table_name = self._settings.lancedb_table
        try:
            return db.open_table(table_name)
        except Exception:
            logger.info("Creating LanceDB table %s", table_name)
            return db.create_table(table_name, data=rows)
