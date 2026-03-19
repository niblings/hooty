"""Tests for Hooty credential provisioning."""

import os
import time

import pytest

from hooty.config import AppConfig, Provider, load_config
from hooty.credentials import (
    CredentialExpiredError,
    CredentialPayload,
    ProviderCredential,
    _credential_secrets,
    apply_credentials,
    clear_credentials,
    credential_status,
    decode_setup_code,
    generate_setup_code,
    get_secret,
    load_credentials,
    save_credentials,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_payload() -> CredentialPayload:
    """Build a multi-provider payload for testing."""
    return CredentialPayload(
        version=2,
        default_profile="az-sonnet",
        providers={
            "azure": ProviderCredential(
                config={"endpoint": "https://az.example.com"},
                env={"AZURE_API_KEY": "sk-test-azure-key-12345678"},
            ),
            "bedrock": ProviderCredential(
                config={"region": "us-west-2"},
                env={"AWS_BEARER_TOKEN_BEDROCK": "br-test-bearer-token-999"},
            ),
        },
        profiles={
            "az-sonnet": {"provider": "azure", "model_id": "claude-sonnet-4-6"},
            "sonnet": {"provider": "bedrock", "model_id": "global.anthropic.claude-sonnet-4-6"},
        },
        extra_config={"stream": True},
    )


def _minimal_payload() -> CredentialPayload:
    return CredentialPayload(
        version=2,
        default_profile="sonnet",
        providers={
            "bedrock": ProviderCredential(
                config={"region": "us-east-1"},
                env={"AWS_BEARER_TOKEN_BEDROCK": "br-mini"},
            ),
        },
        profiles={
            "sonnet": {"provider": "bedrock", "model_id": "anthropic.claude-3"},
        },
    )


# ---------------------------------------------------------------------------
# Setup code round-trip
# ---------------------------------------------------------------------------

class TestSetupCodeRoundTrip:
    """Encode → decode preserves payload exactly."""

    def test_auto_passphrase_round_trip(self):
        payload = _sample_payload()
        code, passphrase_used = generate_setup_code(payload)
        assert code.startswith("HOOTY1:")
        assert passphrase_used  # non-empty
        decoded = decode_setup_code(code, passphrase=passphrase_used)
        assert decoded.version == payload.version
        assert decoded.default_profile == payload.default_profile
        assert set(decoded.providers.keys()) == set(payload.providers.keys())
        for name in payload.providers:
            assert decoded.providers[name].config == payload.providers[name].config
            assert decoded.providers[name].env == payload.providers[name].env
        assert decoded.profiles == payload.profiles
        assert decoded.extra_config == payload.extra_config

    def test_passphrase_mode_round_trip(self):
        payload = _sample_payload()
        code, passphrase_used = generate_setup_code(payload, passphrase="s3cret!")
        assert passphrase_used == "s3cret!"
        decoded = decode_setup_code(code, passphrase="s3cret!")
        assert decoded.default_profile == "az-sonnet"
        assert decoded.providers["azure"].env["AZURE_API_KEY"] == "sk-test-azure-key-12345678"

    def test_minimal_payload_round_trip(self):
        payload = _minimal_payload()
        code, passphrase_used = generate_setup_code(payload)
        decoded = decode_setup_code(code, passphrase=passphrase_used)
        assert decoded.default_profile == "sonnet"
        assert "bedrock" in decoded.providers
        assert decoded.profiles == {"sonnet": {"provider": "bedrock", "model_id": "anthropic.claude-3"}}

    def test_empty_extra_config(self):
        payload = CredentialPayload(
            version=2,
            default_profile="test",
            providers={"azure": ProviderCredential(config={"endpoint": "https://x"}, env={})},
            profiles={"test": {"provider": "azure", "model_id": "y"}},
        )
        code, passphrase_used = generate_setup_code(payload)
        decoded = decode_setup_code(code, passphrase=passphrase_used)
        assert decoded.extra_config == {}

    def test_auto_passphrase_is_unique(self):
        payload = _sample_payload()
        _, p1 = generate_setup_code(payload)
        _, p2 = generate_setup_code(payload)
        assert p1 != p2


class TestSetupCodeErrors:
    def test_bad_prefix(self):
        with pytest.raises(ValueError, match="prefix"):
            decode_setup_code("BADPREFIX:abc", passphrase="x")

    def test_wrong_passphrase(self):
        code, _ = generate_setup_code(_sample_payload(), passphrase="correct")
        with pytest.raises(ValueError, match="Decryption failed"):
            decode_setup_code(code, passphrase="wrong")

    def test_truncated_code(self):
        code, _ = generate_setup_code(_sample_payload())
        # Truncate heavily
        with pytest.raises((ValueError, Exception)):
            decode_setup_code(code[:15], passphrase="x")


# ---------------------------------------------------------------------------
# .credentials file operations
# ---------------------------------------------------------------------------

class TestCredentialFile:
    def test_save_and_load(self, tmp_path, monkeypatch):
        cred_path = tmp_path / ".credentials"
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        payload = _sample_payload()
        save_credentials(payload)

        assert cred_path.exists()
        assert cred_path.read_bytes()[:4] == b"HCR1"

        loaded = load_credentials()
        assert loaded is not None
        assert loaded.default_profile == "az-sonnet"
        assert loaded.providers["azure"].env["AZURE_API_KEY"] == "sk-test-azure-key-12345678"
        assert loaded.profiles == payload.profiles

    def test_load_missing_file(self, tmp_path, monkeypatch):
        cred_path = tmp_path / ".credentials"
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)
        assert load_credentials() is None

    def test_clear_existing(self, tmp_path, monkeypatch):
        cred_path = tmp_path / ".credentials"
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        save_credentials(_sample_payload())
        assert cred_path.exists()
        assert clear_credentials() is True
        assert not cred_path.exists()

    def test_clear_missing(self, tmp_path, monkeypatch):
        cred_path = tmp_path / ".credentials"
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)
        assert clear_credentials() is False

    def test_machine_binding(self, tmp_path, monkeypatch):
        """File saved on one machine cannot be loaded with different machine identity."""
        cred_path = tmp_path / ".credentials"
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        save_credentials(_sample_payload())

        # Simulate different machine
        monkeypatch.setattr("hooty.credentials._machine_passphrase", lambda: "different-machine:host2:user2")
        assert load_credentials() is None

    def test_corrupted_magic(self, tmp_path, monkeypatch):
        cred_path = tmp_path / ".credentials"
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)
        cred_path.write_bytes(b"BADM" + b"\x00" * 100)
        assert load_credentials() is None


# ---------------------------------------------------------------------------
# apply_credentials
# ---------------------------------------------------------------------------

class TestApplyCredentials:
    def test_sets_default_profile(self):
        config = AppConfig()
        payload = _sample_payload()
        apply_credentials(payload, config)
        assert config.active_profile == "az-sonnet"

    def test_sets_azure_config(self):
        config = AppConfig()
        payload = _sample_payload()
        apply_credentials(payload, config)
        assert config.azure.endpoint == "https://az.example.com"

    def test_sets_bedrock_config(self):
        config = AppConfig()
        payload = _sample_payload()
        apply_credentials(payload, config)
        assert config.bedrock.region == "us-west-2"

    def test_injects_env_to_credential_store(self, monkeypatch, clean_env):
        """Credential env vars go into secret store, not os.environ."""
        config = AppConfig()
        payload = _sample_payload()
        apply_credentials(payload, config)
        # Available via get_secret()
        assert get_secret("AZURE_API_KEY") == "sk-test-azure-key-12345678"
        assert get_secret("AWS_BEARER_TOKEN_BEDROCK") == "br-test-bearer-token-999"
        # Must NOT be in os.environ (prevents leaking to child processes)
        assert "AZURE_API_KEY" not in os.environ
        assert "AWS_BEARER_TOKEN_BEDROCK" not in os.environ
        # Cleanup
        _credential_secrets.pop("AZURE_API_KEY", None)
        _credential_secrets.pop("AWS_BEARER_TOKEN_BEDROCK", None)

    def test_get_secret_falls_back_to_environ(self, monkeypatch, clean_env):
        """get_secret() returns os.environ value when not in credential store."""
        monkeypatch.setenv("AZURE_API_KEY", "user-own-key")
        assert get_secret("AZURE_API_KEY") == "user-own-key"

    def test_credential_secret_takes_precedence(self, monkeypatch, clean_env):
        """Credential store takes precedence over os.environ."""
        monkeypatch.setenv("AZURE_API_KEY", "user-own-key")
        config = AppConfig()
        payload = _sample_payload()
        apply_credentials(payload, config)
        assert get_secret("AZURE_API_KEY") == "sk-test-azure-key-12345678"
        # os.environ still has the user's own key (untouched)
        assert os.environ["AZURE_API_KEY"] == "user-own-key"
        # Cleanup
        _credential_secrets.pop("AZURE_API_KEY", None)
        _credential_secrets.pop("AWS_BEARER_TOKEN_BEDROCK", None)

    def test_applies_extra_config_stream(self):
        config = AppConfig(stream=False)
        payload = CredentialPayload(
            version=2,
            default_profile="",
            providers={},
            extra_config={"stream": True},
        )
        apply_credentials(payload, config)
        assert config.stream is True

    def test_applies_profiles_from_credentials(self):
        config = AppConfig()
        payload = _sample_payload()
        apply_credentials(payload, config)
        assert "az-sonnet" in config.profiles
        assert "sonnet" in config.profiles
        assert config.profiles["az-sonnet"].provider == Provider.AZURE
        assert config.profiles["az-sonnet"].model_id == "claude-sonnet-4-6"

    def test_stores_provider_env_for_activation(self, monkeypatch, clean_env):
        config = AppConfig()
        payload = _sample_payload()
        apply_credentials(payload, config)
        assert "bedrock" in config.provider_env
        assert config.provider_env["bedrock"]["AWS_BEARER_TOKEN_BEDROCK"] == "br-test-bearer-token-999"

    def test_applies_azure_openai_config(self):
        config = AppConfig()
        payload = CredentialPayload(
            version=2,
            default_profile="gpt52",
            providers={
                "azure_openai": ProviderCredential(
                    config={
                        "endpoint": "https://oai.example.com",
                        "api_version": "2025-01-01",
                    },
                    env={"AZURE_OPENAI_API_KEY": "aoai-key"},
                ),
            },
            profiles={
                "gpt52": {
                    "provider": "azure_openai",
                    "model_id": "gpt-5.2",
                    "deployment": "gpt-5.2-deploy",
                },
            },
        )
        apply_credentials(payload, config)
        assert config.active_profile == "gpt52"
        assert config.azure_openai.endpoint == "https://oai.example.com"
        assert "gpt52" in config.profiles
        assert config.profiles["gpt52"].model_id == "gpt-5.2"

    def test_invalid_default_profile_ignored(self):
        config = AppConfig()
        payload = CredentialPayload(
            version=2,
            default_profile="nonexistent",
            providers={},
        )
        # Should not raise; invalid default_profile is stored but won't activate
        apply_credentials(payload, config)
        assert config.active_profile == "nonexistent"


# ---------------------------------------------------------------------------
# credential_status
# ---------------------------------------------------------------------------

class TestCredentialStatus:
    def test_status_with_stored_creds(self, tmp_path, monkeypatch):
        cred_path = tmp_path / ".credentials"
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        save_credentials(_sample_payload())
        status = credential_status()

        assert status is not None
        assert status["default_profile"] == "az-sonnet"
        assert "az-sonnet" in status["profiles"]
        assert "sonnet" in status["profiles"]

    def test_status_no_creds(self, tmp_path, monkeypatch):
        cred_path = tmp_path / ".credentials"
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)
        assert credential_status() is None


# ---------------------------------------------------------------------------
# Integration: load_config reads .credentials
# ---------------------------------------------------------------------------

class TestLoadConfigIntegration:
    def test_credentials_loaded_at_lowest_priority(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        cred_path = config_dir / ".credentials"

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_dir / "config.yaml"))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        # Save credentials
        payload = _sample_payload()
        save_credentials(payload)

        config = load_config()
        assert config.active_profile == "az-sonnet"
        assert config.azure.endpoint == "https://az.example.com"
        # Credential secrets available via get_secret(), not in os.environ
        assert get_secret("AZURE_API_KEY") == "sk-test-azure-key-12345678"
        assert "AZURE_API_KEY" not in os.environ
        assert config.credentials_active is True
        # Profile should be activated
        assert config.provider == Provider.AZURE
        assert config.azure.model_id == "claude-sonnet-4-6"

    def test_yaml_overrides_credentials(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        cred_path = config_dir / ".credentials"

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_dir / "config.yaml"))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        # Save credentials with azure endpoint
        payload = _sample_payload()
        save_credentials(payload)

        # Write YAML that overrides endpoint
        import yaml
        (config_dir / "config.yaml").write_text(
            yaml.dump({
                "providers": {
                    "azure": {"endpoint": "https://yaml-override.example.com"},
                },
            })
        )

        config = load_config()
        assert config.azure.endpoint == "https://yaml-override.example.com"

    def test_env_overrides_credentials(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        cred_path = config_dir / ".credentials"

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_dir / "config.yaml"))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        # Credentials set AZURE_API_KEY via setdefault
        payload = _sample_payload()
        save_credentials(payload)

        # But env var already set → should NOT be overwritten
        monkeypatch.setenv("AZURE_API_KEY", "env-wins")

        load_config()
        assert os.environ["AZURE_API_KEY"] == "env-wins"

    def test_no_credentials_file_graceful(self, tmp_path, monkeypatch, clean_env):
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        cred_path = config_dir / ".credentials"

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_dir / "config.yaml"))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        # Should not fail even without .credentials
        config = load_config()
        assert config.provider == Provider.BEDROCK  # default
        assert config.credentials_active is False


# ---------------------------------------------------------------------------
# Payload serialization
# ---------------------------------------------------------------------------

class TestPayloadSerialization:
    def test_to_dict_and_from_dict(self):
        payload = _sample_payload()
        d = payload.to_dict()
        restored = CredentialPayload.from_dict(d)
        assert restored.version == payload.version
        assert restored.default_profile == payload.default_profile
        assert set(restored.providers.keys()) == set(payload.providers.keys())
        assert restored.profiles == payload.profiles

    def test_from_dict_missing_fields(self):
        data = {"version": 2}
        payload = CredentialPayload.from_dict(data)
        assert payload.default_profile == ""
        assert payload.providers == {}
        assert payload.profiles == {}
        assert payload.extra_config == {}

    def test_from_dict_v1_backward_compat(self):
        """v1 payloads with default_provider should be read as default_profile."""
        data = {
            "version": 1,
            "default_provider": "bedrock",
            "providers": {
                "bedrock": {
                    "config": {"region": "us-east-1"},
                    "env": {"AWS_BEARER_TOKEN_BEDROCK": "tok"},
                },
            },
        }
        payload = CredentialPayload.from_dict(data)
        assert payload.default_profile == "bedrock"
        assert "bedrock" in payload.providers

    def test_expires_at_round_trip(self):
        """expires_at survives to_dict / from_dict round-trip."""
        ts = time.time() + 86400
        payload = CredentialPayload(expires_at=ts)
        d = payload.to_dict()
        assert d["expires_at"] == ts
        restored = CredentialPayload.from_dict(d)
        assert restored.expires_at == ts

    def test_expires_at_none_by_default(self):
        data = {"version": 2}
        payload = CredentialPayload.from_dict(data)
        assert payload.expires_at is None


# ---------------------------------------------------------------------------
# Credential expiry
# ---------------------------------------------------------------------------

class TestCredentialExpiry:
    def test_expired_credential_raises(self, tmp_path, monkeypatch):
        """load_credentials raises CredentialExpiredError when expired."""
        cred_path = tmp_path / ".credentials"
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        payload = _minimal_payload()
        payload.expires_at = time.time() - 3600  # expired 1 hour ago
        save_credentials(payload)

        with pytest.raises(CredentialExpiredError, match="expired"):
            load_credentials()

    def test_valid_credential_loads(self, tmp_path, monkeypatch):
        """load_credentials succeeds when expires_at is in the future."""
        cred_path = tmp_path / ".credentials"
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        payload = _minimal_payload()
        payload.expires_at = time.time() + 86400  # expires in 1 day
        save_credentials(payload)

        loaded = load_credentials()
        assert loaded is not None
        assert loaded.default_profile == "sonnet"

    def test_no_expiry_loads(self, tmp_path, monkeypatch):
        """load_credentials succeeds when expires_at is None."""
        cred_path = tmp_path / ".credentials"
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        payload = _minimal_payload()
        assert payload.expires_at is None
        save_credentials(payload)

        loaded = load_credentials()
        assert loaded is not None

    def test_status_shows_expiry(self, tmp_path, monkeypatch):
        """credential_status includes expires_at for valid credentials."""
        cred_path = tmp_path / ".credentials"
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        future = time.time() + 86400 * 30
        payload = _minimal_payload()
        payload.expires_at = future
        save_credentials(payload)

        status = credential_status()
        assert status is not None
        assert status["expires_at"] == future
        assert "profiles" in status

    def test_status_shows_expired(self, tmp_path, monkeypatch):
        """credential_status returns expired flag for expired credentials."""
        cred_path = tmp_path / ".credentials"
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        payload = _minimal_payload()
        payload.expires_at = time.time() - 3600
        save_credentials(payload)

        status = credential_status()
        assert status is not None
        assert status["expired"] is True
        assert "error" in status

    def test_status_no_expiry(self, tmp_path, monkeypatch):
        """credential_status omits expires_at when None."""
        cred_path = tmp_path / ".credentials"
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        payload = _minimal_payload()
        save_credentials(payload)

        status = credential_status()
        assert status is not None
        assert "expires_at" not in status

    def test_load_config_propagates_expired(self, tmp_path, monkeypatch, clean_env):
        """load_config re-raises CredentialExpiredError."""
        config_dir = tmp_path / ".hooty"
        config_dir.mkdir()
        cred_path = config_dir / ".credentials"

        monkeypatch.setattr(AppConfig, "config_file_path", property(lambda self: config_dir / "config.yaml"))
        monkeypatch.setattr(AppConfig, "config_dir", property(lambda self: config_dir))
        monkeypatch.setattr("hooty.credentials._credentials_path", lambda: cred_path)

        payload = _minimal_payload()
        payload.expires_at = time.time() - 3600
        save_credentials(payload)

        with pytest.raises(CredentialExpiredError):
            load_config()
