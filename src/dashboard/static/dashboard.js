/* ══════════════════════════════════════════════════════════════════════════════
   PostureGuard Dashboard – Live + Historical Data Controller
   Polls /api/live/metrics (1 s), /api/live/history (3 s), /api/sessions (12 s)
══════════════════════════════════════════════════════════════════════════════ */

'use strict';

/* ── Config ─────────────────────────────────────────────────────────────── */
const LIVE_POLL_MS     = 1000;   // fast poll for metric cards + status
const HISTORY_POLL_MS  = 3000;   // chart / alert update
const SESSION_POLL_MS  = 12000;  // session list + history table
const CHART_POINTS     = 80;     // rolling window for line charts
const RING_CIRCUM      = 301.6;  // SVG arc circumference (r=48)

/* ── DOM refs ────────────────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);

const dom = {
  workerPill:      $('workerPill'),
  workerDot:       $('workerDot'),
  workerLabel:     $('workerLabel'),
  esp32Pill:       $('esp32Pill'),
  esp32Label:      $('esp32Label'),
  sessionClock:    $('sessionClock'),
  camDot:          $('camDot'),
  scoreArc:        $('scoreArc'),
  postureScore:    $('postureScore'),
  postureBadge:    $('postureBadge'),
  attentionDot:    $('attentionDot'),
  attentionValue:  $('attentionValue'),
  focusPct:        $('focusPct'),
  focusFill:       $('focusFill'),
  sessionSelect:   $('sessionSelect'),
  focusedTime:     $('focusedTime'),
  distractedTime:  $('distractedTime'),
  contDistr:       $('continuousDistractionTime'),
  alertCount:      $('alertCount'),
  alertMetricCard: $('alertMetricCard'),
  alertBadge:      $('alertBadge'),
  alertList:       $('alertList'),
  exportBtn:       $('exportBtn'),
  historyBody:     $('historyBody'),
  toastContainer:  $('toastContainer'),
};

/* ── App state ───────────────────────────────────────────────────────────── */
let viewMode          = 'live';  // 'live' | <session_id>
let activeSessionId   = null;    // currently running session ID from worker
let sessionStartSec   = null;    // server-reported elapsed seconds at load
let sessionStartTime  = null;    // performance.now() reference
let charts            = {};
let lastAlertMessage  = '';
let knownSessions     = new Set();
let prevAlertCount    = 0;

/* ── Helpers ─────────────────────────────────────────────────────────────── */
function fmtDuration(s) {
  if (s == null || isNaN(+s)) return '--';
  const tot = Math.max(0, Math.round(+s));
  const m = Math.floor(tot / 60), sec = tot % 60;
  if (m >= 60) return `${Math.floor(m/60)}h ${m%60}m`;
  return `${m}m ${sec}s`;
}

function fmtSecs(s) {
  if (s == null || isNaN(+s)) return '--';
  return `${Math.max(0, Math.round(+s))}s`;
}

function fmtPct(v) {
  if (v == null || isNaN(+v)) return '--';
  return `${(+v).toFixed(1)}%`;
}

function fmtTs(ts) {
  if (!ts) return '--';
  return new Intl.DateTimeFormat(undefined, {
    month: 'short', day: 'numeric',
    hour: 'numeric', minute: '2-digit', second: '2-digit',
  }).format(new Date(ts));
}

function fmtShortTs(ts) {
  if (!ts) return '--';
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).format(new Date(ts));
}

async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} – ${url}`);
  return r.json();
}

/* ── Session clock (client-side tick) ────────────────────────────────────── */
function tickClock() {
  if (sessionStartTime == null) return;
  const elapsed = (sessionStartSec || 0) + (performance.now() - sessionStartTime) / 1000;
  const m = Math.floor(elapsed / 60), s = Math.floor(elapsed % 60);
  const h = Math.floor(m / 60);
  dom.sessionClock.textContent = h
    ? `${h}:${String(m % 60).padStart(2,'0')}:${String(s).padStart(2,'0')}`
    : `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

setInterval(tickClock, 1000);

/* ── Score ring ──────────────────────────────────────────────────────────── */
function setScoreRing(score) {
  if (score == null || isNaN(+score)) {
    dom.scoreArc.style.strokeDashoffset = RING_CIRCUM;
    dom.postureScore.textContent = '--';
    return;
  }
  const pct    = Math.min(100, Math.max(0, +score));
  const offset = RING_CIRCUM * (1 - pct / 100);
  dom.scoreArc.style.strokeDashoffset = offset;
  dom.postureScore.textContent = Math.round(pct);

  const color = pct >= 80 ? 'var(--green)' : pct >= 50 ? 'var(--amber)' : 'var(--red)';
  dom.scoreArc.style.stroke = color;
  dom.postureScore.style.color = color;
}

/* ── Metric cards ────────────────────────────────────────────────────────── */
function applyLiveMetrics(m) {
  setScoreRing(m.posture_score);

  const ps = m.posture_state || '';
  dom.postureBadge.textContent   = ps || '--';
  dom.postureBadge.dataset.state = ps;

  const as = m.attention_state || '';
  dom.attentionDot.dataset.state = as;
  dom.attentionValue.textContent = as || '--';
  dom.attentionValue.style.color = as === 'FOCUSED' ? 'var(--green)' : as === 'DISTRACTED' ? 'var(--red)' : '';

  const fp = m.focus_percentage ?? 0;
  dom.focusPct.textContent       = fmtPct(fp);
  dom.focusFill.style.width      = `${Math.min(100, Math.max(0, fp))}%`;
  dom.focusPct.style.color       = fp >= 75 ? 'var(--green)' : fp >= 50 ? 'var(--amber)' : 'var(--red)';

  dom.focusedTime.textContent    = fmtDuration(m.focused_time);
  dom.distractedTime.textContent = fmtDuration(m.distracted_time);
  dom.contDistr.textContent      = fmtSecs(m.continuous_distraction_time);

  // Alert count from latest metrics alert_message counts are from history
  if (m.alert_message && m.alert_message !== lastAlertMessage) {
    lastAlertMessage = m.alert_message;
    showToast(m.alert_message);
  }
}

/* ── Status indicators ───────────────────────────────────────────────────── */
function applyStatus(s) {
  // Worker / camera
  if (s.worker_running && s.camera_ok) {
    dom.workerPill.className = 'status-pill active';
    dom.workerDot.className  = 'status-dot pulse';
    dom.workerLabel.textContent = 'LIVE';
    dom.camDot.className = 'cam-dot live';
  } else if (s.worker_running && !s.camera_ok) {
    dom.workerPill.className = 'status-pill offline';
    dom.workerDot.className  = 'status-dot';
    dom.workerLabel.textContent = 'NO CAM';
    dom.camDot.className = 'cam-dot error';
  } else {
    dom.workerPill.className = 'status-pill';
    dom.workerDot.className  = 'status-dot';
    dom.workerLabel.textContent = 'STARTING';
    dom.camDot.className = 'cam-dot';
  }

  // ESP32
  if (s.esp32_connected) {
    dom.esp32Pill.className = 'status-pill esp32-pill connected';
    dom.esp32Label.textContent = 'ESP32 ✓';
  } else {
    dom.esp32Pill.className = 'status-pill esp32-pill offline';
    dom.esp32Label.textContent = 'ESP32 –';
  }

  // Active session / clock
  if (s.active_session_id && !activeSessionId) {
    activeSessionId = s.active_session_id;
    sessionStartSec  = s.session_elapsed_seconds || 0;
    sessionStartTime = performance.now();
    dom.exportBtn.disabled = false;
    dom.exportBtn.onclick = () => {
      window.open(`/api/export/${activeSessionId}.csv`, '_blank');
    };
  }
}

/* ── Charts ──────────────────────────────────────────────────────────────── */
const CHART_DEFAULTS = {
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 300 },
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor: 'rgba(11,17,32,0.92)',
      borderColor: 'rgba(80,120,200,0.2)',
      borderWidth: 1,
      titleColor: '#6b83a8',
      bodyColor: '#dce9ff',
      padding: 10,
    }
  },
  scales: {
    x: {
      ticks: { color: '#2d4060', maxTicksLimit: 8, font: { family: 'JetBrains Mono', size: 10 } },
      grid: { color: 'rgba(80,120,200,0.07)' },
    },
    y: {
      ticks: { color: '#2d4060', font: { family: 'JetBrains Mono', size: 10 } },
      grid: { color: 'rgba(80,120,200,0.07)' },
      beginAtZero: true,
    },
  },
};

function makeLineChart(canvasId, label, colorVar) {
  const ctx = document.getElementById(canvasId);
  return new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label,
        data: [],
        borderColor: colorVar,
        backgroundColor: colorVar.replace(')', ', 0.08)').replace('var(', 'var('),
        borderWidth: 2.5,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0.38,
        fill: true,
      }],
    },
    options: { ...CHART_DEFAULTS, scales: { ...CHART_DEFAULTS.scales, y: { ...CHART_DEFAULTS.scales.y, max: 100 } } },
  });
}

function makeBarChart(canvasId) {
  const ctx = document.getElementById(canvasId);
  return new Chart(ctx, {
    type: 'bar',
    data: {
      labels: ['Focused', 'Distracted'],
      datasets: [{
        data: [0, 0],
        backgroundColor: ['rgba(0,232,150,0.65)', 'rgba(255,61,90,0.65)'],
        borderRadius: 8,
        borderSkipped: false,
      }],
    },
    options: {
      ...CHART_DEFAULTS,
      scales: {
        x: { ...CHART_DEFAULTS.scales.x },
        y: { ...CHART_DEFAULTS.scales.y, title: { display: true, text: 'Minutes', color: '#2d4060', font: { size: 10 } } },
      },
    },
  });
}

function initCharts() {
  charts.posture   = makeLineChart('postureChart', 'Posture Score', '#00c8e8');
  charts.focus     = makeLineChart('focusChart',   'Focus Rate %',  '#00e896');
  charts.timeSplit = makeBarChart('timeSplitChart');
}

function updateCharts(samples) {
  if (!samples || !samples.length) return;

  const recent = samples.slice(-CHART_POINTS);
  const labels = recent.map(s => fmtShortTs(s.timestamp));

  charts.posture.data.labels = labels;
  charts.posture.data.datasets[0].data = recent.map(s => s.posture_score ?? null);
  charts.posture.update('none');

  charts.focus.data.labels = labels;
  charts.focus.data.datasets[0].data = recent.map(s => s.focus_percentage ?? null);
  charts.focus.update('none');

  const latest = samples[samples.length - 1];
  if (latest) {
    charts.timeSplit.data.datasets[0].data = [
      +(latest.focused_time    || 0) / 60,
      +(latest.distracted_time || 0) / 60,
    ];
    charts.timeSplit.update('none');
  }
}

/* ── Alert list ──────────────────────────────────────────────────────────── */
function alertClass(msg) {
  if (!msg) return '';
  if (msg.includes('CRITICAL')) return 'critical';
  if (msg.includes('POSTURE'))  return 'posture';
  return '';
}

function updateAlertList(samples) {
  const alerts = samples.filter(s => s.alert_message).slice(-30).reverse();
  dom.alertCount.textContent = String(alerts.length);
  dom.alertBadge.textContent = String(alerts.length);

  if (alerts.length !== prevAlertCount && alerts.length > prevAlertCount) {
    dom.alertMetricCard.classList.add('has-alerts');
    setTimeout(() => dom.alertMetricCard.classList.remove('has-alerts'), 800);
  }
  prevAlertCount = alerts.length;

  if (!alerts.length) {
    dom.alertList.innerHTML = '<li class="alert-empty">No alerts recorded this session.</li>';
    return;
  }

  dom.alertList.innerHTML = '';
  for (const a of alerts) {
    const li = document.createElement('li');
    li.className = `alert-item ${alertClass(a.alert_message)}`;
    li.innerHTML = `
      <span class="alert-time">${fmtTs(a.timestamp)}</span>
      <span class="alert-msg">${a.alert_message}</span>
    `;
    dom.alertList.appendChild(li);
  }
}

/* ── Toast notifications ─────────────────────────────────────────────────── */
function showToast(msg) {
  const div = document.createElement('div');
  div.className = `toast ${alertClass(msg)}`;
  div.textContent = `⚠ ${msg}`;
  dom.toastContainer.appendChild(div);
  setTimeout(() => div.remove(), 4200);
}

/* ── Session picker & history table ─────────────────────────────────────── */
function buildSessionRow(s) {
  const isActive = s.ended_at == null;
  const dur = (s.total_focused_time || 0) + (s.total_distracted_time || 0);
  return `
    <tr data-id="${s.session_id}">
      <td>${s.session_id.slice(0, 8)}…</td>
      <td>${fmtTs(s.started_at)}</td>
      <td>${s.ended_at ? fmtTs(s.ended_at) : '—'}</td>
      <td>${fmtDuration(s.total_focused_time)}</td>
      <td>${fmtDuration(s.total_distracted_time)}</td>
      <td>${s.final_focus_percentage != null ? fmtPct(s.final_focus_percentage) : '—'}</td>
      <td><span class="session-status ${isActive ? 'active' : 'finished'}">${isActive ? '● Live' : 'Done'}</span></td>
    </tr>
  `;
}

async function loadSessions() {
  const { sessions } = await fetchJson('/api/sessions?limit=50');

  // Update history table
  if (!sessions.length) {
    dom.historyBody.innerHTML = '<tr><td colspan="7" class="table-empty">No past sessions yet.</td></tr>';
  } else {
    dom.historyBody.innerHTML = sessions.map(buildSessionRow).join('');
    dom.historyBody.querySelectorAll('tr[data-id]').forEach(row => {
      row.style.cursor = 'pointer';
      row.addEventListener('click', () => {
        const id = row.dataset.id;
        dom.sessionSelect.value = id === activeSessionId ? 'live' : id;
        dom.sessionSelect.dispatchEvent(new Event('change'));
      });
    });
  }

  // Rebuild session picker options (keep "live" first)
  const currentVal = dom.sessionSelect.value;
  // Remove all non-live options
  [...dom.sessionSelect.options].slice(1).forEach(o => o.remove());

  for (const s of sessions) {
    if (s.session_id === activeSessionId) continue; // already shown as live
    const opt = new Option(
      `${fmtTs(s.started_at)} · ${s.session_id.slice(0, 8)}`,
      s.session_id,
    );
    dom.sessionSelect.add(opt);
  }

  // Restore selection
  if ([...dom.sessionSelect.options].some(o => o.value === currentVal)) {
    dom.sessionSelect.value = currentVal;
  }
}

/* ── Poll: live metrics (1 s) ────────────────────────────────────────────── */
async function pollLive() {
  try {
    const [statusData, metricsData] = await Promise.all([
      fetchJson('/api/status'),
      fetchJson('/api/live/metrics'),
    ]);

    applyStatus(statusData);

    if (metricsData.available && viewMode === 'live') {
      applyLiveMetrics(metricsData);
    }
  } catch (e) {
    console.warn('[live poll]', e.message);
  }
}

/* ── Poll: chart + alert history (3 s) ───────────────────────────────────── */
async function pollHistory() {
  try {
    let samples;

    if (viewMode === 'live') {
      if (!activeSessionId) return;
      const data = await fetchJson(`/api/live/history?limit=80`);
      samples = data.samples || [];
    } else {
      const data = await fetchJson(`/api/sessions/${viewMode}/samples?limit=80`);
      samples = data.samples || [];

      // For historical mode, also update the metric cards with last sample
      if (samples.length) applyLiveMetrics(samples[samples.length - 1]);
    }

    updateCharts(samples);
    updateAlertList(samples);

  } catch (e) {
    console.warn('[history poll]', e.message);
  }
}

/* ── Session select handler ──────────────────────────────────────────────── */
dom.sessionSelect.addEventListener('change', e => {
  viewMode = e.target.value;  // 'live' or a session_id
  // Enable export only when a real session is selected
  if (viewMode !== 'live') {
    dom.exportBtn.disabled = false;
    dom.exportBtn.onclick = () => window.open(`/api/export/${viewMode}.csv`, '_blank');
  } else if (activeSessionId) {
    dom.exportBtn.disabled = false;
    dom.exportBtn.onclick = () => window.open(`/api/export/${activeSessionId}.csv`, '_blank');
  }
  pollHistory();
});

/* ── Init ────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', async () => {
  initCharts();

  // Kick off immediately
  await pollLive();
  await pollHistory();
  await loadSessions();

  // Recurring intervals
  setInterval(pollLive,    LIVE_POLL_MS);
  setInterval(pollHistory, HISTORY_POLL_MS);
  setInterval(loadSessions, SESSION_POLL_MS);
});
