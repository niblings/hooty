"""Tests for SessionStats computation."""

from hooty.session_stats import (
    PersistedStats,
    RunStats,
    SessionStats,
    SubAgentRunStats,
    format_duration,
    load_persisted_stats,
    save_persisted_stats,
)


class TestRunStats:
    """Test RunStats dataclass."""

    def test_defaults(self):
        rs = RunStats()
        assert rs.elapsed == 0.0
        assert rs.input_tokens == 0
        assert rs.output_tokens == 0
        assert rs.total_tokens == 0
        assert rs.reasoning_tokens == 0
        assert rs.tool_calls == 0
        assert rs.ttft is None

    def test_custom_values(self):
        rs = RunStats(
            elapsed=2.5,
            input_tokens=1000,
            output_tokens=500,
            total_tokens=1500,
            tool_calls=3,
            ttft=0.35,
        )
        assert rs.elapsed == 2.5
        assert rs.input_tokens == 1000
        assert rs.output_tokens == 500
        assert rs.total_tokens == 1500
        assert rs.tool_calls == 3
        assert rs.ttft == 0.35


class TestSessionStats:
    """Test SessionStats aggregation."""

    def test_empty(self):
        ss = SessionStats()
        assert ss.total_runs == 0
        assert ss.total_elapsed == 0.0
        assert ss.total_input_tokens == 0
        assert ss.total_output_tokens == 0
        assert ss.total_reasoning_tokens == 0
        assert ss.total_tool_calls == 0
        assert ss.avg_elapsed == 0.0
        assert ss.avg_ttft is None

    def test_single_run(self):
        ss = SessionStats()
        ss.add_run(RunStats(
            elapsed=3.0,
            input_tokens=2000,
            output_tokens=800,
            tool_calls=2,
            ttft=0.5,
        ))
        assert ss.total_runs == 1
        assert ss.total_elapsed == 3.0
        assert ss.total_input_tokens == 2000
        assert ss.total_output_tokens == 800
        assert ss.total_tool_calls == 2
        assert ss.avg_elapsed == 3.0
        assert ss.avg_ttft == 0.5

    def test_multiple_runs(self):
        ss = SessionStats()
        ss.add_run(RunStats(
            elapsed=2.0,
            input_tokens=1000,
            output_tokens=400,
            tool_calls=1,
            ttft=0.3,
        ))
        ss.add_run(RunStats(
            elapsed=4.0,
            input_tokens=3000,
            output_tokens=600,
            tool_calls=5,
            ttft=0.7,
        ))
        assert ss.total_runs == 2
        assert ss.total_elapsed == 6.0
        assert ss.total_input_tokens == 4000
        assert ss.total_output_tokens == 1000
        assert ss.total_tool_calls == 6
        assert ss.avg_elapsed == 3.0
        assert ss.avg_ttft == 0.5

    def test_avg_ttft_skips_none(self):
        ss = SessionStats()
        ss.add_run(RunStats(elapsed=1.0, ttft=0.2))
        ss.add_run(RunStats(elapsed=2.0, ttft=None))
        ss.add_run(RunStats(elapsed=3.0, ttft=0.4))
        assert ss.avg_ttft is not None
        assert abs(ss.avg_ttft - 0.3) < 1e-9  # (0.2 + 0.4) / 2

    def test_avg_ttft_all_none(self):
        ss = SessionStats()
        ss.add_run(RunStats(elapsed=1.0))
        ss.add_run(RunStats(elapsed=2.0))
        assert ss.avg_ttft is None

    def test_total_reasoning_tokens(self):
        ss = SessionStats()
        ss.add_run(RunStats(elapsed=1.0, reasoning_tokens=500))
        ss.add_run(RunStats(elapsed=2.0, reasoning_tokens=300))
        ss.add_run(RunStats(elapsed=3.0))  # no reasoning
        assert ss.total_reasoning_tokens == 800

    def test_add_run_appends(self):
        ss = SessionStats()
        r1 = RunStats(elapsed=1.0)
        r2 = RunStats(elapsed=2.0)
        ss.add_run(r1)
        ss.add_run(r2)
        assert ss.runs == [r1, r2]


class TestPersistedStats:
    """Test PersistedStats dataclass."""

    def test_defaults(self):
        ps = PersistedStats()
        assert ps.total_runs == 0
        assert ps.total_elapsed == 0.0
        assert ps.total_input_tokens == 0
        assert ps.total_output_tokens == 0
        assert ps.total_reasoning_tokens == 0
        assert ps.total_tool_calls == 0
        assert ps.ttft_sum == 0.0
        assert ps.ttft_count == 0

    def test_avg_elapsed(self):
        ps = PersistedStats(total_runs=4, total_elapsed=20.0)
        assert ps.avg_elapsed == 5.0

    def test_avg_elapsed_zero_runs(self):
        ps = PersistedStats()
        assert ps.avg_elapsed == 0.0

    def test_avg_ttft(self):
        ps = PersistedStats(ttft_sum=1.5, ttft_count=3)
        assert ps.avg_ttft == 0.5

    def test_avg_ttft_zero_count(self):
        ps = PersistedStats()
        assert ps.avg_ttft is None


class TestSessionStatsGrandTotals:
    """Test grand total properties combining persisted + current process."""

    def _make_stats(self) -> SessionStats:
        ss = SessionStats()
        ss.persisted = PersistedStats(
            total_runs=10,
            total_elapsed=100.0,
            total_input_tokens=50000,
            total_output_tokens=20000,
            total_tool_calls=30,
            ttft_sum=4.0,
            ttft_count=10,
        )
        ss.add_run(RunStats(elapsed=5.0, input_tokens=2000, output_tokens=800, tool_calls=2, ttft=0.5))
        ss.add_run(RunStats(elapsed=3.0, input_tokens=1000, output_tokens=400, tool_calls=1, ttft=0.3))
        return ss

    def test_grand_total_runs(self):
        ss = self._make_stats()
        assert ss.grand_total_runs == 12  # 10 + 2

    def test_grand_total_elapsed(self):
        ss = self._make_stats()
        assert ss.grand_total_elapsed == 108.0  # 100 + 5 + 3

    def test_grand_avg_elapsed(self):
        ss = self._make_stats()
        assert ss.grand_avg_elapsed == 108.0 / 12

    def test_grand_avg_ttft(self):
        ss = self._make_stats()
        # (4.0 + 0.5 + 0.3) / (10 + 2) = 4.8 / 12 = 0.4
        assert ss.grand_avg_ttft is not None
        assert abs(ss.grand_avg_ttft - 0.4) < 1e-9

    def test_has_persisted_true(self):
        ss = self._make_stats()
        assert ss.has_persisted is True

    def test_has_persisted_false(self):
        ss = SessionStats()
        assert ss.has_persisted is False

    def test_grand_totals_without_persisted(self):
        ss = SessionStats()
        ss.add_run(RunStats(elapsed=5.0, ttft=0.5))
        assert ss.grand_total_runs == 1
        assert ss.grand_total_elapsed == 5.0
        assert ss.grand_avg_elapsed == 5.0
        assert ss.grand_avg_ttft == 0.5

    def test_grand_avg_ttft_with_none_current(self):
        ss = SessionStats()
        ss.persisted = PersistedStats(ttft_sum=2.0, ttft_count=4)
        ss.add_run(RunStats(elapsed=1.0, ttft=None))
        # Only persisted: 2.0 / 4 = 0.5
        assert ss.grand_avg_ttft is not None
        assert abs(ss.grand_avg_ttft - 0.5) < 1e-9


class TestPersistence:
    """Test save/load round-trip and edge cases."""

    def test_save_and_load(self, tmp_path):
        ss = SessionStats()
        ss.add_run(RunStats(elapsed=5.0, input_tokens=2000, output_tokens=800, tool_calls=2, ttft=0.5))
        ss.add_run(RunStats(elapsed=3.0, input_tokens=1000, output_tokens=400, tool_calls=1, ttft=0.3))

        save_persisted_stats(tmp_path, ss)

        loaded = load_persisted_stats(tmp_path)
        assert loaded.total_runs == 2
        assert loaded.total_elapsed == 8.0
        assert loaded.total_input_tokens == 3000
        assert loaded.total_output_tokens == 1200
        assert loaded.total_reasoning_tokens == 0
        assert loaded.total_tool_calls == 3
        assert abs(loaded.ttft_sum - 0.8) < 1e-9
        assert loaded.ttft_count == 2

    def test_save_and_load_reasoning_tokens(self, tmp_path):
        ss = SessionStats()
        ss.add_run(RunStats(elapsed=5.0, input_tokens=2000, output_tokens=800, reasoning_tokens=500))
        ss.add_run(RunStats(elapsed=3.0, input_tokens=1000, output_tokens=400, reasoning_tokens=300))

        save_persisted_stats(tmp_path, ss)

        loaded = load_persisted_stats(tmp_path)
        assert loaded.total_reasoning_tokens == 800

    def test_load_missing_file(self, tmp_path):
        loaded = load_persisted_stats(tmp_path)
        assert loaded.total_runs == 0
        assert loaded.total_elapsed == 0.0

    def test_load_corrupt_file(self, tmp_path):
        (tmp_path / "stats.json").write_text("not json!!!", encoding="utf-8")
        loaded = load_persisted_stats(tmp_path)
        assert loaded.total_runs == 0

    def test_load_partial_data(self, tmp_path):
        (tmp_path / "stats.json").write_text('{"total_runs": 5}', encoding="utf-8")
        loaded = load_persisted_stats(tmp_path)
        assert loaded.total_runs == 5
        assert loaded.total_elapsed == 0.0

    def test_cumulative_across_processes(self, tmp_path):
        # Simulate first process
        ss1 = SessionStats()
        ss1.add_run(RunStats(elapsed=5.0, input_tokens=2000, output_tokens=800, tool_calls=2, ttft=0.5))
        save_persisted_stats(tmp_path, ss1)

        # Simulate second process loading and adding more runs
        ss2 = SessionStats()
        ss2.persisted = load_persisted_stats(tmp_path)
        ss2.add_run(RunStats(elapsed=3.0, input_tokens=1000, output_tokens=400, tool_calls=1, ttft=0.3))
        save_persisted_stats(tmp_path, ss2)

        # Verify cumulative values
        loaded = load_persisted_stats(tmp_path)
        assert loaded.total_runs == 2
        assert loaded.total_elapsed == 8.0
        assert loaded.total_input_tokens == 3000
        assert loaded.total_output_tokens == 1200
        assert loaded.total_tool_calls == 3
        assert abs(loaded.ttft_sum - 0.8) < 1e-9
        assert loaded.ttft_count == 2

    def test_save_creates_directory(self, tmp_path):
        nested = tmp_path / "a" / "b"
        ss = SessionStats()
        ss.add_run(RunStats(elapsed=1.0))
        save_persisted_stats(nested, ss)
        assert (nested / "stats.json").exists()


class TestFormatDuration:
    """Test format_duration helper."""

    def test_seconds(self):
        assert format_duration(7.5) == "7.5s"

    def test_zero(self):
        assert format_duration(0.0) == "0.0s"

    def test_minutes(self):
        assert format_duration(80) == "1m 20s"

    def test_exact_minute(self):
        assert format_duration(60) == "1m 0s"

    def test_hours(self):
        assert format_duration(3900) == "1h 5m"

    def test_exact_hour(self):
        assert format_duration(3600) == "1h 0m"


class TestSubAgentRunStats:
    """Test SubAgentRunStats dataclass."""

    def test_defaults(self):
        r = SubAgentRunStats()
        assert r.agent_name == ""
        assert r.elapsed == 0.0
        assert r.tool_calls == 0
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.error is False

    def test_custom_values(self):
        r = SubAgentRunStats(
            agent_name="explore",
            elapsed=5.2,
            tool_calls=10,
            input_tokens=3000,
            output_tokens=800,
            error=True,
        )
        assert r.agent_name == "explore"
        assert r.elapsed == 5.2
        assert r.tool_calls == 10
        assert r.input_tokens == 3000
        assert r.output_tokens == 800
        assert r.error is True


class TestSessionStatsSubAgent:
    """Test sub-agent statistics in SessionStats."""

    def test_empty(self):
        ss = SessionStats()
        assert ss.total_sub_agent_runs == 0
        assert ss.total_sub_agent_elapsed == 0.0
        assert ss.total_sub_agent_tool_calls == 0
        assert ss.total_sub_agent_input_tokens == 0
        assert ss.total_sub_agent_output_tokens == 0
        assert ss.sub_agent_errors == 0

    def test_add_sub_agent_run(self):
        ss = SessionStats()
        ss.add_sub_agent_run(SubAgentRunStats(
            agent_name="explore",
            elapsed=5.0,
            tool_calls=10,
            input_tokens=3000,
            output_tokens=800,
        ))
        ss.add_sub_agent_run(SubAgentRunStats(
            agent_name="summarize",
            elapsed=2.5,
            tool_calls=3,
            input_tokens=1000,
            output_tokens=400,
            error=True,
        ))
        assert ss.total_sub_agent_runs == 2
        assert ss.total_sub_agent_elapsed == 7.5
        assert ss.total_sub_agent_tool_calls == 13
        assert ss.total_sub_agent_input_tokens == 4000
        assert ss.total_sub_agent_output_tokens == 1200
        assert ss.sub_agent_errors == 1

    def test_sub_agent_runs_independent_of_main_runs(self):
        ss = SessionStats()
        ss.add_run(RunStats(elapsed=10.0, tool_calls=5))
        ss.add_sub_agent_run(SubAgentRunStats(agent_name="explore", elapsed=3.0, tool_calls=8))
        assert ss.total_runs == 1
        assert ss.total_sub_agent_runs == 1
        assert ss.total_tool_calls == 5
        assert ss.total_sub_agent_tool_calls == 8


class TestPersistedStatsSubAgent:
    """Test sub-agent fields in PersistedStats."""

    def test_defaults(self):
        ps = PersistedStats()
        assert ps.total_sub_agent_runs == 0
        assert ps.total_sub_agent_elapsed == 0.0
        assert ps.total_sub_agent_tool_calls == 0
        assert ps.total_sub_agent_input_tokens == 0
        assert ps.total_sub_agent_output_tokens == 0
        assert ps.total_sub_agent_errors == 0

    def test_save_and_load_sub_agent_stats(self, tmp_path):
        ss = SessionStats()
        ss.add_sub_agent_run(SubAgentRunStats(
            agent_name="explore", elapsed=5.0, tool_calls=10,
            input_tokens=3000, output_tokens=800,
        ))
        ss.add_sub_agent_run(SubAgentRunStats(
            agent_name="summarize", elapsed=2.5, tool_calls=3,
            input_tokens=1000, output_tokens=400, error=True,
        ))
        save_persisted_stats(tmp_path, ss)

        loaded = load_persisted_stats(tmp_path)
        assert loaded.total_sub_agent_runs == 2
        assert loaded.total_sub_agent_elapsed == 7.5
        assert loaded.total_sub_agent_tool_calls == 13
        assert loaded.total_sub_agent_input_tokens == 4000
        assert loaded.total_sub_agent_output_tokens == 1200
        assert loaded.total_sub_agent_errors == 1

    def test_load_missing_sub_agent_fields(self, tmp_path):
        """Existing stats.json without sub-agent fields should default to 0."""
        (tmp_path / "stats.json").write_text(
            '{"total_runs": 5, "total_elapsed": 10.0}', encoding="utf-8"
        )
        loaded = load_persisted_stats(tmp_path)
        assert loaded.total_runs == 5
        assert loaded.total_sub_agent_runs == 0
        assert loaded.total_sub_agent_elapsed == 0.0

    def test_cumulative_sub_agent_stats(self, tmp_path):
        """Sub-agent stats accumulate across processes."""
        ss1 = SessionStats()
        ss1.add_sub_agent_run(SubAgentRunStats(
            agent_name="explore", elapsed=5.0, tool_calls=10,
            input_tokens=3000, output_tokens=800,
        ))
        save_persisted_stats(tmp_path, ss1)

        ss2 = SessionStats()
        ss2.persisted = load_persisted_stats(tmp_path)
        ss2.add_sub_agent_run(SubAgentRunStats(
            agent_name="summarize", elapsed=2.5, tool_calls=3,
            input_tokens=1000, output_tokens=400, error=True,
        ))
        save_persisted_stats(tmp_path, ss2)

        loaded = load_persisted_stats(tmp_path)
        assert loaded.total_sub_agent_runs == 2
        assert loaded.total_sub_agent_elapsed == 7.5
        assert loaded.total_sub_agent_tool_calls == 13
        assert loaded.total_sub_agent_input_tokens == 4000
        assert loaded.total_sub_agent_output_tokens == 1200
        assert loaded.total_sub_agent_errors == 1
