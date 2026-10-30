/* app.js - WebGlancer Frontend Controller */

let isServerConnected = false;
let pollingInterval = null;
let lastKnownState = null;

// Executive Table Sorting & Filtering State
let currentSortColumn = 'index';
let currentSortDirection = 'asc';
let currentStatusFilter = 'ALL';
let currentReportData = [];

const ALL_EXPANDABLE_CARDS = ['addDomainCard', 'scheduleCard', 'historyCard', 'periodicReportsCard'];

function toggleRHCard(cardId, onShowCallback) {
    const targetCard = typeof cardId === 'string' ? document.getElementById(cardId) : cardId;
    if (!targetCard) return;

    const willOpen = targetCard.classList.contains('hidden');

    // Close all other expandable cards so each view is cleanly separated
    ALL_EXPANDABLE_CARDS.forEach(id => {
        const c = document.getElementById(id);
        if (c && c !== targetCard) {
            c.classList.add('hidden');
        }
    });

    if (willOpen) {
        targetCard.classList.remove('hidden');
        if (typeof onShowCallback === 'function') {
            onShowCallback();
        }
        targetCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } else {
        targetCard.classList.add('hidden');
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

            if (enableCb) enableCb.checked = !!cfg.enabled;
            if (statusTxt) statusTxt.innerText = cfg.enabled ? '🟢 Active' : '⚪ Disabled';
            if (freqSel) freqSel.value = cfg.frequency || 'daily';
            if (hourSel) hourSel.value = String(cfg.hour || 9).padStart(2, '0');
            if (minSel) minSel.value = String(cfg.minute !== undefined ? cfg.minute : 0).padStart(2, '0');
            if (ampmSel) ampmSel.value = cfg.ampm || 'AM';
            if (tzSel) tzSel.value = cfg.timezone || 'UTC';
            if (nextTxt) nextTxt.innerText = cfg.next_run || 'N/A';

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

    // Compute top 3 domains by highest changed pixels globally (only changed domains with > 0 changed pixels)
    const top3PixelUrls = new Set(
        (window.initialReportData || [])
            .filter(item => item.status === 'Changed' && (Number(item.changed_pixels) || 0) > 0)
            .sort((a, b) => (Number(b.changed_pixels) || 0) - (Number(a.changed_pixels) || 0))
            .slice(0, 3)
            .map(item => item.url)
    );

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

        const isHighMismatch = (Number(item.percentage) || 0) > 50.0 && item.status !== 'Failed';
        const isTop3Pixels = top3PixelUrls.has(item.url);
        const shouldHighlight = isHighMismatch || isTop3Pixels;
        const hlClass = shouldHighlight ? ' domain-hl-red' : '';
        let hlTitle = '';
        if (isHighMismatch && isTop3Pixels) {
            hlTitle = 'Visual mismatch > 50% & Top 3 changed pixels';
        } else if (isHighMismatch) {
            hlTitle = 'Visual mismatch > 50%';
        } else if (isTop3Pixels) {
            hlTitle = 'Top 3 by changed pixels';
        }

        return `
            <tr>
                <td style="color:var(--text-muted); font-weight:700;">#${item._originalIndex}</td>
                <td style="font-weight:700;"><a href="${item.url}" target="_blank" class="domain-link${hlClass}" ${hlTitle ? `title="${hlTitle}"` : ''}>${item.url}</a></td>
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

    // Compute top 3 domains by highest changed pixels globally
    const top3PixelUrls = new Set(
        (window.initialReportData || [])
            .filter(item => item.status === 'Changed' && (Number(item.changed_pixels) || 0) > 0)
            .sort((a, b) => (Number(b.changed_pixels) || 0) - (Number(a.changed_pixels) || 0))
            .slice(0, 3)
            .map(item => item.url)
    );

    app.innerHTML = window.initialReportData.map(item => {
        const stClass = (item.status || '').toLowerCase();
        const pctDisplay = item.status === 'Failed' ? 'N/A' : `${Number(item.percentage || 0).toFixed(2)}%`;
        const pxDisplay = item.status === 'Failed' ? 'N/A' : Number(item.changed_pixels || 0).toLocaleString();
        const safeUrl = (item.url || '').replace(/'/g, "\\'");

        const isHighMismatch = (Number(item.percentage) || 0) > 50.0 && item.status !== 'Failed';
        const isTop3Pixels = top3PixelUrls.has(item.url);
        const shouldHighlight = isHighMismatch || isTop3Pixels;
        const hlClass = shouldHighlight ? ' domain-hl-red' : '';
        let hlTitle = '';
        if (isHighMismatch && isTop3Pixels) {
            hlTitle = 'Visual mismatch > 50% & Top 3 changed pixels';
        } else if (isHighMismatch) {
            hlTitle = 'Visual mismatch > 50%';
        } else if (isTop3Pixels) {
            hlTitle = 'Top 3 by changed pixels';
        }

        return `
            <div id="block-${item._slug}" class="url-block">
                <div class="url-header">
                    <div class="url-title-wrapper">
                        <span class="badge badge-${stClass}">${item.status}</span>
                        <a href="${item.url}" target="_blank" class="domain-link${hlClass}" style="font-size:1.1rem; font-weight:800; text-decoration:none;" ${hlTitle ? `title="${hlTitle}"` : ''}>${item.url}</a>
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

// Logout Handler
async function handleLogout() {
    try {
        await fetch('/api/logout', { method: 'POST' });
    } catch(e) {}
    window.location.href = '/login.html';
}

// Periodic Reports Controller (Daily / Weekly / Monthly / Custom)
let currentPeriodicPreset = 'weekly';
let currentPeriodicReportData = null;

function togglePeriodicReportsCard() {
    toggleRHCard('periodicReportsCard', onPeriodicReportsShow);
}

function onPeriodicReportsShow() {
    initPeriodicDates();
    generatePeriodicReport();
}

function formatDateISO(d) {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function initPeriodicDates() {
    const startInput = document.getElementById('reportStartDate');
    const endInput = document.getElementById('reportEndDate');
    if (!startInput || !endInput) return;

    if (!startInput.value || !endInput.value) {
        setPeriodicPreset('weekly');
    }
}

function setPeriodicPreset(preset, btnEl) {
    currentPeriodicPreset = preset;
    document.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('active'));
    if (btnEl) {
        btnEl.classList.add('active');
    } else {
        const chips = document.querySelectorAll('.preset-chip');
        chips.forEach(c => {
            if (c.innerText.toLowerCase().includes(preset)) c.classList.add('active');
        });
    }

    const today = new Date();
    const startInput = document.getElementById('reportStartDate');
    const endInput = document.getElementById('reportEndDate');
    if (!startInput || !endInput) return;

    if (preset === 'daily') {
        startInput.value = formatDateISO(today);
        endInput.value = formatDateISO(today);
    } else if (preset === 'weekly') {
        const past = new Date();
        past.setDate(today.getDate() - 6);
        startInput.value = formatDateISO(past);
        endInput.value = formatDateISO(today);
    } else if (preset === 'monthly') {
        const past = new Date();
        past.setDate(today.getDate() - 29);
        startInput.value = formatDateISO(past);
        endInput.value = formatDateISO(today);
    }

    if (btnEl) {
        generatePeriodicReport();
    }
}

function handleCustomDateChange() {
    currentPeriodicPreset = 'custom';
    document.querySelectorAll('.preset-chip').forEach(c => c.classList.remove('active'));
    const chips = document.querySelectorAll('.preset-chip');
    chips.forEach(c => {
        if (c.innerText.toLowerCase().includes('custom')) c.classList.add('active');
    });
}

async function generatePeriodicReport() {
    if (!isServerConnected) {
        alert("The backend web server is not currently running.\n\nPlease start the server to generate periodic reports:\n\npython visual_change_detector.py serve");
        return;
    }

    const startInput = document.getElementById('reportStartDate');
    const endInput = document.getElementById('reportEndDate');
    const tbody = document.getElementById('periodicReportTableBody');
    const kpiGrid = document.getElementById('periodicKpiCards');
    const runBtn = document.getElementById('btn-run-periodic-report');

    const startVal = startInput?.value || '';
    const endVal = endInput?.value || '';

    if (tbody) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:2rem; color:var(--text-muted);"><span class="spinner" style="border-top-color:#0284c7; width:20px; height:20px; display:inline-block; vertical-align:middle; margin-right:8px;"></span> Loading historical report data across all domains...</td></tr>';
    }
    if (runBtn) runBtn.disabled = true;

    try {
        const url = `/api/reports/generate?period=${encodeURIComponent(currentPeriodicPreset)}&start_date=${encodeURIComponent(startVal)}&end_date=${encodeURIComponent(endVal)}`;
        const resp = await fetch(url);
        if (!resp.ok) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:1.5rem; color:#dc2626; font-weight:700;">⚠️ Failed to generate periodic report from server.</td></tr>';
            return;
        }

        const data = await resp.json();
        currentPeriodicReportData = data;
        renderPeriodicReportInfoBar(data);
        renderPeriodicReportTable(data);
    } catch (e) {
        if (tbody) tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding:1.5rem; color:#dc2626; font-weight:700;">⚠️ Error communicating with server: ${e.message}</td></tr>`;
    } finally {
        if (runBtn) runBtn.disabled = false;
    }
}

function formatShortDate(dateStr) {
    if (!dateStr) return '';
    const parts = dateStr.split('-');
    if (parts.length === 3) {
        const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        const mIdx = parseInt(parts[1], 10) - 1;
        return `${parts[2]}-${monthNames[mIdx] || parts[1]}`;
    }
    return dateStr;
}

function renderPeriodicReportInfoBar(data) {
    const infoBar = document.getElementById('periodicReportInfoBar');
    if (!infoBar) return;

    infoBar.innerHTML = `
        <div class="info-badge"><strong>Reporting Period:</strong> ${data.start_date} to ${data.end_date} (${data.total_days} days)</div>
        <div class="info-badge"><strong>Monitored Domains:</strong> ${data.total_domains}</div>
        <div class="info-badge"><strong>Dates with Data:</strong> ${data.dates_with_data_count} / ${data.total_days} days</div>
        <div class="info-badge"><strong>Retention:</strong> Rolling 60 Days JSON</div>
    `;
}

function renderPeriodicReportTable(data) {
    const thead = document.getElementById('periodicReportTableHeader');
    const tbody = document.getElementById('periodicReportTableBody');
    if (!tbody) return;

    const dates = data.dates_in_period || [];
    const items = data.domain_matrix || [];

    // Dynamically render header with #, Target Domain / URL, followed by each Date column
    if (thead) {
        thead.innerHTML = `
            <tr>
                <th style="width: 50px; text-align: center;">#</th>
                <th style="min-width: 250px;">Target Domain / URL</th>
                ${dates.map(d => `<th style="text-align: center; min-width: 90px;" title="${d}">${formatShortDate(d)}</th>`).join('')}
            </tr>
        `;
    }

    if (items.length === 0) {
        tbody.innerHTML = `<tr><td colspan="${dates.length + 2}" style="text-align:center; padding:1.5rem; color:var(--text-muted);">No domains found in monitoring list.</td></tr>`;
        return;
    }

    tbody.innerHTML = items.map(item => {
        const timelineMap = {};
        (item.timeline || []).forEach(t => {
            timelineMap[t.date] = t;
        });

        const dailyCells = dates.map(d => {
            const t = timelineMap[d];
            if (t && t.has_data) {
                if (t.status === 'Failed') {
                    return `<td style="text-align:center;"><span class="matrix-pct-failed" title="${d}: Scan Failed">Failed</span></td>`;
                }
                const pct = typeof t.percentage === 'number' ? t.percentage : 0;
                const px = t.changed_pixels ? t.changed_pixels.toLocaleString() : '0';
                if (pct > 0.1 || t.status === 'Changed') {
                    return `<td style="text-align:center;"><span class="matrix-pct-changed" title="${d}: ${pct.toFixed(2)}% changed (${px} px)">${pct.toFixed(2)}%</span></td>`;
                } else {
                    return `<td style="text-align:center;"><span class="matrix-pct-unchanged" title="${d}: 0.00% (Unchanged)">0.00%</span></td>`;
                }
            } else {
                return `<td style="text-align:center; color:#94a3b8;" title="${d}: No scan data for this date">—</td>`;
            }
        }).join('');

        return `
            <tr>
                <td style="color:var(--text-muted); font-weight:700; text-align:center;">#${item.index}</td>
                <td style="font-weight:700;">
                    <a href="${item.url}" target="_blank" style="color:var(--text-primary); text-decoration:none;">${item.url}</a>
                    ${item.baseline_last_updated ? `<div style="font-size:0.75rem; color:var(--text-muted); font-weight:500;">Baseline: ${item.baseline_last_updated}</div>` : ''}
                </td>
                ${dailyCells}
            </tr>
        `;
    }).join('');
}

function downloadPeriodicReport(format) {
    if (!currentPeriodicReportData || !currentPeriodicReportData.domain_matrix) {
        if (!isServerConnected) {
            alert("The backend web server is not running.");
            return;
        }
        const startInput = document.getElementById('reportStartDate');
        const endInput = document.getElementById('reportEndDate');
        const s = startInput?.value || '';
        const e = endInput?.value || '';
        const url = `/api/reports/export?format=${encodeURIComponent(format)}&period=${encodeURIComponent(currentPeriodicPreset)}&start_date=${encodeURIComponent(s)}&end_date=${encodeURIComponent(e)}`;
        window.open(url, '_blank');
        return;
    }

    const data = currentPeriodicReportData;
    const period = currentPeriodicPreset || 'report';
    const filename = `webglancer_report_${period}_${data.start_date}_to_${data.end_date}.${format}`;

    if (format === 'csv') {
        const dates = data.dates_in_period || [];
        const dateHeaders = dates.map(d => formatShortDate(d).toUpperCase());
        const headers = ["#", "TARGET DOMAIN / URL", ...dateHeaders];

        const rows = [headers.map(h => `"${h.replace(/"/g, '""')}"`).join(',')];

        (data.domain_matrix || []).forEach(item => {
            const timelineMap = {};
            (item.timeline || []).forEach(t => { timelineMap[t.date] = t; });

            const dailyValues = dates.map(d => {
                const t = timelineMap[d];
                if (t && t.has_data) {
                    if (t.status === 'Failed') return "Failed";
                    const pct = typeof t.percentage === 'number' ? t.percentage : 0;
                    return `${pct.toFixed(2)}%`;
                }
                return "—";
            });

            const rowData = [
                `"#${item.index}"`,
                `"${(item.url || '').replace(/"/g, '""')}"`,
                ...dailyValues.map(v => `"${v}"`)
            ];
            rows.push(rowData.join(','));
        });

        const csvContent = "\uFEFF" + rows.join('\r\n');
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(link.href);
    } else {
        const jsonContent = JSON.stringify(data, null, 2);
        const blob = new Blob([jsonContent], { type: 'application/json;charset=utf-8;' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(link.href);
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

