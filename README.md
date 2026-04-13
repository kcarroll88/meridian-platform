# Multi-Tenant RAG API

A production-grade multi-tenant RAG (Retrieval-Augmented Generation) API built with FastAPI, PostgreSQL, Redis, and Claude. Each tenant gets isolated document storage, rate limiting, and full usage tracking.

**Live demo:** [coming — Railway deploy Week 1]

---

## Architecture

```
Clients (Locust · curl · demo UI)
        │
        ▼
FastAPI Gateway
  JWT auth · tenant resolution · Redis rate limiting
        │
   ┌────┼────┐
   ▼    ▼    ▼
RAG   Ingest  Tenant
Query  Docs   Admin
   │    │      │
   ▼    ▼      ▼
ChromaDB  Redis  PostgreSQL
(per-tenant    (tenants ·
collections)    usage · audit)
        │
        ▼
Observability
structured logs · trace IDs · LangSmith · /metrics
        │
        ▼
Scale Proof
Locust reports · p50/p95/p99 · cost model
```

---

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI + asyncpg |
| Auth | JWT (admin) + hashed API keys (tenants) |
| Vector store | ChromaDB with per-tenant collection namespaces |
| LLM | Claude (via LangChain) |
| Embeddings | Voyage AI |
| Queue / rate limiting | Redis (Upstash in production) |
| Database | PostgreSQL (Railway in production) |
| Observability | structlog + LangSmith + custom /metrics |
| Load testing | Locust |
| Deploy | Docker + Railway |

---

## Quick start

```bash
# 1. Clone and set up env
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY and generate a SECRET_KEY:
# openssl rand -hex 32

# 2. Start everything
docker compose up

# 3. API docs
open http://localhost:8000/docs
```

---

## API overview

### Admin endpoints (JWT required)

```bash
# Get admin token
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "changeme"}'

# Create a tenant (returns API key — shown once)
curl -X POST http://localhost:8000/api/v1/tenants \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp", "slug": "acme"}'

# List tenants
curl http://localhost:8000/api/v1/tenants \
  -H "Authorization: Bearer <admin_token>"
```

### Tenant endpoints (API key required)

```bash
# Ingest a document (Week 2)
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Authorization: Bearer rtk_..." \
  -F "file=@document.pdf"

# Query (Week 2)
curl -X POST http://localhost:8000/api/v1/query \
  -H "Authorization: Bearer rtk_..." \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the main competitors?"}'
```

### Observability

```bash
curl http://localhost:8000/health
curl http://localhost:8000/metrics
```

Every response includes `X-Trace-ID` and `X-Latency-Ms` headers.

---

## Tenant isolation

Each tenant has:
- A dedicated ChromaDB collection (`tenant_{slug}`) — documents never cross tenant boundaries
- Per-tenant rate limits (requests/min and tokens/min), enforced via Redis sliding window
- All usage logged with trace IDs for auditability

---

## Scale architecture

*Load test results added Week 4*

Target: 10,000 concurrent users, p95 < 2s for RAG queries

| Metric | Target | Actual |
|---|---|---|
| p50 latency | < 800ms | TBD |
| p95 latency | < 2000ms | TBD |
| p99 latency | < 4000ms | TBD |
| Max RPS | 500+ | TBD |
| Cost at 10k users/day | < $X | TBD |

---

## Development

```bash
# Run tests
pip install pytest pytest-asyncio httpx aiosqlite
pytest

# Run with hot reload
uvicorn app.main:app --reload
```

---

## Roadmap

- [x] Week 1 — FastAPI scaffold, PostgreSQL, JWT + API key auth, tenant CRUD, tracing middleware
- [x] Week 2 — RAG query + doc ingest with per-tenant ChromaDB isolation
- [x] Week 3 — Redis rate limiting + job queue, full observability
- [ ] Week 4 — Locust load tests, cost model, README scale proof section
