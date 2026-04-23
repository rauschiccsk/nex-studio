"""RAG indexer CLI — chunk + embed + upsert markdown into Qdrant.

Usage:
    poetry run python scripts/rag_index.py /home/icc/knowledge/icc/DECISIONS.md
    poetry run python scripts/rag_index.py /home/icc/knowledge/icc/*.md --tenant icc
    poetry run python scripts/rag_index.py --delete /home/icc/knowledge/icc/OLD.md

Ported from NEX Command `backend/rag/indexer.py` (see §5.3 in CLAUDE.md).
Same chunking strategy, same payload schema — compatible with existing index.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
)

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:9130")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:9132")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
KB_ROOT = Path(os.environ.get("KB_ROOT", "/home/icc/knowledge")).resolve()
REQUEST_TIMEOUT = 30
CHUNK_MAX_CHARS = 1000
CHUNK_OVERLAP = 200

logger = logging.getLogger("rag_index")


def embed(text: str) -> list[float]:
    response = httpx.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": text},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["embedding"]


def chunk_markdown(content: str, max_chars: int = CHUNK_MAX_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split markdown into chunks, preferring heading boundaries. Port from NEX Command."""
    if not content or not content.strip():
        return []

    sections = re.split(r"(?=^#{1,4}\s)", content, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]

    chunks: list[str] = []
    current = ""

    for section in sections:
        if len(section) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            para_buf = ""
            for para in section.split("\n\n"):
                para = para.strip()
                if not para:
                    continue
                if len(para_buf) + len(para) + 2 > max_chars:
                    if para_buf:
                        chunks.append(para_buf)
                    para_buf = para
                else:
                    para_buf = f"{para_buf}\n\n{para}" if para_buf else para
            if para_buf:
                current = para_buf
            continue

        if len(current) + len(section) + 2 > max_chars:
            if current:
                chunks.append(current)
            current = section
        else:
            current = f"{current}\n\n{section}" if current else section

    if current:
        chunks.append(current)

    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-overlap:]
            cut = prev_tail.find("\n")
            if cut == -1:
                cut = prev_tail.find(" ")
            if cut != -1:
                prev_tail = prev_tail[cut + 1 :]
            overlapped.append(f"{prev_tail}\n\n{chunks[i]}")
        chunks = overlapped

    return chunks


def source_file_from_path(file_path: Path) -> str:
    """Convert absolute path to KB-relative source_file (same scheme as NEX Command)."""
    abs_path = file_path.resolve()
    try:
        return str(abs_path.relative_to(KB_ROOT)).replace("\\", "/")
    except ValueError:
        return str(abs_path).replace("\\", "/")


def extract_category(source_file: str) -> str:
    parts = source_file.strip("/").split("/")
    return parts[0] if len(parts) > 1 else "general"


def delete_document(client: QdrantClient, source_file: str, tenant: str) -> int:
    doc_filter = Filter(must=[FieldCondition(key="source_file", match=MatchValue(value=source_file))])
    count = client.count(collection_name=tenant, count_filter=doc_filter, exact=True).count
    if count == 0:
        return 0
    client.delete(collection_name=tenant, points_selector=FilterSelector(filter=doc_filter))
    return count


def index_document(client: QdrantClient, file_path: Path, tenant: str) -> dict:
    content = file_path.read_text(encoding="utf-8")
    source_file = source_file_from_path(file_path)
    filename = file_path.name
    category = extract_category(source_file)

    deleted = delete_document(client, source_file, tenant)

    chunks = chunk_markdown(content)
    if not chunks:
        return {"source_file": source_file, "chunks": 0, "deleted": deleted, "tenant": tenant}

    now_iso = datetime.now(timezone.utc).isoformat()
    points: list[PointStruct] = []

    for i, chunk_text in enumerate(chunks):
        vector = embed(chunk_text)
        payload = {
            "source_file": source_file,
            "content": chunk_text,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "ingested_at": now_iso,
            "filename": filename,
            "category": category,
            "tenant": tenant,
        }
        points.append(PointStruct(id=str(uuid.uuid4()), vector=vector, payload=payload))

    client.upsert(collection_name=tenant, points=points)
    return {"source_file": source_file, "chunks": len(chunks), "deleted": deleted, "tenant": tenant}


def main() -> int:
    parser = argparse.ArgumentParser(description="Index markdown files into ICC RAG (Qdrant).")
    parser.add_argument("paths", nargs="+", help="File paths to index (or delete with --delete)")
    parser.add_argument("--tenant", default="icc", help="Qdrant collection (default: icc)")
    parser.add_argument("--delete", action="store_true", help="Delete documents instead of indexing")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    client = QdrantClient(url=QDRANT_URL, timeout=REQUEST_TIMEOUT)

    total_chunks = 0
    total_deleted = 0

    for raw in args.paths:
        file_path = Path(raw)
        if not file_path.exists():
            print(f"SKIP (not found): {file_path}", file=sys.stderr)
            continue
        if file_path.is_dir():
            print(f"SKIP (directory, expand globs in shell): {file_path}", file=sys.stderr)
            continue

        try:
            if args.delete:
                source_file = source_file_from_path(file_path)
                count = delete_document(client, source_file, args.tenant)
                print(f"DELETED {count} chunks  source={source_file}  tenant={args.tenant}")
                total_deleted += count
            else:
                result = index_document(client, file_path, args.tenant)
                print(
                    f"INDEXED {result['chunks']} chunks  "
                    f"(replaced {result['deleted']} old)  "
                    f"source={result['source_file']}  tenant={args.tenant}"
                )
                total_chunks += result["chunks"]
                total_deleted += result["deleted"]
        except httpx.HTTPError as exc:
            print(f"HTTP error for {file_path}: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"Error for {file_path}: {exc}", file=sys.stderr)
            return 1

    if args.delete:
        print(f"\nTotal deleted: {total_deleted} chunks")
    else:
        print(f"\nTotal indexed: {total_chunks} chunks (replaced {total_deleted} old)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
