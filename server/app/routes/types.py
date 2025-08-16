# server/app/routes/type.py 片段示例
from fastapi import APIRouter, Query, HTTPException
from ..services.types_service import (
    get_chart, get_effects, get_card, get_matrix, list_types
)

router = APIRouter()

@router.get("/types/list")
def types_list():
    return {"types": list_types()}

@router.get("/types/chart")
def types_chart():
    return get_chart()

@router.get("/types/effects")
def types_effects(
    vs: str = Query(..., description="对面属性"),
    perspective: str = Query("attack", pattern="^(attack|defense)$"),
    sort: str | None = Query(None, pattern="^(asc|desc)$")
):
    return get_effects(vs, perspective, sort)

@router.get("/types/card")
def types_card(self_type: str = Query(..., description="我方属性")):
    try:
        return get_card(self_type)
    except KeyError as e:
        raise HTTPException(404, str(e))

@router.get("/types/matrix")
def types_matrix(perspective: str = Query("attack", pattern="^(attack|defense)$")):
    return get_matrix(perspective)