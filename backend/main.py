from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException, Query, status

from app.config import APP_VERSION, Settings
from app.db.lance_store import LanceVectorStore
from app.db.sqlite_store import SQLiteStore
from app.schemas import (
    EmbedNowResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    SearchRequest,
    SearchResponse,
)
from app.services.embedding_pipeline import EmbeddingPipeline
from app.services.embedding_service import EmbeddingService
from app.services.search_service import SearchService


logger = logging.getLogger("memoryloom.backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    settings.configure_logging()

    sqlite_store = SQLiteStore(settings)
    embedding_service = EmbeddingService(settings)
    lance_store = LanceVectorStore(settings)
    embedding_pipeline = EmbeddingPipeline(
        settings=settings,
        sqlite_store=sqlite_store,
        embedding_service=embedding_service,
        lance_store=lance_store,
    )
    search_service = SearchService(
        settings=settings,
        sqlite_store=sqlite_store,
        embedding_service=embedding_service,
        lance_store=lance_store,
    )

    scheduler = BackgroundScheduler(timezone=settings.scheduler_timezone)
    scheduler.add_job(
        embedding_pipeline.run_once,
        trigger="interval",
        seconds=settings.embedding_interval_seconds,
        id="embedding-batch",
        max_instances=1,
        replace_existing=True,
    )

    app.state.settings = settings
    app.state.sqlite_store = sqlite_store
    app.state.embedding_service = embedding_service
    app.state.lance_store = lance_store
    app.state.embedding_pipeline = embedding_pipeline
    app.state.search_service = search_service
    app.state.scheduler = scheduler

    scheduler.start()
    logger.info("Memory Loom backend started with database dir: %s", settings.database_dir)

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        sqlite_store.close()
        logger.info("Memory Loom backend stopped")


app = FastAPI(
    title="Memory Loom Backend",
    version=APP_VERSION,
    description="Local ingest, embedding and hybrid retrieval service for Memory Loom.",
    lifespan=lifespan,
)


def get_settings() -> Settings:
    return app.state.settings


def get_sqlite_store() -> SQLiteStore:
    return app.state.sqlite_store


def get_embedding_pipeline() -> EmbeddingPipeline:
    return app.state.embedding_pipeline


def get_search_service() -> SearchService:
    return app.state.search_service


SettingsDependency = Annotated[Settings, Depends(get_settings)]
SQLiteStoreDependency = Annotated[SQLiteStore, Depends(get_sqlite_store)]
EmbeddingPipelineDependency = Annotated[EmbeddingPipeline, Depends(get_embedding_pipeline)]
SearchServiceDependency = Annotated[SearchService, Depends(get_search_service)]


@app.get("/health", response_model=HealthResponse)
def health(
    settings: SettingsDependency,
    sqlite_store: SQLiteStoreDependency,
) -> HealthResponse:
    try:
        counts = sqlite_store.embedding_job_counts()
        total_events = sqlite_store.count_events()
        model_reference = settings.model_reference
        lance_ready = app.state.lance_store.table_exists()
        model_loaded = app.state.embedding_service.is_loaded
    except Exception as exc:
        logger.exception("Health check failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="backend health check failed",
        ) from exc

    return HealthResponse(
        status="ok",
        version=settings.version,
        sqlite_path=str(settings.sqlite_path),
        lancedb_uri=str(settings.lancedb_uri),
        model_reference=str(model_reference),
        model_loaded=model_loaded,
        lancedb_ready=lance_ready,
        total_events=total_events,
        embedding_jobs=counts,
    )


@app.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
def ingest(
    payload: IngestRequest,
    sqlite_store: SQLiteStoreDependency,
) -> IngestResponse:
    try:
        record = sqlite_store.insert_event(payload)
    except Exception as exc:
        logger.exception("Failed to ingest payload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to ingest payload",
        ) from exc

    return IngestResponse(
        id=record.event_id,
        status="accepted",
        queued_for_embedding=True,
        content_hash=record.content_hash,
    )


@app.post("/search", response_model=SearchResponse)
def search(
    payload: SearchRequest,
    search_service: SearchServiceDependency,
) -> SearchResponse:
    try:
        return search_service.search(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Search failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="search failed",
        ) from exc


@app.post("/admin/embed-now", response_model=EmbedNowResponse)
def embed_now(
    pipeline: EmbeddingPipelineDependency,
    retry_failed: Annotated[
        bool,
        Query(description="Requeue failed embedding jobs before running the batch."),
    ] = False,
) -> EmbedNowResponse:
    try:
        if retry_failed:
            pipeline.requeue_failed_jobs()
        return pipeline.run_once()
    except RuntimeError as exc:
        logger.exception("Embedding batch failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Embedding batch failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="embedding batch failed",
        ) from exc


@app.post("/admin/rebuild-vector-index", response_model=EmbedNowResponse)
def rebuild_vector_index(
    pipeline: EmbeddingPipelineDependency,
) -> EmbedNowResponse:
    try:
        return pipeline.rebuild_vector_index()
    except RuntimeError as exc:
        logger.exception("Vector index rebuild failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Vector index rebuild failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="vector index rebuild failed",
        ) from exc


if __name__ == "__main__":
    import uvicorn

    runtime_settings = Settings.from_env()
    uvicorn.run(
        "main:app",
        host=runtime_settings.host,
        port=runtime_settings.port,
        reload=False,
    )
