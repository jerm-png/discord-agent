from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from app.core.auth import verify_password, create_token

router = APIRouter()

class LoginRequest(BaseModel):
    password: str

@router.post("/login")
async def login(request: LoginRequest, response: Response):
    """
    Authenticate with the Drift password.
    Returns a JWT token set as an httpOnly cookie.
    """
    if not verify_password(request.password):
        raise HTTPException(
            status_code=401,
            detail="Invalid password"
        )

    token = create_token()

    response.set_cookie(
        key="drift_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=60 * 60 * 24,
    )

    return {"message": "Authenticated"}

@router.post("/logout")
async def logout(response: Response):
    """Clear the auth cookie."""
    response.delete_cookie("drift_token")
    return {"message": "Logged out"}
