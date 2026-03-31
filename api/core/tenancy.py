import urllib.parse
from typing import Optional

from fastapi import HTTPException, status

from api.core.database import _supabase_get


async def _resolve_operator_id(operator_slug: Optional[str]) -> str:
    if not operator_slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="operator query parameter is required",
        )
    operators = await _supabase_get(
        f"operators?slug=eq.{urllib.parse.quote(operator_slug, safe='')}&is_active=eq.true&select=id"
    )
    if not operators:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Operator '{operator_slug}' not found",
        )
    return operators[0]["id"]


def _op_filter(operator_id: str) -> str:
    return f"operator_id=eq.{operator_id}"
