# -*- coding: utf-8 -*-
"""
monitor/auth.py
----------------
Authentication, hCaptcha verification, Rate Limiting, and Audit Logging module for WebGlancer.
Provides session handling, credentials verification, hCaptcha API validation, 5-minute lockout rate-limiting,
and persistent IP/Timestamp login attempt audit logs with automatic 30-day retention pruning.
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path

from monitor.config import CACHE_DIR, ensure_dirs

# Active sessions store: { session_token: expiry_timestamp }
SESSIONS = {}
SESSION_DURATION_SECONDS = 86400 * 7  # 7 Days

# Audit log persistent file path
LOGIN_AUDIT_LOG_FILE = CACHE_DIR / "login_audit.log"

# Rate Limiting Store for Bruteforce Protection
# Schema: { client_ip: { "count": int, "first_failed_time": float, "lockout_until": float } }
FAILED_ATTEMPTS = {}
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 300  # 5 Minutes (300 seconds)


def get_hcaptcha_sitekey() -> str:
    """Get hCaptcha sitekey from environment or default configuration."""
    return os.environ.get("HCAPTCHA_SITEKEY", "56d027fa-471e-4af2-bf82-f8a453acb8e2")


def get_hcaptcha_secret() -> str:
    """Get hCaptcha secret key from environment or default configuration."""
    return os.environ.get("HCAPTCHA_SECRET", "")


def get_admin_username() -> str:
    """Get admin username from environment or default configuration."""
    return os.environ.get("ADMIN_USERNAME", "admin")


def get_admin_password() -> str:
    """Get admin password from environment or default configuration."""
    return os.environ.get("ADMIN_PASSWORD", "admin123")


def get_client_ip(headers, client_address) -> str:
    """Extract client IP address handling X-Forwarded-For / X-Real-IP headers if behind reverse proxies."""
    if headers:
        forwarded_for = headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        real_ip = headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
    if client_address and len(client_address) > 0:
        return str(client_address[0])
    return "127.0.0.1"


def check_rate_limit(client_ip: str) -> tuple[bool, str, int]:
    """
    Check if a client IP is currently rate-limited due to 5 consecutive failed login attempts.
    Returns: (is_locked_out: bool, user_message: str, remaining_seconds: int)
    """
    now = time.time()
    record = FAILED_ATTEMPTS.get(client_ip)

    if not record:
        return False, "", 0

    lockout_until = record.get("lockout_until", 0)
    if now < lockout_until:
        remaining = int(lockout_until - now)
        mins = remaining // 60
        secs = remaining % 60
        time_str = f"{mins} minute(s) and {secs} second(s)" if mins > 0 else f"{secs} second(s)"
        return True, f"Too many failed login attempts. Please wait {time_str} before trying again.", remaining

    # Clear lockout if lockout period has expired
    if lockout_until > 0 and now >= lockout_until:
        FAILED_ATTEMPTS[client_ip] = {"count": 0, "first_failed_time": 0, "lockout_until": 0}

    return False, "", 0


def record_failed_login(client_ip: str) -> bool:
    """
    Record a failed login attempt for a client IP.
    Triggers 5-minute lockout when 5 consecutive failures occur.
    Returns True if the IP is now locked out.
    """
    now = time.time()
    record = FAILED_ATTEMPTS.get(client_ip, {"count": 0, "first_failed_time": now, "lockout_until": 0})

    # Reset count if last failure was over 15 minutes ago
    if now - record.get("first_failed_time", now) > 900 and record.get("lockout_until", 0) == 0:
        record["count"] = 0
        record["first_failed_time"] = now

    record["count"] += 1

    if record["count"] >= MAX_FAILED_ATTEMPTS:
        record["lockout_until"] = now + LOCKOUT_DURATION_SECONDS
        print(f"[AUTH] [LOCKOUT] IP {client_ip} locked out for 5 minutes after {record['count']} failed attempts.", flush=True)

    FAILED_ATTEMPTS[client_ip] = record
    return record["count"] >= MAX_FAILED_ATTEMPTS


def record_successful_login(client_ip: str):
    """Clear failed login attempts counter upon successful login."""
    if client_ip in FAILED_ATTEMPTS:
        del FAILED_ATTEMPTS[client_ip]


def cleanup_old_login_logs(max_days: int = 30):
    """
    Remove log entries from login_audit.log that are older than max_days (default 30 days) to save disk space.
    Log line format: [YYYY-MM-DD HH:MM:SS] [AUTH] ...
    """
    if not LOGIN_AUDIT_LOG_FILE.exists():
        return

    cutoff_datetime = datetime.now() - timedelta(days=max_days)
    pattern = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}\]")
    retained_lines = []

    try:
        content = LOGIN_AUDIT_LOG_FILE.read_text(encoding="utf-8")
        lines = content.splitlines()

        for line in lines:
            match = pattern.match(line.strip())
            if match:
                date_str = match.group(1)
                try:
                    entry_date = datetime.strptime(date_str, "%Y-%m-%d")
                    if entry_date >= cutoff_datetime:
                        retained_lines.append(line)
                except ValueError:
                    retained_lines.append(line)
            else:
                retained_lines.append(line)

        # Write back pruned log entries if any old entries were removed
        if len(retained_lines) < len(lines):
            LOGIN_AUDIT_LOG_FILE.write_text("\n".join(retained_lines) + ("\n" if retained_lines else ""), encoding="utf-8")
    except Exception as e:
        print(f"[AUTH] [ERROR] Failed pruning audit log file: {e}", flush=True)


def log_login_attempt(status: str, username: str, client_ip: str, reason: str):
    """
    Log failed and successful login attempts with timestamp and IP address to:
    1. Standard console output (captured by Docker & Portainer logs).
    2. Persistent file log (.visual_cache/login_audit.log).
    Also triggers automatic 30-day retention pruning.
    """
    ensure_dirs()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_tag = status.upper()
    log_entry = f"[{timestamp}] [AUTH] [{status_tag}] IP: {client_ip} | User: '{username}' | Reason: {reason}"

    # Print to console for Docker stdout logs
    print(log_entry, flush=True)

    # Append to persistent audit log file
    try:
        with open(LOGIN_AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
    except Exception as e:
        print(f"[{timestamp}] [AUTH] [ERROR] Failed writing to audit log file: {e}", flush=True)

    # Auto-prune logs older than 30 days
    cleanup_old_login_logs(max_days=30)


def get_login_audit_logs(limit: int = 100) -> list[str]:
    """Retrieve recent login audit log entries after pruning older entries."""
    cleanup_old_login_logs(max_days=30)
    if not LOGIN_AUDIT_LOG_FILE.exists():
        return []
    try:
        lines = LOGIN_AUDIT_LOG_FILE.read_text(encoding="utf-8").splitlines()
        return lines[-limit:]
    except Exception:
        return []


def verify_hcaptcha_token(token: str, remote_ip: str = None) -> tuple[bool, str]:
    """
    Verify hCaptcha token against hCaptcha verification API.
    Docs: https://docs.hcaptcha.com/
    """
    secret = get_hcaptcha_secret()
    if not secret:
        return True, "hCaptcha secret not configured"

    if not token:
        return False, "hCaptcha token missing. Please complete the captcha challenge."

    url = "https://api.hcaptcha.com/siteverify"
    payload = {
        "secret": secret,
        "response": token
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    encoded_data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            response_text = resp.read().decode("utf-8")
            result = json.loads(response_text)
            if result.get("success") is True:
                return True, "Captcha verified successfully"
            else:
                error_codes = result.get("error-codes", [])
                error_msg = f"hCaptcha validation failed ({', '.join(error_codes)})" if error_codes else "hCaptcha validation failed"
                return False, error_msg
    except Exception as e:
        return False, f"Failed to connect to hCaptcha verification service: {str(e)}"


def purge_expired_sessions_and_attempts():
    """Purge expired session tokens and expired IP lockout records from RAM."""
    now = time.time()
    expired_sessions = [k for k, exp in SESSIONS.items() if now > exp]
    for k in expired_sessions:
        SESSIONS.pop(k, None)

    expired_ips = [
        ip for ip, rec in FAILED_ATTEMPTS.items()
        if rec.get("lockout_until", 0) > 0 and now >= rec.get("lockout_until", 0)
    ]
    for ip in expired_ips:
        FAILED_ATTEMPTS.pop(ip, None)

def create_session() -> str:
    """Generate a new session token and store its expiration time."""
    purge_expired_sessions_and_attempts()
    token = str(uuid.uuid4())
    SESSIONS[token] = time.time() + SESSION_DURATION_SECONDS
    return token


def invalidate_session(token: str):
    """Remove a session token from the active sessions store."""
    if token in SESSIONS:
        del SESSIONS[token]


def is_valid_session(token: str) -> bool:
    """Check if a session token is active and not expired."""
    purge_expired_sessions_and_attempts()
    if not token or token not in SESSIONS:
        return False
    if time.time() > SESSIONS[token]:
        del SESSIONS[token]
        return False
    return True



def get_session_from_headers(headers) -> str:
    """Extract webglancer_session token from HTTP Cookie header."""
    cookie_header = headers.get("Cookie")
    if not cookie_header:
        return ""
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
        if "webglancer_session" in cookie:
            return cookie["webglancer_session"].value
    except Exception:
        pass
    return ""
