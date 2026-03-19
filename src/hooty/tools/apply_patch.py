"""Apply patch in Claude Code format (*** Begin Patch / *** End Patch).

Supports Add File, Update File (with optional Move to), and Delete File operations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("hooty")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Change:
    """A single line change within a chunk."""

    type: str  # "add" | "remove"
    content: str


@dataclass
class Chunk:
    """A context-anchored group of changes within a file update."""

    context: str  # @@ marker text (function signature, etc.)
    changes: list[Change] = field(default_factory=list)


@dataclass
class AddFile:
    """Create a new file with the given content."""

    path: str
    content: str


@dataclass
class UpdateFile:
    """Update an existing file with chunks of changes."""

    path: str
    move_to: str | None = None
    chunks: list[Chunk] = field(default_factory=list)


@dataclass
class DeleteFile:
    """Delete a file."""

    path: str


PatchOperation = AddFile | UpdateFile | DeleteFile


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class PatchParseError(Exception):
    """Raised when the patch text cannot be parsed."""


def parse_patch(text: str) -> list[PatchOperation]:
    """Parse a Claude Code format patch into a list of operations.

    The patch must be enclosed in ``*** Begin Patch`` / ``*** End Patch`` markers.
    """
    # Extract content between markers
    begin_marker = "*** Begin Patch"
    end_marker = "*** End Patch"

    begin_idx = text.find(begin_marker)
    if begin_idx == -1:
        raise PatchParseError("Missing '*** Begin Patch' marker")
    end_idx = text.find(end_marker, begin_idx)
    if end_idx == -1:
        raise PatchParseError("Missing '*** End Patch' marker")

    body = text[begin_idx + len(begin_marker) : end_idx].strip()
    if not body:
        return []

    lines = body.splitlines()
    operations: list[PatchOperation] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("*** Add File: "):
            path = line[len("*** Add File: ") :].strip()
            i += 1
            content_lines: list[str] = []
            while i < len(lines) and not lines[i].startswith("*** "):
                # Lines in Add File have a + prefix
                raw = lines[i]
                if raw.startswith("+"):
                    content_lines.append(raw[1:])
                else:
                    content_lines.append(raw)
                i += 1
            operations.append(AddFile(path=path, content="\n".join(content_lines)))

        elif line.startswith("*** Update File: "):
            path = line[len("*** Update File: ") :].strip()
            i += 1
            move_to: str | None = None
            chunks: list[Chunk] = []

            while i < len(lines) and (
                not lines[i].startswith("*** ") or lines[i].startswith("*** Move to: ")
            ):
                cur = lines[i]

                if cur.startswith("*** Move to: "):
                    move_to = cur[len("*** Move to: ") :].strip()
                    i += 1
                    continue

                if cur.startswith("@@"):
                    context = cur[2:].strip()
                    i += 1
                    changes: list[Change] = []
                    while i < len(lines):
                        cl = lines[i]
                        if cl.startswith("@@") or cl.startswith("*** "):
                            break
                        if cl.startswith("-"):
                            changes.append(Change(type="remove", content=cl[1:]))
                        elif cl.startswith("+"):
                            changes.append(Change(type="add", content=cl[1:]))
                        else:
                            # Context line (space prefix or no prefix) — skip
                            pass
                        i += 1
                    chunks.append(Chunk(context=context, changes=changes))
                else:
                    i += 1

            operations.append(UpdateFile(path=path, move_to=move_to, chunks=chunks))

        elif line.startswith("*** Delete File: "):
            path = line[len("*** Delete File: ") :].strip()
            i += 1
            operations.append(DeleteFile(path=path))

        else:
            i += 1

    return operations


# ---------------------------------------------------------------------------
# Applicator
# ---------------------------------------------------------------------------


def _find_context_line(file_lines: list[str], context: str, start_hint: int = 0) -> int:
    """Find the line matching the @@ context marker via fuzzy matching.

    Returns the 0-based line index, or -1 if not found.
    """
    if not context:
        return start_hint

    # Exact match
    for idx in range(start_hint, len(file_lines)):
        if file_lines[idx].rstrip() == context.rstrip():
            return idx
    # Retry from beginning if start_hint > 0
    if start_hint > 0:
        for idx in range(0, start_hint):
            if file_lines[idx].rstrip() == context.rstrip():
                return idx

    # Fuzzy match — stripped whitespace
    stripped_ctx = context.strip()
    for idx in range(start_hint, len(file_lines)):
        if file_lines[idx].strip() == stripped_ctx:
            return idx
    if start_hint > 0:
        for idx in range(0, start_hint):
            if file_lines[idx].strip() == stripped_ctx:
                return idx

    # Fuzzy match — contains
    if len(stripped_ctx) > 5:
        for idx in range(start_hint, len(file_lines)):
            if stripped_ctx in file_lines[idx]:
                return idx
        if start_hint > 0:
            for idx in range(0, start_hint):
                if stripped_ctx in file_lines[idx]:
                    return idx

    return -1


def _apply_chunk(file_lines: list[str], chunk: Chunk, start_hint: int) -> tuple[list[str], int]:
    """Apply a single chunk to file_lines, returning (new_lines, next_hint)."""
    anchor = _find_context_line(file_lines, chunk.context, start_hint)
    if anchor == -1 and chunk.context:
        raise PatchApplyError(f"Could not find context anchor: {chunk.context!r}")

    # Walk forward from anchor to find the remove lines
    pos = anchor + 1 if chunk.context else anchor

    result = list(file_lines)
    offset = 0

    for change in chunk.changes:
        actual_pos = pos + offset
        if change.type == "remove":
            if actual_pos < len(result):
                actual_line = result[actual_pos].rstrip("\n")
                expected = change.content.rstrip("\n")
                if actual_line.rstrip() != expected.rstrip():
                    # Try to find the line nearby
                    found = False
                    for delta in range(1, 6):
                        for candidate in (actual_pos + delta, actual_pos - delta):
                            if 0 <= candidate < len(result):
                                if result[candidate].rstrip("\n").rstrip() == expected.rstrip():
                                    # Adjust offset
                                    offset += candidate - actual_pos
                                    actual_pos = candidate
                                    found = True
                                    break
                        if found:
                            break
                    if not found:
                        raise PatchApplyError(
                            f"Remove line mismatch at line {actual_pos + 1}: "
                            f"expected {expected!r}, got {actual_line!r}"
                        )
                result.pop(actual_pos)
                offset -= 1
            else:
                raise PatchApplyError(
                    f"Remove line beyond end of file at position {actual_pos + 1}"
                )
        elif change.type == "add":
            actual_pos = pos + offset
            result.insert(actual_pos, change.content)
            offset += 1

    next_hint = pos + offset
    return result, next_hint


class PatchApplyError(Exception):
    """Raised when a patch cannot be applied."""


def apply_operations(ops: list[PatchOperation], base_dir: Path) -> str:
    """Apply a list of patch operations to files under base_dir.

    Returns a human-readable summary of applied changes.
    """
    results: list[str] = []

    for op in ops:
        if isinstance(op, AddFile):
            target = base_dir / op.path
            if target.exists():
                results.append(f"Warning: Overwriting existing file: {op.path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(op.content + "\n", encoding="utf-8")
            results.append(f"Added: {op.path}")

        elif isinstance(op, DeleteFile):
            target = base_dir / op.path
            if not target.exists():
                results.append(f"Warning: File not found for deletion: {op.path}")
                continue
            target.unlink()
            results.append(f"Deleted: {op.path}")

        elif isinstance(op, UpdateFile):
            target = base_dir / op.path
            if not target.exists():
                raise PatchApplyError(f"File not found for update: {op.path}")

            content = target.read_text(encoding="utf-8")
            file_lines = content.splitlines()

            hint = 0
            for chunk in op.chunks:
                file_lines, hint = _apply_chunk(file_lines, chunk, hint)

            new_content = "\n".join(file_lines)
            if content.endswith("\n"):
                new_content += "\n"

            if op.move_to:
                new_target = base_dir / op.move_to
                new_target.parent.mkdir(parents=True, exist_ok=True)
                new_target.write_text(new_content, encoding="utf-8")
                target.unlink()
                results.append(f"Updated and moved: {op.path} → {op.move_to}")
            else:
                target.write_text(new_content, encoding="utf-8")
                results.append(f"Updated: {op.path}")

    if not results:
        return "No operations to apply."
    return "\n".join(results)
