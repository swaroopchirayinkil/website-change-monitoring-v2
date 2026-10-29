# -*- coding: utf-8 -*-
"""
monitor/history_manager.py
---------------------------
Automated historical report data capture, daily JSON persistence, and
on-demand multi-period report aggregation (Daily, Weekly, Monthly, Custom).
"""

import csv
import io
import json
import re
from datetime import datetime, date, timedelta
from pathlib import Path
from monitor.config import (
    HISTORY_DIR,
    CACHE_DIR,
    REPORT_FILE,
    DEFAULT_DOMAIN_FILE,
    ensure_dirs,
)
from monitor.domain_manager import load_urls_from_file


def get_history_file_for_date(target_date: str) -> Path:
    """Return Path for daily report JSON file (format: history/report_YYYY-MM-DD.json)."""
    return HISTORY_DIR / f"report_{target_date}.json"


def record_daily_scan_data(results: list[dict], scan_date: str = None, timestamp: str = None) -> Path:
    """
    Persist structured scan results to a daily JSON file in .visual_cache/history/.
    Merges with existing records for that day if multiple scans run on the same calendar day.
    """
    ensure_dirs()
    now_dt = datetime.now()
    date_str = scan_date or now_dt.strftime("%Y-%m-%d")
    now_str = timestamp or now_dt.strftime("%Y-%m-%d %H:%M:%S")

    target_file = get_history_file_for_date(date_str)

    existing_record = {}
    if target_file.exists():
        try:
            existing_record = json.loads(target_file.read_text(encoding="utf-8"))
        except Exception:
            existing_record = {}

    existing_domains_map = {}
    existing_scans = existing_record.get("scans", [])

    if "domains" in existing_record and isinstance(existing_record["domains"], list):
        for item in existing_record["domains"]:
            if "url" in item:
                existing_domains_map[item["url"]] = item

    # Build standardized domain entries from fresh results
    scan_domains_list = []
    for r in results:
        url = r.get("url")
        if not url:
            continue
        try:
            pct = round(float(r.get("percentage", 0.0)), 2)
        except (ValueError, TypeError):
            pct = 0.0
        try:
            px = int(r.get("changed_pixels", 0))
        except (ValueError, TypeError):
            px = 0

        domain_entry = {
            "url": url,
            "status": r.get("status", "Unchanged"),
            "percentage": pct,
            "changed_pixels": px,
            "baseline_last_updated": r.get("baseline_last_updated", ""),
            "error": r.get("error", None),
            "timestamp": now_str,
        }
        existing_domains_map[url] = domain_entry
        scan_domains_list.append(domain_entry)

    # Append to daily scans log (keep up to 48 scans per day to avoid unbounded growth)
    existing_scans.append({
        "timestamp": now_str,
        "domains_count": len(scan_domains_list),
        "changed": sum(1 for d in scan_domains_list if d["status"] == "Changed"),
        "unchanged": sum(1 for d in scan_domains_list if d["status"] == "Unchanged"),
        "failed": sum(1 for d in scan_domains_list if d["status"] == "Failed"),
    })
    if len(existing_scans) > 48:
        existing_scans = existing_scans[-48:]

    consolidated_domains = list(existing_domains_map.values())
    total_count = len(consolidated_domains)
    changed_count = sum(1 for d in consolidated_domains if d["status"] == "Changed")
    unchanged_count = sum(1 for d in consolidated_domains if d["status"] == "Unchanged")
    failed_count = sum(1 for d in consolidated_domains if d["status"] == "Failed")

    data = {
        "date": date_str,
        "last_updated": now_str,
        "total": total_count,
        "changed": changed_count,
        "unchanged": unchanged_count,
        "failed": failed_count,
        "domains": consolidated_domains,
        "scans": existing_scans,
    }

    temp_file = target_file.with_suffix(".tmp")
    temp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp_file.replace(target_file)

    return target_file


def seed_history_from_existing_reports():
    """
    Backfill daily JSON history from existing HTML report files if JSON does not exist yet.
    Scans report_YYYY-MM-DD.html files in CACHE_DIR and extracts embedded window.initialReportData.
    """
    ensure_dirs()
    pattern = re.compile(r"^report_(\d{4}-\d{2}-\d{2})\.html$")
    json_var_regex = re.compile(r"window\.initialReportData\s*=\s*(\[.*?\]);", re.DOTALL)

    for html_file in CACHE_DIR.glob("report_*.html"):
        match = pattern.match(html_file.name)
        if match:
            date_str = match.group(1)
            target_json = get_history_file_for_date(date_str)
            if not target_json.exists():
                try:
                    content = html_file.read_text(encoding="utf-8")
                    m = json_var_regex.search(content)
                    if m:
                        results = json.loads(m.group(1))
                        mtime_str = datetime.fromtimestamp(html_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                        record_daily_scan_data(results, scan_date=date_str, timestamp=mtime_str)
                except Exception:
                    pass

    # Also inspect live report.html if today's JSON is still missing
    today_str = date.today().strftime("%Y-%m-%d")
    today_json = get_history_file_for_date(today_str)
    if not today_json.exists() and REPORT_FILE.exists():
        try:
            content = REPORT_FILE.read_text(encoding="utf-8")
            m = json_var_regex.search(content)
            if m:
                results = json.loads(m.group(1))
                mtime_str = datetime.fromtimestamp(REPORT_FILE.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                record_daily_scan_data(results, scan_date=today_str, timestamp=mtime_str)
        except Exception:
            pass


def get_available_history_dates() -> list[str]:
    """Return sorted list of date strings (YYYY-MM-DD) for which JSON history exists."""
    ensure_dirs()
    seed_history_from_existing_reports()
    pattern = re.compile(r"^report_(\d{4}-\d{2}-\d{2})\.json$")
    dates = []
    for f in HISTORY_DIR.glob("report_*.json"):
        match = pattern.match(f.name)
        if match:
            dates.append(match.group(1))
    return sorted(dates, reverse=True)


def parse_date_range(period: str = "weekly", start_date: str = None, end_date: str = None) -> tuple[date, date]:
    """Resolve period string or custom dates into (start_date_obj, end_date_obj)."""
    today = date.today()
    period = (period or "weekly").lower()

    if period == "daily":
        d = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else today
        return d, d
    elif period == "weekly":
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else today
        start_d = end_d - timedelta(days=6)  # 7 calendar days total
        return start_d, end_d
    elif period == "monthly":
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else today
        start_d = end_d - timedelta(days=29)  # 30 calendar days total
        return start_d, end_d
    elif period == "custom":
        if start_date and end_date:
            try:
                s = datetime.strptime(start_date, "%Y-%m-%d").date()
                e = datetime.strptime(end_date, "%Y-%m-%d").date()
                if s > e:
                    s, e = e, s
                return s, e
            except ValueError:
                pass
        return today - timedelta(days=6), today
    else:
        return today - timedelta(days=6), today


def generate_periodic_report(period: str = "weekly", start_date: str = None, end_date: str = None) -> dict:
    """
    Generate an on-demand report for a specified period (daily, weekly, monthly, or custom).
    Analyzes all monitored domains from domain.txt and combines stored daily JSON records.
    """
    ensure_dirs()
    seed_history_from_existing_reports()

    start_d, end_d = parse_date_range(period, start_date, end_date)
    start_str = start_d.strftime("%Y-%m-%d")
    end_str = end_d.strftime("%Y-%m-%d")

    # Generate all date strings in the selected range
    curr_d = start_d
    dates_in_period = []
    while curr_d <= end_d:
        dates_in_period.append(curr_d.strftime("%Y-%m-%d"))
        curr_d += timedelta(days=1)

    # Load daily JSON records that fall within range
    daily_records_by_date = {}
    for date_key in dates_in_period:
        f = get_history_file_for_date(date_key)
        if f.exists():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                daily_records_by_date[date_key] = data
            except Exception:
                pass

    # Compile the comprehensive list of domains: domain.txt + any in historical data
    monitored_urls = load_urls_from_file(DEFAULT_DOMAIN_FILE) if DEFAULT_DOMAIN_FILE.exists() else []
    all_domains_set = set(monitored_urls)

    for data in daily_records_by_date.values():
        for d in data.get("domains", []):
            if "url" in d:
                all_domains_set.add(d["url"])

    sorted_domains = sorted(list(all_domains_set))

    # Process metrics for each domain
    domain_matrix = []
    for idx, url in enumerate(sorted_domains, start=1):
        timeline = []
        percentages = []
        changed_pixels_list = []
        statuses = []
        latest_info = None

        for date_key in dates_in_period:
            day_data = daily_records_by_date.get(date_key)
            domain_day_entry = None
            if day_data:
                for entry in day_data.get("domains", []):
                    if entry.get("url") == url:
                        domain_day_entry = entry
                        break

            if domain_day_entry:
                pct = float(domain_day_entry.get("percentage", 0.0))
                px = int(domain_day_entry.get("changed_pixels", 0))
                st = domain_day_entry.get("status", "Unchanged")
                percentages.append(pct)
                changed_pixels_list.append(px)
                statuses.append(st)
                latest_info = domain_day_entry
                timeline.append({
                    "date": date_key,
                    "has_data": True,
                    "status": st,
                    "percentage": round(pct, 2),
                    "changed_pixels": px,
                })
            else:
                timeline.append({
                    "date": date_key,
                    "has_data": False,
                    "status": "No Data",
                    "percentage": None,
                    "changed_pixels": None,
                })

        days_with_data = len(percentages)
        days_changed = sum(1 for s in statuses if s == "Changed")
        days_failed = sum(1 for s in statuses if s == "Failed")
        avg_mismatch = round(sum(percentages) / days_with_data, 2) if days_with_data > 0 else 0.0
        peak_mismatch = round(max(percentages), 2) if percentages else 0.0
        peak_changed_pixels = max(changed_pixels_list) if changed_pixels_list else 0
        latest_pct = round(percentages[-1], 2) if percentages else 0.0
        latest_st = statuses[-1] if statuses else "No Data"

        # Categorize overall period status
        if days_with_data == 0:
            period_status = "No Data"
        elif days_failed == days_with_data:
            period_status = "Failed"
        elif days_changed > 0:
            period_status = "Changed"
        else:
            period_status = "Unchanged"

        baseline_updated = latest_info.get("baseline_last_updated", "") if latest_info else ""
        error_msg = latest_info.get("error") if latest_info else None

        domain_matrix.append({
            "index": idx,
            "url": url,
            "period_status": period_status,
            "avg_mismatch": avg_mismatch,
            "peak_mismatch": peak_mismatch,
            "latest_mismatch": latest_pct,
            "peak_changed_pixels": peak_changed_pixels,
            "days_monitored": days_with_data,
            "days_changed": days_changed,
            "days_failed": days_failed,
            "total_days_in_period": len(dates_in_period),
            "baseline_last_updated": baseline_updated,
            "latest_status": latest_st,
            "error": error_msg,
            "timeline": timeline,
        })

    # Overall Summary KPIs
    total_domains = len(domain_matrix)
    changed_domains = sum(1 for d in domain_matrix if d["period_status"] == "Changed")
    unchanged_domains = sum(1 for d in domain_matrix if d["period_status"] == "Unchanged")
    failed_domains = sum(1 for d in domain_matrix if d["period_status"] == "Failed")
    no_data_domains = sum(1 for d in domain_matrix if d["period_status"] == "No Data")

    domains_with_data = [d for d in domain_matrix if d["days_monitored"] > 0]
    global_avg_mismatch = (
        round(sum(d["avg_mismatch"] for d in domains_with_data) / len(domains_with_data), 2)
        if domains_with_data
        else 0.0
    )

    return {
        "period": period,
        "start_date": start_str,
        "end_date": end_str,
        "total_days": len(dates_in_period),
        "dates_in_period": dates_in_period,
        "dates_with_data_count": len(daily_records_by_date),
        "total_domains": total_domains,
        "changed_domains_count": changed_domains,
        "unchanged_domains_count": unchanged_domains,
        "failed_domains_count": failed_domains,
        "no_data_domains_count": no_data_domains,
        "global_avg_mismatch": global_avg_mismatch,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "domain_matrix": domain_matrix,
    }


def export_report_csv(report_data: dict) -> str:
    """Generate CSV text for a periodic report formatted as a daily percentage matrix matching the frontend."""
    output = io.StringIO()
    writer = csv.writer(output)

    dates = report_data.get("dates_in_period", [])
    # Format date headers as DD-MON uppercase (e.g., 23-OCT, 24-OCT) matching the frontend screenshot
    formatted_date_headers = []
    for d in dates:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            formatted_date_headers.append(dt.strftime("%d-%b").upper())
        except Exception:
            formatted_date_headers.append(d)

    header = ["#", "TARGET DOMAIN / URL"] + formatted_date_headers
    writer.writerow(header)

    for item in report_data.get("domain_matrix", []):
        row = [f"#{item.get('index', '')}", item.get("url", "")]
        timeline_by_date = {t.get("date"): t for t in item.get("timeline", [])}
        for d in dates:
            t = timeline_by_date.get(d)
            if t and t.get("has_data"):
                if t.get("status") == "Failed":
                    row.append("Failed")
                else:
                    pct = t.get("percentage")
                    row.append(f"{pct:.2f}%" if pct is not None else "0.00%")
            else:
                row.append("—")
        writer.writerow(row)

    return output.getvalue()


def cleanup_old_history(max_days: int = 60):
    """Retain daily JSON report history within max_days (default 60 days)."""
    if not HISTORY_DIR.exists():
        return
    cutoff = date.today() - timedelta(days=max_days)
    pattern = re.compile(r"^report_(\d{4}-\d{2}-\d{2})\.json$")
    for f in HISTORY_DIR.glob("report_*.json"):
        match = pattern.match(f.name)
        if match:
            try:
                file_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
                if file_date < cutoff:
                    f.unlink(missing_ok=True)
            except ValueError:
                pass
