from __future__ import annotations

import logging
from typing import Any

from app.config import Settings
from app.db.lance_store import LanceVectorStore
from app.db.sqlite_store import EmbeddingJobRecord, SQLiteStore
from app.schemas import EmbedNowResponse
from app.services.embedding_service import EmbeddingService
from app.services.text_chunker import chunk_text


logger = logging.getLogger(__name__)


class EmbeddingPipeline:
    def __init__(
        self,
        settings: Settings,
        sqlite_store: SQLiteStore,
        embedding_service: EmbeddingService,
        lance_store: LanceVectorStore,
    ) -> None:
        self._settings = settings
        self._sqlite_store = sqlite_store
        self._embedding_service = embedding_service
        self._lance_store = lance_store

    def run_once(self) -> EmbedNowResponse:
        jobs = self._sqlite_store.claim_embedding_jobs(self._settings.embedding_batch_size)
        if not jobs:
            return EmbedNowResponse(
                claimed_jobs=0,
                embedded_events=0,
                embedded_chunks=0,
                failed_jobs=0,
                message="no pending embedding jobs",
            )

        job_ids = [job.job_id for job in jobs]
        try:
            rows = self._build_lance_rows(jobs)
            embedded_chunks = self._lance_store.upsert_chunks(rows)
            self._sqlite_store.mark_jobs_embedded(job_ids)
        except Exception as exc:
            error = str(exc)
            logger.exception("Embedding batch failed")
            self._sqlite_store.mark_jobs_failed(job_ids, error)
            return EmbedNowResponse(
                claimed_jobs=len(jobs),
                embedded_events=0,
                embedded_chunks=0,
                failed_jobs=len(jobs),
                message=error,
            )

        return EmbedNowResponse(
            claimed_jobs=len(jobs),
            embedded_events=len(jobs),
            embedded_chunks=embedded_chunks,
            failed_jobs=0,
            message="embedding batch completed",
        )

    def requeue_failed_jobs(self) -> int:
        return self._sqlite_store.requeue_failed_jobs()

    def _build_lance_rows(self, jobs: list[EmbeddingJobRecord]) -> list[dict[str, Any]]:
        chunk_records: list[tuple[EmbeddingJobRecord, int, str]] = []
        for job in jobs:
            chunks = chunk_text(
                job.event.content,
                chunk_size=self._settings.chunk_size,
                overlap=self._settings.chunk_overlap,
            )
            for chunk_index, chunk in enumerate(chunks):
                chunk_records.append((job, chunk_index, chunk))

        texts = [chunk for _, _, chunk in chunk_records]
        vectors = self._embedding_service.encode_documents(texts)

        rows: list[dict[str, Any]] = []
        for (job, chunk_index, chunk), vector in zip(chunk_records, vectors, strict=True):
            event = job.event
            rows.append(
                {
                    "chunk_id": f"{event.event_id}:{chunk_index}",
                    "event_id": event.event_id,
                    "chunk_index": chunk_index,
                    "vector": vector,
                    "content": chunk,
                    "source": event.source,
                    "captured_at": event.captured_at.isoformat(),
                    "app_name": event.app_name,
                    "window_title": event.window_title,
                    "url": event.url,
                    "metadata": event.metadata,
                    "content_hash": event.content_hash,
                }
            )

        return rows
