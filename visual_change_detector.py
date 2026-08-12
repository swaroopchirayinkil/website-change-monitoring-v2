#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
visual_change_detector.py
-------------------------
Lightweight CLI dispatcher for the Visual Change Monitoring Suite.
Leverages the modular `monitor` package for high-speed Playwright browser rendering,
Pillow visual diffing, REST API server handling, and web dashboard generation.
"""

import argparse
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from monitor.config import ensure_dirs, DEFAULT_DOMAIN_FILE, BASELINES_DIR, LATEST_DIR, DIFFS_DIR, REPORT_FILE
from monitor.domain_manager import (
    load_urls_from_file,
    normalize_url,
    url_to_slug,
    add_domains_to_file,
    remove_domains_from_file,
)
from monitor.screenshot_engine import (
    get_thread_browser,
    cleanup_all_browsers,
    capture_screenshot,
)
from monitor.diff_engine import compute_visual_diff
from monitor.retention_manager import cleanup_old_reports
from monitor.scan_manager import build_combined_report_results
from monitor.server import run_server, generate_html_report


def main():
    parser = argparse.ArgumentParser(
        description="Visual SPA Change Detector using Playwright & Pixel Diffing."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Subcommand: serve
    serve_parser = subparsers.add_parser("serve", help="Launch Web Dashboard Server & REST API")
    serve_parser.add_argument("--port", type=int, default=8000, help="HTTP port (default: 8000)")
    serve_parser.add_argument("--host", type=str, default="0.0.0.0", help="Host IP address (default: 0.0.0.0)")
    serve_parser.add_argument("--no-browser", action="store_true", help="Disable auto opening browser")

    # Subcommand: update
    update_parser = subparsers.add_parser("update", help="Capture baseline screenshots")
    update_parser.add_argument("--url", action="append", help="Target URL (repeatable)")
    update_parser.add_argument("--url-file", type=str, help="Text file containing target URLs")
    update_parser.add_argument("-c", "--concurrency", type=int, default=4, help="Parallel worker threads (default: 4)")
    update_parser.add_argument("--wait-until", type=str, default="load", choices=["load", "domcontentloaded", "networkidle"])
    update_parser.add_argument("--timeout", type=int, default=30000, help="Navigation timeout in ms")
    update_parser.add_argument("--width", type=int, default=1280, help="Viewport width")
    update_parser.add_argument("--height", type=int, default=800, help="Viewport height")
    update_parser.add_argument("--no-full-page", action="store_false", dest="full_page")
    update_parser.add_argument("--wait-ms", type=int, default=1000, help="Hydration wait ms")
    update_parser.add_argument("--wait-selector", type=str, help="CSS selector to wait for")
    update_parser.add_argument("--mask", action="append", help="CSS selector to hide (repeatable)")

    # Subcommand: check
    check_parser = subparsers.add_parser("check", help="Capture live screenshots and compute visual diffs")
    check_parser.add_argument("--url", action="append", help="Target URL (repeatable)")
    check_parser.add_argument("--url-file", type=str, help="Text file containing target URLs")
    check_parser.add_argument("-c", "--concurrency", type=int, default=4, help="Parallel worker threads (default: 4)")
    check_parser.add_argument("--wait-until", type=str, default="load", choices=["load", "domcontentloaded", "networkidle"])
    check_parser.add_argument("--timeout", type=int, default=30000, help="Navigation timeout in ms")
    check_parser.add_argument("--width", type=int, default=1280, help="Viewport width")
    check_parser.add_argument("--height", type=int, default=800, help="Viewport height")
    check_parser.add_argument("--no-full-page", action="store_false", dest="full_page")
    check_parser.add_argument("--wait-ms", type=int, default=1000, help="Hydration wait ms")
    check_parser.add_argument("--wait-selector", type=str, help="CSS selector to wait for")
    check_parser.add_argument("--mask", action="append", help="CSS selector to hide (repeatable)")
    check_parser.add_argument("--threshold", type=float, default=0.1, help="Diff percentage threshold")

    # Subcommand: add
    add_parser = subparsers.add_parser("add", help="Add domain(s) to monitoring list")
    add_parser.add_argument("positional_urls", nargs="*", help="Domain(s) to add")
    add_parser.add_argument("--url", "-u", action="append", help="Domain URL to add (repeatable)")
    add_parser.add_argument("--import-file", "-f", type=str, help="Import domains from text file")
    add_parser.add_argument("--target-file", type=str, default="domain.txt", help="Domain list file")
    add_parser.add_argument("--create-baseline", "-b", action="store_true", help="Auto-capture baseline screenshots")

    # Subcommand: remove
    remove_parser = subparsers.add_parser("remove", help="Remove domain(s) from monitoring list")
    remove_parser.add_argument("positional_urls", nargs="*", help="Domain(s) to remove")
    remove_parser.add_argument("--url", "-u", action="append", help="Domain URL to remove (repeatable)")
    remove_parser.add_argument("--import-file", "-f", type=str, help="Import domains from text file")
    remove_parser.add_argument("--target-file", type=str, default="domain.txt", help="Domain list file")

    args = parser.parse_args()

    if not args.command or args.command == "serve":
        port = getattr(args, "port", 8000)
        host = getattr(args, "host", "0.0.0.0")
        no_browser = getattr(args, "no_browser", False)
        run_server(host=host, port=port, open_browser=not no_browser)
        return

    ensure_dirs()

    if args.command in ["add", "remove"]:
        target_file = Path(args.target_file)
        urls_to_process = []
        if getattr(args, "url", None):
            urls_to_process.extend(args.url)
        if getattr(args, "positional_urls", None):
            urls_to_process.extend(args.positional_urls)
        if getattr(args, "import_file", None):
            imp_path = Path(args.import_file)
            if imp_path.exists():
                urls_to_process.extend(imp_path.read_text(encoding="utf-8").splitlines())

        if not urls_to_process:
            print("❌ Error: No domain(s) specified.")
            sys.exit(1)

        if args.command == "add":
            added, duplicates = add_domains_to_file(urls_to_process, target_file)
            print(f"✅ Added {len(added)} new domain(s) to '{target_file.name}'.")
            if duplicates:
                print(f"ℹ️ Skipped {len(duplicates)} duplicate(s).")
            if args.create_baseline and added:
                print("\n📸 Capturing initial baseline screenshots for new domains...")
                _run_cli_scan("update", added, args)
            else:
                combined = build_combined_report_results()
                generate_html_report(combined, REPORT_FILE)
        elif args.command == "remove":
            removed = remove_domains_from_file(urls_to_process, target_file)
            print(f"🗑️ Removed {len(removed)} domain(s) from '{target_file.name}' and purged cache files.")
            combined = build_combined_report_results()
            generate_html_report(combined, REPORT_FILE)
        return

    # CLI update or check
    urls = []
    if getattr(args, "url", None):
        urls.extend([normalize_url(u) for u in args.url if u.strip()])
    elif getattr(args, "url_file", None):
        urls_file_path = Path(args.url_file)
        if urls_file_path.exists():
            urls.extend(load_urls_from_file(urls_file_path))
    else:
        urls.extend(load_urls_from_file(DEFAULT_DOMAIN_FILE))

    if not urls:
        print("❌ Error: No target URLs found to scan.")
        sys.exit(1)

    _run_cli_scan(args.command, urls, args)


def _run_cli_scan(action: str, urls: list[str], args):
    """Internal runner for CLI update and check scans."""
    concurrency = getattr(args, "concurrency", 4)
    width = getattr(args, "width", 1280)
    height = getattr(args, "height", 800)
    full_page = getattr(args, "full_page", True)
    wait_ms = getattr(args, "wait_ms", 1000)
    wait_selector = getattr(args, "wait_selector", None)
    wait_until = getattr(args, "wait_until", "load")
    timeout = getattr(args, "timeout", 30000)
    masks = getattr(args, "mask", None) or []
    threshold = getattr(args, "threshold", 0.1)

    print(f"\n🚀 Running '{action.upper()}' scan for {len(urls)} URL(s) with {concurrency} worker thread(s)...")
    results_by_url = {}

    def worker(url):
        slug = url_to_slug(url)
        baseline_path = BASELINES_DIR / f"{slug}.png"
        latest_path = LATEST_DIR / f"{slug}.png"
        diff_path = DIFFS_DIR / f"{slug}_diff.png"

        browser = get_thread_browser()

        if action == "update":
            try:
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
                print(f"  [Baseline Created] -> {url}")
                if latest_path.exists():
                    diff_res = compute_visual_diff(baseline_path, latest_path, diff_path, threshold)
                    return {
                        "url": url,
                        "status": "Changed" if diff_res["is_changed"] else "Unchanged",
                        "percentage": diff_res["percentage"],
                        "changed_pixels": diff_res["changed_pixels"],
                        "baseline_rel": f"baselines/{slug}.png",
                        "latest_rel": f"latest/{slug}.png",
                        "diff_rel": f"diffs/{slug}_diff.png",
                    }
                return {
                    "url": url,
                    "status": "Unchanged",
                    "percentage": 0.0,
                    "changed_pixels": 0,
                    "baseline_rel": f"baselines/{slug}.png",
                    "latest_rel": f"baselines/{slug}.png",
                    "diff_rel": f"baselines/{slug}.png",
                }
            except Exception as e:
                print(f"  [Baseline Failed] -> {url}: {e}")
                return {"url": url, "status": "Failed", "percentage": 0, "changed_pixels": 0, "error": str(e)}

        elif action == "check":
            if not baseline_path.exists():
                print(f"  [Skipped - No Baseline] -> {url}")
                return {"url": url, "status": "Failed", "percentage": 0, "changed_pixels": 0, "error": "No baseline screenshot."}

            try:
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
                diff_res = compute_visual_diff(baseline_path, latest_path, diff_path, threshold)
                st = "Changed" if diff_res["is_changed"] else "Unchanged"
                print(f"  [{st}] -> {url} (Diff: {diff_res['percentage']:.2f}%)")
                return {
                    "url": url,
                    "status": st,
                    "percentage": diff_res["percentage"],
                    "changed_pixels": diff_res["changed_pixels"],
                    "baseline_rel": f"baselines/{slug}.png",
                    "latest_rel": f"latest/{slug}.png",
                    "diff_rel": f"diffs/{slug}_diff.png",
                }
            except Exception as e:
                print(f"  [Check Failed] -> {url}: {e}")
                return {"url": url, "status": "Failed", "percentage": 0, "changed_pixels": 0, "error": str(e)}

    try:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(worker, u): u for u in urls}
            for f in as_completed(futures):
                r = f.result()
                results_by_url[r["url"]] = r
    finally:
        cleanup_all_browsers()

    combined = build_combined_report_results(results_by_url)
    generate_html_report(combined, REPORT_FILE)
    print(f"\n✨ Scan completed. Report generated at: {REPORT_FILE.resolve()}")


if __name__ == "__main__":
    main()
