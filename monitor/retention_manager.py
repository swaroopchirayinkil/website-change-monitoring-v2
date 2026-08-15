# -*- coding: utf-8 -*-
"""
monitor/retention_manager.py
-----------------------------
Daily HTML report retention management, historical archive tracking, and audit log cleanup.
"""

import re
from datetime import datetime, date, timedelta
from pathlib import Path
from monitor.config import CACHE_DIR
from monitor.auth import cleanup_old_login_logs


def get_baseline_timestamp_display(baseline_path: Path) -> str:
    """Return formatted timestamp string of baseline modification time."""
    if baseline_path.exists():
        try:
            mtime = baseline_path.stat().st_mtime
            dt = datetime.fromtimestamp(mtime)
            return dt.strftime("%d-%b-%Y %I:%M %p")
        except Exception:
            return "Baseline available"
    return "Baseline not created"


def cleanup_old_reports(max_days: int = 5):
    """Retain only the last 5 calendar days of reports, automatically deleting older reports."""
    if not CACHE_DIR.exists():
        return
    today = date.today()
    cutoff_date = today - timedelta(days=max_days)
    pattern = re.compile(r"^report_(\d{4}-\d{2}-\d{2})\.html$")

    for f in CACHE_DIR.glob("report_*.html"):
        match = pattern.match(f.name)
        if match:
            date_str = match.group(1)
            try:
                file_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if file_date < cutoff_date:
                    f.unlink(missing_ok=True)
            except ValueError:
                pass

    # Also perform 30-day retention cleanup for login audit logs
    cleanup_old_login_logs(max_days=30)


def get_historical_reports() -> list[dict]:
    """Retrieve list of available historical daily reports in CACHE_DIR (within 5-day retention window)."""
    if not CACHE_DIR.exists():
        return []
    cleanup_old_reports(max_days=5)

    pattern = re.compile(r"^report_(\d{4}-\d{2}-\d{2})\.html$")
    reports = []
    today_str = date.today().strftime("%Y-%m-%d")

    files = sorted(CACHE_DIR.glob("report_*.html"), reverse=True)
    for f in files:
        match = pattern.match(f.name)
        if match:
            date_str = match.group(1)
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                formatted_label = dt.strftime("%d-%b-%Y")
                is_today = (date_str == today_str)
                mtime = f.stat().st_mtime
                mod_time = datetime.fromtimestamp(mtime).strftime("%I:%M %p")
                reports.append({
                    "filename": f.name,
                    "date": date_str,
                    "formatted_date": formatted_label,
                    "is_today": is_today,
                    "mod_time": mod_time,
                    "size_kb": round(f.stat().st_size / 1024, 1)
                })
            except ValueError:
                pass
    return reports
