# Project State

**Branch:** `final-testing` (production-deployed branch)  
**Last audited:** 2026-10-29

## Current Status
The application is **functional and actively deployed** via Portainer/Docker.
Core monitoring workflow (screenshot → diff → report) is stable.
Recent additions include structured 60-day daily JSON history persistence, on-demand periodic visual change reports (Weekly/Monthly/Custom) formatted as a day-by-day percentage change matrix, CSV/JSON report exports, and unified `button-rh` accordion card controls.

## Active Branches

| Branch | Purpose |
|---|---|
| `main` | Stable merged release |
| `final-testing` | Production branch (HEAD — includes Portainer volume fix & Periodic Reports) |
| `portainer-test` | Same commit as `final-testing` |
| `portainer-trim-memory` | Memory optimization experiments (remote only) |
| `coolify-test` | Coolify deployment experiments (remote only) |

## Known Bugs

### B1 — `_thread_browsers` List Accumulates Stale Entries
**File:** `monitor/screenshot_engine.py`  
**Symptom:** After multiple scan cycles, `_thread_browsers` contains closed browser references. `cleanup_all_browsers()` iterates and calls `.close()` on already-closed browsers (silently caught), but the list grows unboundedly across scan cycles if worker threads are reused.  
**Root cause:** `get_thread_browser()` checks `hasattr(_thread_local, "playwright")` but never re-checks whether the stored browser is still alive. After `cleanup_all_browsers()` clears `_thread_browsers`, the thread-local attributes still exist, so subsequent scans get stale references.  
**Impact:** Medium — silent errors in cleanup; potential for leaked Chromium processes over time.

### B2 — Race Condition on `ScanManager.is_running` in Scheduler [RESOLVED]
**File:** `monitor/scheduler.py`  
**Resolution:** Resolved — scheduler now acquires `scan_manager.lock` before reading `is_running`.

### B3 — Partial Report Write on Failure
**File:** `monitor/server.py` — `generate_html_report()`  
**Symptom:** If template rendering raises an exception (e.g., unescaped `{` in report data), `report.html` may be left in a partial/corrupt state or not updated.  
**Impact:** Low — the `str.format()` call raises before writing; existing `report.html` is preserved.

### B4 — hCaptcha Sitekey Hard-coded in `login.html`
**File:** `monitor/web/login.html` line 209  
**Symptom:** The DOM has a hardcoded default sitekey. The JS fetch to `/api/hcaptcha-config` only replaces it if the returned key differs from the hardcoded one.  
**Impact:** Low — only affects custom sitekey configuration visibility.

## Security Concerns

| ID | Severity | Issue | Location |
|---|---|---|---|
| S1 | 🔴 High | Default password `admin123` active if `ADMIN_PASSWORD` env var not set | `auth.py:get_admin_password()` |
| S2 | 🔴 High | hCaptcha bypassed silently if `HCAPTCHA_SECRET` is empty | `auth.py:verify_hcaptcha_token()` |
| S3 | 🟡 Medium | `CORS: Allow-Origin: *` + `Allow-Credentials: true` (invalid combo, but misleading) | `server.py:end_headers()` |
| S4 | 🟡 Medium | `app.js` uses `innerHTML` with `item.url` from `domain.txt` — XSS if URL is malicious | `app.js:renderSummaryTable()` / `renderSnapshotBlocks()` |
| S5 | 🟡 Medium | Sessions and rate-limit state lost on container restart | `auth.py:SESSIONS` / `FAILED_ATTEMPTS` |
| S6 | 🟡 Medium | No HTTPS at application layer — must be behind reverse proxy | Deployment concern |
| S7 | 🟢 Low | No CSRF tokens on POST endpoints (relies on `SameSite=Lax`) | `server.py:do_POST()` |

## Technical Debt

| ID | Area | Issue |
|---|---|---|
| TD1 | Testing | Zero test coverage — no `tests/` directory, no CI pipeline |
| TD2 | Legacy code | `website_change_detect.py` is disconnected from server; duplicates `domain_manager.py` logic |
| TD3 | Templating | `index.html` uses `str.format()` — fragile with literal `{}` in data |
| TD4 | Speed mapping | `speed_map = {"low": 1, "medium": 4, "high": 4}` — `high` = `medium` (UI removed 8-worker option but backend not updated) |
| TD5 | Logging | All logging via `print()` — no log levels, no structured format, no log framework |
| TD6 | Dockerfile | `playwright install chromium` runs twice (base image already has it) — wastes ~200MB build time |
| TD7 | Docker | No `init: true` in `docker-compose.yaml` — zombie Playwright subprocesses accumulate |
| TD8 | Memory | `ScanManager.logs` list is unbounded during a scan |
| TD9 | Notifications | No alerting when changes are detected — dashboard must be checked manually |
| TD10 | Session persistence | Sessions reset on restart — users are logged out on every container restart |
| TD11 | API gap | No `GET /api/domains` endpoint — domain list not retrievable without rendering full report |

## Missing Features (Not Yet Implemented)
- Change notifications (email, webhook, ntfy.sh)
- Per-domain configuration (custom masks, timeouts, viewports)
- Multi-user / role-based access
- Session persistence across restarts
- Structured test suite
- CI/CD pipeline
- `GET /api/domains` to list monitored URLs
