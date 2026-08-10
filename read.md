# Website Change Monitoring Suite

A robust, dual-engine suite for monitoring website changes, supporting both **Visual Screenshot Diffing** (designed for modern Single-Page Applications like React, Next.js, Vue, Angular) and **Static HTML Structural Diffing**.

---

## 📋 Table of Contents

1. [Overview & Key Features](#-overview--key-features)
2. [Tools Included](#-tools-included)
3. [Step-by-Step Setup on a New Machine](#-step-by-step-setup-on-a-new-machine)
4. [Detailed CLI Reference & Options](#-detailed-cli-reference--options)
   - [Visual SPA Monitoring (`visual_change_detector.py`)](#1-visual-spa-monitoring-visual_change_detectorpy)
   - [HTML Text Monitoring (`website_change_detect.py`)](#2-html-text-monitoring-website_change_detectpy)
5. [Usage Examples & Common Workflows](#-usage-examples--common-workflows)
6. [Interactive HTML Visual Report](#-interactive-html-visual-report)
7. [Directory Structure & Cache Files](#-directory-structure--cache-files)
8. [Automating with Cron / CI/CD](#-automating-with-cron--cicd)
9. [Troubleshooting & FAQ](#-troubleshooting--faq)

---

## 🔍 Overview & Key Features

Modern websites rely heavily on client-side JavaScript, async data fetching, and dynamic single-page application (SPA) frameworks. Traditional HTTP DOM scrapers often miss rendering changes or produce false alerts due to dynamic script tags, session tokens, or live widgets.

This suite provides two complementary tools:

1. **Visual Engine (`visual_change_detector.py`)**: Uses Playwright (Headless Chromium) with multithreaded parallel execution to render pages after JavaScript hydration, take high-resolution screenshots, mask volatile UI elements, compute pixel-by-pixel diff heatmaps, and generate self-contained HTML reports.
2. **DOM Engine (`website_change_detect.py`)**: Uses Requests & BeautifulSoup for fast, lightweight static HTML comparison, automatically stripping dynamic non-visual tags (scripts, styles, CSRF tokens, GUIDs).

---

## 🛠️ Tools Included

### 1. `visual_change_detector.py` (Visual SPA Monitor)
- **High-Speed Parallel Processing (`-c` / `--concurrency`)**: Uses worker thread pools to process multiple URLs simultaneously.
- **Persistent Worker Browsers**: Reuses browser instances per worker thread, eliminating browser startup overhead for every URL.
- **Configurable Navigation Wait Strategy (`--wait-until`)**: Defaults to `load` to prevent modern ad/analytics trackers from causing long 30-second timeouts.
- **Resilient Timeout Fallback**: Automatically captures currently rendered DOM state if slow external trackers exceed navigation timeouts.
- **Headless Browser Rendering**: Uses Playwright Chromium to wait for JS execution & SPA hydration.
- **Element Masking (`--mask`)**: Injects dynamic CSS rules to hide volatile components (clocks, ads, dynamic banners, chat widgets) prior to screenshot capture.
- **Pixel-by-Pixel Diff Engine**: Employs Python `Pillow` to compute pixel mismatches and filter anti-aliasing noise.
- **Visual Heatmap & Report**: Produces high-visibility magenta diff heatmaps and generates an interactive, dark-themed HTML report (`.visual_cache/report.html`).

### 2. `website_change_detect.py` (Lightweight HTML Text Inspector)
- **Fast Static DOM Scraping**: Fast HTTP requests via `requests`.
- **Intelligent HTML Cleaning**: Automatically removes script tags, CSS styles, hidden inputs (CSRF, state tokens), and randomized query parameter GUIDs.
- **Unified Diff Output**: Outputs standard unified line diffs when structural changes are detected.

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
Playwright requires headless Chromium browser binaries and native Linux shared libraries (such as `libnspr4`, `libnss3`, etc.) to execute screenshots on headless Linux virtual machines.

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

#### Subcommands
* `serve`: Launch the interactive Web Dashboard & REST API server (`http://localhost:8000/report.html`) enabling browser-based task execution and scan speed resource controls.
* `add`: Single or bulk add new domain(s) to a monitoring list file (e.g. `domain.txt`) with automatic URL normalization, deduplication against existing entries, and optional baseline generation (`--create-baseline` / `-b`).
* `update`: Captures target page screenshot(s) and saves them as baseline snapshots.
* `check`: Captures live screenshot(s), compares them against existing baselines, calculates visual difference percentages, and generates the HTML report.

#### Global & Subcommand Options

##### Web Dashboard Server (`serve` Subcommand)
| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--port` | Integer | `8000` | HTTP port to listen on. |
| `--host` | String | `0.0.0.0` | Host IP address to bind to (`0.0.0.0` allows network access). |
| `--no-browser` | Flag | `False` | Disables automatic browser launch upon server startup. |

##### Domain Management (`add` Subcommand)
| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--url`, `-u` | String | `None` | Single or multiple target domain(s)/URL(s) to add (repeatable). |
| `--import-file`, `-f` | Path | `None` | Path to a text file containing domains to bulk import (one per line). |
| `positional_urls` | String | `None` | Domains/URLs passed directly as positional CLI arguments (e.g. `python visual_change_detector.py add site1.com site2.com`). |
| `--target-file` | Path | `domain.txt` | Target domain list file to update (defaults to `domain.txt`). |
| `--create-baseline`, `-b` | Flag | `False` | Automatically capture baseline screenshots for newly added domains immediately upon import. |

##### Capture & Diff Engine (`update` / `check` Subcommands)

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--url` | String | `None` | Target URL to monitor. Can be specified multiple times (e.g., `--url URL1 --url URL2`). |
| `--url-file` | Path | `None` | Path to a text file containing a list of target URLs (one per line). Lines starting with `#` are ignored. |
| `-c`, `--concurrency` | Integer | `4` | Number of parallel Playwright browser worker threads. Set higher (e.g., `8` or `12`) for maximum batch scanning speed. |
| `--wait-until` | String | `load` | Navigation wait strategy (`load`, `domcontentloaded`, or `networkidle`). Defaults to `load` to prevent hanging on ad trackers. |
| `--timeout` | Integer | `30000` | Navigation timeout in milliseconds before falling back to snapshot capture. |
| `--width` | Integer | `1280` | Viewport width in pixels. |
| `--height` | Integer | `800` | Viewport height in pixels. |
| `--full-page` | Flag | `True` | Captures full scrollable height of the page. |
| `--wait-ms` | Integer | `1000` | Milliseconds to wait after page load to allow JavaScript execution & hydration. |
| `--wait-selector` | String | `None` | CSS selector to wait for before taking snapshot (e.g., `#app-loaded`). |
| `--mask` | String | `None` | CSS selector of dynamic elements to hide/mask before capture. Can be repeated (e.g., `--mask ".ad-banner" --mask "#clock"`). |
| `--threshold` | Float | `0.1` | *(Only for `check`)* Percentage threshold of visual pixel change (0.0 to 100.0) required to mark status as `Changed`. |

---

### 2. HTML Text Monitoring (`website_change_detect.py`)

#### Command Syntax
```bash
python website_change_detect.py <command> [options]
```

#### Subcommands
* `update`: Fetches HTML, applies tag cleaning, and saves baseline HTML to `.website_change_cache/`.
* `check`: Fetches live HTML, applies tag cleaning, and compares it line-by-line with the cached HTML snapshot.

#### Options

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--url` | String | `None` | Target URL to monitor. Repeatable for multiple URLs. |
| `--url-file` | Path | `None` | Path to a text file containing a list of target URLs (one per line). |

---

## 💡 Usage Examples & Common Workflows

### Workflow 1: High-Speed Bulk Batch Monitoring (Recommended)
Monitor a large batch of sites in `domain.txt` using 8 parallel worker threads and 500ms hydration delay for maximum performance:

```bash
# 1. High-speed baseline update with 8 workers
python visual_change_detector.py update --url-file domain.txt -c 8 --wait-ms 500

# 2. High-speed visual diff check with 8 workers
python visual_change_detector.py check --url-file domain.txt --threshold 1 -c 8 --wait-ms 500
```

### Workflow 2: Initialize Baseline for a Single SPA Site
Capture a baseline snapshot of `https://example.com` with a 1080p viewport, masking dynamic ad blocks and chat widgets:

```bash
python visual_change_detector.py update \
  --url https://example.com \
  --width 1920 \
  --height 1080 \
  --mask ".ad-banner" \
  --mask "#chat-widget" \
  --wait-ms 3000
```

### Workflow 3: Check Single Site for Visual Changes
Run periodic visual checks against the baseline and trigger an alert if visual diff exceeds 0.5%:

```bash
python visual_change_detector.py check \
  --url https://example.com \
  --width 1920 \
  --height 1080 \
  --mask ".ad-banner" \
  --mask "#chat-widget" \
  --threshold 0.5
```

### Workflow 4: Standard Batch Monitoring using `domain.txt`
1. Create a `domain.txt` file listing your target URLs:
   ```text
   # Production Monitoring List
   https://example.com
   https://example.org/dashboard
   https://example.net/pricing
   ```

2. Initialize baselines for all URLs in `domain.txt` (uses default 4 parallel workers):
   ```bash
   python visual_change_detector.py update --url-file domain.txt
   ```

3. Run bulk visual check:
   ```bash
   python visual_change_detector.py check --url-file domain.txt --threshold 0.1
   ```

### Workflow 5: Waiting for Specific Async Dynamic Content
If a React app requires an API call to finish before rendering content:

```bash
python visual_change_detector.py check \
  --url https://example.com/analytics \
  --wait-selector "#dashboard-charts-loaded" \
  --wait-ms 1000
```

### Workflow 6: Lightweight HTML DOM Monitoring
For fast, non-graphical HTML diffing:

```bash
# Update HTML baseline cache
python website_change_detect.py update --url https://example.com

# Check for HTML content diffs
python website_change_detect.py check --url https://example.com
```

---

## 📊 Interactive HTML Visual Report

When running `visual_change_detector.py check`, the tool automatically generates a new timestamped HTML report (e.g., `.visual_cache/report_2026-08-05_10-18-33.html`) while updating `.visual_cache/report.html` as the latest shortcut.

### Key Features of the HTML Report
* **Executive Summary Table**: Placed at the top of the page, listing all monitored URLs, status badges (`Changed`, `Unchanged`, `Failed`), visual mismatch percentages, changed pixel counts, and one-click jump buttons (`View Snapshots ↓`).
* **Interactive Column Sorting**: Click any column header (`#`, `Target URL`, `Status`, `Visual Mismatch`, `Changed Pixels`) to sort rows in ascending or descending order.
* **Instant Status Filter Chips**: Quick-filter buttons (`All`, `Changed`, `Unchanged`, `Failed`) to focus on specific test outcomes with one click.
* **Floating Smooth Scroll to Top**: A glassmorphic `↑ Top` floating button appears in the bottom right corner as you scroll down, allowing instant smooth scrolling back to the top dashboard.
* **Metric Summary Cards**: Highlights total URLs, count of changed pages, unchanged pages, and failed checks.
* **Side-by-Side Snapshot Comparison**:
  1. **Baseline Snapshot**: Original reference screenshot.
  2. **Live Snapshot**: Current screenshot captured during check.
  3. **Visual Diff Heatmap**: High-contrast dark image overlay with modified pixels highlighted in **bright magenta (`#FF006E`)**.
* **Historical Archiving**: Reports are saved with unique date-time filenames (`report_YYYY-MM-DD_HH-MM-SS.html`), allowing you to review past audit logs without overwriting previous runs.

---

## 📁 Directory Structure & Cache Files

```
website-change-monitoring/
├── visual_change_detector.py    # Multithreaded Playwright & Pillow Visual Change Detection Tool
├── website_change_detect.py     # Requests & BeautifulSoup HTML Structural Monitor
├── requirements.txt             # Python package dependencies
├── domain.txt                   # Example batch URL list file
├── README.md                    # Complete project documentation
├── read.md                      # Supplementary documentation copy
├── .visual_cache/               # Managed cache for visual detector
│   ├── baselines/               # Reference baseline screenshots (.png)
│   ├── latest/                  # Most recent screenshot captures (.png)
│   ├── diffs/                   # Visual diff heatmaps (.png)
│   └── report.html              # Interactive HTML summary report
└── .website_change_cache/       # Managed cache for HTML DOM detector
    └── <url_hash>.html          # Cached cleaned HTML snapshots
```

---

## ⏰ Automating with Cron / CI/CD

### Example Linux Cron Job (Hourly Checks)
You can schedule automated visual monitoring using Linux `cron`:

```bash
# Edit crontab
crontab -e

# Run check every hour on the hour using 4 parallel workers and write output to log file
0 * * * * cd /path/to/website-change-monitoring && ./venv/bin/python visual_change_detector.py check --url-file domain.txt -c 4 >> /var/log/website_monitor.log 2>&1
```

---

## ❓ Troubleshooting & FAQ

### 1. `playwright._impl._driver.TargetClosedError` or missing browser binary
* **Cause**: Playwright Chromium driver is not installed.
* **Fix**: Run `playwright install chromium` inside your virtual environment. On Ubuntu/Debian Linux, if missing system libraries, run `sudo playwright install-deps chromium`.

### 2. High percentage of false positives on live clocks or ads
* **Cause**: Dynamic content (timestamps, news tickers, animated banners) changing between runs.
* **Fix**: Pass CSS selectors of volatile elements using the `--mask` argument (e.g., `--mask ".timestamp" --mask ".live-ad"`).

### 3. Blank screenshots or partial rendering
* **Cause**: Slow network connection or lazy-loaded assets.
* **Fix**: Increase hydration wait time using `--wait-ms 5000` or specify an element to wait for via `--wait-selector "#main-content"`.

---

*Maintained for web infrastructure monitoring and visual regression testing.*
