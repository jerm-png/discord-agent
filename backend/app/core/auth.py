from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import HTTPException, Security, Cookie
from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials,
)
from app.core.config import (
    JWT_SECRET,
    JWT_ALGORITHM,
    JWT_EXPIRE_HOURS,
    DRIFT_PASSWORD,
)

security = HTTPBearer(auto_error=False)

def verify_password(plain: str) -> bool:
    """
    Verify a password against the configured
    Drift password.
    """
    return plain == DRIFT_PASSWORD.strip()

def create_token() -> str:
    """
    Create a JWT token valid for
    JWT_EXPIRE_HOURS hours.
    """
    expire = datetime.utcnow() + timedelta(
        hours=JWT_EXPIRE_HOURS
    )
    return jwt.encode(
        {"sub": "drift-owner", "exp": expire},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )

def verify_token(token: str) -> bool:
    """Verify a JWT token is valid and not expired."""
    try:
        jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
        return True
    except JWTError:
        return False

async def require_auth(
    credentials: HTTPAuthorizationCredentials = Security(
        security
    ),
    drift_token: str = Cookie(default=None),
) -> str:
    """
    FastAPI dependency — require valid auth.
    Accepts token from httpOnly cookie or
    Authorization header.
    Raises 401 if neither is valid.
    """
    if drift_token and verify_token(drift_token):
        return "drift-owner"

    if credentials and verify_token(
        credentials.credentials
    ):
        return "drift-owner"

    raise HTTPException(
        status_code=401,
        detail="Not authenticated",
    )
