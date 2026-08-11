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

function getCsrfHeaders(extra = {}) {
    const token = document.querySelector('meta[name="csrf-token"]')?.content || '';
    return {
        'x-csrf-token': token,
        ...extra
    };
}

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
    if (tabName === 'medicines') loadMedicineSlots();
}

document.querySelectorAll('.sidebar .tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchToTab(btn.dataset.tab));
});

// On page load, restore tab from URL hash
(function restoreTabFromHash() {
    const hash = location.hash.replace('#', '');
    const validTabs = ['summary', 'live-feed', 'vitals', 'prediction', 'notifications', 'profile', 'medicines', 'debug'];
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

function renderNoDataOnCanvas(canvasId, message) {
    destroyChart(canvasId.replace('chart-', '').replace('pred-', 'pred'));
    const canvas = document.getElementById(canvasId);
    if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.font = '15px Inter, sans-serif';
        ctx.fillStyle = GRAY_400;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(message, canvas.width / 2, canvas.height / 2);
    }
}

function buildCharts(historyData) {
    const history = Array.isArray(historyData) ? historyData : [];

    // 1. SPO2 Chart
    destroyChart('spo2');
    const validSpo2 = history.filter(r => r && r.spo2 != null && !isNaN(r.spo2));
    if (validSpo2.length > 0) {
        const labels = validSpo2.map(r => gmt8Time(r.recorded_at));
        const data = validSpo2.map(r => r.spo2);
        const ctx = document.getElementById('chart-spo2');
        if (ctx) charts['spo2'] = new Chart(ctx, makeLineConfig(labels, data, PINK_500, 'SPO2', '%'));
    } else {
        renderNoDataOnCanvas('chart-spo2', 'No SPO2 data recorded yet.');
    }

    // 2. Heart Rate Chart
    destroyChart('hr');
    const validHr = history.filter(r => r && r.heart_rate != null && !isNaN(r.heart_rate));
    if (validHr.length > 0) {
        const labels = validHr.map(r => gmt8Time(r.recorded_at));
        const data = validHr.map(r => r.heart_rate);
        const ctx = document.getElementById('chart-hr');
        if (ctx) charts['hr'] = new Chart(ctx, makeLineConfig(labels, data, '#ef4444', 'Heart Rate', 'BPM'));
    } else {
        renderNoDataOnCanvas('chart-hr', 'No Heart Rate data recorded yet.');
    }

    // 3. Temperature Chart
    destroyChart('temp');
    const validTemp = history.filter(r => r && r.temperature != null && !isNaN(r.temperature));
    if (validTemp.length > 0) {
        const labels = validTemp.map(r => gmt8Time(r.recorded_at));
        const data = validTemp.map(r => r.temperature);
        const ctx = document.getElementById('chart-temp');
        if (ctx) charts['temp'] = new Chart(ctx, makeLineConfig(labels, data, AMBER_500, 'Temperature', '°C'));
    } else {
        renderNoDataOnCanvas('chart-temp', 'No Temperature data recorded yet.');
    }

    // 4. Blood Pressure Chart
    destroyChart('bp');
    const validBp = history.filter(r => r && r.systolic_bp != null && r.diastolic_bp != null && !isNaN(r.systolic_bp) && !isNaN(r.diastolic_bp));
    if (validBp.length > 0) {
        const labels = validBp.map(r => gmt8Time(r.recorded_at));
        const ctx = document.getElementById('chart-bp');
        if (ctx) {
            charts['bp'] = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Systolic BP (SYS)',
                            data: validBp.map(r => r.systolic_bp),
                            borderColor: '#8b5cf6',
                            backgroundColor: '#8b5cf620',
                            borderWidth: 2.5,
                            fill: true,
                            tension: 0.35,
                            spanGaps: false,
                            pointRadius: 3,
                            pointBackgroundColor: '#8b5cf6',
                        },
                        {
                            label: 'Diastolic BP (DIA)',
                            data: validBp.map(r => r.diastolic_bp),
                            borderColor: '#06b6d4',
                            backgroundColor: '#06b6d420',
                            borderWidth: 2.5,
                            fill: true,
                            tension: 0.35,
                            spanGaps: false,
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
    } else {
        renderNoDataOnCanvas('chart-bp', 'No Blood Pressure data recorded yet.');
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

    buildCharts(history);
}

async function updateVitalsCharts() {
    if (!vitalsInitialized) return;
    try {
        const resp = await fetch('/api/vitals/history?limit=100');
        const history = await resp.json();
        if (!Array.isArray(history)) return;
        buildCharts(history);
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

        // Helper for building non-null prediction dataset point objects
        const createPredPoints = (histList, predList, futureTimes) => {
            if (!histList || histList.length === 0 || !predList || predList.length === 0) {
                return { histPoints: [], predPoints: [], labels: [] };
            }
            const histSlice = histList.slice(-20);
            const histPoints = histSlice.map(r => ({ x: gmt8Time(r.recorded_at), y: r.val }));
            const fTimes = (futureTimes || []).map(t => gmt8Time(t));
            const lastPoint = histPoints[histPoints.length - 1];

            const predPoints = [
                { x: lastPoint.x, y: lastPoint.y },
                ...predList.map((yVal, idx) => ({ x: fTimes[idx] || `+${idx+1}`, y: yVal }))
            ];

            const labels = [...histPoints.map(p => p.x), ...fTimes];
            return { histPoints, predPoints, labels };
        };

        // SPO2 Prediction
        destroyChart('predSpo2');
        const validSpo2 = history.filter(r => r && r.spo2 != null && !isNaN(r.spo2)).map(r => ({ recorded_at: r.recorded_at, val: r.spo2 }));
        const ctxSpo2 = document.getElementById('chart-pred-spo2');
        if (ctxSpo2 && validSpo2.length > 0 && pred.spo2_predictions && pred.spo2_predictions.length > 0) {
            const { histPoints, predPoints, labels } = createPredPoints(validSpo2, pred.spo2_predictions, pred.future_times);
            charts['predSpo2'] = new Chart(ctxSpo2, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        { label: 'Historical SPO2', data: histPoints, borderColor: PINK_500, backgroundColor: PINK_100, borderWidth: 2, tension: 0.35, pointRadius: 2, fill: true },
                        { label: 'Predicted SPO2', data: predPoints, borderColor: BLUE_500, borderDash: [6, 3], borderWidth: 2.5, tension: 0.35, pointRadius: 4, pointBackgroundColor: BLUE_500, fill: false },
                    ],
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { usePointStyle: true } } }, scales: { y: { title: { display: true, text: 'SPO2 %', color: GRAY_400 }, grid: { color: PINK_100 } }, x: { grid: { display: false } } } },
            });
            document.getElementById('predSpo2-order').textContent = 'Model: ' + (orders.spo2 || '—');
        } else if (ctxSpo2) {
            renderNoDataOnCanvas('chart-pred-spo2', 'Insufficient SPO2 data for prediction.');
            document.getElementById('predSpo2-order').textContent = 'Model: —';
        }

        // HR Prediction
        destroyChart('predHr');
        const validHr = history.filter(r => r && r.heart_rate != null && !isNaN(r.heart_rate)).map(r => ({ recorded_at: r.recorded_at, val: r.heart_rate }));
        const ctxHr = document.getElementById('chart-pred-hr');
        if (ctxHr && validHr.length > 0 && pred.hr_predictions && pred.hr_predictions.length > 0) {
            const { histPoints, predPoints, labels } = createPredPoints(validHr, pred.hr_predictions, pred.future_times);
            charts['predHr'] = new Chart(ctxHr, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        { label: 'Historical HR', data: histPoints, borderColor: '#ef4444', backgroundColor: '#fee2e2', borderWidth: 2, tension: 0.35, pointRadius: 2, fill: true },
                        { label: 'Predicted HR', data: predPoints, borderColor: BLUE_500, borderDash: [6, 3], borderWidth: 2.5, tension: 0.35, pointRadius: 4, pointBackgroundColor: BLUE_500, fill: false },
                    ]
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { usePointStyle: true } } }, scales: { y: { title: { display: true, text: 'BPM', color: GRAY_400 }, grid: { color: PINK_100 } }, x: { grid: { display: false } } } },
            });
            document.getElementById('predHr-order').textContent = 'Model: ' + (orders.hr || '—');
        } else if (ctxHr) {
            renderNoDataOnCanvas('chart-pred-hr', 'Insufficient Heart Rate data for prediction.');
            document.getElementById('predHr-order').textContent = 'Model: —';
        }

        // Temp Prediction
        destroyChart('predTemp');
        const validTemp = history.filter(r => r && r.temperature != null && !isNaN(r.temperature)).map(r => ({ recorded_at: r.recorded_at, val: r.temperature }));
        const ctxTemp = document.getElementById('chart-pred-temp');
        if (ctxTemp && validTemp.length > 0 && pred.temp_predictions && pred.temp_predictions.length > 0) {
            const { histPoints, predPoints, labels } = createPredPoints(validTemp, pred.temp_predictions, pred.future_times);
            charts['predTemp'] = new Chart(ctxTemp, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        { label: 'Historical Temp', data: histPoints, borderColor: AMBER_500, backgroundColor: '#fef3c7', borderWidth: 2, tension: 0.35, pointRadius: 2, fill: true },
                        { label: 'Predicted Temp', data: predPoints, borderColor: BLUE_500, borderDash: [6, 3], borderWidth: 2.5, tension: 0.35, pointRadius: 4, pointBackgroundColor: BLUE_500, fill: false },
                    ]
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { usePointStyle: true } } }, scales: { y: { title: { display: true, text: '°C', color: GRAY_400 }, grid: { color: PINK_100 } }, x: { grid: { display: false } } } },
            });
            document.getElementById('predTemp-order').textContent = 'Model: ' + (orders.temp || '—');
        } else if (ctxTemp) {
            renderNoDataOnCanvas('chart-pred-temp', 'Insufficient Temperature data for prediction.');
            document.getElementById('predTemp-order').textContent = 'Model: —';
        }

        // BP Prediction
        destroyChart('predBp');
        const validSys = history.filter(r => r && r.systolic_bp != null && !isNaN(r.systolic_bp)).map(r => ({ recorded_at: r.recorded_at, val: r.systolic_bp }));
        const validDia = history.filter(r => r && r.diastolic_bp != null && !isNaN(r.diastolic_bp)).map(r => ({ recorded_at: r.recorded_at, val: r.diastolic_bp }));
        const ctxBp = document.getElementById('chart-pred-bp');
        if (ctxBp && validSys.length > 0 && validDia.length > 0 && pred.sys_bp_predictions && pred.dia_bp_predictions) {
            const sysObj = createPredPoints(validSys, pred.sys_bp_predictions, pred.future_times);
            const diaObj = createPredPoints(validDia, pred.dia_bp_predictions, pred.future_times);
            const allBpLabels = sysObj.labels.length >= diaObj.labels.length ? sysObj.labels : diaObj.labels;

            charts['predBp'] = new Chart(ctxBp, {
                type: 'line',
                data: {
                    labels: allBpLabels,
                    datasets: [
                        { label: 'Historical SYS', data: sysObj.histPoints, borderColor: '#8b5cf6', borderWidth: 2, tension: 0.35, pointRadius: 2, fill: false },
                        { label: 'Predicted SYS', data: sysObj.predPoints, borderColor: '#6366f1', borderDash: [6, 3], borderWidth: 2.5, tension: 0.35, pointRadius: 4, pointBackgroundColor: '#6366f1', fill: false },
                        { label: 'Historical DIA', data: diaObj.histPoints, borderColor: '#06b6d4', borderWidth: 2, tension: 0.35, pointRadius: 2, fill: false },
                        { label: 'Predicted DIA', data: diaObj.predPoints, borderColor: '#0284c7', borderDash: [6, 3], borderWidth: 2.5, tension: 0.35, pointRadius: 4, pointBackgroundColor: '#0284c7', fill: false },
                    ]
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { usePointStyle: true } } }, scales: { y: { title: { display: true, text: 'mmHg', color: GRAY_400 }, grid: { color: PINK_100 } }, x: { grid: { display: false } } } },
            });
            const sysOrder = orders.sys_bp || '—';
            const diaOrder = orders.dia_bp || '—';
            document.getElementById('predBp-order').textContent = `Models — SYS: ${sysOrder} | DIA: ${diaOrder}`;
        } else if (ctxBp) {
            renderNoDataOnCanvas('chart-pred-bp', 'Insufficient Blood Pressure data for prediction.');
            document.getElementById('predBp-order').textContent = 'Model: —';
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

function resolveFeedImgUrl(path) {
    if (!path) return '';
    if (path.startsWith('http://') || path.startsWith('https://')) return path;
    return '/static/' + path.replace(/^\//, '');
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// Apply all images from the ring buffer to the DOM
function renderFeed() {
    // --- Main snapshot (latest image) ---
    if (feedImages.length > 0) {
        const latest = feedImages[0];
        const mainContainer = document.getElementById('feed-main-container');
        const imgSrc = resolveFeedImgUrl(latest.image_path);
        const secEl = document.getElementById('feed-sec-ago');
        const dotEl = document.getElementById('feed-dot');

        if (secEl) secEl.textContent = feedLastSec;
        if (dotEl) dotEl.style.background = 'var(--success)';

        if (mainContainer) {
            let imgEl = document.getElementById('feed-main-img');
            if (!imgEl) {
                mainContainer.innerHTML = `<img src="${escapeHtml(imgSrc)}" alt="Live Feed" class="main-snapshot" id="feed-main-img">`;
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
                        <img src="${escapeHtml(resolveFeedImgUrl(img.image_path))}" alt="Snapshot" loading="lazy">
                        <div class="feed-info">
                            <span>${escapeHtml(img.caption || 'Snapshot')}</span>
                            <span style="color:var(--gray-400);font-size:0.8rem;">${escapeHtml(img.seconds_ago)}s ago</span>
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
                    <div class="filmstrip-item" title="${escapeHtml(img.caption || 'Snapshot')} — ${escapeHtml(img.seconds_ago)}s ago" onclick="showFilmstripImage('${escapeHtml(resolveFeedImgUrl(img.image_path))}')">
                        <img src="${escapeHtml(resolveFeedImgUrl(img.image_path))}" alt="Snapshot" loading="lazy">
                        <span class="filmstrip-time">${escapeHtml(img.seconds_ago)}s</span>
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
        await fetch('/api/notifications/' + notifId + '/read', { method: 'POST', headers: getCsrfHeaders() });
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
            await fetch('/api/notifications/' + n.id + '/read', { method: 'POST', headers: getCsrfHeaders() });
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
            headers: getCsrfHeaders({ 'Content-Type': 'application/json' }),
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

async function saveSmsAlertSetting() {
    const toggleEl = document.getElementById('profile-sms-alerts-toggle');
    if (!toggleEl) return;
    const enabled = toggleEl.checked;
    const badge = document.getElementById('sms-alerts-status-badge');
    const toast = document.getElementById('sms-alerts-saved-toast');
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

    try {
        const resp = await fetch('/api/profile', {
            method: 'PATCH',
            headers: getCsrfHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
                enable_sms_alerts: enabled,
                csrf_token: csrfToken
            })
        });

        if (resp.ok) {
            if (badge) {
                badge.textContent = enabled ? 'Active' : 'Disabled';
                badge.style.background = enabled ? 'var(--pink-600)' : 'var(--gray-400)';
            }
            if (toast) {
                toast.style.display = 'inline-block';
                setTimeout(() => { toast.style.display = 'none'; }, 3000);
            }
        } else {
            const errData = await resp.json().catch(() => ({}));
            alert('Failed to save SMS alert setting: ' + (errData.detail || resp.statusText || 'Server error'));
        }
    } catch (err) {
        alert('Error saving SMS alert setting: ' + err.message);
    }
}

async function toggleProfileSmsAlerts(enabled) {
    await saveSmsAlertSetting();
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

    const smsno = document.getElementById('debug-smsalertno')?.value;
    if (smsno !== undefined && smsno !== '') body.smsalertno = parseInt(smsno);

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


// ─── Medicine Dispenser Schedule (7 Slots) ───────────────────
function getGMT8Date() {
    const d = new Date();
    // Convert to GMT+8
    const utc = d.getTime() + (d.getTimezoneOffset() * 60000);
    return new Date(utc + (3600000 * 8));
}

function updateGMT8LiveClock() {
    const clockEl = document.getElementById('gmt8-live-clock');
    const now8 = getGMT8Date();
    if (clockEl) {
        const dateStr = now8.getFullYear() + '-' +
            String(now8.getMonth() + 1).padStart(2, '0') + '-' +
            String(now8.getDate()).padStart(2, '0');
        const timeStr = now8.toLocaleTimeString('en-US', { hour12: true, hour: '2-digit', minute: '2-digit', second: '2-digit' });
        clockEl.textContent = `${dateStr} ${timeStr}`;
    }

    // Check active slots live against current GMT+8 time
    for (let slot = 1; slot <= 7; slot++) {
        const dtInput = document.getElementById(`med-datetime-${slot}`);
        const activeChk = document.getElementById(`med-active-${slot}`);
        const statusBadge = document.getElementById(`med-status-badge-${slot}`);
        const infoEl = document.getElementById(`med-info-${slot}`);
        const card = document.getElementById(`med-slot-card-${slot}`);
        const dispenseBtn = document.getElementById(`med-dispense-btn-${slot}`);

        if (!activeChk || !dtInput || !statusBadge || !card) continue;

        const isDispensed = card.dataset.isDispensed === 'true';

        if (isDispensed) {
            statusBadge.textContent = 'Dispensed / Completed';
            statusBadge.style.background = '#3b82f6';
            statusBadge.style.color = 'white';
            card.style.borderColor = '#3b82f6';
            card.style.boxShadow = 'none';
            if (dispenseBtn) dispenseBtn.style.display = 'none';
            if (infoEl) infoEl.innerHTML = `Status: <span style="color:#3b82f6;font-weight:600;">✅ Medicine taken / dispensed</span>`;
            continue;
        }

        if (!activeChk.checked) {
            statusBadge.textContent = 'Disabled';
            statusBadge.style.background = 'var(--gray-200)';
            statusBadge.style.color = 'var(--gray-700)';
            card.style.borderColor = 'var(--pink-200)';
            if (dispenseBtn) dispenseBtn.style.display = 'none';
            continue;
        }

        if (!dtInput.value) {
            statusBadge.textContent = 'Scheduled (No Time)';
            statusBadge.style.background = '#f59e0b';
            statusBadge.style.color = 'white';
            card.style.borderColor = 'var(--pink-200)';
            if (dispenseBtn) dispenseBtn.style.display = 'none';
            continue;
        }

        const scheduledTarget = new Date(dtInput.value);
        if (isNaN(scheduledTarget.getTime())) continue;

        if (now8 >= scheduledTarget) {
            statusBadge.textContent = `DUE! (Dispense Code: ${slot})`;
            statusBadge.style.background = '#ef4444';
            statusBadge.style.color = 'white';
            card.style.borderColor = '#ef4444';
            card.style.boxShadow = '0 0 12px rgba(239, 68, 68, 0.3)';
            if (dispenseBtn) dispenseBtn.style.display = 'inline-block';
            if (infoEl) infoEl.innerHTML = `<span style="color:#ef4444;font-weight:700;">🚨 Target time reached! ESP32 trigger code: medicinedispense = ${slot}</span>`;
        } else {
            statusBadge.textContent = 'Active / Waiting';
            statusBadge.style.background = '#10b981';
            statusBadge.style.color = 'white';
            card.style.borderColor = '#10b981';
            card.style.boxShadow = 'none';
            if (dispenseBtn) dispenseBtn.style.display = 'none';
            const diffMs = scheduledTarget - now8;
            const diffMin = Math.round(diffMs / 60000);
            if (infoEl) infoEl.innerHTML = `Status: <span style="color:#10b981;font-weight:600;">Scheduled for ${scheduledTarget.toLocaleString()} (in ~${diffMin} mins)</span>`;
        }
    }
}

setInterval(updateGMT8LiveClock, 1000);

async function loadMedicineSlots() {
    try {
        const resp = await fetch('/api/medicines');
        const slots = await resp.json();
        if (!Array.isArray(slots)) return;

        slots.forEach(slot => {
            const num = slot.slot_number;
            const card = document.getElementById(`med-slot-card-${num}`);
            const nameEl = document.getElementById(`med-name-${num}`);
            const dosageEl = document.getElementById(`med-dosage-${num}`);
            const dtEl = document.getElementById(`med-datetime-${num}`);
            const activeEl = document.getElementById(`med-active-${num}`);

            if (card) card.dataset.isDispensed = slot.is_dispensed ? 'true' : 'false';
            if (nameEl) nameEl.value = slot.name || '';
            if (dosageEl) dosageEl.value = slot.dosage || '';
            if (activeEl) activeEl.checked = !!slot.active;

            if (dtEl && slot.scheduled_datetime) {
                dtEl.value = slot.scheduled_datetime.substring(0, 16);
            } else if (dtEl) {
                dtEl.value = '';
            }
        });

        updateGMT8LiveClock();
    } catch (err) {
        console.error('Failed to load medicine slots:', err);
    }
}

async function saveMedicineSlot(slotNum) {
    const name = document.getElementById(`med-name-${slotNum}`)?.value || '';
    const dosage = document.getElementById(`med-dosage-${slotNum}`)?.value || '';
    const dtVal = document.getElementById(`med-datetime-${slotNum}`)?.value || null;
    const active = document.getElementById(`med-active-${slotNum}`)?.checked || false;

    try {
        const resp = await fetch('/api/medicines/slot', {
            method: 'POST',
            headers: getCsrfHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
                slot_number: slotNum,
                name: name,
                dosage: dosage,
                scheduled_datetime: dtVal ? dtVal + ':00' : null,
                active: active,
                is_dispensed: false
            })
        });

        const data = await resp.json();
        if (resp.ok) {
            alert(`Medicine Slot ${slotNum} saved successfully!`);
            loadMedicineSlots();
        } else {
            alert('Failed to save slot: ' + (data.detail || 'Unknown error'));
        }
    } catch (err) {
        alert('Error saving medicine slot: ' + err.message);
    }
}

async function markSlotDispensed(slotNum) {
    const name = document.getElementById(`med-name-${slotNum}`)?.value || '';
    const dosage = document.getElementById(`med-dosage-${slotNum}`)?.value || '';
    const dtVal = document.getElementById(`med-datetime-${slotNum}`)?.value || null;
    const active = document.getElementById(`med-active-${slotNum}`)?.checked || false;

    try {
        const resp = await fetch('/api/medicines/slot', {
            method: 'POST',
            headers: getCsrfHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
                slot_number: slotNum,
                name: name,
                dosage: dosage,
                scheduled_datetime: dtVal ? dtVal + ':00' : null,
                active: active,
                is_dispensed: true
            })
        });

        if (resp.ok) {
            alert(`Medicine Slot ${slotNum} marked as dispensed!`);
            loadMedicineSlots();
        } else {
            alert('Error updating slot status.');
        }
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function resetMedicineSlot(slotNum) {
    if (!confirm(`Are you sure you want to clear Medicine Slot ${slotNum}?`)) return;
    try {
        const resp = await fetch(`/api/medicines/slot/${slotNum}/reset`, {
            method: 'POST',
            headers: getCsrfHeaders()
        });
        if (resp.ok) {
            document.getElementById(`med-name-${slotNum}`).value = `Medicine Slot ${slotNum}`;
            document.getElementById(`med-dosage-${slotNum}`).value = '';
            document.getElementById(`med-datetime-${slotNum}`).value = '';
            document.getElementById(`med-active-${slotNum}`).checked = false;
            const card = document.getElementById(`med-slot-card-${slotNum}`);
            if (card) card.dataset.isDispensed = 'false';
            loadMedicineSlots();
            alert(`Slot ${slotNum} cleared.`);
        }
    } catch (err) {
        alert('Error clearing slot: ' + err.message);
    }
}


