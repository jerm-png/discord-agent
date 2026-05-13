from fastapi import APIRouter, Depends
from app.core.auth import CurrentUser, get_current_user
from app.core.config import WORKSPACES

router = APIRouter()


@router.get("")
async def list_workspaces(
    user: CurrentUser = Depends(get_current_user),
):
    """
    Workspace list visible to the current user.

    - parker (role=user): only the "parker" workspace.
    - drift-owner (role=admin): every workspace EXCEPT parker. Admin
      reviews Parker's activity through the content-flag system, not by
      browsing his workspace directly.
    - Any other user: workspaces with no `user_restricted` field set
      (defensive — keeps Parker.exe hidden by default).
    """
    user_id = user["user_id"]
    visible = []
    for slug, config in WORKSPACES.items():
        restricted = config.get("user_restricted")
        if restricted is not None:
            if user_id != restricted:
                continue
        else:
            if user_id == "parker":
                continue
        visible.append({
            "slug": slug,
            "label": config["label"],
            "memory_mode": config["memory_mode"],
            "isolated": config.get("isolated", False),
            "entity_memory": config.get("entity_memory", False),
        })
    return {"workspaces": visible}
