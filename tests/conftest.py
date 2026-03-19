"""Shared test fixtures for Hooty."""

import pytest

from hooty.config import AnthropicConfig, AppConfig, AzureConfig, AzureOpenAIConfig, BedrockConfig, OllamaConfig, ProfileConfig, Provider


@pytest.fixture
def anthropic_config(tmp_path):
    """Create a test config for Anthropic provider (direct API)."""
    config = AppConfig(
        provider=Provider.ANTHROPIC,
        anthropic=AnthropicConfig(
            model_id="claude-sonnet-4-6",
        ),
        working_directory=str(tmp_path),
    )
    return config


@pytest.fixture
def anthropic_azure_config(tmp_path):
    """Create a test config for Anthropic provider via Azure AI Foundry."""
    config = AppConfig(
        provider=Provider.ANTHROPIC,
        anthropic=AnthropicConfig(
            model_id="claude-sonnet-4-6",
            base_url="https://my-resource.services.ai.azure.com/v1/",
        ),
        working_directory=str(tmp_path),
    )
    return config


@pytest.fixture
def bedrock_config(tmp_path):
    """Create a test config for Bedrock provider."""
    config = AppConfig(
        provider=Provider.BEDROCK,
        bedrock=BedrockConfig(
            model_id="anthropic.claude-3-5-sonnet-20241022-v2:0",
            region="us-east-1",
        ),
        working_directory=str(tmp_path),
    )
    return config


@pytest.fixture
def azure_config(tmp_path):
    """Create a test config for Azure provider."""
    config = AppConfig(
        provider=Provider.AZURE,
        azure=AzureConfig(
            model_id="Phi-4",
            endpoint="https://test.models.ai.azure.com",
        ),
        working_directory=str(tmp_path),
    )
    return config


@pytest.fixture
def azure_openai_config(tmp_path):
    """Create a test config for Azure OpenAI provider."""
    config = AppConfig(
        provider=Provider.AZURE_OPENAI,
        azure_openai=AzureOpenAIConfig(
            model_id="gpt-5.2-chat",
            endpoint="https://oai-test.openai.azure.com",
            deployment="gpt-5.2-chat",
        ),
        working_directory=str(tmp_path),
    )
    return config


@pytest.fixture
def ollama_config(tmp_path):
    """Create a test config for Ollama provider."""
    config = AppConfig(
        provider=Provider.OLLAMA,
        ollama=OllamaConfig(
            model_id="qwen3.5:9b",
        ),
        working_directory=str(tmp_path),
    )
    return config


@pytest.fixture
def config_with_profiles(tmp_path):
    """Create a test config with multiple profiles."""
    config = AppConfig(
        provider=Provider.BEDROCK,
        working_directory=str(tmp_path),
        profiles={
            "sonnet": ProfileConfig(
                provider=Provider.BEDROCK,
                model_id="global.anthropic.claude-sonnet-4-6",
            ),
            "opus": ProfileConfig(
                provider=Provider.BEDROCK,
                model_id="global.anthropic.claude-opus-4-6-v1",
            ),
            "az-sonnet": ProfileConfig(
                provider=Provider.AZURE,
                model_id="claude-sonnet-4-6",
                endpoint="https://az.example.com",
            ),
            "gpt52": ProfileConfig(
                provider=Provider.AZURE_OPENAI,
                model_id="gpt-5.2",
                endpoint="https://res.openai.azure.com",
                deployment="gpt-5.2",
            ),
            "claude-direct": ProfileConfig(
                provider=Provider.ANTHROPIC,
                model_id="claude-sonnet-4-6",
            ),
            "azure-claude": ProfileConfig(
                provider=Provider.ANTHROPIC,
                model_id="claude-sonnet-4-6",
                base_url="https://my-resource.services.ai.azure.com/v1/",
            ),
            "local-qwen": ProfileConfig(
                provider=Provider.OLLAMA,
                model_id="qwen3.5:9b",
            ),
        },
        active_profile="sonnet",
    )
    return config


@pytest.fixture
def clean_env(monkeypatch):
    """Remove Hooty-related environment variables."""
    env_vars = [
        "HOOTY_PROFILE",
        "HOOTY_DEBUG",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_REGION",
        "AZURE_API_KEY",
        "AZURE_ENDPOINT",
        "AZURE_API_VERSION",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_API_VERSION",
        "GITHUB_ACCESS_TOKEN",
        "HOOTY_REASONING",
        "OLLAMA_HOST",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)
    # Also clear credential secret store to prevent cross-test leakage
    from hooty.credentials import _credential_secrets
    _credential_secrets.clear()
