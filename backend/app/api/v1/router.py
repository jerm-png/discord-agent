from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    status,
    threads,
    workspaces,
)

router = APIRouter()

router.include_router(
    auth.router,
    prefix="/auth",
    tags=["auth"],
)
router.include_router(
    status.router,
    prefix="",
    tags=["status"],
)
router.include_router(
    workspaces.router,
    prefix="/workspaces",
    tags=["workspaces"],
)
router.include_router(
    threads.router,
    tags=["threads"],
)
