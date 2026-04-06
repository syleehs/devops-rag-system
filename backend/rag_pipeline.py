"""
RAG Pipeline Module
Handles document processing, embedding generation, and semantic search
"""

import logging
from typing import List, Optional
import json

import psycopg2
from psycopg2.extras import RealDictCursor
import anthropic

logger = logging.getLogger(__name__)

class RAGPipeline:
    """
    RAG (Retrieval-Augmented Generation) pipeline for DevOps knowledge base.
    
    Responsibilities:
    - Document chunking and preprocessing
    - Embedding generation via Claude API
    - Semantic search via pgvector in PostgreSQL
    - Document storage and retrieval
    """
    
    def __init__(self, config, metrics):
        """
        Initialize RAG pipeline.
        
        Args:
            config: Configuration object with database and API credentials
            metrics: CloudWatch metrics client for tracking operations
        """
        self.config = config
        self.metrics = metrics
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        
        # Initialize database connection pool (simplified)
        self.db_config = {
            'dbname': config.db_name,
            'user': config.db_user,
            'password': config.db_password,
            'host': config.db_host,
            'port': config.db_port
        }
        
        # Initialize database schema
        self._init_database()
    
    def _init_database(self):
        """Initialize PostgreSQL schema with pgvector extension."""
        try:
            conn = psycopg2.connect(**self.db_config)
            conn.autocommit = True
            
            with conn.cursor() as cur:
                # Enable pgvector extension
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                
                # Create documents table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS documents (
                        id SERIAL PRIMARY KEY,
                        title VARCHAR(500) NOT NULL,
                        content TEXT NOT NULL,
                        embedding vector(1536),
                        category VARCHAR(100),
                        tags TEXT[],
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create index on embedding for faster searches
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_documents_embedding 
                    ON documents USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                """)
                
                # Create query metrics table
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
                
                # Create index on timestamps for metrics queries
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_query_metrics_timestamp 
                    ON query_metrics (timestamp DESC)
                """)
                
                # Create ingest metrics table
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
            
            conn.close()
            logger.info("Database schema initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise
    
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
            start = end - overlap
        
        logger.info(f"Document chunked into {len(chunks)} pieces")
        return chunks
    
    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for text using Claude API.
        
        Args:
            text: Text to embed
        
        Returns:
            Embedding vector (1536 dimensions)
        """
        try:
            response = self.client.messages.embed(
                model="claude-3-5-sonnet-20241022",
                input=[text]
            )
            
            # Extract embedding from response
            embedding = response.content[0].embedding
            logger.debug(f"Generated embedding with {len(embedding)} dimensions")
            return embedding
            
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            raise
    
    def store_document(
        self,
        title: str,
        content: str,
        embedding: List[float],
        category: str,
        tags: Optional[List[str]] = None
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
        try:
            conn = psycopg2.connect(**self.db_config)
            
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO documents (title, content, embedding, category, tags)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    title,
                    content,
                    embedding,
                    category,
                    tags or []
                ))
                
                doc_id = cur.fetchone()[0]
            
            conn.commit()
            conn.close()
            
            logger.info(f"Stored document {title} (ID: {doc_id})")
            return doc_id
            
        except Exception as e:
            logger.error(f"Failed to store document: {e}")
            raise
    
    def retrieve_documents(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        similarity_threshold: float = 0.7
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
        try:
            conn = psycopg2.connect(**self.db_config)
            
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Use pgvector cosine similarity for semantic search
                cur.execute("""
                    SELECT 
                        id,
                        title,
                        content,
                        category,
                        tags,
                        1 - (embedding <=> %s) as similarity
                    FROM documents
                    WHERE (1 - (embedding <=> %s)) > %s
                    ORDER BY similarity DESC
                    LIMIT %s
                """, (
                    query_embedding,
                    query_embedding,
                    similarity_threshold,
                    top_k
                ))
                
                results = cur.fetchall()
            
            conn.close()
            
            logger.info(f"Retrieved {len(results)} documents with threshold {similarity_threshold}")
            return results
            
        except Exception as e:
            logger.error(f"Failed to retrieve documents: {e}")
            raise
    
    def delete_document(self, doc_id: int) -> bool:
        """
        Delete a document from the knowledge base.
        
        Args:
            doc_id: Document ID to delete
        
        Returns:
            True if successful
        """
        try:
            conn = psycopg2.connect(**self.db_config)
            
            with conn.cursor() as cur:
                cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Deleted document {doc_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete document: {e}")
            raise
    
    def update_document(
        self,
        doc_id: int,
        title: Optional[str] = None,
        content: Optional[str] = None,
        embedding: Optional[List[float]] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None
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
        try:
            conn = psycopg2.connect(**self.db_config)
            
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
                
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE documents SET {', '.join(updates)} WHERE id = %s",
                        params
                    )
            
            conn.commit()
            conn.close()
            
            logger.info(f"Updated document {doc_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update document: {e}")
            raise
