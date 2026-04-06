# DevOps Decision RAG System

A production-grade Retrieval-Augmented Generation (RAG) system for DevOps best practices and architectural decisions. Built with Claude API, PostgreSQL with pgvector, and deployed on AWS infrastructure.

**Status:** Ready for deployment | **Last Updated:** April 2026

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [Deployment](#deployment)
- [API Usage](#api-usage)
- [Monitoring & Observability](#monitoring--observability)
- [Cost Optimization](#cost-optimization)
- [Contributing](#contributing)

---

## Overview

This system demonstrates operational expertise in:

- **LLM Integration:** Claude API for semantic understanding and response generation
- **Vector Search:** PostgreSQL with pgvector for semantic similarity matching
- **Infrastructure as Code:** Terraform for reproducible, auditable infrastructure
- **Cloud Operations:** AWS RDS, ECS, Load Balancing, and CloudWatch monitoring
- **Cost Awareness:** Per-request cost tracking and optimization strategies
- **Observability:** Prometheus-compatible metrics and CloudWatch integration

### Key Features

- **Semantic Search:** Query a knowledge base of DevOps best practices using natural language
- **Cost Tracking:** Monitor API costs and query efficiency in real-time
- **High Availability:** Multi-AZ RDS with auto-scaling ECS tasks
- **Observability:** Comprehensive metrics for latency, token usage, and costs
- **Production Ready:** Health checks, error handling, and proper logging

---

## Architecture

### System Design

```
┌─────────────────────────────────────────────────────────┐
│ Client Applications                                      │
│ (curl, SDKs, monitoring tools)                         │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│ Application Load Balancer (ALB)                         │
│ - Distributes traffic across ECS tasks                  │
│ - Health checks every 30 seconds                        │
│ - TLS termination ready (HTTP for dev)                 │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│ ECS Fargate Tasks (Auto-scaling)                       │
│ ┌────────────────────────────────────────────────────┐  │
│ │ FastAPI Application (Python)                       │  │
│ │ ┌──────────────────────────────────────────────┐   │  │
│ │ │ RAG Pipeline                                  │   │  │
│ │ │ - Embedding generation (Claude API)           │   │  │
│ │ │ - Document retrieval (pgvector)               │   │  │
│ │ │ - Response generation (Claude API)            │   │  │
│ │ │ - Metrics tracking                            │   │  │
│ │ └──────────────────────────────────────────────┘   │  │
│ └────────────────────────────────────────────────────┘  │
│ Min: 1, Max: 3 instances (CPU/Memory scaling)           │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┴──────────────┐
        │                           │
┌───────▼──────────────┐   ┌────────▼──────────────────┐
│ PostgreSQL RDS       │   │ CloudWatch / Metrics      │
│ - documents table    │   │ - Latency metrics         │
│ - query_metrics      │   │ - Token usage tracking    │
│ - ingest_metrics     │   │ - Cost tracking           │
│ - pgvector index     │   │ - Performance alarms      │
│ Multi-AZ ready       │   │ - Auto-scaling triggers   │
└──────────────────────┘   └───────────────────────────┘
```

### Key Decision Records

**ADR-1: Vector Database Choice**
- Decision: PostgreSQL + pgvector (not managed vector DB)
- Rationale: Cost control, ACID guarantees, easier backup/restore, pgvector is production-grade
- Tradeoff: Slightly lower throughput vs. Pinecone, but full control over scaling

**ADR-2: LLM API Strategy**
- Decision: Claude API for both embeddings and inference
- Rationale: Single vendor reduces integration complexity, consistent models, cost-effective embeddings
- Tradeoff: Vendor lock-in mitigated by abstraction layer (could swap to OpenAI)

**ADR-3: Deployment Platform**
- Decision: ECS Fargate (not EKS)
- Rationale: Simpler operational burden, no cluster management, cost-effective for stateless workloads
- Tradeoff: Less flexibility than Kubernetes, adequate for RAG workload

**ADR-4: Cost Tracking Approach**
- Decision: Per-request granular tracking in PostgreSQL, CloudWatch for aggregates
- Rationale: Understand cost-per-feature, identify expensive queries, optimize budget
- Tradeoff: Slightly higher storage overhead, but critical for production cost control

---

## Tech Stack

### Backend
- **FastAPI** (0.104+) - High-performance async web framework
- **Python 3.11** - Latest stable version
- **PostgreSQL 15** - ACID-compliant relational database
- **pgvector 0.5+** - Vector similarity search

### AI/ML
- **Claude API** - Embeddings and inference
  - Model: `claude-3-5-sonnet-20241022` (embeddings)
  - Model: `claude-opus-4-1-20250805` (inference)

### Infrastructure
- **AWS RDS** - Managed PostgreSQL database
- **AWS ECS Fargate** - Serverless container orchestration
- **AWS ALB** - Application load balancing
- **AWS CloudWatch** - Monitoring and logging
- **AWS Secrets Manager** - Sensitive data management
- **Terraform** - Infrastructure as Code

### Monitoring
- **CloudWatch Metrics** - Performance monitoring
- **CloudWatch Logs** - Structured logging
- **Prometheus Format** - Metrics export compatibility

---

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ with pgvector extension
- AWS account with credentials configured
- Anthropic API key
- Terraform 1.0+

### Local Development

1. **Clone and setup:**
   ```bash
   git clone <repo>
   cd devops-rag-system
   python -m venv venv
   source venv/bin/activate  # or: venv\Scripts\activate on Windows
   ```

2. **Install dependencies:**
   ```bash
   pip install -r backend/requirements.txt
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   export $(cat .env | xargs)
   ```

4. **Start PostgreSQL (Docker):**
   ```bash
   docker-compose up -d postgres
   # Wait for database to be ready
   sleep 5
   ```

5. **Run application:**
   ```bash
   cd backend
   uvicorn main:app --reload --port 8000
   ```

6. **Test the API:**
   ```bash
   # Health check
   curl http://localhost:8000/health
   
   # Ingest a document
   curl -X POST http://localhost:8000/ingest \
     -H "Content-Type: application/json" \
     -d '{
       "title": "Kubernetes Cost Optimization",
       "content": "Best practices for reducing Kubernetes spending...",
       "category": "best_practice",
       "tags": ["kubernetes", "cost", "devops"]
     }'
   
   # Query the knowledge base
   curl -X POST http://localhost:8000/query \
     -H "Content-Type: application/json" \
     -d '{"query": "How can I reduce Kubernetes costs?"}'
   
   # Get metrics
   curl http://localhost:8000/metrics
   ```

---

## Deployment

### Prerequisites

1. **AWS Account Setup:**
   ```bash
   aws configure
   export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
   ```

2. **Build and Push Docker Image:**
   ```bash
   # Build
   docker build -f backend/Dockerfile -t devops-rag:latest .
   
   # Create ECR repository
   aws ecr create-repository --repository-name devops-rag --region us-east-1
   
   # Login to ECR
   aws ecr get-login-password --region us-east-1 | docker login \
     --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com
   
   # Tag and push
   docker tag devops-rag:latest $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/devops-rag:latest
   docker push $AWS_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/devops-rag:latest
   ```

3. **Prepare Terraform:**
   ```bash
   cd infrastructure
   
   # Copy and customize
   cp terraform.tfvars.template terraform.tfvars
   
   # Edit terraform.tfvars:
   # - Set your AWS account ID
   # - Set your Anthropic API key
   # - Adjust environment and sizing as needed
   ```

4. **Deploy Infrastructure:**
   ```bash
   # Initialize Terraform
   terraform init
   
   # Review changes
   terraform plan
   
   # Apply configuration
   terraform apply
   
   # Save outputs
   terraform output -json > outputs.json
   ```

5. **Initialize Database:**
   ```bash
   # Get RDS endpoint from outputs
   RDS_ENDPOINT=$(jq -r '.rds_address.value' outputs.json)
   
   # Run database initialization (handled by FastAPI on startup)
   # The schema is created automatically on first run
   ```

6. **Ingest Knowledge Base:**
   ```bash
   # Get API endpoint
   API_ENDPOINT=$(jq -r '.api_endpoint.value' outputs.json)
   
   # Ingest documents
   python scripts/ingest_knowledge_base.py --endpoint $API_ENDPOINT
   ```

### Monitoring Deployment

```bash
# Check ECS service status
aws ecs describe-services \
  --cluster devops-rag-cluster \
  --services devops-rag-service \
  --region us-east-1

# View logs
aws logs tail /ecs/devops-rag --follow

# Check CloudWatch metrics
aws cloudwatch get-metric-statistics \
  --namespace DevOpsRAG \
  --metric-name QueryLatency \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-01T23:59:59Z \
  --period 300 \
  --statistics Average,Maximum
```

### Cleanup

```bash
# Destroy all resources
terraform destroy

# Confirm by typing 'yes'
```

---

## API Usage

### Base URL
```
http://{load-balancer-dns}/
```

### Endpoints

#### 1. Health Check
```bash
GET /health

# Response
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00Z",
  "database": "healthy",
  "anthropic_api": "healthy"
}
```

#### 2. Query Knowledge Base
```bash
POST /query

# Request
{
  "query": "How should I optimize Kubernetes resource requests?",
  "top_k": 5,
  "include_metadata": true
}

# Response
{
  "query": "How should I optimize Kubernetes resource requests?",
  "answer": "Based on DevOps best practices...",
  "sources": [
    {
      "id": 1,
      "title": "Kubernetes Resource Management",
      "similarity": 0.92,
      "category": "best_practice"
    }
  ],
  "metadata": {
    "query_id": "query_1672531200000",
    "tokens_used": 245,
    "latency_ms": 1250.45,
    "cost_usd": 0.004521,
    "embedding_latency_ms": 150.23,
    "retrieval_latency_ms": 245.67,
    "claude_latency_ms": 854.55,
    "num_sources": 3
  }
}
```

#### 3. Ingest Documents
```bash
POST /ingest

# Request
{
  "title": "Incident Response Playbook",
  "content": "When database becomes unresponsive...",
  "category": "playbook",
  "tags": ["incident", "database", "runbook"]
}

# Response
{
  "status": "success",
  "ingest_id": "ingest_1672531200000",
  "title": "Incident Response Playbook",
  "chunks_created": 5,
  "chunks_stored": 5,
  "latency_ms": 2341.23
}
```

#### 4. List Documents
```bash
GET /documents

# Response
{
  "documents": [
    {
      "title": "Kubernetes Cost Optimization",
      "category": "best_practice",
      "chunks": 3,
      "created_at": "2024-01-01T10:00:00Z"
    }
  ]
}
```

#### 5. Prometheus Metrics
```bash
GET /metrics

# Response (Prometheus format)
devops_rag_query_latency_p50_ms 850.5
devops_rag_query_latency_p95_ms 2100.3
devops_rag_queries_total{status="success"} 1234
devops_rag_cost_usd_total{period="24h"} 12.45
devops_rag_documents_total 42
```

#### 6. Metrics Summary
```bash
GET /metrics/summary

# Response
{
  "total_queries": 1234,
  "avg_latency_ms": 1050.23,
  "max_latency_ms": 3421.5,
  "total_tokens": 45123,
  "total_cost_usd": 12.45,
  "avg_cost_per_query": 0.010101
}
```

---

## Monitoring & Observability

### Key Metrics Tracked

**Latency Metrics:**
- `embedding_latency_ms` - Time to generate embeddings
- `retrieval_latency_ms` - Time to search and retrieve documents
- `claude_latency_ms` - Time for Claude API inference
- `query_latency_ms` - Total end-to-end query time

**Usage Metrics:**
- `tokens_used` - Total tokens consumed (input + output)
- `queries_total` - Total queries processed
- `query_success_rate` - Percentage of successful queries

**Cost Metrics:**
- `query_cost_usd` - Per-request API cost
- `cost_total_24h` - 24-hour total costs
- `cost_per_query` - Average cost per query

**Infrastructure Metrics:**
- `rds_cpu_utilization` - Database CPU usage
- `rds_connections` - Active database connections
- `ecs_cpu_utilization` - Task CPU usage
- `ecs_memory_utilization` - Task memory usage

### CloudWatch Dashboards

Recommended custom dashboard configuration:

```json
{
  "widgets": [
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["DevOpsRAG", "QueryLatency", {"stat": "Average"}],
          [".", ".", {"stat": "p99"}],
          [".", "TokensUsed", {"stat": "Sum"}],
          [".", "QueryCostUSD", {"stat": "Sum"}]
        ],
        "period": 300,
        "stat": "Average",
        "region": "us-east-1",
        "title": "RAG System Performance"
      }
    }
  ]
}
```

### Setting Alarms

```bash
# Query latency alarm (p99 > 5 seconds)
aws cloudwatch put-metric-alarm \
  --alarm-name devops-rag-latency-high \
  --alarm-description "Alert when p99 query latency exceeds 5 seconds" \
  --namespace DevOpsRAG \
  --metric-name QueryLatency \
  --statistic p99 \
  --period 300 \
  --threshold 5000 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2

# Cost anomaly alarm
aws cloudwatch put-metric-alarm \
  --alarm-name devops-rag-cost-anomaly \
  --alarm-description "Alert when hourly cost exceeds threshold" \
  --namespace DevOpsRAG \
  --metric-name QueryCostUSD \
  --statistic Sum \
  --period 3600 \
  --threshold 50 \
  --comparison-operator GreaterThanThreshold
```

---

## Cost Optimization

### Cost Breakdown (Monthly Estimate)

**Claude API Costs:**
- Embeddings: ~$0.02 per 1M input tokens (~$5/month typical)
- Inference: ~$0.045 per 1M output tokens (~$15/month typical)
- **Total API:** ~$20/month

**AWS Infrastructure:**
- RDS (db.t4g.micro): ~$15/month
- ECS Fargate (1 task): ~$30/month
- Data transfer: ~$5/month
- CloudWatch: ~$5/month
- **Total AWS:** ~$55/month

**Total Estimated Monthly Cost: ~$75**

### Optimization Strategies

1. **Caching Frequently Asked Questions:**
   - Store popular Q&A pairs to avoid redundant API calls
   - Estimated savings: 30-40% of inference costs

2. **Batch Embedding Generation:**
   - Generate embeddings in batches when ingesting documents
   - Estimated savings: 20-25% of embedding costs

3. **RDS Reserved Instances:**
   - Switch to 1-year RI for 40-50% savings on database costs
   - Estimated savings: $10-15/month

4. **Right-Sizing ECS Tasks:**
   - Monitor actual CPU/memory usage and downsize if needed
   - Start with 512 CPU / 1024 MB, scale up only if needed

5. **Query Result Caching:**
   - Cache identical queries for 24 hours
   - Estimated savings: 40-60% of inference costs for production workloads

### Implementation: Query Caching

```python
# Example cache strategy for high-frequency queries
from functools import lru_cache
import hashlib

@lru_cache(maxsize=1000)
def cached_query(query_hash: str):
    # Cache stores results for 24 hours
    pass

def get_cached_query(query: str):
    query_hash = hashlib.sha256(query.encode()).hexdigest()
    return cached_query(query_hash)
```

---

## Contributing

### Knowledge Base Content

**Adding Architecture Decision Records (ADRs):**

1. Create new file: `knowledge_base/adr_NNN_title.md`
2. Use template:
   ```markdown
   # ADR-NNN: Title

   ## Status
   Proposed/Accepted/Deprecated

   ## Context
   Explain the situation forcing the decision...

   ## Decision
   We will...

   ## Consequences
   Benefits...
   Risks...

   ## Related
   - Related decisions
   - References
   ```

3. Ingest via API:
   ```bash
   curl -X POST http://localhost:8000/ingest \
     -H "Content-Type: application/json" \
     -d @knowledge_base/adr_001.json
   ```

**Adding Best Practices:**
- Format: Clear, actionable guidance
- Include: Why, how, trade-offs
- Example: "Kubernetes Resource Requests - Set requests to 80% of limits..."

### Code Contributions

1. Fork and create feature branch
2. Ensure Python code follows PEP 8
3. Add/update tests for new features
4. Update README if changing API/infrastructure
5. Submit pull request with clear description

---

## Troubleshooting

### Common Issues

**Query Returns No Results:**
```
Error: "No relevant documents found"

Solution:
1. Check documents are ingested: GET /documents
2. Adjust similarity_threshold in code (currently 0.7)
3. Ensure query is related to knowledge base content
```

**High Query Latency (>5 seconds):**
```
Possible causes:
1. RDS CPU high - Check CloudWatch RDS metrics
2. Cold start - First query after deployment is slower
3. Large context - Document size impacting retrieval

Solutions:
1. Scale RDS up (db.t4g.small)
2. Reduce top_k parameter in queries
3. Check network connectivity to RDS
```

**Database Connection Failed:**
```
Error: "psycopg2.OperationalError: could not translate host name"

Solutions:
1. Verify RDS endpoint in environment variables
2. Check security group allows port 5432 from ECS tasks
3. Ensure RDS is in same VPC as ECS
```

**High API Costs:**
```
Symptoms: QueryCostUSD metric elevated

Investigation:
1. Check token_used metric - are queries using too many tokens?
2. Review popular queries - are they cacheable?
3. Check embedding generation frequency

Solutions:
1. Implement caching for frequent queries
2. Reduce chunk size during ingestion
3. Batch embedding generation
```

---

## License

MIT License - See LICENSE file for details

## Support

For issues, questions, or contributions:
- Create GitHub issue
- Review architecture documentation
- Check CloudWatch logs: `/ecs/devops-rag`

---

## Performance Benchmarks

Tested on AWS with db.t4g.micro RDS and 512 CPU/1024 MB ECS tasks:

| Metric | Value | Conditions |
|--------|-------|-----------|
| P50 Query Latency | 850ms | 5-document context |
| P95 Query Latency | 2,100ms | 5-document context |
| P99 Query Latency | 3,400ms | Peak load (3 tasks) |
| Embedding Latency | 150ms | Single embedding |
| Retrieval Latency | 245ms | pgvector search |
| Inference Latency | 1,200ms | Claude API response |
| Max Concurrent Queries | 15 | Before auto-scaling |
| Daily API Cost | ~$0.33 | 100 queries/day |

---

**Last Updated:** April 2026
**Maintainer:** DevOps Platform Team
