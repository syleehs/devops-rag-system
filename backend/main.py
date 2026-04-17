"""
DevOps Decision RAG System - FastAPI Backend
Handles document ingestion, querying, and observability
"""

import os

# Must be set before any ONNX/tokenizer imports
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import asyncio
import json
import time
from datetime import datetime
from functools import partial
from typing import Optional
import logging

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import anthropic

from metrics import CloudWatchMetrics
from rag_pipeline import RAGPipeline
from config import Config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="DevOps Decision RAG System",
    description="RAG system for DevOps best practices and architectural decisions",
    version="1.0.0"
)

# Initialize clients and services
config = Config()
db_pool = ThreadedConnectionPool(
    minconn=1,
    maxconn=10,
    dbname=config.db_name,
    user=config.db_user,
    password=config.db_password,
    host=config.db_host,
    port=config.db_port,
    sslmode=config.db_sslmode,
    connect_timeout=5,
)
metrics = CloudWatchMetrics(config, pool=db_pool)
rag_pipeline = RAGPipeline(config, metrics, pool=db_pool)
anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)

# ==================== Pydantic Models ====================

class QueryRequest(BaseModel):
    """Request model for RAG queries"""
    query: str
    top_k: Optional[int] = 5
    include_metadata: Optional[bool] = False

class QueryResponse(BaseModel):
    """Response model for RAG queries"""
    query: str
    answer: str
    sources: list[dict]
    metadata: dict

class DocumentIngest(BaseModel):
    """Request model for document ingestion"""
    title: str
    content: str
    category: str  # e.g., "adr", "best_practice", "playbook"
    tags: Optional[list[str]] = []

class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: str
    database: str
    anthropic_api: str

# ==================== Endpoints ====================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint.
    Verifies database connectivity and API availability.
    """
    start_time = time.time()
    
    try:
        with rag_pipeline.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        db_status = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "unhealthy"

    try:
        # Quick check of Anthropic API connectivity
        anthropic_client.models.list()
        api_status = "healthy"
    except Exception as e:
        logger.error(f"Anthropic API health check failed: {e}")
        api_status = "unhealthy"

    # Record latency metric
    latency_ms = (time.time() - start_time) * 1000
    metrics.record_health_check_latency(latency_ms)

    if db_status == "unhealthy" or api_status == "unhealthy":
        raise HTTPException(status_code=503, detail="Service unavailable")

    return HealthResponse(
        status="healthy",
        timestamp=datetime.utcnow().isoformat(),
        database=db_status,
        anthropic_api=api_status
    )

@app.post("/query", response_model=QueryResponse)
async def query_knowledge_base(request: QueryRequest):
    """
    Query the DevOps knowledge base using RAG.
    
    Flow:
    1. Generate embeddings for the query
    2. Search PostgreSQL/pgvector for similar documents
    3. Build context from top-k results
    4. Query Claude API for answer
    5. Track metrics (latency, cost, tokens)
    """
    query_id = f"query_{int(time.time() * 1000)}"
    start_time = time.time()
    
    logger.info(f"[{query_id}] Processing query: {request.query[:100]}")
    
    try:
        # Step 1: Generate query embedding
        embedding_start = time.time()
        query_embedding = rag_pipeline.generate_embedding(request.query)
        embedding_latency_ms = (time.time() - embedding_start) * 1000
        metrics.record_embedding_latency(embedding_latency_ms)
        
        # Step 2: Retrieve similar documents from pgvector
        retrieval_start = time.time()
        similar_docs = rag_pipeline.retrieve_documents(query_embedding, top_k=request.top_k)
        retrieval_latency_ms = (time.time() - retrieval_start) * 1000
        metrics.record_retrieval_latency(retrieval_latency_ms)
        
        if not similar_docs:
            logger.warning(f"[{query_id}] No relevant documents found")
            metrics.record_query_metric(
                query_id=query_id,
                query=request.query,
                success=False,
                tokens_used=0,
                latency_ms=0
            )
            raise HTTPException(status_code=404, detail="No relevant documents found")
        
        # Step 3: Build context from retrieved documents
        context = "\n\n".join([
            f"[{doc['title']}]\n{doc['content']}"
            for doc in similar_docs
        ])
        
        # Step 4: Query Claude API with context
        claude_start = time.time()
        response = anthropic_client.messages.create(
            model="claude-opus-4-1-20250805",
            max_tokens=1024,
            system="""You are a DevOps expert assistant. Answer questions about 
DevOps best practices, architectural decisions, and incident response procedures. 
Use the provided context from the knowledge base. If the context doesn't contain 
relevant information, acknowledge this and provide general best practices.""",
            messages=[
                {
                    "role": "user",
                    "content": f"""Based on the following DevOps knowledge base, answer this question:

Question: {request.query}

Context:
{context}

Provide a clear, actionable answer."""
                }
            ]
        )
        
        claude_latency_ms = (time.time() - claude_start) * 1000
        metrics.record_claude_latency(claude_latency_ms)
        
        # Extract response
        answer = response.content[0].text
        tokens_used = response.usage.input_tokens + response.usage.output_tokens
        
        # Step 5: Record metrics
        total_latency_ms = (time.time() - start_time) * 1000
        metrics.record_query_metric(
            query_id=query_id,
            query=request.query,
            success=True,
            tokens_used=tokens_used,
            latency_ms=total_latency_ms
        )
        
        # Estimate cost (Claude Opus 4.1: input/output tokens pricing)
        # This is a rough estimate - verify actual pricing
        input_cost = response.usage.input_tokens * 0.015 / 1_000_000  # $15 per 1M input tokens
        output_cost = response.usage.output_tokens * 0.045 / 1_000_000  # $45 per 1M output tokens
        total_cost = input_cost + output_cost
        metrics.record_query_cost(total_cost)
        
        logger.info(f"[{query_id}] Query successful. Tokens: {tokens_used}, Latency: {total_latency_ms:.2f}ms, Cost: ${total_cost:.6f}")
        
        return QueryResponse(
            query=request.query,
            answer=answer,
            sources=similar_docs,
            metadata={
                "query_id": query_id,
                "tokens_used": tokens_used,
                "latency_ms": round(total_latency_ms, 2),
                "cost_usd": round(total_cost, 6),
                "embedding_latency_ms": round(embedding_latency_ms, 2),
                "retrieval_latency_ms": round(retrieval_latency_ms, 2),
                "claude_latency_ms": round(claude_latency_ms, 2),
                "num_sources": len(similar_docs)
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{query_id}] Query failed: {str(e)}")
        metrics.record_query_metric(
            query_id=query_id,
            query=request.query,
            success=False,
            tokens_used=0,
            latency_ms=(time.time() - start_time) * 1000
        )
        raise HTTPException(status_code=500, detail=f"Query processing failed: {str(e)}")

@app.post("/ingest")
async def ingest_document(document: DocumentIngest):
    """
    Ingest a new document into the knowledge base.

    Documents are chunked, embedded, and stored in PostgreSQL with pgvector.
    """
    ingest_id = f"ingest_{int(time.time() * 1000)}"
    start_time = time.time()

    logger.info(f"[{ingest_id}] Ingesting document: {document.title}")

    try:
        # Chunk the document
        chunks = rag_pipeline.chunk_document(document.content, chunk_size=1000, overlap=200)
        logger.info(f"[{ingest_id}] Created {len(chunks)} chunks")

        # Run embedding + DB writes in a thread to avoid blocking the event loop,
        # while ensuring ONNX runs in a single dedicated thread (not the default threadpool)
        embeddings = await asyncio.to_thread(rag_pipeline.generate_embeddings_batch, chunks)

        # Store all chunks in a single connection/transaction
        batch = [
            {
                'title': f"{document.title} (Part {i+1})",
                'content': chunk,
                'embedding': embedding,
                'category': document.category,
                'tags': document.tags or [],
            }
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ]
        await asyncio.to_thread(rag_pipeline.store_documents_batch, batch)
        stored_chunks = len(batch)
        
        latency_ms = (time.time() - start_time) * 1000
        metrics.record_ingest_metric(ingest_id, document.title, stored_chunks, latency_ms)
        
        logger.info(f"[{ingest_id}] Ingest complete. Stored {stored_chunks} chunks in {latency_ms:.2f}ms")
        
        return {
            "status": "success",
            "ingest_id": ingest_id,
            "title": document.title,
            "chunks_created": len(chunks),
            "chunks_stored": stored_chunks,
            "latency_ms": round(latency_ms, 2)
        }
        
    except Exception as e:
        logger.error(f"[{ingest_id}] Ingestion failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Document ingestion failed: {str(e)}")

@app.get("/documents")
async def list_documents():
    """List all documents in the knowledge base."""
    try:
        with rag_pipeline.get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT DISTINCT title, category, COUNT(*) as chunks,
                           MIN(created_at) as created_at
                    FROM documents
                    GROUP BY title, category
                    ORDER BY created_at DESC
                """)
                documents = cur.fetchall()

        return {"documents": documents}

    except Exception as e:
        logger.error(f"Failed to list documents: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve documents")

@app.get("/metrics")
async def get_metrics():
    """
    Prometheus-compatible metrics endpoint.
    Exposes metrics for monitoring and cost tracking.
    """
    return metrics.get_prometheus_metrics()

@app.get("/metrics/summary")
async def get_metrics_summary():
    """Get a summary of key metrics over the last hour."""
    try:
        with rag_pipeline.get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        COUNT(*) as total_queries,
                        ROUND(AVG(latency_ms)::numeric, 2) as avg_latency_ms,
                        ROUND(MAX(latency_ms)::numeric, 2) as max_latency_ms,
                        ROUND(SUM(tokens_used)::numeric) as total_tokens,
                        ROUND(SUM(cost_usd)::numeric, 4) as total_cost_usd,
                        ROUND((SUM(cost_usd) / COUNT(*))::numeric, 6) as avg_cost_per_query
                    FROM query_metrics
                    WHERE timestamp > NOW() - INTERVAL '1 hour'
                """)
                summary = cur.fetchone()

        return summary or {
            "total_queries": 0,
            "avg_latency_ms": 0,
            "max_latency_ms": 0,
            "total_tokens": 0,
            "total_cost_usd": 0,
            "avg_cost_per_query": 0
        }
        
    except Exception as e:
        logger.error(f"Failed to get metrics summary: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve metrics")

@app.get("/")
async def root():
    """Root endpoint with API documentation."""
    return {
        "name": "DevOps Decision RAG System",
        "version": "1.0.0",
        "documentation": "/docs",
        "endpoints": {
            "health": "GET /health",
            "query": "POST /query",
            "ingest": "POST /ingest",
            "documents": "GET /documents",
            "metrics": "GET /metrics",
            "metrics_summary": "GET /metrics/summary"
        }
    }

# ==================== Error Handlers ====================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler with logging."""
    logger.error(f"HTTP Exception: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Catch-all exception handler."""
    logger.error(f"Unhandled exception: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
