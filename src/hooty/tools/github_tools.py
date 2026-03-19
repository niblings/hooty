"""GitHub integration tools for Hooty."""

from __future__ import annotations

from typing import Optional

from agno.tools import Toolkit


def create_github_tools() -> Optional[Toolkit]:
    """Create GitHub tools if PyGithub is available."""
    try:
        from agno.tools.github import GithubTools

        return GithubTools()
    except ImportError:
        return None
