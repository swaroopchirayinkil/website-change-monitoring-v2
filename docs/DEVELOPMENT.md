# Development Guide

## Prerequisites
- Python 3.11+
- Docker + Docker Compose (or Portainer)
- `pip install -r requirements.txt`
- `playwright install chromium` (for local dev without Docker)

## Local Development (no Docker)

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Set credentials (or use insecure defaults for local dev only)
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=dev_password_here

# Start server
python visual_change_detector.py serve --port 8000
# Opens http://localhost:8000/login.html

# CLI usage (no server)
python visual_change_detector.py update --url https://example.com
python visual_change_detector.py check --url https://example.com
python visual_change_detector.py add https://example.com --create-baseline
python visual_change_detector.py remove https://example.com
```

## Docker / Portainer Deployment

```bash
# Create .env from template (never commit .env)
cp .env.example .env
# Edit .env: set ADMIN_PASSWORD and HCAPTCHA_SECRET

# Build and start
docker compose up -d --build

# View logs
docker compose logs -f webglancer

# Stop
docker compose down
```

Dashboard: `http://localhost:8087/login.html`

### Portainer (Git-based)
- Repository URL: `https://github.com/swaroopchirayinkil/website-change-monitoring-v2.git`
- Branch: `final-testing`
- Set env vars in Portainer stack editor (not via `.env` file)
- Volume `webglancer_data` persists all state

## Adding a New REST API Endpoint

1. Add route handling in `monitor/server.py`:
   - GET routes → `do_GET()` before the `return super().do_GET()` fallback
   - POST routes → `do_POST()` after the session authentication check block
2. Session guard is already applied at the middleware point — add new protected endpoints after the `is_valid_session` check.
3. Public endpoints (like `/api/hcaptcha-config`) go before the session check.
4. No framework routing — all routing is `if self.path == "/api/..."` conditionals.

## Adding a New Frontend Feature

- **HTML structure:** Edit `monitor/web/index.html`
  - Use `{{` and `}}` to escape literal braces (Python `str.format()` template)
  - Do not add Python placeholders outside of `generate_html_report()` in `server.py`
- **Styles:** Edit `monitor/web/styles.css`
- **JavaScript:** Edit `monitor/web/app.js`
  - Data from the server is available in `window.initialReportData` (array) and `window.initialHistoryData` (array)
  - Use `fetch('/api/...')` for live data — always check `isServerConnected` first
- **Template injection:** If new server-side data is needed in the initial page load, add it to `generate_html_report()` in `server.py` and add the corresponding placeholder to `index.html`

## Adding a New Domain Manager Operation

1. Add the function to `monitor/domain_manager.py`
2. Add an API endpoint in `monitor/server.py`
3. If the operation should trigger a report refresh, call `build_combined_report_results()` then `generate_html_report()`

## Modifying the Scan Pipeline

The scan pipeline lives in `monitor/scan_manager.py:_execute_scan()`.
- `action == "update"` → captures to `baselines/`
- `action == "check"` → captures to `latest/` then diffs
- Both use `get_thread_browser()` from `screenshot_engine.py`
- Both call `cleanup_all_browsers()` in the `finally` block — **never remove this**
- New scan options: add parameters to `start_scan()`, pass through `options` dict, consume in `_execute_scan()`

## Modifying the Scheduler

Config schema is in `scheduler.py:DEFAULT_SCHEDULE`. Any new fields added must be:
1. Included in `DEFAULT_SCHEDULE` with a safe default
2. Handled in `_is_due()` or `_calculate_next_run()` as appropriate
3. Saved/loaded via `save_config()` / `load_config()` (already generic — handles any dict keys)
4. Exposed in the frontend schedule card in `index.html` / `app.js`

## Environment Variable Handling Pattern

All env vars are read in `monitor/auth.py` via `os.environ.get("VAR", "default")`.
If adding a new env var:
1. Add the getter function in `auth.py` or `config.py`
2. Document it in `AGENTS.md` env var table
3. Add it to `.env.example` (without real values)
4. Add it to `docker-compose.yaml` environment section

## Report Generation

`generate_html_report(results, output_path)` in `server.py`:
1. Reads `monitor/web/index.html` as a template
2. Calls `template.format(now_str=..., total=..., report_data_json=..., ...)` 
3. Writes to `.visual_cache/report.html` (live) and `.visual_cache/report_YYYY-MM-DD.html` (daily archive)
4. Calls `cleanup_old_reports(max_days=5)` — deletes archives older than 5 days

## Key Path Constants (from `monitor/config.py`)

```python
BASE_DIR        = Path.cwd()
CACHE_DIR       = BASE_DIR / ".visual_cache"
BASELINES_DIR   = CACHE_DIR / "baselines"
LATEST_DIR      = CACHE_DIR / "latest"
DIFFS_DIR       = CACHE_DIR / "diffs"
REPORT_FILE     = CACHE_DIR / "report.html"
DEFAULT_DOMAIN_FILE = CACHE_DIR / "domain.txt"
WEB_DIR         = Path(__file__).parent / "web"   # monitor/web/
```

Always import from `monitor.config`. Never hardcode these paths.
