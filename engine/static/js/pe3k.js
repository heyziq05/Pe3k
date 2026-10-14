/* Pe3k shared front-end helpers: theme, API, formatting, toasts, charts. */
(function () {
  "use strict";

  const root = document.documentElement;
  const THEME_KEY = "pe3k-theme";

  // ------------------------------------------------------------------ theme
  function savedTheme() {
    try { return localStorage.getItem(THEME_KEY); } catch (e) { return null; }
  }
  function applyTheme(theme, persist) {
    root.setAttribute("data-theme", theme);
    root.setAttribute("data-bs-theme", theme);
    if (persist) { try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* storage unavailable */ } }
    const btn = document.getElementById("themeToggle");
    if (btn) btn.setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
    document.dispatchEvent(new CustomEvent("pe3k:theme", { detail: { theme } }));
  }
  function currentTheme() { return root.getAttribute("data-theme") || "dark"; }

  document.addEventListener("DOMContentLoaded", () => {
    // Modals live at <body> level so page animations on <main> can't trap them under the backdrop.
    document.querySelectorAll("main .modal").forEach((m) => document.body.appendChild(m));
    const btn = document.getElementById("themeToggle");
    if (btn) btn.addEventListener("click", () => applyTheme(currentTheme() === "dark" ? "light" : "dark", true));
    if (window.matchMedia) {
      window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", (e) => {
        if (!savedTheme()) applyTheme(e.matches ? "light" : "dark", false);
      });
    }
    applyTheme(currentTheme(), false);
    poll(updateNav, 30000);
    initLiveLogo();
    initPageTransitions();
  });

  // ------------------------------------------------------------- live logo
  const reduceMotion = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* While the pointer is over the top bar, the logo's iris looks toward it. */
  function initLiveLogo() {
    const logo = document.querySelector(".brand .pe3k-logo");
    const iris = logo && logo.querySelector(".logo-iris");
    const nav = document.querySelector(".navbar-glass");
    if (!iris || !nav) return;
    const MAX = 3.4; // logo units (viewBox is 64)
    let frame = null;
    nav.addEventListener("pointermove", (ev) => {
      if (reduceMotion() || frame) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        const r = logo.getBoundingClientRect();
        const dx = ev.clientX - (r.left + r.width / 2), dy = ev.clientY - (r.top + r.height / 2);
        const dist = Math.hypot(dx, dy) || 1;
        const k = Math.min(dist / 60, 1) * MAX / dist;
        iris.style.transform = `translate(${(dx * k).toFixed(2)}px, ${(dy * k * 0.7).toFixed(2)}px)`;
      });
    });
    nav.addEventListener("pointerleave", () => { iris.style.transform = ""; });
  }

  // -------------------------------------------------------- page transitions
  /* Fade the content out before following an internal link; the new page fades in via CSS. */
  function initPageTransitions() {
    document.addEventListener("click", (ev) => {
      const a = ev.target.closest("a[href]");
      if (!a || ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
      if (a.target && a.target !== "_self") return;
      if (a.hasAttribute("download") || a.getAttribute("href").startsWith("#")) return;
      const url = new URL(a.href, location.href);
      if (url.origin !== location.origin || url.pathname.startsWith("/export/") || url.pathname.startsWith("/api/")) return;
      if (url.pathname === location.pathname && url.search === location.search) return;
      ev.preventDefault();
      document.body.classList.add("pe3k-leaving");
      setTimeout(() => { location.href = url.href; }, reduceMotion() ? 140 : 200);
    });
    // Coming back via the back/forward cache: make sure the page is visible again.
    window.addEventListener("pageshow", () => document.body.classList.remove("pe3k-leaving"));
  }

  // -------------------------------------------------------------------- api
  async function api(method, url, body) {
    const opts = { method, headers: { Accept: "application/json" } };
    if (method !== "GET") {
      opts.headers["X-Pe3k-Request"] = "1";
      if (body !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
    }
    let res;
    try {
      res = await fetch(url, opts);
    } catch (e) {
      const err = new Error("Cannot reach the Pe3k server. Is it still running?");
      err.network = true;
      throw err;
    }
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) {
      const err = new Error((data && data.error) || `Request failed (${res.status})`);
      err.status = res.status;
      err.fields = (data && data.fields) || {};
      throw err;
    }
    return data;
  }

  // ----------------------------------------------------------------- polling
  function poll(fn, ms) {
    let timer = null;
    let stopped = false;
    const run = async () => {
      if (stopped) return;
      try { await fn(); } catch (e) { console.warn("[Pe3k] poll error", e); }
      if (!stopped) timer = setTimeout(run, ms);
    };
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) { clearTimeout(timer); timer = null; }
      else if (!timer && !stopped) run();
    });
    run();
    return { stop() { stopped = true; clearTimeout(timer); }, now() { clearTimeout(timer); run(); } };
  }

  // --------------------------------------------------------------- formatting
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const toDate = (iso) => (iso ? new Date(iso) : null);

  function fmtDateTime(iso, withSeconds) {
    const d = toDate(iso);
    if (!d || isNaN(d)) return "—";
    return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: withSeconds ? "2-digit" : undefined });
  }
  function fmtTime(iso) {
    const d = toDate(iso);
    return d && !isNaN(d) ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "—";
  }
  function timeAgo(iso) {
    const d = toDate(iso);
    if (!d || isNaN(d)) return "never";
    const s = Math.round((Date.now() - d.getTime()) / 1000);
    if (s < 10) return "just now";
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  }
  function fmtDuration(seconds) {
    if (seconds == null) return "ongoing";
    const s = Math.max(0, Math.round(seconds));
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    if (d) return `${d}d ${h}h`;
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m`;
    return `${s}s`;
  }
  function fmtBytes(n) {
    if (n == null || isNaN(n)) return "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0, v = Number(n);
    while (v >= 1000 && i < units.length - 1) { v /= 1000; i++; }
    return `${v.toFixed(v >= 100 || i === 0 ? 0 : v >= 10 ? 1 : 2)} ${units[i]}`;
  }
  function fmtMbps(v) {
    if (v == null || isNaN(v)) return "—";
    return v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2);
  }
  function fmtMs(v) {
    if (v == null || isNaN(v)) return "—";
    return `${v < 10 ? Number(v).toFixed(1) : Math.round(v)} ms`;
  }
  function fmtPct(v) {
    if (v == null || isNaN(v)) return "—";
    return `${Number(v).toFixed(v >= 99.95 || v === 0 ? 0 : 2)}%`;
  }

  const STATUS = {
    online: ["status-online", "bi-check-circle-fill", "Online"],
    unstable: ["status-unstable", "bi-exclamation-triangle-fill", "Unstable"],
    offline: ["status-offline", "bi-x-circle-fill", "Offline"],
    unknown: ["status-unknown", "bi-question-circle", "Pending"],
  };
  function statusPill(status, title) {
    const [cls, icon, label] = STATUS[status] || STATUS.unknown;
    return `<span class="status ${cls}" ${title ? `title="${esc(title)}"` : ""}><i class="bi ${icon}" aria-hidden="true"></i>${label}</span>`;
  }
  const TYPE_ICONS = { router: "bi-router", laptop: "bi-laptop", desktop: "bi-pc-display", phone: "bi-phone", tablet: "bi-tablet",
    printer: "bi-printer", server: "bi-hdd-stack", iot: "bi-cpu", other: "bi-question-diamond" };
  const TYPE_LABELS = { router: "Router", laptop: "Laptop", desktop: "Desktop", phone: "Phone", tablet: "Tablet", printer: "Printer",
    server: "Server", iot: "IoT device", other: "Other" };
  function typeIcon(t) { return `<i class="bi ${TYPE_ICONS[t] || TYPE_ICONS.other}" aria-hidden="true"></i>`; }

  function emptyState(icon, title, text, action) {
    return `<div class="empty"><i class="bi ${icon}" aria-hidden="true"></i><h3>${esc(title)}</h3><p>${esc(text)}</p>${action || ""}</div>`;
  }
  function skeletonRows(cols, rows) {
    let html = "";
    for (let r = 0; r < (rows || 4); r++) {
      html += "<tr>" + Array.from({ length: cols }, () => `<td><span class="skeleton" style="width:${50 + Math.random() * 40}%"></span></td>`).join("") + "</tr>";
    }
    return html;
  }

  // ------------------------------------------------------------------ toasts
  function toast(message, kind) {
    const host = document.getElementById("toasts");
    if (!host) return;
    const icons = { ok: "bi-check-circle-fill ok-text", error: "bi-x-circle-fill bad-text", warn: "bi-exclamation-triangle-fill warn-text", info: "bi-info-circle-fill info-text" };
    const el = document.createElement("div");
    el.className = "toast";
    el.setAttribute("role", kind === "error" ? "alert" : "status");
    el.innerHTML = `<div class="toast-body"><i class="bi ${icons[kind || "info"]}" aria-hidden="true"></i><div class="flex-grow-1">${esc(message)}</div>
      <button type="button" class="btn-close btn-close-sm ms-2" data-bs-dismiss="toast" aria-label="Close"></button></div>`;
    host.appendChild(el);
    const t = new bootstrap.Toast(el, { delay: kind === "error" ? 7000 : 3500 });
    el.addEventListener("hidden.bs.toast", () => el.remove());
    t.show();
  }

  // ---------------------------------------------------------- confirm dialog
  function confirmDialog({ title, body, okText, danger }) {
    return new Promise((resolve) => {
      const wrap = document.createElement("div");
      wrap.className = "modal fade";
      wrap.tabIndex = -1;
      wrap.innerHTML = `<div class="modal-dialog modal-dialog-centered"><div class="modal-content">
        <div class="modal-header"><h2 class="modal-title">${esc(title)}</h2><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div>
        <div class="modal-body text-2">${body}</div>
        <div class="modal-footer"><button type="button" class="btn btn-glass" data-bs-dismiss="modal">Cancel</button>
        <button type="button" class="btn ${danger ? "btn-danger" : "btn-accent"}" data-ok>${esc(okText || "Confirm")}</button></div></div></div>`;
      document.body.appendChild(wrap);
      const modal = new bootstrap.Modal(wrap);
      let result = false;
      wrap.querySelector("[data-ok]").addEventListener("click", () => { result = true; modal.hide(); });
      wrap.addEventListener("hidden.bs.modal", () => { wrap.remove(); resolve(result); });
      modal.show();
    });
  }

  // ------------------------------------------------------------------- forms
  function clearErrors(form) {
    form.querySelectorAll(".is-invalid").forEach((el) => el.classList.remove("is-invalid"));
    form.querySelectorAll(".invalid-feedback[data-dyn]").forEach((el) => el.remove());
    const general = form.querySelector("[data-form-error]");
    if (general) { general.classList.add("d-none"); general.textContent = ""; }
  }
  function showErrors(form, err) {
    clearErrors(form);
    const fields = err.fields || {};
    let shown = 0;
    Object.entries(fields).forEach(([name, msg]) => {
      const input = form.querySelector(`[name="${name}"]`);
      if (!input) return;
      input.classList.add("is-invalid");
      const fb = document.createElement("div");
      fb.className = "invalid-feedback";
      fb.dataset.dyn = "1";
      fb.textContent = msg;
      (input.closest(".form-check, .input-group") || input).insertAdjacentElement("afterend", fb);
      if (fb.previousElementSibling && fb.previousElementSibling.classList.contains("form-check")) fb.style.display = "block";
      if (!shown++) input.focus();
    });
    const general = form.querySelector("[data-form-error]");
    const unplaced = Object.entries(fields).filter(([n]) => !form.querySelector(`[name="${n}"]`)).map(([, m]) => m);
    if (general && (!shown || unplaced.length)) {
      general.textContent = unplaced.length ? unplaced.join(" ") : err.message;
      general.classList.remove("d-none");
    }
  }
  function setBusy(btn, busy, label) {
    if (!btn) return;
    if (busy) {
      btn.dataset.label = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner-border spinner-border-sm" aria-hidden="true"></span>${label ? esc(label) : ""}`;
    } else if (btn.dataset.label) {
      btn.disabled = false;
      btn.innerHTML = btn.dataset.label;
    }
  }

  // --------------------------------------------------------------------- nav
  async function updateNav() {
    const data = await api("GET", "/api/nav");
    const badge = document.getElementById("navAlertCount");
    if (badge) {
      badge.textContent = data.alerts_open > 99 ? "99+" : data.alerts_open;
      badge.classList.toggle("d-none", !data.alerts_open);
    }
    const pill = document.getElementById("navScanner");
    if (pill) {
      const s = data.scan;
      const color = s.running ? "var(--info-text)" : s.engine === "manual" ? "var(--muted)" : s.ready ? "var(--ok-text)" : "var(--warn-text)";
      pill.querySelector(".dot").style.color = color;
      pill.querySelector(".dot").classList.toggle("pulse", !!s.running);
      pill.querySelector(".label").textContent = s.running ? `${s.engine_label}: scanning…` : `${s.engine_label}${s.engine !== "manual" && !s.ready ? " · not ready" : ""}`;
      pill.title = "Active discovery engine";
    }
  }

  // ------------------------------------------------------------------ charts
  const charts = new Set();
  function cssVar(name) { return getComputedStyle(root).getPropertyValue(name).trim(); }
  function chartTheme() {
    return { text: cssVar("--text-2"), muted: cssVar("--axis"), grid: cssVar("--grid"), surface: cssVar("--glass-strong"),
      border: cssVar("--glass-border-strong"), ink: cssVar("--text") };
  }
  const crosshair = {
    id: "pe3kCrosshair",
    afterDatasetsDraw(chart) {
      const active = chart.tooltip && chart.tooltip.getActiveElements();
      if (!active || !active.length || chart.config.type !== "line") return;
      const x = active[0].element.x;
      const { top, bottom } = chart.chartArea;
      const ctx = chart.ctx;
      ctx.save();
      ctx.strokeStyle = chartTheme().muted;
      ctx.globalAlpha = 0.5;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
      ctx.restore();
    },
  };

  function themedOptions(opts) {
    const t = chartTheme();
    const o = opts || {};
    o.scales = o.scales || {};
    Object.values(o.scales).forEach((s) => {
      s.ticks = Object.assign({}, s.ticks, { color: t.muted, font: { size: 11 } });
      s.grid = Object.assign({}, s.grid, { color: t.grid, drawTicks: false, tickColor: t.grid });
      s.border = Object.assign({}, s.border, { color: t.grid, display: false });
      if (s.title) s.title.color = t.muted;
    });
    o.plugins = o.plugins || {};
    o.plugins.legend = Object.assign({ display: false }, o.plugins.legend);
    if (o.plugins.legend.labels) o.plugins.legend.labels.color = t.text;
    o.plugins.tooltip = Object.assign({}, o.plugins.tooltip, {
      backgroundColor: t.surface, titleColor: t.ink, bodyColor: t.text, borderColor: t.border, borderWidth: 1,
      padding: 10, cornerRadius: 10, boxPadding: 4, usePointStyle: true,
    });
    return o;
  }

  function seriesColor(varName, alpha) {
    const c = cssVar(varName);
    if (alpha == null) return c;
    const hex = c.replace("#", "");
    const n = parseInt(hex.length === 3 ? hex.split("").map((x) => x + x).join("") : hex, 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
  }

  function paintDatasets(chart) {
    chart.data.datasets.forEach((ds) => {
      if (ds.pe3kSeries) {
        ds.borderColor = seriesColor(ds.pe3kSeries);
        ds.pointBackgroundColor = seriesColor(ds.pe3kSeries);
        ds.pointHoverBackgroundColor = seriesColor(ds.pe3kSeries);
        ds.pointBorderColor = chartTheme().surface;
        if (ds.pe3kFill) {
          ds.backgroundColor = (ctx) => {
            const area = ctx.chart.chartArea;
            if (!area) return seriesColor(ds.pe3kSeries, 0.12);
            const g = ctx.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
            g.addColorStop(0, seriesColor(ds.pe3kSeries, 0.22));
            g.addColorStop(1, seriesColor(ds.pe3kSeries, 0.0));
            return g;
          };
        } else if (chart.config.type === "bar") {
          ds.backgroundColor = seriesColor(ds.pe3kSeries);
          ds.borderColor = "transparent";
        }
      }
    });
  }

  function makeChart(canvas, config) {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    config.options = themedOptions(Object.assign({ responsive: true, maintainAspectRatio: false, animation: { duration: 300 },
      interaction: { mode: "index", intersect: false } }, config.options));
    config.plugins = (config.plugins || []).concat([crosshair]);
    const chart = new Chart(canvas, config);
    chart._pe3kOptions = config.options;
    paintDatasets(chart);
    chart.update("none");
    charts.add(chart);
    setChartEmpty(chart, true); // until the first data arrives
    return chart;
  }
  document.addEventListener("pe3k:theme", () => {
    charts.forEach((chart) => {
      themedOptions(chart.config.options); // raw options, never the resolver proxy
      paintDatasets(chart);
      chart.update("none");
    });
  });

  function lineDataset(label, series, data, extra) {
    return Object.assign({ label, data, pe3kSeries: series, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, pointHitRadius: 12,
      tension: 0.3, cubicInterpolationMode: "monotone", spanGaps: false, fill: false }, extra || {});
  }

  function timeTickFormatter(rangeMs) {
    return (value) => {
      const d = new Date(value);
      if (rangeMs > 2 * 86400000) return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
      if (rangeMs < 15 * 60000) return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    };
  }
  function timeScale(rangeMs) {
    return { type: "linear", ticks: { callback: timeTickFormatter(rangeMs), maxTicksLimit: 6, maxRotation: 0, padding: 8 }, grid: { display: false } };
  }
  function setXRange(chart, min, max) {
    const x = chart.config.options.scales.x;
    x.min = min;
    x.max = max;
    x.ticks.callback = timeTickFormatter(max - min);
  }
  function setChartEmpty(chart, empty) {
    const box = chart.canvas.closest(".chart-box");
    if (box) box.classList.toggle("is-empty", !!empty);
  }

  // ------------------------------------------------------------------ export
  window.Pe3k = {
    api, poll, esc, toast, confirm: confirmDialog, clearErrors, showErrors, setBusy,
    fmtDateTime, fmtTime, timeAgo, fmtDuration, fmtBytes, fmtMbps, fmtMs, fmtPct,
    statusPill, typeIcon, TYPE_LABELS, emptyState, skeletonRows,
    makeChart, lineDataset, timeScale, setChartEmpty, setXRange, seriesColor, updateNav, theme: currentTheme,
  };
})();
