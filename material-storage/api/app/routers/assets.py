"""assets router stub — Phase B-1 placeholder,实际 endpoint Phase B-2+ 实施。"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/_stub")
async def stub() -> dict[str, str]:
    return {"router": "assets", "status": "stub - not implemented yet"}
