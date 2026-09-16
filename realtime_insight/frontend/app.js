/* Realtime Insight — dashboard client
 * - koneksi WebSocket + auto-reconnect
 * - render kartu metrik + sparkline
 * - chart utama (Chart.js) dengan pilihan metrik
 * - daftar insight + kartu kesimpulan
 * - tabel riwayat laporan
 */

"use strict";

const state = {
  cycle: 0,
  trends: [],
  insights: [],
  conclusion: null,
  socket: null,
  reconnectAttempts: 0,
  selectedMetric: null,
  charts: {},
};

/* ------------------------------------------------------------------ */
/* Utilities                                                          */
/* ------------------------------------------------------------------ */
const $ = (sel) => document.querySelector(sel);
const fmt = (v, d = 2) =>
  v === null || v === undefined || Number.isNaN(v)
    ? "-"
    : Number(v).toLocaleString("id-ID", { maximumFractionDigits: d });
const fmtPct = (v) => (v === null || v === undefined ? "-" : `${v > 0 ? "+" : ""}${fmt(v, 2)}%`);
const fmtTime = (iso) => {
  const d = new Date(iso);
  return d.toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
};

function setWs(status, label) {
  const el = $("#wsStatus");
  el.className = "ws-status " + status;
  el.innerHTML = `<span class="dot"></span> ${label}`;
}

function updateClock() {
  $("#clock").textContent = new Date().toLocaleTimeString("id-ID", { hour12: false });
}

/* ------------------------------------------------------------------ */
/* Chart palettes                                                     */
/* ------------------------------------------------------------------ */
const COLORS = ["#2f81f7", "#7c5cff", "#2ecc71", "#ffc24b", "#ff5b5b", "#00d0d0"];

/* ------------------------------------------------------------------ */
/* Render: kartu metrik                                               */
/* ------------------------------------------------------------------ */
function renderCards() {
  const wrap = $("#metricCards");
  wrap.innerHTML = "";
  state.trends.forEach((t, i) => {
    const delta = t.delta_pct_vs_prev;
    const cls = delta === null ? "" : delta >= 0 ? "up" : "down";
    const arr = delta === null ? "" : delta >= 0 ? "▲" : "▼";
    const card = document.createElement("div");
    card.className = "metric-card fade-in";
    card.style.setProperty("--accent", COLORS[i % COLORS.length]);
    card.innerHTML = `
      <div class="m-name">${esc(t.metric)}</div>
      <div class="m-value">${fmt(t.last_value)} <small style="color:var(--muted)">${esc(t.unit || "")}</small></div>
      <div class="m-delta ${cls}">${arr} ${fmtPct(delta)} <span style="color:var(--muted);font-weight:400">vs jendela sebelumnya</span></div>
      <div class="m-sub">mean ${fmt(t.mean)} · median ${fmt(t.median)} · σ ${fmt(t.stdev, 1)}</div>
      <div class="sparkline"><canvas id="spark-${i}" width="320" height="46"></canvas></div>`;
    wrap.appendChild(card);
    drawSparkline(i, t);
  });
}

function drawSparkline(index, trend) {
  const canvas = document.getElementById(`spark-${index}`);
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const vals = trend.series.map((p) => p.v);
  if (vals.length < 2) return;
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const color = COLORS[index % COLORS.length];
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  vals.forEach((v, i) => {
    const x = (i / (vals.length - 1)) * (w - 4) + 2;
    const y = h - 4 - ((v - min) / span) * (h - 8);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
}

/* ------------------------------------------------------------------ */
/* Render: chart utama                                                */
/* ------------------------------------------------------------------ */
function setupChartSelector() {
  const existing = document.getElementById("chartMetric");
  if (existing) return existing;
  const head = document.querySelector(".panel-head .legend-hint");
  const sel = document.createElement("select");
  sel.id = "chartMetric";
  sel.className = "chart-select";
  sel.addEventListener("change", () => {
    state.selectedMetric = sel.value;
    rebuildMainChart();
  });
  $(".panel .panel-head").appendChild(sel);
  return sel;
}

function renderChartSelector() {
  const sel = document.getElementById("chartMetric");
  if (!sel) return;
  const opts = state.trends.map((t) => t.metric);
  if (!opts.includes(sel.value)) {
    sel.innerHTML = "";
    opts.forEach((m) => {
      const o = document.createElement("option");
      o.value = m;
      o.textContent = m;
      sel.appendChild(o);
    });
    state.selectedMetric = opts[0] ?? null;
  }
}

function rebuildMainChart() {
  const ctx = document.getElementById("trendChart");
  if (!ctx || !state.selectedMetric) return;
  const trend = state.trends.find((t) => t.metric === state.selectedMetric);
  if (!trend) return;

  const labels = trend.series.map((p) => new Date(p.t).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }));
  const data = trend.series.map((p) => p.v);
  const ma = trend.moving_average || [];

  if (state.charts.main) state.charts.main.destroy();
  state.charts.main = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: trend.metric,
          data,
          borderColor: "#2f81f7",
          backgroundColor: "rgba(47,129,247,.12)",
          fill: true,
          tension: 0.35,
          pointRadius: 1.5,
        },
        {
          label: "Moving avg 5-titik",
          data: ma,
          borderColor: "#ffc24b",
          borderDash: [6, 4],
          borderWidth: 1.6,
          pointRadius: 0,
          tension: 0.3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: "#8b96b8", usePointStyle: true } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.y, 3)}` } },
      },
      scales: {
        x: { ticks: { color: "#8b96b8", maxTicksLimit: 10 }, grid: { color: "#1e2745" } },
        y: { ticks: { color: "#8b96b8" }, grid: { color: "#1e2745" } },
      },
    },
  });
}

/* ------------------------------------------------------------------ */
/* Render: insight & conclusion                                       */
/* ------------------------------------------------------------------ */
const SEV_ICON = { info: "•", warning: "⚠", critical: "🚨" };

function renderInsights() {
  const list = $("#insightList");
  if (!state.insights.length) {
    list.innerHTML = `<p class="empty">Belum ada insight — menunggu data ...</p>`;
    return;
  }
  list.innerHTML = "";
  state.insights.slice().reverse().forEach((ins) => {
    const div = document.createElement("div");
    div.className = `insight sev-${ins.severity} fade-in`;
    div.innerHTML = `
      <span class="badge-ic">${SEV_ICON[ins.severity] || "•"}</span>
      <div>
        <div class="i-label">${esc(ins.label)}</div>
        <div class="i-meta">${esc(ins.type)} · ${esc(ins.metric)} · ${fmtTime(ins.created_at)}</div>
      </div>`;
    list.appendChild(div);
  });
}

function renderConclusion() {
  const box = $("#conclusionBox");
  const meta = $("#conclusionMeta");
  if (!state.conclusion) {
    box.innerHTML = `<p class="empty">Kesimpulan akan muncul saat ada perubahan signifikan (delta ≥ threshold).</p>`;
    meta.textContent = "—";
    return;
  }
  box.innerHTML = `<p class="fade-in">${esc(state.conclusion.content)}</p>`;
  meta.textContent = `${state.conclusion.provider.toUpperCase()} · ${fmtTime(state.conclusion.created_at)}`;
}

/* ------------------------------------------------------------------ */
/* Riwayat laporan                                                    */
/* ------------------------------------------------------------------ */
async function loadReports() {
  try {
    const res = await fetch("/api/reports/conclusions?limit=50");
    const rows = await res.json();
    const tbody = $("#reportTable");
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="4"><p class="empty">Belum ada kesimpulan tersimpan.</p></td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map((r) => `
      <tr>
        <td class="time">${fmtTime(r.created_at)}</td>
        <td><span class="prov">${esc(r.provider)}</span></td>
        <td><span class="trig">${r.trigger_count}</span></td>
        <td>${esc(r.content)}</td>
      </tr>`).join("");
  } catch (err) {
    console.error("Gagal memuat riwayat:", err);
  }
}

/* ------------------------------------------------------------------ */
/* Payload handling                                                   */
/* ------------------------------------------------------------------ */
function applyPayload(payload) {
  state.trends = payload.trends || [];
  state.insights = payload.insights || [];
  state.conclusion = payload.conclusion || null;
  state.cycle = payload.cycle || state.cycle;

  $("#cycleInfo").textContent = `Siklus #${state.cycle}`;
  if (payload.sources && payload.sources.length) $("#sourceLabel").textContent = payload.sources.join(", ");
  renderCards();
  renderChartSelector();
  renderInsights();
  renderConclusion();
  rebuildMainChart();
}

async function loadInitial() {
  try {
    const res = await fetch("/api/data");
    const payload = await res.json();
    applyPayload(payload);
  } catch (err) {
    console.warn("Belum ada data di /api/data:", err);
  }
}

/* ------------------------------------------------------------------ */
/* WebSocket                                                          */
/* ------------------------------------------------------------------ */
function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/api/ws/live`);
  state.socket = ws;

  ws.onopen = () => {
    setWs("online", "Terhubung — live");
    state.reconnectAttempts = 0;
  };
  ws.onmessage = (ev) => {
    try {
      applyPayload(JSON.parse(ev.data));
    } catch (err) {
      console.error("Payload WS tidak valid:", err);
    }
  };
  ws.onclose = () => {
    setWs("offline", "Terputus — menghubungkan ulang...");
    scheduleReconnect();
  };
  ws.onerror = () => ws.close();
}

function scheduleReconnect() {
  const delay = Math.min(1000 * 2 ** state.reconnectAttempts, 15000);
  state.reconnectAttempts += 1;
  setTimeout(() => {
    const stillAlive = document.visibilityState !== "hidden";
    if (stillAlive) connectWs();
  }, delay);
}

/* ------------------------------------------------------------------ */
/* Actions                                                            */
/* ------------------------------------------------------------------ */
async function runNow() {
  const btn = $("#runNowBtn");
  btn.disabled = true;
  btn.textContent = "⏳ Memproses...";
  try {
    await fetch("/api/trigger", { method: "POST" });
  } finally {
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = "▶ Jalankan Sekarang";
    }, 1200);
  }
}

/* ------------------------------------------------------------------ */
/* Init                                                               */
/* ------------------------------------------------------------------ */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (m) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[m]));
}

document.addEventListener("DOMContentLoaded", () => {
  setupChartSelector();
  updateClock();
  setInterval(updateClock, 1000);
  loadInitial();
  loadReports();
  connectWs();

  $("#runNowBtn").addEventListener("click", runNow);
  $("#refreshReportsBtn").addEventListener("click", loadReports);

  // ambil info interval dari /health
  fetch("/api/health")
    .then((r) => r.json())
    .then((h) => {
      if (h.config && h.config.update_interval_s) {
        $("#intervalLabel").textContent = `${h.config.update_interval_s}s`;
      }
    })
    .catch(() => {});
});