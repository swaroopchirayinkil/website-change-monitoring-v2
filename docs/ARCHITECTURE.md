# Architecture

## Component Map

```
┌─────────────────────────────────────────────────────┐
│  Docker Container (port 8087)                       │
│                                                     │
│  visual_change_detector.py                          │
│    └─ serve ──▶ monitor/server.py                   │
│                  MonitoringRequestHandler            │
│                  (ThreadedHTTPServer)                │
│                        │                            │
│          ┌─────────────┼──────────────┐             │
│          │             │              │             │
│       auth.py    scan_manager.py   scheduler.py     │
│          │             │              │             │
│          │      ┌──────┴──────┐    (5s poll)        │
│          │      ▼             ▼       │             │
│          │  screenshot_  diff_        │             │
│          │  engine.py    engine.py    │             │
│          │  (Playwright) (Pillow)     │             │
│          │                            │             │
│  ─────────── FILESYSTEM (.visual_cache/) ─────────  │
│  domain.txt  baselines/  latest/  diffs/            │
│  report.html  report_DATE.html                      │
│  history/ (report_DATE.json)                        │
│  schedule_config.json  login_audit.log              │
└─────────────────────────────────────────────────────┘
         ▲ HTTP (Cookie auth)
         │
   Browser client
   login.html → index.html / report.html
   app.js polls /api/status every 1s during scan
              checks /api/status every 3s always
```

## Module Responsibilities

| Module | Owns | Does NOT own |
|---|---|---|
| `config.py` | All `Path` constants for `.visual_cache/` | No logic |
| `server.py` | HTTP routing, session guards, `generate_html_report()` | Business logic |
| `scan_manager.py` | Scan state machine, `ThreadPoolExecutor`, `build_combined_report_results()` | Browser or image ops |
| `screenshot_engine.py` | Playwright browser pool (thread-local), `capture_screenshot()` | Diff logic |
| `diff_engine.py` | Pixel diff, heatmap PNG creation | Screenshot capture |
| `history_manager.py` | Daily JSON snapshot persistence, periodic date matrix compilation, CSV export, 60-day retention | Scan orchestration |
| `auth.py` | Sessions dict, `FAILED_ATTEMPTS` dict, hCaptcha API call, audit log file | HTTP response writing |
| `scheduler.py` | Background daemon thread, `schedule_config.json` persistence | Scan logic (delegates to `scan_manager`) |
| `domain_manager.py` | `domain.txt` CRUD, URL normalization, slug generation, cache file cleanup | Scan orchestration |
| `retention_manager.py` | Daily HTML deletion (5-day window), audit log pruning (30-day), hooks JSON history pruning (60-day) | Scan or auth logic |

## Data Flow — Scan Lifecycle

```
POST /api/start-scan
  │
  ▼
ScanManager.start_scan(action, speed, custom_urls)
  │  spawns daemon thread
  ▼
_execute_scan()
  │  ThreadPoolExecutor(max_workers=1–4)
  │  per URL:
  │    get_thread_browser()  ──▶  Playwright chromium (thread-local)
  │    capture_screenshot()  ──▶  page.goto() → wait → masks → screenshot PNG
  │    compute_visual_diff() ──▶  Pillow diff → heatmap PNG → {percentage, changed_pixels}
  │    ScanManager.logs.append(...)
  │
  ▼ (finally block)
cleanup_all_browsers()   ← closes all Playwright instances
  │
  ▼
build_combined_report_results()  ← merges fresh results + disk state for all domains
  │
  ▼
generate_html_report()   ← renders index.html template → report.html + report_DATE.html
```

## REST API Surface

| Method | Path | Auth | Handler location |
|---|---|---|---|
| GET | `/login` `/login.html` | Public | `server.py:do_GET` |
| GET | `/api/hcaptcha-config` | Public | `server.py:do_GET` |
| GET | `/styles.css` `/app.js` | Public | `server.py:do_GET` |
| POST | `/api/login` | Public | `server.py:do_POST` |
| POST | `/api/logout` | Public | `server.py:do_POST` |
| GET | `/api/status` | Session | `server.py:do_GET` → `scan_manager.get_state()` |
| GET | `/api/history` | Session | `server.py:do_GET` → `retention_manager.get_historical_reports()` |
| GET | `/api/reports/history-dates` | Session | `server.py:do_GET` → `history_manager.get_available_history_dates()` |
| GET | `/api/reports/generate` | Session | `server.py:do_GET` → `history_manager.generate_periodic_report()` |
| GET | `/api/reports/export` | Session | `server.py:do_GET` → `history_manager.export_report_csv()` |
| GET | `/api/login-logs` | Session | `server.py:do_GET` → `auth.get_login_audit_logs()` |
| GET | `/api/schedule` | Session | `server.py:do_GET` → `scheduler_manager.get_status()` |
| POST | `/api/schedule` | Session | `server.py:do_POST` → `scheduler_manager.save_config()` |
| POST | `/api/start-scan` | Session | `server.py:do_POST` → `scan_manager.start_scan()` |
| POST | `/api/add-domain` | Session | `server.py:do_POST` → `domain_manager.add_domains_to_file()` |
| POST | `/api/remove-domain` | Session | `server.py:do_POST` → `domain_manager.remove_domains_from_file()` |
| GET | `/report.html` `/baselines/*` `/latest/*` `/diffs/*` | Session | `SimpleHTTPRequestHandler` fallback (serves `.visual_cache/`) |

## Storage Layout

```
.visual_cache/               ← Docker volume root (webglancer_data)
  domain.txt                 ← Monitored URL list (one per line, # for comments)
  report.html                ← Live dashboard (overwritten each scan)
  report_YYYY-MM-DD.html     ← Daily archive (5-day rolling, auto-deleted)
  history/                   ← Structured daily JSON records (60-day rolling retention)
    report_YYYY-MM-DD.json   ← Machine-readable daily scan results across all domains
  schedule_config.json       ← Scheduler settings (enabled, freq, hour, tz, last_run)
  login_audit.log            ← Login/logout audit trail (30-day rolling, auto-pruned)
  baselines/{slug}.png       ← Reference screenshots
  latest/{slug}.png          ← Most recent live screenshots
  diffs/{slug}_diff.png      ← Magenta pixel-diff heatmaps
```

**URL → filename slug:** `url_to_slug(url)` in `domain_manager.py`  
= `{sanitized_domain_prefix_30chars}_{sha256(url)[:16]}`  
Deterministic and collision-resistant.

## Frontend Architecture

`login.html` — Fully self-contained (inline CSS + JS). Loads hCaptcha from CDN. On success sets `webglancer_session` cookie and redirects to `/report.html`.

`index.html` — Python `str.format()` template rendered server-side by `generate_html_report()`.  
Placeholders: `{now_str}`, `{total}`, `{changed}`, `{unchanged}`, `{failed}`, `{report_data_json}`, `{history_data_json}`.  
**Any `{` or `}` added to this file outside a placeholder must be escaped as `{{` / `}}`.**

`app.js` — Stateless frontend controller:
- `renderSummaryTable()` / `renderSnapshotBlocks()` — reads from `window.initialReportData` (injected at page bottom by template).
- `checkServerStatus()` — polls `/api/status` every 3s; drives `isServerConnected` flag.
- `startPolling()` / `updateProgressUI()` — 1s poll during active scan; reloads page on completion.
- `toggleRHCard(targetId, callback)` — Accordion reveal/hide pattern for expandable panels (`addDomainCard`, `scheduleCard`, `historyCard`, `periodicReportsCard`), automatically closing other open cards to keep the UI clean.
- `renderPeriodicReportTable(data)` — Dynamically renders day-by-day percentage matrix columns across Weekly, Monthly, or Custom periods.
- `downloadPeriodicReport(format)` — Downloads periodic reports in CSV or JSON.
- All domain/scan operations call REST API then either reload or start polling.

## Authentication Flow

```
Client → POST /api/login {username, password, hcaptcha_response}
  server.py:
    1. check_rate_limit(client_ip)  ← 5 failures = 5-min lockout
    2. verify credentials (env vars)
    3. verify_hcaptcha_token()  ← calls api.hcaptcha.com (bypassed if HCAPTCHA_SECRET empty)
    4. create_session()  ← UUID4, 7-day TTL, stored in SESSIONS dict
    5. Set-Cookie: webglancer_session=<token>; HttpOnly; SameSite=Lax
```

All subsequent requests read `Cookie: webglancer_session=<token>` via `get_session_from_headers()`.

## Scheduler Behavior

- Daemon thread starts with server, polls every 5 seconds.
- Reads `schedule_config.json` each tick (under lock).
- Skips if `scan_manager.is_running` is True.
- `_is_due()`: for `daily` — compares current time vs configured hour:minute in chosen timezone; for `1h/6h/12h` — checks elapsed time since `last_run`.
- On trigger: writes `last_run` to disk before calling `scan_manager.start_scan()`.
- Config survives container restart (persisted in volume).

## Concurrency Model

- HTTP server: `ThreadingMixIn` — one thread per HTTP request.
- Scan workers: `ThreadPoolExecutor(max_workers=1 or 4)` — thread-local Playwright browser per worker.
- Scheduler: single daemon thread.
- State guard: `ScanManager.lock` (threading.Lock) protects all mutable scan state.
- `_thread_browsers_lock` protects the global browser registry list.
