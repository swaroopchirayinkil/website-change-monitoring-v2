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
DEFAULT_DOMAIN_FILE = BASE_DIR / "domain.txt"

# Web dashboard template directory
PACKAGE_DIR = Path(__file__).parent
WEB_DIR = PACKAGE_DIR / "web"

def ensure_dirs():
    """Ensure baseline, latest, diffs, and cache directories exist."""
    for d in [CACHE_DIR, BASELINES_DIR, LATEST_DIR, DIFFS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
