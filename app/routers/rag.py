import structlog
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Request, status
from pydantic import BaseModel

from app.models.tenant import Tenant
from app.services.auth import get_tenant_from_api_key
from app.services.rag_service import RAGService
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


class IngestResponse(BaseModel):
    filename: str
    chunks_stored: int
    collection: str


@router.post("/ingest", response_model=IngestResponse)
async def ingest_document(
    request: Request,
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_tenant_from_api_key),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported")

    file_bytes = await file.read()

    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large. Max 20MB")

    if len(file_bytes) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty")

    try:
        rag = RAGService(collection_name=tenant.chroma_collection)
        result = await rag.ingest_pdf(file_bytes, file.filename)
        return IngestResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error("ingest_error", error=str(e), tenant_id=str(tenant.id))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ingest failed")


@router.post("/query", response_model=QueryResponse)
async def query_documents(
    request: Request,
    body: QueryRequest,
    tenant: Tenant = Depends(get_tenant_from_api_key),
):
    if not body.question.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Question cannot be empty")

    trace_id = request.headers.get("x-trace-id", "")
    structlog.contextvars.bind_contextvars(tenant_id=str(tenant.id), tenant_slug=tenant.slug)

    try:
        rag = RAGService(collection_name=tenant.chroma_collection)
        result = await rag.query(body.question, trace_id=trace_id)
        return QueryResponse(**result)
    except Exception as e:
        logger.error("query_error", error=str(e), tenant_id=str(tenant.id))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Query failed")