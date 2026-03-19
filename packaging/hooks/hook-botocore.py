"""PyInstaller hook to strip unused AWS service definitions from botocore.

botocore bundles JSON models for all ~411 AWS services (~20 MB).
Hooty only uses bedrock-runtime, so we keep only the services that are
actually needed and exclude everything else to save ~15 MB.

This hook replaces PyInstaller's built-in botocore hook by collecting
only the data files we need.
"""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, get_package_paths

# Services required by Hooty
KEEP_SERVICES = {
    "bedrock",
    "bedrock-agent",
    "bedrock-agent-runtime",
    "bedrock-data-automation",
    "bedrock-data-automation-runtime",
    "bedrock-runtime",
    "bedrock-runtime-eap",
    "sts",         # Token retrieval
    "sso",         # SSO authentication
    "sso-oidc",    # SSO OIDC flow
}

# Collect all botocore data files first
_all_datas = collect_data_files("botocore")

_, botocore_dir = get_package_paths("botocore")
data_prefix = os.path.join(botocore_dir, "data")

datas = []
for src, dest in _all_datas:
    # Check if this file is inside botocore/data/<service>/
    if src.startswith(data_prefix + os.sep):
        rel = src[len(data_prefix) + 1:]
        # Top-level service directory name is the first path component
        service_name = rel.split(os.sep)[0] if os.sep in rel else None
        if service_name is not None and service_name not in KEEP_SERVICES:
            continue  # Skip this service's data files
    datas.append((src, dest))

hiddenimports = ["botocore"]
