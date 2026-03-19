"""Credential provisioning for Hooty.

Provides setup-code generation/decoding, encrypted credential storage,
and application of credentials to AppConfig.
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import platform
import secrets
import stat
import struct
import time
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_SETUP_CODE_PREFIX = "HOOTY1:"
_CRED_FILE_MAGIC = b"HCR1"
_CRED_FILE_NAME = ".credentials"
_PBKDF2_ITERATIONS = 480_000
_SALT_LENGTH = 16



class CredentialExpiredError(Exception):
    """Raised when stored credentials have expired."""


# ---------------------------------------------------------------------------
# Credential secret store (never placed in os.environ)
# ---------------------------------------------------------------------------

# Secrets from the credential system are stored here, NOT in os.environ,
# so they cannot leak to child processes (shell commands, hooks, etc.).
_credential_secrets: dict[str, str] = {}


def set_credential_secret(key: str, value: str) -> None:
    """Store a credential-provided secret (does NOT touch os.environ)."""
    _credential_secrets[key] = value


def get_secret(key: str) -> str | None:
    """Look up a secret: credential store first, then os.environ.

    This is the single entry point for reading API keys / tokens.
    - Credential-provided values are invisible to child processes.
    - User-set environment variables are still honoured as fallback.
    """
    return _credential_secrets.get(key) or os.environ.get(key)


def get_credential_secret_keys() -> frozenset[str]:
    """Return the set of keys stored in the credential secret store."""
    return frozenset(_credential_secrets)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ProviderCredential:
    """Per-provider config and secrets."""

    config: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class CredentialPayload:
    """Full credential payload supporting multiple providers."""

    version: int = 2
    default_profile: str = ""
    providers: dict[str, ProviderCredential] = field(default_factory=dict)
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    extra_config: dict[str, Any] = field(default_factory=dict)
    expires_at: float | None = None  # Unix timestamp, None = no expiry

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CredentialPayload:
        providers = {}
        for name, pdata in data.get("providers", {}).items():
            providers[name] = ProviderCredential(
                config=pdata.get("config", {}),
                env=pdata.get("env", {}),
            )
        # Support both v1 (default_provider) and v2 (default_profile)
        default_profile = data.get("default_profile", "")
        if not default_profile:
            default_profile = data.get("default_provider", "")
        return cls(
            version=data.get("version", 2),
            default_profile=default_profile,
            providers=providers,
            profiles=data.get("profiles", {}),
            extra_config=data.get("extra_config", {}),
            expires_at=data.get("expires_at"),
        )


# ---------------------------------------------------------------------------
# Crypto helpers (require cryptography)
# ---------------------------------------------------------------------------

def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte Fernet key from a passphrase and salt via PBKDF2."""
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    raw = kdf.derive(passphrase.encode())
    return base64.urlsafe_b64encode(raw)


def _machine_passphrase() -> str:
    """Derive a machine-bound passphrase from hostname + username."""
    hostname = platform.node()
    username = getpass.getuser()
    return f"hooty-machine:{hostname}:{username}"


# ---------------------------------------------------------------------------
# Setup code: generate / decode / needs_passphrase
# ---------------------------------------------------------------------------

def generate_setup_code(
    payload: CredentialPayload,
    passphrase: str | None = None,
) -> tuple[str, str]:
    """Encode a CredentialPayload into a setup code string.

    If *passphrase* is None a random passphrase is generated automatically.
    Returns ``(setup_code, passphrase_used)``.
    """
    from cryptography.fernet import Fernet

    actual_passphrase = passphrase if passphrase is not None else secrets.token_urlsafe(16)

    flags = 0x01
    salt = os.urandom(_SALT_LENGTH)
    fernet_key = _derive_key(actual_passphrase, salt)
    fernet = Fernet(fernet_key)

    json_bytes = json.dumps(payload.to_dict(), separators=(",", ":")).encode()
    compressed = zlib.compress(json_bytes)
    encrypted = fernet.encrypt(compressed)

    # Wire format: flags(1 byte) + salt(16 bytes) + encrypted
    blob = struct.pack("B", flags) + salt + encrypted
    encoded = base64.urlsafe_b64encode(blob).decode().rstrip("=")
    return _SETUP_CODE_PREFIX + encoded, actual_passphrase


def decode_setup_code(
    code: str,
    passphrase: str,
) -> CredentialPayload:
    """Decode a setup code string back to a CredentialPayload."""
    from cryptography.fernet import Fernet, InvalidToken

    if not code.startswith(_SETUP_CODE_PREFIX):
        raise ValueError("Invalid setup code: missing HOOTY1: prefix")

    b64 = code[len(_SETUP_CODE_PREFIX):]
    padded = b64 + "=" * (-len(b64) % 4)
    blob = base64.urlsafe_b64decode(padded)

    if len(blob) < 1 + _SALT_LENGTH:
        raise ValueError("Invalid setup code: too short")

    flags = blob[0]
    if not (flags & 0x01):
        raise ValueError("Invalid setup code: unsupported flag (legacy simple mode)")

    salt = blob[1: 1 + _SALT_LENGTH]
    encrypted = blob[1 + _SALT_LENGTH:]

    fernet_key = _derive_key(passphrase, salt)
    fernet = Fernet(fernet_key)

    try:
        compressed = fernet.decrypt(encrypted)
    except InvalidToken:
        raise ValueError("Decryption failed: invalid passphrase or corrupted code")

    json_bytes = zlib.decompress(compressed)
    data = json.loads(json_bytes)
    return CredentialPayload.from_dict(data)


# ---------------------------------------------------------------------------
# .credentials file: save / load / clear
# ---------------------------------------------------------------------------

def _credentials_path() -> Path:
    return Path.home() / ".hooty" / _CRED_FILE_NAME


def save_credentials(payload: CredentialPayload) -> Path:
    """Encrypt and save payload to ~/.hooty/.credentials."""
    from cryptography.fernet import Fernet

    path = _credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    salt = os.urandom(_SALT_LENGTH)
    passphrase = _machine_passphrase()
    fernet_key = _derive_key(passphrase, salt)
    fernet = Fernet(fernet_key)

    json_bytes = json.dumps(payload.to_dict(), separators=(",", ":")).encode()
    compressed = zlib.compress(json_bytes)
    encrypted = fernet.encrypt(compressed)

    # File format: magic(4) + salt(16) + encrypted
    from hooty.concurrency import atomic_write_bytes

    data = _CRED_FILE_MAGIC + salt + encrypted
    atomic_write_bytes(path, data)

    # Owner-only read/write
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # Windows may not support chmod

    return path


def load_credentials() -> Optional[CredentialPayload]:
    """Load and decrypt ~/.hooty/.credentials. Returns None if absent."""
    from cryptography.fernet import Fernet, InvalidToken

    path = _credentials_path()
    if not path.exists():
        return None

    data = path.read_bytes()
    if not data.startswith(_CRED_FILE_MAGIC):
        return None

    offset = len(_CRED_FILE_MAGIC)
    if len(data) < offset + _SALT_LENGTH:
        return None

    salt = data[offset: offset + _SALT_LENGTH]
    encrypted = data[offset + _SALT_LENGTH:]

    passphrase = _machine_passphrase()
    fernet_key = _derive_key(passphrase, salt)
    fernet = Fernet(fernet_key)

    try:
        compressed = fernet.decrypt(encrypted)
    except InvalidToken:
        return None

    json_bytes = zlib.decompress(compressed)
    payload = CredentialPayload.from_dict(json.loads(json_bytes))
    if payload.expires_at is not None and time.time() > payload.expires_at:
        raise CredentialExpiredError(
            f"Credentials expired on {datetime.fromtimestamp(payload.expires_at).strftime('%Y-%m-%d %H:%M')}"
        )
    return payload


def clear_credentials() -> bool:
    """Delete ~/.hooty/.credentials. Returns True if file existed."""
    path = _credentials_path()
    if path.exists():
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# Apply credentials to AppConfig
# ---------------------------------------------------------------------------

def apply_credentials(payload: CredentialPayload, config: "AppConfig") -> None:  # noqa: F821
    """Apply all providers' config and env from the credential payload."""
    from hooty.config import ProfileConfig, Provider

    # Apply per-provider config and env
    for provider_name, cred in payload.providers.items():
        _apply_provider_config(provider_name, cred, config)
        for key, value in cred.env.items():
            set_credential_secret(key, value)
        # Store provider-level env vars for profile activation
        if cred.env:
            config.provider_env[provider_name] = dict(cred.env)

    # Apply profiles from credentials
    for name, pdata in payload.profiles.items():
        if "provider" not in pdata or "model_id" not in pdata:
            continue
        try:
            provider = Provider(pdata["provider"])
        except ValueError:
            continue
        profile = ProfileConfig(
            provider=provider,
            model_id=pdata["model_id"],
            region=pdata.get("region"),
            endpoint=pdata.get("endpoint"),
            deployment=pdata.get("deployment"),
            api_version=pdata.get("api_version"),
            sso_auth=pdata.get("sso_auth"),
            max_input_tokens=pdata.get("max_input_tokens"),
            base_url=pdata.get("base_url"),
        )
        config.profiles[name] = profile

    # Set default profile
    if payload.default_profile:
        config.active_profile = payload.default_profile

    # Apply extra_config
    if "stream" in payload.extra_config:
        config.stream = bool(payload.extra_config["stream"])
    if "roles" in payload.extra_config:
        roles = payload.extra_config["roles"]
        if "planning" in roles:
            config.roles.planning = roles["planning"]
        if "coding" in roles:
            config.roles.coding = roles["coding"]


def _apply_provider_config(
    provider_name: str, cred: ProviderCredential, config: "AppConfig",  # noqa: F821
) -> None:
    """Apply a single provider's config fields to AppConfig."""
    cfg = cred.config
    if provider_name == "anthropic":
        if "model_id" in cfg:
            config.anthropic.model_id = cfg["model_id"]
        if "base_url" in cfg:
            config.anthropic.base_url = cfg["base_url"]
        if "max_input_tokens" in cfg:
            config.anthropic.max_input_tokens = cfg["max_input_tokens"]
    elif provider_name == "bedrock":
        if "model_id" in cfg:
            config.bedrock.model_id = cfg["model_id"]
        if "region" in cfg:
            config.bedrock.region = cfg["region"]
        if "sso_auth" in cfg:
            config.bedrock.sso_auth = cfg["sso_auth"]
        if "max_input_tokens" in cfg:
            config.bedrock.max_input_tokens = cfg["max_input_tokens"]
    elif provider_name == "azure":
        if "model_id" in cfg:
            config.azure.model_id = cfg["model_id"]
        if "endpoint" in cfg:
            config.azure.endpoint = cfg["endpoint"]
        if "api_version" in cfg:
            config.azure.api_version = cfg["api_version"]
        if "max_input_tokens" in cfg:
            config.azure.max_input_tokens = cfg["max_input_tokens"]
    elif provider_name == "azure_openai":
        if "model_id" in cfg:
            config.azure_openai.model_id = cfg["model_id"]
        if "endpoint" in cfg:
            config.azure_openai.endpoint = cfg["endpoint"]
        if "deployment" in cfg:
            config.azure_openai.deployment = cfg["deployment"]
        if "api_version" in cfg:
            config.azure_openai.api_version = cfg["api_version"]
        if "max_input_tokens" in cfg:
            config.azure_openai.max_input_tokens = cfg["max_input_tokens"]


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------

def credential_status() -> Optional[dict[str, Any]]:
    """Return a summary of stored credentials. None if absent.

    Catches CredentialExpiredError to report expiry status instead of raising.
    """
    try:
        payload = load_credentials()
    except CredentialExpiredError as e:
        # Still return summary with expired flag
        return {"expired": True, "error": str(e)}

    if payload is None:
        return None

    summary: dict[str, Any] = {
        "default_profile": payload.default_profile,
        "profiles": list(payload.profiles.keys()),
    }
    if payload.expires_at is not None:
        summary["expires_at"] = payload.expires_at
    return summary
