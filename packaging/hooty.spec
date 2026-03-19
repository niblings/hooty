# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Hooty — onedir mode.

Usage:
    pyinstaller packaging/hooty.spec

Output:
    dist/hooty/          (directory with hooty executable + dependencies)
"""

import platform
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# rich._unicode_data contains version-specific modules with hyphens in their
# names (e.g. unicode17-0-0.py) loaded dynamically via importlib.  PyInstaller
# cannot detect them automatically, so we collect the entire sub-package.
_rich_unicode_hidden = collect_submodules("rich._unicode_data")
_rich_unicode_datas = collect_data_files("rich._unicode_data")

# Project root (one level up from this spec file)
PROJECT_ROOT = Path(SPECPATH).parent
SRC_DIR = PROJECT_ROOT / "src"

a = Analysis(
    [str(PROJECT_ROOT / "packaging" / "boot_hooty.py")],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=[
        # Bundled data files
        (str(SRC_DIR / "hooty" / "data" / "model_catalog.json"), "hooty/data"),
        (str(SRC_DIR / "hooty" / "data" / "prompts.yaml"), "hooty/data"),
        (str(SRC_DIR / "hooty" / "data" / "agents.yaml"), "hooty/data"),
        (str(SRC_DIR / "hooty" / "data" / "thinking_keywords.yaml"), "hooty/data"),
        # Builtin skills (recursive directory tree)
        (str(SRC_DIR / "hooty" / "data" / "skills"), "hooty/data/skills"),
    ] + _rich_unicode_datas,
    hiddenimports=[
        # --- Hooty internal modules (lazily imported) ---
        "hooty",
        "hooty.__init__",
        "hooty.main",
        "hooty.config",
        "hooty.providers",
        "hooty.agent_factory",
        "hooty.repl",
        "hooty.model_catalog",
        "hooty.session_store",
        "hooty.context",
        "hooty.tools",
        "hooty.tools.coding_tools",
        "hooty.tools.confirm",
        "hooty.tools.github_tools",
        "hooty.tools.search_tools",
        "hooty.tools.sql_tools",
        "hooty.tools.mcp_tools",
        # --- Agno framework (lazily imported) ---
        "agno",
        "agno.agent",
        "agno.compression.manager",
        "agno.db.base",
        "agno.db.sqlite",
        "agno.models.aws",
        "agno.models.azure",
        "agno.models.ollama",
        "agno.models.base",
        "agno.run.agent",
        "agno.session.summary",
        "agno.tools.coding",
        "agno.tools.duckduckgo",
        "agno.tools.github",
        "agno.tools.mcp",
        "agno.tools.reasoning",
        "agno.tools.sql",
        "agno.tools.website",
        "agno.utils.log",
        # --- AWS / Azure provider SDKs ---
        "boto3",
        "botocore",
        "aioboto3",
        "azure.ai.inference",
        # --- MCP ---
        "mcp",
        "mcp.client",
        "mcp.client.stdio",
        # --- prompt_toolkit ---
        "prompt_toolkit",
        "prompt_toolkit.completion",
        "prompt_toolkit.formatted_text",
        "prompt_toolkit.history",
        "prompt_toolkit.key_binding",
        "prompt_toolkit.styles",
        # --- Rich (+ dynamically loaded _unicode_data submodules) ---
        "rich",
        "rich.live",
        "rich.markdown",
        "rich.measure",
        "rich.segment",
        "rich.table",
    ] + _rich_unicode_hidden + [
        # --- Other runtime deps ---
        "yaml",
        "dotenv",
        "sqlalchemy",
        "aiosqlite",
        "tiktoken",
        "tiktoken_ext",
        "tiktoken_ext.openai_public",
        "tokenizers",
        "typer",
        "click",
        "psycopg2",
        # --- Search / web tools ---
        "ddgs",
        "bs4",
        # --- Ollama ---
        "ollama",
        "httpx",
        # --- GitHub ---
        "github",
        # --- Image processing (for /attach capture) ---
        "PIL",
        "PIL.Image",
    ],
    hookspath=[str(PROJECT_ROOT / "packaging" / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # GUI / heavy libs not needed
        "tkinter",
        "_tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        # PIL (Pillow) is required for /attach capture image resizing
        "cv2",
        # Dev tools
        "pytest",
        "ruff",
        "pyinstaller",
        "IPython",
        "notebook",
        "sphinx",
        "setuptools",
        "pip",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # onedir mode
    name="hooty",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=platform.system() != "Windows",  # Disable UPX on Windows (antivirus false positives)
    console=True,
    icon=str(PROJECT_ROOT / "packaging" / "hooty.ico"),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=platform.system() != "Windows",
    upx_exclude=[],
    name="hooty",
)
