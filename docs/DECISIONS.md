# Architectural Decisions

## D1 — Python stdlib HTTP server instead of Flask/FastAPI
**Decision:** Use `http.server.SimpleHTTPRequestHandler` + `socketserver.ThreadingMixIn`.  
**Why:** Zero external web-framework dependency. Serves static files natively. API surface is small enough for manual routing. Keeps container lightweight.  
**Trade-off:** Manual routing in `do_GET`/`do_POST` is verbose. Adding many endpoints is painful.  
**Revisit if:** Endpoint count grows beyond ~15, or streaming/WebSocket is needed.

## D2 — Playwright sync API with thread-local browsers
**Decision:** One Playwright browser per worker thread, reused across URLs. `cleanup_all_browsers()` called in `finally` after each scan.  
**Why:** Sync API is simpler in a threaded context. Thread-local browsers avoid lock contention. Reuse reduces startup overhead (the dominant cost).  
**Trade-off:** See Bug B1 — stale browser entries after cleanup.

## D3 — Filesystem-only storage (no database)
**Decision:** All state in `.visual_cache/` flat files (PNG, HTML, JSON, plain text).  
**Why:** No DB setup, migrations, or connection management. Docker volume provides persistence.  
**Trade-off:** No query capability. Concurrent writes guarded only by `ScanManager.lock` — file writes are not atomic.  
**Revisit if:** Per-domain metadata, per-URL history, or multi-node deployment is needed.

## D4 — `str.format()` for HTML report templating
**Decision:** `index.html` uses `{placeholder}` tokens replaced by `generate_html_report()` via `template.format(...)`.  
**Why:** Zero template engine dependency.  
**Critical rule:** All literal `{` or `}` in `index.html` must be escaped as `{{` / `}}`. JSON data injected via `json.dumps()` is safe (braces are string-escaped), but template modifications are not.

## D5 — In-memory session and rate-limiting state
**Decision:** `auth.py:SESSIONS` and `FAILED_ATTEMPTS` are plain Python dicts.  
**Why:** Single-instance deployment. Session loss on restart is acceptable.  
**Trade-off:** All sessions invalidated on container restart. Rate-limiting resets on restart.

## D6 — 7-day session TTL, cookie-based auth
**Decision:** Sessions live 7 days. Cookie: `HttpOnly; SameSite=Lax`.  
**Why:** Single operator use case — long TTL reduces re-authentication friction.  
**Trade-off:** No idle timeout. Stolen token valid up to 7 days.

## D7 — hCaptcha over reCAPTCHA
**Decision:** hCaptcha for bot protection on login.  
**Why:** Privacy-focused. No Google dependency.  
**Critical trade-off:** If `HCAPTCHA_SECRET` env var is empty, verification is silently bypassed (`return True, "hCaptcha secret not configured"`). This is a dangerous default in production.

## D8 — Scheduler as a daemon thread (not system cron)
**Decision:** `SchedulerManager` runs a `threading.Thread(daemon=True)` polling every 5 seconds.  
**Why:** No external cron daemon needed. Config managed via web UI, persisted to JSON.  
**Trade-off:** Max 5-second drift from target time. Scheduler dies with process.

## D9 — No `container_name` in docker-compose
**Commit:** `6d14cc2`  
**Why:** Portainer auto-generates container names. A hardcoded name prevents multiple deployments and conflicts with existing containers.

## D10 — `domain.txt` stored inside Docker volume, seeded from repo root
**Commit:** `762841e`  
**Why:** Portainer Git deployments don't support bind mounts from host. Volume-only approach is universal.  
**Rule:** The root `domain.txt` in the repo is a seed only — applied once on first boot if `.visual_cache/domain.txt` doesn't exist. After that, all changes go through the web UI or API.

## D11 — `shm_size: '1gb'` required
**Why:** Chromium uses `/dev/shm` for rendering. Docker's default (64MB) causes Chromium OOM crashes.  
**Rule:** Do not reduce or remove `shm_size`.

## D12 — Pixel diff noise floor of 15/255
**Why:** Eliminates anti-aliasing, subpixel font variation, and JPEG compression artifacts that would produce false positives on unchanged pages.  
**`is_changed` threshold:** Default 0.1% of total pixels. Configurable via `--threshold` CLI flag.

## D13 — `website_change_detect.py` retained but not integrated
**Why:** Original v1 DOM-text-diff script. Different use case (text diff vs. visual diff), different cache dir (`.website_change_cache/`).  
**Status:** Effectively standalone. Do not import from it in `monitor/`.

## D14 — `playwright install chromium` in Dockerfile despite base image
**Current state:** This is technical debt (TD6). The base image `mcr.microsoft.com/playwright/python:v1.40.0-jammy` already includes Chromium. The redundant install was added to guarantee version consistency but adds ~200MB to build time.

## D15 — Structured Daily JSON History (`.visual_cache/history/`)
**Decision:** Store daily scan results as structured JSON files (`report_YYYY-MM-DD.json`) instead of parsing HTML archives for historical trends.  
**Why:** Machine-readable, zero-overhead querying, and backfill capability from existing HTML snapshots via regex parsing of `window.initialReportData`.  
**Storage location:** `.visual_cache/history/` inside the `webglancer_data` volume.

## D16 — Day-by-Day Percentage Matrix over Aggregate Statistics
**Decision:** In periodic reports (Weekly / Monthly / Custom), replace aggregated statistical fields (Period Status, Avg Mismatch, Peak Mismatch, Days Changed, Daily Timeline) with an explicit date-by-date percentage change matrix.  
**Why:** Users require exact day-to-day visual change percentage visibility across each domain in both the UI table and exported CSV spreadsheets, rather than broad aggregate summaries.

## D17 — 60-Day Rolling JSON Retention Policy
**Decision:** Retain daily JSON history snapshots for 60 calendar days (`cleanup_old_history(max_days=60)`).  
**Why:** Allows weekly and 30-day monthly periodic reporting with a comfortable buffer, while bounding Docker volume disk growth. HTML report archives remain on a 5-day retention window.

## D18 — Unified Reveal/Hide (`button-rh`) Accordion Model
**Decision:** Standardize expandable header panels (`addDomainCard`, `scheduleCard`, `historyCard`, `periodicReportsCard`) under a unified `toggleRHCard()` accordion controller.  
**Why:** Prevents multiple heavy control cards from remaining open concurrently, avoids cluttering the dashboard layout, and ensures the core live scan DOM hierarchy is never distorted.
