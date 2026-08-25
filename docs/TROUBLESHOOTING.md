# Troubleshooting

## Chromium / Playwright Issues

### Chromium crashes immediately in Docker
**Symptom:** Scan fails instantly; logs show shared memory or signal errors.  
**Cause:** Insufficient `/dev/shm` allocation.  
**Fix:** Ensure `shm_size: '1gb'` is present in `docker-compose.yaml`. Never remove it.

### "Target page, context or browser has been closed"
**Symptom:** Screenshot capture raises Playwright error after a previous scan.  
**Cause:** Bug B1 — stale thread-local browser reference after `cleanup_all_browsers()`. The browser was closed but `_thread_local.playwright` / `_thread_local.browser` attributes still exist.  
**Fix (workaround):** Restart the container to clear thread-local state. Permanent fix requires resetting `_thread_local` attributes in `cleanup_all_browsers()` — see `monitor/screenshot_engine.py`.

### Navigation timeout warnings in logs
**Symptom:** `[Warning] Navigation timeout for 'https://...': ...`  
**Cause:** The target URL's `load` event takes longer than `timeout` (default 30000ms) or never fires (SPAs with infinite watchers).  
**Behavior:** The code automatically retries with `wait_until="domcontentloaded"`. Screenshot is still captured.  
**Fix:** Add `--wait-until domcontentloaded` for slow SPAs, or increase `timeout`.

### Zombie Playwright processes accumulating
**Symptom:** `ps aux` shows many orphaned `chrome` / `chromium` processes inside the container.  
**Cause:** No PID 1 init process — Docker's default process cannot reap zombie children.  
**Fix:** Add `init: true` to the service in `docker-compose.yaml`. This enables `tini` as PID 1.

---

## Authentication Issues

### Login fails even with correct credentials
**Check 1:** Is `ADMIN_PASSWORD` env var set? Default is `admin123` — confirm the value with `docker exec <container> env | grep ADMIN`.  
**Check 2:** Is hCaptcha completing successfully? If `HCAPTCHA_SECRET` is set but incorrect, the verification API returns failure even on valid CAPTCHA responses.  
**Check 3:** Is the IP rate-limited? After 5 failures, the IP is locked for 5 minutes. Check `login_audit.log` in the volume.

### "Authentication required" on all pages after container restart
**Cause:** Sessions are in-memory only — they are cleared on every restart.  
**Fix:** Log in again. This is by design (see Decision D5). Permanent fix requires session persistence.

### hCaptcha widget not appearing on login page
**Cause:** hCaptcha CDN script (`https://js.hcaptcha.com/1/api.js`) failed to load — network issue or ad blocker.  
**Behavior:** `hcaptcha.getResponse()` returns `''` → client-side validation rejects submission before reaching the server.  
**Fix:** Check browser console for script load errors. Ensure no ad blocker is blocking `js.hcaptcha.com`.

### Rate limit won't clear
**Cause:** Rate-limiting state is in-memory. The only way to clear it without waiting is a container restart.  
**Workaround:** `docker compose restart webglancer` — this also clears all active sessions.

---

## Scan / Monitoring Issues

### "No baseline screenshot. Run baseline update first."
**Cause:** A live check was triggered for a URL that has never had a baseline captured.  
**Fix:** Run "Update Baselines" (or `POST /api/start-scan {action: "update"}`) for the affected URL.

### Page shows "Failed" for all URLs after adding new domain
**Cause:** Domain added without "Automatically capture initial baseline" checkbox checked.  
**Fix:** Click "Update Baselines" or check the box when adding domains.

### Report shows "Changed" for pages that clearly haven't changed
**Cause:** Dynamic content (ads, timestamps, cookie banners, animated elements) is causing pixel differences.  
**Fix:** Use the `mask` option (CSS selectors) to hide volatile elements during capture. Currently only configurable via CLI `--mask` flag; the web UI doesn't expose this yet.

### Scan is stuck — progress never advances
**Symptom:** Progress bar stays at 0% or a URL never completes.  
**Cause:** A URL is hanging past the timeout. The `ThreadPoolExecutor` thread is blocked.  
**Check:** Logs in the progress panel show which URL is active.  
**Fix:** If stuck, the only recovery is a container restart (forcibly terminates the stuck thread). Reduce `timeout` for faster failure.

### "A task is already in progress" error from API
**Cause:** `ScanManager.is_running` is True — another scan is running.  
**Fix:** Wait for the current scan to complete. Only one scan can run at a time by design.

---

## Report / Dashboard Issues

### `report.html` is blank or shows template placeholders like `{total}`
**Cause:** `generate_html_report()` failed — likely a `str.format()` error from a literal `{` or `}` in the template.  
**Fix:** Check `monitor/web/index.html` for any unescaped curly braces added during a recent edit. Escape as `{{` / `}}`.

### Historical reports not appearing in the archive panel
**Cause 1:** Daily reports only exist if a scan ran on that calendar day.  
**Cause 2:** Reports older than 5 days are auto-deleted by `cleanup_old_reports()`.  
**Check:** List files in `.visual_cache/` → look for `report_YYYY-MM-DD.html`.

### Dashboard shows stale data after a scan
**Cause:** `window.initialReportData` is injected at page render time. The JS `updateProgressUI()` function triggers `window.location.reload()` when the scan completes, which should refresh data.  
**Fix:** Hard-reload the page (Ctrl+Shift+R) to bypass browser cache.

---

## Docker / Deployment Issues

### `domain.txt` is empty after redeployment
**Cause:** The domain list is stored in the Docker volume (`.visual_cache/domain.txt`). If the volume was deleted or is new, the volume is seeded from the repo root `domain.txt` once.  
**Fix:** The root `domain.txt` in the repo is the seed. Populate it before first deployment, or re-add domains via the web UI after deployment.

### Portainer deployment fails with volume mount error
**Cause:** Older versions of the stack had a bind mount for `domain.txt` that Portainer doesn't support.  
**Fix:** Ensure `docker-compose.yaml` uses only named volume mounts (`webglancer_data:/app/.visual_cache`), not host bind mounts. See commit `762841e`.

### Container restarts in a loop (health check failing)
**Symptom:** `docker compose ps` shows container restarting.  
**Cause:** Health check `curl -f http://localhost:8087/login.html` is failing.  
**Diagnosis:** `docker compose logs webglancer` — look for Python startup errors.  
**Common causes:** Port 8087 already in use; Python import error on startup; `monitor/web/login.html` missing.

### Build takes very long
**Cause:** Technical debt TD6 — `playwright install chromium` runs twice during build (base image already has it). Each run downloads ~200MB.  
**Workaround:** Use layer caching (`docker compose build` reuses cache if `requirements.txt` unchanged).

---

## Log Locations

| Log | Location | Format |
|---|---|---|
| Docker stdout | `docker compose logs webglancer` | Plain text `print()` output |
| Login audit | `.visual_cache/login_audit.log` | `[YYYY-MM-DD HH:MM:SS] [AUTH] [STATUS] IP: ... \| User: ... \| Reason: ...` |
| Schedule last run | `.visual_cache/schedule_config.json` → `last_run` field | ISO 8601 datetime |
