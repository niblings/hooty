"""Tests for model_catalog module."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from hooty.model_catalog import (
    _find_entry,
    _load_model_catalog,
    _lookup_model_catalog,
    _resolve_entry,
    get_model_capabilities,
)


class TestResolveEntry:
    """Test backward-compatible entry normalization."""

    def test_int_value(self):
        assert _resolve_entry(200000) == {"max_input_tokens": 200000}

    def test_dict_value(self):
        entry = {"max_input_tokens": 200000, "supports_reasoning": True}
        assert _resolve_entry(entry) is entry

    def test_dict_without_capabilities(self):
        entry = {"max_input_tokens": 131072}
        assert _resolve_entry(entry) is entry


class TestFindEntry:
    """Test _find_entry with both old (int) and new (dict) catalog formats."""

    _CATALOG = {
        "anthropic": {
            "claude-sonnet-4-6": {
                "max_input_tokens": 200000,
                "supports_reasoning": True,
            },
        },
        "bedrock": {
            "anthropic.claude-sonnet-4-6": {
                "max_input_tokens": 200000,
                "supports_reasoning": True,
            },
        },
        "ollama": {
            "gemma2": 8192,
        },
    }

    @pytest.fixture(autouse=True)
    def _patch_catalog(self):
        with patch("hooty.model_catalog._load_model_catalog", return_value=self._CATALOG):
            yield

    def test_exact_match_dict(self):
        entry = _find_entry("claude-sonnet-4-6", "anthropic")
        assert entry == {"max_input_tokens": 200000, "supports_reasoning": True}

    def test_exact_match_int_backward_compat(self):
        entry = _find_entry("gemma2", "ollama")
        assert entry == {"max_input_tokens": 8192}

    def test_bedrock_region_strip(self):
        entry = _find_entry("us.anthropic.claude-sonnet-4-6", "bedrock")
        assert entry is not None
        assert entry["max_input_tokens"] == 200000

    def test_not_found(self):
        assert _find_entry("nonexistent", "anthropic") is None

    def test_unknown_provider(self):
        assert _find_entry("anything", "unknown_provider") is None


class TestLookupModelCatalog:
    """Test _lookup_model_catalog returns int for backward compatibility."""

    _CATALOG = {
        "anthropic": {
            "claude-sonnet-4-6": {
                "max_input_tokens": 200000,
                "supports_reasoning": True,
            },
        },
        "ollama": {
            "gemma2": 8192,
        },
    }

    @pytest.fixture(autouse=True)
    def _patch_catalog(self):
        with patch("hooty.model_catalog._load_model_catalog", return_value=self._CATALOG):
            yield

    def test_returns_int_from_dict_entry(self):
        assert _lookup_model_catalog("claude-sonnet-4-6", "anthropic") == 200000

    def test_returns_int_from_int_entry(self):
        assert _lookup_model_catalog("gemma2", "ollama") == 8192

    def test_returns_none_for_missing(self):
        assert _lookup_model_catalog("nonexistent", "anthropic") is None


class TestGetModelCapabilities:
    """Test get_model_capabilities returns capability flags."""

    _CATALOG = {
        "anthropic": {
            "claude-sonnet-4-6": {
                "max_input_tokens": 200000,
                "supports_vision": True,
                "supports_reasoning": True,
                "supports_function_calling": True,
                "supports_response_schema": True,
            },
            "claude-haiku-4-5": {
                "max_input_tokens": 200000,
                "supports_function_calling": True,
            },
        },
        "azure": {
            "grok-4-fast-reasoning": {
                "max_input_tokens": 131072,
                "supports_reasoning": True,
                "supports_function_calling": True,
            },
        },
        "ollama": {
            "gemma2": 8192,
        },
    }

    @pytest.fixture(autouse=True)
    def _patch_catalog(self):
        with patch("hooty.model_catalog._load_model_catalog", return_value=self._CATALOG):
            yield

    def test_full_capabilities(self):
        caps = get_model_capabilities("claude-sonnet-4-6", "anthropic")
        assert caps == {
            "supports_vision": True,
            "supports_reasoning": True,
            "supports_function_calling": True,
            "supports_response_schema": True,
        }

    def test_partial_capabilities(self):
        caps = get_model_capabilities("claude-haiku-4-5", "anthropic")
        assert caps == {"supports_function_calling": True}
        assert "supports_reasoning" not in caps

    def test_grok_reasoning(self):
        caps = get_model_capabilities("grok-4-fast-reasoning", "azure")
        assert caps["supports_reasoning"] is True

    def test_int_entry_returns_empty(self):
        caps = get_model_capabilities("gemma2", "ollama")
        assert caps == {}

    def test_unknown_model_returns_empty(self):
        caps = get_model_capabilities("nonexistent", "anthropic")
        assert caps == {}

    def test_excludes_max_input_tokens(self):
        caps = get_model_capabilities("claude-sonnet-4-6", "anthropic")
        assert "max_input_tokens" not in caps


class TestRealCatalog:
    """Test against the actual bundled model_catalog.json."""

    @pytest.fixture(autouse=True)
    def _reset_catalog_cache(self):
        """Reset the module-level catalog cache before each test."""
        import hooty.model_catalog as mc
        old = mc._model_catalog
        mc._model_catalog = None
        yield
        mc._model_catalog = old

    def test_catalog_loads(self):
        catalog = _load_model_catalog()
        assert "anthropic" in catalog
        assert "bedrock" in catalog
        assert "azure" in catalog

    def test_anthropic_sonnet_has_reasoning(self):
        caps = get_model_capabilities("claude-sonnet-4-6", "anthropic")
        assert caps.get("supports_reasoning") is True

    def test_anthropic_haiku_has_reasoning(self):
        caps = get_model_capabilities("claude-haiku-4-5", "anthropic")
        assert caps.get("supports_reasoning") is True

    def test_grok_fast_reasoning_azure(self):
        caps = get_model_capabilities("grok-4-fast-reasoning", "azure")
        assert caps.get("supports_function_calling") is True

    def test_gemma2_ollama_no_function_calling(self):
        caps = get_model_capabilities("gemma2", "ollama")
        assert caps.get("supports_function_calling", False) is False

    def test_anthropic_sonnet_has_vision(self):
        caps = get_model_capabilities("claude-sonnet-4-6", "anthropic")
        assert caps.get("supports_vision") is True

    def test_gemma2_ollama_no_vision(self):
        caps = get_model_capabilities("gemma2", "ollama")
        assert caps.get("supports_vision", False) is False

    def test_lookup_returns_int(self):
        result = _lookup_model_catalog("claude-sonnet-4-6", "anthropic")
        assert isinstance(result, int)
        assert result == 200000
