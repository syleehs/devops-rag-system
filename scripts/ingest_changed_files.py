"""
Ingest new or changed knowledge base files directly via RAGPipeline.

Idempotent: skips files whose stem (filename without extension) is already
present in the documents table. Designed to run from CI after a deploy.

Required env vars:
- DATABASE_URL: Neon connection string
- GROQ_API_KEY: not actually used here, but Config() requires it set

Exit codes:
- 0: success (including "nothing to do")
- 1: ingest failed
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2

# Make backend/ importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from config import Config  # noqa: E402
from rag_pipeline import RAGPipeline  # noqa: E402


def ingested_stems(database_url: str) -> set[str]:
    """Return the set of distinct filename stems already in the documents table."""
    with psycopg2.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT regexp_replace(title, ' \\(Part [0-9]+\\)$', '') " "FROM documents")
        return {row[0] for row in cur.fetchall()}


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL is required", file=sys.stderr)
        return 1

    kb_dir = Path("knowledge_base")
    if not kb_dir.exists():
        print(f"ERROR: {kb_dir} does not exist", file=sys.stderr)
        return 1

    existing = ingested_stems(database_url)
    all_files = sorted(kb_dir.glob("*.md"))
    new_files = [f for f in all_files if f.stem not in existing]

    print(f"Existing stems in DB: {len(existing)}")
    print(f"Files in {kb_dir}: {len(all_files)}")
    print(f"New files to ingest: {len(new_files)}")

    if not new_files:
        print("Nothing to do.")
        return 0

    rag = RAGPipeline(Config(), metrics=None)
    total_chunks = 0
    for f in new_files:
        content = f.read_text()
        category = "adr" if f.name.startswith("adr_") else "general"
        chunks = rag.chunk_document(content)
        embeddings = rag.generate_embeddings_batch(chunks)
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings, strict=False), 1):
            title = f"{f.stem} (Part {i})" if len(chunks) > 1 else f.stem
            rag.store_document(
                title=title,
                content=chunk,
                embedding=emb,
                category=category,
                tags=[category],
            )
        print(f"  + {f.name}: {len(chunks)} chunks")
        total_chunks += len(chunks)

    print(f"Done. {total_chunks} new chunks ingested.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
