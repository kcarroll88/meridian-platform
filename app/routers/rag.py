import structlog
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Request, status
from pydantic import BaseModel

from app.models.tenant import Tenant
from app.services.auth import get_tenant_from_api_key
from app.services.rag_service import RAGService
from app.services.queue_service import enqueue_ingest_job, get_job_status
from app.services.rate_limiter import check_rate_limit
from app.logger import get_logger

router = APIRouter(tags=["rag"])
logger = get_logger(__name__)

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict]
    chunks_retrieved: int


class IngestJobResponse(BaseModel):
    job_id: str
    status: str
    filename: str


@router.post("/ingest", response_model=IngestJobResponse, status_code=202)
async def ingest_document(
    request: Request,
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_tenant_from_api_key),
):
    """Enqueue a PDF for async ingestion. Returns a job_id to poll for status."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    file_bytes = await file.read()

    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Max 20MB")

    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="File is empty")

    # Rate limit check
    allowed, count, retry_after = await check_rate_limit(
        tenant_id=str(tenant.id),
        limit=tenant.rate_limit_requests,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    job_id = await enqueue_ingest_job(
        tenant_id=str(tenant.id),
        collection_name=tenant.chroma_collection,
        filename=file.filename,
        file_bytes=file_bytes,
    )

    return IngestJobResponse(job_id=job_id, status="pending", filename=file.filename)


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    tenant: Tenant = Depends(get_tenant_from_api_key),
):
    """Poll for ingest job status."""
    job = await get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Ensure tenant can only see their own jobs
    if job["tenant_id"] != str(tenant.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    return job


@router.post("/query", response_model=QueryResponse)
async def query_documents(
    request: Request,
    body: QueryRequest,
    tenant: Tenant = Depends(get_tenant_from_api_key),
):
    """Query the tenant's document collection."""
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    # Rate limit check
    allowed, count, retry_after = await check_rate_limit(
        tenant_id=str(tenant.id),
        limit=tenant.rate_limit_requests,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    trace_id = request.headers.get("x-trace-id", "")
    structlog.contextvars.bind_contextvars(tenant_id=str(tenant.id), tenant_slug=tenant.slug)

    try:
        rag = RAGService(collection_name=tenant.chroma_collection)
        result = await rag.query(body.question, trace_id=trace_id)
        return QueryResponse(**result)
    except Exception as e:
        logger.error("query_error", error=str(e), tenant_id=str(tenant.id))
        raise HTTPException(status_code=500, detail="Query failed")