/* Device History page */
(function () {
  "use strict";
  const P = window.Pe3k;
  const $ = (id) => document.getElementById(id);
  const deviceId = Number($("historyRoot").dataset.device);
  const SPAN = { "1h": 3600e3, "24h": 86400e3, "7d": 7 * 86400e3, "30d": 30 * 86400e3 };
  let windowSel = "24h";
  let page = 1;
  let total = 0;
  const perPage = 15;

  const latChart = P.makeChart($("latChart"), {
    type: "line",
    data: { datasets: [P.lineDataset("Latency", "--series-1", [], { pe3kFill: true, fill: "origin" })] },
    options: {
      scales: { x: P.timeScale(SPAN["24h"]), y: { beginAtZero: true, ticks: { callback: (v) => `${v} ms` } } },
      plugins: { tooltip: { callbacks: { title: (i) => P.fmtDateTime(new Date(i[0].parsed.x).toISOString()), label: (c) => ` Latency: ${P.fmtMs(c.parsed.y)}` } } },
    },
  });
  const statusColor = (pct) => getComputedStyle(document.documentElement).getPropertyValue(pct >= 99 ? "--ok" : pct >= 90 ? "--warn" : "--bad").trim();
  const availChart = P.makeChart($("availChart"), {
    type: "bar",
    data: { datasets: [{ label: "Availability", data: [], borderRadius: 4, borderSkipped: "bottom", barPercentage: 0.9, categoryPercentage: 0.9 }] },
    options: {
      scales: { x: Object.assign(P.timeScale(SPAN["24h"]), { offset: false }), y: { min: 0, max: 100, ticks: { callback: (v) => `${v}%`, stepSize: 25 } } },
      plugins: { tooltip: { callbacks: { title: (i) => P.fmtDateTime(new Date(i[0].parsed.x).toISOString()),
        label: (c) => ` ${c.parsed.y >= 99 ? "Healthy" : c.parsed.y >= 90 ? "Degraded" : "Outage"}: ${P.fmtPct(c.parsed.y)} answered` } } },
    },
  });
  function paintAvail() {
    const ds = availChart.data.datasets[0];
    ds.backgroundColor = ds.data.map((p) => statusColor(p.y));
    availChart.update("none");
  }
  document.addEventListener("pe3k:theme", paintAvail);

  async function loadSummary() {
    const d = await P.api("GET", `/api/devices/${deviceId}/history?window=${windowSel}&page=${page}&per_page=${perPage}`);
    const dev = d.device, u = d.uptime;
    $("hStatus").innerHTML = dev.monitoring_enabled ? P.statusPill(dev.status) : '<span class="chip"><i class="bi bi-pause-fill"></i>Paused</span>';
    $("hSeen").textContent = `Last seen ${P.timeAgo(dev.last_seen)} · ${dev.ip_address}`;
    $("hWindowChip").textContent = windowSel;
    $("hUptime").textContent = P.fmtPct(u.uptime_percent);
    const bar = $("hUptimeBar");
    bar.classList.toggle("warn", u.uptime_percent != null && u.uptime_percent < 99 && u.uptime_percent >= 90);
    bar.classList.toggle("bad", u.uptime_percent != null && u.uptime_percent < 90);
    bar.firstElementChild.style.width = `${u.uptime_percent || 0}%`;
    const w = d.uptime_windows;
    $("hUptimeOther").textContent = `24h ${P.fmtPct(w["24h"])} · 7d ${P.fmtPct(w["7d"])} · 30d ${P.fmtPct(w["30d"])}`;
    $("hChecks").textContent = u.total_checks.toLocaleString();
    $("hChecksSplit").innerHTML = `<span class="ok-text"><i class="bi bi-check-lg"></i> ${u.successful_checks.toLocaleString()} ok</span><span class="bad-text"><i class="bi bi-x-lg"></i> ${u.failed_checks.toLocaleString()} failed</span>`;
    $("hLatency").textContent = P.fmtMs(u.avg_latency_ms);
    $("hLatencyRange").textContent = u.min_latency_ms != null ? `min ${P.fmtMs(u.min_latency_ms)} · max ${P.fmtMs(u.max_latency_ms)}` : "No replies in window";

    $("outageCount").textContent = `${d.outages.length} in window`;
    $("outageRows").innerHTML = d.outages.length ? d.outages.map((o) => `<tr>
        <td>${P.esc(P.fmtDateTime(o.start))}</td>
        <td>${o.ongoing ? '<span class="status status-offline"><i class="bi bi-x-circle-fill"></i>Ongoing</span>' : P.esc(P.fmtDateTime(o.end))}</td>
        <td class="text-end tabular">${o.ongoing ? "—" : P.fmtDuration(o.duration_seconds)}</td></tr>`).join("")
      : `<tr><td colspan="3">${P.emptyState("bi-emoji-smile", "No outages", "The device was never confirmed offline in this window.")}</td></tr>`;

    total = d.total;
    const pages = Math.max(1, Math.ceil(total / perPage));
    $("pageInfo").textContent = total ? `Page ${page} of ${pages}` : "";
    $("prevPage").disabled = page <= 1;
    $("nextPage").disabled = page >= pages;
    $("checkRows").innerHTML = d.checks.length ? d.checks.map((c) => `<tr>
        <td class="tabular" title="${P.esc(c.checked_at)}">${P.esc(P.fmtDateTime(c.checked_at, true))}</td>
        <td>${c.success ? '<span class="ok-text"><i class="bi bi-check-circle-fill"></i> Reply</span>' : `<span class="bad-text"><i class="bi bi-x-circle-fill"></i> ${P.esc(c.error || "No reply")}</span>`}</td>
        <td class="text-end tabular">${c.success ? P.fmtMs(c.latency_ms) : "—"}</td>
        <td class="hide-xs">${P.statusPill(c.status_after)}</td>
        <td class="hide-xs tabular text-2">${c.attempts}</td></tr>`).join("")
      : `<tr><td colspan="5">${P.emptyState("bi-hourglass", "No checks yet", "Checks appear after the first ping cycle.")}</td></tr>`;
    $("exportHistory").href = `/export/devices/${deviceId}/history.csv?window=${windowSel}`;
    $("exportUptime").href = `/export/uptime.csv?window=${windowSel}`;
  }

  async function loadCharts() {
    const d = await P.api("GET", `/api/latency?window=${windowSel}&device_id=${deviceId}`);
    const now = Date.now();
    latChart.data.datasets[0].data = d.points.map((p) => ({ x: Date.parse(p.t), y: p.avg_ms }));
    P.setXRange(latChart, now - SPAN[windowSel], now);
    P.setChartEmpty(latChart, !d.points.some((p) => p.avg_ms != null));
    latChart.update();
    availChart.data.datasets[0].data = d.points.map((p) => ({ x: Date.parse(p.t), y: p.success_rate }));
    P.setXRange(availChart, now - SPAN[windowSel], now);
    P.setChartEmpty(availChart, !d.points.length);
    paintAvail();
  }

  function reloadAll() {
    return Promise.all([loadSummary(), loadCharts()]).catch((e) => P.toast(e.message, "error"));
  }

  $("deviceSelect").addEventListener("change", (e) => { location.href = `/history/${e.target.value}`; });
  document.querySelectorAll("#windowSel .btn").forEach((btn) => btn.addEventListener("click", () => {
    document.querySelectorAll("#windowSel .btn").forEach((b) => { b.classList.remove("active"); b.setAttribute("aria-pressed", "false"); });
    btn.classList.add("active"); btn.setAttribute("aria-pressed", "true");
    windowSel = btn.dataset.w;
    page = 1;
    reloadAll();
  }));
  $("prevPage").addEventListener("click", () => { page = Math.max(1, page - 1); loadSummary(); });
  $("nextPage").addEventListener("click", () => { page += 1; loadSummary(); });

  $("checkRows").innerHTML = P.skeletonRows(5, 6);
  $("outageRows").innerHTML = P.skeletonRows(3, 3);
  P.poll(reloadAll, 60000);
})();
