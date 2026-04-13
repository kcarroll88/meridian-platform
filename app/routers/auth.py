from fastapi import APIRouter, HTTPException, status
from app.models.schemas import AdminLogin, TokenResponse
from app.services.auth import verify_admin_credentials, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def login(data: AdminLogin):
    if not verify_admin_credentials(data.username, data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    token = create_access_token({"sub": data.username, "role": "admin"})
    return TokenResponse(access_token=token)
