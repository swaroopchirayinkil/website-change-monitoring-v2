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
- Secrets are **never hardcoded** in container image layers (`Dockerfile`).
- Managed dynamically via `.env` file and container runtime environment variables.

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

In **Portainer** → **Stacks** → **Add Stack**, paste the following configuration:

```yaml
version: "3.8"

services:
  webglancer:
    image: webglancer:latest
    restart: unless-stopped
    ports:
      - "8087:8087"
    env_file:
      - path: .env
        required: false
    environment:
      - TZ=Asia/Kolkata
      - PYTHONUNBUFFERED=1
      - ADMIN_USERNAME=${ADMIN_USERNAME:-admin}
      - ADMIN_PASSWORD=${ADMIN_PASSWORD:-admin123}
      - HCAPTCHA_SITEKEY=${HCAPTCHA_SITEKEY}
      - HCAPTCHA_SECRET=${HCAPTCHA_SECRET}
    volumes:
      # Persist screenshots, history, schedule config, and audit logs
      - webglancer_data:/app/.visual_cache
      # Persist domain target list
      - ./domain.txt:/app/domain.txt:rw
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8087/login.html || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

volumes:
  webglancer_data:
    name: webglancer_data
```

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
website-change-monitoring/
├── visual_change_detector.py    # Playwright & Pillow Visual Change Monitor + Web Server
├── website_change_detect.py     # Requests & BeautifulSoup HTML Structural Monitor
├── requirements.txt             # Python package dependencies
├── domain.txt                   # Monitored domain target file
├── Dockerfile                   # Production Docker image build recipe
├── docker-compose.yml           # Docker Compose orchestration blueprint
├── .env.example                 # Environment configuration template
├── .env                         # Local runtime secrets (Git ignored)
├── monitor/                     # Application Package Core
│   ├── auth.py                  # Session handling, hCaptcha, Rate Limiting & Audit Logger
│   ├── server.py                # HTTP Server Handler & REST API Router
│   ├── scan_manager.py          # Parallel worker pool manager
│   ├── retention_manager.py     # Daily report & 30-day log retention pruner
│   ├── scheduler.py             # Persistent daily background scanner
│   └── web/                     # Web Frontend Templates & Assets
│       ├── login.html           # Dark-mode glassmorphism login UI
│       ├── index.html           # Dashboard template
│       ├── styles.css           # UI Design System CSS
│       └── app.js               # Frontend JavaScript controller
└── .visual_cache/               # Persistent volume mount path
    ├── baselines/               # Reference baseline screenshots (.png)
    ├── latest/                  # Live screenshots (.png)
    ├── diffs/                   # Visual diff heatmaps (.png)
    ├── history/                 # 5-day daily report archives (.html)
    ├── login_audit.log          # 30-day persistent login audit log
    └── schedule_config.json     # Saved background schedule configuration
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
