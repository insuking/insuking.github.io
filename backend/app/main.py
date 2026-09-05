from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.domain_schema import router as domain_schema_router
from app.api.health import router as health_router
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(domain_schema_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "environment": settings.environment}
