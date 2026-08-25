# AGENTS.md — WebGlancer AI Agent Entry Point

## What This Project Is
**WebGlancer** is a self-hosted, Dockerized visual website change monitoring suite.
It screenshots URLs with Playwright/Chromium, pixel-diffs them against stored baselines using Pillow,
and serves results on a session-authenticated web dashboard with a REST API.

## Start Here — Read These Docs in Order
1. `docs/ARCHITECTURE.md` — Component map, data flow, file ownership
2. `docs/PROJECT_STATE.md` — Current state, known bugs, tech debt
3. `docs/DECISIONS.md` — Why key design choices were made
4. `docs/DEVELOPMENT.md` — How to run, build, test, deploy
5. `docs/TROUBLESHOOTING.md` — Debugging known failure modes

## Codebase at a Glance

```
visual_change_detector.py   ← CLI entry point (serve / update / check / add / remove)
website_change_detect.py    ← LEGACY standalone DOM-text diff tool. NOT integrated.
monitor/
  server.py                 ← All HTTP routing + REST API (the web server)
  scan_manager.py           ← Thread-safe scan state machine + ThreadPoolExecutor
  screenshot_engine.py      ← Playwright browser lifecycle + capture logic
  diff_engine.py            ← Pillow pixel-diff + magenta heatmap generation
  auth.py                   ← Session tokens, hCaptcha, rate limiting, audit log
  scheduler.py              ← Background daemon scheduler (5s poll loop)
  domain_manager.py         ← URL CRUD, normalize, SHA-256 slug, domain.txt I/O
  retention_manager.py      ← 5-day report + 30-day audit log retention
  config.py                 ← All path constants (single source of truth)
  web/
    index.html              ← Dashboard HTML template (Python str.format() placeholders)
    login.html              ← Self-contained login page (HTML + CSS + JS inline)
    styles.css              ← Dashboard styles
    app.js                  ← Dashboard frontend controller (670 lines)
```

## Critical Rules for Agents

1. **`config.py` is the authority on all file paths.** Never hardcode `.visual_cache/` paths elsewhere.
2. **`website_change_detect.py` is legacy/standalone.** Do not integrate it with `server.py` or `scheduler.py` without explicit instruction.
3. **`index.html` uses Python `str.format()` for templating.** Any literal `{` or `}` in template modifications must be escaped as `{{` / `}}`.
4. **All persistent state lives in the `webglancer_data` Docker volume** mounted at `/app/.visual_cache`. Do not store state anywhere else.
5. **Sessions and rate-limit state are in-memory only.** They reset on container restart by design (current state — see `PROJECT_STATE.md`).
6. **The scheduler runs as a daemon thread.** It does not survive container restart unless `schedule_config.json` re-enables it (which it does, since config is persisted on disk).
7. **Only one scan can run at a time.** `ScanManager.is_running` guards this. Do not bypass.
8. **`cleanup_all_browsers()` must be called after every scan** (in the `finally` block of `ThreadPoolExecutor`). Never remove this.

## Environment Variables (configure via `.env` or Docker env)

| Variable | Default | Notes |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | Change in production |
| `ADMIN_PASSWORD` | `admin123` | **Change in production — default is insecure** |
| `HCAPTCHA_SITEKEY` | *(public key in code)* | hCaptcha widget sitekey |
| `HCAPTCHA_SECRET` | *(empty)* | **If empty, CAPTCHA is silently bypassed** |
| `TZ` | `Asia/Kolkata` | Container timezone for scheduler |

## Key Constraints
- Python 3.11+ required (uses `zoneinfo`, walrus operator ``:=``, `match` not used).
- Playwright pinned to `==1.40.0` to match the Docker base image.
- Docker base image: `mcr.microsoft.com/playwright/python:v1.40.0-jammy`.
- Container port: `8087`.
- `shm_size: '1gb'` in docker-compose is **required** — Chromium crashes without it.
