"""CLI entry point for Hooty."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Any, Optional

import click
import typer
from rich.console import Console

from hooty import __version__
from hooty.config import load_config, owl_eyes, validate_config

_console = Console()


def _owl_eyes() -> tuple[str, str]:
    """Return (eye_char, eye_color) based on current hour (default awake window)."""
    return owl_eyes(datetime.now().hour)


def _print_banner() -> None:
    """Print the owl banner."""
    eye_char, eye_color = _owl_eyes()
    _console.print("   [bright_white],___,[/bright_white]")
    _console.print(
        f"   [bright_white]([/bright_white][bold {eye_color}]{eye_char}[/bold {eye_color}]"
        f"[bright_white],[/bright_white][bold {eye_color}]{eye_char}[/bold {eye_color}]"
        f"[bright_white])[/bright_white]"
        f"    [bold #E6C200]Hooty[/bold #E6C200] v{__version__}"
    )
    _console.print(
        "   [bright_white]/)  )[/bright_white]"
        "    Interactive AI coding assistant"
    )
    _console.print(
        '  [bright_white]--""--[/bright_white]'
        "    powered by [dim]Agno[/dim]"
    )
    _console.print()


def _help_callback(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    """Custom help callback that prints banner before help text."""
    if not value or ctx.resilient_parsing:
        return
    _console.print()
    _print_banner()
    # Show the default help text
    click.echo(ctx.get_help())
    ctx.exit()


app = typer.Typer(
    name="hooty",
    add_completion=False,
    rich_markup_mode="rich",
    context_settings={"help_option_names": []},
    invoke_without_command=True,
)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"Hooty v{__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    prompt: Optional[str] = typer.Option(
        None,
        "--prompt",
        "-p",
        help="Run a single prompt in non-interactive mode",
    ),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Profile name to use (defined in config.yaml)",
    ),
    resume: Optional[str] = typer.Option(
        None,
        "--resume",
        "-r",
        help="Resume a session by ID, or pick from list if no ID given",
    ),
    continue_session: bool = typer.Option(
        False,
        "--continue",
        "-c",
        help="Resume the most recent session",
    ),
    working_dir: Optional[str] = typer.Option(
        None,
        "--dir",
        "-d",
        help="Working directory for file operations",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug logging",
    ),
    mcp_debug: bool = typer.Option(
        False,
        "--mcp-debug",
        help="Show MCP server stderr output",
    ),
    no_stream: bool = typer.Option(
        False,
        "--no-stream",
        help="Disable streaming output",
    ),
    no_skills: bool = typer.Option(
        False,
        "--no-skills",
        help="Disable agent skills",
    ),
    add_dir: Optional[list[str]] = typer.Option(
        None,
        "--add-dir",
        help="Add working directory for file read/write (repeatable)",
    ),
    reasoning: Optional[str] = typer.Option(
        None,
        "--reasoning",
        help="Enable extended thinking: on | auto",
    ),
    snapshot: Optional[bool] = typer.Option(
        None,
        "--snapshot/--no-snapshot",
        help="Enable/disable file snapshot tracking for /diff and /rewind",
    ),
    no_hooks: bool = typer.Option(
        False,
        "--no-hooks",
        help="Disable lifecycle hooks",
    ),
    attach: Optional[list[str]] = typer.Option(
        None,
        "--attach",
        "-a",
        help="Attach file(s) to first message (repeatable)",
    ),
    unsafe: bool = typer.Option(
        False,
        "--unsafe",
        "-y",
        help="Disable safe mode (skip confirmation dialogs)",
    ),
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
    show_help: Optional[bool] = typer.Option(
        None,
        "--help",
        is_eager=True,
        expose_value=False,
        callback=_help_callback,
        help="Show this message and exit.",
    ),
) -> None:
    """Start the interactive AI coding assistant."""
    # If a subcommand is invoked, skip REPL startup
    if ctx.invoked_subcommand is not None:
        return

    # Conflict check: --resume and --continue are mutually exclusive
    if resume is not None and continue_session:
        _console.print(
            "\n  [bold red]✗ --resume and --continue cannot be used together[/bold red]\n"
        )
        sys.exit(1)

    # Detect non-interactive mode: --prompt or stdin pipe
    is_non_interactive = prompt is not None or not sys.stdin.isatty()

    # Resolve --attach paths relative to CWD *before* --dir changes working directory
    from pathlib import Path as _P
    attach_resolved = [str(_P(p).resolve()) for p in (attach or [])]

    # Resolve --resume: picker sentinel vs actual session ID
    resume_picker = resume == _RESUME_PICKER_SENTINEL
    resume_session_id = None if resume_picker else resume

    try:
        config = load_config(
            profile_override=profile,
            working_dir_override=working_dir,
            add_dirs=add_dir or [],
            session_id=resume_session_id,
            resume=resume is not None,
            continue_session=continue_session,
            debug=debug,
            mcp_debug=mcp_debug,
            stream=not no_stream,
            no_skills=no_skills,
            reasoning=reasoning or "",
            unsafe=unsafe,
            snapshot=snapshot if snapshot is not None else None,
            no_hooks=no_hooks,
        )
    except Exception as e:
        if type(e).__name__ == "CredentialExpiredError":
            _console.print(f"\n  [bold red]✗ {e}[/bold red]")
            _console.print("  [dim]Run 'hooty setup' to apply new credentials, or 'hooty setup clear' to remove.[/dim]\n")
            sys.exit(1)
        if type(e).__name__ == "ConfigFileError":
            _console.print(f"\n  [bold red]✗ {e}[/bold red]\n")
            sys.exit(1)
        raise

    # Validate working directory exists
    if not os.path.isdir(config.working_directory):
        _console.print(
            f"\n  [bold red]✗ Working directory does not exist: {config.working_directory}[/bold red]\n"
        )
        sys.exit(1)

    # Check if initial setup is needed
    if not config.config_file_path.exists() and not (config.config_dir / ".credentials").exists():
        _console.print(
            "\n  [bold yellow]⚠ No configuration found.[/bold yellow]"
            "\n  [dim]Run [bold]hooty setup[/bold] to configure credentials,"
            "\n  or create [bold]~/.hooty/config.yaml[/bold] manually.[/dim]\n"
        )
        sys.exit(1)

    # Validate credentials
    error = validate_config(config)
    if error:
        _console.print(f"\n  [bold red]✗ {error}[/bold red]\n")
        sys.exit(1)

    # Non-interactive mode: run single prompt and exit
    if is_non_interactive:
        # Resolve prompt: --prompt takes priority over stdin
        prompt_text = prompt if prompt is not None else sys.stdin.read().strip()
        if not prompt_text:
            print("Error: No prompt provided.", file=sys.stderr)
            sys.exit(2)
        from hooty.oneshot import oneshot_run

        oneshot_run(config, prompt_text, attach_files=attach_resolved)
        return

    # Resolve --continue to actual session_id (most recent session)
    if config.continue_session and not config.session_id:
        from hooty.session_store import get_most_recent_session_id

        recent_id = get_most_recent_session_id(config)
        if recent_id:
            config.session_id = recent_id
            _console.print(
                f"  [dim]Resuming session:[/dim] [magenta]{recent_id[:8]}...[/magenta]"
            )
        else:
            _console.print("  [dim]No previous sessions found. Starting new session.[/dim]")

    # Resolve --resume (no ID) to actual session_id via interactive picker
    if resume_picker and not config.session_id:
        from hooty.session_picker import pick_session

        chosen_id = pick_session(config, _console)
        if chosen_id is None:
            _console.print("  [dim]Cancelled.[/dim]")
            sys.exit(0)
        elif chosen_id:
            config.session_id = chosen_id
            _console.print(
                f"  [dim]Resuming session:[/dim] [magenta]{chosen_id[:8]}...[/magenta]"
            )
        else:
            _console.print("  [dim]Starting new session.[/dim]")

    # Show resuming message for --resume=<id>
    elif config.resume and config.session_id:
        _console.print(
            f"  [dim]Resuming session:[/dim] [magenta]{config.session_id[:8]}...[/magenta]"
        )

    # Acquire session lock for --continue / --resume (existing session)
    if config.session_id and (config.continue_session or config.resume):
        from hooty.session_lock import acquire_lock

        if not acquire_lock(config, config.session_id):
            _console.print(
                f"\n  [bold red]✗ Session {config.session_id[:8]}... is locked by another process[/bold red]\n"
            )
            sys.exit(1)

    from hooty.repl import REPL

    repl = REPL(config, attach_files=attach_resolved)
    repl.start()


# Sentinel used when --resume is given without a session ID (picker mode)
_RESUME_PICKER_SENTINEL = "__picker__"


# ---------------------------------------------------------------------------
# setup subcommand group
# ---------------------------------------------------------------------------

setup_app = typer.Typer(
    name="setup",
    help="Credential provisioning commands.",
    add_completion=False,
    invoke_without_command=True,
)
app.add_typer(setup_app, name="setup")


@setup_app.callback(invoke_without_command=True)
def setup_default(ctx: typer.Context) -> None:
    """Interactive setup: paste a setup code to configure credentials."""
    if ctx.invoked_subcommand is not None:
        return

    try:
        from hooty.credentials import (
            decode_setup_code,
            load_credentials,
            save_credentials,
        )
    except ImportError:
        _console.print(
            "\n  [bold red]✗ cryptography package is required for setup.[/bold red]"
            "\n  [dim]Install with: uv sync --extra enterprise[/dim]\n"
        )
        sys.exit(1)

    from hooty.ui import hotkey_select, password_input, text_input

    # Check for existing credentials
    existing = load_credentials()
    if existing is not None:
        choice = hotkey_select(
            [("Y", "Yes \u2014 overwrite"), ("N", "No \u2014 cancel")],
            title="Setup",
            subtitle="Existing credentials found",
            con=_console,
        )
        if choice != "Y":
            _console.print("  [dim]Cancelled.[/dim]")
            return

    # Get setup code
    code = text_input(
        title="Setup",
        subtitle="Paste the setup code:",
        con=_console,
    )
    if not code:
        _console.print("  [dim]Cancelled.[/dim]")
        return

    # Always require passphrase
    passphrase = password_input(
        title="Passphrase",
        subtitle="Enter the passphrase",
        con=_console,
    )
    if passphrase is None:
        _console.print("  [dim]Cancelled.[/dim]")
        return

    # Decode and save
    try:
        payload = decode_setup_code(code, passphrase=passphrase)
    except ValueError as exc:
        _console.print(f"\n  [bold red]✗ {exc}[/bold red]\n")
        sys.exit(1)

    save_credentials(payload)
    _console.print("\n  [bold green]✓ Credentials saved[/bold green]\n")


@setup_app.command("generate")
def setup_generate(
    passphrase: Optional[str] = typer.Option(
        None,
        "--passphrase",
        help="Passphrase for encryption (auto-generated if omitted)",
    ),
    dump: bool = typer.Option(
        False,
        "--dump",
        help="Print raw JSON payload instead of encrypted setup code",
    ),
    exclude_profiles: Optional[str] = typer.Option(
        None,
        "--exclude-profiles",
        help="Comma-separated profile names to exclude (e.g. 'dev,local')",
    ),
    expiry_days: int = typer.Option(
        30,
        "--expiry-days",
        help="Credential expiry in days (0 = no expiry)",
    ),
) -> None:
    """Generate a setup code from current config.yaml and environment."""
    try:
        from hooty.credentials import CredentialPayload, ProviderCredential, generate_setup_code
    except ImportError:
        _console.print(
            "\n  [bold red]✗ cryptography package is required.[/bold red]"
            "\n  [dim]Install with: uv sync --extra enterprise[/dim]\n"
        )
        sys.exit(1)

    config = load_config()

    # Determine which profiles to exclude
    excluded: set[str] = set()
    if exclude_profiles:
        excluded = {p.strip() for p in exclude_profiles.split(",") if p.strip()}

    providers: dict[str, ProviderCredential] = {}

    # Collect Anthropic config
    anthropic_env: dict[str, str] = {}
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_api_key:
        anthropic_env["ANTHROPIC_API_KEY"] = anthropic_api_key
    if anthropic_env or config.anthropic.base_url:
        anthropic_cfg: dict[str, Any] = {}
        if config.anthropic.base_url:
            anthropic_cfg["base_url"] = config.anthropic.base_url
        providers["anthropic"] = ProviderCredential(config=anthropic_cfg, env=anthropic_env)

    # Collect Azure config
    if config.azure.endpoint:
        azure_env: dict[str, str] = {}
        api_key = os.environ.get("AZURE_API_KEY", "")
        if api_key:
            azure_env["AZURE_API_KEY"] = api_key
        azure_cfg: dict[str, Any] = {
            "endpoint": config.azure.endpoint,
        }
        if config.azure.api_version:
            azure_cfg["api_version"] = config.azure.api_version
        providers["azure"] = ProviderCredential(config=azure_cfg, env=azure_env)

    # Collect Azure OpenAI config
    if config.azure_openai.endpoint:
        aoai_env: dict[str, str] = {}
        aoai_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        if aoai_key:
            aoai_env["AZURE_OPENAI_API_KEY"] = aoai_key
        aoai_cfg: dict[str, Any] = {
            "endpoint": config.azure_openai.endpoint,
            "api_version": config.azure_openai.api_version,
        }
        providers["azure_openai"] = ProviderCredential(config=aoai_cfg, env=aoai_env)

    # Collect OpenAI config
    openai_env: dict[str, str] = {}
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        openai_env["OPENAI_API_KEY"] = openai_key
    if openai_env:
        providers["openai"] = ProviderCredential(config={}, env=openai_env)

    # Collect Bedrock config
    # Note: AWS_BEARER_TOKEN_BEDROCK is excluded — it is a user-side
    # temporary token, not suitable for credential provisioning.
    bedrock_env: dict[str, str] = {}
    ak = os.environ.get("AWS_ACCESS_KEY_ID", "")
    sk = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    if ak:
        bedrock_env["AWS_ACCESS_KEY_ID"] = ak
    if sk:
        bedrock_env["AWS_SECRET_ACCESS_KEY"] = sk
    if bedrock_env or config.bedrock.region != "us-east-1":
        bedrock_cfg: dict[str, Any] = {
            "region": config.bedrock.region,
        }
        providers["bedrock"] = ProviderCredential(config=bedrock_cfg, env=bedrock_env)

    # Build profiles dict from config (excluding specified profiles)
    cred_profiles: dict[str, dict[str, Any]] = {}
    for name, prof in config.profiles.items():
        if name in excluded:
            continue
        pdata: dict[str, Any] = {
            "provider": prof.provider.value,
            "model_id": prof.model_id,
        }
        if prof.region is not None:
            pdata["region"] = prof.region
        if prof.endpoint is not None:
            pdata["endpoint"] = prof.endpoint
        if prof.deployment is not None:
            pdata["deployment"] = prof.deployment
        if prof.api_version is not None:
            pdata["api_version"] = prof.api_version
        if prof.sso_auth is not None:
            pdata["sso_auth"] = prof.sso_auth
        if prof.max_input_tokens is not None:
            pdata["max_input_tokens"] = prof.max_input_tokens
        if prof.base_url is not None:
            pdata["base_url"] = prof.base_url
        cred_profiles[name] = pdata

    # Determine default_profile (handle exclusion)
    default_profile = config.active_profile
    if default_profile in excluded:
        default_profile = next(iter(cred_profiles), "")

    # Remove providers not referenced by any remaining profile
    referenced_providers = {p["provider"] for p in cred_profiles.values()}
    providers = {k: v for k, v in providers.items() if k in referenced_providers}

    if not providers and not cred_profiles:
        _console.print("\n  [bold yellow]⚠ No provider credentials found to bundle.[/bold yellow]\n")
        sys.exit(1)

    import time

    expires_at = time.time() + expiry_days * 86400 if expiry_days > 0 else None

    payload = CredentialPayload(
        version=2,
        default_profile=default_profile,
        providers=providers,
        profiles=cred_profiles,
        extra_config={"stream": config.stream},
        expires_at=expires_at,
    )

    if dump:
        import json

        _console.print(json.dumps(payload.to_dict(), indent=2, ensure_ascii=False))
        return

    code, passphrase_used = generate_setup_code(payload, passphrase=passphrase)
    _console.print()
    _console.print(code, highlight=False)
    _console.print()

    providers_str = ", ".join(providers.keys())
    profiles_str = ", ".join(cred_profiles.keys())
    env_keys = sorted({k for p in providers.values() for k in p.env})
    _console.print(f"  [dim]Providers: {providers_str}[/dim]")
    _console.print(f"  [dim]Profiles: {profiles_str}[/dim]")
    if env_keys:
        _console.print(f"  [dim]Secret keys: {', '.join(env_keys)}[/dim]")
    if expires_at is not None:
        from datetime import datetime

        expires_dt = datetime.fromtimestamp(expires_at)
        expires_label = expires_dt.strftime("%Y-%m-%d %H:%M")
        _console.print(f"  [dim]Expires: {expiry_days} days (at {expires_label})[/dim]")
    else:
        _console.print("  [dim]Expires: never[/dim]")
    _console.print()
    if passphrase is None:
        _console.print("  [yellow]⚠ Share the setup code and passphrase via separate channels[/yellow]")
    _console.print(f"  [bold]Passphrase: {passphrase_used}[/bold]")
    _console.print()


@setup_app.command("show")
def setup_show() -> None:
    """Show stored credential status (secrets masked)."""
    try:
        from hooty.credentials import credential_status
    except ImportError:
        _console.print(
            "\n  [bold red]✗ cryptography package is required.[/bold red]"
            "\n  [dim]Install with: uv sync --extra enterprise[/dim]\n"
        )
        sys.exit(1)

    status = credential_status()
    if status is None:
        _console.print("\n  [dim]No stored credentials found.[/dim]\n")
        return

    _console.print()

    # Handle expired credentials
    if status.get("expired"):
        _console.print(f"  [bold red]Credential expired ({status['error']})[/bold red]")
        _console.print("  [dim]Run 'hooty setup' to apply new credentials, or 'hooty setup clear' to remove.[/dim]")
        _console.print()
        return

    _console.print(f"  [bold]Default profile:[/bold] {status.get('default_profile', '—')}")
    profiles = status.get("profiles", [])
    if profiles:
        _console.print(f"  [bold]Profiles:[/bold] {', '.join(profiles)}")

    if "expires_at" in status:
        from datetime import datetime

        exp_dt = datetime.fromtimestamp(status["expires_at"]).strftime("%Y-%m-%d %H:%M")
        _console.print(f"  [bold]Credential is valid[/bold] (expires at {exp_dt})")
    else:
        _console.print("  [bold]Credential is valid[/bold] (no expiry)")
    _console.print()


@setup_app.command("clear")
def setup_clear() -> None:
    """Delete stored credentials."""
    try:
        from hooty.credentials import clear_credentials
    except ImportError:
        _console.print(
            "\n  [bold red]✗ cryptography package is required.[/bold red]"
            "\n  [dim]Install with: uv sync --extra enterprise[/dim]\n"
        )
        sys.exit(1)

    if clear_credentials():
        _console.print("\n  [bold green]✓ Credentials cleared.[/bold green]\n")
    else:
        _console.print("\n  [dim]No stored credentials found.[/dim]\n")


def _preprocess_resume_argv() -> None:
    """Allow --resume / -r without a value (picker mode).

    Typer requires a value for Optional[str] options.  When --resume is
    given bare (no following value), we inject the picker sentinel so that
    typer sees ``--resume __picker__`` and the main function can detect it.
    """
    args = sys.argv[1:]
    new_args: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--resume", "-r"):
            # Check if next arg looks like a value for --resume
            if i + 1 < len(args) and not args[i + 1].startswith("-"):
                new_args.append(arg)
                new_args.append(args[i + 1])
                i += 2
            elif "=" in arg:
                new_args.append(arg)
                i += 1
            else:
                new_args.append(arg)
                new_args.append(_RESUME_PICKER_SENTINEL)
                i += 1
        elif arg.startswith("--resume="):
            new_args.append(arg)
            i += 1
        else:
            new_args.append(arg)
            i += 1
    sys.argv[1:] = new_args


def _cli_entry() -> None:
    """CLI entry point (called from pyproject.toml scripts)."""
    _preprocess_resume_argv()
    app()


if __name__ == "__main__":
    _cli_entry()
