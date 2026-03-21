#!/usr/bin/env python3
"""Extract model metadata from LiteLLM and build a bundled catalog.

Usage:
    python scripts/update_model_catalog.py              # full update
    python scripts/update_model_catalog.py --update-only # update existing keys only
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
CATALOG_PATH = Path(__file__).resolve().parent.parent / "src" / "hooty" / "data" / "model_catalog.json"

# Region prefixes that Bedrock attaches to model IDs
# e.g. "global.anthropic.claude-sonnet-4-6" -> "anthropic.claude-sonnet-4-6"
_BEDROCK_REGION_PREFIX_RE = re.compile(
    r"^(?:global|us|eu|ap|apac|au|me|il|mx|ca|jp)\."
)

# Legacy Bedrock model patterns to exclude from the catalog
_BEDROCK_EXCLUDE_RE = re.compile(
    r"^anthropic\.claude-(3|instant|v\d)"
)

# Azure AI Foundry: model families to include (case-insensitive)
_AZURE_AI_INCLUDE_RE = re.compile(r"claude|grok|Llama-[4-9]", re.IGNORECASE)

# Azure GPT models: match gpt-5 through gpt-9
# (excludes gpt-4, gpt-35-turbo which is Azure's GPT-3.5 naming)
_AZURE_GPT_RE = re.compile(r"gpt-[5-9]")


def _strip_bedrock_region(model_id: str) -> str:
    """Remove Bedrock region prefix from a model ID."""
    return _BEDROCK_REGION_PREFIX_RE.sub("", model_id)


def _fetch_litellm() -> dict:
    """Download the LiteLLM model catalog."""
    print(f"Fetching {LITELLM_URL} ...")
    with urllib.request.urlopen(LITELLM_URL, timeout=30) as resp:
        return json.loads(resp.read())


_CAPABILITY_FIELDS = (
    "supports_vision",
    "supports_reasoning",
    "supports_function_calling",
    "supports_response_schema",
)

# Anthropic direct API: match "claude-*" top-level keys (not prefixed)
_ANTHROPIC_DIRECT_RE = re.compile(r"^claude-")

# Exclude legacy Anthropic direct API models
_ANTHROPIC_DIRECT_EXCLUDE_RE = re.compile(
    r"^claude-(3|instant|v\d|2)"
)


def _build_entry(info: dict) -> dict:
    """Build a catalog entry dict from a LiteLLM info dict.

    Includes max_input_tokens and capability flags (True only).
    """
    entry: dict = {"max_input_tokens": info["max_input_tokens"]}
    for field in _CAPABILITY_FIELDS:
        if info.get(field) is True:
            entry[field] = True
    return entry


def _should_replace(existing: dict | None, new_entry: dict) -> bool:
    """Check if new_entry should replace existing (larger max_input_tokens wins)."""
    if existing is None:
        return True
    return new_entry["max_input_tokens"] > existing["max_input_tokens"]


def _extract_models(data: dict) -> dict[str, dict[str, dict]]:
    """Extract models from LiteLLM data for all supported providers.

    Returns {"anthropic": {...}, "bedrock": {...}, "azure": {...}, "azure_openai": {...}, "openai": {...}}.

    - anthropic: Direct Anthropic API models (claude-* top-level keys)
    - azure: Azure AI Foundry models (Claude/Grok/Llama 4+ via azure_ai/ keys)
    - azure_openai: Azure OpenAI Service models (GPT via azure/ keys)
    - openai: Direct OpenAI API models (gpt-5+ top-level keys)
    """
    bedrock: dict[str, dict] = {}
    azure: dict[str, dict] = {}
    azure_openai: dict[str, dict] = {}
    openai_direct: dict[str, dict] = {}
    anthropic: dict[str, dict] = {}

    for key, info in data.items():
        if not isinstance(info, dict):
            continue
        max_input = info.get("max_input_tokens")
        if max_input is None:
            continue

        entry = _build_entry(info)

        # OpenAI direct API: top-level "gpt-*" keys (no "/" prefix), GPT-5+
        if key.startswith("gpt-") and "/" not in key and _AZURE_GPT_RE.match(key):
            if _should_replace(openai_direct.get(key), entry):
                openai_direct[key] = entry

        # Anthropic direct API: top-level "claude-*" keys (no "/" prefix)
        if _ANTHROPIC_DIRECT_RE.match(key) and "/" not in key:
            if _ANTHROPIC_DIRECT_EXCLUDE_RE.match(key):
                continue
            if _should_replace(anthropic.get(key), entry):
                anthropic[key] = entry

        # Bedrock: keys containing "anthropic.claude" but NOT LiteLLM
        # routing keys (which contain "/")
        if "anthropic.claude" in key and "/" not in key:
            # Strip region prefix to get the base model ID
            base_id = _strip_bedrock_region(key)
            # Skip legacy models (claude-3*, claude-instant*, claude-v\d*)
            if _BEDROCK_EXCLUDE_RE.match(base_id):
                continue
            # Keep the largest max_input_tokens seen for this base_id
            if _should_replace(bedrock.get(base_id), entry):
                bedrock[base_id] = entry

        # Azure AI Foundry: "azure_ai/" keys matching included model families
        elif key.startswith("azure_ai/") and _AZURE_AI_INCLUDE_RE.search(key):
            parts = key.split("/")
            model_name = parts[-1]
            if _should_replace(azure.get(model_name), entry):
                azure[model_name] = entry

        # Azure OpenAI Service: "azure/" keys containing GPT-5+
        elif key.startswith("azure/") and _AZURE_GPT_RE.search(key):
            # Strip provider/region prefix: "azure/eu/gpt-5..." -> "gpt-5..."
            parts = key.split("/")
            model_name = parts[-1]
            if _should_replace(azure_openai.get(model_name), entry):
                azure_openai[model_name] = entry

    return {
        "anthropic": anthropic,
        "bedrock": bedrock,
        "azure": azure,
        "azure_openai": azure_openai,
        "openai": openai_direct,
    }


def _build_catalog(
    extracted: dict[str, dict[str, dict]],
    existing: dict | None,
    update_only: bool,
) -> dict:
    """Build the final catalog dict.

    Preserves the key order of the existing catalog so that
    manually-maintained sections (e.g. ollama) stay in place.
    """
    _LITELLM_PROVIDERS = {"anthropic", "bedrock", "azure", "azure_openai", "openai"}

    updated_providers: dict[str, dict] = {}
    for provider in _LITELLM_PROVIDERS:
        new_models = extracted.get(provider, {})
        old_models = (existing or {}).get(provider, {})

        if update_only and old_models:
            merged = {}
            for model_id, old_val in old_models.items():
                merged[model_id] = new_models.get(model_id, old_val)
        else:
            merged = {**old_models, **new_models}
            merged = dict(sorted(merged.items()))
        updated_providers[provider] = merged

    # Rebuild catalog preserving the existing key order
    catalog: dict = {
        "_metadata": {
            "source": "litellm/model_prices_and_context_window.json",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    if existing:
        for key, value in existing.items():
            if key.startswith("_"):
                continue
            if key in _LITELLM_PROVIDERS:
                catalog[key] = updated_providers.pop(key)
            else:
                # Preserve manually-maintained sections as-is
                catalog[key] = value

    # Append any LiteLLM providers not in the existing catalog
    for provider, models in updated_providers.items():
        catalog[provider] = models

    return catalog


def _diff_catalog(existing: dict | None, new_catalog: dict) -> dict[str, dict]:
    """Compare existing and new catalog, return per-provider diff summary."""
    result: dict[str, dict] = {}
    # Collect all provider keys (skip "_" prefixed metadata keys)
    all_keys = {
        k for k in list(existing or {}) + list(new_catalog)
        if not k.startswith("_")
    }
    for provider in sorted(all_keys):
        old_models = (existing or {}).get(provider, {})
        new_models = new_catalog.get(provider, {})
        old_ids = set(old_models)
        new_ids = set(new_models)

        added = sorted(new_ids - old_ids)
        removed = sorted(old_ids - new_ids)
        changed: list[str] = []
        for mid in sorted(old_ids & new_ids):
            if old_models[mid] != new_models[mid]:
                changed.append(mid)

        result[provider] = {
            "added": added,
            "removed": removed,
            "changed": changed,
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Update the bundled model catalog.")
    parser.add_argument(
        "--update-only",
        action="store_true",
        help="Only update existing keys (preserve manual edits)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing the catalog file",
    )
    args = parser.parse_args()

    # Load existing catalog if present
    existing = None
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH) as f:
            existing = json.load(f)
        print(f"Loaded existing catalog from {CATALOG_PATH}")

    data = _fetch_litellm()
    extracted = _extract_models(data)

    print(f"  Anthropic direct found:    {len(extracted['anthropic'])}")
    print(f"  Bedrock models found:      {len(extracted['bedrock'])}")
    print(f"  Azure AI Foundry found:    {len(extracted['azure'])}")
    print(f"  Azure OpenAI found:        {len(extracted['azure_openai'])}")
    print(f"  OpenAI direct found:       {len(extracted['openai'])}")

    catalog = _build_catalog(extracted, existing, args.update_only)

    if args.dry_run:
        diff = _diff_catalog(existing, catalog)
        has_changes = False
        for provider, summary in diff.items():
            added = summary["added"]
            removed = summary["removed"]
            changed = summary["changed"]
            if not (added or removed or changed):
                continue
            has_changes = True
            print(f"\n[{provider}] +{len(added)} added, -{len(removed)} removed, ~{len(changed)} changed")
            for mid in added:
                print(f"  + {mid}")
            for mid in removed:
                print(f"  - {mid}")
            for mid in changed:
                print(f"  ~ {mid}")
        if not has_changes:
            print("\nNo changes detected.")
        print("\n(dry run — no files written)")
    else:
        CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CATALOG_PATH, "w") as f:
            json.dump(catalog, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Wrote {CATALOG_PATH}")


if __name__ == "__main__":
    main()
