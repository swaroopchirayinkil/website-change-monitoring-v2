# Website Change Monitoring Suite

A robust, dual-engine suite for monitoring website changes, supporting both **Visual Screenshot Diffing** (designed for modern Single-Page Applications like React, Next.js, Vue, Angular) and **Static HTML Structural Diffing**, complete with an interactive Web Dashboard, live execution progress, single-domain targeted controls, and full CRUD domain management.

---

## 📋 Table of Contents

1. [Overview & Key Features](#-overview--key-features)
2. [Tools Included](#-tools-included)
3. [Interactive Web Dashboard & Server Mode](#-interactive-web-dashboard--server-mode)
4. [Domain Management (Add & Remove Controls)](#-domain-management-add--remove-controls)
5. [Step-by-Step Setup on a New Machine](#-step-by-step-setup-on-a-new-machine)
6. [Detailed CLI Reference & Options](#-detailed-cli-reference--options)
   - [Visual SPA Monitoring (`visual_change_detector.py`)](#1-visual-spa-monitoring-visual_change_detectorpy)
   - [HTML Text Monitoring (`website_change_detect.py`)](#2-html-text-monitoring-website_change_detectpy)
7. [Testing the Features](#-testing-the-features)
8. [Usage Examples & Common Workflows](#-usage-examples--common-workflows)
9. [Directory Structure & Cache Files](#-directory-structure--cache-files)
10. [Automating with Cron / CI/CD](#-automating-with-cron--cicd)
11. [Troubleshooting & FAQ](#-troubleshooting--faq)

---

## 🔍 Overview & Key Features

Modern websites rely heavily on client-side JavaScript, async data fetching, and dynamic single-page application (SPA) frameworks. Traditional HTTP DOM scrapers often miss rendering changes or produce false alerts due to dynamic script tags, session tokens, or live widgets.

This suite provides two complementary engines:

1. **Visual Engine (`visual_change_detector.py`)**: Uses Playwright (Headless Chromium) with multithreaded parallel execution to render pages after JavaScript hydration, take high-resolution screenshots, mask volatile UI elements, compute pixel-by-pixel diff heatmaps, and host an interactive Web Dashboard.
2. **DOM Engine (`website_change_detect.py`)**: Uses Requests & BeautifulSoup for fast, lightweight static HTML comparison, automatically stripping dynamic non-visual tags (scripts, styles, CSRF tokens, GUIDs).

---

## 🛠️ Tools Included

### 1. `visual_change_detector.py` (Visual SPA Monitor & Web Dashboard)
- **Interactive Web Dashboard Server (`serve`)**: Built-in HTTP server hosting a modern dashboard (`http://localhost:8000/report.html`) with server online indicator, task controller, live progress banner, log console, and domain management.
- **Granular Single-Domain Controls**: Dedicated `📸 Baseline` and `🔍 Check` control buttons for every domain to trigger targeted single-site scans without re-scanning the entire suite.
- **Full Domain Management**: Add single/bulk domains and remove domains (with automatic cache purging) via Web UI and REST API.
- **High-Speed Parallel Processing (`-c` / `--concurrency`)**: Uses worker thread pools to process multiple URLs simultaneously with configurable speed presets (Low: 1 worker, Medium: 4 workers, High: 8 workers).
- **Persistent Worker Browsers**: Reuses browser instances per worker thread, eliminating browser startup overhead for every URL.
- **Resilient Timeout Fallback**: Automatically captures currently rendered DOM state if slow external trackers exceed navigation timeouts.
- **Element Masking (`--mask`)**: Injects dynamic CSS rules to hide volatile components (clocks, ads, dynamic banners, chat widgets) prior to screenshot capture.
- **Pixel-by-Pixel Diff Engine & Heatmap**: Employs Python `Pillow` to compute pixel mismatches, filter anti-aliasing noise, and output high-contrast magenta heatmaps.

### 2. `website_change_detect.py` (Lightweight HTML Text Inspector)
- **Fast Static DOM Scraping**: Fast HTTP requests via `requests`.
- **Intelligent HTML Cleaning**: Automatically removes script tags, CSS styles, hidden inputs (CSRF, state tokens), and randomized query parameter GUIDs.
- **Unified Diff Output**: Outputs standard unified line diffs when structural changes are detected.
- **Domain CLI Management**: Supports `add` and `remove` subcommands to maintain the monitoring target list and HTML cache files.

---

## 🌐 Interactive Web Dashboard & Server Mode

Start the web server to access the interactive dashboard:

```bash
python visual_change_detector.py serve
```
Then visit **`http://localhost:8000/report.html`** in your browser.

### Key Features of the Dashboard
- **Executive Task Controller**: Launch suite-wide or single-domain baseline updates and live visual checks with one click.
- **Resource Usage / Speed Selector**:
  - 🐢 **Low Resource Usage**: 1 worker thread (ideal for low-RAM VMs or single-core environments).
  - ⚡ **Medium Speed**: 4 worker threads.
  - 🚀 **High Speed**: 8 worker threads (maximum batch scanning throughput).
- **Live Task Progress Banner & Log Console**: Displays real-time scan percentage, currently active URL, active worker count, and scrolling logs during execution.
- **Targeted Single-Domain Actions**: Each domain row includes dedicated `📸 Baseline`, `🔍 Check`, and `🗑️ Remove` buttons.
- **Interactive Executive Table**: Instant sorting by URL, status, or diff percentage, plus status filter chips (`All`, `Changed`, `Unchanged`, `Failed`).
- **Floating Smooth Scroll**: Floating `↑ Top` button for seamless navigation across large reports.

---

## ➕ Domain Management (Add & Remove Controls)

### 1. Adding Domains (Single & Bulk)
* **Web UI**: Click **`➕ Add Domain(s)`** in the control panel to expand the domain input card. Type one or multiple URLs (one per line). Option to automatically generate baseline screenshots upon adding.
* **REST API**: `POST /api/add-domain` accepts JSON `{"urls": [...], "create_baseline": true}`.
* **CLI**:
  ```bash
  python visual_change_detector.py add --url https://example.com --create-baseline
  python website_change_detect.py add --url https://example.com
  ```

### 2. Removing Domains & Purging Cache
* **Web UI**: Click **`🗑️ Remove`** next to any domain in the summary table or block header. Confirms action, removes domain from `domain.txt`, purges cached screenshots, and reloads the report.
* **REST API**: `POST /api/remove-domain` accepts JSON `{"url": "https://example.com"}`.
* **CLI**:
  ```bash
  python visual_change_detector.py remove --url https://example.com
  python website_change_detect.py remove --url https://example.com
  ```

---

## 🚀 Step-by-Step Setup on a New Machine

Follow these exact steps to set up and run the monitoring tools on a fresh system (Linux, macOS, or Windows WSL).

### System Prerequisites
- **Python**: Version 3.8 or higher (`python3 --version`)
- **Git**: Installed on system
- **Internet Access**: To fetch Playwright browser binaries and target URLs.

### Step 1: Clone the Repository
```bash
git clone https://github.com/swaroopchirayinkil/website-change-monitoring.git
cd website-change-monitoring
```

### Step 2: Create and Activate a Virtual Environment
```bash
# Create virtual environment
python3 -m venv venv

# Activate on Linux/macOS:
source venv/bin/activate

# Activate on Windows (Command Prompt):
# venv\Scripts\activate.bat

# Activate on Windows (PowerShell):
# venv\Scripts\Activate.ps1
```

### Step 3: Install Python Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Install Playwright Headless Chromium Browser & System Dependencies
Playwright requires headless Chromium browser binaries and native Linux shared libraries to execute screenshots on headless Linux virtual machines.

```bash
# Install Chromium browser binary inside venv
playwright install chromium

# MANDATORY on Linux/Ubuntu Virtual Machines (runs install-deps via venv path so sudo can find it):
sudo ./venv/bin/playwright install-deps chromium
```

---

## 📖 Detailed CLI Reference & Options

### 1. Visual SPA Monitoring (`visual_change_detector.py`)

#### Command Syntax
```bash
python visual_change_detector.py <command> [options]
```

#### Eg: Command Syntax to run the Rest API Server and create dashboard

```bash
python visual_change_detector.py serve
```

#### Subcommands
* `serve`: Launch the interactive Web Dashboard & REST API server (`http://localhost:8000/report.html`).
* `add`: Single or bulk add domain(s) to monitoring list with deduplication and optional baseline generation (`--create-baseline` / `-b`).
* `remove`: Remove domain(s) from monitoring list and clean up baseline/latest/diff cache files.
* `update`: Captures target page screenshot(s) and saves them as baseline snapshots.
* `check`: Captures live screenshot(s), compares them against existing baselines, calculates visual difference percentages, and generates the HTML report.

#### Global & Subcommand Options

##### Web Dashboard Server (`serve` Subcommand)
| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--port` | Integer | `8000` | HTTP port to listen on. |
| `--host` | String | `0.0.0.0` | Host IP address to bind to (`0.0.0.0` allows network access). |
| `--no-browser` | Flag | `False` | Disables automatic browser launch upon server startup. |

##### Domain Management (`add` and `remove` Subcommands)
| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--url`, `-u` | String | `None` | Single or multiple target domain(s)/URL(s) (repeatable). |
| `--import-file`, `-f` | Path | `None` | Path to a text file containing domains (one per line). |
| `positional_urls` | String | `None` | Domains/URLs passed directly as positional CLI arguments. |
| `--target-file` | Path | `domain.txt` | Target domain list file to update. |
| `--create-baseline`, `-b` | Flag | `False` | *(Add only)* Automatically capture baseline screenshots for newly added domains. |

##### Capture & Diff Engine (`update` / `check` Subcommands)
| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--url` | String | `None` | Target URL to monitor (repeatable). |
| `--url-file` | Path | `None` | Path to a text file containing target URLs (one per line). |
| `-c`, `--concurrency` | Integer | `4` | Number of parallel Playwright browser worker threads. |
| `--wait-until` | String | `load` | Navigation wait strategy (`load`, `domcontentloaded`, or `networkidle`). |
| `--timeout` | Integer | `30000` | Navigation timeout in milliseconds before fallback capture. |
| `--width` | Integer | `1280` | Viewport width in pixels. |
| `--height` | Integer | `800` | Viewport height in pixels. |
| `--full-page` | Flag | `True` | Captures full scrollable height of the page. |
| `--wait-ms` | Integer | `1000` | Milliseconds to wait after load for JavaScript hydration. |
| `--wait-selector` | String | `None` | CSS selector to wait for before taking snapshot. |
| `--mask` | String | `None` | CSS selector of dynamic elements to hide/mask before capture (repeatable). |
| `--threshold` | Float | `0.1` | *(Check only)* Percentage threshold of visual pixel change to trigger `Changed` status. |

---

### 2. HTML Text Monitoring (`website_change_detect.py`)

```bash
python website_change_detect.py <command> [options]
```

* `update`: Fetches HTML, applies tag cleaning, and saves baseline HTML to `.website_change_cache/`.
* `check`: Fetches live HTML, applies tag cleaning, and compares line-by-line with cached snapshot.
* `add`: Adds domain(s) to target file with optional `--update-cache`.
* `remove`: Removes domain(s) from target file and deletes HTML cache files.

---

## 🧪 Testing the Features

### 1. Testing Web Dashboard UI
1. **Start Server**: `python visual_change_detector.py serve`
2. **Open Browser**: Go to `http://localhost:8000/report.html`.
3. **Test Add Domain**:
   - Click `➕ Add Domain(s)`.
   - Enter `https://news.ycombinator.com`.
   - Ensure auto-baseline checkbox is checked and click `Add to Monitoring`.
   - Verify progress bar completes and page reloads with the new domain.
4. **Test Targeted Single-Domain Check**:
   - Click `🔍 Check` on an individual domain row.
   - Verify scan runs only for that single domain.
5. **Test Remove Domain**:
   - Click `🗑️ Remove` next to a domain.
   - Confirm removal dialog.
   - Verify domain is removed from table and `domain.txt`.

### 2. Testing CLI Subcommands
```bash
# Add domain via CLI with auto-baseline
python visual_change_detector.py add --url https://example.com --create-baseline

# Run visual check for single domain
python visual_change_detector.py check --url https://example.com

# Remove domain via CLI
python visual_change_detector.py remove --url https://example.com
```

---

## 💡 Usage Examples & Common Workflows

### High-Speed Batch Scan (8 Parallel Workers)
```bash
python visual_change_detector.py check --url-file domain.txt --threshold 0.1 -c 8 --wait-ms 500
```

### Masking Dynamic Ads and Chat Widgets
```bash
python visual_change_detector.py check \
  --url https://example.com \
  --mask ".ad-banner" \
  --mask "#chat-widget" \
  --threshold 0.5
```

---

## 📁 Directory Structure & Cache Files

```
website-change-monitoring/
├── visual_change_detector.py    # Playwright & Pillow Visual Change Monitor + Web Server
├── website_change_detect.py     # Requests & BeautifulSoup HTML Structural Monitor
├── requirements.txt             # Python package dependencies
├── domain.txt                   # Monitored domain target file
├── README.md                    # Complete project documentation
├── .visual_cache/               # Managed visual cache directory
│   ├── baselines/               # Reference baseline screenshots (.png)
│   ├── latest/                  # Live screenshots (.png)
│   ├── diffs/                   # Visual diff heatmaps (.png)
│   └── report.html              # Interactive HTML dashboard report
└── .website_change_cache/       # Managed HTML cache directory
    └── <url_hash>.html          # Cached cleaned HTML snapshots
```

---

## ⏰ Automating with Cron / CI/CD

### Example Linux Cron Job (Hourly Checks)
```bash
0 * * * * cd /path/to/website-change-monitoring && ./venv/bin/python visual_change_detector.py check --url-file domain.txt -c 4 >> /var/log/website_monitor.log 2>&1
```

---

## ❓ Troubleshooting & FAQ

### 1. `OSError: [Errno 98] Address already in use`
* **Cause**: A web server process is already running on port 8000.
* **Fix Options**:
  - Run on a different port: `python visual_change_detector.py serve --port 8080`
  - Or free port 8000: `fuser -k 8000/tcp`

### 2. Playwright / Chromium Missing Dependencies on Linux
* **Cause**: Missing Linux system libraries for headless browser rendering.
* **Fix**: Run `sudo ./venv/bin/playwright install-deps chromium`.

### 3. False Alerts on Dynamic Timestamps or News Tickers
* **Cause**: Live clock or dynamic widget changes between runs.
* **Fix**: Use `--mask` with dynamic CSS selectors (e.g. `--mask ".timestamp" --mask ".live-ad"`).

---

*Maintained for web infrastructure monitoring and visual regression testing.*
