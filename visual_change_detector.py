#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
visual_change_detector.py
-------------------------
A modern, high-speed visual change detection CLI tool for Single Page Applications (SPAs)
and dynamic websites using Playwright (Headless Chromium) and pixel-level image diffing.

Features:
- Parallel Browser Workers (-c / --concurrency): Scan multiple URLs concurrently.
- Headless Browser Rendering: Waits for JS execution & SPA hydration.
- Reusable Worker Browsers: Eliminates browser startup overhead per URL.
- Element Masking: Hide dynamic elements (timestamps, ads, widgets) before capture.
- Pixel-by-Pixel Diffing: High-precision visual change calculations.
- Visual Heatmap Generation: Highlights exact visual changes in red/magenta.
- Interactive HTML Report: Self-contained report with side-by-side diff viewers.
"""

import argparse
import hashlib
import http.server
import json
import os
import re
import shutil
import socketserver
import sys
import threading
import time
import webbrowser
from datetime import datetime, date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from PIL import Image, ImageChops, ImageEnhance
from playwright.sync_api import sync_playwright

CACHE_DIR = Path.cwd() / ".visual_cache"
BASELINES_DIR = CACHE_DIR / "baselines"
LATEST_DIR = CACHE_DIR / "latest"
DIFFS_DIR = CACHE_DIR / "diffs"
REPORT_FILE = CACHE_DIR / "report.html"

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

_thread_local = threading.local()
_thread_browsers = []
_thread_browsers_lock = threading.Lock()

def get_thread_browser():
    """Retrieve or initialize a thread-local Playwright browser instance to maximize scanning throughput."""
    if not hasattr(_thread_local, "playwright"):
        _thread_local.playwright = sync_playwright().start()
        _thread_local.browser = _thread_local.playwright.chromium.launch(headless=True)
        with _thread_browsers_lock:
            _thread_browsers.append((_thread_local.playwright, _thread_local.browser))
    return _thread_local.browser

def cleanup_all_browsers():
    """Safely shut down all active thread-local Playwright browser instances."""
    with _thread_browsers_lock:
        for pw, browser in _thread_browsers:
            try:
                browser.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass
        _thread_browsers.clear()

def ensure_dirs():
    """Ensure baseline, latest, diffs, and cache directories exist."""
    for d in [CACHE_DIR, BASELINES_DIR, LATEST_DIR, DIFFS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

def normalize_url(raw_url: str) -> str:
    """Normalize domain/URL input string to standard HTTP/HTTPS format."""
    url = raw_url.strip()
    if not url:
        return ""
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
    if not url.endswith("/") and not Path(url.split("?")[0].split("#")[0]).suffix and "?" not in url and "#" not in url:
        url = url + "/"
    return url

def load_urls_from_file(file_path: Path) -> list[str]:
    """Read URLs from a text file, ignoring empty lines and comments."""
    if not file_path.exists():
        return []
    lines = file_path.read_text(encoding="utf-8").splitlines()
    return [normalize_url(line) for line in lines if line.strip() and not line.strip().startswith("#")]

def add_domains_to_file(
    input_urls: list[str],
    target_file: Path = Path("domain.txt")
) -> tuple[list[str], list[str]]:
    """
    Append new non-duplicate domains to the target domain file.
    Returns (added_urls, duplicate_urls).
    """
    existing_urls = load_urls_from_file(target_file)
    existing_set = {u.rstrip("/").lower() for u in existing_urls}
    
    added_urls = []
    duplicate_urls = []
    
    for raw in input_urls:
        norm = normalize_url(raw)
        if not norm:
            continue
        key = norm.rstrip("/").lower()
        if key in existing_set:
            if norm not in duplicate_urls:
                duplicate_urls.append(norm)
        else:
            added_urls.append(norm)
            existing_set.add(key)
            
    if added_urls:
        content = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
        if content and not content.endswith("\n"):
            content += "\n"
        new_content = content + "\n".join(added_urls) + "\n"
        target_file.write_text(new_content, encoding="utf-8")
        
    return added_urls, duplicate_urls

def remove_domains_from_file(
    input_urls: list[str],
    target_file: Path = Path("domain.txt")
) -> list[str]:
    """
    Remove specified domains from target domain file and delete associated baseline/latest/diff cache files.
    Returns list of removed URLs.
    """
    if not target_file.exists():
        return []
        
    existing_urls = load_urls_from_file(target_file)
    remove_keys = {normalize_url(u).rstrip("/").lower() for u in input_urls if u.strip()}
    
    remaining_urls = []
    removed_urls = []
    
    for url in existing_urls:
        key = url.rstrip("/").lower()
        if key in remove_keys:
            removed_urls.append(url)
            # Remove cached screenshot files
            slug = url_to_slug(url)
            for p in [BASELINES_DIR / f"{slug}.png", LATEST_DIR / f"{slug}.png", DIFFS_DIR / f"{slug}_diff.png"]:
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
        else:
            remaining_urls.append(url)
            
    if removed_urls:
        new_content = "\n".join(remaining_urls) + ("\n" if remaining_urls else "")
        target_file.write_text(new_content, encoding="utf-8")
        
    return removed_urls

def url_to_slug(url: str) -> str:
    """Generate a clean, deterministic filename slug for a URL."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    sanitized = "".join(c if c.isalnum() else "_" for c in url.split("//")[-1])[:30]
    return f"{sanitized}_{digest}"

def capture_screenshot(
    url: str,
    output_path: Path,
    viewport_width: int = 1280,
    viewport_height: int = 800,
    full_page: bool = True,
    wait_ms: int = 1000,
    wait_selector: str = None,
    masks: list[str] = None,
    wait_until: str = "load",
    timeout: int = 30000,
    browser=None,
):
    """Launch or reuse headless browser, wait for page rendering, mask elements, and capture screenshot."""
    should_close_browser = False
    pw = None
    if browser is None:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        should_close_browser = True

    try:
        context = browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
            device_scale_factor=1,
        )
        page = context.new_page()
        
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout)
        except Exception as e:
            # Fallback if preferred wait_until timed out (DOM is usually loaded)
            if wait_until != "domcontentloaded":
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=10000)
                except Exception:
                    pass
            print(f"     [Warning] Navigation timeout for '{url}': {e}. Capturing rendered DOM state...")

        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=10000)
            except Exception:
                print(f"     [Warning] Wait selector '{wait_selector}' not found within timeout.")

        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)

        # Inject CSS to hide/mask dynamic volatile elements if specified
        if masks:
            css_rules = ", ".join(masks) + " { visibility: hidden !important; opacity: 0 !important; }"
            page.add_style_tag(content=css_rules)
            time.sleep(0.2)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output_path), full_page=full_page)
        context.close()
    finally:
        if should_close_browser:
            browser.close()
            if pw:
                pw.stop()

def compute_visual_diff(
    baseline_path: Path,
    latest_path: Path,
    diff_path: Path,
    threshold_percent: float = 0.1,
) -> dict:
    """Compare baseline and latest screenshots pixel-by-pixel."""
    img_base = Image.open(baseline_path).convert("RGB")
    img_live = Image.open(latest_path).convert("RGB")

    width = max(img_base.width, img_live.width)
    height = max(img_base.height, img_live.height)

    # Pad images to match maximum dimensions if viewport height varies
    if img_base.size != (width, height):
        padded = Image.new("RGB", (width, height), (255, 255, 255))
        padded.paste(img_base, (0, 0))
        img_base = padded

    if img_live.size != (width, height):
        padded = Image.new("RGB", (width, height), (255, 255, 255))
        padded.paste(img_live, (0, 0))
        img_live = padded

    # Compute absolute RGB difference
    diff_raw = ImageChops.difference(img_base, img_live)
    gray_diff = diff_raw.convert("L")

    # Filter minor noise/anti-aliasing (threshold < 15 out of 255)
    noise_cutoff = 15
    mask = gray_diff.point(lambda p: 255 if p > noise_cutoff else 0, mode="1")

    histogram = mask.histogram()
    changed_pixels = histogram[255] if len(histogram) > 255 else 0
    total_pixels = width * height
    percentage = (changed_pixels / total_pixels) * 100.0 if total_pixels > 0 else 0.0

    # Generate visual heatmap (bright magenta highlight on dimmed baseline)
    enhancer = ImageEnhance.Brightness(img_base.convert("L").convert("RGB"))
    dimmed_baseline = enhancer.enhance(0.4)
    highlight_color = Image.new("RGB", (width, height), (255, 0, 110))

    visual_heatmap = Image.composite(highlight_color, dimmed_baseline, mask)
    visual_heatmap.save(diff_path)

    is_changed = percentage > threshold_percent

    return {
        "width": width,
        "height": height,
        "total_pixels": total_pixels,
        "changed_pixels": changed_pixels,
        "percentage": round(percentage, 4),
        "is_changed": is_changed,
    }

def build_combined_report_results(scanned_results: dict = None) -> list[dict]:
    """Combine newly scanned results with cached baseline/latest state for all domains in domain.txt."""
    if scanned_results is None:
        scanned_results = {}
        
    target_file = Path("domain.txt")
    all_urls = load_urls_from_file(target_file) if target_file.exists() else []

    # Include any custom scanned URLs that might not be in domain.txt
    for u in scanned_results.keys():
        if u not in all_urls:
            all_urls.append(u)

    combined = []
    for url in all_urls:
        slug = url_to_slug(url)
        baseline_path = BASELINES_DIR / f"{slug}.png"
        latest_path = LATEST_DIR / f"{slug}.png"
        diff_path = DIFFS_DIR / f"{slug}_diff.png"
        baseline_updated = get_baseline_timestamp_display(baseline_path)

        if url in scanned_results:
            res_item = dict(scanned_results[url])
            res_item["baseline_last_updated"] = baseline_updated
            combined.append(res_item)
        else:
            if baseline_path.exists() and latest_path.exists() and diff_path.exists():
                try:
                    diff_res = compute_visual_diff(
                        baseline_path=baseline_path,
                        latest_path=latest_path,
                        diff_path=diff_path,
                        threshold_percent=0.1,
                    )
                    combined.append({
                        "url": url,
                        "status": "Changed" if diff_res["is_changed"] else "Unchanged",
                        "percentage": diff_res["percentage"],
                        "changed_pixels": diff_res["changed_pixels"],
                        "baseline_rel": f"baselines/{slug}.png",
                        "latest_rel": f"latest/{slug}.png",
                        "diff_rel": f"diffs/{slug}_diff.png",
                        "baseline_last_updated": baseline_updated,
                    })
                except Exception as e:
                    combined.append({
                        "url": url,
                        "status": "Failed",
                        "percentage": 0,
                        "changed_pixels": 0,
                        "error": str(e),
                        "baseline_last_updated": baseline_updated,
                    })
            elif baseline_path.exists():
                combined.append({
                    "url": url,
                    "status": "Unchanged",
                    "percentage": 0.0,
                    "changed_pixels": 0,
                    "baseline_rel": f"baselines/{slug}.png",
                    "latest_rel": f"baselines/{slug}.png",
                    "diff_rel": f"baselines/{slug}.png",
                    "baseline_last_updated": baseline_updated,
                })
            else:
                combined.append({
                    "url": url,
                    "status": "Failed",
                    "percentage": 0,
                    "changed_pixels": 0,
                    "error": "No baseline screenshot captured yet.",
                    "baseline_last_updated": baseline_updated,
                })
    return combined

class ScanManager:
    """Thread-safe state manager for web dashboard task execution."""
    def __init__(self):
        self.lock = threading.Lock()
        self.is_running = False
        self.action = None
        self.speed = "low"  # Default low resource usage (1 worker process)
        self.concurrency = 1
        self.total_urls = 0
        self.completed_urls = 0
        self.current_url = ""
        self.status_message = "Idle"
        self.logs = []
        self.error = None

    def start_scan(self, action: str, speed: str = "low", custom_urls: list = None, options: dict = None):
        with self.lock:
            if self.is_running:
                return False, "A task is already in progress."
            self.is_running = True
            self.action = action
            self.speed = speed.lower() if speed else "low"
            # Default is LOW resource usage (1 worker process)
            speed_map = {"low": 1, "medium": 4, "high": 8}
            self.concurrency = speed_map.get(self.speed, 1)
            self.total_urls = 0
            self.completed_urls = 0
            self.current_url = ""
            self.status_message = f"Starting {action} (Speed: {self.speed.upper()}, Workers: {self.concurrency})..."
            self.logs = []
            self.error = None

        if custom_urls is None and options and "custom_urls" in options:
            custom_urls = options["custom_urls"]

        thread = threading.Thread(
            target=self._execute_scan,
            args=(action, custom_urls, options or {}),
            daemon=True
        )
        thread.start()
        return True, "Task started successfully."

    def _execute_scan(self, action: str, custom_urls: list, options: dict):
        try:
            target_file = Path(options.get("target_file", "domain.txt"))
            if custom_urls:
                urls = [normalize_url(u) for u in custom_urls if u.strip()]
            elif options and options.get("custom_urls"):
                urls = [normalize_url(u) for u in options.get("custom_urls") if u.strip()]
            elif target_file.exists():
                urls = load_urls_from_file(target_file)
            else:
                urls = []

            if not urls:
                with self.lock:
                    self.is_running = False
                    self.status_message = "No URLs to scan."
                    self.error = "Target domain list is empty."
                return

            with self.lock:
                self.total_urls = len(urls)
                self.status_message = f"Processing {self.total_urls} URL(s) ({self.concurrency} worker thread(s))..."

            width = options.get("width", 1280)
            height = options.get("height", 800)
            full_page = options.get("full_page", True)
            wait_ms = options.get("wait_ms", 1000)
            wait_selector = options.get("wait_selector", None)
            wait_until = options.get("wait_until", "load")
            timeout = options.get("timeout", 30000)
            masks = options.get("mask", [])
            threshold = options.get("threshold", 0.1)

            if action == "update":
                results_by_url = {}

                def update_worker(url):
                    with self.lock:
                        self.current_url = url
                    slug = url_to_slug(url)
                    baseline_path = BASELINES_DIR / f"{slug}.png"
                    latest_path = LATEST_DIR / f"{slug}.png"
                    diff_path = DIFFS_DIR / f"{slug}_diff.png"
                    try:
                        browser = get_thread_browser()
                        capture_screenshot(
                            url=url,
                            output_path=baseline_path,
                            viewport_width=width,
                            viewport_height=height,
                            full_page=full_page,
                            wait_ms=wait_ms,
                            wait_selector=wait_selector,
                            masks=masks,
                            wait_until=wait_until,
                            timeout=timeout,
                            browser=browser,
                        )
                        msg = f"Baseline saved -> {baseline_path.name}"
                        success = True

                        if latest_path.exists():
                            diff_res = compute_visual_diff(
                                baseline_path=baseline_path,
                                latest_path=latest_path,
                                diff_path=diff_path,
                                threshold_percent=threshold,
                            )
                            res = {
                                "url": url,
                                "status": "Changed" if diff_res["is_changed"] else "Unchanged",
                                "percentage": diff_res["percentage"],
                                "changed_pixels": diff_res["changed_pixels"],
                                "baseline_rel": f"baselines/{slug}.png",
                                "latest_rel": f"latest/{slug}.png",
                                "diff_rel": f"diffs/{slug}_diff.png",
                            }
                        else:
                            res = {
                                "url": url,
                                "status": "Unchanged",
                                "percentage": 0.0,
                                "changed_pixels": 0,
                                "baseline_rel": f"baselines/{slug}.png",
                                "latest_rel": f"baselines/{slug}.png",
                                "diff_rel": f"baselines/{slug}.png",
                            }
                    except Exception as e:
                        msg = f"Failed: {e}"
                        success = False
                        res = {
                            "url": url,
                            "status": "Failed",
                            "percentage": 0,
                            "changed_pixels": 0,
                            "error": str(e)
                        }

                    with self.lock:
                        self.completed_urls += 1
                        self.logs.append({
                            "url": url,
                            "status": "SUCCESS" if success else "FAILED",
                            "msg": f"{url[:40]} | {msg}",
                            "timestamp": time.strftime("%H:%M:%S")
                        })
                    return res

                try:
                    with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                        futures = {executor.submit(update_worker, u): u for u in urls}
                        for f in as_completed(futures):
                            r = f.result()
                            results_by_url[r["url"]] = r
                finally:
                    cleanup_all_browsers()

                combined = build_combined_report_results(results_by_url)
                generate_html_report(combined)

                with self.lock:
                    self.status_message = "Baseline update completed."
                    self.is_running = False

            elif action == "check":
                results_by_url = {}

                def check_worker(url):
                    with self.lock:
                        self.current_url = url
                    slug = url_to_slug(url)
                    baseline_path = BASELINES_DIR / f"{slug}.png"
                    latest_path = LATEST_DIR / f"{slug}.png"
                    diff_path = DIFFS_DIR / f"{slug}_diff.png"

                    if not baseline_path.exists():
                        res = {
                            "url": url,
                            "status": "Failed",
                            "percentage": 0,
                            "changed_pixels": 0,
                            "error": "No baseline screenshot. Run baseline update first."
                        }
                    else:
                        try:
                            browser = get_thread_browser()
                            capture_screenshot(
                                url=url,
                                output_path=latest_path,
                                viewport_width=width,
                                viewport_height=height,
                                full_page=full_page,
                                wait_ms=wait_ms,
                                wait_selector=wait_selector,
                                masks=masks,
                                wait_until=wait_until,
                                timeout=timeout,
                                browser=browser,
                            )
                            diff_res = compute_visual_diff(
                                baseline_path=baseline_path,
                                latest_path=latest_path,
                                diff_path=diff_path,
                                threshold_percent=threshold,
                            )
                            res = {
                                "url": url,
                                "status": "Changed" if diff_res["is_changed"] else "Unchanged",
                                "percentage": diff_res["percentage"],
                                "changed_pixels": diff_res["changed_pixels"],
                                "baseline_rel": f"baselines/{slug}.png",
                                "latest_rel": f"latest/{slug}.png",
                                "diff_rel": f"diffs/{slug}_diff.png",
                            }
                        except Exception as e:
                            res = {
                                "url": url,
                                "status": "Failed",
                                "percentage": 0,
                                "changed_pixels": 0,
                                "error": str(e)
                            }

                    with self.lock:
                        self.completed_urls += 1
                        pct_info = f"{res.get('percentage', 0):.2f}% diff" if res['status'] != 'Failed' else 'Error'
                        self.logs.append({
                            "url": url,
                            "status": res["status"],
                            "msg": f"{url[:40]} | {res['status']} ({pct_info})",
                            "timestamp": time.strftime("%H:%M:%S")
                        })
                    return res

                try:
                    with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                        futures = {executor.submit(check_worker, u): u for u in urls}
                        for f in as_completed(futures):
                            r = f.result()
                            results_by_url[r["url"]] = r
                finally:
                    cleanup_all_browsers()

                combined = build_combined_report_results(results_by_url)
                generate_html_report(combined)

                with self.lock:
                    self.status_message = "Live check completed."
                    self.is_running = False

        except Exception as ex:
            with self.lock:
                self.is_running = False
                self.error = str(ex)
                self.status_message = f"Error: {ex}"

    def get_state(self):
        with self.lock:
            return {
                "is_running": self.is_running,
                "action": self.action,
                "speed": self.speed,
                "concurrency": self.concurrency,
                "total_urls": self.total_urls,
                "completed_urls": self.completed_urls,
                "current_url": self.current_url,
                "percentage": round((self.completed_urls / self.total_urls * 100), 1) if self.total_urls > 0 else 0,
                "status_message": self.status_message,
                "logs": list(self.logs),
                "error": self.error
            }

scan_manager = ScanManager()

class MonitoringRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(CACHE_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/status":
            self.send_json_response(scan_manager.get_state())
        elif self.path == "/api/history":
            self.send_json_response({
                "success": True,
                "reports": get_historical_reports()
            })
        elif self.path == "/" or self.path == "/index.html":
            self.path = "/report.html"
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            data = json.loads(raw)
        except Exception:
            data = {}

        if self.path == "/api/start-scan":
            action = data.get("action", "check")
            speed = data.get("speed", "low")
            custom_urls = data.get("custom_urls", None)
            success, msg = scan_manager.start_scan(action=action, speed=speed, custom_urls=custom_urls, options=data)
            self.send_json_response({"success": success, "message": msg, "state": scan_manager.get_state()})

        elif self.path == "/api/add-domain":
            urls = data.get("urls", [])
            target_file = Path(data.get("target_file", "domain.txt"))
            create_baseline = data.get("create_baseline", False)
            speed = data.get("speed", "low")
            
            added, duplicates = add_domains_to_file(urls, target_file)
            if create_baseline and added:
                scan_manager.start_scan(action="update", speed=speed, custom_urls=added)
            else:
                combined = build_combined_report_results()
                generate_html_report(combined)
            
            self.send_json_response({
                "success": True,
                "added": added,
                "duplicates": duplicates,
                "total": len(load_urls_from_file(target_file))
            })

        elif self.path == "/api/remove-domain":
            urls = data.get("urls", [])
            if "url" in data and data["url"]:
                urls.append(data["url"])
            target_file = Path(data.get("target_file", "domain.txt"))
            
            removed = remove_domains_from_file(urls, target_file)
            combined = build_combined_report_results()
            generate_html_report(combined)
            
            self.send_json_response({
                "success": True,
                "removed": removed,
                "total": len(load_urls_from_file(target_file))
            })

        else:
            self.send_error(404, "Endpoint not found")

    def send_json_response(self, data: dict, status_code: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

def run_server(host: str = "0.0.0.0", port: int = 8000, open_browser: bool = True):
    ensure_dirs()
    if not REPORT_FILE.exists():
        generate_html_report([])

    server_address = (host, port)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(server_address, MonitoringRequestHandler)
    url = f"http://localhost:{port}/report.html"

    print("\n🌐 Visual Change Monitor Web Server is Running!")
    print("=" * 70)
    print(f" 🔗 Local Dashboard URL : http://localhost:{port}/report.html")
    print(f" 🔗 Network Access URL  : http://{host}:{port}/report.html")
    print(f" ⚡ Default Resource    : LOW Resource Usage (1 Worker Process)")
    print("=" * 70)
    print(" Press Ctrl+C to stop the server.\n")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web server...")
    finally:
        httpd.server_close()
        cleanup_all_browsers()

def generate_html_report(results: list[dict]) -> tuple[Path, Path]:
    """Generate a modern interactive HTML report with baseline, live, diff viewers, summary table, and 5-day retention."""
    cleanup_old_reports(max_days=5)
    history_reports = get_historical_reports()
    history_json = json.dumps(history_reports)

    results_json = json.dumps(results)
    timestamp_display = time.strftime('%Y-%m-%d %H:%M:%S')
    today_date_slug = time.strftime('%Y-%m-%d')
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Visual Change Detection Report - {timestamp_display}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-main: #0f172a;
            --bg-card: #1e293b;
            --border-color: #334155;
            --text-primary: #f8fafc;
            --text-muted: #94a3b8;
            --accent-changed: #f43f5e;
            --accent-unchanged: #10b981;
            --accent-failed: #eab308;
            --accent-blue: #38bdf8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        html {{ scroll-behavior: smooth; }}
        body {{
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-main);
            color: var(--text-primary);
            padding: 2rem;
            line-height: 1.5;
        }}
        .header {{
            margin-bottom: 2rem;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 1rem;
        }}
        .header h1 {{ font-size: 1.8rem; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 0.5rem; }}
        .header p {{ color: var(--text-muted); font-size: 0.95rem; margin-top: 0.3rem; }}

        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.25rem;
        }}
        .card .title {{ font-size: 0.85rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600; }}
        .card .value {{ font-size: 2rem; font-weight: 700; margin-top: 0.5rem; }}

        /* Executive Summary Table & Sort Styles */
        .summary-table-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2.5rem;
        }}
        .summary-table-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
            margin-bottom: 1.25rem;
        }}
        .summary-table-card h2 {{
            font-size: 1.2rem;
            font-weight: 700;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        .table-filter-bar {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            flex-wrap: wrap;
        }}
        .filter-chip {{
            padding: 0.35rem 0.85rem;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
            cursor: pointer;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            color: var(--text-muted);
            transition: all 0.2s ease;
            user-select: none;
        }}
        .filter-chip:hover, .filter-chip.active {{
            background: rgba(56, 189, 248, 0.15);
            color: var(--accent-blue);
            border-color: var(--accent-blue);
        }}

        .table-responsive {{
            overflow-x: auto;
        }}
        .summary-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
            text-align: left;
        }}
        .summary-table th {{
            background: rgba(255, 255, 255, 0.03);
            color: var(--text-muted);
            font-weight: 600;
            padding: 0.85rem 1rem;
            border-bottom: 2px solid var(--border-color);
            text-transform: uppercase;
            font-size: 0.75rem;
            letter-spacing: 0.05em;
        }}
        .summary-table th.sortable {{
            cursor: pointer;
            user-select: none;
            transition: background 0.2s ease, color 0.2s ease;
        }}
        .summary-table th.sortable:hover {{
            background: rgba(56, 189, 248, 0.15);
            color: var(--accent-blue);
        }}
        .summary-table th.sortable.active {{
            color: var(--accent-blue);
        }}
        .sort-icon {{
            display: inline-block;
            margin-left: 0.35rem;
            opacity: 0.5;
            font-size: 0.75rem;
        }}
        .summary-table th.sortable.active .sort-icon {{
            opacity: 1;
            color: var(--accent-blue);
        }}

        .summary-table td {{
            padding: 0.85rem 1rem;
            border-bottom: 1px solid var(--border-color);
            vertical-align: middle;
        }}
        .summary-table tr:hover {{
            background: rgba(255, 255, 255, 0.02);
        }}
        .summary-table .btn-jump {{
            display: inline-block;
            padding: 0.3rem 0.75rem;
            background: rgba(56, 189, 248, 0.1);
            color: var(--accent-blue);
            border: 1px solid var(--accent-blue);
            border-radius: 6px;
            text-decoration: none;
            font-size: 0.8rem;
            font-weight: 600;
            transition: all 0.2s ease;
        }}
        .summary-table .btn-jump:hover {{
            background: var(--accent-blue);
            color: #0f172a;
        }}

        .url-block {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            margin-bottom: 2rem;
            overflow: hidden;
        }}
        .url-header {{
            padding: 1rem 1.5rem;
            background: rgba(255,255,255,0.02);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
        }}
        .url-title {{ font-size: 1.1rem; font-weight: 600; word-break: break-all; }}
        .badge {{
            padding: 0.35rem 0.8rem;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 700;
            text-transform: uppercase;
        }}
        .badge-changed {{ background: rgba(244, 63, 94, 0.15); color: var(--accent-changed); border: 1px solid var(--accent-changed); }}
        .badge-unchanged {{ background: rgba(16, 185, 129, 0.15); color: var(--accent-unchanged); border: 1px solid var(--accent-unchanged); }}
        .badge-failed {{ background: rgba(234, 179, 8, 0.15); color: var(--accent-failed); border: 1px solid var(--accent-failed); }}

        .image-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 1.5rem;
            padding: 1.5rem;
        }}
        .img-container {{
            background: #090d16;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 0.75rem;
        }}
        .img-title {{
            font-size: 0.85rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
            color: var(--text-muted);
            text-align: center;
        }}
        .img-container img {{
            width: 100%;
            height: auto;
            border-radius: 4px;
            display: block;
        }}

        /* Task Control Panel & Live Progress Banner */
        .control-panel-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
        }}
        .control-panel-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.25rem;
            flex-wrap: wrap;
            gap: 1rem;
        }}
        .panel-title h2 {{
            font-size: 1.2rem;
            font-weight: 700;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .server-badge {{
            padding: 0.35rem 0.85rem;
            border-radius: 20px;
            font-size: 0.78rem;
            font-weight: 700;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
        }}
        .server-badge.online {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--accent-unchanged);
            border: 1px solid var(--accent-unchanged);
        }}
        .server-badge.offline {{
            background: rgba(148, 163, 184, 0.12);
            color: var(--text-muted);
            border: 1px solid var(--border-color);
        }}
        .control-panel-body {{
            display: flex;
            align-items: center;
            gap: 1.5rem;
            flex-wrap: wrap;
        }}
        .control-group {{
            display: flex;
            flex-direction: column;
            gap: 0.35rem;
        }}
        .control-group label {{
            font-size: 0.78rem;
            font-weight: 700;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .control-select {{
            background: #0f172a;
            color: #f8fafc;
            border: 1px solid var(--border-color);
            padding: 0.6rem 1rem;
            border-radius: 8px;
            font-size: 0.88rem;
            font-weight: 600;
            outline: none;
            cursor: pointer;
            transition: border-color 0.2s ease;
        }}
        .control-select:focus {{
            border-color: var(--accent-blue);
        }}
        .button-group {{
            display: flex;
            gap: 0.85rem;
            flex-wrap: wrap;
            align-items: center;
        }}
        .btn-action {{
            padding: 0.65rem 1.35rem;
            border-radius: 8px;
            font-size: 0.88rem;
            font-weight: 700;
            border: none;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .btn-update-baseline {{
            background: rgba(56, 189, 248, 0.15);
            color: var(--accent-blue);
            border: 1px solid var(--accent-blue);
        }}
        .btn-update-baseline:hover:not(:disabled) {{
            background: var(--accent-blue);
            color: #0f172a;
            box-shadow: 0 4px 14px rgba(56, 189, 248, 0.3);
        }}
        .btn-live-check {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--accent-unchanged);
            border: 1px solid var(--accent-unchanged);
        }}
        .btn-live-check:hover:not(:disabled) {{
            background: var(--accent-unchanged);
            color: #0f172a;
            box-shadow: 0 4px 14px rgba(16, 185, 129, 0.3);
        }}
        .btn-action:disabled {{
            opacity: 0.4;
            cursor: not-allowed;
        }}

        /* Progress Banner */
        .progress-banner {{
            background: #090d16;
            border: 1px solid var(--accent-blue);
            border-radius: 12px;
            padding: 1.25rem 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 8px 30px rgba(56, 189, 248, 0.15);
        }}
        .progress-banner.hidden {{ display: none; }}
        .progress-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.8rem;
            flex-wrap: wrap;
            gap: 0.5rem;
        }}
        .progress-title {{
            font-size: 1rem;
            font-weight: 700;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 0.6rem;
        }}
        .speed-badge {{
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.25rem 0.65rem;
            border-radius: 12px;
            background: rgba(56, 189, 248, 0.2);
            color: var(--accent-blue);
            border: 1px solid rgba(56, 189, 248, 0.4);
        }}
        .progress-bar-wrapper {{
            width: 100%;
            height: 10px;
            background: var(--bg-card);
            border-radius: 5px;
            overflow: hidden;
            margin-bottom: 0.8rem;
        }}
        .progress-bar-fill {{
            height: 100%;
            background: linear-gradient(90deg, var(--accent-blue), #818cf8);
            transition: width 0.3s ease;
        }}
        .progress-details {{
            display: flex;
            justify-content: space-between;
            font-size: 0.85rem;
            color: var(--text-muted);
            flex-wrap: wrap;
            gap: 0.5rem;
        }}
        .progress-log-box {{
            margin-top: 0.8rem;
            max-height: 120px;
            overflow-y: auto;
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 0.6rem 0.8rem;
            font-family: monospace;
            font-size: 0.8rem;
            color: #cbd5e1;
        }}
        .spinner {{
            width: 16px;
            height: 16px;
            border: 2px solid rgba(255,255,255,0.3);
            border-top-color: var(--accent-blue);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            display: inline-block;
        }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}

        /* Single-Domain Action Buttons */
        .url-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.75rem;
        }}
        .url-title-wrapper {{
            display: flex;
            align-items: center;
            gap: 0.85rem;
            flex-wrap: wrap;
        }}
        .domain-action-buttons {{
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
        }}
        .btn-domain-action {{
            padding: 0.35rem 0.75rem;
            border-radius: 6px;
            font-size: 0.78rem;
            font-weight: 700;
            border: none;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
        }}
        .btn-domain-update {{
            background: rgba(56, 189, 248, 0.15);
            color: var(--accent-blue);
            border: 1px solid var(--accent-blue);
        }}
        .btn-domain-update:hover:not(:disabled) {{
            background: var(--accent-blue);
            color: #0f172a;
            box-shadow: 0 2px 8px rgba(56, 189, 248, 0.3);
        }}
        .btn-domain-check {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--accent-unchanged);
            border: 1px solid var(--accent-unchanged);
        }}
        .btn-domain-check:hover:not(:disabled) {{
            background: var(--accent-unchanged);
            color: #0f172a;
            box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);
        }}
        .btn-domain-remove {{
            background: rgba(244, 63, 94, 0.15);
            color: var(--accent-changed);
            border: 1px solid var(--accent-changed);
        }}
        .btn-domain-remove:hover:not(:disabled) {{
            background: var(--accent-changed);
            color: #ffffff;
            box-shadow: 0 2px 8px rgba(244, 63, 94, 0.3);
        }}
        .btn-domain-action:disabled {{
            opacity: 0.4;
            cursor: not-allowed;
        }}

        /* Add Domain Expandable Card Styling */
        .btn-add-domain {{
            background: rgba(168, 85, 247, 0.15);
            color: #c084fc;
            border: 1px solid #c084fc;
        }}
        .btn-add-domain:hover:not(:disabled) {{
            background: #c084fc;
            color: #0f172a;
            box-shadow: 0 4px 14px rgba(192, 132, 252, 0.3);
        }}
        .add-domain-card {{
            background: var(--bg-card);
            border: 1px solid rgba(192, 132, 252, 0.4);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 8px 30px rgba(192, 132, 252, 0.15);
            transition: all 0.3s ease;
        }}
        .add-domain-card.hidden {{ display: none; }}
        .add-domain-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }}
        .add-domain-header h3 {{
            font-size: 1.1rem;
            font-weight: 700;
            color: #f8fafc;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .add-domain-textarea {{
            width: 100%;
            height: 90px;
            background: #090d16;
            color: #f8fafc;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 0.75rem 1rem;
            font-family: monospace;
            font-size: 0.88rem;
            margin-bottom: 1rem;
            outline: none;
            resize: vertical;
            box-sizing: border-box;
        }}
        .add-domain-textarea:focus {{
            border-color: #c084fc;
        }}
        .add-domain-actions {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
        }}
        .checkbox-label {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.85rem;
            color: var(--text-muted);
            cursor: pointer;
        }}

        /* Summary Table Action Cell Buttons */
        .table-action-cell {{
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }}
        .btn-sm-action {{
            padding: 0.25rem 0.55rem;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 700;
            border: none;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
        }}
        .btn-sm-update {{
            background: rgba(56, 189, 248, 0.15);
            color: var(--accent-blue);
            border: 1px solid var(--accent-blue);
        }}
        .btn-sm-update:hover:not(:disabled) {{
            background: var(--accent-blue);
            color: #0f172a;
        }}
        .btn-sm-check {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--accent-unchanged);
            border: 1px solid var(--accent-unchanged);
        }}
        .btn-sm-check:hover:not(:disabled) {{
            background: var(--accent-unchanged);
            color: #0f172a;
        }}
        .btn-sm-remove {{
            background: rgba(244, 63, 94, 0.15);
            color: var(--accent-changed);
            border: 1px solid var(--accent-changed);
        }}
        .btn-sm-remove:hover:not(:disabled) {{
            background: var(--accent-changed);
            color: #ffffff;
        }}
        .btn-sm-action:disabled {{
            opacity: 0.4;
            cursor: not-allowed;
        }}

        /* Scroll to Top Floating Button */
        .scroll-top-btn {{
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            z-index: 1000;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.75rem 1.25rem;
            background: rgba(30, 41, 59, 0.85);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid var(--accent-blue);
            color: var(--accent-blue);
            border-radius: 50px;
            font-size: 0.85rem;
            font-weight: 700;
            cursor: pointer;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
            opacity: 0;
            visibility: hidden;
            transform: translateY(20px);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            user-select: none;
        }}
        .scroll-top-btn.visible {{
            opacity: 1;
            visibility: visible;
            transform: translateY(0);
        }}
        .scroll-top-btn:hover {{
            background: var(--accent-blue);
            color: #0f172a;
            box-shadow: 0 12px 32px rgba(56, 189, 248, 0.4);
            transform: translateY        .scroll-top-btn svg {{
            width: 16px;
            height: 16px;
            fill: currentColor;
            transition: transform 0.2s ease;
        }}
        .scroll-top-btn:hover svg {{
            transform: translateY(-2px);
        }}

        /* Historical Reports Archive Styles */
        .btn-history {{
            background: linear-gradient(135deg, #7c3aed, #5b21b6);
            color: #fff;
            box-shadow: 0 4px 12px rgba(124, 58, 237, 0.35);
        }}
        .btn-history:hover {{
            background: linear-gradient(135deg, #8b5cf6, #6d28d9);
            box-shadow: 0 6px 16px rgba(139, 92, 246, 0.45);
            transform: translateY(-1px);
        }}
        .history-card {{
            background: var(--bg-card);
            border: 1px solid rgba(124, 58, 237, 0.45);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 10px 25px -5px rgba(109, 40, 217, 0.25);
            animation: fadeIn 0.25s ease-out;
        }}
        .history-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 1.25rem;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 0.75rem;
        }}
        .history-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
            gap: 1rem;
        }}
        .history-item-card {{
            background: #090d16;
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 1.1rem;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            gap: 0.85rem;
            transition: all 0.2s ease;
        }}
        .history-item-card:hover {{
            border-color: #8b5cf6;
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(139, 92, 246, 0.25);
        }}
        .history-item-card.is-today {{
            border-color: var(--accent-blue);
            background: rgba(56, 189, 248, 0.05);
        }}
        .history-card-badge {{
            display: inline-block;
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.2rem 0.6rem;
            border-radius: 20px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .badge-today {{
            background: rgba(56, 189, 248, 0.2);
            color: var(--accent-blue);
            border: 1px solid rgba(56, 189, 248, 0.4);
        }}
        .badge-archive {{
            background: rgba(148, 163, 184, 0.15);
            color: var(--text-muted);
            border: 1px solid var(--border-color);
        }}
        .btn-view-report {{
            padding: 0.55rem 1rem;
            background: rgba(56, 189, 248, 0.15);
            border: 1px solid var(--accent-blue);
            color: var(--accent-blue);
            border-radius: 6px;
            font-size: 0.85rem;
            font-weight: 600;
            cursor: pointer;
            text-align: center;
            text-decoration: none;
            transition: all 0.2s;
            display: block;
        }}
        .btn-view-report:hover {{
            background: var(--accent-blue);
            color: #0f172a;
            box-shadow: 0 4px 12px rgba(56, 189, 248, 0.3);
        }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>Visual Change Monitoring Dashboard</h1>
            <p>Generated on {timestamp_display} | Daily Retention Archive: report_{today_date_slug}.html (5-Day Retention)</p>
        </div>
    </div>

    <!-- Executive Task Control Panel -->
    <div class="control-panel-card">
        <div class="control-panel-header">
            <div class="panel-title">
                <h2>⚡ Task Execution & Scan Resource Controller</h2>
            </div>
            <span id="server-status-badge" class="server-badge offline">Checking Server Status...</span>
        </div>
        <div class="control-panel-body">
            <div class="control-group">
                <label for="speedSelect">Scan Speed / Resource Usage:</label>
                <select id="speedSelect" class="control-select">
                    <option value="low" selected>🐢 Low Resource Usage (Default: 1 Worker Thread)</option>
                    <option value="medium">⚡ Medium Speed (4 Worker Threads)</option>
                    <option value="high">🚀 High Speed (8 Worker Threads)</option>
                </select>
            </div>
            <div class="button-group">
                <button id="btn-update-baseline" class="btn-action btn-update-baseline" onclick="triggerTask('update')">
                    📸 Update Baselines
                </button>
                <button id="btn-live-check" class="btn-action btn-live-check" onclick="triggerTask('check')">
                    🔍 Run Live Visual Check
                </button>
                <button id="btn-toggle-add-domain" class="btn-action btn-add-domain" onclick="toggleAddDomainCard()">
                    ➕ Add Domain(s)
                </button>
                <button id="btn-toggle-history" class="btn-action btn-history" onclick="toggleHistoryCard()">
                    📜 View Historical Reports (Last 5 Days)
                </button>
            </div>
        </div>
    </div>

    <!-- Add Domain Expandable Card -->
    <div id="addDomainCard" class="add-domain-card hidden">
        <div class="add-domain-header">
            <h3>➕ Add New Domain(s) for Monitoring</h3>
            <button onclick="toggleAddDomainCard()" style="background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:1.2rem;">✖</button>
        </div>
        <p style="font-size:0.85rem; color:var(--text-muted); margin-bottom:0.75rem;">Enter one or multiple target domain URLs below (e.g. <code>https://example.com</code>, one per line):</p>
        <textarea id="newDomainsTextarea" class="add-domain-textarea" placeholder="https://example.com&#10;https://news.ycombinator.com"></textarea>
        <div class="add-domain-actions">
            <label class="checkbox-label">
                <input type="checkbox" id="autoBaselineCheckbox" checked>
                📸 Automatically capture initial baseline screenshot for newly added domain(s)
            </label>
            <div style="display:flex; gap:0.5rem;">
                <button class="btn-action" style="background:#334155; color:#fff;" onclick="toggleAddDomainCard()">Cancel</button>
                <button id="btn-submit-add-domain" class="btn-action btn-add-domain" onclick="submitAddDomains()">Add to Monitoring</button>
            </div>
        </div>
    </div>

    <!-- Historical Reports Expandable Card -->
    <div id="historyCard" class="history-card hidden">
        <div class="history-header">
            <div>
                <h3 style="display:flex; align-items:center; gap:0.5rem; color:#fff; font-size:1.15rem; font-weight:700;">
                    📜 Historical Reports Archive (5-Day Retention Window)
                </h3>
                <p style="font-size:0.85rem; color:var(--text-muted); margin-top:0.25rem;">
                    The suite automatically retains 1 report per calendar day for up to 5 days. Click <strong>View Report</strong> below to inspect any previous execution report.
                </p>
            </div>
            <button onclick="toggleHistoryCard()" style="background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:1.2rem;">✖</button>
        </div>
        <div id="historyGrid" class="history-grid">
            <!-- Dynamically populated -->
        </div>
    </div>

    <!-- Live Task Progress Banner -->
    <div id="progressContainer" class="progress-banner hidden">
        <div class="progress-header">
            <div class="progress-title">
                <span class="spinner"></span>
                <span id="progressTaskTitle">Executing Task...</span>
            </div>
            <div id="progressSpeedBadge" class="speed-badge">Low Resource (1 Worker)</div>
        </div>
        <div class="progress-bar-wrapper">
            <div id="progressBarFill" class="progress-bar-fill" style="width: 0%;"></div>
        </div>
        <div class="progress-details">
            <span id="progressPercentageText">0% Completed (0/0)</span>
            <span id="progressActiveUrl">Initializing...</span>
        </div>
        <div id="progressLogBox" class="progress-log-box"></div>
    </div>

    <div id="app"></div>

    <!-- Floating Smooth Scroll To Top Button -->
    <button id="scrollToTopBtn" class="scroll-top-btn" onclick="scrollToTop()" title="Scroll back to top">
        <svg viewBox="0 0 24 24"><path d="M12 4l-8 8h5v8h6v-8h5z"/></svg>
        <span>Top</span>
    </button>

    <script>
        let isServerConnected = false;
        let pollingInterval = null;
        let lastKnownState = null;
        const initialHistoryData = {history_json};

        function toggleHistoryCard() {{
            const card = document.getElementById('historyCard');
            if (card) {{
                card.classList.toggle('hidden');
                if (!card.classList.contains('hidden')) {{
                    loadHistoryReports();
                }}
            }}
        }}

        async function loadHistoryReports() {{
            let reports = initialHistoryData || [];
            if (isServerConnected) {{
                try {{
                    const resp = await fetch('/api/history');
                    if (resp.ok) {{
                        const data = await resp.json();
                        if (data.reports) reports = data.reports;
                    }}
                }} catch(e) {{}}
            }}
            renderHistoryGrid(reports);
        }}

        function renderHistoryGrid(reports) {{
            const grid = document.getElementById('historyGrid');
            if (!grid) return;
            if (!reports || reports.length === 0) {{
                grid.innerHTML = '<p style="color:var(--text-muted); font-size:0.9rem;">No historical reports found in retention window.</p>';
                return;
            }}
            grid.innerHTML = reports.map(r => `
                <div class="history-item-card ${{r.is_today ? 'is-today' : ''}}">
                    <div>
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.4rem;">
                            <span style="font-weight:700; font-size:1rem; color:#fff;">🗓️ ${{r.formatted_date}}</span>
                            <span class="history-card-badge ${{r.is_today ? 'badge-today' : 'badge-archive'}}">${{r.is_today ? 'Today' : 'Archive'}}</span>
                        </div>
                        <div style="font-size:0.8rem; color:var(--text-muted); margin-top:0.3rem;">
                            📄 <code>${{r.filename}}</code><br>
                            🕒 Last updated: ${{r.mod_time}} (${{r.size_kb}} KB)
                        </div>
                    </div>
                    <a href="${{r.filename}}" class="btn-view-report" target="_blank">
                        👁️ View Report
                    </a>
                </div>
            `).join('');
        }}

        function toggleAddDomainCard() {{
            const card = document.getElementById('addDomainCard');
            if (card) card.classList.toggle('hidden');
        }}

        async function submitAddDomains() {{
            const textarea = document.getElementById('newDomainsTextarea');
            const autoBaseline = document.getElementById('autoBaselineCheckbox')?.checked || false;
            const speedSelect = document.getElementById('speedSelect');
            const speed = speedSelect ? speedSelect.value : 'low';
            
            if (!textarea || !textarea.value.trim()) {{
                alert('Please enter at least one URL/domain to add.');
                return;
            }}

            if (!isServerConnected) {{
                alert("The backend web server is not currently running.\\n\\nTo add domains from this dashboard, start the server in your terminal:\\n\\npython visual_change_detector.py serve");
                return;
            }}

            const rawUrls = textarea.value.split('\\n').map(s => s.trim()).filter(Boolean);
            const btnSubmit = document.getElementById('btn-submit-add-domain');
            if (btnSubmit) btnSubmit.disabled = true;

            try {{
                const resp = await fetch('/api/add-domain', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ urls: rawUrls, create_baseline: autoBaseline, speed: speed }})
                }});
                const res = await resp.json();
                if (res.success) {{
                    alert(`✅ Added ${{res.added.length}} new domain(s)!` + (res.duplicates.length ? `\\n(Skipped ${{res.duplicates.length}} duplicate(s))` : ''));
                    textarea.value = '';
                    toggleAddDomainCard();
                    if (autoBaseline && res.added.length > 0) {{
                        startPolling();
                    }} else {{
                        window.location.reload();
                    }}
                }} else {{
                    alert(res.message || 'Failed to add domains.');
                }}
            }} catch (err) {{
                alert('Error adding domains: ' + err);
            }} finally {{
                if (btnSubmit) btnSubmit.disabled = false;
            }}
        }}

        async function confirmAndRemoveDomain(url) {{
            if (!confirm(`Are you sure you want to remove '${{url}}' from monitoring?\\n\\nThis will remove it from domain.txt and clean up its baseline and snapshot screenshots.`)) {{
                return;
            }}

            if (!isServerConnected) {{
                alert("The backend web server is not currently running.\\n\\nTo remove domains from this dashboard, start the server in your terminal:\\n\\npython visual_change_detector.py serve");
                return;
            }}

            try {{
                const resp = await fetch('/api/remove-domain', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ url: url }})
                }});
                const res = await resp.json();
                if (res.success) {{
                    alert(`🗑️ Removed '${{url}}' from monitoring.`);
                    window.location.reload();
                }} else {{
                    alert(res.message || 'Failed to remove domain.');
                }}
            }} catch (err) {{
                alert('Error removing domain: ' + err);
            }}
        }}

        async function checkServerStatus() {{
            try {{
                const resp = await fetch('/api/status', {{ cache: 'no-store' }});
                if (resp.ok) {{
                    const state = await resp.json();
                    isServerConnected = true;
                    const badge = document.getElementById('server-status-badge');
                    if (badge) {{
                        badge.className = 'server-badge online';
                        badge.textContent = '🟢 Server Online';
                    }}
                    updateProgressUI(state);
                    return true;
                }}
            }} catch (e) {{
                isServerConnected = false;
                const badge = document.getElementById('server-status-badge');
                if (badge) {{
                    badge.className = 'server-badge offline';
                    badge.textContent = '🟡 Standalone View (Run python visual_change_detector.py serve)';
                }}
            }}
            return false;
        }}

        async function triggerTask(action) {{
            const speedSelect = document.getElementById('speedSelect');
            const speed = speedSelect ? speedSelect.value : 'low';
            const btnUpdate = document.getElementById('btn-update-baseline');
            const btnCheck = document.getElementById('btn-live-check');

            if (!isServerConnected) {{
                alert("The backend web server is not currently running.\\n\\nTo trigger interactive scans from this dashboard, start the server in your terminal:\\n\\npython visual_change_detector.py serve");
                return;
            }}

            if (btnUpdate) btnUpdate.disabled = true;
            if (btnCheck) btnCheck.disabled = true;

            try {{
                const resp = await fetch('/api/start-scan', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ action: action, speed: speed }})
                }});
                const res = await resp.json();
                if (res.success) {{
                    startPolling();
                }} else {{
                    alert(res.message || 'Failed to start task.');
                    if (btnUpdate) btnUpdate.disabled = false;
                    if (btnCheck) btnCheck.disabled = false;
                }}
            }} catch (err) {{
                alert('Error starting task: ' + err);
                if (btnUpdate) btnUpdate.disabled = false;
                if (btnCheck) btnCheck.disabled = false;
            }}
        }}

        async function triggerSingleDomainTask(action, url) {{
            const speedSelect = document.getElementById('speedSelect');
            const speed = speedSelect ? speedSelect.value : 'low';
            const btnUpdate = document.getElementById('btn-update-baseline');
            const btnCheck = document.getElementById('btn-live-check');

            if (!isServerConnected) {{
                alert("The backend web server is not currently running.\\n\\nTo trigger interactive scans from this dashboard, start the server in your terminal:\\n\\npython visual_change_detector.py serve");
                return;
            }}

            if (btnUpdate) btnUpdate.disabled = true;
            if (btnCheck) btnCheck.disabled = true;
            document.querySelectorAll('.btn-domain-action, .btn-sm-action').forEach(b => b.disabled = true);

            try {{
                const resp = await fetch('/api/start-scan', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ action: action, speed: speed, custom_urls: [url] }})
                }});
                const res = await resp.json();
                if (res.success) {{
                    startPolling();
                }} else {{
                    alert(res.message || 'Failed to start task for ' + url);
                    if (btnUpdate) btnUpdate.disabled = false;
                    if (btnCheck) btnCheck.disabled = false;
                    document.querySelectorAll('.btn-domain-action, .btn-sm-action').forEach(b => b.disabled = false);
                }}
            }} catch (err) {{
                alert('Error starting task: ' + err);
                if (btnUpdate) btnUpdate.disabled = false;
                if (btnCheck) btnCheck.disabled = false;
                document.querySelectorAll('.btn-domain-action, .btn-sm-action').forEach(b => b.disabled = false);
            }}
        }}

        function startPolling() {{
            if (pollingInterval) clearInterval(pollingInterval);
            pollingInterval = setInterval(async () => {{
                const connected = await checkServerStatus();
                if (!connected && pollingInterval) {{
                    clearInterval(pollingInterval);
                }}
            }}, 1000);
        }}

        function updateProgressUI(state) {{
            const banner = document.getElementById('progressContainer');
            const fill = document.getElementById('progressBarFill');
            const pctText = document.getElementById('progressPercentageText');
            const activeUrl = document.getElementById('progressActiveUrl');
            const taskTitle = document.getElementById('progressTaskTitle');
            const speedBadge = document.getElementById('progressSpeedBadge');
            const logBox = document.getElementById('progressLogBox');
            const btnUpdate = document.getElementById('btn-update-baseline');
            const btnCheck = document.getElementById('btn-live-check');

            if (!banner) return;

            if (state.is_running) {{
                banner.classList.remove('hidden');
                if (btnUpdate) btnUpdate.disabled = true;
                if (btnCheck) btnCheck.disabled = true;
                document.querySelectorAll('.btn-domain-action, .btn-sm-action').forEach(b => b.disabled = true);

                fill.style.width = state.percentage + '%';
                pctText.textContent = `${{state.percentage}}% Completed (${{state.completed_urls}}/${{state.total_urls}})`;
                activeUrl.textContent = state.current_url ? `Scanning: ${{state.current_url}}` : state.status_message;
                taskTitle.textContent = state.action === 'update' ? '📸 Updating Baselines...' : '🔍 Running Live Visual Check...';
                speedBadge.textContent = `Resource Usage: ${{state.speed.toUpperCase()}} (${{state.concurrency}} worker${{state.concurrency > 1 ? 's' : ''}})`;

                if (state.logs && state.logs.length > 0 && logBox) {{
                    logBox.innerHTML = state.logs.map(l => `<div>[${{l.timestamp}}] ${{l.msg}}</div>`).join('');
                    logBox.scrollTop = logBox.scrollHeight;
                }}
            }} else {{
                if (lastKnownState && lastKnownState.is_running) {{
                    banner.classList.remove('hidden');
                    fill.style.width = '100%';
                    pctText.textContent = '100% Completed';
                    activeUrl.textContent = 'Task completed! Reloading report...';
                    setTimeout(() => {{
                        window.location.reload();
                    }}, 1500);
                }} else {{
                    banner.classList.add('hidden');
                    if (btnUpdate) btnUpdate.disabled = false;
                    if (btnCheck) btnCheck.disabled = false;
                    document.querySelectorAll('.btn-domain-action, .btn-sm-action').forEach(b => b.disabled = false);
                }}
            }}
            lastKnownState = state;
        }}

        checkServerStatus();
        const results = {results_json};
        results.forEach((r, idx) => r.originalIndex = idx + 1);
        
        const total = results.length;
        const changed = results.filter(r => r.status === 'Changed').length;
        const unchanged = results.filter(r => r.status === 'Unchanged').length;
        const failed = results.filter(r => r.status === 'Failed').length;

        const app = document.getElementById('app');

        // Metric Summary Cards
        let html = `
            <div class="summary-cards">
                <div class="card"><div class="title">Total URLs</div><div class="value">${{total}}</div></div>
                <div class="card"><div class="title" style="color:var(--accent-changed)">Changed</div><div class="value" style="color:var(--accent-changed)">${{changed}}</div></div>
                <div class="card"><div class="title" style="color:var(--accent-unchanged)">Unchanged</div><div class="value" style="color:var(--accent-unchanged)">${{unchanged}}</div></div>
                <div class="card"><div class="title" style="color:var(--accent-failed)">Failed</div><div class="value" style="color:var(--accent-failed)">${{failed}}</div></div>
            </div>
        `;

        // Executive Summary Table Card Container
        html += `
            <div class="summary-table-card">
                <div class="summary-table-header">
                    <h2>📋 Executive Results Summary</h2>
                    <div class="table-filter-bar">
                        <span class="filter-chip active" data-filter="ALL" onclick="setFilter('ALL')">All (${{total}})</span>
                        <span class="filter-chip" data-filter="CHANGED" onclick="setFilter('CHANGED')" style="border-color: rgba(244, 63, 94, 0.4);">Changed (${{changed}})</span>
                        <span class="filter-chip" data-filter="UNCHANGED" onclick="setFilter('UNCHANGED')" style="border-color: rgba(16, 185, 129, 0.4);">Unchanged (${{unchanged}})</span>
                        <span class="filter-chip" data-filter="FAILED" onclick="setFilter('FAILED')" style="border-color: rgba(234, 179, 8, 0.4);">Failed (${{failed}})</span>
                    </div>
                </div>
                <div class="table-responsive">
                    <table class="summary-table">
                        <thead>
                            <tr>
                                <th id="th-id" class="sortable" onclick="sortTable('id')"># <span id="icon-id" class="sort-icon">↕</span></th>
                                <th id="th-url" class="sortable" onclick="sortTable('url')">Target URL <span id="icon-url" class="sort-icon">↕</span></th>
                                <th id="th-status" class="sortable" onclick="sortTable('status')">Status <span id="icon-status" class="sort-icon">↕</span></th>
                                <th id="th-percentage" class="sortable" onclick="sortTable('percentage')">Visual Mismatch <span id="icon-percentage" class="sort-icon">↕</span></th>
                                <th id="th-changed_pixels" class="sortable" onclick="sortTable('changed_pixels')">Changed Pixels <span id="icon-changed_pixels" class="sort-icon">↕</span></th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody id="summary-table-body">
                        </tbody>
                    </table>
                </div>
            </div>
        `;

        // Detailed URL Snapshot Blocks Container
        html += `<div id="snapshot-blocks"></div>`;
        app.innerHTML = html;

        // Interactive Table Sorting & Filtering Logic
        let currentSortKey = null;
        let currentSortAsc = true;
        let currentFilter = 'ALL';

        function renderSummaryTable() {{
            let filtered = results;
            if (currentFilter !== 'ALL') {{
                filtered = results.filter(r => r.status.toUpperCase() === currentFilter);
            }}

            let sorted = [...filtered];
            if (currentSortKey) {{
                sorted.sort((a, b) => {{
                    let valA, valB;
                    if (currentSortKey === 'id') {{
                        valA = a.originalIndex;
                        valB = b.originalIndex;
                    }} else if (currentSortKey === 'url') {{
                        valA = a.url.toLowerCase();
                        valB = b.url.toLowerCase();
                    }} else if (currentSortKey === 'status') {{
                        const priority = {{ 'CHANGED': 3, 'FAILED': 2, 'UNCHANGED': 1 }};
                        valA = priority[a.status.toUpperCase()] || 0;
                        valB = priority[b.status.toUpperCase()] || 0;
                    }} else if (currentSortKey === 'percentage') {{
                        valA = a.status === 'Failed' ? -1 : (a.percentage || 0);
                        valB = b.status === 'Failed' ? -1 : (b.percentage || 0);
                    }} else if (currentSortKey === 'changed_pixels') {{
                        valA = a.status === 'Failed' ? -1 : (a.changed_pixels || 0);
                        valB = b.status === 'Failed' ? -1 : (b.changed_pixels || 0);
                    }}

                    if (valA < valB) return currentSortAsc ? -1 : 1;
                    if (valA > valB) return currentSortAsc ? 1 : -1;
                    return 0;
                }});
            }}

            const tbody = document.getElementById('summary-table-body');
            if (!tbody) return;

            if (sorted.length === 0) {{
                tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 2rem;">No matching URLs found.</td></tr>`;
                return;
            }}

            let rowsHtml = '';
            sorted.forEach((res) => {{
                const badgeClass = res.status === 'Changed' ? 'badge-changed' : (res.status === 'Unchanged' ? 'badge-unchanged' : 'badge-failed');
                const pctStr = res.status === 'Failed' ? 'N/A' : `${{res.percentage}}%`;
                const pixelsStr = res.status === 'Failed' ? 'N/A' : (res.changed_pixels !== undefined ? res.changed_pixels.toLocaleString() : 'N/A');

                rowsHtml += `
                    <tr>
                        <td><strong>${{res.originalIndex}}</strong></td>
                        <td style="word-break: break-all;">
                            <a href="${{res.url}}" target="_blank" style="color: #f8fafc; text-decoration: none; font-weight:600;">${{res.url}}</a>
                            <div style="font-size:0.75rem; color:var(--text-muted); margin-top:0.25rem;">
                                📸 Baseline last updated: <strong style="color:#cbd5e1;">${{res.baseline_last_updated || 'Baseline not created'}}</strong>
                            </div>
                        </td>
                        <td><span class="badge ${{badgeClass}}">${{res.status}}</span></td>
                        <td><strong>${{pctStr}}</strong></td>
                        <td>${{pixelsStr}}</td>
                        <td>
                            <div class="table-action-cell">
                                <button class="btn-sm-action btn-sm-update" onclick="triggerSingleDomainTask('update', '${{res.url}}')" title="Update baseline screenshot for ${{res.url}}">📸 Baseline</button>
                                <button class="btn-sm-action btn-sm-check" onclick="triggerSingleDomainTask('check', '${{res.url}}')" title="Run live visual check for ${{res.url}}">🔍 Check</button>
                                <button class="btn-sm-action btn-sm-remove" onclick="confirmAndRemoveDomain('${{res.url}}')" title="Remove ${{res.url}} from monitoring">🗑️ Remove</button>
                                <a href="#url-block-${{res.originalIndex}}" class="btn-jump">View ↓</a>
                            </div>
                        </td>
                    </tr>
                `;
            }});
            tbody.innerHTML = rowsHtml;

            // Update Sort Column Headers UI
            ['id', 'url', 'status', 'percentage', 'changed_pixels'].forEach(key => {{
                const th = document.getElementById(`th-${{key}}`);
                const icon = document.getElementById(`icon-${{key}}`);
                if (th && icon) {{
                    if (currentSortKey === key) {{
                        th.classList.add('active');
                        icon.textContent = currentSortAsc ? '▲' : '▼';
                    }} else {{
                        th.classList.remove('active');
                        icon.textContent = '↕';
                    }}
                }}
            }});
        }}

        function sortTable(key) {{
            if (currentSortKey === key) {{
                currentSortAsc = !currentSortAsc;
            }} else {{
                currentSortKey = key;
                currentSortAsc = (key === 'url' || key === 'id');
            }}
            renderSummaryTable();
        }}

        function setFilter(status) {{
            currentFilter = status;
            document.querySelectorAll('.filter-chip').forEach(btn => {{
                btn.classList.toggle('active', btn.dataset.filter === status);
            }});
            renderSummaryTable();
        }}

        // Render Detailed Snapshot Comparison Blocks
        const snapshotBlocksContainer = document.getElementById('snapshot-blocks');
        let blocksHtml = '';
        results.forEach((res) => {{
            const badgeClass = res.status === 'Changed' ? 'badge-changed' : (res.status === 'Unchanged' ? 'badge-unchanged' : 'badge-failed');
            blocksHtml += `
                <div class="url-block" id="url-block-${{res.originalIndex}}">
                    <div class="url-header">
                        <div class="url-title-wrapper">
                            <div class="url-title">#${{res.originalIndex}}. ${{res.url}}</div>
                            <div class="domain-action-buttons">
                                <button class="btn-domain-action btn-domain-update" onclick="triggerSingleDomainTask('update', '${{res.url}}')" title="Update baseline screenshot for ${{res.url}}">
                                    📸 Update Baseline
                                </button>
                                <button class="btn-domain-action btn-domain-check" onclick="triggerSingleDomainTask('check', '${{res.url}}')" title="Run live visual check for ${{res.url}}">
                                    🔍 Run Live Check
                                </button>
                                <button class="btn-domain-action btn-domain-remove" onclick="confirmAndRemoveDomain('${{res.url}}')" title="Remove ${{res.url}} from monitoring">
                                    🗑️ Remove
                                </button>
                            </div>
                            <div class="baseline-timestamp-tag" title="Exact file modification timestamp of baseline screenshot">
                                📸 Baseline last updated: <strong>${{res.baseline_last_updated || 'Baseline not created'}}</strong>
                            </div>
                        </div>
                        <div class="badge ${{badgeClass}}">${{res.status}} (${{res.percentage}}% Diff)</div>
                    </div>
            `;

            if (res.status !== 'Failed') {{
                blocksHtml += `
                    <div class="image-grid">
                        <div class="img-container">
                            <div class="img-title">Baseline Snapshot</div>
                            <a href="${{res.baseline_rel}}" target="_blank"><img src="${{res.baseline_rel}}" alt="Baseline"></a>
                        </div>
                        <div class="img-container">
                            <div class="img-title">Live Snapshot</div>
                            <a href="${{res.latest_rel}}" target="_blank"><img src="${{res.latest_rel}}" alt="Live"></a>
                        </div>
                        <div class="img-container">
                            <div class="img-title">Visual Diff Heatmap</div>
                            <a href="${{res.diff_rel}}" target="_blank"><img src="${{res.diff_rel}}" alt="Diff"></a>
                        </div>
                    </div>
                `;
            }} else {{
                blocksHtml += `<div style="padding:1.5rem; color:var(--accent-failed)">Error: ${{res.error}}</div>`;
            }}

            blocksHtml += `</div>`;
        }});
        snapshotBlocksContainer.innerHTML = blocksHtml;

        // Initial render of summary table
        renderSummaryTable();

        // Floating Scroll to Top button toggle & action
        const scrollBtn = document.getElementById('scrollToTopBtn');
        window.addEventListener('scroll', () => {{
            if (window.scrollY > 300) {{
                scrollBtn.classList.add('visible');
            }} else {{
                scrollBtn.classList.remove('visible');
            }}
        }});

        function scrollToTop() {{
            window.scrollTo({{
                top: 0,
                behavior: 'smooth'
            }});
        }}
    </script>
</body>
</html>
"""
    daily_report_file = CACHE_DIR / f"report_{today_date_slug}.html"
    daily_report_file.write_text(html_content, encoding="utf-8")
    REPORT_FILE.write_text(html_content, encoding="utf-8")
    return daily_report_file, REPORT_FILE

def main():
    parser = argparse.ArgumentParser(
        description="Visual Change Monitoring Tool for SPAs & Modern Web Apps using Headless Browser screenshots."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Common arguments
    def add_common_args(p):
        g = p.add_mutually_exclusive_group(required=True)
        g.add_argument("--url", action="append", help="Target URL to capture (can be repeated)")
        g.add_argument("--url-file", type=Path, help="File containing list of URLs (one per line)")
        p.add_argument("--width", type=int, default=1280, help="Viewport width (default: 1280)")
        p.add_argument("--height", type=int, default=800, help="Viewport height (default: 800)")
        p.add_argument("--full-page", action="store_true", default=True, help="Capture full scrollable page")
        p.add_argument("--wait-ms", type=int, default=1000, help="Milliseconds to wait after load for JS hydration (default: 1000)")
        p.add_argument("--wait-selector", type=str, help="CSS selector to wait for before taking screenshot")
        p.add_argument("--mask", action="append", help="CSS selector to hide/mask dynamic volatile elements (repeatable)")
        p.add_argument("-c", "--concurrency", type=int, default=4, help="Number of parallel browser worker threads (default: 4)")
        p.add_argument("--wait-until", type=str, choices=["domcontentloaded", "load", "networkidle"], default="load", help="Page navigation wait strategy (default: load)")
        p.add_argument("--timeout", type=int, default=30000, help="Page navigation timeout in milliseconds (default: 30000)")

    # UPDATE subcommand
    upd = subparsers.add_parser("update", help="Capture/refresh baseline screenshots")
    add_common_args(upd)

    # CHECK subcommand
    chk = subparsers.add_parser("check", help="Capture live screenshot and diff against baseline")
    add_common_args(chk)
    chk.add_argument("--threshold", type=float, default=0.1, help="Percentage visual change threshold to trigger alert (default: 0.1)")

    # ADD subcommand
    add_parser = subparsers.add_parser("add", help="Bulk or single add domain(s) to monitoring list file")
    add_group = add_parser.add_mutually_exclusive_group(required=False)
    add_group.add_argument("--url", "-u", action="append", help="Single or multiple target domain(s)/URL(s) to add (repeatable)")
    add_group.add_argument("--import-file", "-f", type=Path, help="Path to a text file containing domains to bulk import (one per line)")
    add_parser.add_argument("positional_urls", nargs="*", help="Domains/URLs passed as positional arguments")
    add_parser.add_argument("--target-file", type=Path, default=Path("domain.txt"), help="Monitoring domain list file to update (default: domain.txt)")
    add_parser.add_argument("--create-baseline", "-b", action="store_true", help="Automatically capture baseline screenshots for newly added domains")
    
    # Common browser rendering options for optional baseline creation
    add_parser.add_argument("--width", type=int, default=1280, help="Viewport width (default: 1280)")
    add_parser.add_argument("--height", type=int, default=800, help="Viewport height (default: 800)")
    add_parser.add_argument("--full-page", action="store_true", default=True, help="Capture full scrollable page")
    add_parser.add_argument("--wait-ms", type=int, default=1000, help="Milliseconds to wait after load for JS hydration (default: 1000)")
    add_parser.add_argument("--wait-selector", type=str, help="CSS selector to wait for before taking screenshot")
    add_parser.add_argument("--mask", action="append", help="CSS selector to hide/mask dynamic volatile elements (repeatable)")
    add_parser.add_argument("-c", "--concurrency", type=int, default=4, help="Number of parallel browser worker threads (default: 4)")
    add_parser.add_argument("--wait-until", type=str, choices=["domcontentloaded", "load", "networkidle"], default="load", help="Page navigation wait strategy (default: load)")
    # REMOVE subcommand
    rem_parser = subparsers.add_parser("remove", help="Remove domain(s) from monitoring list and clean up cache")
    rem_group = rem_parser.add_mutually_exclusive_group(required=False)
    rem_group.add_argument("--url", "-u", action="append", help="Single or multiple domain(s)/URL(s) to remove (repeatable)")
    rem_group.add_argument("--import-file", "-f", type=Path, help="Path to a text file containing domains to remove (one per line)")
    rem_parser.add_argument("positional_urls", nargs="*", help="Domains/URLs passed as positional arguments")
    rem_parser.add_argument("--target-file", type=Path, default=Path("domain.txt"), help="Monitoring domain list file to update (default: domain.txt)")

    # SERVE subcommand
    srv = subparsers.add_parser("serve", help="Start the interactive web dashboard & API server")
    srv.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    srv.add_argument("--host", type=str, default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)")
    srv.add_argument("--no-browser", action="store_true", help="Do not automatically open browser on startup")

    args = parser.parse_args()
    ensure_dirs()

    if args.command == "serve":
        run_server(host=args.host, port=args.port, open_browser=not args.no_browser)
        return

    if args.command == "remove":
        raw_inputs = []
        if args.url:
            raw_inputs.extend(args.url)
        if args.positional_urls:
            raw_inputs.extend(args.positional_urls)
        if args.import_file:
            if not args.import_file.exists():
                print(f"❌ Error: Import file '{args.import_file}' not found.")
                sys.exit(1)
            file_urls = [line.strip() for line in args.import_file.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
            raw_inputs.extend(file_urls)

        if not raw_inputs:
            print("❌ Error: No domains provided to remove. Use --url, --import-file, or pass domains as arguments.")
            sys.exit(1)

        removed = remove_domains_from_file(raw_inputs, args.target_file)
        
        print("\n🗑️ Domain Removal Results:")
        print("=" * 65)
        print(f" Target File   : {args.target_file.resolve()}")
        print(f" Removed       : {len(removed)} domain(s)")
        
        if removed:
            print("\nRemoved Domains & Cache Cleaned:")
            for u in removed:
                print(f"  • {u}")

        total_in_file = len(load_urls_from_file(args.target_file))
        print(f"\n📊 Remaining Domains in '{args.target_file.name}': {total_in_file}")
        
        # Update dashboard HTML report
        combined = build_combined_report_results()
        generate_html_report(combined)
        print(f"✅ Updated monitoring report: {REPORT_FILE}")
        return

    if args.command == "add":
        raw_inputs = []
        if args.url:
            raw_inputs.extend(args.url)
        if args.positional_urls:
            raw_inputs.extend(args.positional_urls)
        if args.import_file:
            if not args.import_file.exists():
                print(f"❌ Error: Import file '{args.import_file}' not found.")
                sys.exit(1)
            file_urls = [line.strip() for line in args.import_file.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
            raw_inputs.extend(file_urls)
            
        if not raw_inputs:
            print("❌ Error: No domains provided. Use --url, --import-file, or pass domains as arguments.")
            sys.exit(1)
            
        added, duplicates = add_domains_to_file(raw_inputs, args.target_file)
        
        print("\n➕ Bulk Domain Import Results:")
        print("=" * 65)
        print(f" Target File   : {args.target_file.resolve()}")
        print(f" Newly Added  : {len(added)} domain(s)")
        print(f" Duplicates   : {len(duplicates)} domain(s) skipped")
        
        if added:
            print("\nNewly Added Domains:")
            for u in added:
                print(f"  • {u}")
                
        if duplicates:
            print("\nSkipped Existing Duplicates:")
            for u in duplicates:
                print(f"  • {u}")
                
        total_in_file = len(load_urls_from_file(args.target_file))
        print(f"\n📊 Total Monitoring Domains in '{args.target_file.name}': {total_in_file}")
        
        if args.create_baseline and added:
            print(f"\n📸 Auto-creating Baselines for {len(added)} newly added domain(s)...")
            print("=" * 65)
            masks = args.mask or []
            concurrency = max(1, args.concurrency)
            
            def update_worker(url):
                slug = url_to_slug(url)
                baseline_path = BASELINES_DIR / f"{slug}.png"
                try:
                    browser = get_thread_browser()
                    capture_screenshot(
                        url=url,
                        output_path=baseline_path,
                        viewport_width=args.width,
                        viewport_height=args.height,
                        full_page=args.full_page,
                        wait_ms=args.wait_ms,
                        wait_selector=args.wait_selector,
                        masks=masks,
                        wait_until=args.wait_until,
                        timeout=args.timeout,
                        browser=browser,
                    )
                    return url, True, f"Baseline saved -> {baseline_path.name}"
                except Exception as e:
                    return url, False, str(e)
                    
            try:
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    future_to_url = {executor.submit(update_worker, url): url for url in added}
                    for future in as_completed(future_to_url):
                        url, success, msg = future.result()
                        status_lbl = "[SUCCESS]" if success else "[FAILED] "
                        print(f"  {status_lbl} {url[:45].ljust(45)} | {msg}")
            finally:
                cleanup_all_browsers()
            print("=" * 65)
            print("✔ Baseline initialization complete!")
        print()
        return

    # Determine URL list for update/check commands
    if getattr(args, "url_file", None):
        urls = [line.strip() for line in args.url_file.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
    else:
        urls = args.url

    masks = args.mask or []
    concurrency = max(1, args.concurrency)

    if args.command == "update":
        print(f"\n📸 Updating Baselines for {len(urls)} URL(s) using {concurrency} parallel worker(s)...")
        print("=" * 80)
        
        def update_worker(url):
            slug = url_to_slug(url)
            baseline_path = BASELINES_DIR / f"{slug}.png"
            try:
                browser = get_thread_browser()
                capture_screenshot(
                    url=url,
                    output_path=baseline_path,
                    viewport_width=args.width,
                    viewport_height=args.height,
                    full_page=args.full_page,
                    wait_ms=args.wait_ms,
                    wait_selector=args.wait_selector,
                    masks=masks,
                    wait_until=args.wait_until,
                    timeout=args.timeout,
                    browser=browser,
                )
                return url, True, f"Baseline saved -> {baseline_path.name}"
            except Exception as e:
                return url, False, str(e)

        try:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                future_to_url = {executor.submit(update_worker, url): url for url in urls}
                for future in as_completed(future_to_url):
                    url, success, msg = future.result()
                    status_lbl = "[SUCCESS]" if success else "[FAILED] "
                    print(f"  {status_lbl} {url[:45].ljust(45)} | {msg}")
        finally:
            cleanup_all_browsers()

        print("=" * 80)
        print("✔ Baselines update complete!\n")

    elif args.command == "check":
        print(f"\n🔍 Checking Visual Changes for {len(urls)} URL(s) using {concurrency} parallel worker(s)...")
        print("=" * 85)
        print(f"{'URL'.ljust(45)} | {'Status'.ljust(10)} | {'Diff %'.ljust(8)} | Details")
        print("-" * 45 + "-+-" + "-" * 10 + "-+-" + "-" * 8 + "-+-" + "-" * 20)

        results_by_url = {}

        def check_worker(url):
            slug = url_to_slug(url)
            baseline_path = BASELINES_DIR / f"{slug}.png"
            latest_path = LATEST_DIR / f"{slug}.png"
            diff_path = DIFFS_DIR / f"{slug}_diff.png"

            if not baseline_path.exists():
                err_msg = "No baseline screenshot. Run 'update' command first."
                return {
                    "url": url,
                    "status": "Failed",
                    "percentage": 0,
                    "changed_pixels": 0,
                    "error": err_msg
                }

            try:
                browser = get_thread_browser()
                capture_screenshot(
                    url=url,
                    output_path=latest_path,
                    viewport_width=args.width,
                    viewport_height=args.height,
                    full_page=args.full_page,
                    wait_ms=args.wait_ms,
                    wait_selector=args.wait_selector,
                    masks=masks,
                    wait_until=args.wait_until,
                    timeout=args.timeout,
                    browser=browser,
                )

                diff_res = compute_visual_diff(
                    baseline_path=baseline_path,
                    latest_path=latest_path,
                    diff_path=diff_path,
                    threshold_percent=args.threshold,
                )

                status = "Changed" if diff_res["is_changed"] else "Unchanged"
                return {
                    "url": url,
                    "status": status,
                    "percentage": diff_res["percentage"],
                    "changed_pixels": diff_res["changed_pixels"],
                    "baseline_rel": f"baselines/{slug}.png",
                    "latest_rel": f"latest/{slug}.png",
                    "diff_rel": f"diffs/{slug}_diff.png",
                }
            except Exception as e:
                return {
                    "url": url,
                    "status": "Failed",
                    "percentage": 0,
                    "changed_pixels": 0,
                    "error": str(e)
                }

        try:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                future_to_url = {executor.submit(check_worker, url): url for url in urls}
                for future in as_completed(future_to_url):
                    res = future.result()
                    url = res["url"]
                    results_by_url[url] = res

                    status = res["status"]
                    if status == "Failed":
                        pct_str = "N/A"
                        details = res.get("error", "Unknown error")
                    else:
                        pct_str = f"{res['percentage']:.2f}%"
                        details = f"{res['changed_pixels']} changed pixels"

                    print(f"{url[:42].ljust(45)} | {status.ljust(10)} | {pct_str.ljust(8)} | {details}")
        finally:
            cleanup_all_browsers()

        # Preserve original URL order in final HTML report
        results = [results_by_url[u] for u in urls if u in results_by_url]

        ts_file, latest_file = generate_html_report(results)
        print("=" * 85)
        print(f"📊 Timestamped Report saved: {ts_file.resolve()}")
        print(f"🔗 Latest Report shortcut:   {latest_file.resolve()}\n")

if __name__ == "__main__":
    main()
