"""
Retrieval-only CLI — queries the RAG knowledge base without calling the LLM.
Usage:
    python scripts/retrieve_only.py "how do I restart a crashed ECS task?"
    python scripts/retrieve_only.py "node health monitoring" --top-k 3 --threshold 0.5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import Config
from backend.rag_pipeline import RAGPipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Retrieval-only RAG query (no LLM).")
    parser.add_argument("query", help="Natural-language query.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.3,
                        help="Cosine similarity threshold (default 0.3).")
    parser.add_argument("--full", action="store_true",
                        help="Print full chunk content (default: first 300 chars).")
    args = parser.parse_args()

    config = Config()
    rag = RAGPipeline(config, metrics=None)

    embedding = rag.generate_embedding(args.query)
    results = rag.retrieve_documents(
        query_embedding=embedding,
        top_k=args.top_k,
        similarity_threshold=args.threshold,
    )

    if not results:
        print(f"No results above similarity threshold {args.threshold}.")
        return 1

    print(f"\nQuery: {args.query}")
    print(f"Retrieved {len(results)} chunk(s):\n")
    for i, r in enumerate(results, 1):
        score = r.get("similarity") or r.get("score") or "?"
        source = r.get("source") or r.get("metadata", {}).get("source") or r.get("title") or "unknown"
        content = r.get("content") or r.get("chunk") or ""
        snippet = content if args.full else content[:300].replace("\n", " ")
        print(f"--- [{i}] score={score}  source={source}")
        print(snippet)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
