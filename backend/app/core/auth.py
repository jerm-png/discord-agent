from datetime import datetime, timedelta
from typing import Optional, TypedDict
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
    PARKER_PASSWORD,
)

security = HTTPBearer(auto_error=False)


class CurrentUser(TypedDict):
    user_id: str
    role: str


def verify_password(plain: str) -> Optional[CurrentUser]:
    """
    Match a submitted password against the known accounts.
    Returns {user_id, role} on hit, None otherwise.
    """
    submitted = plain.strip()
    if DRIFT_PASSWORD and submitted == DRIFT_PASSWORD.strip():
        return {"user_id": "drift-owner", "role": "admin"}
    if PARKER_PASSWORD and submitted == PARKER_PASSWORD.strip():
        return {"user_id": "parker", "role": "user"}
    return None


def create_token(user_id: str, role: str) -> str:
    """Create a JWT carrying user_id (sub) and role."""
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": user_id, "role": role, "exp": expire},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def decode_token(token: str) -> Optional[CurrentUser]:
    """Return the {user_id, role} payload if the token is valid; else None."""
    try:
        payload = jwt.decode(
            token, JWT_SECRET, algorithms=[JWT_ALGORITHM]
        )
        user_id = payload.get("sub")
        role = payload.get("role", "user")
        if not user_id:
            return None
        return {"user_id": user_id, "role": role}
    except JWTError:
        return None


def verify_token(token: str) -> bool:
    """Legacy boolean check kept for WS handlers that only need yes/no."""
    return decode_token(token) is not None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
    drift_token: str = Cookie(default=None),
) -> CurrentUser:
    """FastAPI dependency that returns the authenticated {user_id, role}."""
    if drift_token:
        user = decode_token(drift_token)
        if user:
            return user
    if credentials:
        user = decode_token(credentials.credentials)
        if user:
            return user
    raise HTTPException(status_code=401, detail="Not authenticated")


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Security(security),
    drift_token: str = Cookie(default=None),
) -> str:
    """
    Legacy dependency that returns just the user_id string. Kept so the
    many existing endpoints typed `user: str = Depends(require_auth)`
    don't all need to change at once.
    """
    user = await get_current_user(credentials, drift_token)
    return user["user_id"]


async def require_admin(
    user: CurrentUser = Security(get_current_user),
) -> CurrentUser:
    """Restrict an endpoint to admin role."""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user
