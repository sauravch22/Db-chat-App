"""LLM provider management API — get/set the active LLM provider at runtime,
plus per-task model routing configuration."""

import logging
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from app.api.deps import get_current_user, has_any_onboard
from app.services.llm_provider import (
    get_provider, get_provider_config, set_provider,
    get_all_role_configs, set_role_provider, clear_role_provider,
    get_provider_for_role, VALID_ROLES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["LLM Settings"])

SUPPORTED_PROVIDERS = [
    {"id": "ollama_local", "name": "Ollama (Local)", "needs_key": False,
     "default_url": "http://localhost:11434", "default_model": "mistral"},
    {"id": "openai", "name": "OpenAI", "needs_key": True,
     "default_url": "https://api.openai.com/v1/chat/completions", "default_model": "gpt-4o-mini"},
    {"id": "anthropic", "name": "Anthropic Claude", "needs_key": True,
     "default_url": "https://api.anthropic.com/v1/messages", "default_model": "claude-sonnet-4-20250514"},
    {"id": "custom", "name": "Custom (OpenAI-compatible)", "needs_key": False,
     "default_url": "", "default_model": ""},
]

ROLE_DESCRIPTIONS = {
    "classify": "Intent classification & table selection — fast, cheap model preferred",
    "sql_generate": "SQL query generation — code-optimized model preferred",
    "reasoning": "Query planning & reasoning step — deep-thinking model preferred",
    "summarize": "Data insight summarization — general model preferred",
    "nosql": "NoSQL query generation (MongoDB, Cypher, etc.)",
    "explain": "SQL explanation in plain English",
    "general": "Fallback for welcome messages, misc tasks",
}


@router.get("/providers")
async def list_providers(user: dict = Depends(get_current_user)):
    """Return list of supported LLM providers and the current active one."""
    cfg = get_provider_config()
    return {
        "active": cfg.get("provider", "ollama_local"),
        "active_model": cfg.get("model", ""),
        "active_url": cfg.get("api_url", ""),
        "providers": SUPPORTED_PROVIDERS,
    }


class SetProviderRequest(BaseModel):
    provider: str
    api_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


@router.post("/provider")
async def change_provider(req: SetProviderRequest, user: dict = Depends(get_current_user)):
    """Switch the active LLM provider at runtime (admin only)."""
    if not has_any_onboard(user):
        raise HTTPException(403, "Admin permission required to change LLM provider")
    valid_ids = {p["id"] for p in SUPPORTED_PROVIDERS}
    if req.provider not in valid_ids:
        raise HTTPException(400, f"Unknown provider '{req.provider}'. Supported: {valid_ids}")

    try:
        kwargs = {}
        if req.api_url:
            kwargs["api_url"] = req.api_url
        if req.model:
            kwargs["model"] = req.model
        if req.api_key:
            kwargs["api_key"] = req.api_key
        set_provider(req.provider, **kwargs)
        return {"status": "ok", "provider": req.provider, "model": req.model or "(default)"}
    except Exception as e:
        logger.error("Failed to set LLM provider: %s", e)
        raise HTTPException(500, str(e))


@router.get("/health")
async def llm_health(user: dict = Depends(get_current_user)):
    """Quick health-check of the active LLM provider."""
    provider = get_provider()
    ok = await provider.health()
    cfg = get_provider_config()
    return {"healthy": ok, "provider": cfg.get("provider", "unknown"),
            "model": cfg.get("model", "")}


# ── Model Routing API ──────────────────────────────────────

@router.get("/model-routing")
async def get_model_routing(user: dict = Depends(get_current_user)):
    """Return the full model routing configuration (default + per-role overrides)."""
    data = get_all_role_configs()
    data["providers"] = SUPPORTED_PROVIDERS
    data["role_descriptions"] = ROLE_DESCRIPTIONS
    return data


class SetRoleRequest(BaseModel):
    role: str
    provider: str
    model: Optional[str] = None
    api_url: Optional[str] = None
    api_key: Optional[str] = None


@router.post("/model-routing")
async def set_model_routing(req: SetRoleRequest, user: dict = Depends(get_current_user)):
    """Set or update the LLM provider for a specific task role (admin only)."""
    if not has_any_onboard(user):
        raise HTTPException(403, "Admin permission required to change model routing")
    if req.role not in VALID_ROLES:
        raise HTTPException(400, f"Unknown role '{req.role}'. Valid: {list(VALID_ROLES)}")
    valid_ids = {p["id"] for p in SUPPORTED_PROVIDERS}
    if req.provider not in valid_ids:
        raise HTTPException(400, f"Unknown provider '{req.provider}'. Supported: {valid_ids}")

    try:
        kwargs = {}
        if req.model:
            kwargs["model"] = req.model
        if req.api_url:
            kwargs["api_url"] = req.api_url
        if req.api_key:
            kwargs["api_key"] = req.api_key
        set_role_provider(req.role, req.provider, **kwargs)
        return {"status": "ok", "role": req.role, "provider": req.provider,
                "model": req.model or "(default)"}
    except Exception as e:
        logger.error("Failed to set role provider: %s", e)
        raise HTTPException(500, str(e))


class ClearRoleRequest(BaseModel):
    role: str


@router.delete("/model-routing")
async def clear_model_routing(req: ClearRoleRequest, user: dict = Depends(get_current_user)):
    """Remove a role override so it falls back to the default provider (admin only)."""
    if not has_any_onboard(user):
        raise HTTPException(403, "Admin permission required")
    if req.role not in VALID_ROLES:
        raise HTTPException(400, f"Unknown role '{req.role}'. Valid: {list(VALID_ROLES)}")
    clear_role_provider(req.role)
    return {"status": "ok", "role": req.role, "message": "Cleared — will use default provider"}


@router.get("/model-routing/health/{role}")
async def role_health(role: str, user: dict = Depends(get_current_user)):
    """Health check for a specific role's provider."""
    if role not in VALID_ROLES:
        raise HTTPException(400, f"Unknown role '{role}'")
    provider = get_provider_for_role(role)
    ok = await provider.health()
    return {"role": role, "healthy": ok, "provider_type": type(provider).__name__}
