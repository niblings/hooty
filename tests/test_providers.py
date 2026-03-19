"""Tests for LLM provider factory for Hooty."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from hooty.config import AnthropicConfig, AppConfig, AzureOpenAIConfig, BedrockConfig, OllamaConfig, Provider, ReasoningConfig
from hooty.providers import create_model


class TestCreateModel:
    """Test provider factory function."""

    @patch("hooty.providers._create_anthropic_model")
    def test_creates_anthropic_model(self, mock_create, anthropic_config):
        mock_create.return_value = MagicMock()
        create_model(anthropic_config)
        mock_create.assert_called_once_with(anthropic_config)

    @patch("hooty.providers._create_bedrock_model")
    def test_creates_bedrock_model(self, mock_create, bedrock_config):
        mock_create.return_value = MagicMock()
        create_model(bedrock_config)
        mock_create.assert_called_once_with(bedrock_config)

    @patch("hooty.providers._create_azure_model")
    def test_creates_azure_model(self, mock_create, azure_config):
        mock_create.return_value = MagicMock()
        create_model(azure_config)
        mock_create.assert_called_once_with(azure_config)

    @patch("hooty.providers._create_ollama_model")
    def test_creates_ollama_model(self, mock_create, ollama_config):
        mock_create.return_value = MagicMock()
        create_model(ollama_config)
        mock_create.assert_called_once_with(ollama_config)

    def test_unsupported_provider(self):
        config = AppConfig()
        config.provider = "invalid"
        config.reasoning.mode = "off"  # skip supports_thinking() which needs valid provider
        with pytest.raises(ValueError, match="Unsupported provider"):
            create_model(config)


class TestAnthropicModel:
    """Test Anthropic model creation."""

    @pytest.fixture(autouse=True)
    def _mock_anthropic_module(self, monkeypatch):
        """Inject a fake agno.models.anthropic module so tests work
        even when the anthropic SDK is not installed."""
        self.captured_kwargs = {}

        mock_claude_cls = MagicMock()
        mock_claude_cls.side_effect = lambda **kw: self.captured_kwargs.update(kw) or MagicMock()

        fake_mod = MagicMock()
        fake_mod.Claude = mock_claude_cls

        # Temporarily register the fake module
        monkeypatch.setitem(sys.modules, "agno.models.anthropic", fake_mod)

    def test_direct_api(self, monkeypatch, clean_env):
        """Direct Anthropic API should use ANTHROPIC_API_KEY."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

        from hooty.providers import _create_anthropic_model

        config = AppConfig(provider=Provider.ANTHROPIC)
        _create_anthropic_model(config)

        assert self.captured_kwargs["id"] == "claude-sonnet-4-6"
        assert self.captured_kwargs["api_key"] == "sk-test-key"
        # client_params should contain only the timeout (no base_url for direct API)
        assert "base_url" not in self.captured_kwargs.get("client_params", {})
        assert "timeout" in self.captured_kwargs["client_params"]

    def test_azure_endpoint(self, monkeypatch, clean_env):
        """Azure AI Foundry should use AZURE_API_KEY and client_params."""
        monkeypatch.setenv("AZURE_API_KEY", "az-test-key")

        from hooty.providers import _create_anthropic_model
        from hooty.config import AnthropicConfig

        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(
                model_id="claude-sonnet-4-6",
                base_url="https://my-resource.services.ai.azure.com/v1/",
            ),
        )
        _create_anthropic_model(config)

        assert self.captured_kwargs["id"] == "claude-sonnet-4-6"
        assert self.captured_kwargs["api_key"] == "az-test-key"
        cp = self.captured_kwargs["client_params"]
        assert cp["base_url"] == "https://my-resource.services.ai.azure.com/v1/"
        assert "timeout" in cp

    def test_azure_endpoint_with_anthropic_key(self, monkeypatch, clean_env):
        """Azure AI Foundry should fall back to ANTHROPIC_API_KEY."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-for-azure")

        from hooty.providers import _create_anthropic_model
        from hooty.config import AnthropicConfig

        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(
                model_id="claude-sonnet-4-6",
                base_url="https://my-resource.services.ai.azure.com/v1/",
            ),
        )
        _create_anthropic_model(config)

        assert self.captured_kwargs["api_key"] == "sk-for-azure"
        cp = self.captured_kwargs["client_params"]
        assert cp["base_url"] == "https://my-resource.services.ai.azure.com/v1/"
        assert "timeout" in cp


class TestBedrockBearerToken:
    """Test Bedrock bearer token authentication."""

    @pytest.fixture(autouse=True, scope="class")
    def _import_aws_module(self):
        """Import agno.models.aws once for the class (boto3 import is heavy)."""
        import agno.models.aws
        import agno.models.aws.claude
        TestBedrockBearerToken._aws_mod = agno.models.aws
        TestBedrockBearerToken._aws_claude_mod = agno.models.aws.claude

    def test_bearer_token_no_session(self, monkeypatch, clean_env):
        """Bearer token auth should not pass a session (let botocore resolve)."""
        monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-bearer-token")

        captured_kwargs = {}

        mock_cls = MagicMock()
        mock_cls.side_effect = lambda **kw: captured_kwargs.update(kw) or MagicMock()

        monkeypatch.setattr(self._aws_claude_mod, "Claude", mock_cls)

        from hooty.providers import _create_bedrock_model

        config = AppConfig(provider=Provider.BEDROCK)
        _create_bedrock_model(config)

        assert "session" not in captured_kwargs
        assert "aws_access_key_id" not in captured_kwargs
        assert "aws_secret_access_key" not in captured_kwargs

    def test_access_key_no_session(self, monkeypatch, clean_env):
        """Access key auth should pass credentials directly, not a session."""
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")

        captured_kwargs = {}

        mock_cls = MagicMock()
        mock_cls.side_effect = lambda **kw: captured_kwargs.update(kw) or MagicMock()

        monkeypatch.setattr(self._aws_claude_mod, "Claude", mock_cls)

        from hooty.providers import _create_bedrock_model

        config = AppConfig(provider=Provider.BEDROCK)
        _create_bedrock_model(config)

        # AwsClaude uses aws_access_key / aws_secret_key param names
        assert captured_kwargs["aws_access_key"] == "test-key"
        assert captured_kwargs["aws_secret_key"] == "test-secret"
        assert "session" not in captured_kwargs


class TestReasoningActive:
    """Test reasoning active flag and thinking parameter."""

    @pytest.fixture(autouse=True)
    def _mock_anthropic_module(self, monkeypatch):
        """Inject a fake agno.models.anthropic module."""
        self.captured_kwargs = {}

        mock_claude_cls = MagicMock()
        mock_claude_cls.side_effect = lambda **kw: self.captured_kwargs.update(kw) or MagicMock()

        fake_mod = MagicMock()
        fake_mod.Claude = mock_claude_cls

        monkeypatch.setitem(sys.modules, "agno.models.anthropic", fake_mod)

    def test_anthropic_no_thinking_at_creation(self, monkeypatch, clean_env):
        """Thinking parameter should NOT be set at model creation (set per-request)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        from hooty.providers import _create_anthropic_model

        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(model_id="claude-sonnet-4-6"),
            reasoning=ReasoningConfig(mode="on"),
        )
        config._reasoning_active = True
        _create_anthropic_model(config)

        assert "thinking" not in self.captured_kwargs
        assert "max_tokens" not in self.captured_kwargs

    def test_anthropic_reasoning_inactive(self, monkeypatch, clean_env):
        """Thinking parameter should not be set when reasoning is off."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        from hooty.providers import _create_anthropic_model

        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(model_id="claude-sonnet-4-6"),
        )
        _create_anthropic_model(config)

        assert "thinking" not in self.captured_kwargs

    def test_reasoning_active_flag_set_by_create_model(self, monkeypatch, clean_env):
        """create_model should set config._reasoning_active correctly."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(model_id="claude-sonnet-4-6"),
            reasoning=ReasoningConfig(mode="on"),
        )
        create_model(config)
        assert config._reasoning_active is True

    def test_reasoning_active_flag_true_for_bedrock_claude(self, monkeypatch, clean_env):
        """Bedrock Claude models now support reasoning via catalog detection."""
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")

        # Mock AWS modules at sys.modules level to avoid import side-effects
        mock_aws_claude_cls = MagicMock()
        mock_aws_claude_cls.side_effect = lambda **kw: MagicMock()
        fake_aws_claude_mod = MagicMock()
        fake_aws_claude_mod.Claude = mock_aws_claude_cls

        fake_aws_mod = MagicMock()
        fake_aws_mod.AwsBedrock = MagicMock(side_effect=lambda **kw: MagicMock())

        monkeypatch.setitem(sys.modules, "agno.models.aws.claude", fake_aws_claude_mod)
        monkeypatch.setitem(sys.modules, "agno.models.aws", fake_aws_mod)

        config = AppConfig(
            provider=Provider.BEDROCK,
            bedrock=BedrockConfig(model_id="global.anthropic.claude-sonnet-4-6"),
            reasoning=ReasoningConfig(mode="on"),
        )
        create_model(config)
        assert config._reasoning_active is True

    def test_reasoning_active_flag_auto_anthropic(self, monkeypatch, clean_env):
        """auto mode should activate reasoning for Anthropic provider."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(model_id="claude-sonnet-4-6"),
            reasoning=ReasoningConfig(mode="auto"),
        )
        create_model(config)
        assert config._reasoning_active is True


class TestAzureOpenAIReasoningActive:
    """Test reasoning active flag for Azure OpenAI models."""

    @pytest.fixture(autouse=True)
    def _mock_azure_openai_module(self, monkeypatch):
        """Inject a fake agno.models.azure.openai_chat module."""
        self.captured_kwargs = {}

        mock_cls = MagicMock()
        mock_cls.side_effect = lambda **kw: self.captured_kwargs.update(kw) or MagicMock()

        fake_mod = MagicMock()
        fake_mod.AzureOpenAI = mock_cls

        monkeypatch.setitem(sys.modules, "agno.models.azure.openai_chat", fake_mod)

    def test_azure_openai_gpt52_reasoning_active(self, monkeypatch, clean_env):
        """GPT-5.2 with mode=on should activate reasoning."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

        config = AppConfig(
            provider=Provider.AZURE_OPENAI,
            azure_openai=AzureOpenAIConfig(
                model_id="gpt-5.2", endpoint="https://test.openai.azure.com",
                deployment="gpt-52",
            ),
            reasoning=ReasoningConfig(mode="on"),
        )
        create_model(config)
        assert config._reasoning_active is True

    def test_azure_openai_gpt52_chat_reasoning_active(self, monkeypatch, clean_env):
        """GPT-5.2-chat with mode=on should activate reasoning."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

        config = AppConfig(
            provider=Provider.AZURE_OPENAI,
            azure_openai=AzureOpenAIConfig(
                model_id="gpt-5.2-chat", endpoint="https://test.openai.azure.com",
                deployment="gpt-52-chat",
            ),
            reasoning=ReasoningConfig(mode="on"),
        )
        create_model(config)
        assert config._reasoning_active is True

    def test_azure_openai_gpt51_reasoning_active(self, monkeypatch, clean_env):
        """GPT-5.1 with mode=on should activate reasoning (per model catalog)."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

        config = AppConfig(
            provider=Provider.AZURE_OPENAI,
            azure_openai=AzureOpenAIConfig(
                model_id="gpt-5.1", endpoint="https://test.openai.azure.com",
                deployment="gpt-51",
            ),
            reasoning=ReasoningConfig(mode="on"),
        )
        create_model(config)
        assert config._reasoning_active is True

    def test_azure_openai_gpt5_reasoning_active(self, monkeypatch, clean_env):
        """GPT-5 with mode=on should activate reasoning (per model catalog)."""
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

        config = AppConfig(
            provider=Provider.AZURE_OPENAI,
            azure_openai=AzureOpenAIConfig(
                model_id="gpt-5", endpoint="https://test.openai.azure.com",
                deployment="gpt-5",
            ),
            reasoning=ReasoningConfig(mode="on"),
        )
        create_model(config)
        assert config._reasoning_active is True


class TestOllamaModel:
    """Test Ollama model creation."""

    @pytest.fixture(autouse=True)
    def _mock_ollama_module(self, monkeypatch):
        """Inject a fake agno.models.ollama module."""
        self.captured_kwargs = {}

        mock_ollama_cls = MagicMock()
        mock_ollama_cls.side_effect = lambda **kw: self.captured_kwargs.update(kw) or MagicMock()

        fake_mod = MagicMock()
        fake_mod.Ollama = mock_ollama_cls

        monkeypatch.setitem(sys.modules, "agno.models.ollama", fake_mod)

    def test_default_ollama(self, clean_env):
        """Default Ollama should use model_id only."""
        from hooty.providers import _create_ollama_model

        config = AppConfig(provider=Provider.OLLAMA)
        _create_ollama_model(config)

        assert self.captured_kwargs["id"] == "qwen3.5:9b"
        assert "host" not in self.captured_kwargs
        assert "api_key" not in self.captured_kwargs

    def test_ollama_with_host(self, clean_env):
        """Custom host should be passed."""
        from hooty.providers import _create_ollama_model

        config = AppConfig(
            provider=Provider.OLLAMA,
            ollama=OllamaConfig(
                model_id="llama3.1:8b",
                host="http://remote:11434",
            ),
        )
        _create_ollama_model(config)

        assert self.captured_kwargs["id"] == "llama3.1:8b"
        assert self.captured_kwargs["host"] == "http://remote:11434"

    def test_ollama_with_api_key(self, clean_env):
        """API key for Ollama Cloud should be passed."""
        from hooty.providers import _create_ollama_model

        config = AppConfig(
            provider=Provider.OLLAMA,
            ollama=OllamaConfig(
                model_id="qwen3.5:9b",
                host="https://cloud.ollama.com",
                api_key="olk-test-key",
            ),
        )
        _create_ollama_model(config)

        assert self.captured_kwargs["id"] == "qwen3.5:9b"
        assert self.captured_kwargs["host"] == "https://cloud.ollama.com"
        assert self.captured_kwargs["api_key"] == "olk-test-key"
