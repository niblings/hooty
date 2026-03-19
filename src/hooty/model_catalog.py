"""Bundled model catalog lookup and context-limit resolution."""

from __future__ import annotations

import json
import re
from pathlib import Path

from hooty.config import AppConfig

_model_catalog: dict | None = None

# Region prefixes that Bedrock attaches to model IDs
_BEDROCK_REGION_PREFIX_RE = re.compile(
    r"^(?:global|us|eu|ap|apac|au|me|il|mx|ca|jp)\."
)


def _load_model_catalog() -> dict:
    global _model_catalog
    if _model_catalog is None:
        catalog_path = Path(__file__).parent / "data" / "model_catalog.json"
        if catalog_path.exists():
            with open(catalog_path, encoding="utf-8") as f:
                _model_catalog = json.load(f)
        else:
            _model_catalog = {}
    return _model_catalog


def _resolve_entry(value: int | dict) -> dict:
    """Normalize a catalog entry to dict form.

    Handles backward compatibility: int values are treated as
    {"max_input_tokens": int}.
    """
    if isinstance(value, int):
        return {"max_input_tokens": value}
    return value


def _find_entry(model_id: str, provider: str) -> dict | None:
    """Find the raw catalog entry for a model (exact or Bedrock region-stripped)."""
    catalog = _load_model_catalog()
    provider_models = catalog.get(provider, {})

    # Exact match
    if model_id in provider_models:
        return _resolve_entry(provider_models[model_id])

    # Bedrock: try without region prefix
    if provider == "bedrock":
        base_id = _BEDROCK_REGION_PREFIX_RE.sub("", model_id)
        if base_id != model_id and base_id in provider_models:
            return _resolve_entry(provider_models[base_id])

    return None


def _lookup_model_catalog(model_id: str, provider: str) -> int | None:
    """Look up max_input_tokens from the bundled catalog.

    For Bedrock, tries exact match first, then strips the region prefix
    (e.g. "global.", "us.", "jp.") and retries.
    """
    entry = _find_entry(model_id, provider)
    if entry is not None:
        return entry.get("max_input_tokens")
    return None


def get_model_capabilities(model_id: str, provider: str) -> dict:
    """Return capability flags for a model from the bundled catalog.

    Returns a dict with boolean capability flags, e.g.:
        {"supports_reasoning": True, "supports_function_calling": True}

    Unknown models return an empty dict.
    """
    entry = _find_entry(model_id, provider)
    if entry is None:
        return {}
    return {
        k: v
        for k, v in entry.items()
        if k != "max_input_tokens"
    }


def get_context_limit(config: AppConfig) -> int:
    """Return max_input_tokens for the current model.

    Resolution order:
    1. config.yaml providers.<provider>.max_input_tokens
    2. Bundled model catalog
    3. Fallback default (200,000)
    """
    if config.provider.value == "anthropic":
        model_id = config.anthropic.model_id
        if config.anthropic.max_input_tokens:
            return config.anthropic.max_input_tokens
    elif config.provider.value == "bedrock":
        model_id = config.bedrock.model_id
        if config.bedrock.max_input_tokens:
            return config.bedrock.max_input_tokens
    elif config.provider.value == "azure_openai":
        model_id = config.azure_openai.model_id
        if config.azure_openai.max_input_tokens:
            return config.azure_openai.max_input_tokens
    elif config.provider.value == "ollama":
        model_id = config.ollama.model_id
        if config.ollama.max_input_tokens:
            return config.ollama.max_input_tokens
    else:
        model_id = config.azure.model_id
        if config.azure.max_input_tokens:
            return config.azure.max_input_tokens

    limit = _lookup_model_catalog(model_id, config.provider.value)
    if limit is not None:
        return limit

    if config.provider.value == "ollama":
        return 8_192  # Conservative default for local models
    return 200_000
