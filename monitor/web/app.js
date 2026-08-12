/* app.js - WebGlancer Frontend Controller */

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

function toggleScheduleCard() {
    toggleRHCard('scheduleCard', loadScheduleConfig);
}

async function loadScheduleConfig() {
    if (!isServerConnected) return;
    try {
        const resp = await fetch('/api/schedule');
        if (resp.ok) {
            const cfg = await resp.json();
            const enableCb = document.getElementById('scheduleEnableCheckbox');
            const statusTxt = document.getElementById('scheduleStatusText');
            const freqSel = document.getElementById('scheduleFrequencySelect');
            const hourSel = document.getElementById('scheduleHourSelect');
            const minSel = document.getElementById('scheduleMinuteSelect');
            const ampmSel = document.getElementById('scheduleAmpmSelect');
            const tzSel = document.getElementById('scheduleTimezoneSelect');
            const nextTxt = document.getElementById('scheduleNextRunText');
            const countTxt = document.getElementById('scheduleCountdownText');

            if (enableCb) enableCb.checked = !!cfg.enabled;
            if (statusTxt) statusTxt.innerText = cfg.enabled ? '🟢 Active' : '⚪ Disabled';
            if (freqSel) freqSel.value = cfg.frequency || 'daily';
            if (hourSel) hourSel.value = String(cfg.hour || 9).padStart(2, '0');
            if (minSel) minSel.value = String(cfg.minute !== undefined ? cfg.minute : 0).padStart(2, '0');
            if (ampmSel) ampmSel.value = cfg.ampm || 'AM';
            if (tzSel) tzSel.value = cfg.timezone || 'UTC';
            if (nextTxt) nextTxt.innerText = cfg.next_run || 'N/A';
            if (countTxt) countTxt.innerText = cfg.countdown_display || 'N/A';

            handleFrequencyChange();
            initWheelPickers();
        }
    } catch(e) {}
}

function initWheelPickers() {
    const hourPopup = document.getElementById('hourWheelPopup');
    const minutePopup = document.getElementById('minuteWheelPopup');
    if (hourPopup && hourPopup.children.length === 0) {
        for (let h = 1; h <= 12; h++) {
            const val = String(h).padStart(2, '0');
            const item = document.createElement('div');
            item.className = 'wheel-item';
            item.innerText = val;
            item.onclick = function(e) {
                e.stopPropagation();
                document.getElementById('scheduleHourSelect').value = val;
                hourPopup.classList.add('hidden');
            };
            hourPopup.appendChild(item);
        }
    }
    if (minutePopup && minutePopup.children.length === 0) {
        for (let m = 0; m < 60; m++) {
            const val = String(m).padStart(2, '0');
            const item = document.createElement('div');
            item.className = 'wheel-item';
            item.innerText = val;
            item.onclick = function(e) {
                e.stopPropagation();
                document.getElementById('scheduleMinuteSelect').value = val;
                minutePopup.classList.add('hidden');
            };
            minutePopup.appendChild(item);
        }
    }

    document.addEventListener('click', function(e) {
        if (!e.target.closest('#hourWheelColumn')) {
            const hp = document.getElementById('hourWheelPopup');
            if (hp) hp.classList.add('hidden');
        }
        if (!e.target.closest('#minuteWheelColumn')) {
            const mp = document.getElementById('minuteWheelPopup');
            if (mp) mp.classList.add('hidden');
        }
    });
}

function toggleWheelPopup(popupId) {
    initWheelPickers();
    const popup = document.getElementById(popupId);
    if (popup) {
        const isHidden = popup.classList.contains('hidden');
        document.querySelectorAll('.wheel-popup').forEach(p => p.classList.add('hidden'));
        if (isHidden) popup.classList.remove('hidden');
    }
}

function stepHour(delta) {
    const el = document.getElementById('scheduleHourSelect');
    if (!el) return;
    let cur = parseInt(el.value || '9', 10);
    cur += delta;
    if (cur > 12) cur = 1;
    if (cur < 1) cur = 12;
    el.value = String(cur).padStart(2, '0');
}

function stepMinute(delta) {
    const el = document.getElementById('scheduleMinuteSelect');
    if (!el) return;
    let cur = parseInt(el.value || '0', 10);
    cur += delta;
    if (cur > 59) cur = 0;
    if (cur < 0) cur = 59;
    el.value = String(cur).padStart(2, '0');
}

function handleWheelScroll(event, type) {
    event.preventDefault();
    const delta = event.deltaY < 0 ? 1 : -1;
    if (type === 'hour') {
        stepHour(delta);
    } else if (type === 'minute') {
        stepMinute(delta);
    }
}

function formatWheelInput(input, min, max) {
    let val = parseInt(input.value || '0', 10);
    if (isNaN(val)) val = min;
    if (val < min) val = min;
    if (val > max) val = max;
    input.value = String(val).padStart(2, '0');
}

function handleFrequencyChange() {
    const freqSel = document.getElementById('scheduleFrequencySelect');
    const timeGrp = document.getElementById('scheduleTimeGroup');
    if (freqSel && timeGrp) {
        if (freqSel.value === 'daily') {
            timeGrp.style.display = 'flex';
        } else {
            timeGrp.style.display = 'none';
        }
    }
}

async function submitScheduleConfig() {
    if (!isServerConnected) {
        alert("The backend web server is not currently running.\n\nTo manage schedules from this dashboard, start the server in your terminal:\n\npython visual_change_detector.py serve");
        return;
    }

    const enabled = document.getElementById('scheduleEnableCheckbox')?.checked || false;
    const frequency = document.getElementById('scheduleFrequencySelect')?.value || 'daily';
    const hour = parseInt(document.getElementById('scheduleHourSelect')?.value || '9', 10);
    const minute = parseInt(document.getElementById('scheduleMinuteSelect')?.value || '0', 10);
    const ampm = document.getElementById('scheduleAmpmSelect')?.value || 'AM';
    const timezone = document.getElementById('scheduleTimezoneSelect')?.value || 'UTC';
    const speedSelect = document.getElementById('speedSelect');
    const speed = speedSelect ? speedSelect.value : 'low';

    const btnSave = document.getElementById('btn-save-schedule');
    if (btnSave) btnSave.disabled = true;

    try {
        const resp = await fetch('/api/schedule', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                enabled: enabled,
                frequency: frequency,
                hour: hour,
                minute: minute,
                ampm: ampm,
                timezone: timezone,
                speed: speed
            })
        });

        const res = await resp.json();
        if (res.success) {
            alert(`✅ Schedule ${enabled ? 'Enabled' : 'Disabled'} and saved successfully!\n\nNext Run: ${res.schedule.next_run}`);
            loadScheduleConfig();
        } else {
            alert('Failed to save schedule configuration.');
        }
    } catch(e) {
        alert('Error connecting to server to save schedule.');
    } finally {
        if (btnSave) btnSave.disabled = false;
    }
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
                    <span style="font-weight:800; font-size:1rem; color:#1c1917;">🗓️ ${r.formatted_date}</span>
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
            loadScheduleConfig();
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

// Automatically check server status & background tasks every 3 seconds
if (typeof window !== 'undefined') {
    setInterval(checkServerStatus, 3000);
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
                <td style="color:var(--text-muted); font-weight:700;">#${item._originalIndex}</td>
                <td style="font-weight:700;"><a href="${item.url}" target="_blank" style="color:var(--text-primary); text-decoration:none;">${item.url}</a></td>
                <td><span class="badge badge-${stClass}">${item.status}</span></td>
                <td style="font-weight:800; color:${item.percentage > 0 ? 'var(--accent-changed)' : 'var(--text-primary)'};">${pctDisplay}</td>
                <td style="color:var(--text-muted); font-weight:600;">${pxDisplay}</td>
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
                        <a href="${item.url}" target="_blank" style="font-size:1.1rem; font-weight:800; color:#1c1917; text-decoration:none;">${item.url}</a>
                        <span style="font-size:0.85rem; color:var(--text-muted);">| Diff: <strong style="color:#1c1917;">${pctDisplay}</strong> (${pxDisplay} px changed)</span>
                        ${item.baseline_last_updated ? `<span style="font-size:0.8rem; color:#6b21a8; background:#e9d5ff; padding:0.2rem 0.6rem; border-radius:12px; border:1px solid #c084fc; font-weight:700;">🗓️ Baseline: ${item.baseline_last_updated}</span>` : ''}
                    </div>
                    <div class="domain-action-buttons">
                        <button class="btn-domain-action btn-domain-update" onclick="triggerSingleDomainTask('update', '${safeUrl}')" title="Update baseline screenshot for this site">📸 Baseline</button>
                        <button class="btn-domain-action btn-domain-check" onclick="triggerSingleDomainTask('check', '${safeUrl}')" title="Run live visual check for this site">🔍 Check</button>
                        <button class="btn-domain-action btn-domain-remove" onclick="confirmAndRemoveDomain('${safeUrl}')" title="Remove domain from target list and purge cache">🗑️ Remove Domain</button>
                    </div>
                </div>
                ${item.error ? `<div style="padding:1.5rem; color:var(--accent-failed); background:#fffbeb; font-weight:600;">⚠️ Error: ${item.error}</div>` : `
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
