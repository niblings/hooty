"""Tests for Hooty configuration management."""

from pathlib import Path

import yaml

import pytest

from hooty.config import AgnoConfig, AnthropicConfig, AppConfig, AzureConfig, AzureOpenAIConfig, ConfigFileError, ProfileConfig, Provider, ReasoningConfig, RolesConfig, SkillsConfig, _apply_yaml, _supports_reasoning_effort, detect_reasoning_level, detect_thinking_budget, load_config, project_dir_name, supports_thinking, supports_vision, validate_config


class TestAppConfigDefaults:
    """Test default configuration values."""

    def test_default_provider(self):
        config = AppConfig()
        assert config.provider == Provider.BEDROCK

    def test_default_stream(self):
        config = AppConfig()
        assert config.stream is True

    def test_default_bedrock_model(self):
        config = AppConfig()
        assert config.bedrock.model_id == "global.anthropic.claude-sonnet-4-6"

    def test_default_anthropic_model(self):
        config = AppConfig()
        assert config.anthropic.model_id == "claude-sonnet-4-6"

    def test_default_anthropic_base_url(self):
        config = AppConfig()
        assert config.anthropic.base_url == ""

    def test_default_azure_model(self):
        config = AppConfig()
        assert config.azure.model_id == "claude-sonnet-4-6"

    def test_default_azure_openai_model(self):
        config = AppConfig()
        assert config.azure_openai.model_id == "gpt-5.2"

    def test_default_azure_openai_api_version(self):
        config = AppConfig()
        assert config.azure_openai.api_version == "2024-10-21"

    def test_config_dir(self):
        config = AppConfig()
        assert config.config_dir == Path.home() / ".hooty"

    def test_default_allowed_commands(self):
        config = AppConfig()
        assert config.allowed_commands == []

    def test_default_shell_timeout(self):
        config = AppConfig()
        assert config.shell_timeout == 120

    def test_default_idle_timeout(self):
        config = AppConfig()
        assert config.idle_timeout == 0

    def test_default_roles(self):
        config = AppConfig()
        assert isinstance(config.roles, RolesConfig)
        assert config.roles.planning is None
        assert config.roles.coding is None

    def test_session_dir_none_without_session_id(self):
        config = AppConfig()
        assert config.session_dir is None
        assert config.session_tmp_dir is None

    def test_session_dir_with_session_id(self):
        config = AppConfig(session_id="abc-123")
        assert config.session_dir == config.config_dir / "sessions" / "abc-123"
        assert config.session_tmp_dir == config.config_dir / "sessions" / "abc-123" / "tmp"

    def test_default_memory_enabled(self):
        config = AppConfig()
        assert config.memory_enabled is True

    def test_global_memory_db_path(self):
        config = AppConfig()
        assert config.global_memory_db_path == str(config.config_dir / "memory.db")

    def test_project_dir(self):
        config = AppConfig(working_directory="/tmp/projects/myapp")
        proj_name = project_dir_name(Path("/tmp/projects/myapp"))
        assert config.project_dir == config.config_dir / "projects" / proj_name

    def test_project_memory_db_path(self):
        config = AppConfig(working_directory="/tmp/projects/myapp")
        assert config.project_memory_db_path == str(config.project_dir / "memory.db")

    def test_default_profiles_empty(self):
        config = AppConfig()
        assert config.profiles == {}

    def test_default_ollama_model(self):
        config = AppConfig()
        assert config.ollama.model_id == "qwen3.5:9b"

    def test_default_ollama_host_empty(self):
        config = AppConfig()
        assert config.ollama.host == ""

    def test_default_ollama_api_key_empty(self):
        config = AppConfig()
        assert config.ollama.api_key == ""

    def test_default_active_profile_empty(self):
        config = AppConfig()
        assert config.active_profile == ""

    def test_default_provider_env_empty(self):
        config = AppConfig()
        assert config.provider_env == {}


class TestLoadConfigFromYaml:
    """Test YAML configuration loading."""

    def test_load_providers_from_yaml(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "providers": {
                        "azure": {
                            "model_id": "Llama-3.1-70B",
                            "endpoint": "https://test.azure.com",
                        }
                    },
                }
            )
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.azure.model_id == "Llama-3.1-70B"

    def test_load_ollama_from_yaml(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "providers": {
                        "ollama": {
                            "model_id": "llama3.1:8b",
                            "host": "http://remote:11434",
                            "api_key": "test-key",
                            "max_input_tokens": 131072,
                        }
                    },
                }
            )
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.ollama.model_id == "llama3.1:8b"
        assert config.ollama.host == "http://remote:11434"
        assert config.ollama.api_key == "test-key"
        assert config.ollama.max_input_tokens == 131072

    def test_load_profiles_from_yaml(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "default": {"profile": "sonnet"},
                    "providers": {
                        "bedrock": {"region": "us-west-2"},
                    },
                    "profiles": {
                        "sonnet": {
                            "provider": "bedrock",
                            "model_id": "global.anthropic.claude-sonnet-4-6",
                        },
                        "opus": {
                            "provider": "bedrock",
                            "model_id": "global.anthropic.claude-opus-4-6-v1",
                        },
                    },
                }
            )
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert "sonnet" in config.profiles
        assert "opus" in config.profiles
        assert config.profiles["sonnet"].provider == Provider.BEDROCK
        assert config.profiles["sonnet"].model_id == "global.anthropic.claude-sonnet-4-6"
        assert config.active_profile == "sonnet"
        assert config.provider == Provider.BEDROCK
        assert config.bedrock.model_id == "global.anthropic.claude-sonnet-4-6"

    def test_load_profile_with_overrides(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "default": {"profile": "gpt52"},
                    "providers": {
                        "azure_openai": {
                            "endpoint": "https://default.openai.azure.com",
                            "api_version": "2024-10-21",
                        },
                    },
                    "profiles": {
                        "gpt52": {
                            "provider": "azure_openai",
                            "model_id": "gpt-5.2",
                            "endpoint": "https://resource-a.openai.azure.com",
                            "deployment": "gpt-5.2",
                        },
                    },
                }
            )
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        # Profile override should win over providers section
        assert config.azure_openai.endpoint == "https://resource-a.openai.azure.com"
        assert config.azure_openai.deployment == "gpt-5.2"
        assert config.azure_openai.model_id == "gpt-5.2"

    def test_load_azure_openai_from_yaml(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "providers": {
                        "azure_openai": {
                            "model_id": "gpt-5.2-chat",
                            "endpoint": "https://oai-test.openai.azure.com",
                            "deployment": "gpt-5.2-chat",
                            "api_version": "2025-01-01",
                        }
                    },
                }
            )
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.azure_openai.model_id == "gpt-5.2-chat"
        assert config.azure_openai.endpoint == "https://oai-test.openai.azure.com"
        assert config.azure_openai.deployment == "gpt-5.2-chat"
        assert config.azure_openai.api_version == "2025-01-01"

    def test_load_allowed_commands_from_yaml(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "tools": {
                        "allowed_commands": ["terraform", "kubectl", "helm"],
                    }
                }
            )
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.allowed_commands == ["terraform", "kubectl", "helm"]

    def test_load_shell_timeout_from_yaml(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "tools": {
                        "shell_timeout": 600,
                        "idle_timeout": 60,
                    }
                }
            )
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.shell_timeout == 600
        assert config.idle_timeout == 60

    def test_load_shell_operators_from_yaml(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "tools": {
                        "shell_operators": {
                            "pipe": False,
                            "chain": False,
                            "redirect": True,
                        }
                    }
                }
            )
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.shell_operators.pipe is False
        assert config.shell_operators.chain is False
        assert config.shell_operators.redirect is True

    def test_load_shell_operators_defaults(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({"default": {}}))

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.shell_operators.pipe is True
        assert config.shell_operators.chain is True
        assert config.shell_operators.redirect is False

    def test_load_yaml_without_tools_section(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({"default": {}})
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.allowed_commands == []

    def test_load_roles_from_yaml(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "roles": {
                        "planning": "You are an infrastructure architect.",
                        "coding": "You are a Python specialist.",
                    }
                }
            )
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.roles.planning == "You are an infrastructure architect."
        assert config.roles.coding == "You are a Python specialist."

    def test_load_roles_partial_from_yaml(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "roles": {
                        "planning": "Custom planning role only.",
                    }
                }
            )
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.roles.planning == "Custom planning role only."
        assert config.roles.coding is None

    def test_load_memory_config_from_yaml(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "memory": {
                        "enabled": False,
                    }
                }
            )
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.memory_enabled is False

    def test_load_memory_enabled_default_from_yaml(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({"default": {}})
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.memory_enabled is True

    def test_load_missing_yaml(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_file = config_dir / "config.yaml"

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.provider == Provider.BEDROCK

    def test_invalid_profile_provider_skipped(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "profiles": {
                        "bad": {"provider": "nonexistent", "model_id": "x"},
                        "good": {"provider": "bedrock", "model_id": "y"},
                    },
                }
            )
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert "bad" not in config.profiles
        assert "good" in config.profiles

    def test_profile_missing_required_fields_skipped(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "profiles": {
                        "no_model": {"provider": "bedrock"},
                        "no_provider": {"model_id": "test"},
                    },
                }
            )
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.profiles == {}

    def test_yaml_parse_error_raises_config_file_error(self, tmp_path, monkeypatch, clean_env):
        """Malformed YAML should raise ConfigFileError with file name and line info."""
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            "providers:\n"
            "  ollama:\n"
            "    model_id: qwen3.5:9b\n"
            "   bad_indent: true\n"  # intentional bad indent
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))

        with pytest.raises(ConfigFileError, match="config.yaml"):
            load_config()


class TestLoadConfigFromEnv:
    """Test environment variable configuration."""

    def test_profile_from_env(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "profiles": {
                        "sonnet": {
                            "provider": "bedrock",
                            "model_id": "global.anthropic.claude-sonnet-4-6",
                        },
                    },
                }
            )
        )
        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        monkeypatch.setenv("HOOTY_PROFILE", "sonnet")

        config = load_config()
        assert config.active_profile == "sonnet"
        assert config.provider == Provider.BEDROCK

    def test_debug_from_env(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_dir / "config.yaml"))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        monkeypatch.setenv("HOOTY_DEBUG", "true")

        config = load_config()
        assert config.debug is True

    def test_ollama_host_from_env(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_dir / "config.yaml"))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        monkeypatch.setenv("OLLAMA_HOST", "http://remote:11434")

        config = load_config()
        assert config.ollama.host == "http://remote:11434"


class TestLoadConfigCliOverrides:
    """Test CLI argument overrides."""

    def test_profile_override(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "default": {"profile": "sonnet"},
                    "profiles": {
                        "sonnet": {
                            "provider": "bedrock",
                            "model_id": "global.anthropic.claude-sonnet-4-6",
                        },
                        "opus": {
                            "provider": "bedrock",
                            "model_id": "global.anthropic.claude-opus-4-6-v1",
                        },
                    },
                }
            )
        )
        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))

        config = load_config(profile_override="opus")
        assert config.active_profile == "opus"
        assert config.bedrock.model_id == "global.anthropic.claude-opus-4-6-v1"

    def test_cli_overrides_env(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "profiles": {
                        "sonnet": {
                            "provider": "bedrock",
                            "model_id": "global.anthropic.claude-sonnet-4-6",
                        },
                        "opus": {
                            "provider": "bedrock",
                            "model_id": "global.anthropic.claude-opus-4-6-v1",
                        },
                    },
                }
            )
        )
        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        monkeypatch.setenv("HOOTY_PROFILE", "sonnet")

        config = load_config(profile_override="opus")
        assert config.active_profile == "opus"
        assert config.bedrock.model_id == "global.anthropic.claude-opus-4-6-v1"


class TestActivateProfile:
    """Test profile activation."""

    def test_activate_anthropic_direct_profile(self, config_with_profiles):
        config = config_with_profiles
        error = config.activate_profile("claude-direct")
        assert error is None
        assert config.provider == Provider.ANTHROPIC
        assert config.active_profile == "claude-direct"
        assert config.anthropic.model_id == "claude-sonnet-4-6"
        assert config.anthropic.base_url == ""

    def test_activate_anthropic_azure_profile(self, config_with_profiles):
        config = config_with_profiles
        error = config.activate_profile("azure-claude")
        assert error is None
        assert config.provider == Provider.ANTHROPIC
        assert config.active_profile == "azure-claude"
        assert config.anthropic.model_id == "claude-sonnet-4-6"
        assert config.anthropic.base_url == "https://my-resource.services.ai.azure.com/v1/"

    def test_activate_bedrock_profile(self, config_with_profiles):
        config = config_with_profiles
        error = config.activate_profile("opus")
        assert error is None
        assert config.provider == Provider.BEDROCK
        assert config.active_profile == "opus"
        assert config.bedrock.model_id == "global.anthropic.claude-opus-4-6-v1"

    def test_activate_azure_profile(self, config_with_profiles):
        config = config_with_profiles
        error = config.activate_profile("az-sonnet")
        assert error is None
        assert config.provider == Provider.AZURE
        assert config.active_profile == "az-sonnet"
        assert config.azure.model_id == "claude-sonnet-4-6"
        assert config.azure.endpoint == "https://az.example.com"

    def test_activate_azure_openai_profile(self, config_with_profiles):
        config = config_with_profiles
        error = config.activate_profile("gpt52")
        assert error is None
        assert config.provider == Provider.AZURE_OPENAI
        assert config.active_profile == "gpt52"
        assert config.azure_openai.model_id == "gpt-5.2"
        assert config.azure_openai.endpoint == "https://res.openai.azure.com"
        assert config.azure_openai.deployment == "gpt-5.2"

    def test_activate_unknown_profile(self, config_with_profiles):
        config = config_with_profiles
        error = config.activate_profile("nonexistent")
        assert error is not None
        assert "Unknown profile" in error
        assert "nonexistent" in error

    def test_activate_profile_injects_env_to_credential_store(self):
        """Provider env vars go into credential secret store, not os.environ."""
        from hooty.credentials import _credential_secrets, get_secret
        config = AppConfig(
            profiles={
                "test": ProfileConfig(
                    provider=Provider.BEDROCK,
                    model_id="test-model",
                ),
            },
            provider_env={
                "bedrock": {"AWS_ACCESS_KEY_ID": "test-key"},
            },
        )
        config.activate_profile("test")
        assert get_secret("AWS_ACCESS_KEY_ID") == "test-key"
        # Must NOT be in os.environ (prevents leaking to child processes)
        import os
        assert os.environ.get("AWS_ACCESS_KEY_ID") != "test-key"
        # Cleanup
        _credential_secrets.pop("AWS_ACCESS_KEY_ID", None)

    def test_activate_profile_preserves_none_overrides(self):
        """Profile fields that are None should not override provider base config."""
        config = AppConfig(
            profiles={
                "test": ProfileConfig(
                    provider=Provider.BEDROCK,
                    model_id="new-model",
                    region=None,  # Should not change bedrock.region
                ),
            },
        )
        config.bedrock.region = "ap-northeast-1"
        config.activate_profile("test")
        assert config.bedrock.model_id == "new-model"
        assert config.bedrock.region == "ap-northeast-1"  # Preserved

    def test_azure_openai_deployment_falls_back_to_model_id(self):
        """When deployment is not specified, model_id should be used."""
        config = AppConfig(
            profiles={
                "gpt": ProfileConfig(
                    provider=Provider.AZURE_OPENAI,
                    model_id="gpt-5.2",
                    endpoint="https://res.openai.azure.com",
                    # deployment is None — should fall back to model_id
                ),
            },
        )
        config.activate_profile("gpt")
        assert config.azure_openai.deployment == "gpt-5.2"
        assert config.azure_openai.model_id == "gpt-5.2"

    def test_ollama_profile_activation(self):
        """Ollama profile should set model_id and host."""
        config = AppConfig(
            profiles={
                "local": ProfileConfig(
                    provider=Provider.OLLAMA,
                    model_id="llama3.1:8b",
                    host="http://remote:11434",
                    max_input_tokens=131072,
                ),
            },
        )
        config.activate_profile("local")
        assert config.provider == Provider.OLLAMA
        assert config.ollama.model_id == "llama3.1:8b"
        assert config.ollama.host == "http://remote:11434"
        assert config.ollama.max_input_tokens == 131072

    def test_azure_openai_explicit_deployment_wins(self):
        """When deployment is explicitly set, it should be used over model_id."""
        config = AppConfig(
            profiles={
                "gpt": ProfileConfig(
                    provider=Provider.AZURE_OPENAI,
                    model_id="gpt-5.2",
                    endpoint="https://res.openai.azure.com",
                    deployment="my-custom-deploy",
                ),
            },
        )
        config.activate_profile("gpt")
        assert config.azure_openai.deployment == "my-custom-deploy"
        assert config.azure_openai.model_id == "gpt-5.2"


class TestValidateConfig:
    """Test configuration validation."""

    def test_anthropic_direct_valid(self, monkeypatch, clean_env):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
        config = AppConfig(provider=Provider.ANTHROPIC)
        assert validate_config(config) is None

    def test_anthropic_direct_invalid_no_key(self, clean_env):
        config = AppConfig(provider=Provider.ANTHROPIC)
        error = validate_config(config)
        assert error is not None
        assert "ANTHROPIC_API_KEY" in error

    def test_anthropic_azure_valid(self, monkeypatch, clean_env):
        monkeypatch.setenv("AZURE_API_KEY", "az-test-key")
        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(
                base_url="https://my-resource.services.ai.azure.com/v1/",
            ),
        )
        assert validate_config(config) is None

    def test_anthropic_azure_valid_with_anthropic_key(self, monkeypatch, clean_env):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-for-azure")
        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(
                base_url="https://my-resource.services.ai.azure.com/v1/",
            ),
        )
        assert validate_config(config) is None

    def test_anthropic_azure_invalid_no_key(self, clean_env):
        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(
                base_url="https://my-resource.services.ai.azure.com/v1/",
            ),
        )
        error = validate_config(config)
        assert error is not None
        assert "AZURE_API_KEY" in error

    def test_bedrock_valid_with_keys(self, monkeypatch, clean_env):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
        config = AppConfig(provider=Provider.BEDROCK)
        assert validate_config(config) is None

    def test_bedrock_valid_with_bearer_token(self, monkeypatch, clean_env):
        monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-bearer-token")
        config = AppConfig(provider=Provider.BEDROCK)
        assert validate_config(config) is None

    def test_bedrock_valid_with_sso(self, clean_env):
        config = AppConfig(provider=Provider.BEDROCK)
        config.bedrock.sso_auth = True
        assert validate_config(config) is None

    def test_bedrock_invalid_no_auth(self, clean_env):
        config = AppConfig(provider=Provider.BEDROCK)
        error = validate_config(config)
        assert error is not None
        assert "AWS Bedrock" in error

    def test_azure_valid(self, monkeypatch, clean_env):
        monkeypatch.setenv("AZURE_API_KEY", "test-key")
        config = AppConfig(provider=Provider.AZURE)
        config.azure.endpoint = "https://test.azure.com"
        assert validate_config(config) is None

    def test_azure_invalid_no_key(self, clean_env):
        config = AppConfig(provider=Provider.AZURE)
        config.azure.endpoint = "https://test.azure.com"
        error = validate_config(config)
        assert error is not None
        assert "AZURE_API_KEY" in error

    def test_azure_invalid_no_endpoint(self, monkeypatch, clean_env):
        monkeypatch.setenv("AZURE_API_KEY", "test-key")
        config = AppConfig(provider=Provider.AZURE)
        error = validate_config(config)
        assert error is not None
        assert "endpoint" in error.lower()

    def test_azure_openai_valid(self, monkeypatch, clean_env):
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        config = AppConfig(provider=Provider.AZURE_OPENAI)
        config.azure_openai.endpoint = "https://oai-test.openai.azure.com"
        config.azure_openai.deployment = "gpt-5.2-chat"
        assert validate_config(config) is None

    def test_azure_openai_invalid_no_key(self, clean_env):
        config = AppConfig(provider=Provider.AZURE_OPENAI)
        config.azure_openai.endpoint = "https://oai-test.openai.azure.com"
        config.azure_openai.deployment = "gpt-5.2-chat"
        error = validate_config(config)
        assert error is not None
        assert "AZURE_OPENAI_API_KEY" in error

    def test_azure_openai_invalid_no_endpoint(self, monkeypatch, clean_env):
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        config = AppConfig(provider=Provider.AZURE_OPENAI)
        config.azure_openai.deployment = "gpt-5.2-chat"
        error = validate_config(config)
        assert error is not None
        assert "endpoint" in error.lower()

    def test_azure_openai_invalid_no_deployment(self, monkeypatch, clean_env):
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
        config = AppConfig(provider=Provider.AZURE_OPENAI)
        config.azure_openai.endpoint = "https://oai-test.openai.azure.com"
        error = validate_config(config)
        assert error is not None
        assert "deployment" in error.lower()

    def test_ollama_valid_no_auth_required(self, clean_env):
        """Ollama should always pass validation (local, no auth)."""
        config = AppConfig(provider=Provider.OLLAMA)
        assert validate_config(config) is None


class TestAwakeConfig:
    """Test hooty.awake configuration."""

    def test_default_awake(self):
        config = AppConfig()
        assert config.awake == (9, 21)

    def test_awake_from_yaml(self):
        config = AppConfig()
        _apply_yaml(config, {"hooty": {"awake": [6, 18]}})
        assert config.awake == (6, 18)

    def test_awake_non_list_fallback(self):
        config = AppConfig()
        _apply_yaml(config, {"hooty": {"awake": "9-21"}})
        assert config.awake == (9, 21)

    def test_awake_wrong_length_fallback(self):
        config = AppConfig()
        _apply_yaml(config, {"hooty": {"awake": [9]}})
        assert config.awake == (9, 21)

    def test_awake_out_of_range_fallback(self):
        config = AppConfig()
        _apply_yaml(config, {"hooty": {"awake": [-1, 21]}})
        assert config.awake == (9, 21)

    def test_awake_out_of_range_high_fallback(self):
        config = AppConfig()
        _apply_yaml(config, {"hooty": {"awake": [9, 24]}})
        assert config.awake == (9, 21)

    def test_awake_start_ge_end_fallback(self):
        config = AppConfig()
        _apply_yaml(config, {"hooty": {"awake": [21, 9]}})
        assert config.awake == (9, 21)

    def test_awake_equal_fallback(self):
        config = AppConfig()
        _apply_yaml(config, {"hooty": {"awake": [12, 12]}})
        assert config.awake == (9, 21)

    def test_awake_diff_less_than_2_fallback(self):
        config = AppConfig()
        _apply_yaml(config, {"hooty": {"awake": [10, 11]}})
        assert config.awake == (9, 21)

    def test_awake_diff_exactly_2(self):
        config = AppConfig()
        _apply_yaml(config, {"hooty": {"awake": [10, 12]}})
        assert config.awake == (10, 12)

    def test_awake_from_full_load(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({"hooty": {"awake": [7, 20]}})
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.awake == (7, 20)


class TestSkillsConfig:
    """Test skills configuration."""

    def test_default_skills_enabled(self):
        config = AppConfig()
        assert isinstance(config.skills, SkillsConfig)
        assert config.skills.enabled is True

    def test_skills_state_path(self):
        config = AppConfig(working_directory="/tmp/projects/myapp")
        assert config.skills_state_path == config.project_dir / ".skills.json"

    def test_skills_enabled_from_yaml(self):
        config = AppConfig()
        _apply_yaml(config, {"skills": {"enabled": True}})
        assert config.skills.enabled is True

    def test_skills_disabled_from_yaml(self):
        config = AppConfig()
        _apply_yaml(config, {"skills": {"enabled": False}})
        assert config.skills.enabled is False

    def test_skills_from_full_load(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({"skills": {"enabled": True}})
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.skills.enabled is True

    def test_skills_absent_in_yaml_keeps_defaults(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({"default": {}}))

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.skills.enabled is True

    def test_no_skills_cli_override(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({"skills": {"enabled": True}}))

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config(no_skills=True)

        assert config.skills.enabled is False


class TestAgnoConfig:
    """Test Agno framework configuration."""

    def test_default_agno_telemetry_false(self):
        config = AppConfig()
        assert isinstance(config.agno, AgnoConfig)
        assert config.agno.telemetry is False

    def test_agno_telemetry_true_from_yaml(self):
        config = AppConfig()
        _apply_yaml(config, {"agno": {"telemetry": True}})
        assert config.agno.telemetry is True

    def test_agno_telemetry_false_from_yaml(self):
        config = AppConfig()
        _apply_yaml(config, {"agno": {"telemetry": False}})
        assert config.agno.telemetry is False

    def test_agno_absent_in_yaml_keeps_defaults(self):
        config = AppConfig()
        _apply_yaml(config, {"default": {}})
        assert config.agno.telemetry is False

    def test_agno_from_full_load(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            yaml.dump({"agno": {"telemetry": True}})
        )

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.agno.telemetry is True

    def test_agno_default_from_full_load(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({"default": {}}))

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.agno.telemetry is False


class TestReasoningConfig:
    """Test reasoning configuration."""

    def test_default_reasoning_mode_auto(self):
        config = AppConfig()
        assert isinstance(config.reasoning, ReasoningConfig)
        assert config.reasoning.mode == "auto"

    def test_default_reasoning_active_false(self):
        config = AppConfig()
        assert config._reasoning_active is False

    def test_apply_yaml_reasoning_mode(self):
        config = AppConfig()
        _apply_yaml(config, {"reasoning": {"mode": "on"}})
        assert config.reasoning.mode == "on"

    def test_apply_yaml_reasoning_auto(self):
        config = AppConfig()
        _apply_yaml(config, {"reasoning": {"mode": "auto"}})
        assert config.reasoning.mode == "auto"

    def test_apply_yaml_reasoning_invalid_mode_ignored(self):
        config = AppConfig()
        _apply_yaml(config, {"reasoning": {"mode": "invalid"}})
        assert config.reasoning.mode == "auto"

    def test_default_auto_level_one(self):
        config = AppConfig()
        assert config.reasoning.auto_level == 1

    def test_apply_yaml_auto_level(self):
        config = AppConfig()
        _apply_yaml(config, {"reasoning": {"auto_level": 2}})
        assert config.reasoning.auto_level == 2

    def test_apply_yaml_auto_level_clamped(self):
        config = AppConfig()
        _apply_yaml(config, {"reasoning": {"auto_level": 5}})
        assert config.reasoning.auto_level == 3
        config2 = AppConfig()
        _apply_yaml(config2, {"reasoning": {"auto_level": -1}})
        assert config2.reasoning.auto_level == 0

    def test_reasoning_env_var_on(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_dir / "config.yaml"))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        monkeypatch.setenv("HOOTY_REASONING", "on")

        config = load_config()
        assert config.reasoning.mode == "on"

    def test_reasoning_env_var_auto(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_dir / "config.yaml"))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        monkeypatch.setenv("HOOTY_REASONING", "auto")

        config = load_config()
        assert config.reasoning.mode == "auto"

    def test_reasoning_env_var_true(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_dir / "config.yaml"))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        monkeypatch.setenv("HOOTY_REASONING", "true")

        config = load_config()
        assert config.reasoning.mode == "on"

    def test_reasoning_cli_override(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({"reasoning": {"mode": "off"}}))

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config(reasoning="on")

        assert config.reasoning.mode == "on"

    def test_reasoning_from_full_yaml(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(yaml.dump({
            "reasoning": {"mode": "auto"},
        }))

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_file))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        config = load_config()

        assert config.reasoning.mode == "auto"


class TestSupportsThinking:
    """Test supports_thinking() helper."""

    def test_supports_thinking_anthropic_sonnet(self):
        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(model_id="claude-sonnet-4-6"),
        )
        assert supports_thinking(config) is True

    def test_supports_thinking_anthropic_opus(self):
        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(model_id="claude-opus-4-6"),
        )
        assert supports_thinking(config) is True

    def test_supports_thinking_bedrock_claude(self):
        # Default bedrock model (claude-sonnet-4-6) now detected via catalog
        config = AppConfig(provider=Provider.BEDROCK)
        assert supports_thinking(config) is True

    def test_supports_thinking_azure_claude(self):
        # Default azure model (claude-sonnet-4-6) now detected via catalog
        config = AppConfig(provider=Provider.AZURE)
        assert supports_thinking(config) is True

    def test_supports_thinking_ollama(self):
        config = AppConfig(provider=Provider.OLLAMA)
        assert supports_thinking(config) is False

    def test_supports_thinking_haiku_35(self):
        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(model_id="claude-3-5-haiku-20241022"),
        )
        assert supports_thinking(config) is False

    def test_supports_thinking_haiku_3(self):
        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(model_id="claude-3-haiku-20240307"),
        )
        assert supports_thinking(config) is False

    def test_supports_thinking_haiku_latest(self):
        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(model_id="claude-3-5-haiku-latest"),
        )
        assert supports_thinking(config) is False

    def test_supports_thinking_azure_openai_gpt52(self):
        config = AppConfig(
            provider=Provider.AZURE_OPENAI,
            azure_openai=AzureOpenAIConfig(model_id="gpt-5.2"),
        )
        assert supports_thinking(config) is True

    def test_supports_thinking_azure_openai_gpt52_chat(self):
        config = AppConfig(
            provider=Provider.AZURE_OPENAI,
            azure_openai=AzureOpenAIConfig(model_id="gpt-5.2-chat"),
        )
        assert supports_thinking(config) is True

    def test_supports_thinking_azure_openai_gpt52_pro(self):
        config = AppConfig(
            provider=Provider.AZURE_OPENAI,
            azure_openai=AzureOpenAIConfig(model_id="gpt-5.2-pro"),
        )
        assert supports_thinking(config) is True

    def test_supports_thinking_azure_openai_gpt53_codex(self):
        config = AppConfig(
            provider=Provider.AZURE_OPENAI,
            azure_openai=AzureOpenAIConfig(model_id="gpt-5.3-codex"),
        )
        assert supports_thinking(config) is True

    def test_supports_thinking_azure_openai_gpt5_yes(self):
        # gpt-5 now has supports_reasoning in the catalog (LiteLLM upstream)
        config = AppConfig(
            provider=Provider.AZURE_OPENAI,
            azure_openai=AzureOpenAIConfig(model_id="gpt-5"),
        )
        assert supports_thinking(config) is True

    def test_supports_thinking_azure_openai_gpt51_yes(self):
        # gpt-5.1 now has supports_reasoning in the catalog (LiteLLM upstream)
        config = AppConfig(
            provider=Provider.AZURE_OPENAI,
            azure_openai=AzureOpenAIConfig(model_id="gpt-5.1"),
        )
        assert supports_thinking(config) is True

    def test_supports_thinking_azure_openai_gpt5_mini_yes(self):
        # gpt-5-mini now has supports_reasoning in the catalog (LiteLLM upstream)
        config = AppConfig(
            provider=Provider.AZURE_OPENAI,
            azure_openai=AzureOpenAIConfig(model_id="gpt-5-mini"),
        )
        assert supports_thinking(config) is True

    def test_supports_thinking_azure_openai_gpt4o_no(self):
        config = AppConfig(
            provider=Provider.AZURE_OPENAI,
            azure_openai=AzureOpenAIConfig(model_id="gpt-4o"),
        )
        assert supports_thinking(config) is False


class TestSupportsVision:
    """Test supports_vision() helper."""

    def test_supports_vision_anthropic_sonnet(self):
        config = AppConfig(
            provider=Provider.ANTHROPIC,
            anthropic=AnthropicConfig(model_id="claude-sonnet-4-6"),
        )
        assert supports_vision(config) is True

    def test_supports_vision_bedrock_claude(self):
        config = AppConfig(provider=Provider.BEDROCK)
        assert supports_vision(config) is True

    def test_supports_vision_azure_claude(self):
        config = AppConfig(provider=Provider.AZURE)
        assert supports_vision(config) is True

    def test_supports_vision_ollama_default(self):
        config = AppConfig(provider=Provider.OLLAMA)
        assert supports_vision(config) is False

    def test_supports_vision_unknown_provider_fallback(self):
        config = AppConfig(
            provider=Provider.AZURE,
            azure=AzureConfig(model_id="claude-sonnet-4-6"),
        )
        assert supports_vision(config) is True

    def test_supports_vision_non_claude_no_catalog(self):
        config = AppConfig(
            provider=Provider.AZURE_OPENAI,
            azure_openai=AzureOpenAIConfig(model_id="gpt-5.2"),
        )
        # GPT-5.2 should have vision from catalog
        caps_result = supports_vision(config)
        assert isinstance(caps_result, bool)


class TestSupportsReasoningEffort:
    """Test _supports_reasoning_effort() helper."""

    def test_gpt52(self):
        assert _supports_reasoning_effort("gpt-5.2") is True

    def test_gpt52_chat(self):
        assert _supports_reasoning_effort("gpt-5.2-chat") is True

    def test_gpt52_codex(self):
        assert _supports_reasoning_effort("gpt-5.2-codex") is True

    def test_gpt52_pro(self):
        assert _supports_reasoning_effort("gpt-5.2-pro") is True

    def test_gpt53_codex(self):
        assert _supports_reasoning_effort("gpt-5.3-codex") is True

    def test_gpt510_chat(self):
        assert _supports_reasoning_effort("gpt-5.10-chat") is True

    def test_gpt5_no(self):
        assert _supports_reasoning_effort("gpt-5") is False

    def test_gpt51_no(self):
        assert _supports_reasoning_effort("gpt-5.1") is False

    def test_gpt5_mini_no(self):
        assert _supports_reasoning_effort("gpt-5-mini") is False

    def test_gpt4o_no(self):
        assert _supports_reasoning_effort("gpt-4o") is False


class TestDetectThinkingBudget:
    """Test detect_thinking_budget() keyword detection."""

    def _make_config(self, mode="auto", provider=Provider.ANTHROPIC, **kwargs):
        return AppConfig(
            provider=provider,
            anthropic=AnthropicConfig(model_id="claude-sonnet-4-6"),
            reasoning=ReasoningConfig(mode=mode, **kwargs),
        )

    def test_detect_thinking_budget_think(self):
        config = self._make_config()
        assert detect_thinking_budget("please think about this", config) == 4_000

    def test_detect_thinking_budget_think_hard(self):
        config = self._make_config()
        assert detect_thinking_budget("think hard about this", config) == 10_000

    def test_detect_thinking_budget_think_harder(self):
        config = self._make_config()
        assert detect_thinking_budget("think harder", config) == 30_000

    def test_detect_thinking_budget_ultrathink(self):
        config = self._make_config()
        assert detect_thinking_budget("ultrathink", config) == 30_000

    def test_detect_thinking_budget_megathink(self):
        config = self._make_config()
        assert detect_thinking_budget("megathink", config) == 10_000

    def test_detect_thinking_budget_japanese_think(self):
        config = self._make_config()
        assert detect_thinking_budget("考えて", config) == 4_000

    def test_detect_thinking_budget_japanese_hard(self):
        config = self._make_config()
        assert detect_thinking_budget("よく考えて", config) == 10_000

    def test_detect_thinking_budget_japanese_harder(self):
        config = self._make_config()
        assert detect_thinking_budget("熟考して", config) == 30_000

    def test_detect_thinking_budget_no_keyword_on(self):
        config = self._make_config(mode="on")
        assert detect_thinking_budget("hello world", config) == 10_000

    def test_detect_thinking_budget_no_keyword_auto(self):
        # auto_level=1 (default) → level1 budget even without keywords
        config = self._make_config(mode="auto")
        assert detect_thinking_budget("hello world", config) == 4_000

    def test_detect_thinking_budget_no_keyword_auto_level0(self):
        config = self._make_config(mode="auto", auto_level=0)
        assert detect_thinking_budget("hello world", config) is None

    def test_detect_thinking_budget_off_mode(self):
        config = self._make_config(mode="off")
        assert detect_thinking_budget("think hard", config) is None

    def test_detect_thinking_budget_bedrock_claude(self):
        # Default bedrock model (claude-sonnet-4-6) now supports thinking via catalog
        config = AppConfig(
            provider=Provider.BEDROCK,
            reasoning=ReasoningConfig(mode="on"),
        )
        assert detect_thinking_budget("think hard", config) == 10_000

    def test_detect_thinking_budget_ollama(self):
        config = AppConfig(
            provider=Provider.OLLAMA,
            reasoning=ReasoningConfig(mode="on"),
        )
        assert detect_thinking_budget("think hard", config) is None

    def test_detect_thinking_budget_custom_keywords(self):
        config = self._make_config(
            keywords={"level1": ["ponder"], "level3": ["深思"]},
            auto_level=0,
        )
        # Custom level1 keyword
        assert detect_thinking_budget("ponder this", config) == 4_000
        # Original level1 keyword replaced — should not match level1
        # auto_level=0 so no fallback
        assert detect_thinking_budget("think about it", config) is None
        # Custom level3 keyword
        assert detect_thinking_budget("深思してください", config) == 30_000
        # Default level2 still works (not overridden)
        assert detect_thinking_budget("megathink", config) == 10_000

    def test_apply_yaml_reasoning_keywords(self):
        config = AppConfig()
        _apply_yaml(config, {
            "reasoning": {
                "mode": "auto",
                "keywords": {
                    "level1": ["think"],
                    "level2": ["think hard"],
                    "level3": ["ultrathink"],
                    "level4": ["invalid"],  # ignored
                },
            },
        })
        assert config.reasoning.keywords == {
            "level1": ["think"],
            "level2": ["think hard"],
            "level3": ["ultrathink"],
        }


class TestDetectReasoningLevel:
    """Test detect_reasoning_level() for both Anthropic and Azure OpenAI."""

    def _make_config(self, mode="auto", provider=Provider.ANTHROPIC, **kwargs):
        if provider == Provider.AZURE_OPENAI:
            return AppConfig(
                provider=provider,
                azure_openai=AzureOpenAIConfig(model_id=kwargs.pop("model_id", "gpt-5.2")),
                reasoning=ReasoningConfig(mode=mode, **kwargs),
            )
        return AppConfig(
            provider=provider,
            anthropic=AnthropicConfig(model_id="claude-sonnet-4-6"),
            reasoning=ReasoningConfig(mode=mode, **kwargs),
        )

    def test_anthropic_level1_keyword(self):
        config = self._make_config()
        assert detect_reasoning_level("please think about this", config) == "level1"

    def test_anthropic_mode_on_default(self):
        config = self._make_config(mode="on")
        assert detect_reasoning_level("hello world", config) == "level2"

    def test_azure_openai_level1_keyword(self):
        config = self._make_config(provider=Provider.AZURE_OPENAI)
        assert detect_reasoning_level("please think about this", config) == "level1"

    def test_azure_openai_level3_keyword(self):
        config = self._make_config(provider=Provider.AZURE_OPENAI)
        assert detect_reasoning_level("ultrathink", config) == "level3"

    def test_azure_openai_mode_on_default(self):
        config = self._make_config(mode="on", provider=Provider.AZURE_OPENAI)
        assert detect_reasoning_level("hello world", config) == "level2"

    def test_azure_openai_mode_off(self):
        config = self._make_config(mode="off", provider=Provider.AZURE_OPENAI)
        assert detect_reasoning_level("think hard", config) is None

    def test_azure_openai_unsupported_model(self):
        # gpt-4o is not in the catalog with supports_reasoning
        config = self._make_config(
            mode="on", provider=Provider.AZURE_OPENAI, model_id="gpt-4o",
        )
        assert detect_reasoning_level("think hard", config) is None

    def test_auto_level_zero_no_keyword(self):
        config = self._make_config(auto_level=0)
        assert detect_reasoning_level("hello world", config) is None

    def test_auto_level_one_no_keyword(self):
        config = self._make_config(auto_level=1)
        assert detect_reasoning_level("hello world", config) == "level1"

    def test_auto_level_three_no_keyword(self):
        config = self._make_config(auto_level=3)
        assert detect_reasoning_level("hello world", config) == "level3"

    def test_auto_level_keyword_overrides(self):
        # Keyword should take priority over auto_level
        config = self._make_config(auto_level=1)
        assert detect_reasoning_level("ultrathink", config) == "level3"
