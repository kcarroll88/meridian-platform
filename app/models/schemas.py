import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
import re


# --- Tenant schemas ---

class TenantCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    rate_limit_requests: int = Field(default=60, ge=1, le=10_000)
    rate_limit_tokens: int = Field(default=100_000, ge=1000, le=10_000_000)

    @field_validator("slug")
    @classmethod
    def slug_no_double_dash(cls, v: str) -> str:
        if "--" in v:
            raise ValueError("slug cannot contain consecutive dashes")
        return v


class TenantUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    is_active: bool | None = None
    rate_limit_requests: int | None = Field(None, ge=1, le=10_000)
    rate_limit_tokens: int | None = Field(None, ge=1000, le=10_000_000)


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    rate_limit_requests: int
    rate_limit_tokens: int
    chroma_collection: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TenantListResponse(BaseModel):
    tenants: list[TenantResponse]
    total: int


# --- API Key schemas ---

class ApiKeyCreate(BaseModel):
    label: str | None = Field(None, max_length=100)


class ApiKeyCreatedResponse(BaseModel):
    """Returned once at creation — raw key never stored."""
    id: uuid.UUID
    key: str  # raw key, show once
    key_prefix: str
    label: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiKeyResponse(BaseModel):
    """Safe to return anytime — no raw key."""
    id: uuid.UUID
    key_prefix: str
    label: str | None
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


# --- Usage schemas ---

class UsageSummaryResponse(BaseModel):
    tenant_id: uuid.UUID
    tenant_slug: str
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    avg_latency_ms: float
    estimated_cost_usd: float  # Week 4: cost modeling


# --- Auth schemas ---

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AdminLogin(BaseModel):
    username: str
    password: str
