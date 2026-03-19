"""Tests for text_utils — display-width-aware truncation."""

from hooty.text_utils import truncate_display


class TestTruncateDisplay:
    """Test CJK-safe display-width truncation."""

    def test_ascii_short_no_truncation(self):
        assert truncate_display("hello", 50) == "hello"

    def test_ascii_exact_fit(self):
        text = "A" * 50
        assert truncate_display(text, 50) == text

    def test_ascii_truncated(self):
        text = "A" * 60
        result = truncate_display(text, 50)
        assert result.endswith("...")
        assert len(result) <= 50

    def test_cjk_no_truncation(self):
        # 10 CJK chars = 20 display columns
        text = "あ" * 10
        assert truncate_display(text, 20) == text

    def test_cjk_truncated(self):
        # 30 CJK chars = 60 display columns, truncate to 50
        text = "あ" * 30
        result = truncate_display(text, 50)
        assert result.endswith("...")
        # Verify display width within budget
        width = sum(2 if ord(c) > 0x7F else 1 for c in result if c != ".")
        dots = result.count(".")
        assert width + dots <= 50

    def test_mixed_cjk_ascii(self):
        text = "Hello世界Python日本語テスト" * 3
        result = truncate_display(text, 50)
        assert result.endswith("...")
        assert len(result) < len(text)

    def test_custom_suffix(self):
        text = "A" * 60
        result = truncate_display(text, 50, suffix=" …")
        assert result.endswith(" …")

    def test_empty_string(self):
        assert truncate_display("", 50) == ""

    def test_cjk_boundary_no_split(self):
        # Ensure a wide char is not partially included
        # "あ" = 2 cols; with suffix "..." = 3 cols, budget = 7 cols for content
        # 3 "あ" = 6 cols fits, 4 "あ" = 8 cols doesn't
        text = "あ" * 6  # 12 display cols
        result = truncate_display(text, 10)
        assert result.endswith("...")
        # Content before "..." should be whole CJK chars only
        content = result[: -len("...")]
        for ch in content:
            assert ch == "あ"
