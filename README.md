# Website Change Monitoring Suite

A robust, dual-engine suite for monitoring website changes, supporting both **Visual Screenshot Diffing** (designed for modern Single-Page Applications like React, Next.js, Vue, Angular) and **Static HTML Structural Diffing**, complete with an interactive Web Dashboard, **hCaptcha & Session Authentication**, **Brute-Force Rate Limiting**, **30-Day Audit Logging**, live execution progress, single-domain targeted controls, and Docker/Portainer deployment blueprints.

---

## 📋 Table of Contents

1. [Overview & Key Features](#-overview--key-features)
2. [Security, Authentication & Rate Limiting](#-security-authentication--rate-limiting)
3. [Tools Included](#-tools-included)
4. [Docker & Portainer Deployment](#-docker--portainer-deployment)
5. [Interactive Web Dashboard & Server Mode](#-interactive-web-dashboard--server-mode)
6. [Domain Management (Add & Remove Controls)](#-domain-management-add--remove-controls)
7. [Step-by-Step Setup on a New Machine](#-step-by-step-setup-on-a-new-machine)
8. [Detailed REST API & CLI Reference](#-detailed-rest-api--cli-reference)
9. [Directory Structure & Persistence](#-directory-structure--persistence)
10. [Automating with Cron / CI/CD](#-automating-with-cron--cicd)
11. [Troubleshooting & FAQ](#-troubleshooting--faq)

---

## 🔍 Overview & Key Features

Modern websites rely heavily on client-side JavaScript, async data fetching, and dynamic single-page application (SPA) frameworks. Traditional HTTP DOM scrapers often miss rendering changes or produce false alerts due to dynamic script tags, session tokens, or live widgets.

This suite provides two complementary engines:

1. **Visual Engine (`visual_change_detector.py`)**: Uses Playwright (Headless Chromium) with multithreaded parallel execution to render pages after JavaScript hydration, take high-resolution screenshots, mask volatile UI elements, compute pixel-by-pixel diff heatmaps, host an interactive Web Dashboard, and enforce **hCaptcha-protected authentication**.
2. **DOM Engine (`website_change_detect.py`)**: Uses Requests & BeautifulSoup for fast, lightweight static HTML comparison, automatically stripping dynamic non-visual tags (scripts, styles, CSRF tokens, GUIDs).

---

## 🛡️ Security, Authentication & Rate Limiting

The application includes enterprise-grade security features for deployment via Portainer or cloud servers:

### 1. hCaptcha Login Verification
- Dark-themed login page (`/login.html`) protected by **hCaptcha** bot verification.
- Every login request verifies the challenge token with the official hCaptcha API (`https://api.hcaptcha.com/siteverify`).

### 2. Session Cookie Authentication
- Restricted dashboard routes (`/`, `/report.html`, `.png` assets) and REST API endpoints require a valid `webglancer_session` HTTP cookie (`HttpOnly` & `SameSite=Lax`).
- Includes a persistent **🔒 Logout** button in the dashboard header to invalidate active sessions.

### 3. Brute-Force Rate Limiting & 5-Minute Lockout
- **5 Consecutive Failed Attempts**: Tracks failed login attempts (invalid password or failed captcha) per client IP address.
- **5-Minute Lockout**: Triggers an automatic 5-minute lockout (`HTTP 429 Too Many Requests`) upon the 5th consecutive failure.
- **Dynamic Countdown**: Displays remaining lockout seconds (`"Please wait 4 minute(s) and 58 second(s)..."`).
- **Auto-Reset**: Successful logins automatically reset the failed attempt counter.

### 4. 30-Day Audit Logging & Automatic Pruning
- Every login attempt (`SUCCESS`, `FAILED`, `RATE_LIMITED`, `LOGOUT`) is logged with **Timestamp**, **Client IP Address** (with `X-Forwarded-For` proxy support), **Username**, and **Reason**.
- Logs stream to standard output (`stdout` / Docker logs) and persist in `.visual_cache/login_audit.log`.
- **30-Day Retention Window**: Log entries older than 30 days are automatically pruned during daily maintenance sweeps to save disk space.
- Protected endpoint `GET /api/login-logs` provides real-time audit log access.

### 5. Secure Secret Management (DevSecOps Best Practice)
- Credentials are managed via `.env` file and container runtime environment variables.
- **⚠️ Important:** Default fallback values (`admin` / `admin123`) are active if `ADMIN_USERNAME` / `ADMIN_PASSWORD` env vars are not set. Always set strong credentials in production.
- **⚠️ Important:** If `HCAPTCHA_SECRET` is not set, CAPTCHA verification is silently bypassed.

---

## 🐳 Docker & Portainer Deployment

Deploy WebGlancer seamlessly using Docker Compose or Portainer Stacks.

### 1. Environment Variables Configuration

Create a `.env` file in the project root (copied from `.env.example`):

```env
# Dashboard Admin Credentials
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_secure_password_here

# hCaptcha Security Credentials
HCAPTCHA_SITEKEY=your_hcaptcha_sitekey_key_here
HCAPTCHA_SECRET=your_hcaptcha_secret_key_here
```

### 2. Docker Compose Deployment

```bash
# Build and start container in background
docker-compose up -d --build

# View real-time container logs
docker-compose logs -f
```

### 3. Portainer Stack Blueprint

In **Portainer** → **Stacks** → **Add Stack**, use **Git Repository** with the `final-testing` branch, or paste the following configuration directly. Set environment variables in the Portainer stack editor (do not use `env_file` in Portainer):

```yaml
services:
  webglancer:
    build:
      context: .
      dockerfile: Dockerfile
    image: webglancer:latest
    restart: unless-stopped
    ports:
      - "8087:8087"
    shm_size: '1gb'
    environment:
      - TZ=Asia/Kolkata
      - PYTHONUNBUFFERED=1
      - ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
      - ADMIN_PASSWORD=${ADMIN_PASSWORD:-admin123}
      - HCAPTCHA_SITEKEY=${HCAPTCHA_SITEKEY:-56d027fa-471e-4af2-bf82-f8a453acb8e2}
      - HCAPTCHA_SECRET=${HCAPTCHA_SECRET}
    volumes:
      # All persistent state: screenshots, reports, domain list, schedule config, audit logs
      - webglancer_data:/app/.visual_cache
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8087/login.html || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

volumes:
  webglancer_data:
    driver: local
    name: webglancer_data
```

> **Note:** `shm_size: '1gb'` is required — Chromium crashes without sufficient shared memory.

---

## 🌐 Interactive Web Dashboard & Server Mode

Start the web server locally or inside a container:

```bash
python visual_change_detector.py serve --port 8087
```

- **Login Page URL:** `http://localhost:8087/login.html`
- **Dashboard URL:** `http://localhost:8087/report.html` *(Requires login)*

---

## 📖 Detailed REST API & CLI Reference

### REST API Endpoints

| Endpoint | Method | Auth | Description |
| :--- | :--- | :--- | :--- |
| `/login.html` | GET | Public | Serves the hCaptcha login interface. |
| `/api/hcaptcha-config` | GET | Public | Returns active hCaptcha sitekey. |
| `/api/login` | POST | Public | Authenticates credentials & hCaptcha token. Sets session cookie. |
| `/api/logout` | POST | Public | Invalidates session token and clears cookie. |
| `/api/status` | GET | Session | Returns scan state, worker concurrency, and live progress logs. |
| `/api/history` | GET | Session | Returns list of archived 5-day daily reports. |
| `/api/login-logs` | GET | Session | Returns recent login audit log entries (IP, timestamp, status). |
| `/api/schedule` | GET / POST| Session | Retrieves or updates background scan schedule config. |
| `/api/start-scan` | POST | Session | Triggers suite-wide or custom domain visual scan (`check`/`update`). |
| `/api/add-domain` | POST | Session | Adds new domain(s) with optional baseline creation. |
| `/api/remove-domain`| POST | Session | Removes domain and purges baseline/latest/diff cache files. |

---

## 📁 Directory Structure & Persistence

```
website-change-monitoring-v2/
├── visual_change_detector.py    # CLI entry point (serve / update / check / add / remove)
├── website_change_detect.py     # Legacy standalone DOM-text diff tool (not integrated with server)
├── requirements.txt             # Python package dependencies
├── domain.txt                   # Seed domain list (copied to volume on first boot)
├── Dockerfile                   # Production Docker image build recipe
├── docker-compose.yaml          # Docker Compose / Portainer orchestration
├── .env.example                 # Environment configuration template
├── .env                         # Local runtime secrets (Git ignored)
├── docs/                        # Developer & AI agent documentation
│   ├── ARCHITECTURE.md
│   ├── PROJECT_STATE.md
│   ├── DECISIONS.md
│   ├── DEVELOPMENT.md
│   └── TROUBLESHOOTING.md
├── monitor/                     # Application package
│   ├── config.py                # Centralized path constants (single source of truth)
│   ├── auth.py                  # Sessions, hCaptcha, rate limiting & audit log
│   ├── server.py                # HTTP server handler & REST API router
│   ├── scan_manager.py          # Thread-safe scan state machine & worker pool
│   ├── screenshot_engine.py     # Playwright browser lifecycle & capture
│   ├── diff_engine.py           # Pillow pixel-diff & magenta heatmap generation
│   ├── domain_manager.py        # URL CRUD, normalization, SHA-256 slug, domain.txt I/O
│   ├── retention_manager.py     # 5-day report & 30-day audit log retention
│   ├── scheduler.py             # Background daemon scheduler (5s poll loop)
│   └── web/                     # Frontend assets
│       ├── login.html           # Self-contained login page (inline CSS + JS)
│       ├── index.html           # Dashboard template (Python str.format() placeholders)
│       ├── styles.css           # Dashboard styles
│       └── app.js               # Frontend controller (670 lines)
└── .visual_cache/               # Docker volume mount (webglancer_data → /app/.visual_cache)
    ├── domain.txt               # Active monitored URL list (managed via web UI)
    ├── baselines/               # Reference baseline screenshots (.png)
    ├── latest/                  # Most recent live screenshots (.png)
    ├── diffs/                   # Visual diff heatmaps — magenta highlight (.png)
    ├── report.html              # Live dashboard report (overwritten each scan)
    ├── report_YYYY-MM-DD.html   # Daily archived reports (5-day rolling window)
    ├── login_audit.log          # Login audit trail (30-day rolling window)
    └── schedule_config.json     # Scheduler configuration (persists across restarts)
```

---

## ❓ Troubleshooting & FAQ

### 1. `HTTP 429 Too Many Requests`
* **Cause**: 5 consecutive failed login attempts were recorded from your IP address.
* **Fix**: Wait 5 minutes for the lockout counter to automatically expire, or enter correct credentials once unblocked.

### 2. hCaptcha Verification Fails
* **Cause**: Missing or invalid `HCAPTCHA_SITEKEY` / `HCAPTCHA_SECRET` environment variables.
* **Fix**: Verify your sitekey and secret key in `.env` or Portainer environment variables.

### 3. Missing Audit Logs
* **Cause**: Logs older than 30 days are automatically pruned to save disk space.
* **Fix**: Active logs within 30 days are stored in `.visual_cache/login_audit.log` and accessible via `/api/login-logs`.

---

*Maintained for secure enterprise web monitoring and visual regression testing.*
