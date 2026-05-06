#!/usr/bin/env python3
"""
Ingest knowledge base documents into the RAG system.

Usage:
    python scripts/ingest_knowledge_base.py --endpoint http://localhost:8000
    python scripts/ingest_knowledge_base.py --endpoint http://devops-rag-alb-123.us-east-1.elb.amazonaws.com
"""

import argparse
import glob
import logging
import os

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def ingest_documents(endpoint: str, knowledge_base_dir: str = "knowledge_base"):
    """
    Ingest all markdown documents from the knowledge base directory.

    Args:
        endpoint: API endpoint (e.g., http://localhost:8000)
        knowledge_base_dir: Directory containing .md files
    """
    if not endpoint.startswith("http"):
        endpoint = f"http://{endpoint}"

    # Ensure trailing slash
    endpoint = endpoint.rstrip("/")

    ingest_url = f"{endpoint}/ingest"

    logger.info(f"Ingesting documents from {knowledge_base_dir}")
    logger.info(f"API endpoint: {ingest_url}")

    # Find all markdown files
    md_files = glob.glob(os.path.join(knowledge_base_dir, "*.md"))

    if not md_files:
        logger.warning(f"No markdown files found in {knowledge_base_dir}")
        return

    logger.info(f"Found {len(md_files)} documents to ingest")

    stats = {"success": 0, "failed": 0, "total_chunks": 0}

    for md_file in sorted(md_files):
        filename = os.path.basename(md_file)

        # Determine category from filename
        if filename.startswith("adr_"):
            category = "adr"
        elif filename.startswith("best_practices_"):
            category = "best_practice"
        elif filename.startswith("playbooks_"):
            category = "playbook"
        else:
            category = "general"

        # Read document
        with open(md_file, "r") as f:
            content = f.read()

        # Extract title from first H1 if available
        title = filename.replace(".md", "").replace("_", " ").title()
        if content.startswith("# "):
            title = content.split("\n")[0].replace("# ", "")

        # Build tags
        tags = [category]
        if "kubernetes" in content.lower():
            tags.append("kubernetes")
        if "terraform" in content.lower():
            tags.append("terraform")
        if "cost" in content.lower():
            tags.append("cost")
        if "incident" in content.lower():
            tags.append("incident")
        if "security" in content.lower():
            tags.append("security")

        # Prepare request
        payload = {"title": title, "content": content, "category": category, "tags": tags}

        try:
            logger.info(f"Ingesting: {title}")
            response = requests.post(ingest_url, json=payload, timeout=30)

            if response.status_code == 200:
                result = response.json()
                chunks = result.get("chunks_stored", 0)
                stats["success"] += 1
                stats["total_chunks"] += chunks
                logger.info(f"✓ Success: {chunks} chunks stored")
            else:
                stats["failed"] += 1
                logger.error(f"✗ Failed: HTTP {response.status_code}")
                logger.error(f"  Response: {response.text}")

        except requests.exceptions.ConnectionError:
            stats["failed"] += 1
            logger.error(f"✗ Failed: Could not connect to {ingest_url}")
        except requests.exceptions.Timeout:
            stats["failed"] += 1
            logger.error("✗ Failed: Request timeout")
        except Exception as e:
            stats["failed"] += 1
            logger.error(f"✗ Failed: {str(e)}")

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Ingestion Summary")
    logger.info("=" * 60)
    logger.info(f"Total documents processed: {len(md_files)}")
    logger.info(f"Successful: {stats['success']}")
    logger.info(f"Failed: {stats['failed']}")
    logger.info(f"Total chunks stored: {stats['total_chunks']}")
    logger.info("=" * 60)

    return stats


def main():
    parser = argparse.ArgumentParser(description="Ingest knowledge base documents into DevOps RAG system")
    parser.add_argument(
        "--endpoint", default="http://localhost:8000", help="API endpoint (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--knowledge-base", default="knowledge_base", help="Knowledge base directory (default: knowledge_base)"
    )

    args = parser.parse_args()

    # Verify directory exists
    if not os.path.isdir(args.knowledge_base):
        logger.error(f"Knowledge base directory not found: {args.knowledge_base}")
        return 1

    # Ingest documents
    stats = ingest_documents(args.endpoint, args.knowledge_base)

    if stats["failed"] == 0:
        logger.info("\n✓ All documents ingested successfully!")
        return 0
    else:
        logger.warning(f"\n⚠ {stats['failed']} documents failed to ingest")
        return 1


if __name__ == "__main__":
    exit(main())
