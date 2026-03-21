"""Configuration management for Hooty."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv


class Provider(str, Enum):
    """Supported LLM providers."""

    ANTHROPIC = "anthropic"
    AZURE = "azure"
    AZURE_OPENAI = "azure_openai"
    BEDROCK = "bedrock"
    OPENAI = "openai"
    OLLAMA = "ollama"


@dataclass
class ProfileConfig:
    """Named model profile."""

    provider: Provider = Provider.BEDROCK
    model_id: str = ""
    # Provider-specific overrides (None = inherit from providers: section)
    region: str | None = None
    endpoint: str | None = None
    deployment: str | None = None
    api_version: str | None = None
    host: str | None = None
    sso_auth: bool | None = None
    max_input_tokens: int | None = None
    base_url: str | None = None


@dataclass
class BedrockConfig:
    """AWS Bedrock provider configuration."""

    model_id: str = "global.anthropic.claude-sonnet-4-6"
    region: str = "us-east-1"
    sso_auth: bool = False
    max_input_tokens: Optional[int] = None


@dataclass
class AnthropicConfig:
    """Anthropic provider configuration (direct API or Azure AI Foundry)."""

    model_id: str = "claude-sonnet-4-6"
    base_url: str = ""          # empty = direct Anthropic API
    max_input_tokens: Optional[int] = None


@dataclass
class AzureConfig:
    """Azure AI Foundry provider configuration."""

    model_id: str = "claude-sonnet-4-6"
    endpoint: str = ""
    api_version: Optional[str] = None
    max_input_tokens: Optional[int] = None


@dataclass
class AzureOpenAIConfig:
    """Azure OpenAI Service provider configuration."""

    model_id: str = "gpt-5.2"
    endpoint: str = ""
    deployment: str = ""
    api_version: str = "2024-10-21"
    max_input_tokens: Optional[int] = None


@dataclass
class OpenAIConfig:
    """OpenAI direct API provider configuration."""

    model_id: str = "gpt-5.2"
    max_input_tokens: Optional[int] = None


@dataclass
class OllamaConfig:
    """Ollama provider configuration (local or Ollama Cloud)."""

    model_id: str = "qwen3.5:9b"
    host: str = ""              # empty = SDK default (localhost:11434)
    api_key: str = ""           # Ollama Cloud; empty = local (no auth)
    max_input_tokens: Optional[int] = None


@dataclass
class ReasoningConfig:
    """Extended thinking (reasoning) configuration."""

    mode: str = "auto"         # "off" | "on" | "auto"
    auto_level: int = 1        # auto mode default level when no keyword (0=off, 1-3)
    keywords: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class ShellOperatorsConfig:
    """Shell operator control for _check_command()."""

    pipe: bool = True       # | with per-segment allowlist validation
    chain: bool = True      # && || ; with per-segment allowlist validation
    redirect: bool = False  # > >> < (blocked by default)


@dataclass
class CaptureConfig:
    """Screen capture configuration."""

    delay_max: int = 30        # max delay seconds
    repeat_max: int = 5        # max sequential captures
    interval_min: int = 5      # min interval seconds
    interval_max: int = 30     # max interval seconds


@dataclass
class AttachmentConfig:
    """Attachment configuration."""

    max_files: int = 20            # max number of attached files
    max_side: int = 1568           # image resize max dimension (Claude recommended)
    large_file_tokens: int = 10000  # warning threshold per text file
    max_total_tokens: int = 50000   # hard limit for all attachments combined
    context_ratio: float = 0.25     # max ratio of context window for attachments
    capture: CaptureConfig = field(default_factory=CaptureConfig)


@dataclass
class AgnoConfig:
    """Agno framework configuration."""

    telemetry: bool = False


@dataclass
class SkillsConfig:
    """Agent Skills configuration."""

    enabled: bool = True


@dataclass
class RolesConfig:
    """Mode-specific role configuration for LLM persona."""

    planning: str | None = None
    coding: str | None = None


@dataclass
class AppConfig:
    """Application configuration."""

    provider: Provider = Provider.BEDROCK
    stream: bool = True
    debug: bool = False
    mcp_debug: bool = False
    working_directory: str = ""

    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    bedrock: BedrockConfig = field(default_factory=BedrockConfig)
    azure: AzureConfig = field(default_factory=AzureConfig)
    azure_openai: AzureOpenAIConfig = field(default_factory=AzureOpenAIConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    mcp: dict[str, dict[str, Any]] = field(default_factory=dict)
    mcp_sources: dict[str, str] = field(default_factory=dict)  # "global" or "project"
    databases: dict[str, str] = field(default_factory=dict)
    active_db: Optional[str] = None
    web_search: bool = False
    web_search_region: str = "jp-jp"  # DuckDuckGo region (e.g., "jp-jp", "us-en")
    github_enabled: bool = False

    roles: RolesConfig = field(default_factory=RolesConfig)
    attachment: AttachmentConfig = field(default_factory=AttachmentConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    agno: AgnoConfig = field(default_factory=AgnoConfig)
    reasoning: ReasoningConfig = field(default_factory=ReasoningConfig)

    # Runtime flag: whether extended thinking is actually active for current provider+model.
    # Set by providers.create_model(), not persisted.
    _reasoning_active: bool = field(default=False, repr=False)

    memory_enabled: bool = True

    auto_compact: bool = True
    auto_compact_threshold: float = 0.7

    resume_history: int = 1  # Number of past Q&A pairs to show on resume (0=disabled)

    profiles: dict[str, ProfileConfig] = field(default_factory=dict)
    active_profile: str = ""
    # Provider-level env vars (loaded from credentials, shared across profiles)
    provider_env: dict[str, dict[str, str]] = field(default_factory=dict)

    credentials_active: bool = False

    awake: tuple[int, int] = (9, 21)

    allowed_commands: list[str] = field(default_factory=list)
    shell_operators: ShellOperatorsConfig = field(default_factory=ShellOperatorsConfig)
    shell_timeout: int = 120
    idle_timeout: int = 0

    ignore_dirs: list[str] = field(default_factory=list)

    add_dirs: list[str] = field(default_factory=list)

    pkg_auto_download: Optional[bool] = None  # None = ask on first run

    cache_system_prompt: bool = True

    # API timeout settings (seconds) — applies to LLM HTTP requests.
    # connect: TCP connection establishment.
    # streaming_read: silence between streaming chunks (TTFT + inter-chunk).
    # read: non-streaming full-response wait.
    api_connect_timeout: int = 30
    api_streaming_read_timeout: int = 180
    api_read_timeout: int = 360

    snapshot_enabled: bool = False

    hooks_enabled: bool = True

    unsafe: bool = False
    non_interactive: bool = False

    session_id: Optional[str] = None
    resume: bool = False
    continue_session: bool = False

    @property
    def config_dir(self) -> Path:
        return Path.home() / ".hooty"

    @property
    def session_db_path(self) -> str:
        return str(self.config_dir / "sessions.db")

    @property
    def global_memory_db_path(self) -> str:
        return str(self.config_dir / "memory.db")

    @property
    def project_dir(self) -> Path:
        return self.config_dir / "projects" / project_dir_name(Path(self.working_directory))

    @property
    def project_memory_db_path(self) -> str:
        return str(self.project_dir / "memory.db")

    @property
    def project_plans_dir(self) -> Path:
        return self.project_dir / "plans"

    @property
    def project_history_dir(self) -> Path:
        return self.project_dir / "history"

    @property
    def skills_state_path(self) -> Path:
        return self.project_dir / ".skills.json"

    @property
    def global_skills_state_path(self) -> Path:
        return self.config_dir / ".skills.json"

    @property
    def hooks_state_path(self) -> Path:
        return self.project_dir / ".hooks.json"

    @property
    def config_file_path(self) -> Path:
        return self.config_dir / "config.yaml"

    @property
    def databases_file_path(self) -> Path:
        return self.config_dir / "databases.yaml"

    @property
    def mcp_file_path(self) -> Path:
        return self.config_dir / "mcp.yaml"

    @property
    def mcp_project_file_path(self) -> Path:
        return Path(self.working_directory) / ".hooty" / "mcp.yaml"

    @property
    def mcp_state_path(self) -> Path:
        return self.project_dir / ".mcp.json"

    @property
    def locks_dir(self) -> Path:
        return self.config_dir / "locks"

    @property
    def session_dir(self) -> Path | None:
        """Per-session directory. None if session_id is not set."""
        if self.session_id is None:
            return None
        return self.config_dir / "sessions" / self.session_id

    @property
    def session_tmp_dir(self) -> Path | None:
        """Per-session temp directory."""
        sd = self.session_dir
        return sd / "tmp" if sd else None

    @property
    def session_plans_dir(self) -> Path | None:
        """Per-session plans directory (deprecated: use project_plans_dir)."""
        sd = self.session_dir
        return sd / "plans" if sd else None

    def activate_profile(self, profile_name: str) -> str | None:
        """Activate a named profile. Returns error message or None."""
        if profile_name not in self.profiles:
            available = ", ".join(sorted(self.profiles.keys()))
            return f"Unknown profile: {profile_name}. Available: {available}"

        profile = self.profiles[profile_name]
        self.provider = profile.provider
        self.active_profile = profile_name

        # Apply model_id and overrides to the provider config
        if profile.provider == Provider.ANTHROPIC:
            self.anthropic.model_id = profile.model_id
            if profile.base_url is not None:
                self.anthropic.base_url = profile.base_url
            if profile.max_input_tokens is not None:
                self.anthropic.max_input_tokens = profile.max_input_tokens
        elif profile.provider == Provider.BEDROCK:
            self.bedrock.model_id = profile.model_id
            if profile.region is not None:
                self.bedrock.region = profile.region
            if profile.sso_auth is not None:
                self.bedrock.sso_auth = profile.sso_auth
            if profile.max_input_tokens is not None:
                self.bedrock.max_input_tokens = profile.max_input_tokens
        elif profile.provider == Provider.AZURE:
            self.azure.model_id = profile.model_id
            if profile.endpoint is not None:
                self.azure.endpoint = profile.endpoint
            if profile.api_version is not None:
                self.azure.api_version = profile.api_version
            if profile.max_input_tokens is not None:
                self.azure.max_input_tokens = profile.max_input_tokens
        elif profile.provider == Provider.AZURE_OPENAI:
            self.azure_openai.model_id = profile.model_id
            if profile.endpoint is not None:
                self.azure_openai.endpoint = profile.endpoint
            # Fallback: use model_id as deployment name when not specified
            if profile.deployment is not None:
                self.azure_openai.deployment = profile.deployment
            else:
                self.azure_openai.deployment = profile.model_id
            if profile.api_version is not None:
                self.azure_openai.api_version = profile.api_version
            if profile.max_input_tokens is not None:
                self.azure_openai.max_input_tokens = profile.max_input_tokens
        elif profile.provider == Provider.OPENAI:
            self.openai.model_id = profile.model_id
            if profile.max_input_tokens is not None:
                self.openai.max_input_tokens = profile.max_input_tokens
        elif profile.provider == Provider.OLLAMA:
            self.ollama.model_id = profile.model_id
            if profile.host is not None:
                self.ollama.host = profile.host
            if profile.max_input_tokens is not None:
                self.ollama.max_input_tokens = profile.max_input_tokens

        # Inject provider-level env vars from credentials into secret store
        # (never into os.environ — prevents leaking to child processes)
        from hooty.credentials import set_credential_secret
        provider_key = profile.provider.value
        for key, value in self.provider_env.get(provider_key, {}).items():
            set_credential_secret(key, value)

        return None

    def save_pkg_auto_download(self, value: bool) -> None:
        """Persist ``pkg.auto_download`` to config.yaml."""
        self.pkg_auto_download = value
        config_path = self.config_file_path
        data: dict = {}
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        data.setdefault("pkg", {})["auto_download"] = value
        from hooty.concurrency import atomic_write_text

        config_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            config_path,
            yaml.safe_dump(data, default_flow_style=False),
        )


def project_dir_name(work_dir: Path) -> str:
    """Derive a unique project directory name."""
    slug = work_dir.name
    digest = hashlib.sha256(
        str(work_dir.resolve()).encode()
    ).hexdigest()[:8]
    return f"{slug}-{digest}"


def owl_eyes(hour: int, awake_start: int = 9, awake_end: int = 21) -> tuple[str, str]:
    """Return (eye_char, eye_color) based on current hour and awake window.

    - awake_start − 1: squinting (waking up)
    - awake_start .. awake_end (inclusive): wide open
    - awake_end + 1: squinting (getting sleepy)
    - otherwise: sleepy
    """
    if hour == (awake_start - 1) % 24 or hour == (awake_end + 1) % 24:
        return ("=", "#9E8600")   # squinting
    elif awake_start <= hour <= awake_end:
        return ("o", "#E6C200")   # wide open
    else:
        return ("ᴗ", "#9E8600")   # half-closed (sleepy)


class ConfigFileError(Exception):
    """Raised when a YAML config file cannot be parsed."""


def _load_yaml_file(path: Path) -> Any:
    """Load and parse a YAML file with a user-friendly error on syntax errors."""
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as exc:
        # Extract line/column info from PyYAML's marks
        parts: list[str] = [f"Failed to parse {path.name}:"]
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            parts.append(f"  line {mark.line + 1}, column {mark.column + 1}")
        problem = getattr(exc, "problem", None)
        if problem:
            parts.append(f"  {problem}")
        context = getattr(exc, "context", None)
        if context:
            parts.append(f"  {context}")
        parts.append(f"\nPlease check: {path}")
        raise ConfigFileError("\n".join(parts)) from None


def _apply_yaml(config: AppConfig, data: dict[str, Any]) -> None:
    """Apply YAML config data to AppConfig."""
    default = data.get("default", {})
    if "profile" in default:
        config.active_profile = default["profile"]
    if "stream" in default:
        config.stream = default["stream"]
    if "debug" in default:
        config.debug = default["debug"]

    providers = data.get("providers", {})

    anthropic = providers.get("anthropic") or {}
    if "model_id" in anthropic:
        config.anthropic.model_id = anthropic["model_id"]
    if "base_url" in anthropic:
        config.anthropic.base_url = anthropic["base_url"]
    if "max_input_tokens" in anthropic:
        config.anthropic.max_input_tokens = anthropic["max_input_tokens"]

    bedrock = providers.get("bedrock", {})
    if "model_id" in bedrock:
        config.bedrock.model_id = bedrock["model_id"]
    if "region" in bedrock:
        config.bedrock.region = bedrock["region"]
    if "sso_auth" in bedrock:
        config.bedrock.sso_auth = bedrock["sso_auth"]
    if "max_input_tokens" in bedrock:
        config.bedrock.max_input_tokens = bedrock["max_input_tokens"]

    azure = providers.get("azure", {})
    if "model_id" in azure:
        config.azure.model_id = azure["model_id"]
    if "endpoint" in azure:
        config.azure.endpoint = azure["endpoint"]
    if "api_version" in azure:
        config.azure.api_version = azure["api_version"]
    if "max_input_tokens" in azure:
        config.azure.max_input_tokens = azure["max_input_tokens"]

    azure_openai = providers.get("azure_openai", {})
    if "model_id" in azure_openai:
        config.azure_openai.model_id = azure_openai["model_id"]
    if "endpoint" in azure_openai:
        config.azure_openai.endpoint = azure_openai["endpoint"]
    if "deployment" in azure_openai:
        config.azure_openai.deployment = azure_openai["deployment"]
    if "api_version" in azure_openai:
        config.azure_openai.api_version = azure_openai["api_version"]
    if "max_input_tokens" in azure_openai:
        config.azure_openai.max_input_tokens = azure_openai["max_input_tokens"]

    openai_cfg = providers.get("openai", {})
    if "model_id" in openai_cfg:
        config.openai.model_id = openai_cfg["model_id"]
    if "max_input_tokens" in openai_cfg:
        config.openai.max_input_tokens = openai_cfg["max_input_tokens"]

    ollama = providers.get("ollama", {})
    if "model_id" in ollama:
        config.ollama.model_id = ollama["model_id"]
    if "host" in ollama:
        config.ollama.host = ollama["host"]
    if "api_key" in ollama:
        config.ollama.api_key = ollama["api_key"]
    if "max_input_tokens" in ollama:
        config.ollama.max_input_tokens = ollama["max_input_tokens"]

    # User-defined allowed commands and shell timeout settings
    tools = data.get("tools", {})
    if "allowed_commands" in tools:
        config.allowed_commands = tools["allowed_commands"]
    if "shell_timeout" in tools:
        config.shell_timeout = int(tools["shell_timeout"])
    if "idle_timeout" in tools:
        config.idle_timeout = int(tools["idle_timeout"])
    if "ignore_dirs" in tools:
        config.ignore_dirs = tools["ignore_dirs"]
    if "web_search_region" in tools:
        config.web_search_region = str(tools["web_search_region"])
    if "mcp_debug" in tools:
        config.mcp_debug = bool(tools["mcp_debug"])
    shell_ops = tools.get("shell_operators", {})
    if isinstance(shell_ops, dict):
        if "pipe" in shell_ops:
            config.shell_operators.pipe = bool(shell_ops["pipe"])
        if "chain" in shell_ops:
            config.shell_operators.chain = bool(shell_ops["chain"])
        if "redirect" in shell_ops:
            config.shell_operators.redirect = bool(shell_ops["redirect"])

    # API timeout settings
    api_timeout = data.get("api_timeout", {})
    if isinstance(api_timeout, dict):
        if "connect" in api_timeout:
            config.api_connect_timeout = int(api_timeout["connect"])
        if "streaming_read" in api_timeout:
            config.api_streaming_read_timeout = int(api_timeout["streaming_read"])
        if "read" in api_timeout:
            config.api_read_timeout = int(api_timeout["read"])

    # Mode-specific roles
    roles = data.get("roles", {})
    if "planning" in roles:
        config.roles.planning = roles["planning"]
    if "coding" in roles:
        config.roles.coding = roles["coding"]

    # Session settings
    session = data.get("session", {})
    if "auto_compact" in session:
        config.auto_compact = bool(session["auto_compact"])
    if "auto_compact_threshold" in session:
        config.auto_compact_threshold = float(session["auto_compact_threshold"])
    if "cache_system_prompt" in session:
        config.cache_system_prompt = bool(session["cache_system_prompt"])
    if "resume_history" in session:
        config.resume_history = max(0, int(session["resume_history"]))

    # Memory settings
    memory = data.get("memory", {})
    if "enabled" in memory:
        config.memory_enabled = bool(memory["enabled"])

    # Hooty mascot settings
    hooty = data.get("hooty", {})
    if "awake" in hooty:
        val = hooty["awake"]
        if (
            isinstance(val, list)
            and len(val) == 2
            and all(isinstance(v, int) for v in val)
            and 0 <= val[0] <= 23
            and 0 <= val[1] <= 23
            and val[0] < val[1]
            and val[1] - val[0] >= 2
        ):
            config.awake = (val[0], val[1])

    # Package manager settings
    pkg = data.get("pkg", {})
    if "auto_download" in pkg:
        val = pkg["auto_download"]
        config.pkg_auto_download = bool(val) if val is not None else None

    # Snapshot settings
    snapshot = data.get("snapshot", {})
    if "enabled" in snapshot:
        config.snapshot_enabled = bool(snapshot["enabled"])

    # Attachment settings
    attachment = data.get("attachment", {})
    if "max_files" in attachment:
        config.attachment.max_files = int(attachment["max_files"])
    if "max_side" in attachment:
        config.attachment.max_side = int(attachment["max_side"])
    if "large_file_tokens" in attachment:
        config.attachment.large_file_tokens = int(attachment["large_file_tokens"])
    if "max_total_tokens" in attachment:
        config.attachment.max_total_tokens = int(attachment["max_total_tokens"])
    if "context_ratio" in attachment:
        config.attachment.context_ratio = float(attachment["context_ratio"])
    capture = attachment.get("capture", {})
    if "delay_max" in capture:
        config.attachment.capture.delay_max = int(capture["delay_max"])
    if "repeat_max" in capture:
        config.attachment.capture.repeat_max = int(capture["repeat_max"])
    if "interval_min" in capture:
        config.attachment.capture.interval_min = int(capture["interval_min"])
    if "interval_max" in capture:
        config.attachment.capture.interval_max = int(capture["interval_max"])

    # Skills settings
    skills = data.get("skills", {})
    if "enabled" in skills:
        config.skills.enabled = bool(skills["enabled"])

    # Agno settings
    agno = data.get("agno", {})
    if "telemetry" in agno:
        config.agno.telemetry = bool(agno["telemetry"])

    # Reasoning settings
    reasoning = data.get("reasoning", {})
    if "mode" in reasoning and reasoning["mode"] in ("off", "on", "auto"):
        config.reasoning.mode = reasoning["mode"]
    if "auto_level" in reasoning and isinstance(reasoning["auto_level"], int):
        config.reasoning.auto_level = max(0, min(reasoning["auto_level"], 3))
    if "keywords" in reasoning and isinstance(reasoning["keywords"], dict):
        config.reasoning.keywords = {
            k: v for k, v in reasoning["keywords"].items()
            if k in ("level1", "level2", "level3") and isinstance(v, list)
        }

    # Profiles section
    profiles_data = data.get("profiles", {})
    for name, pdata in profiles_data.items():
        if not isinstance(pdata, dict) or "provider" not in pdata or "model_id" not in pdata:
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
            host=pdata.get("host"),
            sso_auth=pdata.get("sso_auth"),
            max_input_tokens=pdata.get("max_input_tokens"),
            base_url=pdata.get("base_url"),
        )
        config.profiles[name] = profile

    # mcp is loaded from mcp.yaml (not config.yaml)


def _apply_env(config: AppConfig) -> None:
    """Apply environment variables to AppConfig."""
    if profile := os.environ.get("HOOTY_PROFILE"):
        config.active_profile = profile
    if os.environ.get("HOOTY_DEBUG", "").lower() in ("1", "true"):
        config.debug = True

    # Reasoning mode
    reasoning_val = os.environ.get("HOOTY_REASONING", "").lower()
    if reasoning_val in ("on", "1", "true"):
        config.reasoning.mode = "on"
    elif reasoning_val == "auto":
        config.reasoning.mode = "auto"

    # Anthropic
    if base_url := os.environ.get("ANTHROPIC_BASE_URL"):
        config.anthropic.base_url = base_url

    # AWS
    if region := os.environ.get("AWS_REGION"):
        config.bedrock.region = region

    # Azure AI Foundry
    if endpoint := os.environ.get("AZURE_ENDPOINT"):
        config.azure.endpoint = endpoint
    if api_version := os.environ.get("AZURE_API_VERSION"):
        config.azure.api_version = api_version

    # Azure OpenAI Service
    if endpoint := os.environ.get("AZURE_OPENAI_ENDPOINT"):
        config.azure_openai.endpoint = endpoint
    if deployment := os.environ.get("AZURE_OPENAI_DEPLOYMENT"):
        config.azure_openai.deployment = deployment
    if api_version := os.environ.get("AZURE_OPENAI_API_VERSION"):
        config.azure_openai.api_version = api_version

    # Ollama
    if host := os.environ.get("OLLAMA_HOST"):
        config.ollama.host = host


def _supports_reasoning_effort(model_id: str) -> bool:
    """Check if an OpenAI model supports reasoning_effort parameter.

    GPT-5.2+ (including variants like chat, codex, pro, mini) are supported.
    """
    m = re.match(r"gpt-5\.(\d+)", model_id.lower())
    return m is not None and int(m.group(1)) >= 2


def supports_thinking(config: AppConfig) -> bool:
    """Check if current provider+model supports reasoning/thinking.

    Resolution:
    1. Catalog ``supports_reasoning`` flag (authoritative when present)
    2. Hardcoded fallback for models not yet in the catalog
    """
    from hooty.model_catalog import get_model_capabilities

    provider = config.provider.value
    if provider == "anthropic":
        model_id = config.anthropic.model_id
    elif provider == "azure_openai":
        model_id = config.azure_openai.model_id
    elif provider == "bedrock":
        model_id = config.bedrock.model_id
    elif provider == "azure":
        model_id = config.azure.model_id
    elif provider == "openai":
        model_id = config.openai.model_id
    elif provider == "ollama":
        model_id = config.ollama.model_id
    else:
        return False

    caps = get_model_capabilities(model_id, provider)
    if "supports_reasoning" in caps:
        return caps["supports_reasoning"]

    # Fallback: hardcoded rules for models not in the catalog
    if config.provider == Provider.ANTHROPIC:
        non_thinking = {
            "claude-3-haiku-20240307",
            "claude-3-5-haiku-20241022",
            "claude-3-5-haiku-latest",
        }
        return config.anthropic.model_id not in non_thinking

    if config.provider in (Provider.AZURE_OPENAI, Provider.OPENAI):
        return _supports_reasoning_effort(model_id)

    return False


def supports_vision(config: AppConfig) -> bool:
    """Check if current provider+model supports vision (image input)."""
    from hooty.model_catalog import get_model_capabilities

    provider = config.provider.value
    if provider == "anthropic":
        model_id = config.anthropic.model_id
    elif provider == "azure_openai":
        model_id = config.azure_openai.model_id
    elif provider == "bedrock":
        model_id = config.bedrock.model_id
    elif provider == "azure":
        model_id = config.azure.model_id
    elif provider == "openai":
        model_id = config.openai.model_id
    elif provider == "ollama":
        model_id = config.ollama.model_id
    else:
        return False

    caps = get_model_capabilities(model_id, provider)
    if "supports_vision" in caps:
        return caps["supports_vision"]

    # Fallback: Claude 4+ models support vision
    if provider in ("anthropic", "bedrock", "azure"):
        return "claude" in model_id.lower()

    return False


REASONING_LEVEL_BUDGETS: dict[str, int] = {
    "level1": 4_000,
    "level2": 10_000,
    "level3": 30_000,
}

REASONING_EFFORT_MAP: dict[str, str] = {
    "level1": "low",
    "level2": "medium",
    "level3": "high",
}

_ADAPTIVE_THINKING_RE = re.compile(r"claude-opus-4-[6-9]|claude-opus-[5-9]")


def supports_adaptive_thinking(model_id: str) -> bool:
    """Check if model supports adaptive thinking (Opus 4.6+)."""
    return bool(_ADAPTIVE_THINKING_RE.search(model_id))


@lru_cache(maxsize=1)
def _load_default_thinking_keywords() -> dict[str, list[str]]:
    """Load default thinking keywords from bundled YAML (cached)."""
    kw_path = Path(__file__).parent / "data" / "thinking_keywords.yaml"
    with open(kw_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# Cache for _build_thinking_keywords: (cache_key, result)
_thinking_keywords_cache: tuple[tuple[tuple[str, ...], ...] | None, list[tuple[str, int]]] = (
    None,
    [],
)


def _build_thinking_keywords(config: AppConfig) -> list[tuple[str, int]]:
    """Build keyword→budget list from config, sorted longest-first (cached)."""
    global _thinking_keywords_cache  # noqa: PLW0603

    # Build a hashable key from user keywords
    user_kw = config.reasoning.keywords
    cache_key = tuple(
        tuple(user_kw.get(level, ())) for level in REASONING_LEVEL_BUDGETS
    )

    cached_key, cached_result = _thinking_keywords_cache
    if cached_key == cache_key:
        return cached_result

    defaults = _load_default_thinking_keywords()
    pairs: list[tuple[str, int]] = []
    for level, budget in REASONING_LEVEL_BUDGETS.items():
        words = user_kw.get(level, defaults[level])
        for w in words:
            pairs.append((w.lower(), budget))
    # Sort by keyword length descending (most specific first)
    pairs.sort(key=lambda p: len(p[0]), reverse=True)

    _thinking_keywords_cache = (cache_key, pairs)
    return pairs


def detect_thinking_budget(message: str, config: AppConfig) -> int | None:
    """Detect thinking keywords in message and return budget_tokens.

    Returns int (budget) to enable thinking, or None to disable.
    Deprecated: use detect_reasoning_level() for provider-agnostic detection.
    """
    level = detect_reasoning_level(message, config)
    if level is None:
        return None
    return REASONING_LEVEL_BUDGETS[level]


def detect_reasoning_level(message: str, config: AppConfig) -> str | None:
    """Detect reasoning level from message keywords.

    Returns "level1" | "level2" | "level3" | None.
    """
    if config.reasoning.mode == "off" or not supports_thinking(config):
        return None

    msg_lower = message.lower()
    for keyword, budget in _build_thinking_keywords(config):
        if keyword in msg_lower:
            for level, lvl_budget in REASONING_LEVEL_BUDGETS.items():
                if budget == lvl_budget:
                    return level
            return "level2"  # fallback

    # No keyword matched
    if config.reasoning.mode == "on":
        return "level2"  # default level
    # auto: use auto_level if set, otherwise no reasoning
    if config.reasoning.auto_level > 0:
        lvl = min(config.reasoning.auto_level, 3)
        return f"level{lvl}"
    return None


def _merge_project_mcp(config: AppConfig) -> None:
    """Merge project-level mcp.yaml into config.mcp (later wins)."""
    project_path = config.mcp_project_file_path
    if not project_path.exists():
        return
    data = _load_yaml_file(project_path)
    if not isinstance(data, dict) or not isinstance(data.get("servers"), dict):
        return
    for name, conf in data["servers"].items():
        config.mcp[name] = conf
        config.mcp_sources[name] = "project"


def _apply_mcp_disabled(config: AppConfig) -> None:
    """Remove disabled MCP servers from config.mcp."""
    import json

    path = config.mcp_state_path
    if not path.exists():
        return
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            return
    except (json.JSONDecodeError, OSError):
        return
    disabled = set(state.get("disabled", []))
    for name in disabled:
        config.mcp.pop(name, None)
        config.mcp_sources.pop(name, None)


def load_config(
    *,
    profile_override: Optional[str] = None,
    working_dir_override: Optional[str] = None,
    add_dirs: list[str] | None = None,
    session_id: Optional[str] = None,
    resume: bool = False,
    continue_session: bool = False,
    debug: bool = False,
    mcp_debug: bool = False,
    stream: bool = True,
    no_skills: bool = False,
    reasoning: str = "",
    unsafe: bool = False,
    snapshot: Optional[bool] = None,
    no_hooks: bool = False,
) -> AppConfig:
    """Load configuration from YAML, environment variables, and CLI overrides.

    Priority: CLI args > env vars > .env > config.yaml > credentials > defaults
    """
    load_dotenv()

    config = AppConfig()

    # Load .credentials (lowest priority — overridden by everything else)
    try:
        from hooty.credentials import apply_credentials, load_credentials, CredentialExpiredError

        cred_payload = load_credentials()
        if cred_payload is not None:
            apply_credentials(cred_payload, config)
            config.credentials_active = True
    except ImportError:
        pass  # cryptography not installed
    except CredentialExpiredError:
        raise  # propagate to caller
    except Exception:
        pass  # corrupted file, etc.

    # Load YAML config
    if config.config_file_path.exists():
        data = _load_yaml_file(config.config_file_path)
        if data:
            _apply_yaml(config, data)

    # Load databases.yaml
    if config.databases_file_path.exists():
        data = _load_yaml_file(config.databases_file_path)
        if isinstance(data, dict) and "databases" in data:
            config.databases = data["databases"]

    # Load mcp.yaml (global)
    if config.mcp_file_path.exists():
        data = _load_yaml_file(config.mcp_file_path)
        if isinstance(data, dict) and isinstance(data.get("servers"), dict):
            config.mcp = data["servers"]
            config.mcp_sources = {name: "global" for name in config.mcp}

    # Apply environment variables
    _apply_env(config)

    # Apply CLI overrides
    if profile_override is not None:
        config.active_profile = profile_override
    if working_dir_override is not None:
        config.working_directory = str(Path(working_dir_override).resolve())
    else:
        config.working_directory = str(Path.cwd())
    if debug:
        config.debug = True
    if mcp_debug:
        config.mcp_debug = True
    if not stream:
        config.stream = False
    if session_id is not None:
        config.session_id = session_id
    if resume:
        config.resume = True
    if continue_session:
        config.continue_session = True
    if no_skills:
        config.skills.enabled = False
    if reasoning and reasoning in ("on", "auto"):
        config.reasoning.mode = reasoning
    if add_dirs:
        config.add_dirs = [str(Path(d).resolve()) for d in add_dirs]
    if unsafe:
        config.unsafe = True
    if snapshot is not None:
        config.snapshot_enabled = snapshot
    if no_hooks:
        config.hooks_enabled = False

    # Load project mcp.yaml (later wins over global)
    # working_directory is now resolved (from --dir or cwd)
    _merge_project_mcp(config)

    # Exclude disabled MCP servers
    _apply_mcp_disabled(config)

    # Activate profile (if set)
    if config.active_profile:
        config.activate_profile(config.active_profile)

    # Ensure config directory exists
    config.config_dir.mkdir(parents=True, exist_ok=True)

    return config


def save_databases(config: AppConfig) -> None:
    """Save databases configuration back to databases.yaml."""
    from hooty.concurrency import atomic_write_text

    config.config_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        config.databases_file_path,
        yaml.dump({"databases": config.databases}, default_flow_style=False, allow_unicode=True),
    )


def validate_config(config: AppConfig) -> Optional[str]:
    """Validate configuration. Returns error message or None if valid."""
    from hooty.credentials import get_secret

    if config.provider == Provider.ANTHROPIC:
        if config.anthropic.base_url:
            # Azure AI Foundry via Anthropic SDK — accept either key
            api_key = get_secret("AZURE_API_KEY") or get_secret("ANTHROPIC_API_KEY")
            if not api_key:
                return (
                    "Anthropic (Azure) API key is missing.\n"
                    "  Set AZURE_API_KEY or ANTHROPIC_API_KEY environment variable."
                )
        else:
            # Direct Anthropic API
            api_key = get_secret("ANTHROPIC_API_KEY")
            if not api_key:
                return (
                    "Anthropic API key is missing.\n"
                    "  Set the ANTHROPIC_API_KEY environment variable."
                )

    if config.provider == Provider.AZURE_OPENAI:
        api_key = get_secret("AZURE_OPENAI_API_KEY")
        if not api_key:
            return (
                "Azure OpenAI credentials are missing.\n"
                "  Set the AZURE_OPENAI_API_KEY environment variable."
            )
        if not config.azure_openai.endpoint:
            return (
                "Azure OpenAI endpoint is not configured.\n"
                "  Set providers.azure_openai.endpoint in config.yaml or\n"
                "  the AZURE_OPENAI_ENDPOINT environment variable."
            )
        if not config.azure_openai.deployment:
            return (
                "Azure OpenAI deployment is not configured.\n"
                "  Set providers.azure_openai.deployment in config.yaml or\n"
                "  the AZURE_OPENAI_DEPLOYMENT environment variable."
            )

    if config.provider == Provider.AZURE:
        api_key = get_secret("AZURE_API_KEY")
        if not api_key:
            return (
                "Azure AI credentials are missing.\n"
                "  Set the AZURE_API_KEY environment variable."
            )
        if not config.azure.endpoint:
            return (
                "Azure AI endpoint is not configured.\n"
                "  Set providers.azure.endpoint in config.yaml or\n"
                "  the AZURE_ENDPOINT environment variable."
            )

    if config.provider == Provider.OPENAI:
        api_key = get_secret("OPENAI_API_KEY")
        if not api_key:
            return (
                "OpenAI API key is missing.\n"
                "  Set the OPENAI_API_KEY environment variable."
            )

    if config.provider == Provider.OLLAMA:
        pass  # Local execution — no auth required

    if config.provider == Provider.BEDROCK:
        has_keys = get_secret("AWS_ACCESS_KEY_ID") and get_secret("AWS_SECRET_ACCESS_KEY")
        # Bearer token is NOT managed by credentials — user env only
        has_bearer = bool(os.environ.get("AWS_BEARER_TOKEN_BEDROCK"))
        if not has_keys and not has_bearer and not config.bedrock.sso_auth:
            return (
                "AWS Bedrock credentials are missing.\n"
                "  Set one of the following:\n"
                "  - AWS_BEARER_TOKEN_BEDROCK environment variable (bearer token auth)\n"
                "  - AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY environment variables\n"
                "  - sso_auth: true in config.yaml"
            )

    return None
