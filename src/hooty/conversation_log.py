"""Conversation log — append Q&A pairs to per-session JSONL files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def log_conversation(
    project_dir: Path | None,
    *,
    session_id: str,
    model: str,
    user_input: str,
    output: str,
    full_output: str = "",
    output_tokens: int | None = None,
) -> None:
    """Append a conversation turn (Q&A pair) to the project conversation log."""
    if not project_dir or not output:
        return
    history_dir = project_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    entry: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "model": model,
        "input": user_input,
        "output": output,
    }
    if full_output and full_output != output:
        entry["full_output"] = full_output
    if output_tokens is not None:
        entry["output_tokens"] = output_tokens
    try:
        with open(history_dir / f"{session_id}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def load_recent_history(
    project_dir: Path | None,
    session_id: str,
    count: int,
) -> list[dict]:
    """Load last *count* Q&A pairs from the conversation log.

    Each returned dict has ``input`` and ``output`` keys.
    ``output`` is the full response text when available.
    """
    if not project_dir or count <= 0:
        return []
    path = project_dir / "history" / f"{session_id}.jsonl"
    try:
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        entries: list[dict] = []
        for line in lines[-count:]:
            rec = json.loads(line)
            entries.append({
                "input": rec.get("input", ""),
                "output": rec.get("full_output") or rec.get("output", ""),
            })
        return entries
    except (OSError, json.JSONDecodeError):
        return []
