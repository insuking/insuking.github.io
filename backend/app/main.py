from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.approvals import router as approvals_router
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.domain_schema import router as domain_schema_router
from app.api.health import router as health_router
from app.api.positions import router as positions_router
from app.api.stock_radar import router as stock_radar_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    # Local dev origins are always allowed; `CORS_EXTRA_ORIGINS` (P43) adds
    # the public origin the frontend is reached at once one exists (e.g. a
    # Cloudflare Tunnel hostname for the Android TWA) - see
    # docs/ANDROID_APP.md.
    allow_origins=["http://localhost:5173", "http://localhost:4173", *settings.cors_extra_origins_list],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(domain_schema_router)
app.include_router(approvals_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(positions_router)
app.include_router(stock_radar_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "environment": settings.environment}
