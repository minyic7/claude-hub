from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import jwt
from claude_hub.auth import require_auth
from claude_hub.config import settings

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_in: int


@router.post("/api/login")
async def login(req: LoginRequest) -> LoginResponse:
    if req.username == settings.auth_username and req.password == settings.auth_password:
        exp = datetime.now(timezone.utc) + timedelta(hours=settings.auth_token_hours)
        token = jwt.encode({"exp": exp}, settings.auth_secret, algorithm="HS256")
        return LoginResponse(
            token=token,
            expires_in=settings.auth_token_hours * 3600,
        )
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/api/auth/check")
async def auth_check():
    """Public endpoint: tells the frontend whether auth is required."""
    return {"auth_required": settings.auth_enabled}


@router.get("/api/auth/verify")
async def verify_token(_payload: dict = Depends(require_auth)):
    """Returns 200 if the request has a valid token. Used by frontend to validate stored token."""
    return {"status": "ok"}
