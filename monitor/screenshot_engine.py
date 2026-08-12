# -*- coding: utf-8 -*-
"""
monitor/screenshot_engine.py
-----------------------------
Playwright headless Chromium browser lifecycle management and SPA screenshot capture.
"""

import threading
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

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
