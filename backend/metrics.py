"""
Metrics Module
Tracks operational metrics and exports to CloudWatch and Prometheus
"""

import logging
from contextlib import contextmanager
from datetime import datetime

import boto3
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)


class CloudWatchMetrics:
    """
    Tracks system metrics for observability.

    Metrics tracked:
    - Query latency (embedding, retrieval, Claude inference)
    - Token usage and costs
    - Query success/failure rates
    - Document ingestion metrics
    - Health check status
    """

    def __init__(self, config, pool: ThreadedConnectionPool = None):
        """
        Initialize metrics tracking.

        Args:
            config: Configuration object with AWS credentials
            pool: Shared database connection pool (optional; creates own if not provided)
        """
        self.config = config
        self._external_pool = pool
        self.db_config = {
            "dbname": config.db_name,
            "user": config.db_user,
            "password": config.db_password,
            "host": config.db_host,
            "port": config.db_port,
            "sslmode": config.db_sslmode,
            "connect_timeout": 5,
        }
        if pool is None:
            self._own_pool = ThreadedConnectionPool(minconn=1, maxconn=5, **self.db_config)
        else:
            self._own_pool = None

        # Initialize CloudWatch client (skip in local development)
        self.namespace = "DevOpsRAG"
        if config.is_production():
            try:
                self.cloudwatch = boto3.client(
                    "cloudwatch",
                    region_name=config.aws_region,
                )
                logger.info("CloudWatch client initialized")
            except Exception as e:
                logger.warning(f"Could not initialize CloudWatch client: {e}")
                self.cloudwatch = None
        else:
            self.cloudwatch = None
            logger.info("CloudWatch disabled in development mode")

    @contextmanager
    def _conn(self):
        """Get a connection from the pool. Always returns it on exit."""
        pool = self._external_pool or self._own_pool
        conn = pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)

    def record_query_metric(self, query_id: str, query: str, success: bool, tokens_used: int, latency_ms: float):
        """
        Record a query execution metric.

        Args:
            query_id: Unique query identifier
            query: Query text (for logging)
            success: Whether query succeeded
            tokens_used: Total tokens (input + output)
            latency_ms: Total latency in milliseconds
        """
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO query_metrics (query_id, query, success, tokens_used, latency_ms)
                        VALUES (%s, %s, %s, %s, %s)
                    """,
                        (query_id, query, success, tokens_used, latency_ms),
                    )

            # Push to CloudWatch
            if self.cloudwatch and success:
                self._push_cloudwatch_metric(metric_name="QueryLatency", value=latency_ms, unit="Milliseconds")
                self._push_cloudwatch_metric(metric_name="TokensUsed", value=tokens_used, unit="Count")

            logger.debug(f"Recorded query metric: {query_id}")

        except Exception as e:
            logger.error(f"Failed to record query metric: {e}")

    def record_query_cost(self, cost_usd: float):
        """
        Record API cost for a query.

        Args:
            cost_usd: Cost in USD
        """
        try:
            if self.cloudwatch:
                self._push_cloudwatch_metric(metric_name="QueryCostUSD", value=cost_usd, unit="None")

            logger.debug(f"Recorded query cost: ${cost_usd:.6f}")

        except Exception as e:
            logger.error(f"Failed to record query cost: {e}")

    def record_embedding_latency(self, latency_ms: float):
        """Record embedding generation latency."""
        try:
            if self.cloudwatch:
                self._push_cloudwatch_metric(metric_name="EmbeddingLatency", value=latency_ms, unit="Milliseconds")
        except Exception as e:
            logger.error(f"Failed to record embedding latency: {e}")

    def record_retrieval_latency(self, latency_ms: float):
        """Record document retrieval latency."""
        try:
            if self.cloudwatch:
                self._push_cloudwatch_metric(metric_name="RetrievalLatency", value=latency_ms, unit="Milliseconds")
        except Exception as e:
            logger.error(f"Failed to record retrieval latency: {e}")

    def record_llm_latency(self, latency_ms: float):
        """Record LLM inference latency."""
        try:
            if self.cloudwatch:
                self._push_cloudwatch_metric(metric_name="LLMLatency", value=latency_ms, unit="Milliseconds")
        except Exception as e:
            logger.error(f"Failed to record LLM latency: {e}")

    def record_health_check_latency(self, latency_ms: float):
        """Record health check latency."""
        try:
            if self.cloudwatch:
                self._push_cloudwatch_metric(metric_name="HealthCheckLatency", value=latency_ms, unit="Milliseconds")
        except Exception as e:
            logger.error(f"Failed to record health check latency: {e}")

    def record_ingest_metric(self, ingest_id: str, title: str, chunks_stored: int, latency_ms: float):
        """
        Record document ingestion metric.

        Args:
            ingest_id: Unique ingest identifier
            title: Document title
            chunks_stored: Number of chunks stored
            latency_ms: Ingestion latency
        """
        try:
            with self._conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO ingest_metrics (ingest_id, title, chunks_stored, latency_ms)
                        VALUES (%s, %s, %s, %s)
                    """,
                        (ingest_id, title, chunks_stored, latency_ms),
                    )

            if self.cloudwatch:
                self._push_cloudwatch_metric(metric_name="IngestLatency", value=latency_ms, unit="Milliseconds")
                self._push_cloudwatch_metric(metric_name="ChunksStored", value=chunks_stored, unit="Count")

            logger.debug(f"Recorded ingest metric: {ingest_id}")

        except Exception as e:
            logger.error(f"Failed to record ingest metric: {e}")

    def _push_cloudwatch_metric(self, metric_name: str, value: float, unit: str):
        """
        Push a metric to CloudWatch.

        Args:
            metric_name: CloudWatch metric name
            value: Metric value
            unit: CloudWatch unit (Milliseconds, Count, None, etc.)
        """
        if not self.cloudwatch:
            return

        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=[{"MetricName": metric_name, "Value": value, "Unit": unit, "Timestamp": datetime.utcnow()}],
            )
        except Exception as e:
            logger.warning(f"Failed to push CloudWatch metric {metric_name}: {e}")

    def get_prometheus_metrics(self) -> str:
        """
        Generate Prometheus-compatible metrics output.

        Returns:
            String in Prometheus text format
        """
        try:
            metrics_output = [
                "# HELP devops_rag_metrics DevOps RAG System Metrics",
                "# TYPE devops_rag_metrics gauge",
            ]

            with self._conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT
                            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms) as p50,
                            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) as p95,
                            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms) as p99,
                            COUNT(*) as total_queries,
                            SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_queries
                        FROM query_metrics
                        WHERE timestamp > NOW() - INTERVAL '1 hour'
                    """)

                    query_stats = cur.fetchone()
                    if query_stats:
                        metrics_output.append(f"devops_rag_query_latency_p50_ms {query_stats['p50'] or 0}")
                        metrics_output.append(f"devops_rag_query_latency_p95_ms {query_stats['p95'] or 0}")
                        metrics_output.append(f"devops_rag_query_latency_p99_ms {query_stats['p99'] or 0}")
                        metrics_output.append(
                            f"devops_rag_queries_total {{status=\"success\"}} {query_stats['successful_queries'] or 0}"
                        )
                        metrics_output.append(
                            f"devops_rag_queries_total {{status=\"all\"}} {query_stats['total_queries'] or 0}"
                        )

                    cur.execute("""
                        SELECT
                            SUM(tokens_used) as total_tokens,
                            SUM(cost_usd) as total_cost
                        FROM query_metrics
                        WHERE timestamp > NOW() - INTERVAL '24 hours'
                    """)

                    cost_stats = cur.fetchone()
                    if cost_stats:
                        metrics_output.append(
                            f"devops_rag_tokens_total {{period=\"24h\"}} {cost_stats['total_tokens'] or 0}"
                        )
                        metrics_output.append(
                            f"devops_rag_cost_usd_total {{period=\"24h\"}} {cost_stats['total_cost'] or 0}"
                        )

                    cur.execute("SELECT COUNT(*) as total_documents FROM documents")
                    doc_count = cur.fetchone()
                    if doc_count:
                        metrics_output.append(f"devops_rag_documents_total {doc_count['total_documents'] or 0}")

            return "\n".join(metrics_output)

        except Exception as e:
            logger.error(f"Failed to generate Prometheus metrics: {e}")
            return "# Error generating metrics"
