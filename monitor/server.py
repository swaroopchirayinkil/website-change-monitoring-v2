# -*- coding: utf-8 -*-
"""
monitor/server.py
-----------------
HTTP Server Handler and REST API routing for WebGlancer.
"""

import http.server
import json
import socketserver
import webbrowser
from datetime import datetime, date
from pathlib import Path

from monitor.config import CACHE_DIR, REPORT_FILE, DEFAULT_DOMAIN_FILE, WEB_DIR, ensure_dirs
from monitor.domain_manager import url_to_slug, add_domains_to_file, remove_domains_from_file
from monitor.scan_manager import scan_manager, build_combined_report_results
from monitor.retention_manager import cleanup_old_reports, get_historical_reports

def generate_html_report(results: list[dict], output_path: Path = REPORT_FILE):
    """Generate interactive HTML report dashboard using external HTML/CSS/JS template files."""
    ensure_dirs()

    total = len(results)
    changed = sum(1 for r in results if r.get("status") == "Changed")
    unchanged = sum(1 for r in results if r.get("status") == "Unchanged")
    failed = sum(1 for r in results if r.get("status") == "Failed")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Add indices and slugs for client-side sorting and anchor linking
    processed_results = []
    for idx, r in enumerate(results, start=1):
        item = dict(r)
        item["_originalIndex"] = idx
        item["_slug"] = url_to_slug(r["url"])
        processed_results.append(item)

    report_json_str = json.dumps(processed_results, indent=2)
    historical_reports = get_historical_reports()
    history_json_str = json.dumps(historical_reports, indent=2)

    template_file = WEB_DIR / "index.html"
    if template_file.exists():
        template = template_file.read_text(encoding="utf-8")
        html_content = template.format(
            now_str=now_str,
            total=total,
            changed=changed,
            unchanged=unchanged,
            failed=failed,
            report_data_json=report_json_str,
            history_data_json=history_json_str
        )
    else:
        # Fallback inline generation if template file missing
        html_content = f"<!DOCTYPE html><html><body><h1>Report Generated at {now_str}</h1></body></html>"

    output_path.write_text(html_content, encoding="utf-8")

    # Maintain 5-day daily report retention window
    cleanup_old_reports(max_days=5)
    today_str = date.today().strftime("%Y-%m-%d")
    daily_archived_report = CACHE_DIR / f"report_{today_str}.html"
    daily_archived_report.write_text(html_content, encoding="utf-8")


class MonitoringRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom HTTP Handler serving Dashboard UI and REST API endpoints."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(CACHE_DIR), **kwargs)

    def end_headers(self):
        # Enable CORS for local API access
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        # Serve static frontend web assets from monitor/web/
        if self.path in ["/styles.css", "/app.js"]:
            asset_path = WEB_DIR / self.path.lstrip("/")
            if asset_path.exists():
                content_type = "text/css" if self.path.endswith(".css") else "application/javascript"
                content = asset_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        # Redirect root paths to report dashboard
        if self.path in ["/", "/index.html"]:
            self.send_response(302)
            self.send_header("Location", "/report.html")
            self.end_headers()
            return

        # REST API: Status Endpoint
        if self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            state = scan_manager.get_state()
            self.wfile.write(json.dumps(state).encode("utf-8"))
            return

        # REST API: History Endpoint
        if self.path == "/api/history":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            reports = get_historical_reports()
            self.wfile.write(json.dumps({"reports": reports}).encode("utf-8"))
            return

        return super().do_GET()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data_raw = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            post_data = json.loads(post_data_raw)
        except Exception:
            post_data = {}

        # REST API: Start Scan Trigger
        if self.path == "/api/start-scan":
            action = post_data.get("action", "check")
            speed = post_data.get("speed", "low")
            custom_urls = post_data.get("custom_urls", None)

            def report_gen_wrapper(results):
                generate_html_report(results, REPORT_FILE)

            success, msg = scan_manager.start_scan(
                action=action,
                speed=speed,
                custom_urls=custom_urls,
                report_generator=report_gen_wrapper
            )

            self.send_response(200 if success else 400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"success": success, "message": msg}).encode("utf-8"))
            return

        # REST API: Add Domain Endpoint
        if self.path == "/api/add-domain":
            urls = post_data.get("urls", [])
            create_baseline = post_data.get("create_baseline", False)
            speed = post_data.get("speed", "low")

            if not urls:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": "No URLs provided"}).encode("utf-8"))
                return

            target_file = DEFAULT_DOMAIN_FILE
            added, duplicates = add_domains_to_file(urls, target_file)

            if create_baseline and added:
                def report_gen_wrapper(results):
                    generate_html_report(results, REPORT_FILE)

                scan_manager.start_scan(
                    action="update",
                    speed=speed,
                    custom_urls=added,
                    report_generator=report_gen_wrapper
                )
            else:
                combined = build_combined_report_results()
                generate_html_report(combined, REPORT_FILE)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "added": added,
                "duplicates": duplicates,
                "message": f"Successfully added {len(added)} domain(s)."
            }).encode("utf-8"))
            return

        # REST API: Remove Domain Endpoint
        if self.path == "/api/remove-domain":
            url = post_data.get("url", "")
            if not url:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": "No URL provided"}).encode("utf-8"))
                return

            target_file = DEFAULT_DOMAIN_FILE
            removed = remove_domains_from_file([url], target_file)

            combined = build_combined_report_results()
            generate_html_report(combined, REPORT_FILE)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "removed": removed,
                "message": f"Successfully removed {url}."
            }).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()


def run_server(host: str = "0.0.0.0", port: int = 8000, open_browser: bool = True):
    """Start the interactive Web Dashboard & REST API server."""
    ensure_dirs()
    if not REPORT_FILE.exists():
        combined = build_combined_report_results()
        generate_html_report(combined, REPORT_FILE)

    class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True

    server_address = (host, port)
    httpd = ThreadedHTTPServer(server_address, MonitoringRequestHandler)

    url = f"http://localhost:{port}/report.html"
    print("\n" + "="*70)
    print(" 🚀 WEBGLANCER REST API SERVER STARTED")
    print("="*70)
    print(f" 🌐 Web Dashboard URL:  {url}")
    print(f" 📡 Local Server Address: http://{host}:{port}")
    print(" ⚡ High-Speed Concurrency Controls: Active")
    print(" Press Ctrl+C to stop the server.")
    print("="*70 + "\n")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[Shutting Down] Stopping Web Dashboard Server...")
        httpd.shutdown()
        httpd.server_close()
