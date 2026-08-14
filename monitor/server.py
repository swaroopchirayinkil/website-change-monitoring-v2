# -*- coding: utf-8 -*-
"""
monitor/server.py
-----------------
HTTP Server Handler and REST API routing for WebGlancer with Session & hCaptcha Authentication, Rate Limiting, and Audit Logging.
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
from monitor.scheduler import scheduler_manager
from monitor.auth import (
    get_hcaptcha_sitekey,
    get_admin_username,
    get_admin_password,
    verify_hcaptcha_token,
    create_session,
    invalidate_session,
    is_valid_session,
    get_session_from_headers,
    get_client_ip,
    log_login_attempt,
    get_login_audit_logs,
    check_rate_limit,
    record_failed_login,
    record_successful_login,
)


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
    """Custom HTTP Handler serving Dashboard UI, Authentication, and REST API endpoints."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(CACHE_DIR), **kwargs)

    def end_headers(self):
        # Enable CORS for local API access
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Cookie")
        self.send_header("Access-Control-Allow-Credentials", "true")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        # 1. PUBLIC ENDPOINTS (No authentication required)
        if self.path in ["/login", "/login.html"]:
            login_path = WEB_DIR / "login.html"
            if login_path.exists():
                content = login_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        if self.path == "/api/hcaptcha-config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"sitekey": get_hcaptcha_sitekey()}).encode("utf-8"))
            return

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

        # 2. SESSION AUTHENTICATION CHECK
        session_token = get_session_from_headers(self.headers)
        if not is_valid_session(session_token):
            if self.path.startswith("/api/"):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Unauthorized", "message": "Authentication required. Please login."}).encode("utf-8"))
                return
            else:
                # Redirect unauthenticated HTML / asset GET requests to login page
                self.send_response(302)
                self.send_header("Location", "/login.html")
                self.end_headers()
                return

        # 3. PROTECTED ENDPOINTS (Valid Session Verified)
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

        # REST API: Login Audit Logs Endpoint
        if self.path == "/api/login-logs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            logs = get_login_audit_logs(limit=100)
            self.wfile.write(json.dumps({"logs": logs}).encode("utf-8"))
            return

        # REST API: Schedule GET Endpoint
        if self.path == "/api/schedule":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status = scheduler_manager.get_status()
            self.wfile.write(json.dumps(status).encode("utf-8"))
            return

        return super().do_GET()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_data_raw = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            post_data = json.loads(post_data_raw)
        except Exception:
            post_data = {}

        # 1. PUBLIC API: LOGIN ENDPOINT WITH HCAPTCHA VERIFICATION, RATE LIMITING & AUDIT LOGGING
        if self.path == "/api/login":
            username = post_data.get("username", "").strip()
            password = post_data.get("password", "")
            hcaptcha_token = post_data.get("hcaptcha_response", "")
            client_ip = get_client_ip(self.headers, self.client_address)

            # Check if client IP is currently rate-limited (5-minute lockout)
            is_locked, lock_msg, remaining_sec = check_rate_limit(client_ip)
            if is_locked:
                log_login_attempt("RATE_LIMITED", username or "unknown", client_ip, lock_msg)
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", str(remaining_sec))
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": lock_msg, "retry_after": remaining_sec}).encode("utf-8"))
                return

            # Verify admin credentials
            expected_user = get_admin_username()
            expected_pass = get_admin_password()

            if username != expected_user or password != expected_pass:
                record_failed_login(client_ip)
                is_now_locked, lock_reason_msg, _ = check_rate_limit(client_ip)
                err_msg = lock_reason_msg if is_now_locked else "Invalid username or password."

                log_login_attempt("FAILED", username or "unknown", client_ip, "Invalid username or password")
                self.send_response(429 if is_now_locked else 401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": err_msg}).encode("utf-8"))
                return

            # Verify hCaptcha token
            hcaptcha_ok, hcaptcha_msg = verify_hcaptcha_token(hcaptcha_token, remote_ip=client_ip)

            if not hcaptcha_ok:
                record_failed_login(client_ip)
                is_now_locked, lock_reason_msg, _ = check_rate_limit(client_ip)
                err_msg = lock_reason_msg if is_now_locked else hcaptcha_msg

                log_login_attempt("FAILED", username, client_ip, f"hCaptcha validation failed: {hcaptcha_msg}")
                self.send_response(429 if is_now_locked else 400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": err_msg}).encode("utf-8"))
                return

            # Successful login: reset failed login attempts counter and issue session
            record_successful_login(client_ip)
            session_token = create_session()
            log_login_attempt("SUCCESS", username, client_ip, "Login successful")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", f"webglancer_session={session_token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "message": "Login successful!"}).encode("utf-8"))
            return

        # 2. PUBLIC API: LOGOUT ENDPOINT
        if self.path == "/api/logout":
            client_ip = get_client_ip(self.headers, self.client_address)
            session_token = get_session_from_headers(self.headers)
            invalidate_session(session_token)
            log_login_attempt("LOGOUT", get_admin_username(), client_ip, "User logged out")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", "webglancer_session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "message": "Logged out."}).encode("utf-8"))
            return

        # 3. SESSION AUTHENTICATION CHECK FOR PROTECTED POST ENDPOINTS
        session_token = get_session_from_headers(self.headers)
        if not is_valid_session(session_token):
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Unauthorized", "message": "Authentication required."}).encode("utf-8"))
            return

        # REST API: Schedule POST Endpoint
        if self.path == "/api/schedule":
            scheduler_manager.save_config(post_data)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            status = scheduler_manager.get_status()
            self.wfile.write(json.dumps({"success": True, "schedule": status}).encode("utf-8"))
            return

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

    scheduler_manager.start(report_generator=generate_html_report)

    class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True

    server_address = (host, port)
    httpd = ThreadedHTTPServer(server_address, MonitoringRequestHandler)

    url = f"http://localhost:{port}/report.html"
    print("\n" + "="*70)
    print(" 🚀 WEBGLANCER REST API SERVER STARTED")
    print("="*70)
    print(f" 🌐 Web Dashboard URL:  {url}")
    print(f" 🔑 Login Page URL:    http://localhost:{port}/login.html")
    print(f" 🛡️  hCaptcha Security: Active")
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
