"""Load and resolve prompt templates from data/prompts.yaml."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ModePrompts:
    role: str
    instructions: list[str | dict]


@dataclass
class PromptsConfig:
    memory_policy: str
    modes: dict[str, ModePrompts] = field(default_factory=dict)


def load_prompts() -> PromptsConfig:
    """Load data/prompts.yaml and return a PromptsConfig."""
    path = Path(__file__).parent / "data" / "prompts.yaml"
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    modes: dict[str, ModePrompts] = {}
    for name, mode_data in raw.get("modes", {}).items():
        modes[name] = ModePrompts(
            role=mode_data["role"],
            instructions=mode_data["instructions"],
        )

    return PromptsConfig(
        memory_policy=raw["memory_policy"],
        modes=modes,
    )


def resolve_instructions(
    raw: list[str | dict],
    flags: dict[str, bool],
    template_vars: dict[str, str],
) -> list[str]:
    """Evaluate ``when`` conditions and substitute template variables.

    Returns the final list of instruction strings.
    """
    result: list[str] = []
    mapping = defaultdict(str, template_vars)
    for item in raw:
        if isinstance(item, str):
            result.append(item.format_map(mapping))
        elif isinstance(item, dict):
            when = item.get("when")
            if when and not _eval_when(when, flags):
                continue
            value = item["value"]
            result.append(value.format_map(mapping))
    return result


def _eval_when(expr: str, flags: dict[str, bool]) -> bool:
    """Simple condition evaluator: ``'key'`` or ``'not key'``."""
    expr = expr.strip()
    if expr.startswith("not "):
        return not flags.get(expr[4:].strip(), False)
    return flags.get(expr, False)
