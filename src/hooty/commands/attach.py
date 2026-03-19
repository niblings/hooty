"""/attach command — attach files (images/text) to the next prompt."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.commands import CommandContext


def _format_image_info(attachment) -> str:
    """Format image size and token info: ``[image, WxH >> WxH, ~N tokens]``."""
    if (
        attachment.orig_width != attachment.width
        or attachment.orig_height != attachment.height
    ):
        size_info = (
            f"{attachment.orig_width}x{attachment.orig_height} \u00bb "
            f"{attachment.width}x{attachment.height}"
        )
    else:
        size_info = f"{attachment.width}x{attachment.height}"
    return f"\\[image, {size_info}, ~{attachment.estimated_tokens} tokens]"


def _format_attachment_line(attachment, index: int) -> str:
    """Format a single attachment confirmation line."""
    if attachment.kind == "image":
        info = _format_image_info(attachment)
        return (
            f"  \U0001f4ce Attachment ({index}): {attachment.display_name} {info}"
        )
    else:
        from hooty.attachment import _format_size

        return (
            f"  \U0001f4ce Attachment ({index}): {attachment.display_name} "
            f"\\[text, {_format_size(attachment.file_size)}, ~{attachment.estimated_tokens} tokens]"
        )


def _parse_paths(args: list[str]) -> list[str]:
    """Parse file paths from args, handling quotes and spaces.

    Uses shlex to correctly split quoted paths that were already
    broken apart by str.split() in the REPL dispatcher.
    """
    import shlex

    joined = " ".join(args)
    try:
        return shlex.split(joined)
    except ValueError:
        # Unmatched quote — fall back to simple strip
        stripped = joined.strip("'\"")
        return [stripped] if stripped else []


def cmd_attach(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Handle /attach command and subcommands."""
    from hooty.attachment import AttachmentStack

    stack: AttachmentStack = ctx.get_attachment_stack()  # type: ignore[assignment]
    if stack is None:
        ctx.console.print("  [error]✗ Attachment stack not available[/error]")
        return

    if not args:
        # No args: launch file picker
        _attach_via_picker(ctx, stack)
        return

    sub = args[0].lower()

    if sub == "list":
        from hooty.attachment_picker import pick_attachments
        pick_attachments(stack, ctx.console)
        return

    if sub == "paste":
        _attach_paste(ctx, stack)
        return

    if sub == "capture":
        _attach_capture(ctx, stack, args[1:])
        return

    if sub == "clear":
        count = stack.clear()
        if count:
            ctx.console.print(f"  [success]✓ Cleared {count} attachment(s)[/success]")
        else:
            ctx.console.print("  [dim]No attachments to clear.[/dim]")
        return

    # Parse paths (supports multiple quoted paths with spaces)
    paths = _parse_paths(args)
    for path in paths:
        _add_file(ctx, stack, path)


def _attach_via_picker(ctx: CommandContext, stack) -> None:
    """Launch file picker and add selected file."""
    try:
        from hooty.file_picker import pick_file
    except ImportError:
        ctx.console.print("  [error]✗ File picker not available[/error]")
        return

    result = pick_file(ctx.config.working_directory, title="📎 Attach File", con=ctx.console, allow_navigate_above=True)
    if result:
        _add_file(ctx, stack, result)


def _add_file(ctx: CommandContext, stack, file_path: str) -> None:
    """Add a file to the attachment stack and display result."""
    from pathlib import Path

    # Resolve relative to working directory
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(ctx.config.working_directory) / p

    # Directory → fall back to file picker rooted at that directory
    if p.is_dir():
        try:
            from hooty.file_picker import pick_file
        except ImportError:
            ctx.console.print("  [error]✗ File picker not available[/error]")
            return
        result = pick_file(str(p), title="📎 Attach File", con=ctx.console, allow_navigate_above=True)
        if result:
            _add_file(ctx, stack, result)
        return

    # Determine attachments_dir
    ctx.ensure_session_dir()
    attachments_dir = None
    if ctx.config.session_dir:
        attachments_dir = ctx.config.session_dir / "attachments"

    result = stack.add(
        p,
        config=ctx.config,
        attachments_dir=attachments_dir,
        context_limit=ctx.get_context_limit(),
    )

    if isinstance(result, str):
        ctx.console.print(f"  {result}")
        return

    # Success
    line = _format_attachment_line(result, stack.count)
    ctx.console.print(line)

    # Large text file warning
    if (
        result.kind == "text"
        and result.estimated_tokens > ctx.config.attachment.large_file_tokens
    ):
        ctx.console.print(
            f"  \u26a0\ufe0f  Large file (~{result.estimated_tokens} tokens). "
            f"Consider trimming before attaching."
        )


def _image_pixel_hash(path) -> bytes | None:
    """Compute SHA-256 of raw pixel data (ignoring PNG metadata)."""
    import hashlib

    try:
        from PIL import Image as PILImage

        img = PILImage.open(path)
        pixel_hash = hashlib.sha256(img.tobytes()).digest()
        img.close()
        return pixel_hash
    except Exception:
        return None


def _is_duplicate_image(stack, new_path) -> bool:
    """Check if an image with identical pixel content is already attached."""
    new_hash = _image_pixel_hash(new_path)
    if new_hash is None:
        return False

    for item in stack.items():
        if item.kind == "image" and item.path:
            if _image_pixel_hash(item.path) == new_hash:
                return True
    return False


def _parse_capture_args(
    args: list[str],
) -> tuple[str, int, int, int]:
    """Parse /attach capture arguments.

    Returns (target, delay, repeat, interval).
    """
    import shlex

    target = "active"
    delay = 0
    repeat = 1
    interval = 0

    # Rejoin args for shlex parsing (handles quoted strings)
    joined = " ".join(args)
    try:
        tokens = shlex.split(joined)
    except ValueError:
        tokens = args

    i = 0
    positional_done = False
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--delay":
            positional_done = True
            if i + 1 < len(tokens):
                try:
                    delay = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
                continue
        elif tok == "--repeat":
            positional_done = True
            if i + 1 < len(tokens):
                try:
                    repeat = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
                continue
        elif tok == "--interval":
            positional_done = True
            if i + 1 < len(tokens):
                try:
                    interval = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
                continue
        elif not positional_done and not tok.startswith("--"):
            target = tok
            positional_done = True
        i += 1

    return target, delay, repeat, interval


def _countdown(ctx: CommandContext, seconds: int, message: str = "") -> None:
    """Display a countdown timer. Raises KeyboardInterrupt if Ctrl+C."""
    import time

    f = ctx.console.file
    f.write("\033[?25l")  # hide cursor
    f.flush()
    try:
        for remaining in range(seconds, 0, -1):
            label = f"  \u23f3 {remaining}s"
            if message:
                label += f" \u2014 {message}"
            label += "...  "
            print(label, end="\r", file=f, flush=True)
            time.sleep(1)
        # Clear countdown line
        print(" " * 50, end="\r", file=f, flush=True)
    finally:
        f.write("\033[?25h")  # restore cursor
        f.flush()


def _capture_and_add(
    ctx: CommandContext, stack, target: str, dest, attachments_dir,
) -> tuple[bool, str | None]:
    """Capture screen, add to stack. Returns (success, message)."""
    from hooty.capture import capture_screen

    result = capture_screen(target, dest)
    if not result.ok:
        return False, result.error

    add_result = stack.add(
        result.image_path,
        config=ctx.config,
        attachments_dir=attachments_dir,
        context_limit=ctx.get_context_limit(),
    )
    if isinstance(add_result, str):
        return False, add_result

    return True, result.message


def _attach_capture(ctx: CommandContext, stack, args: list[str]) -> None:
    """Capture screen and attach as image."""
    try:
        _attach_capture_impl(ctx, stack, args)
    except KeyboardInterrupt:
        ctx.console.print("\n  [dim]Capture cancelled.[/dim]")
    except Exception as e:
        ctx.console.print(f"  [error]\u2717 Capture error: {e}[/error]")


_CAPTURE_HELP = """\
  [bold]Usage:[/bold] /attach capture [target] [options]

  [bold]Targets:[/bold]
    (none), active    Active (foreground) window
    0, primary        Primary monitor
    1, 2              Monitor by index
    chrome.exe        Process name
    Notepad           Window class name (falls back to title match)
    "Design Doc"      Window title (partial match)

  [bold]Options:[/bold]
    --delay N         Wait N seconds before capture (max 30)
    --repeat N        Take N sequential captures (max 5)
    --interval N      Seconds between captures (5-30, required with --repeat)

  [bold]Examples:[/bold]
    /attach capture
    /attach capture chrome.exe --delay 3
    /attach capture "Design Doc" --delay 2 --repeat 3 --interval 5"""


def _attach_capture_impl(ctx: CommandContext, stack, args: list[str]) -> None:
    """Internal implementation for screen capture."""
    from time import strftime

    from hooty.capture import is_capture_available, sanitize_target_name
    from hooty.config import supports_vision

    if args and args[0] in ("--help", "-h", "help"):
        ctx.console.print(_CAPTURE_HELP)
        return

    if not is_capture_available():
        ctx.console.print(
            "  \u26a0\ufe0f Screen capture is not supported in this environment "
            "(Windows / WSL2 only)"
        )
        return

    if not supports_vision(ctx.config):
        ctx.console.print(
            "  \u26a0\ufe0f Vision not supported by current model."
        )
        return

    # Parse arguments
    target, delay, repeat, interval = _parse_capture_args(args)

    # Validate options
    cap_cfg = ctx.config.attachment.capture
    if delay < 0 or delay > cap_cfg.delay_max:
        ctx.console.print(
            f"  \u26a0\ufe0f --delay must be {cap_cfg.delay_max} seconds or less"
        )
        return
    if repeat < 1 or repeat > cap_cfg.repeat_max:
        ctx.console.print(
            f"  \u26a0\ufe0f --repeat must be {cap_cfg.repeat_max} or less"
        )
        return
    if repeat > 1 and interval == 0:
        ctx.console.print(
            "  \u26a0\ufe0f --interval is required when using --repeat"
        )
        return
    if repeat > 1 and (interval < cap_cfg.interval_min or interval > cap_cfg.interval_max):
        ctx.console.print(
            f"  \u26a0\ufe0f --interval must be between "
            f"{cap_cfg.interval_min} and {cap_cfg.interval_max} seconds"
        )
        return

    # Prepare attachments directory
    ctx.ensure_session_dir()
    attachments_dir = ctx.config.session_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_target_name(target)

    # active + no delay: auto grace period so user can switch windows
    if target == "active" and delay == 0:
        ctx.console.print(
            "  [dim]\U0001f4a1 'active' captures the foreground window. "
            "Switch now...[/dim]"
        )
        _countdown(ctx, 3)

    # Delay countdown
    if delay > 0:
        msg = ""
        if repeat > 1:
            msg = f"{repeat} shots at {interval}s intervals"
        _countdown(ctx, delay, msg)

    # Single capture
    if repeat == 1:
        ts = strftime("%Y%m%d_%H%M%S")
        filename = f"capture_{safe_name}_{ts}.png"
        dest = attachments_dir / filename

        ok, message = _capture_and_add(ctx, stack, target, dest, attachments_dir)
        if not ok:
            ctx.console.print(f"  \u26a0\ufe0f Capture failed: {message}")
            return

        att = stack.items()[-1]
        info = _format_image_info(att)
        line = f"  \U0001f4ce Attachment ({stack.count}): {att.display_name} {info}"
        if message:
            line += f"  [dim]({message})[/dim]"
        ctx.console.print(line)
        return

    # Sequential capture
    captured = 0
    for shot in range(1, repeat + 1):
        ts = strftime("%Y%m%d_%H%M%S")
        filename = f"capture_{safe_name}_{ts}_{shot:03d}.png"
        dest = attachments_dir / filename

        ok, message = _capture_and_add(ctx, stack, target, dest, attachments_dir)
        capture_time = strftime("%H:%M:%S")

        if ok:
            att = stack.items()[-1]
            info = _format_image_info(att)
            ctx.console.print(
                f"  \U0001f4ce [{shot}/{repeat}] {att.display_name} "
                f"{info} ({capture_time}) \u2705"
            )
            captured += 1
        else:
            ctx.console.print(
                f"  \U0001f4ce [{shot}/{repeat}] ({capture_time}) "
                f"\u274c {message}"
            )

        # Wait interval (except after last shot)
        if shot < repeat:
            _countdown(ctx, interval)

    ctx.console.print(
        f"  \U0001f4ce Attachment ({captured}): {captured} sequential captures"
    )


def _attach_paste(ctx: CommandContext, stack) -> None:
    """Capture clipboard content and attach it."""
    from hooty.clipboard import capture_clipboard

    ctx.ensure_session_dir()
    attachments_dir = ctx.config.session_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    ctx.console.print("  [dim]Checking clipboard...[/dim]")
    result = capture_clipboard(attachments_dir)

    match result.kind:
        case "unsupported":
            ctx.console.print(
                "  ⚠️ Clipboard capture is not supported in this environment.\n"
                "    Please specify the file path with /attach <path>."
            )
        case "error":
            ctx.console.print(f"  [error]✗ {result.error}[/error]")
        case "empty":
            ctx.console.print("  [dim]No image or files found in clipboard.[/dim]")
        case "image":
            if _is_duplicate_image(stack, result.image_path):
                result.image_path.unlink(missing_ok=True)
                ctx.console.print("  [dim]Same image already attached (skipped).[/dim]")
            else:
                _add_file(ctx, stack, str(result.image_path))
        case "files":
            for fp in result.file_paths:
                _add_file(ctx, stack, str(fp))
