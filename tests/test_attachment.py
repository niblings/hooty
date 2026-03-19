"""Tests for attachment module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from hooty.attachment import (
    Attachment,
    AttachmentStack,
    _format_size,
    _process_image,
    _process_text,
)
from hooty.config import AppConfig, AttachmentConfig


@pytest.fixture
def config():
    """Create a minimal AppConfig for testing."""
    cfg = AppConfig()
    cfg.attachment = AttachmentConfig()
    return cfg


@pytest.fixture
def tmp_dir():
    """Create a temporary directory."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def text_file(tmp_dir):
    """Create a temporary text file."""
    p = tmp_dir / "test.py"
    p.write_text("print('hello world')\n" * 10, encoding="utf-8")
    return p


@pytest.fixture
def large_text_file(tmp_dir):
    """Create a large temporary text file."""
    p = tmp_dir / "large.log"
    # ~45KB of text → ~15000 tokens
    p.write_text("x" * 45000, encoding="utf-8")
    return p


@pytest.fixture
def image_file(tmp_dir):
    """Create a small test PNG image."""
    from PIL import Image as PILImage
    p = tmp_dir / "test.png"
    img = PILImage.new("RGB", (100, 80), color="red")
    img.save(p, format="PNG")
    img.close()
    return p


@pytest.fixture
def large_image_file(tmp_dir):
    """Create a large test PNG image that needs resizing."""
    from PIL import Image as PILImage
    p = tmp_dir / "big.png"
    img = PILImage.new("RGB", (3000, 2000), color="blue")
    img.save(p, format="PNG")
    img.close()
    return p


class TestFormatSize:
    def test_bytes(self):
        assert _format_size(500) == "500B"

    def test_kilobytes(self):
        assert _format_size(2300) == "2.2KB"

    def test_megabytes(self):
        assert _format_size(1_500_000) == "1.4MB"


class TestProcessText:
    def test_read_text_file(self, text_file):
        result = _process_text(text_file)
        assert isinstance(result, Attachment)
        assert result.kind == "text"
        assert result.display_name == "test.py"
        assert result.content is not None
        assert "hello world" in result.content
        assert result.file_size > 0

    def test_token_estimation(self, text_file):
        result = _process_text(text_file)
        assert isinstance(result, Attachment)
        expected = len(result.content) // 3
        assert result.estimated_tokens == expected

    def test_nonexistent_file(self, tmp_dir):
        result = _process_text(tmp_dir / "nope.txt")
        assert isinstance(result, str)
        assert "Cannot read" in result


class TestProcessImage:
    def test_small_image_no_resize(self, image_file, tmp_dir):
        attachments_dir = tmp_dir / "attachments"
        result = _process_image(image_file, max_side=1568, attachments_dir=attachments_dir)
        assert isinstance(result, Attachment)
        assert result.kind == "image"
        assert result.orig_width == 100
        assert result.orig_height == 80
        assert result.width == 100
        assert result.height == 80
        assert result.stored_path is not None
        assert result.stored_path.exists()

    def test_large_image_resized(self, large_image_file, tmp_dir):
        attachments_dir = tmp_dir / "attachments"
        result = _process_image(large_image_file, max_side=1568, attachments_dir=attachments_dir)
        assert isinstance(result, Attachment)
        assert result.orig_width == 3000
        assert result.orig_height == 2000
        assert max(result.width, result.height) <= 1568

    def test_token_estimation_image(self, image_file, tmp_dir):
        attachments_dir = tmp_dir / "attachments"
        result = _process_image(image_file, max_side=1568, attachments_dir=attachments_dir)
        assert isinstance(result, Attachment)
        expected = int((result.width * result.height) / 750)
        assert result.estimated_tokens == expected


class TestAttachmentStack:
    def test_add_text(self, config, text_file, tmp_dir):
        stack = AttachmentStack()
        result = stack.add(text_file, config=config, attachments_dir=tmp_dir / "att")
        assert isinstance(result, Attachment)
        assert stack.count == 1
        assert stack.total_tokens > 0

    def test_add_image(self, config, image_file, tmp_dir):
        stack = AttachmentStack()
        result = stack.add(image_file, config=config, attachments_dir=tmp_dir / "att")
        assert isinstance(result, Attachment)
        assert stack.count == 1
        assert result.kind == "image"

    def test_add_unsupported_extension(self, config, tmp_dir):
        p = tmp_dir / "archive.zip"
        p.write_bytes(b"PK\x03\x04")
        stack = AttachmentStack()
        result = stack.add(p, config=config, attachments_dir=tmp_dir / "att")
        assert isinstance(result, str)
        assert "unsupported" in result

    def test_add_nonexistent_file(self, config, tmp_dir):
        stack = AttachmentStack()
        result = stack.add(tmp_dir / "nope.txt", config=config, attachments_dir=tmp_dir / "att")
        assert isinstance(result, str)
        assert "not found" in result

    def test_remove(self, config, tmp_dir):
        # Create two text files
        f1 = tmp_dir / "a.py"
        f2 = tmp_dir / "b.py"
        f1.write_text("aaa", encoding="utf-8")
        f2.write_text("bbb", encoding="utf-8")

        stack = AttachmentStack()
        stack.add(f1, config=config, attachments_dir=tmp_dir / "att")
        stack.add(f2, config=config, attachments_dir=tmp_dir / "att")
        assert stack.count == 2

        removed = stack.remove([0])
        assert removed == 1
        assert stack.count == 1
        assert stack.items()[0].display_name == "b.py"

    def test_clear(self, config, text_file, tmp_dir):
        stack = AttachmentStack()
        stack.add(text_file, config=config, attachments_dir=tmp_dir / "att")
        assert stack.count == 1
        count = stack.clear()
        assert count == 1
        assert stack.count == 0

    def test_flush_text(self, config, text_file, tmp_dir):
        stack = AttachmentStack()
        stack.add(text_file, config=config, attachments_dir=tmp_dir / "att")
        images, text_block = stack.flush()
        assert images is None
        assert "--- Attached: test.py ---" in text_block
        assert stack.count == 0

    def test_flush_image(self, config, image_file, tmp_dir):
        stack = AttachmentStack()
        att_dir = tmp_dir / "att"
        stack.add(image_file, config=config, attachments_dir=att_dir)
        images, text_block = stack.flush()
        assert images is not None
        assert len(images) == 1
        assert text_block == ""
        assert stack.count == 0

    def test_token_limit_exceeded(self, config, tmp_dir):
        config.attachment.max_total_tokens = 100
        f1 = tmp_dir / "big.py"
        f1.write_text("x" * 600, encoding="utf-8")  # ~200 tokens

        stack = AttachmentStack()
        result = stack.add(f1, config=config, attachments_dir=tmp_dir / "att")
        assert isinstance(result, str)
        assert "limit exceeded" in result

    def test_vision_not_supported(self, config, image_file, tmp_dir):
        with patch("hooty.config.supports_vision", return_value=False):
            stack = AttachmentStack()
            result = stack.add(image_file, config=config, attachments_dir=tmp_dir / "att")
            assert isinstance(result, str)
            assert "vision not supported" in result

    def test_items_returns_copy(self, config, text_file, tmp_dir):
        stack = AttachmentStack()
        stack.add(text_file, config=config, attachments_dir=tmp_dir / "att")
        items = stack.items()
        items.clear()
        assert stack.count == 1  # original not affected
