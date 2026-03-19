"""Bootstrap for PyInstaller-bundled Hooty.

Sets locale environment variables to prevent Click/Typer encoding
errors on minimal systems, then delegates to the real entry point.
"""

import os

os.environ.setdefault("LC_ALL", "C.UTF-8")
os.environ.setdefault("LANG", "C.UTF-8")

from hooty.main import app  # noqa: E402

app()
