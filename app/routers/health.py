from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, func
from datetime import datetime, timezone

from app.db.database import get_db
from app.models.tenant import Tenant, UsageLog
from app.config import get_settings

router = APIRouter(tags=["observability"])
settings = get_settings()


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """Liveness + readiness check."""
    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    return {
        "status": "ok" if db_ok else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": settings.environment,
        "checks": {
            "database": "ok" if db_ok else "error",
        },
    }


@router.get("/metrics")
async def metrics(db: AsyncSession = Depends(get_db)):
    """Aggregate usage metrics — useful for load test dashboards."""
    tenant_count = (await db.execute(select(func.count()).select_from(Tenant))).scalar_one()
    active_tenants = (await db.execute(
        select(func.count()).select_from(Tenant).where(Tenant.is_active == True)
    )).scalar_one()

    total_requests = (await db.execute(select(func.count()).select_from(UsageLog))).scalar_one()
    total_tokens = (await db.execute(
        select(func.sum(UsageLog.input_tokens + UsageLog.output_tokens)).select_from(UsageLog)
    )).scalar_one() or 0
    avg_latency = (await db.execute(
        select(func.avg(UsageLog.latency_ms)).select_from(UsageLog)
    )).scalar_one() or 0

    return {
        "tenants": {"total": tenant_count, "active": active_tenants},
        "requests": {"total": total_requests},
        "tokens": {"total": int(total_tokens)},
        "latency": {"avg_ms": round(float(avg_latency), 2)},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
