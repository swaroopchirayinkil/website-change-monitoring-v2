# -*- coding: utf-8 -*-
"""
monitor/config.py
-----------------
Centralized paths and constants for WebGlancer.
"""

from pathlib import Path

BASE_DIR = Path.cwd()
CACHE_DIR = BASE_DIR / ".visual_cache"
BASELINES_DIR = CACHE_DIR / "baselines"
LATEST_DIR = CACHE_DIR / "latest"
DIFFS_DIR = CACHE_DIR / "diffs"
REPORT_FILE = CACHE_DIR / "report.html"
DEFAULT_DOMAIN_FILE = CACHE_DIR / "domain.txt"

# Web dashboard template directory
PACKAGE_DIR = Path(__file__).parent
WEB_DIR = PACKAGE_DIR / "web"

def ensure_dirs():
    """Ensure baseline, latest, diffs, and cache directories exist."""
    for d in [CACHE_DIR, BASELINES_DIR, LATEST_DIR, DIFFS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    # Initialize domain.txt inside persistent cache volume if missing
    if not DEFAULT_DOMAIN_FILE.exists():
        root_domain_file = BASE_DIR / "domain.txt"
        if root_domain_file.exists() and root_domain_file.is_file():
            try:
                DEFAULT_DOMAIN_FILE.write_text(root_domain_file.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                pass
        else:
            try:
                DEFAULT_DOMAIN_FILE.write_text("", encoding="utf-8")
            except Exception:
                pass
