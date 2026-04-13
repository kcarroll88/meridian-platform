import json
import uuid
from datetime import datetime, timezone
from enum import Enum

import redis.asyncio as aioredis

from app.config import get_settings
from app.logger import get_logger

settings = get_settings()
logger = get_logger(__name__)

INGEST_QUEUE = "queue:ingest"
JOB_KEY_PREFIX = "job:"
JOB_TTL = 60 * 60 * 24  # 24 hours


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


def get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def enqueue_ingest_job(
    tenant_id: str,
    collection_name: str,
    filename: str,
    file_bytes: bytes,
) -> str:
    job_id = str(uuid.uuid4())
    redis = get_redis()

    job_data = {
        "job_id": job_id,
        "tenant_id": tenant_id,
        "collection_name": collection_name,
        "filename": filename,
        "status": JobStatus.PENDING,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result": None,
        "error": None,
    }

    # Store job metadata
    await redis.setex(
        f"{JOB_KEY_PREFIX}{job_id}",
        JOB_TTL,
        json.dumps(job_data),
    )

    # Push file bytes separately (binary)
    await redis.setex(
        f"{JOB_KEY_PREFIX}{job_id}:bytes",
        JOB_TTL,
        file_bytes.hex(),
    )

    # Push job ID to queue
    await redis.lpush(INGEST_QUEUE, job_id)

    logger.info("job_enqueued", job_id=job_id, filename=filename, tenant_id=tenant_id)
    await redis.aclose()
    return job_id


async def get_job_status(job_id: str) -> dict | None:
    redis = get_redis()
    raw = await redis.get(f"{JOB_KEY_PREFIX}{job_id}")
    await redis.aclose()
    if not raw:
        return None
    return json.loads(raw)


async def update_job_status(
    job_id: str,
    status: JobStatus,
    result: dict | None = None,
    error: str | None = None,
):
    redis = get_redis()
    raw = await redis.get(f"{JOB_KEY_PREFIX}{job_id}")
    if raw:
        job_data = json.loads(raw)
        job_data["status"] = status
        job_data["result"] = result
        job_data["error"] = error
        job_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await redis.setex(
            f"{JOB_KEY_PREFIX}{job_id}",
            JOB_TTL,
            json.dumps(job_data),
        )
    await redis.aclose()