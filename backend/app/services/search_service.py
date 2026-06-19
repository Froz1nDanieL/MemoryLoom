from __future__ import annotations

import logging
from datetime import timezone

from app.config import Settings
from app.db.lance_store import LanceVectorStore, VectorSearchMatch
from app.db.sqlite_store import MemoryEventRecord, SQLiteStore
from app.schemas import SearchRequest, SearchResponse, SearchResult
from app.services.embedding_service import EmbeddingService


logger = logging.getLogger(__name__)


class SearchService:
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

    def search(self, payload: SearchRequest) -> SearchResponse:
        if payload.end_at and payload.start_at and payload.end_at < payload.start_at:
            raise ValueError("end_at must be greater than or equal to start_at")

        results: list[SearchResult] = []
        backend_parts: list[str] = []

        if payload.backend in ("hybrid", "keyword"):
            keyword_results = self._keyword_results(payload)
            results.extend(keyword_results)
            backend_parts.append("keyword")

        if payload.backend in ("hybrid", "vector"):
            vector_results = self._vector_results(
                payload,
                strict=payload.backend == "vector",
            )
            results.extend(vector_results)
            backend_parts.append("vector")

        merged = self._merge_results(results, payload.top_k)
        return SearchResponse(
            query=payload.query,
            backend="+".join(backend_parts) if backend_parts else payload.backend,
            results=merged,
        )

    def _keyword_results(self, payload: SearchRequest) -> list[SearchResult]:
        records = self._sqlite_store.keyword_search(payload, payload.top_k)
        return [
            self._event_to_search_result(
                record=record,
                score=max(0.25, 0.9 - index * 0.02),
                score_kind="keyword",
            )
            for index, record in enumerate(records)
        ]

    def _vector_results(self, payload: SearchRequest, strict: bool) -> list[SearchResult]:
        try:
            query_vector = self._embedding_service.encode_query(payload.query)
            matches = self._lance_store.search(
                query_vector=query_vector,
                limit=payload.top_k * self._settings.vector_search_multiplier,
            )
        except Exception as exc:
            if strict:
                raise RuntimeError(f"vector search failed: {exc}") from exc

            logger.warning("Vector search skipped: %s", exc)
            return []

        filtered = [match for match in matches if self._match_filters(match, payload)]
        return [
            SearchResult(
                event_id=match.event_id,
                chunk_id=match.chunk_id,
                source=match.source,
                content=match.content,
                score=match.score,
                score_kind="vector",
                captured_at=match.captured_at,
                app_name=match.app_name,
                window_title=match.window_title,
                url=match.url,
                metadata=match.metadata,
            )
            for match in filtered[: payload.top_k]
        ]

    @staticmethod
    def _event_to_search_result(
        record: MemoryEventRecord,
        score: float,
        score_kind: str,
    ) -> SearchResult:
        return SearchResult(
            event_id=record.event_id,
            chunk_id=None,
            source=record.source,
            content=record.content,
            score=score,
            score_kind=score_kind,
            captured_at=record.captured_at,
            app_name=record.app_name,
            window_title=record.window_title,
            url=record.url,
            metadata=record.metadata,
        )

    @staticmethod
    def _match_filters(match: VectorSearchMatch, payload: SearchRequest) -> bool:
        if payload.source and match.source != payload.source:
            return False
        if payload.app_name and match.app_name != payload.app_name:
            return False

        captured_at = match.captured_at
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)

        if payload.start_at:
            start_at = payload.start_at
            if start_at.tzinfo is None:
                start_at = start_at.replace(tzinfo=timezone.utc)
            if captured_at < start_at.astimezone(timezone.utc):
                return False
        if payload.end_at:
            end_at = payload.end_at
            if end_at.tzinfo is None:
                end_at = end_at.replace(tzinfo=timezone.utc)
            if captured_at > end_at.astimezone(timezone.utc):
                return False

        return True

    @staticmethod
    def _merge_results(results: list[SearchResult], limit: int) -> list[SearchResult]:
        merged: dict[int, SearchResult] = {}
        for result in results:
            existing = merged.get(result.event_id)
            if existing is None or result.score > existing.score:
                merged[result.event_id] = result

        return sorted(
            merged.values(),
            key=lambda item: (item.score, item.captured_at),
            reverse=True,
        )[:limit]
