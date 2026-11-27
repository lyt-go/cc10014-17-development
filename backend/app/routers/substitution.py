"""材料替代批量采纳专用路由。

通用列表/登记/详情仍走 resource.py，这里只承载替代业务的领域动作：
批量采纳、领用、审核拒绝、申请人修订和方案审批资格视图。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.schemas import (
    BatchAdoptPayload,
    RejectPayload,
    RequisitionPayload,
    RevisePayload,
)
from app.services.material_substitution import MaterialSubstitutionService

router = APIRouter(prefix="/api/material-substitution", tags=["材料替代采纳"])

service = MaterialSubstitutionService()


def _error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/plans/{plan_id}/batch-adopt")
def batch_adopt(plan_id: int, payload: BatchAdoptPayload) -> dict[str, Any]:
    """工程师从材料核验中批量采纳同一方案的多条替代建议。"""
    try:
        receipt = service.batch_adopt(plan_id, payload.substitution_ids, payload.applicant)
    except ValueError as exc:
        raise _error(exc) from exc
    return {"ok": True, "message": "批量采纳处理完成", "receipt": receipt}


@router.get("/plans/{plan_id}/eligibility")
def plan_eligibility(plan_id: int) -> dict[str, Any]:
    """方案审批入口：逐行说明替换资格、工艺变更记录与领用限制。"""
    try:
        return service.plan_eligibility(plan_id)
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/{substitution_id}/requisition")
def requisition(substitution_id: int, payload: RequisitionPayload) -> dict[str, Any]:
    """施工方领用替代材料；待复核/被拒绝/核验失效的材料一律拒绝。"""
    try:
        record = service.requisition(substitution_id, payload.receiver, payload.quantity)
    except ValueError as exc:
        raise _error(exc) from exc
    return {"ok": True, "message": "领用登记成功", "entry": record}


@router.post("/{substitution_id}/reject")
def reject(substitution_id: int, payload: RejectPayload) -> dict[str, Any]:
    """审核时依据工艺变更记录拒绝某条清单行替换。"""
    try:
        entry = service.reject(substitution_id, payload.reason)
    except ValueError as exc:
        raise _error(exc) from exc
    return {"ok": True, "message": "该清单行替换已拒绝", "entry": entry}


@router.post("/{substitution_id}/revise")
def revise(substitution_id: int, payload: RevisePayload) -> dict[str, Any]:
    """申请人修订待复核/已拒绝的替代建议，回到待采纳后可再次批量采纳。"""
    try:
        entry = service.revise(substitution_id, payload.values)
    except ValueError as exc:
        raise _error(exc) from exc
    return {"ok": True, "message": "替代建议已修订，可重新提交", "entry": entry}
