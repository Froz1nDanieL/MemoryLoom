from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parents[1]
APP_VERSION = "0.2.0"


class Settings(BaseModel):
    version: str = APP_VERSION
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "INFO"

    database_dir: Path = BASE_DIR / "database"
    sqlite_path: Path = BASE_DIR / "database" / "memoryloom.sqlite3"
    lancedb_uri: Path = BASE_DIR / "database" / "lancedb"
    lancedb_table: str = "memory_chunks"

    model_name: str = "BAAI/bge-small-zh-v1.5"
    local_model_path: Path = BASE_DIR / "models" / "bge-small-zh-v1.5"
    query_instruction: str = "为这个句子生成表示以用于检索相关文章："
    normalize_embeddings: bool = True

    chunk_size: int = Field(default=700, ge=100, le=4000)
    chunk_overlap: int = Field(default=100, ge=0, le=1000)
    embedding_batch_size: int = Field(default=16, ge=1, le=256)
    embedding_interval_seconds: int = Field(default=30, ge=5, le=3600)
    max_embedding_attempts: int = Field(default=3, ge=1, le=20)
    vector_search_multiplier: int = Field(default=3, ge=1, le=10)
    scheduler_timezone: str = "Asia/Shanghai"

    @classmethod
    def from_env(cls) -> "Settings":
        database_dir = Path(os.getenv("MEMORYLOOM_DATABASE_DIR", str(BASE_DIR / "database")))
        return cls(
            host=os.getenv("MEMORYLOOM_BACKEND_HOST", "127.0.0.1"),
            port=int(os.getenv("MEMORYLOOM_BACKEND_PORT", "8765")),
            log_level=os.getenv("MEMORYLOOM_LOG_LEVEL", "INFO"),
            database_dir=database_dir,
            sqlite_path=Path(
                os.getenv(
                    "MEMORYLOOM_SQLITE_PATH",
                    str(database_dir / "memoryloom.sqlite3"),
                )
            ),
            lancedb_uri=Path(
                os.getenv(
                    "MEMORYLOOM_LANCEDB_URI",
                    str(database_dir / "lancedb"),
                )
            ),
            lancedb_table=os.getenv("MEMORYLOOM_LANCEDB_TABLE", "memory_chunks"),
            model_name=os.getenv("MEMORYLOOM_MODEL_NAME", "BAAI/bge-small-zh-v1.5"),
            local_model_path=Path(
                os.getenv(
                    "MEMORYLOOM_LOCAL_MODEL_PATH",
                    str(BASE_DIR / "models" / "bge-small-zh-v1.5"),
                )
            ),
            query_instruction=os.getenv(
                "MEMORYLOOM_QUERY_INSTRUCTION",
                "为这个句子生成表示以用于检索相关文章：",
            ),
            chunk_size=int(os.getenv("MEMORYLOOM_CHUNK_SIZE", "700")),
            chunk_overlap=int(os.getenv("MEMORYLOOM_CHUNK_OVERLAP", "100")),
            embedding_batch_size=int(os.getenv("MEMORYLOOM_EMBEDDING_BATCH_SIZE", "16")),
            embedding_interval_seconds=int(os.getenv("MEMORYLOOM_EMBEDDING_INTERVAL_SECONDS", "30")),
            max_embedding_attempts=int(os.getenv("MEMORYLOOM_MAX_EMBEDDING_ATTEMPTS", "3")),
        )

    @property
    def model_reference(self) -> str | Path:
        if self.local_model_path.exists():
            return self.local_model_path
        return self.model_name

    def configure_logging(self) -> None:
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper(), logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        )
