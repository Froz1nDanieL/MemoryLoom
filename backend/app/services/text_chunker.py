from __future__ import annotations


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []

    if len(normalized) <= chunk_size:
        return [normalized]

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        chunks.append(normalized[start:end])
        if end == len(normalized):
            break
        start = max(end - overlap, start + 1)

    return chunks
