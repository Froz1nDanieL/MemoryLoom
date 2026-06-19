from __future__ import annotations

import logging
from typing import Iterable

from app.config import Settings


logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = None
        self._dimension: int | None = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def dimension(self) -> int | None:
        return self._dimension

    def encode_documents(self, texts: Iterable[str]) -> list[list[float]]:
        return self._encode(list(texts), is_query=False)

    def encode_query(self, query: str) -> list[float]:
        text = f"{self._settings.query_instruction}{query}"
        vectors = self._encode([text], is_query=True)
        return vectors[0] if vectors else []

    def _encode(self, texts: list[str], is_query: bool) -> list[list[float]]:
        if not texts:
            return []

        model = self._load_model()
        embeddings = model.encode(
            texts,
            batch_size=self._settings.embedding_batch_size,
            normalize_embeddings=self._settings.normalize_embeddings,
            show_progress_bar=False,
        )

        vectors = embeddings.tolist()
        if vectors and isinstance(vectors[0], float):
            vectors = [vectors]

        logger.debug("Encoded %s %s embedding(s)", len(vectors), "query" if is_query else "document")
        return [[float(value) for value in vector] for vector in vectors]

    def _load_model(self):
        if self._model is not None:
            return self._model

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Failed to import sentence-transformers. Install compatible backend "
                "dependencies with `python -m pip install -r requirements.txt`. "
                f"Original error: {exc}"
            ) from exc

        model_reference = self._settings.model_reference
        logger.info("Loading embedding model: %s", model_reference)
        try:
            self._model = SentenceTransformer(str(model_reference))
            self._dimension = int(self._model.get_sentence_embedding_dimension())
        except Exception as exc:
            raise RuntimeError(
                "Failed to load embedding model. Put BAAI/bge-small-zh-v1.5 under "
                f"{self._settings.local_model_path} or allow sentence-transformers to download "
                f"{self._settings.model_name}. Original error: {exc}"
            ) from exc

        logger.info("Embedding model loaded with dimension: %s", self._dimension)
        return self._model
