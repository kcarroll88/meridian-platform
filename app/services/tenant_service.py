from sqlalchemy.orm import selectinload
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException, status

from app.models.tenant import Tenant, ApiKey
from app.models.schemas import TenantCreate, TenantUpdate
from app.services.auth import generate_api_key
from app.logger import get_logger

logger = get_logger(__name__)


def _slug_to_collection(slug: str) -> str:
    """Generate a stable ChromaDB collection name from tenant slug."""
    return f"tenant_{slug.replace('-', '_')}"


async def create_tenant(db: AsyncSession, data: TenantCreate) -> tuple[Tenant, str]:
    """Returns (tenant, raw_api_key). Raw key shown once."""
    existing = await db.execute(select(Tenant).where(Tenant.slug == data.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant with slug '{data.slug}' already exists",
        )

    tenant = Tenant(
        name=data.name,
        slug=data.slug,
        rate_limit_requests=data.rate_limit_requests,
        rate_limit_tokens=data.rate_limit_tokens,
        chroma_collection=_slug_to_collection(data.slug),
    )
    db.add(tenant)
    await db.flush()  # get tenant.id

    raw_key, key_hash, key_prefix = generate_api_key()
    api_key = ApiKey(
        tenant_id=tenant.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        label="default",
    )
    db.add(api_key)
    await db.flush()  # persist api_key

    # Eagerly load relationship before commit
    await db.refresh(tenant, ["api_keys"])
    await db.commit()

    logger.info("tenant_created", tenant_id=str(tenant.id), slug=tenant.slug)
    return tenant, raw_key


async def get_tenant(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


async def get_tenant_by_slug(db: AsyncSession, slug: str) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


async def list_tenants(db: AsyncSession, skip: int = 0, limit: int = 50) -> tuple[list[Tenant], int]:
    count_result = await db.execute(select(func.count()).select_from(Tenant))
    total = count_result.scalar_one()

    result = await db.execute(select(Tenant).offset(skip).limit(limit).order_by(Tenant.created_at.desc()))
    tenants = result.scalars().all()
    return list(tenants), total


async def update_tenant(db: AsyncSession, tenant_id: uuid.UUID, data: TenantUpdate) -> Tenant:
    tenant = await get_tenant(db, tenant_id)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tenant, field, value)

    await db.commit()
    await db.refresh(tenant)
    logger.info("tenant_updated", tenant_id=str(tenant_id), fields=list(update_data.keys()))
    return tenant


async def create_api_key(db: AsyncSession, tenant_id: uuid.UUID, label: str | None) -> tuple[ApiKey, str]:
    """Returns (api_key_record, raw_key). Raw key shown once."""
    await get_tenant(db, tenant_id)  # validates existence

    raw_key, key_hash, key_prefix = generate_api_key()
    api_key = ApiKey(
        tenant_id=tenant_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        label=label,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.info("api_key_created", tenant_id=str(tenant_id), prefix=key_prefix)
    return api_key, raw_key


async def revoke_api_key(db: AsyncSession, tenant_id: uuid.UUID, key_id: uuid.UUID) -> None:
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id)
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    api_key.is_active = False
    await db.commit()
    logger.info("api_key_revoked", key_id=str(key_id), tenant_id=str(tenant_id))
