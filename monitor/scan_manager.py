# -*- coding: utf-8 -*-
"""
monitor/scan_manager.py
------------------------
Thread-safe task execution state manager and background worker pool coordinator.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from monitor.config import BASELINES_DIR, LATEST_DIR, DIFFS_DIR, DEFAULT_DOMAIN_FILE
from monitor.domain_manager import load_urls_from_file, normalize_url, url_to_slug
from monitor.screenshot_engine import get_thread_browser, cleanup_all_browsers, capture_screenshot
from monitor.diff_engine import compute_visual_diff
from monitor.retention_manager import get_baseline_timestamp_display

def build_combined_report_results(scanned_results: dict = None) -> list[dict]:
    """Combine newly scanned results with cached baseline/latest state for all domains in domain.txt."""
    if scanned_results is None:
        scanned_results = {}
        
    target_file = DEFAULT_DOMAIN_FILE
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

    def start_scan(self, action: str, speed: str = "low", custom_urls: list = None, options: dict = None, report_generator=None):
        with self.lock:
            if self.is_running:
                return False, "A task is already in progress."
            self.is_running = True
            self.action = action
            self.speed = speed.lower() if speed else "low"
            # Default is LOW resource usage (1 worker process)
            speed_map = {"low": 1, "medium": 4, "high": 4}
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
            args=(action, custom_urls, options or {}, report_generator),
            daemon=True
        )
        thread.start()
        return True, "Task started successfully."

    def _execute_scan(self, action: str, custom_urls: list, options: dict, report_generator=None):
        try:
            target_file = Path(options.get("target_file", DEFAULT_DOMAIN_FILE))
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
                if report_generator:
                    report_generator(combined)

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
                if report_generator:
                    report_generator(combined)

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
