"""JWT authentication for Claude Hub.

Uses FastAPI Depends() — NOT BaseHTTPMiddleware — to avoid WebSocket incompatibility.
WebSocket auth is handled via query parameter inside the endpoint.
"""

import jwt as pyjwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from claude_hub.config import settings

security = HTTPBearer()


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises on failure."""
    try:
        return pyjwt.decode(token, settings.auth_secret, algorithms=["HS256"])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """FastAPI dependency for API routes. Extracts Bearer token from header."""
    return decode_token(credentials.credentials)


def verify_ws_token(token: str) -> bool:
    """Verify a WebSocket token from query param. Returns True or raises."""
    if not token:
        return False
    try:
        pyjwt.decode(token, settings.auth_secret, algorithms=["HS256"])
        return True
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
        return False
