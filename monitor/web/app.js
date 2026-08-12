/* app.js - Visual Change Monitoring Suite Frontend Controller */

let isServerConnected = false;
let pollingInterval = null;
let lastKnownState = null;

// Executive Table Sorting & Filtering State
let currentSortColumn = 'index';
let currentSortDirection = 'asc';
let currentStatusFilter = 'ALL';
let currentReportData = [];

function toggleRHCard(cardId, onShowCallback) {
    const card = typeof cardId === 'string' ? document.getElementById(cardId) : cardId;
    if (card) {
        card.classList.toggle('hidden');
        if (!card.classList.contains('hidden') && typeof onShowCallback === 'function') {
            onShowCallback();
        }
    }
}

function toggleHistoryCard() {
    toggleRHCard('historyCard', loadHistoryReports);
}

async function loadHistoryReports() {
    let reports = window.initialHistoryData || [];
    if (isServerConnected) {
        try {
            const resp = await fetch('/api/history');
            if (resp.ok) {
                const data = await resp.json();
                if (data.reports) reports = data.reports;
            }
        } catch(e) {}
    }
    renderHistoryGrid(reports);
}

function renderHistoryGrid(reports) {
    const grid = document.getElementById('historyGrid');
    if (!grid) return;
    if (!reports || reports.length === 0) {
        grid.innerHTML = '<p style="color:var(--text-muted); font-size:0.9rem;">No historical reports found in retention window.</p>';
        return;
    }
    grid.innerHTML = reports.map(r => `
        <div class="history-item-card ${r.is_today ? 'is-today' : ''}">
            <div>
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.4rem;">
                    <span style="font-weight:700; font-size:1rem; color:#fff;">🗓️ ${r.formatted_date}</span>
                    <span class="history-card-badge ${r.is_today ? 'badge-today' : 'badge-archive'}">${r.is_today ? 'Today' : 'Archive'}</span>
                </div>
                <div style="font-size:0.8rem; color:var(--text-muted); margin-top:0.3rem;">
                    📄 <code>${r.filename}</code><br>
                    🕒 Last updated: ${r.mod_time} (${r.size_kb} KB)
                </div>
            </div>
            <a href="${r.filename}" class="btn-view-report" target="_blank">
                👁️ View Report
            </a>
        </div>
    `).join('');
}

function toggleAddDomainCard() {
    toggleRHCard('addDomainCard');
}

async function submitAddDomains() {
    const textarea = document.getElementById('newDomainsTextarea');
    const autoBaseline = document.getElementById('autoBaselineCheckbox')?.checked || false;
    const speedSelect = document.getElementById('speedSelect');
    const speed = speedSelect ? speedSelect.value : 'low';
    
    if (!textarea || !textarea.value.trim()) {
        alert('Please enter at least one URL/domain to add.');
        return;
    }

    if (!isServerConnected) {
        alert("The backend web server is not currently running.\n\nTo add domains from this dashboard, start the server in your terminal:\n\npython visual_change_detector.py serve");
        return;
    }

    const rawUrls = textarea.value.split('\n').map(s => s.trim()).filter(Boolean);
    const btnSubmit = document.getElementById('btn-submit-add-domain');
    if (btnSubmit) btnSubmit.disabled = true;

    try {
        const resp = await fetch('/api/add-domain', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ urls: rawUrls, create_baseline: autoBaseline, speed: speed })
        });
        const res = await resp.json();
        if (res.success) {
            alert(`✅ Added ${res.added.length} new domain(s)!` + (res.duplicates.length ? `\n(Skipped ${res.duplicates.length} duplicate(s))` : ''));
            textarea.value = '';
            toggleAddDomainCard();
            if (autoBaseline && res.added.length > 0) {
                startPolling();
            } else {
                window.location.reload();
            }
        } else {
            alert(res.message || 'Failed to add domains.');
        }
    } catch(e) {
        alert('Error connecting to server to add domains.');
    } finally {
        if (btnSubmit) btnSubmit.disabled = false;
    }
}

async function confirmAndRemoveDomain(url) {
    if (!url) return;
    if (!confirm(`Are you sure you want to remove "${url}" from the target list?\n\nThis will purge its baseline screenshot, latest check screenshot, and visual diff files.`)) {
        return;
    }
    
    if (!isServerConnected) {
        alert("The backend web server is not currently running.\n\nTo remove domains from this dashboard, start the server in your terminal:\n\npython visual_change_detector.py serve");
        return;
    }

    try {
        const resp = await fetch('/api/remove-domain', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        });
        const res = await resp.json();
        if (res.success) {
            alert(`🗑️ Removed ${url} and cleaned cache files.`);
            window.location.reload();
        } else {
            alert(res.message || 'Failed to remove domain.');
        }
    } catch(e) {
        alert('Error communicating with server to remove domain.');
    }
}

async function checkServerStatus() {
    const badge = document.getElementById('serverStatusBadge');
    try {
        const resp = await fetch('/api/status');
        if (resp.ok) {
            isServerConnected = true;
            if (badge) {
                badge.className = 'server-badge online';
                badge.innerHTML = '🟢 REST API Server Online';
            }
            const data = await resp.json();
            if (data.is_running) {
                startPolling();
            }
            return true;
        }
    } catch(e) {}
    isServerConnected = false;
    if (badge) {
        badge.className = 'server-badge offline';
        badge.innerHTML = '⚪ Server Offline (CLI Mode)';
    }
    return false;
}

async function triggerTask(action) {
    if (!isServerConnected) {
        alert("The backend web server is not currently running.\n\nTo control scans from this dashboard, start the server in your terminal:\n\npython visual_change_detector.py serve");
        return;
    }

    const speedSelect = document.getElementById('speedSelect');
    const speed = speedSelect ? speedSelect.value : 'low';

    try {
        const resp = await fetch('/api/start-scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: action, speed: speed })
        });

        const data = await resp.json();
        if (data.success) {
            startPolling();
        } else {
            alert(data.message || 'Task could not be started.');
        }
    } catch(e) {
        alert('Error connecting to server.');
    }
}

async function triggerSingleDomainTask(action, url) {
    if (!url) return;
    if (!isServerConnected) {
        alert("The backend web server is not currently running.\n\nTo control single-domain scans from this dashboard, start the server in your terminal:\n\npython visual_change_detector.py serve");
        return;
    }

    const speedSelect = document.getElementById('speedSelect');
    const speed = speedSelect ? speedSelect.value : 'low';

    try {
        const resp = await fetch('/api/start-scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: action, speed: speed, custom_urls: [url] })
        });

        const data = await resp.json();
        if (data.success) {
            startPolling();
        } else {
            alert(data.message || 'Single-domain task could not be started.');
        }
    } catch(e) {
        alert('Error connecting to server for single-domain action.');
    }
}

function startPolling() {
    if (pollingInterval) return;
    updateProgressUI();
    pollingInterval = setInterval(updateProgressUI, 1000);
}

function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

async function updateProgressUI() {
    const banner = document.getElementById('progressContainer');
    const titleEl = document.getElementById('progressTaskTitle');
    const speedEl = document.getElementById('progressSpeedBadge');
    const fillEl = document.getElementById('progressBarFill');
    const textEl = document.getElementById('progressPercentageText');
    const activeUrlEl = document.getElementById('progressActiveUrl');
    const logBoxEl = document.getElementById('progressLogBox');
    const btnUpdate = document.getElementById('btn-update-baseline');
    const btnCheck = document.getElementById('btn-live-check');

    try {
        const resp = await fetch('/api/status');
        if (!resp.ok) {
            stopPolling();
            if (banner) banner.classList.add('hidden');
            return;
        }

        const state = await resp.json();
        lastKnownState = state;

        if (state.is_running) {
            if (banner) banner.classList.remove('hidden');
            if (btnUpdate) btnUpdate.disabled = true;
            if (btnCheck) btnCheck.disabled = true;

            const actionLabel = state.action === 'update' ? '📸 Updating Baselines...' : '🔍 Running Live Visual Check...';
            if (titleEl) titleEl.innerText = actionLabel;
            
            const speedNames = { low: 'Low Resource (1 Worker)', medium: 'Medium Speed (4 Workers)', high: 'High Speed (8 Workers)' };
            if (speedEl) speedEl.innerText = speedNames[state.speed] || `${state.speed} (${state.concurrency} Workers)`;

            const pct = state.percentage || 0;
            if (fillEl) fillEl.style.width = `${pct}%`;
            if (textEl) textEl.innerText = `${pct}% Completed (${state.completed_urls}/${state.total_urls})`;
            if (activeUrlEl) activeUrlEl.innerText = state.current_url ? `Scanning: ${state.current_url}` : 'Processing...';

            if (logBoxEl && state.logs) {
                logBoxEl.innerHTML = state.logs.map(l => `<div>[${l.timestamp}] <strong>[${l.status}]</strong> ${l.msg}</div>`).join('');
                logBoxEl.scrollTop = logBoxEl.scrollHeight;
            }
        } else {
            stopPolling();
            if (banner) banner.classList.add('hidden');
            if (btnUpdate) btnUpdate.disabled = false;
            if (btnCheck) btnCheck.disabled = false;

            if (state.status_message && state.status_message.includes('completed')) {
                window.location.reload();
            }
        }
    } catch(e) {
        stopPolling();
        if (banner) banner.classList.add('hidden');
    }
}

// Executive Summary Table Sorting & Filtering Logic
function setStatusFilter(status, chipElement) {
    currentStatusFilter = status;
    document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
    if (chipElement) chipElement.classList.add('active');
    renderSummaryTable();
}

function handleSort(column) {
    if (currentSortColumn === column) {
        currentSortDirection = currentSortDirection === 'asc' ? 'desc' : 'asc';
    } else {
        currentSortColumn = column;
        currentSortDirection = (column === 'percentage' || column === 'changed_pixels') ? 'desc' : 'asc';
    }
    renderSummaryTable();
}

function updateSortIcons() {
    ['index', 'url', 'status', 'percentage', 'changed_pixels'].forEach(col => {
        const th = document.getElementById(`th-${col}`);
        const icon = document.getElementById(`sort-icon-${col}`);
        if (th && icon) {
            if (col === currentSortColumn) {
                th.classList.add('active');
                icon.innerText = currentSortDirection === 'asc' ? '▲' : '▼';
            } else {
                th.classList.remove('active');
                icon.innerText = '↕';
            }
        }
    });
}

function renderSummaryTable() {
    if (!window.initialReportData) return;
    const tbody = document.getElementById('summaryTableBody');
    if (!tbody) return;

    let items = [...window.initialReportData];

    if (currentStatusFilter !== 'ALL') {
        items = items.filter(item => (item.status || '').toUpperCase() === currentStatusFilter);
    }

    items.sort((a, b) => {
        let valA = a[currentSortColumn];
        let valB = b[currentSortColumn];

        if (currentSortColumn === 'index') {
            valA = a._originalIndex;
            valB = b._originalIndex;
        } else if (currentSortColumn === 'url' || currentSortColumn === 'status') {
            valA = (valA || '').toString().toLowerCase();
            valB = (valB || '').toString().toLowerCase();
        } else {
            valA = Number(valA) || 0;
            valB = Number(valB) || 0;
        }

        if (valA < valB) return currentSortDirection === 'asc' ? -1 : 1;
        if (valA > valB) return currentSortDirection === 'asc' ? 1 : -1;
        return 0;
    });

    updateSortIcons();

    if (items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding:1.5rem;">No sites match the selected status filter (${currentStatusFilter}).</td></tr>`;
        return;
    }

    tbody.innerHTML = items.map(item => {
        const stClass = (item.status || '').toLowerCase();
        const pctDisplay = item.status === 'Failed' ? 'N/A' : `${Number(item.percentage || 0).toFixed(2)}%`;
        const pxDisplay = item.status === 'Failed' ? 'N/A' : Number(item.changed_pixels || 0).toLocaleString();
        const safeUrl = (item.url || '').replace(/'/g, "\\'");

        return `
            <tr>
                <td style="color:var(--text-muted); font-weight:600;">#${item._originalIndex}</td>
                <td style="font-weight:600;"><a href="${item.url}" target="_blank" style="color:var(--text-primary); text-decoration:none;">${item.url}</a></td>
                <td><span class="badge badge-${stClass}">${item.status}</span></td>
                <td style="font-weight:700; color:${item.percentage > 0 ? 'var(--accent-changed)' : 'var(--text-primary)'};">${pctDisplay}</td>
                <td style="color:var(--text-muted);">${pxDisplay}</td>
                <td>
                    <div class="table-action-cell">
                        <button class="btn-sm-action btn-sm-update" onclick="triggerSingleDomainTask('update', '${safeUrl}')" title="Update baseline screenshot for this site">📸 Baseline</button>
                        <button class="btn-sm-action btn-sm-check" onclick="triggerSingleDomainTask('check', '${safeUrl}')" title="Run visual check for this site">🔍 Check</button>
                        <button class="btn-sm-action btn-sm-remove" onclick="confirmAndRemoveDomain('${safeUrl}')" title="Remove domain from target list and clean cache">🗑️ Remove</button>
                        <a href="#block-${item._slug}" class="btn-jump">👁️ View Screenshots</a>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

// Render Snapshot Visual Blocks
function renderSnapshotBlocks() {
    const app = document.getElementById('app');
    if (!app || !window.initialReportData) return;

    app.innerHTML = window.initialReportData.map(item => {
        const stClass = (item.status || '').toLowerCase();
        const pctDisplay = item.status === 'Failed' ? 'N/A' : `${Number(item.percentage || 0).toFixed(2)}%`;
        const pxDisplay = item.status === 'Failed' ? 'N/A' : Number(item.changed_pixels || 0).toLocaleString();
        const safeUrl = (item.url || '').replace(/'/g, "\\'");

        return `
            <div id="block-${item._slug}" class="url-block">
                <div class="url-header">
                    <div class="url-title-wrapper">
                        <span class="badge badge-${stClass}">${item.status}</span>
                        <a href="${item.url}" target="_blank" style="font-size:1.1rem; font-weight:700; color:#fff; text-decoration:none;">${item.url}</a>
                        <span style="font-size:0.85rem; color:var(--text-muted);">| Diff: <strong style="color:#fff;">${pctDisplay}</strong> (${pxDisplay} px changed)</span>
                        ${item.baseline_last_updated ? `<span style="font-size:0.8rem; color:var(--accent-blue); background:rgba(56,189,248,0.1); padding:0.2rem 0.6rem; border-radius:12px; border:1px solid rgba(56,189,248,0.3);">🗓️ Baseline: ${item.baseline_last_updated}</span>` : ''}
                    </div>
                    <div class="domain-action-buttons">
                        <button class="btn-domain-action btn-domain-update" onclick="triggerSingleDomainTask('update', '${safeUrl}')" title="Update baseline screenshot for this site">📸 Baseline</button>
                        <button class="btn-domain-action btn-domain-check" onclick="triggerSingleDomainTask('check', '${safeUrl}')" title="Run live visual check for this site">🔍 Check</button>
                        <button class="btn-domain-action btn-domain-remove" onclick="confirmAndRemoveDomain('${safeUrl}')" title="Remove domain from target list and purge cache">🗑️ Remove Domain</button>
                    </div>
                </div>
                ${item.error ? `<div style="padding:1.5rem; color:var(--accent-failed); background:rgba(234, 179, 8, 0.05); font-weight:600;">⚠️ Error: ${item.error}</div>` : `
                    <div class="image-grid">
                        <div class="img-container">
                            <div class="img-title">Reference Baseline</div>
                            <a href="${item.baseline_rel}" target="_blank"><img src="${item.baseline_rel}" alt="Baseline" loading="lazy"></a>
                        </div>
                        <div class="img-container">
                            <div class="img-title">Live Captured Screenshot</div>
                            <a href="${item.latest_rel}" target="_blank"><img src="${item.latest_rel}" alt="Latest" loading="lazy"></a>
                        </div>
                        <div class="img-container">
                            <div class="img-title">Visual Diff Heatmap (Magenta)</div>
                            <a href="${item.diff_rel}" target="_blank"><img src="${item.diff_rel}" alt="Diff Heatmap" loading="lazy"></a>
                        </div>
                    </div>
                `}
            </div>
        `;
    }).join('');
}

// Scroll to Top Floating Button Functionality
function scrollToTop() {
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function handleScrollTopButtonVisibility() {
    const btn = document.getElementById('scrollToTopBtn');
    if (!btn) return;
    if (window.scrollY > 300) {
        btn.classList.add('visible');
    } else {
        btn.classList.remove('visible');
    }
}

// Initialization on DOM Content Loaded
document.addEventListener('DOMContentLoaded', () => {
    checkServerStatus();
    renderSummaryTable();
    renderSnapshotBlocks();
    window.addEventListener('scroll', handleScrollTopButtonVisibility);

    // Auto-bind click events for elements with class 'button-rh' and 'data-rh-target'
    document.querySelectorAll('.button-rh[data-rh-target]').forEach(btn => {
        const targetId = btn.getAttribute('data-rh-target');
        if (targetId && !btn.hasAttribute('onclick')) {
            btn.addEventListener('click', () => toggleRHCard(targetId));
        }
    });
});
