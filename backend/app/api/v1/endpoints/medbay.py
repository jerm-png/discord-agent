from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.auth import CurrentUser, require_admin
from app.db.memory_manager import (
    medbay_list_protocol,
    medbay_add_protocol,
    medbay_update_protocol_dose,
    medbay_stop_protocol,
    medbay_list_labs,
    medbay_latest_labs,
    medbay_add_lab_result,
    medbay_list_followups,
    medbay_add_followup,
    medbay_complete_followup,
    medbay_list_changes,
    medbay_log_change,
)

router = APIRouter()

# This module IS the health workspace's data plane — every row written
# or read through here lives under workspace="health". The constant is
# referenced explicitly on every helper call so the gate is visible at
# the read/write site, not just inherited from the default.
WORKSPACE = "health"


# ── Request bodies ────────────────────────────────────────────
class ProtocolCreate(BaseModel):
    supplement_name: str
    dose: str | None = None
    frequency: str | None = None
    reason: str | None = None
    target_marker: str | None = None


class LabResultCreate(BaseModel):
    marker_name: str
    value: float
    unit: str | None = None
    reference_low: float | None = None
    reference_high: float | None = None
    test_date: str | None = None


class FollowupCreate(BaseModel):
    description: str
    reason: str | None = None
    suggested_date: str | None = None


class ChangeCreate(BaseModel):
    change_type: str  # added | dose_change | stopped
    item_name: str
    old_value: str | None = None
    new_value: str | None = None
    reason: str | None = None


# ── Protocol ──────────────────────────────────────────────────
@router.get("/protocol")
async def list_protocol(
    include_stopped: bool = Query(False),
    user: CurrentUser = Depends(require_admin),
):
    """Active (and optionally stopped) protocol items for the admin user."""
    if include_stopped:
        return {
            "protocol": medbay_list_protocol(
                user["user_id"], status=None, workspace=WORKSPACE,
            )
        }
    return {
        "protocol": medbay_list_protocol(
            user["user_id"], status="active", workspace=WORKSPACE,
        )
    }


@router.post("/protocol")
async def create_protocol(
    body: ProtocolCreate,
    user: CurrentUser = Depends(require_admin),
):
    new_id = medbay_add_protocol(
        user_id=user["user_id"],
        supplement_name=body.supplement_name,
        dose=body.dose,
        frequency=body.frequency,
        reason=body.reason,
        target_marker=body.target_marker,
        workspace=WORKSPACE,
    )
    return {"id": new_id}


# ── Labs ──────────────────────────────────────────────────────
@router.get("/labs")
async def list_labs(
    marker: str | None = Query(None),
    user: CurrentUser = Depends(require_admin),
):
    return {
        "labs": medbay_list_labs(
            user["user_id"], marker=marker, workspace=WORKSPACE,
        )
    }


@router.get("/labs/latest")
async def list_latest_labs(
    user: CurrentUser = Depends(require_admin),
):
    return {
        "labs": medbay_latest_labs(user["user_id"], workspace=WORKSPACE),
    }


@router.post("/labs")
async def create_lab(
    body: LabResultCreate,
    user: CurrentUser = Depends(require_admin),
):
    new_id = medbay_add_lab_result(
        user_id=user["user_id"],
        marker_name=body.marker_name,
        value=body.value,
        unit=body.unit,
        reference_low=body.reference_low,
        reference_high=body.reference_high,
        test_date=body.test_date,
        workspace=WORKSPACE,
    )
    return {"id": new_id}


# ── Follow-ups ────────────────────────────────────────────────
@router.get("/followups")
async def list_followups(
    include_completed: bool = Query(False),
    user: CurrentUser = Depends(require_admin),
):
    return {
        "followups": medbay_list_followups(
            user["user_id"],
            include_completed=include_completed,
            workspace=WORKSPACE,
        )
    }


@router.post("/followups")
async def create_followup(
    body: FollowupCreate,
    user: CurrentUser = Depends(require_admin),
):
    new_id = medbay_add_followup(
        user_id=user["user_id"],
        description=body.description,
        reason=body.reason,
        suggested_date=body.suggested_date,
        workspace=WORKSPACE,
    )
    return {"id": new_id}


@router.patch("/followups/{followup_id}/complete")
async def complete_followup(
    followup_id: int,
    user: CurrentUser = Depends(require_admin),
):
    ok = medbay_complete_followup(
        user["user_id"], followup_id, workspace=WORKSPACE,
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Follow-up not found or already completed.",
        )
    return {"status": "ok", "id": followup_id}


# ── Changes log ───────────────────────────────────────────────
@router.get("/changes")
async def list_changes(
    limit: int = Query(100, ge=1, le=500),
    user: CurrentUser = Depends(require_admin),
):
    return {
        "changes": medbay_list_changes(
            user["user_id"], limit=limit, workspace=WORKSPACE,
        )
    }


@router.post("/changes")
async def create_change(
    body: ChangeCreate,
    user: CurrentUser = Depends(require_admin),
):
    new_id = medbay_log_change(
        user_id=user["user_id"],
        change_type=body.change_type,
        item_name=body.item_name,
        old_value=body.old_value,
        new_value=body.new_value,
        reason=body.reason,
        workspace=WORKSPACE,
    )
    return {"id": new_id}
