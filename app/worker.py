import asyncio
import json

import redis.asyncio as aioredis

from app.config import get_settings
from app.logger import setup_logging, get_logger
from app.services.rag_service import RAGService
from app.services.queue_service import (
    INGEST_QUEUE,
    JOB_KEY_PREFIX,
    JobStatus,
    update_job_status,
)

setup_logging()
settings = get_settings()
logger = get_logger(__name__)


async def process_job(job_id: str, redis: aioredis.Redis):
    await update_job_status(job_id, JobStatus.PROCESSING)
    logger.info("job_processing", job_id=job_id)

    try:
        raw = await redis.get(f"{JOB_KEY_PREFIX}{job_id}")
        if not raw:
            raise ValueError("Job metadata not found")

        job_data = json.loads(raw)
        hex_bytes = await redis.get(f"{JOB_KEY_PREFIX}{job_id}:bytes")
        if not hex_bytes:
            raise ValueError("Job file bytes not found")

        file_bytes = bytes.fromhex(hex_bytes)
        rag = RAGService(collection_name=job_data["collection_name"])
        result = await rag.ingest_pdf(file_bytes, job_data["filename"])

        await update_job_status(job_id, JobStatus.COMPLETE, result=result)
        logger.info("job_complete", job_id=job_id, result=result)

        await redis.delete(f"{JOB_KEY_PREFIX}{job_id}:bytes")

    except Exception as e:
        logger.error("job_failed", job_id=job_id, error=str(e))
        await update_job_status(job_id, JobStatus.FAILED, error=str(e))


async def run_worker():
    logger.info("worker_starting")
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    while True:
        try:
            result = await redis.brpop(INGEST_QUEUE, timeout=5)
            if result:
                _, job_id = result
                await process_job(job_id, redis)
        except Exception as e:
            logger.error("worker_error", error=str(e))
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run_worker())