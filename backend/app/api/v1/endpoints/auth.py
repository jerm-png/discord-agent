from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from app.core.auth import (
    CurrentUser,
    create_token,
    get_current_user,
    verify_password,
)

router = APIRouter()


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def login(request: LoginRequest, response: Response):
    """
    Authenticate against either DRIFT_PASSWORD (admin) or PARKER_PASSWORD
    (user). Returns the assigned user_id + role and sets the JWT cookie.
    """
    user = verify_password(request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid password")

    token = create_token(user["user_id"], user["role"])
    response.set_cookie(
        key="drift_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=86400,
    )

    return {
        "message": "Authenticated",
        "user_id": user["user_id"],
        "role": user["role"],
    }


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    """Return the current authenticated user info (driven by the cookie)."""
    return user


@router.post("/logout")
async def logout(response: Response):
    """Clear the auth cookie."""
    response.delete_cookie("drift_token")
    return {"message": "Logged out"}
