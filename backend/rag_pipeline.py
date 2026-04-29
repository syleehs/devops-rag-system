"""
RAG Pipeline Module
Handles document processing, embedding generation, and semantic search
"""

import logging
import os
from typing import List, Optional

# Prevent ONNX Runtime thread contention with uvicorn
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from contextlib import contextmanager

import psycopg2
from fastembed import TextEmbedding
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)


class RAGPipeline:
    """
    RAG (Retrieval-Augmented Generation) pipeline for DevOps knowledge base.

    Responsibilities:
    - Document chunking and preprocessing
    - Embedding generation via local fastembed (BAAI/bge-small-en-v1.5)
    - Semantic search via pgvector in PostgreSQL
    - Document storage and retrieval
    """

    def __init__(self, config, metrics, pool: ThreadedConnectionPool = None):
        """
        Initialize RAG pipeline.

        Args:
            config: Configuration object with database and API credentials
            metrics: CloudWatch metrics client for tracking operations
            pool: Shared database connection pool (creates own if not provided)
        """
        self.config = config
        self.metrics = metrics
        self.embedding_model = TextEmbedding("BAAI/bge-small-en-v1.5")

        self._db_config = {
            "dbname": config.db_name,
            "user": config.db_user,
            "password": config.db_password,
            "host": config.db_host,
            "port": config.db_port,
            "sslmode": config.db_sslmode,
            "connect_timeout": 5,
        }
        self.pool = pool or ThreadedConnectionPool(minconn=1, maxconn=10, **self._db_config)

        # Initialize database schema (dedicated connection, not from pool)
        self._init_database()

    @contextmanager
    def get_conn(self):
        """Get a connection from the pool. Always returns it on exit."""
        conn = self.pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.pool.putconn(conn)

    def _init_database(self):
        """Initialize PostgreSQL schema with pgvector extension.

        Uses a dedicated connection (not from the pool) with autocommit=True
        so DDL statements execute immediately without fighting the pool's
        commit/rollback context manager.
        """
        conn = psycopg2.connect(**self._db_config)
        try:
            conn.autocommit = True

            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS documents (
                        id SERIAL PRIMARY KEY,
                        title VARCHAR(500) NOT NULL,
                        content TEXT NOT NULL,
                        embedding vector(384),
                        category VARCHAR(100),
                        tags TEXT[],
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                cur.execute("DROP INDEX IF EXISTS idx_documents_embedding")
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_documents_embedding
                    ON documents USING hnsw (embedding vector_cosine_ops)
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS query_metrics (
                        id SERIAL PRIMARY KEY,
                        query_id VARCHAR(100) NOT NULL UNIQUE,
                        query TEXT NOT NULL,
                        success BOOLEAN NOT NULL,
                        tokens_used INTEGER,
                        latency_ms FLOAT,
                        cost_usd FLOAT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_query_metrics_timestamp
                    ON query_metrics (timestamp DESC)
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ingest_metrics (
                        id SERIAL PRIMARY KEY,
                        ingest_id VARCHAR(100) NOT NULL UNIQUE,
                        title VARCHAR(500),
                        chunks_stored INTEGER,
                        latency_ms FLOAT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

            logger.info("Database schema initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
        finally:
            conn.close()

    def chunk_document(self, content: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
        """
        Split document into overlapping chunks for embedding.

        Args:
            content: Full document content
            chunk_size: Target characters per chunk
            overlap: Characters to overlap between chunks

        Returns:
            List of document chunks
        """
        chunks = []
        start = 0

        while start < len(content):
            end = min(start + chunk_size, len(content))
            chunk = content[start:end]
            chunks.append(chunk)
            if end >= len(content):
                break
            start = max(end - overlap, start + 1)

        logger.info(f"Document chunked into {len(chunks)} pieces")
        return chunks

    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for text using local ONNX model.

        Args:
            text: Text to embed

        Returns:
            Embedding vector (384 dimensions)
        """
        embedding = list(self.embedding_model.embed([text]))[0].tolist()
        logger.debug(f"Generated embedding with {len(embedding)} dimensions")
        return embedding

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in a single batch.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        embeddings = [e.tolist() for e in self.embedding_model.embed(texts)]
        logger.debug(f"Generated {len(embeddings)} embeddings in batch")
        return embeddings

    def store_document(
        self, title: str, content: str, embedding: List[float], category: str, tags: Optional[List[str]] = None
    ) -> int:
        """
        Store document and embedding in PostgreSQL.

        Args:
            title: Document title
            content: Document content
            embedding: Embedding vector
            category: Document category (adr, best_practice, etc.)
            tags: Optional list of tags

        Returns:
            Document ID
        """
        with self.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO documents (title, content, embedding, category, tags)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """,
                    (title, content, embedding, category, tags or []),
                )

                doc_id = cur.fetchone()[0]

        logger.info(f"Stored document {title} (ID: {doc_id})")
        return doc_id

    def store_documents_batch(
        self,
        documents: List[dict],
    ) -> List[int]:
        """
        Store multiple documents in a single connection and transaction.

        Args:
            documents: List of dicts with keys: title, content, embedding, category, tags

        Returns:
            List of document IDs
        """
        with self.get_conn() as conn:
            doc_ids = []
            with conn.cursor() as cur:
                for doc in documents:
                    cur.execute(
                        """
                        INSERT INTO documents (title, content, embedding, category, tags)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                    """,
                        (
                            doc["title"],
                            doc["content"],
                            doc["embedding"],
                            doc["category"],
                            doc.get("tags") or [],
                        ),
                    )
                    doc_ids.append(cur.fetchone()[0])

        logger.info(f"Stored {len(doc_ids)} documents in batch")
        return doc_ids

    def retrieve_documents(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        similarity_threshold: float = 0.7,
    ) -> List[dict]:
        """
        Retrieve semantically similar documents using pgvector.

        Uses cosine similarity to find relevant documents.

        Args:
            query_embedding: Embedding vector for the query
            top_k: Number of top results to return
            similarity_threshold: Minimum similarity score (0-1)

        Returns:
            List of relevant documents with similarity scores
        """
        with self.get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        title,
                        content,
                        category,
                        tags,
                        1 - (embedding <=> %s::vector) as similarity
                    FROM documents
                    WHERE (1 - (embedding <=> %s::vector)) > %s
                    ORDER BY similarity DESC
                    LIMIT %s
                """,
                    (query_embedding, query_embedding, similarity_threshold, top_k),
                )

                results = cur.fetchall()

        logger.info(f"Retrieved {len(results)} documents with threshold {similarity_threshold}")
        return results

    def delete_document(self, doc_id: int) -> bool:
        """
        Delete a document from the knowledge base.

        Args:
            doc_id: Document ID to delete

        Returns:
            True if successful
        """
        with self.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))

        logger.info(f"Deleted document {doc_id}")
        return True

    def update_document(
        self,
        doc_id: int,
        title: Optional[str] = None,
        content: Optional[str] = None,
        embedding: Optional[List[float]] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """
        Update an existing document.

        Args:
            doc_id: Document ID to update
            title: New title (optional)
            content: New content (optional)
            embedding: New embedding (optional)
            category: New category (optional)
            tags: New tags (optional)

        Returns:
            True if successful
        """
        updates = []
        params = []

        if title is not None:
            updates.append("title = %s")
            params.append(title)
        if content is not None:
            updates.append("content = %s")
            params.append(content)
        if embedding is not None:
            updates.append("embedding = %s")
            params.append(embedding)
        if category is not None:
            updates.append("category = %s")
            params.append(category)
        if tags is not None:
            updates.append("tags = %s")
            params.append(tags)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(doc_id)

            with self.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE documents SET {', '.join(updates)} WHERE id = %s",
                        params,
                    )

        logger.info(f"Updated document {doc_id}")
        return True
