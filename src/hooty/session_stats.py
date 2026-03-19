"""Session-level statistics tracking."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RunStats:
    """Stats for a single agent run."""

    elapsed: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    tool_calls: int = 0
    ttft: float | None = None


@dataclass
class SubAgentRunStats:
    """Stats for a single sub-agent invocation."""

    agent_name: str = ""
    elapsed: float = 0.0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: bool = False


@dataclass
class PersistedStats:
    """Cumulative statistics persisted across CLI processes."""

    total_runs: int = 0
    total_elapsed: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_reasoning_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_write_tokens: int = 0
    total_tool_calls: int = 0
    ttft_sum: float = 0.0
    ttft_count: int = 0
    total_sub_agent_runs: int = 0
    total_sub_agent_elapsed: float = 0.0
    total_sub_agent_tool_calls: int = 0
    total_sub_agent_input_tokens: int = 0
    total_sub_agent_output_tokens: int = 0
    total_sub_agent_errors: int = 0

    @property
    def avg_elapsed(self) -> float:
        return self.total_elapsed / self.total_runs if self.total_runs else 0.0

    @property
    def avg_ttft(self) -> float | None:
        return self.ttft_sum / self.ttft_count if self.ttft_count else None


@dataclass
class SessionStats:
    """Cumulative session statistics."""

    runs: list[RunStats] = field(default_factory=list)
    sub_agent_runs: list[SubAgentRunStats] = field(default_factory=list)
    session_start: float = field(default_factory=time.monotonic)
    persisted: PersistedStats = field(default_factory=PersistedStats)

    def add_run(self, stats: RunStats) -> None:
        self.runs.append(stats)

    def add_sub_agent_run(self, stats: SubAgentRunStats) -> None:
        self.sub_agent_runs.append(stats)

    # -- Current process properties --

    @property
    def total_runs(self) -> int:
        return len(self.runs)

    @property
    def total_elapsed(self) -> float:
        return sum(r.elapsed for r in self.runs)

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.runs)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.runs)

    @property
    def total_reasoning_tokens(self) -> int:
        return sum(r.reasoning_tokens for r in self.runs)

    @property
    def total_tool_calls(self) -> int:
        return sum(r.tool_calls for r in self.runs)

    @property
    def avg_elapsed(self) -> float:
        return self.total_elapsed / len(self.runs) if self.runs else 0.0

    @property
    def avg_ttft(self) -> float | None:
        ttfts = [r.ttft for r in self.runs if r.ttft is not None]
        return sum(ttfts) / len(ttfts) if ttfts else None

    # -- Sub-agent properties --

    @property
    def total_sub_agent_runs(self) -> int:
        return len(self.sub_agent_runs)

    @property
    def total_sub_agent_elapsed(self) -> float:
        return sum(r.elapsed for r in self.sub_agent_runs)

    @property
    def total_sub_agent_tool_calls(self) -> int:
        return sum(r.tool_calls for r in self.sub_agent_runs)

    @property
    def total_sub_agent_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.sub_agent_runs)

    @property
    def total_sub_agent_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.sub_agent_runs)

    @property
    def sub_agent_errors(self) -> int:
        return sum(1 for r in self.sub_agent_runs if r.error)

    # -- Grand total properties (persisted + current process) --

    @property
    def grand_total_runs(self) -> int:
        return self.persisted.total_runs + self.total_runs

    @property
    def grand_total_elapsed(self) -> float:
        return self.persisted.total_elapsed + self.total_elapsed

    @property
    def grand_avg_elapsed(self) -> float:
        total = self.grand_total_runs
        return self.grand_total_elapsed / total if total else 0.0

    @property
    def grand_avg_ttft(self) -> float | None:
        ttfts = [r.ttft for r in self.runs if r.ttft is not None]
        ttft_sum = self.persisted.ttft_sum + sum(ttfts)
        ttft_count = self.persisted.ttft_count + len(ttfts)
        return ttft_sum / ttft_count if ttft_count else None

    @property
    def has_persisted(self) -> bool:
        """True if there are persisted stats from a previous process."""
        return self.persisted.total_runs > 0


_STATS_FILENAME = "stats.json"


def load_persisted_stats(session_dir: Path) -> PersistedStats:
    """Load persisted stats from a session directory. Returns empty stats on any error."""
    stats_path = session_dir / _STATS_FILENAME
    try:
        if stats_path.exists():
            data = json.loads(stats_path.read_text(encoding="utf-8"))
            return PersistedStats(
                total_runs=int(data.get("total_runs", 0)),
                total_elapsed=float(data.get("total_elapsed", 0.0)),
                total_input_tokens=int(data.get("total_input_tokens", 0)),
                total_output_tokens=int(data.get("total_output_tokens", 0)),
                total_reasoning_tokens=int(data.get("total_reasoning_tokens", 0)),
                total_cache_read_tokens=int(data.get("total_cache_read_tokens", 0)),
                total_cache_write_tokens=int(data.get("total_cache_write_tokens", 0)),
                total_tool_calls=int(data.get("total_tool_calls", 0)),
                ttft_sum=float(data.get("ttft_sum", 0.0)),
                ttft_count=int(data.get("ttft_count", 0)),
                total_sub_agent_runs=int(data.get("total_sub_agent_runs", 0)),
                total_sub_agent_elapsed=float(data.get("total_sub_agent_elapsed", 0.0)),
                total_sub_agent_tool_calls=int(data.get("total_sub_agent_tool_calls", 0)),
                total_sub_agent_input_tokens=int(data.get("total_sub_agent_input_tokens", 0)),
                total_sub_agent_output_tokens=int(data.get("total_sub_agent_output_tokens", 0)),
                total_sub_agent_errors=int(data.get("total_sub_agent_errors", 0)),
            )
    except Exception:
        logger.debug("Failed to load persisted stats from %s", stats_path, exc_info=True)
    return PersistedStats()


def save_persisted_stats(session_dir: Path, session_stats: SessionStats) -> None:
    """Save cumulative stats (persisted + current) to session directory. Best-effort."""
    stats_path = session_dir / _STATS_FILENAME
    try:
        ttfts = [r.ttft for r in session_stats.runs if r.ttft is not None]
        data = {
            "total_runs": session_stats.persisted.total_runs + session_stats.total_runs,
            "total_elapsed": session_stats.persisted.total_elapsed + session_stats.total_elapsed,
            "total_input_tokens": (
                session_stats.persisted.total_input_tokens + session_stats.total_input_tokens
            ),
            "total_output_tokens": (
                session_stats.persisted.total_output_tokens + session_stats.total_output_tokens
            ),
            "total_reasoning_tokens": (
                session_stats.persisted.total_reasoning_tokens
                + session_stats.total_reasoning_tokens
            ),
            "total_cache_read_tokens": (
                session_stats.persisted.total_cache_read_tokens
                + sum(r.cache_read_tokens for r in session_stats.runs)
            ),
            "total_cache_write_tokens": (
                session_stats.persisted.total_cache_write_tokens
                + sum(r.cache_write_tokens for r in session_stats.runs)
            ),
            "total_tool_calls": (
                session_stats.persisted.total_tool_calls + session_stats.total_tool_calls
            ),
            "ttft_sum": session_stats.persisted.ttft_sum + sum(ttfts),
            "ttft_count": session_stats.persisted.ttft_count + len(ttfts),
            "total_sub_agent_runs": (
                session_stats.persisted.total_sub_agent_runs
                + session_stats.total_sub_agent_runs
            ),
            "total_sub_agent_elapsed": (
                session_stats.persisted.total_sub_agent_elapsed
                + session_stats.total_sub_agent_elapsed
            ),
            "total_sub_agent_tool_calls": (
                session_stats.persisted.total_sub_agent_tool_calls
                + session_stats.total_sub_agent_tool_calls
            ),
            "total_sub_agent_input_tokens": (
                session_stats.persisted.total_sub_agent_input_tokens
                + session_stats.total_sub_agent_input_tokens
            ),
            "total_sub_agent_output_tokens": (
                session_stats.persisted.total_sub_agent_output_tokens
                + session_stats.total_sub_agent_output_tokens
            ),
            "total_sub_agent_errors": (
                session_stats.persisted.total_sub_agent_errors
                + session_stats.sub_agent_errors
            ),
        }
        from hooty.concurrency import atomic_write_text

        session_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(stats_path, json.dumps(data))
    except Exception:
        logger.debug("Failed to save persisted stats to %s", stats_path, exc_info=True)


def format_duration(seconds: float) -> str:
    """Format seconds into a human-readable short form.

    < 60s  -> "7.5s"
    >= 60s -> "1m 20s"
    >= 3600s -> "1h 5m"
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m = int(seconds) // 60
        s = int(seconds) % 60
        return f"{m}m {s}s"
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    return f"{h}h {m}m"
