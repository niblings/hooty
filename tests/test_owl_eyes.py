"""Tests for owl_eyes() function."""

import pytest

from hooty.config import owl_eyes


class TestOwlEyesDefault:
    """Test owl_eyes with default awake window [9, 21]."""

    @pytest.mark.parametrize("hour", [23, 0, 1, 2, 3, 4, 5, 6, 7])
    def test_sleepy_hours(self, hour):
        eye, color = owl_eyes(hour)
        assert eye == "ᴗ"
        assert color == "#9E8600"

    def test_squinting_waking_up(self):
        eye, color = owl_eyes(8)
        assert eye == "="
        assert color == "#9E8600"

    @pytest.mark.parametrize("hour", range(9, 22))
    def test_wide_open_hours(self, hour):
        eye, color = owl_eyes(hour)
        assert eye == "o"
        assert color == "#E6C200"

    def test_squinting_getting_sleepy(self):
        eye, color = owl_eyes(22)
        assert eye == "="
        assert color == "#9E8600"


class TestOwlEyesCustom:
    """Test owl_eyes with custom awake windows."""

    def test_early_bird(self):
        # awake 5-17
        assert owl_eyes(4, 5, 17)[0] == "="   # squinting (waking)
        assert owl_eyes(5, 5, 17)[0] == "o"   # wide open
        assert owl_eyes(17, 5, 17)[0] == "o"  # wide open (inclusive)
        assert owl_eyes(18, 5, 17)[0] == "="  # squinting (sleepy)
        assert owl_eyes(19, 5, 17)[0] == "ᴗ"  # sleepy

    def test_night_owl(self):
        # awake 12-23
        assert owl_eyes(11, 12, 23)[0] == "="  # squinting (waking)
        assert owl_eyes(12, 12, 23)[0] == "o"  # wide open
        assert owl_eyes(23, 12, 23)[0] == "o"  # wide open (inclusive)
        assert owl_eyes(0, 12, 23)[0] == "="   # squinting (sleepy), (23+1)%24=0
        assert owl_eyes(1, 12, 23)[0] == "ᴗ"   # sleepy
