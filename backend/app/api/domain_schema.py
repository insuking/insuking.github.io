from fastapi import APIRouter

from app.models import DOMAIN_MODELS

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/domain-schema")
async def domain_schema() -> dict[str, dict]:
    """JSON Schema for every P1 domain model, keyed by model name.

    This is the contract surface P1's acceptance criteria checks against:
    later phases (P2 persistence, P6 recommendation API, etc.) build their
    request/response shapes directly on these models rather than redefining
    them, so a break here is a break everywhere downstream.
    """
    return {model.__name__: model.model_json_schema() for model in DOMAIN_MODELS}
