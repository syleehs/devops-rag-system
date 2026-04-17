"""Unit tests for RAG pipeline document chunking."""

from rag_pipeline import RAGPipeline


class FakeConfig:
    db_name = "test"
    db_user = "test"
    db_password = "test"
    db_host = "localhost"
    db_port = 5432


class FakeMetrics:
    pass


def test_chunk_document_single_chunk():
    """Short content produces a single chunk."""
    pipeline = RAGPipeline.__new__(RAGPipeline)
    pipeline.config = FakeConfig()
    chunks = pipeline.chunk_document("Hello world", chunk_size=1000, overlap=200)
    assert len(chunks) == 1
    assert chunks[0] == "Hello world"


def test_chunk_document_multiple_chunks():
    """Long content is split into overlapping chunks."""
    pipeline = RAGPipeline.__new__(RAGPipeline)
    pipeline.config = FakeConfig()
    content = "A" * 2500
    chunks = pipeline.chunk_document(content, chunk_size=1000, overlap=200)
    assert len(chunks) >= 3
    # Verify overlap: end of chunk N overlaps with start of chunk N+1
    assert chunks[0][-200:] == chunks[1][:200]


def test_chunk_document_empty():
    """Empty content produces no chunks."""
    pipeline = RAGPipeline.__new__(RAGPipeline)
    pipeline.config = FakeConfig()
    chunks = pipeline.chunk_document("", chunk_size=1000, overlap=200)
    assert len(chunks) == 0
