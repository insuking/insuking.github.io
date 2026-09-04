from fastapi import APIRouter, Response

from app.db.redis_client import check_redis
from app.db.session import check_database

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    """Liveness: process is up and serving requests."""
    return {"status": "live"}


@router.get("/ready")
async def ready(response: Response) -> dict[str, object]:
    """Readiness: dependencies (database, redis) are reachable."""
    db_ok = await check_database()
    redis_ok = await check_redis()
    is_ready = db_ok and redis_ok

    if not is_ready:
        response.status_code = 503

    return {
        "status": "ready" if is_ready else "not_ready",
        "checks": {
            "database": "ok" if db_ok else "fail",
            "redis": "ok" if redis_ok else "fail",
        },
    }
