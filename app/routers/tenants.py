import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.schemas import (
    TenantCreate, TenantUpdate, TenantResponse, TenantListResponse,
    ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse,
)
from app.services import tenant_service
from app.services.auth import require_admin

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    data: TenantCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
):
    """Create a new tenant. Returns the initial API key — shown once."""
    tenant, raw_key = await tenant_service.create_tenant(db, data)
    return ApiKeyCreatedResponse(
        id=tenant.api_keys[0].id,
        key=raw_key,
        key_prefix=tenant.api_keys[0].key_prefix,
        label=tenant.api_keys[0].label,
        created_at=tenant.api_keys[0].created_at,
    )


@router.get("", response_model=TenantListResponse)
async def list_tenants(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
):
    tenants, total = await tenant_service.list_tenants(db, skip=skip, limit=limit)
    return TenantListResponse(tenants=tenants, total=total)


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
):
    return await tenant_service.get_tenant(db, tenant_id)


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: uuid.UUID,
    data: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
):
    return await tenant_service.update_tenant(db, tenant_id, data)


# --- API Key management ---

@router.post("/{tenant_id}/keys", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    tenant_id: uuid.UUID,
    data: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
):
    """Generate a new API key for a tenant. Raw key shown once."""
    api_key, raw_key = await tenant_service.create_api_key(db, tenant_id, data.label)
    return ApiKeyCreatedResponse(
        id=api_key.id,
        key=raw_key,
        key_prefix=api_key.key_prefix,
        label=api_key.label,
        created_at=api_key.created_at,
    )


@router.delete("/{tenant_id}/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    tenant_id: uuid.UUID,
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_admin),
):
    await tenant_service.revoke_api_key(db, tenant_id, key_id)
