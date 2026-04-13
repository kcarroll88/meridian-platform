import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import get_settings
from app.db.database import get_db
from app.models.tenant import ApiKey, Tenant
from app.logger import get_logger

settings = get_settings()
logger = get_logger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()

ADMIN_USERNAME = "admin"
# In production: load from env/secrets manager
ADMIN_PASSWORD_HASH = pwd_context.hash("changeme")


# --- JWT (admin access) ---

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def verify_admin_credentials(username: str, password: str) -> bool:
    return username == ADMIN_USERNAME and pwd_context.verify(password, ADMIN_PASSWORD_HASH)


async def require_admin(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired admin token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, settings.secret_key, algorithms=[settings.algorithm])
        role: str = payload.get("role")
        if role != "admin":
            raise credentials_exception
        return payload
    except JWTError:
        raise credentials_exception


# --- API Key (tenant access) ---

def generate_api_key() -> tuple[str, str, str]:
    """Returns (raw_key, key_hash, key_prefix)."""
    raw = "rtk_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    key_prefix = raw[:12]
    return raw, key_hash, key_prefix


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def get_tenant_from_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    key_hash = hash_api_key(credentials.credentials)

    result = await db.execute(
        select(ApiKey)
        .join(Tenant)
        .where(ApiKey.key_hash == key_hash, ApiKey.is_active == True, Tenant.is_active == True)
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )

    # Update last_used_at (fire and forget — don't block the request)
    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info("api_key_authenticated", tenant_id=str(api_key.tenant_id), prefix=api_key.key_prefix)
    return api_key.tenant
