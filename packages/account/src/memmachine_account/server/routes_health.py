"""`GET /account/v1/health` - unauthenticated liveness check (DESIGN.md §13)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["System"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Report that the gateway process is up (separate from MemMachine's own /health)."""
    return {"status": "healthy"}
