"""Attachment stack for /attach — images and text files attached to prompts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.config import AppConfig


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".log", ".json", ".yaml", ".yml", ".xml",
    ".py", ".rs", ".js", ".ts", ".java", ".go",
    ".toml", ".html", ".css", ".sh",
}


@dataclass
class Attachment:
    """A single attached file (image or text)."""

    path: Path
    kind: str               # "image" | "text"
    display_name: str
    estimated_tokens: int
    # Image fields
    orig_width: int | None = None
    orig_height: int | None = None
    width: int | None = None
    height: int | None = None
    stored_path: Path | None = None
    # Text fields
    content: str | None = None
    file_size: int = 0


def _format_size(size: int) -> str:
    """Format byte size as human-readable string."""
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    else:
        return f"{size / (1024 * 1024):.1f}MB"


def _process_image(
    path: Path, *, max_side: int, attachments_dir: Path,
) -> Attachment | str:
    """Process an image file: resize if needed, save as PNG, estimate tokens.

    Returns Attachment on success, error string on failure.
    """
    try:
        from PIL import Image as PILImage
    except ImportError:
        return "Pillow is not installed. Run: uv pip install Pillow"

    try:
        img = PILImage.open(path)
    except Exception as e:
        return f"Cannot open image: {e}"

    orig_w, orig_h = img.size
    w, h = orig_w, orig_h

    if max(w, h) > max_side:
        img.thumbnail((max_side, max_side), PILImage.LANCZOS)
        w, h = img.size

    attachments_dir.mkdir(parents=True, exist_ok=True)
    stored = attachments_dir / f"{uuid.uuid4()}.png"
    img.save(stored, format="PNG")
    img.close()

    tokens = int((w * h) / 750)

    return Attachment(
        path=path,
        kind="image",
        display_name=path.name,
        estimated_tokens=tokens,
        orig_width=orig_w,
        orig_height=orig_h,
        width=w,
        height=h,
        stored_path=stored,
    )


def _process_text(path: Path) -> Attachment | str:
    """Process a text file: read content, estimate tokens.

    Returns Attachment on success, error string on failure.
    """
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Cannot read file: {e}"

    file_size = path.stat().st_size
    tokens = int(len(content) / 3)

    return Attachment(
        path=path,
        kind="text",
        display_name=path.name,
        estimated_tokens=tokens,
        content=content,
        file_size=file_size,
    )


@dataclass
class AttachmentStack:
    """Stack of files attached to the next prompt."""

    _items: list[Attachment] = field(default_factory=list)

    def add(
        self,
        path: str | Path,
        *,
        config: AppConfig,
        attachments_dir: Path | None = None,
        context_limit: int = 200_000,
    ) -> Attachment | str:
        """Add file to stack. Returns Attachment on success, error string on failure."""
        p = Path(path).resolve()
        if not p.exists():
            return f"File not found: {p}"

        # File count limit
        if len(self._items) >= config.attachment.max_files:
            return (
                f"\u26a0\ufe0f Max file count reached ({config.attachment.max_files}). "
                f"Remove some attachments first."
            )

        # Duplicate check
        if any(item.path == p for item in self._items):
            return f"\u26a0\ufe0f {p.name}: already attached."

        suffix = p.suffix.lower()

        if suffix in IMAGE_EXTENSIONS:
            # Vision check
            from hooty.config import supports_vision
            if not supports_vision(config):
                return f"\u26a0\ufe0f {p.name}: vision not supported by current model."

            if attachments_dir is None:
                return "attachments_dir is required for image files."
            result = _process_image(p, max_side=config.attachment.max_side, attachments_dir=attachments_dir)
        elif suffix in TEXT_EXTENSIONS:
            result = _process_text(p)
        else:
            return f"\u26a0\ufe0f {suffix}: unsupported file format."

        if isinstance(result, str):
            return result

        # Check hard limit
        hard_limit = min(
            config.attachment.max_total_tokens,
            int(context_limit * config.attachment.context_ratio),
        )
        new_total = self.total_tokens + result.estimated_tokens
        if new_total > hard_limit:
            return (
                f"\u26a0\ufe0f Attachment limit exceeded "
                f"(~{new_total}/{hard_limit} tokens). "
                f"Remove some attachments first."
            )

        self._items.append(result)
        return result

    def remove(self, indices: list[int]) -> int:
        """Remove items by index (0-based). Returns count removed."""
        to_remove = set(indices)
        before = len(self._items)
        self._items = [item for i, item in enumerate(self._items) if i not in to_remove]
        return before - len(self._items)

    def clear(self) -> int:
        """Clear stack, return removed count."""
        count = len(self._items)
        self._items.clear()
        return count

    @property
    def count(self) -> int:
        return len(self._items)

    @property
    def total_tokens(self) -> int:
        return sum(item.estimated_tokens for item in self._items)

    def items(self) -> list[Attachment]:
        return list(self._items)

    def flush(self) -> tuple[list | None, str]:
        """Drain stack. Returns (images_for_agno, text_block).

        images: list of agno.media.Image with content=bytes, format="png"
        text_block: filename-headed fenced blocks for text attachments
        """
        from agno.media import Image as AgnoImage

        images: list[AgnoImage] = []
        text_parts: list[str] = []

        for item in self._items:
            if item.kind == "image" and item.stored_path:
                data = item.stored_path.read_bytes()
                images.append(AgnoImage(content=data, format="png"))
            elif item.kind == "text" and item.content is not None:
                text_parts.append(
                    f"\n--- Attached: {item.display_name} ---\n"
                    f"{item.content}\n"
                    f"--- End: {item.display_name} ---"
                )

        self._items.clear()
        return (images if images else None, "\n".join(text_parts))
