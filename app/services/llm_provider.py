"""Pluggable LLM provider system.

Supports: ollama_local, openai, anthropic, custom (any OpenAI-compatible API).
Provider can be switched at runtime via the admin API or .env config.
"""

import httpx
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from app.config import Settings

logger = logging.getLogger(__name__)
settings = Settings()

_THINK_RE = re.compile(r'<think>.*?</think>', re.DOTALL)


class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    async def chat(self, messages: list, temperature: float = 0.0,
                   max_tokens: int = 512) -> str:
        """Non-streaming chat completion. Returns the assistant message content."""

    async def stream_chat(self, messages: list, temperature: float = 0.0,
                          max_tokens: int = 512) -> AsyncIterator[str]:
        """Streaming chat — yields text chunks. Default falls back to non-streaming."""
        yield await self.chat(messages, temperature, max_tokens)

    @abstractmethod
    async def health(self) -> bool:
        """Return True if the provider is reachable."""


class OllamaLocalProvider(LLMProvider):
    """Ollama running locally — uses /api/chat (native) or /v1/chat/completions (OpenAI compat)."""

    def __init__(self, base_url: str = None, model: str = None, timeout: float = None):
        self.base_url = (base_url or settings.OLLAMA_URL).rstrip("/")
        self.model = model or settings.OLLAMA_LLM_MODEL
        self.timeout = timeout or settings.LLM_TIMEOUT_SEC

    async def chat(self, messages: list, temperature: float = 0.0,
                   max_tokens: int = 512) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{self.base_url}/api/chat", json=payload,
                                  timeout=self.timeout)
        if r.status_code != 200:
            logger.error("Ollama local error %d: %s", r.status_code, r.text[:300])
            raise Exception(f"Ollama returned status {r.status_code}")
        data = r.json()
        content = data.get("message", {}).get("content", "").strip()
        content = _THINK_RE.sub("", content).strip()
        return content

    async def stream_chat(self, messages: list, temperature: float = 0.0,
                          max_tokens: int = 512) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", f"{self.base_url}/api/chat",
                                     json=payload, timeout=self.timeout) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield token
                    except json.JSONDecodeError:
                        continue

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient() as c:
                r = await c.get(f"{self.base_url}/api/tags", timeout=10)
                return r.status_code == 200
        except Exception:
            return False


class OpenAICompatProvider(LLMProvider):
    """Any OpenAI-compatible API (OpenAI, vLLM, LM Studio, text-gen-webui, etc.)."""

    def __init__(self, api_url: str = None, model: str = None,
                 api_key: str = None, timeout: float = None):
        self.api_url = api_url or settings.LLM_API_URL
        self.model = model or settings.LLM_MODEL_NAME
        self.api_key = api_key or ""
        self.timeout = timeout or settings.LLM_TIMEOUT_SEC

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def chat(self, messages: list, temperature: float = 0.0,
                   max_tokens: int = 512) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(self.api_url, json=payload,
                                  headers=self._headers(), timeout=self.timeout)
        if r.status_code != 200:
            logger.error("OpenAI-compat error %d: %s", r.status_code, r.text[:300])
            raise Exception(f"LLM API returned status {r.status_code}")
        data = r.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        content = _THINK_RE.sub("", content).strip()
        usage = data.get("usage", {})
        logger.debug("LLM tokens: prompt=%s completion=%s",
                     usage.get("prompt_tokens", "?"), usage.get("completion_tokens", "?"))
        return content

    async def stream_chat(self, messages: list, temperature: float = 0.0,
                          max_tokens: int = 512) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", self.api_url, json=payload,
                                     headers=self._headers(), timeout=self.timeout) as resp:
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    try:
                        chunk = json.loads(line)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            yield token
                    except json.JSONDecodeError:
                        continue

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient() as c:
                r = await c.post(self.api_url, json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                }, headers=self._headers(), timeout=15)
                return r.status_code == 200
        except Exception:
            return False


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API (Messages API)."""

    def __init__(self, api_key: str = "", model: str = "claude-sonnet-4-20250514",
                 timeout: float = None):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout or 120.0
        self.base_url = "https://api.anthropic.com/v1/messages"

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

    async def chat(self, messages: list, temperature: float = 0.0,
                   max_tokens: int = 512) -> str:
        system_text = ""
        user_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_text += m["content"] + "\n"
            else:
                user_msgs.append({"role": m["role"], "content": m["content"]})

        payload = {"model": self.model, "max_tokens": max_tokens,
                   "messages": user_msgs}
        if system_text.strip():
            payload["system"] = system_text.strip()

        async with httpx.AsyncClient() as client:
            r = await client.post(self.base_url, json=payload,
                                  headers=self._headers(), timeout=self.timeout)
        if r.status_code != 200:
            logger.error("Anthropic error %d: %s", r.status_code, r.text[:300])
            raise Exception(f"Anthropic API returned status {r.status_code}")
        data = r.json()
        blocks = data.get("content", [])
        return " ".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()

    async def stream_chat(self, messages: list, temperature: float = 0.0,
                          max_tokens: int = 512) -> AsyncIterator[str]:
        system_text = ""
        user_msgs = []
        for m in messages:
            if m["role"] == "system":
                system_text += m["content"] + "\n"
            else:
                user_msgs.append({"role": m["role"], "content": m["content"]})

        payload = {"model": self.model, "max_tokens": max_tokens,
                   "messages": user_msgs, "stream": True}
        if system_text.strip():
            payload["system"] = system_text.strip()

        async with httpx.AsyncClient() as client:
            async with client.stream("POST", self.base_url, json=payload,
                                     headers=self._headers(), timeout=self.timeout) as resp:
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                        if event.get("type") == "content_block_delta":
                            token = event.get("delta", {}).get("text", "")
                            if token:
                                yield token
                    except json.JSONDecodeError:
                        continue

    async def health(self) -> bool:
        return bool(self.api_key)


# ── Provider registry ──────────────────────────────────────

_active_provider: Optional[LLMProvider] = None
_provider_config: dict = {}

VALID_ROLES = ("classify", "sql_generate", "reasoning", "summarize",
               "nosql", "explain", "general")


def _build_provider(provider_type: str, **kwargs) -> LLMProvider:
    """Instantiate a provider by type string."""
    if provider_type == "ollama_local":
        return OllamaLocalProvider(
            base_url=kwargs.get("api_url") or kwargs.get("base_url"),
            model=kwargs.get("model"),
            timeout=kwargs.get("timeout"),
        )
    elif provider_type == "openai":
        return OpenAICompatProvider(
            api_url=kwargs.get("api_url", "https://api.openai.com/v1/chat/completions"),
            model=kwargs.get("model", "gpt-4o-mini"),
            api_key=kwargs.get("api_key", ""),
            timeout=kwargs.get("timeout"),
        )
    elif provider_type == "anthropic":
        return AnthropicProvider(
            api_key=kwargs.get("api_key", ""),
            model=kwargs.get("model", "claude-sonnet-4-20250514"),
            timeout=kwargs.get("timeout"),
        )
    elif provider_type == "custom":
        return OpenAICompatProvider(
            api_url=kwargs.get("api_url"),
            model=kwargs.get("model"),
            api_key=kwargs.get("api_key"),
            timeout=kwargs.get("timeout"),
        )
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")


def get_provider_config() -> dict:
    """Return current provider configuration."""
    return dict(_provider_config)


def set_provider(provider_type: str, **kwargs):
    """Switch the active (default) LLM provider at runtime.

    provider_type: ollama_local | openai | anthropic | custom
    kwargs: provider-specific overrides (api_url, model, api_key, etc.)
    """
    global _active_provider, _provider_config
    _provider_config = {"provider": provider_type, **kwargs}
    _active_provider = _build_provider(provider_type, **kwargs)
    logger.info("LLM provider set to %s (model=%s)", provider_type,
                kwargs.get("model") or "(default)")


def get_provider() -> LLMProvider:
    """Get the active (default) LLM provider, initializing from settings if needed."""
    global _active_provider
    if _active_provider is None:
        _init_default_provider()
    return _active_provider


def _init_default_provider():
    """Initialize provider from env / settings on first use."""
    provider_type = getattr(settings, "LLM_PROVIDER", "").strip().lower()

    if not provider_type:
        api_url = settings.LLM_API_URL
        if "localhost" in api_url and "11434" in api_url:
            provider_type = "ollama_local"
        elif "api.openai.com" in api_url:
            provider_type = "openai"
        elif "api.anthropic.com" in api_url:
            provider_type = "anthropic"
        else:
            provider_type = "custom"

    set_provider(
        provider_type,
        api_url=settings.LLM_API_URL,
        model=settings.LLM_MODEL_NAME,
        api_key=getattr(settings, "LLM_API_KEY", ""),
    )


# ── Task-based model router ───────────────────────────────

_role_overrides: dict[str, LLMProvider] = {}
_role_configs: dict[str, dict] = {}
_roles_initialized: bool = False


def _init_role_overrides():
    """Read per-role env vars (LLM_ROLE_<ROLE>_*) and build role-specific providers."""
    global _roles_initialized
    _roles_initialized = True
    for role in VALID_ROLES:
        prefix = f"LLM_ROLE_{role.upper()}"
        prov_type = getattr(settings, f"{prefix}_PROVIDER", "").strip().lower()
        if not prov_type:
            continue
        model = getattr(settings, f"{prefix}_MODEL", "") or None
        api_url = getattr(settings, f"{prefix}_API_URL", "") or None
        api_key = getattr(settings, f"{prefix}_API_KEY", "") or None
        try:
            _role_overrides[role] = _build_provider(
                prov_type, api_url=api_url, model=model, api_key=api_key,
            )
            _role_configs[role] = {
                "provider": prov_type, "model": model or "",
                "api_url": api_url or "", "api_key": api_key or "",
            }
            logger.info("Model role '%s' → %s (model=%s)", role, prov_type, model or "(default)")
        except Exception as exc:
            logger.warning("Failed to init role '%s': %s", role, exc)


def set_role_provider(role: str, provider_type: str, **kwargs):
    """Set or replace the provider for a specific task role at runtime."""
    if role not in VALID_ROLES:
        raise ValueError(f"Unknown role '{role}'. Valid: {VALID_ROLES}")
    _role_overrides[role] = _build_provider(provider_type, **kwargs)
    _role_configs[role] = {"provider": provider_type, **kwargs}
    logger.info("Model role '%s' updated → %s (model=%s)", role, provider_type,
                kwargs.get("model") or "(default)")


def clear_role_provider(role: str):
    """Remove role override so it falls back to the default provider."""
    _role_overrides.pop(role, None)
    _role_configs.pop(role, None)
    logger.info("Model role '%s' cleared — will use default provider", role)


def get_provider_for_role(role: str) -> LLMProvider:
    """Return the provider for a task role, falling back to the default provider."""
    if not _roles_initialized:
        _init_role_overrides()
    if role in _role_overrides:
        return _role_overrides[role]
    return get_provider()


def get_all_role_configs() -> dict:
    """Return the current per-role configuration map (for admin UI)."""
    if not _roles_initialized:
        _init_role_overrides()
    return {
        "default": get_provider_config(),
        "roles": {r: dict(c) for r, c in _role_configs.items()},
        "valid_roles": list(VALID_ROLES),
    }
