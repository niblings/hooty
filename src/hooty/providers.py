"""LLM provider factory with lazy imports."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import httpx

from hooty.config import AppConfig, Provider, supports_thinking
from hooty.credentials import get_secret

if TYPE_CHECKING:
    from agno.models.base import Model


def _build_httpx_timeout(config: AppConfig, *, streaming: bool) -> httpx.Timeout:
    """Build an httpx Timeout using the app-wide API timeout settings."""
    read = config.api_streaming_read_timeout if streaming else config.api_read_timeout
    return httpx.Timeout(
        connect=float(config.api_connect_timeout),
        read=float(read),
        write=float(config.api_write_timeout),
        pool=float(config.api_pool_timeout),
    )


def create_model(config: AppConfig) -> Model:
    """Create an Agno Model instance based on configuration.

    Imports provider SDKs lazily so users only need the SDK
    for their chosen provider installed.
    """
    # Determine if reasoning is active for this provider+model
    reasoning_active = (
        config.reasoning.mode in ("on", "auto")
        and supports_thinking(config)
    )
    config._reasoning_active = reasoning_active

    if config.provider == Provider.ANTHROPIC:
        return _create_anthropic_model(config)
    elif config.provider == Provider.BEDROCK:
        return _create_bedrock_model(config)
    elif config.provider == Provider.AZURE:
        return _create_azure_model(config)
    elif config.provider == Provider.AZURE_OPENAI:
        return _create_azure_openai_model(config)
    elif config.provider == Provider.OPENAI:
        return _create_openai_model(config)
    elif config.provider == Provider.OLLAMA:
        return _create_ollama_model(config)
    else:
        raise ValueError(f"Unsupported provider: {config.provider}")


def _create_anthropic_model(config: AppConfig) -> Model:
    """Create Anthropic model instance (direct API or Azure AI Foundry)."""
    try:
        from agno.models.anthropic import Claude
    except ImportError:
        raise ImportError(
            "Anthropic requires additional packages.\n"
            "  pip install hooty[anthropic]"
        )

    kwargs: dict = {"id": config.anthropic.model_id}

    if config.anthropic.base_url:
        # Azure AI Foundry via Anthropic-compatible endpoint
        kwargs["api_key"] = get_secret("AZURE_API_KEY") or get_secret("ANTHROPIC_API_KEY")
        kwargs["client_params"] = {"base_url": config.anthropic.base_url}
    else:
        # Direct Anthropic API
        kwargs["api_key"] = get_secret("ANTHROPIC_API_KEY")

    if config.cache_system_prompt:
        kwargs["cache_system_prompt"] = True

    # Apply API timeout (streaming/non-streaming aware)
    timeout = _build_httpx_timeout(config, streaming=config.stream)
    client_params = kwargs.get("client_params", {}) or {}
    client_params["timeout"] = timeout
    kwargs["client_params"] = client_params

    return Claude(**kwargs)


def _create_bedrock_model(config: AppConfig) -> Model:
    """Create AWS Bedrock model instance.

    For Claude models, uses agno's AwsClaude which supports cache_system_prompt.
    For non-Claude models, uses the generic AwsBedrock.
    """
    is_claude = "claude" in config.bedrock.model_id.lower()

    try:
        if is_claude:
            from agno.models.aws.claude import Claude as AwsClaude
        from agno.models.aws import AwsBedrock
    except ImportError:
        raise ImportError(
            "AWS Bedrock requires additional packages.\n"
            "  pip install hooty[aws]"
        )

    if is_claude:
        # AwsClaude uses different param names than AwsBedrock
        kwargs: dict = {
            "id": config.bedrock.model_id,
            "aws_region": config.bedrock.region,
        }
        if config.bedrock.sso_auth:
            import boto3
            kwargs["session"] = boto3.Session()
        else:
            access_key = get_secret("AWS_ACCESS_KEY_ID")
            secret_key = get_secret("AWS_SECRET_ACCESS_KEY")
            if access_key and secret_key:
                kwargs["aws_access_key"] = access_key
                kwargs["aws_secret_key"] = secret_key
            # When using AWS_BEARER_TOKEN_BEDROCK (or other botocore-resolved
            # credentials), pass no explicit auth — let the SDK resolve
            # credentials from the environment automatically.
        if config.cache_system_prompt:
            kwargs["cache_system_prompt"] = True
        # AwsClaude uses Anthropic SDK — apply httpx timeout via client_params
        timeout = _build_httpx_timeout(config, streaming=config.stream)
        kwargs["client_params"] = {"timeout": timeout}
        model = AwsClaude(**kwargs)
    else:
        kwargs = {
            "id": config.bedrock.model_id,
            "aws_region": config.bedrock.region,
        }
        if config.bedrock.sso_auth:
            kwargs["aws_sso_auth"] = True
        else:
            access_key = get_secret("AWS_ACCESS_KEY_ID")
            secret_key = get_secret("AWS_SECRET_ACCESS_KEY")
            if access_key and secret_key:
                kwargs["aws_access_key_id"] = access_key
                kwargs["aws_secret_access_key"] = secret_key
        # AwsBedrock uses boto3 — apply timeout via botocore Config on session
        import botocore.config
        _boto_config = botocore.config.Config(
            connect_timeout=config.api_connect_timeout,
            read_timeout=(
                config.api_streaming_read_timeout if config.stream
                else config.api_read_timeout
            ),
        )
        if "session" not in kwargs:
            import boto3
            kwargs["session"] = boto3.Session(region_name=config.bedrock.region)
        # Attach botocore Config — AwsBedrock creates clients from the session,
        # but botocore.config.Config must be passed at client creation time.
        # Store it for the client override below.
        _boto_session = kwargs.get("session")
        model = AwsBedrock(**kwargs)
        # Override the boto3 clients with timeout-configured versions
        if _boto_session is not None:
            import contextlib
            with contextlib.suppress(Exception):
                model.client = _boto_session.client(
                    "bedrock-runtime",
                    region_name=config.bedrock.region,
                    config=_boto_config,
                )
            with contextlib.suppress(Exception):
                model.async_client = None  # Force lazy re-creation

    # Skip Bedrock CountTokens API — use local tiktoken fallback to avoid
    # noisy AccessDeniedException warnings when the IAM policy / bearer
    # token auth lacks bedrock:CountTokens permission.
    #
    # For Claude models, apply a 1.2x correction factor because tiktoken
    # (o200k_base) underestimates Claude token counts by ~18.6% on average.
    # Measured across 6 categories (en/ja prose, mixed, code, JSON, conversation)
    # with Haiku 4.5, Sonnet 4.5, Sonnet 4.6 — all identical results.
    # See docs/provider_spec.md and samples/compare_token_counts.py.
    import types

    from agno.models.base import Model

    if is_claude:
        _TIKTOKEN_CLAUDE_CORRECTION = 1.2

        def _corrected_count_tokens(self, messages, tools=None, output_schema=None):
            base_count = Model.count_tokens(self, messages, tools, output_schema)
            return int(base_count * _TIKTOKEN_CLAUDE_CORRECTION)

        async def _corrected_acount_tokens(self, messages, tools=None, output_schema=None):
            base_count = await Model.acount_tokens(self, messages, tools, output_schema)
            return int(base_count * _TIKTOKEN_CLAUDE_CORRECTION)

        model.count_tokens = types.MethodType(_corrected_count_tokens, model)
        model.acount_tokens = types.MethodType(_corrected_acount_tokens, model)
    else:
        model.count_tokens = types.MethodType(Model.count_tokens, model)
        model.acount_tokens = types.MethodType(Model.acount_tokens, model)

    return model


def _create_azure_model(config: AppConfig) -> Model:
    """Create Azure AI Foundry model instance."""
    try:
        from agno.models.azure import AzureAIFoundry
    except ImportError:
        raise ImportError(
            "Azure AI requires additional packages.\n"
            "  pip install hooty[azure]"
        )

    kwargs: dict = {
        "id": config.azure.model_id,
        "api_key": get_secret("AZURE_API_KEY"),
        "azure_endpoint": config.azure.endpoint,
    }

    if config.azure.api_version:
        kwargs["api_version"] = config.azure.api_version

    return AzureAIFoundry(**kwargs)


def _create_azure_openai_model(config: AppConfig) -> Model:
    """Create Azure OpenAI Service model instance."""
    try:
        from agno.models.azure.openai_chat import AzureOpenAI
    except ImportError:
        raise ImportError(
            "Azure OpenAI requires additional packages.\n"
            "  pip install hooty[azure-openai]"
        )

    timeout = _build_httpx_timeout(config, streaming=config.stream)
    return AzureOpenAI(
        id=config.azure_openai.model_id,
        api_key=get_secret("AZURE_OPENAI_API_KEY"),
        azure_endpoint=config.azure_openai.endpoint,
        azure_deployment=config.azure_openai.deployment,
        api_version=config.azure_openai.api_version,
        client_params={"timeout": timeout},
    )


def _create_openai_model(config: AppConfig) -> Model:
    """Create OpenAI direct API model instance."""
    try:
        from agno.models.openai import OpenAIChat
    except ImportError:
        raise ImportError(
            "OpenAI requires additional packages.\n"
            "  pip install hooty[openai]"
        )

    timeout = _build_httpx_timeout(config, streaming=config.stream)
    client_params: dict[str, Any] = {"timeout": timeout}
    if config.openai.base_url:
        client_params["base_url"] = config.openai.base_url
    return OpenAIChat(
        id=config.openai.model_id,
        api_key=get_secret("OPENAI_API_KEY"),
        client_params=client_params,
    )


def _create_ollama_model(config: AppConfig) -> Model:
    """Create Ollama model instance (local or Ollama Cloud)."""
    try:
        from agno.models.ollama import Ollama
    except ImportError:
        raise ImportError(
            "Ollama requires additional packages.\n"
            "  pip install hooty[ollama]"
        )
    kwargs: dict = {"id": config.ollama.model_id}
    if config.ollama.host:
        kwargs["host"] = config.ollama.host
    if config.ollama.api_key:
        kwargs["api_key"] = config.ollama.api_key
    return Ollama(**kwargs)
