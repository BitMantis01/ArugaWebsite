/* ============================================================
   ARUGA — Dashboard JavaScript
   Tab switching, charts, live polling, notifications
   ============================================================ */

// Chart color palette (pink theme)
const PINK_500 = '#f4a4b5';
const PINK_300 = '#f9a8d4';
const PINK_100 = '#fce7f2';
const BLUE_500 = '#3b82f6';
const AMBER_500 = '#f59e0b';
const GREEN_500 = '#10b981';
const GRAY_400 = '#9ca3af';

// Active chart instances (destroy before re-creating)
const charts = {};

// Feed polling state (declared early — referenced by IIFE restoreTabFromHash)
let feedLastSec = 0;
let feedImageCache = {};
let feedSocket = null;
let feedHttpTimer = null;

function destroyChart(key) {
    if (charts[key]) { charts[key].destroy(); delete charts[key]; }
}

// ─── Tab Switching (with hash routing) ──────────────────────
function switchToTab(tabName) {
    document.querySelectorAll('.sidebar .tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));

    const btn = document.querySelector(`.sidebar .tab-btn[data-tab="${tabName}"]`);
    if (btn) btn.classList.add('active');

    const panel = document.getElementById('tab-' + tabName);
    if (panel) panel.classList.add('active');

    // Update URL hash without triggering scroll/reload
    if (location.hash !== '#' + tabName) {
        history.replaceState(null, '', '#' + tabName);
    }

    // Initialize/resume content for the active tab
    if (tabName === 'vitals') initVitalsCharts();
    if (tabName === 'prediction') initPredictionCharts();
    if (tabName === 'live-feed') startFeedPolling();
}

document.querySelectorAll('.sidebar .tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchToTab(btn.dataset.tab));
});

// On page load, restore tab from URL hash
(function restoreTabFromHash() {
    const hash = location.hash.replace('#', '');
    const validTabs = ['summary', 'live-feed', 'vitals', 'prediction', 'notifications', 'profile', 'debug'];
    if (hash && validTabs.includes(hash)) {
        switchToTab(hash);
    }
})();

// ─── Common Chart Config ─────────────────────────────────────
function gmt8Time(isoStr) {
    if (!isoStr) return '--:--:--';
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return '--:--:--';
    d.setHours(d.getHours() + 8);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function makeLineConfig(labels, data, color, label, yLabel) {
    return {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: label,
                data: data,
                borderColor: color,
                backgroundColor: color + '20',
                borderWidth: 2.5,
                fill: true,
                tension: 0.35,
                spanGaps: true,
                pointRadius: 3,
                pointBackgroundColor: color,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: true, labels: { usePointStyle: true, boxWidth: 10 } },
            },
            scales: {
                y: {
                    title: { display: true, text: yLabel, color: GRAY_400 },
                    grid: { color: PINK_100 },
                },
                x: {
                    title: { display: true, text: 'Time', color: GRAY_400 },
                    grid: { display: false },
                },
            },
        },
    };
}

// ─── Vitals History Charts ────────────────────────────────────
let vitalsInitialized = false;

function showNoDataMessage() {
    ['chart-spo2', 'chart-hr', 'chart-temp', 'chart-bp'].forEach(id => {
        destroyChart(id);
        const canvas = document.getElementById(id);
        if (canvas) {
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.font = '16px Inter, sans-serif';
            ctx.fillStyle = GRAY_400;
            ctx.textAlign = 'center';
            ctx.fillText('No vitals data available yet.', canvas.width / 2, canvas.height / 2);
        }
    });
    vitalsInitialized = false;
}

function buildCharts(history) {
    const labels = history.map(r => gmt8Time(r.recorded_at));

    destroyChart('spo2');
    const ctx1 = document.getElementById('chart-spo2');
    if (ctx1) charts['spo2'] = new Chart(ctx1, makeLineConfig(labels, history.map(r => r.spo2), PINK_500, 'SPO2', '%'));

    destroyChart('hr');
    const ctx2 = document.getElementById('chart-hr');
    if (ctx2) charts['hr'] = new Chart(ctx2, makeLineConfig(labels, history.map(r => r.heart_rate), '#ef4444', 'Heart Rate', 'BPM'));

    destroyChart('temp');
    const ctx3 = document.getElementById('chart-temp');
    if (ctx3) charts['temp'] = new Chart(ctx3, makeLineConfig(labels, history.map(r => r.temperature), AMBER_500, 'Temperature', '°C'));

    destroyChart('bp');
    const ctx4 = document.getElementById('chart-bp');
    if (ctx4) {
        charts['bp'] = new Chart(ctx4, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Systolic BP (SYS)',
                        data: history.map(r => r.systolic_bp),
                        borderColor: '#8b5cf6',
                        backgroundColor: '#8b5cf620',
                        borderWidth: 2.5,
                        fill: true,
                        tension: 0.35,
                        spanGaps: true,
                        pointRadius: 3,
                        pointBackgroundColor: '#8b5cf6',
                    },
                    {
                        label: 'Diastolic BP (DIA)',
                        data: history.map(r => r.diastolic_bp),
                        borderColor: '#06b6d4',
                        backgroundColor: '#06b6d420',
                        borderWidth: 2.5,
                        fill: true,
                        tension: 0.35,
                        spanGaps: true,
                        pointRadius: 3,
                        pointBackgroundColor: '#06b6d4',
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: true, labels: { usePointStyle: true, boxWidth: 10 } } },
                scales: {
                    y: { title: { display: true, text: 'mmHg', color: GRAY_400 }, grid: { color: PINK_100 } },
                    x: { title: { display: true, text: 'Time', color: GRAY_400 }, grid: { display: false } }
                }
            }
        });
    }

    vitalsInitialized = true;
}

async function initVitalsCharts() {
    let history = [];
    try {
        const resp = await fetch('/api/vitals/history?limit=100');
        const data = await resp.json();
        history = Array.isArray(data) ? data : [];
    } catch (e) {
        history = Array.isArray(window.__VITALS_HISTORY) ? window.__VITALS_HISTORY : [];
    }

    if (history.length === 0) { showNoDataMessage(); return; }
    buildCharts(history);
}

async function updateVitalsCharts() {
    if (!vitalsInitialized) return;
    try {
        const resp = await fetch('/api/vitals/history?limit=100');
        const history = await resp.json();
        if (!Array.isArray(history) || history.length === 0) return;

        const labels = history.map(r => gmt8Time(r.recorded_at));
        ['spo2', 'hr', 'temp'].forEach(key => {
            const c = charts[key];
            if (!c) return;
            c.data.labels = labels;
            c.data.datasets[0].data = history.map(r => r[key === 'spo2' ? 'spo2' : key === 'hr' ? 'heart_rate' : 'temperature']);
            c.update('none');
        });

        const bpChart = charts['bp'];
        if (bpChart) {
            bpChart.data.labels = labels;
            bpChart.data.datasets[0].data = history.map(r => r.systolic_bp);
            bpChart.data.datasets[1].data = history.map(r => r.diastolic_bp);
            bpChart.update('none');
        }
    } catch (e) { /* ignore */ }
}

// ─── Prediction Charts ───────────────────────────────────────
let predsInitialized = false;

async function initPredictionCharts() {
    try {
        let historyResp = await fetch('/api/vitals/history?limit=100');
        let history = await historyResp.json();
        if (!Array.isArray(history)) history = [];

        const resp = await fetch('/api/predictions?steps=20');
        const pred = await resp.json();
        const orders = pred.arima_orders || {};

        // SPO2 Prediction
        destroyChart('predSpo2');
        const ctxSpo2 = document.getElementById('chart-pred-spo2');
        if (ctxSpo2) {
            const histSpo2 = history.map(r => r.spo2).filter(v => v != null);
            const histLabels = history.map(r => gmt8Time(r.recorded_at)).slice(-histSpo2.slice(-20).length);
            const allLabels = [...histLabels.slice(-20), ...(pred.future_times || []).map(t => gmt8Time(t))];

            charts['predSpo2'] = new Chart(ctxSpo2, {
                type: 'line',
                data: {
                    labels: allLabels,
                    datasets: [
                        { label: 'Historical SPO2', data: [...histSpo2.slice(-20), ...Array(pred.spo2_predictions?.length || 0).fill(null)], borderColor: PINK_500, backgroundColor: PINK_100, borderWidth: 2, tension: 0.35, pointRadius: 2 },
                        { label: 'Predicted SPO2', data: [...Array(histSpo2.slice(-20).length).fill(null), ...(pred.spo2_predictions || [])], borderColor: BLUE_500, borderDash: [6, 3], borderWidth: 2.5, tension: 0.35, pointRadius: 4, pointBackgroundColor: BLUE_500 },
                    ],
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { usePointStyle: true } } }, scales: { y: { title: { display: true, text: 'SPO2 %', color: GRAY_400 }, grid: { color: PINK_100 } }, x: { grid: { display: false } } } },
            });
            document.getElementById('predSpo2-order').textContent = 'Model: ' + (orders.spo2 || '—');
        }

        // HR Prediction
        destroyChart('predHr');
        const ctxHr = document.getElementById('chart-pred-hr');
        if (ctxHr) {
            const histHr = history.map(r => r.heart_rate).filter(v => v != null);
            const histLabels2 = history.map(r => gmt8Time(r.recorded_at)).slice(-histHr.slice(-20).length);
            const allLabels2 = [...histLabels2.slice(-20), ...(pred.future_times || []).map(t => gmt8Time(t))];
            charts['predHr'] = new Chart(ctxHr, {
                type: 'line', data: { labels: allLabels2, datasets: [
                    { label: 'Historical HR', data: [...histHr.slice(-20), ...Array(pred.hr_predictions?.length || 0).fill(null)], borderColor: '#ef4444', backgroundColor: '#fee2e2', borderWidth: 2, tension: 0.35, pointRadius: 2 },
                    { label: 'Predicted HR', data: [...Array(histHr.slice(-20).length).fill(null), ...(pred.hr_predictions || [])], borderColor: BLUE_500, borderDash: [6, 3], borderWidth: 2.5, tension: 0.35, pointRadius: 4, pointBackgroundColor: BLUE_500 },
                ]},
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { usePointStyle: true } } }, scales: { y: { title: { display: true, text: 'BPM', color: GRAY_400 }, grid: { color: PINK_100 } }, x: { grid: { display: false } } } },
            });
            document.getElementById('predHr-order').textContent = 'Model: ' + (orders.hr || '—');
        }

        // Temp Prediction
        destroyChart('predTemp');
        const ctxTemp = document.getElementById('chart-pred-temp');
        if (ctxTemp) {
            const histTemp = history.map(r => r.temperature).filter(v => v != null);
            const histLabels3 = history.map(r => gmt8Time(r.recorded_at)).slice(-histTemp.slice(-20).length);
            const allLabels3 = [...histLabels3.slice(-20), ...(pred.future_times || []).map(t => gmt8Time(t))];
            charts['predTemp'] = new Chart(ctxTemp, {
                type: 'line', data: { labels: allLabels3, datasets: [
                    { label: 'Historical Temp', data: [...histTemp.slice(-20), ...Array(pred.temp_predictions?.length || 0).fill(null)], borderColor: AMBER_500, backgroundColor: '#fef3c7', borderWidth: 2, tension: 0.35, pointRadius: 2 },
                    { label: 'Predicted Temp', data: [...Array(histTemp.slice(-20).length).fill(null), ...(pred.temp_predictions || [])], borderColor: BLUE_500, borderDash: [6, 3], borderWidth: 2.5, tension: 0.35, pointRadius: 4, pointBackgroundColor: BLUE_500 },
                ]},
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { usePointStyle: true } } }, scales: { y: { title: { display: true, text: '°C', color: GRAY_400 }, grid: { color: PINK_100 } }, x: { grid: { display: false } } } },
            });
            document.getElementById('predTemp-order').textContent = 'Model: ' + (orders.temp || '—');
        }

        // Blood Pressure (SYS / DIA) Prediction
        destroyChart('predBp');
        const ctxBp = document.getElementById('chart-pred-bp');
        if (ctxBp) {
            const histSys = history.map(r => r.systolic_bp).filter(v => v != null);
            const histDia = history.map(r => r.diastolic_bp).filter(v => v != null);
            const maxHistLen = Math.max(histSys.length, histDia.length, 1);
            const histLabels4 = history.map(r => gmt8Time(r.recorded_at)).slice(-maxHistLen);
            const allLabels4 = [...histLabels4.slice(-20), ...(pred.future_times || []).map(t => gmt8Time(t))];
            const histCount = histLabels4.slice(-20).length;

            charts['predBp'] = new Chart(ctxBp, {
                type: 'line',
                data: {
                    labels: allLabels4,
                    datasets: [
                        { label: 'Historical SYS', data: [...histSys.slice(-20), ...Array(pred.sys_bp_predictions?.length || 0).fill(null)], borderColor: '#8b5cf6', borderWidth: 2, tension: 0.35, pointRadius: 2 },
                        { label: 'Predicted SYS', data: [...Array(histCount).fill(null), ...(pred.sys_bp_predictions || [])], borderColor: '#6366f1', borderDash: [6, 3], borderWidth: 2.5, tension: 0.35, pointRadius: 4, pointBackgroundColor: '#6366f1' },
                        { label: 'Historical DIA', data: [...histDia.slice(-20), ...Array(pred.dia_bp_predictions?.length || 0).fill(null)], borderColor: '#06b6d4', borderWidth: 2, tension: 0.35, pointRadius: 2 },
                        { label: 'Predicted DIA', data: [...Array(histCount).fill(null), ...(pred.dia_bp_predictions || [])], borderColor: '#0284c7', borderDash: [6, 3], borderWidth: 2.5, tension: 0.35, pointRadius: 4, pointBackgroundColor: '#0284c7' },
                    ]
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { usePointStyle: true } } }, scales: { y: { title: { display: true, text: 'mmHg', color: GRAY_400 }, grid: { color: PINK_100 } }, x: { grid: { display: false } } } },
            });
            const sysOrder = orders.sys_bp || '—';
            const diaOrder = orders.dia_bp || '—';
            document.getElementById('predBp-order').textContent = `Models — SYS: ${sysOrder} | DIA: ${diaOrder}`;
        }

        predsInitialized = true;
    } catch (err) {
        console.error('Failed to load predictions:', err);
    }
}


// ─── Live Feed via WebSocket ─────────────────────────────────

// Image ring buffer (most recent first)
let feedImages = [];
const FEED_MAX = 30;

// Collapsible history toggle
function toggleHistory() {
    const strip = document.getElementById('feed-filmstrip');
    const chevron = document.getElementById('history-chevron');
    if (!strip || !chevron) return;
    const isHidden = strip.style.display === 'none';
    strip.style.display = isHidden ? 'grid' : 'none';
    chevron.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
}

// Apply all images from the ring buffer to the DOM
function renderFeed() {
    // --- Main snapshot (latest image) ---
    if (feedImages.length > 0) {
        const latest = feedImages[0];
        const mainContainer = document.getElementById('feed-main-container');
        const imgSrc = '/static/' + latest.image_path;
        const secEl = document.getElementById('feed-sec-ago');
        const dotEl = document.getElementById('feed-dot');

        if (secEl) secEl.textContent = feedLastSec;
        if (dotEl) dotEl.style.background = 'var(--success)';

        if (mainContainer) {
            let imgEl = document.getElementById('feed-main-img');
            if (!imgEl) {
                mainContainer.innerHTML = `<img src="${imgSrc}" alt="Live Feed" class="main-snapshot" id="feed-main-img">`;
            } else if (imgEl.getAttribute('data-path') !== latest.image_path) {
                imgEl.src = imgSrc;
                imgEl.setAttribute('data-path', latest.image_path);
            }
        }
    }

    // --- Recent snapshots grid (images 0-3) ---
    const grid = document.getElementById('feed-grid');
    if (grid) {
        const recent = feedImages.slice(0, 4);
        if (recent.length === 0) {
            grid.innerHTML = '<p style="color:var(--gray-400);text-align:center;padding:2rem;grid-column:1/-1;">No snapshots yet. Waiting for device feed...</p>';
        } else {
            const newIds = recent.map(i => i.id).join(',');
            if (grid.dataset.ids !== newIds) {
                grid.dataset.ids = newIds;
                grid.innerHTML = recent.map(img => `
                    <div class="card feed-card">
                        <img src="/static/${img.image_path}" alt="Snapshot" loading="lazy">
                        <div class="feed-info">
                            <span>${img.caption || 'Snapshot'}</span>
                            <span style="color:var(--gray-400);font-size:0.8rem;">${img.seconds_ago}s ago</span>
                        </div>
                    </div>`).join('');
            }
        }
    }

    // --- History grid (images 4-15) ---
    const filmstrip = document.getElementById('feed-filmstrip');
    if (filmstrip) {
        const history = feedImages.slice(4, 16);
        const countEl = document.getElementById('history-count');
        if (countEl) countEl.textContent = history.length > 0 ? `(${history.length})` : '';
        if (history.length === 0) {
            filmstrip.innerHTML = '<p style="color:var(--gray-400);padding:1rem;">No older snapshots yet.</p>';
        } else {
            const newHistIds = history.map(i => i.id).join(',');
            if (filmstrip.dataset.ids !== newHistIds) {
                filmstrip.dataset.ids = newHistIds;
                filmstrip.innerHTML = history.map(img => `
                    <div class="filmstrip-item" title="${img.caption || 'Snapshot'} — ${img.seconds_ago}s ago" onclick="showFilmstripImage('/static/${img.image_path}')">
                        <img src="/static/${img.image_path}" alt="Snapshot" loading="lazy">
                        <span class="filmstrip-time">${img.seconds_ago}s</span>
                    </div>`).join('');
            }
        }
    }
}

// Tick timer every second
setInterval(() => {
    const feedPanel = document.getElementById('tab-live-feed');
    if (feedPanel && feedPanel.classList.contains('active')) {
        // Age all images by 1 second
        feedImages.forEach(img => { img.seconds_ago = (img.seconds_ago || 0) + 1; });
        feedLastSec = feedImages.length > 0 ? feedImages[0].seconds_ago : 0;
        const secEl = document.getElementById('feed-sec-ago');
        if (secEl && feedLastSec > 0) secEl.textContent = feedLastSec;
    }
}, 1000);

// Click a filmstrip thumbnail to preview
function showFilmstripImage(src) {
    const mainContainer = document.getElementById('feed-main-container');
    if (mainContainer) {
        let imgEl = document.getElementById('feed-main-img');
        if (imgEl) {
            imgEl.src = src;
            imgEl.removeAttribute('data-path');
        } else {
            mainContainer.innerHTML = `<img src="${src}" alt="Live Feed" class="main-snapshot" id="feed-main-img">`;
        }
    }
}

let feedReconnectTimer = null;
let feedReconnectDelay = 1000;

function startFeedPolling() {
    if (feedSocket && (feedSocket.readyState === WebSocket.OPEN || feedSocket.readyState === WebSocket.CONNECTING)) return;

    const userId = window.__USER_ID || 1;
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/live-feed`;

    console.log('[Feed] Connecting WebSocket:', wsUrl);
    feedSocket = new WebSocket(wsUrl);

    feedSocket.onopen = () => {
        console.log('[Feed] WebSocket connected, subscribing to patient', userId);
        feedReconnectDelay = 1000; // reset backoff
        if (feedReconnectTimer) { clearTimeout(feedReconnectTimer); feedReconnectTimer = null; }
        feedSocket.send(`patient_id:${userId}`);
        // Fetch initial batch via HTTP
        fetch(`/api/live-feed?limit=24`)
            .then(r => r.json())
            .then(images => {
                feedImages = images.map(img => ({ ...img, seconds_ago: img.seconds_ago || 0 }));
                feedLastSec = feedImages.length > 0 ? feedImages[0].seconds_ago : 0;
                renderFeed();
            })
            .catch(() => {});
        // Stop HTTP fallback polling while WS is connected
        if (feedHttpTimer) { clearInterval(feedHttpTimer); feedHttpTimer = null; }
    };

    feedSocket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'new_image' && msg.image_path) {
                feedImages.unshift({ ...msg, seconds_ago: 0 });
                if (feedImages.length > FEED_MAX) feedImages.length = FEED_MAX;
                feedLastSec = 0;
                renderFeed();
            }
        } catch (e) { /* ignore */ }
    };

    feedSocket.onclose = () => {
        console.log('[Feed] WebSocket closed, starting HTTP fallback & scheduling reconnect');
        feedSocket = null;
        startHttpFallback();
        // Schedule auto-reconnect with exponential backoff up to 16s
        if (!feedReconnectTimer) {
            feedReconnectTimer = setTimeout(() => {
                feedReconnectTimer = null;
                feedReconnectDelay = Math.min(feedReconnectDelay * 2, 16000);
                startFeedPolling();
            }, feedReconnectDelay);
        }
    };

    feedSocket.onerror = () => {
        console.log('[Feed] WebSocket error');
        feedSocket?.close();
    };

    // Safety: if WS doesn't connect within 3s, start HTTP fallback
    setTimeout(() => {
        if (!feedSocket || feedSocket.readyState !== WebSocket.OPEN) {
            startHttpFallback();
        }
    }, 3000);
}


function startHttpFallback() {
    if (feedHttpTimer) return;
    console.log('[Feed] Starting HTTP fallback polling');
    refreshFeedHttp();
    feedHttpTimer = setInterval(refreshFeedHttp, 2000);
}

async function refreshFeedHttp() {
    try {
        const resp = await fetch('/api/live-feed?limit=24');
        if (!resp.ok) return;
        const images = await resp.json();
        if (images.length > 0) {
            feedImages = images.map(img => ({ ...img, seconds_ago: img.seconds_ago || 0 }));
            feedLastSec = feedImages.length > 0 ? feedImages[0].seconds_ago : 0;
            renderFeed();
        }
    } catch (e) { /* ignore */ }
}

function stopFeedPolling() {
    if (feedSocket) { feedSocket.close(); feedSocket = null; }
    if (feedHttpTimer) { clearInterval(feedHttpTimer); feedHttpTimer = null; }
}
async function markRead(notifId, element) {
    try {
        await fetch('/api/notifications/' + notifId + '/read', { method: 'POST' });
        element.classList.remove('unread');
    } catch (err) {
        console.error('Mark read failed:', err);
    }
}

async function markAllRead() {
    try {
        const resp = await fetch('/api/notifications');
        const notifs = await resp.json();
        const unread = notifs.filter(n => !n.is_read);
        for (const n of unread) {
            await fetch('/api/notifications/' + n.id + '/read', { method: 'POST' });
        }
        // Refresh the list and badge
        const items = document.querySelectorAll('.notif-item');
        items.forEach(el => el.classList.remove('unread'));
        const badge = document.getElementById('unread-badge');
        if (badge) badge.style.display = 'none';
    } catch (err) {
        console.error('Mark all read failed:', err);
    }
}

// ─── Live Polling: Update vitals cards & timer ──────────────
function getSpo2Status(spo2) {
    if (spo2 == null) return { cls: '', text: '--' };
    if (spo2 >= 95) return { cls: 'normal', text: 'Normal' };
    if (spo2 >= 90) return { cls: 'warning', text: 'Warning' };
    return { cls: 'critical', text: 'Critical' };
}

function updateVitalCard(valId, statusId, value, statusObj) {
    const valEl = document.getElementById(valId);
    const statusEl = document.getElementById(statusId);
    if (valEl) valEl.textContent = value != null ? value : '--';
    if (statusEl) {
        statusEl.textContent = statusObj.text;
        statusEl.className = 'vital-status ' + statusObj.cls;
    }
}

// Poll every 5 seconds for fresh data
setInterval(async () => {
    try {
        const resp = await fetch('/api/vitals/latest');
        const data = await resp.json();

        // Update summary cards
        if (data.spo2 !== undefined || data.heart_rate !== undefined || data.temperature !== undefined) {
            updateVitalCard('vital-spo2-val', 'vital-spo2-status', data.spo2, getSpo2Status(data.spo2));
            updateVitalCard('vital-hr-val', 'vital-hr-status', data.heart_rate, { cls: 'normal', text: data.heart_rate != null ? 'Normal' : '--' });
            updateVitalCard('vital-temp-val', 'vital-temp-status', data.temperature, { cls: 'normal', text: data.temperature != null ? 'Normal' : '--' });
        }

        if (data.systolic_bp !== undefined || data.diastolic_bp !== undefined) {
            const bpVal = (data.systolic_bp != null && data.diastolic_bp != null)
                ? data.systolic_bp + '/' + data.diastolic_bp
                : '--/--';
            const bpEl = document.getElementById('vital-bp-val');
            if (bpEl) bpEl.textContent = bpVal;
            const bpStatus = document.getElementById('vital-bp-status');
            if (bpStatus) {
                bpStatus.textContent = (data.systolic_bp != null) ? 'Normal' : '--';
                bpStatus.className = 'vital-status normal';
            }
        }

        // Update timestamp
        if (data.seconds_ago !== undefined) {
            const secEl = document.getElementById('summary-sec-ago');
            if (secEl) secEl.textContent = data.seconds_ago;
        }

        // Refresh vitals charts if that tab is visible
        const vitalsPanel = document.getElementById('tab-vitals');
        if (vitalsPanel && vitalsPanel.classList.contains('active')) {
            updateVitalsCharts();
        }

        // Refresh predictions if that tab is visible
        const predPanel = document.getElementById('tab-prediction');
        if (predPanel && predPanel.classList.contains('active')) {
            initPredictionCharts();
        }

        // Update unread notification count
        const notifResp = await fetch('/api/notifications');
        const notifs = await notifResp.json();
        const unreadCount = notifs.filter(n => !n.is_read).length;
        const badge = document.getElementById('unread-badge');
        if (badge) {
            if (unreadCount > 0) {
                badge.textContent = unreadCount;
                badge.style.display = 'inline';
            } else {
                badge.style.display = 'none';
            }
        }

        // Refresh notification list if that tab is visible
        const notifPanel = document.getElementById('tab-notifications');
        if (notifPanel && notifPanel.classList.contains('active')) {
            const list = document.getElementById('notif-list');
            if (list && notifs.length > 0) {
                list.innerHTML = notifs.map(n => `
                    <div class="notif-item ${n.is_read ? '' : 'unread'} level-${n.level}"
                         data-id="${n.id}" onclick="markRead(${n.id}, this)">
                        <div class="notif-icon">${n.level === 'critical' ? '[CRITICAL]' : n.level === 'warning' ? '[WARNING]' : '[INFO]'}</div>
                        <div class="notif-body">
                            <div class="notif-title">${n.title}</div>
                            <div class="notif-msg">${n.message}</div>
                            <div class="notif-time">${gmt8Time(n.created_at)}</div>
                        </div>
                    </div>`).join('');
            }
        }
    } catch (err) {
        // Silently ignore polling errors
    }
}, 5000);

// ─── Initialize charts on page load if on relevant tabs ─────
document.addEventListener('DOMContentLoaded', () => {
    // Summary is default, no chart needed immediately
    // Charts init on tab switch
});

// ─── Profile: Edit Age ─────────────────────────────────────
function editAge(e) {
    e.preventDefault();
    document.getElementById('profile-age-display').style.display = 'none';
    document.getElementById('profile-age-edit').style.display = 'block';
}
function cancelEditAge() {
    document.getElementById('profile-age-display').style.display = 'block';
    document.getElementById('profile-age-edit').style.display = 'none';
    document.getElementById('profile-age-input').value = document.getElementById('profile-age-display').textContent.replace('—', '');
}
async function saveAge() {
    const input = document.getElementById('profile-age-input');
    const age = parseInt(input.value);
    if (!age || age < 1 || age > 120) { alert('Enter a valid age (1-120)'); return; }
    try {
        const resp = await fetch('/api/profile', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ age: age })
        });
        if (resp.ok) {
            document.getElementById('profile-age-display').textContent = age;
            cancelEditAge();
        } else {
            alert('Failed to save age');
        }
    } catch (err) { alert('Error: ' + err.message); }
}

// ─── Debug Tab ──────────────────────────────────────────────
async function refreshDebugPreview() {
    const pre = document.getElementById('debug-preview');
    if (!pre) return;
    pre.textContent = 'Loading...';
    try {
        const userId = window.__USER_ID || 1;
        const resp = await fetch(`/api/esp32/alerts/${userId}`, {
            headers: { 'x-api-key': 'aruga-dev-key-change-in-production' }
        });
        const data = await resp.json();
        pre.textContent = JSON.stringify(data, null, 2);
    } catch (err) {
        pre.textContent = 'Error: ' + err.message;
    }
}

async function applyDebugOverrides() {
    const userId = window.__USER_ID || 1;
    const body = {};

    const smsalert = document.getElementById('debug-smsalert')?.value;
    if (smsalert) body.smsalert = smsalert === 'true';

    const smsmsg = document.getElementById('debug-smsalertmsg')?.value;
    if (smsmsg) body.smsalertmsg = smsmsg;

    const med = document.getElementById('debug-meddispense')?.value;
    if (med !== undefined && med !== '') body.medicinedispense = parseInt(med);

    const led = document.getElementById('debug-led')?.value;
    if (led) body.led = led;

    const alertVal = document.getElementById('debug-alert')?.value;
    if (alertVal) body.alert = alertVal === 'true';

    const lcd3 = document.getElementById('debug-lcd3')?.value;
    if (lcd3) body.lcd3 = lcd3;

    try {
        const resp = await fetch(`/api/debug/override/${userId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'x-api-key': 'aruga-dev-key-change-in-production'
            },
            body: JSON.stringify(body)
        });
        const data = await resp.json();
        alert('Overrides applied!');
        refreshDebugPreview();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function clearDebugOverrides() {
    const userId = window.__USER_ID || 1;
    try {
        await fetch(`/api/debug/override/${userId}`, {
            method: 'DELETE',
            headers: { 'x-api-key': 'aruga-dev-key-change-in-production' }
        });
        // Reset form fields
        document.querySelectorAll('#tab-debug select, #tab-debug input[type=text], #tab-debug input[type=number]').forEach(el => {
            if (el.tagName === 'SELECT') el.selectedIndex = 0;
            else el.value = '';
        });
        document.getElementById('debug-meddispense').value = '0';
        alert('Overrides cleared!');
        refreshDebugPreview();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}
