# Contributing Guide

## About This Project

Hooty is an experimental project for coding agents.
The development process itself is part of the experiment - we actively use AI tools.

## AI-Powered Development

We recommend using coding agents like Claude Code or GitHub Copilot when contributing.

## Development Setup

- Python 3.12+, [uv](https://docs.astral.sh/uv/)
- `uv sync --all-extras`
- Tests: `uv run pytest -m "not integration"`
- Lint: `uv run ruff check src/ tests/`

## Language Rules

- PRs, Issues, and discussions: Japanese
- Source code comments: English
- Markdown files (`.md`): Japanese
