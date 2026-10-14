/* Bandwidth page */
(function () {
  "use strict";
  const P = window.Pe3k;
  const $ = (id) => document.getElementById(id);
  const SPAN = { "1h": 3600e3, "6h": 6 * 3600e3, "24h": 86400e3, "7d": 7 * 86400e3, "30d": 30 * 86400e3 };
  let histWindow = "24h";
  let iface = "all";

  const mbpsTooltip = { callbacks: { title: (i) => P.fmtDateTime(new Date(i[0].parsed.x).toISOString(), true), label: (c) => ` ${c.dataset.label}: ${P.fmtMbps(c.parsed.y)} Mbps` } };
  const liveChart = P.makeChart($("liveChart"), {
    type: "line",
    data: { datasets: [P.lineDataset("Download", "--series-1", [], { pe3kFill: true, fill: "origin", tension: 0.25 }), P.lineDataset("Upload", "--series-2", [], { tension: 0.25 })] },
    options: { scales: { x: P.timeScale(1200e3), y: { beginAtZero: true, ticks: { callback: (v) => `${v} Mbps` } } }, plugins: { tooltip: mbpsTooltip } },
  });
  const histChart = P.makeChart($("histChart"), {
    type: "line",
    data: { datasets: [P.lineDataset("Download", "--series-1", [], { pe3kFill: true, fill: "origin" }), P.lineDataset("Upload", "--series-2", [])] },
    options: { scales: { x: P.timeScale(SPAN["24h"]), y: { beginAtZero: true, ticks: { callback: (v) => `${v} Mbps` } } }, plugins: { tooltip: mbpsTooltip } },
  });
  const dailyChart = P.makeChart($("dailyChart"), {
    type: "bar",
    data: { labels: [], datasets: [
      { label: "Downloaded", data: [], pe3kSeries: "--series-1", borderRadius: 4, borderSkipped: "bottom", categoryPercentage: 0.7, barPercentage: 0.9 },
      { label: "Uploaded", data: [], pe3kSeries: "--series-2", borderRadius: 4, borderSkipped: "bottom", categoryPercentage: 0.7, barPercentage: 0.9 },
    ] },
    options: {
      scales: { x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 7 } }, y: { beginAtZero: true, ticks: { callback: (v) => P.fmtBytes(v) } } },
      plugins: { tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${P.fmtBytes(c.parsed.y)}` } } },
    },
  });

  function dayLabel(day) {
    const [y, m, d] = day.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  }

  async function loadInterfaces() {
    const d = await P.api("GET", "/api/bandwidth/interfaces");
    iface = d.selected;
    const sel = $("ifaceSelect");
    sel.innerHTML = `<option value="all">All interfaces (excluding loopback)</option>` + d.interfaces.map((i) =>
      `<option value="${P.esc(i.name)}">${P.esc(i.name)}${i.loopback ? " (loopback)" : ""}${i.is_up ? "" : " — down"}</option>`).join("");
    if (iface !== "all" && !d.interfaces.some((i) => i.name === iface)) {
      sel.insertAdjacentHTML("beforeend", `<option value="${P.esc(iface)}">${P.esc(iface)} — not found</option>`);
    }
    sel.value = iface;
    const info = d.interfaces.find((i) => i.name === iface);
    $("ifaceInfo").innerHTML = info ? `
      <div class="stat-row"><span class="k">State</span><span class="v">${info.is_up ? '<span class="ok-text"><i class="bi bi-check-circle-fill"></i> Up</span>' : '<span class="bad-text"><i class="bi bi-x-circle-fill"></i> Down</span>'}</span></div>
      <div class="stat-row"><span class="k">IPv4</span><span class="v mono">${P.esc(info.ipv4.join(", ") || "—")}</span></div>
      <div class="stat-row"><span class="k">Link speed</span><span class="v">${info.speed_mbps ? `${info.speed_mbps} Mbps` : "—"}</span></div>`
      : `<div class="stat-row"><span class="k">Interfaces counted</span><span class="v">${d.interfaces.filter((i) => !i.loopback).length}</span></div>`;
  }

  async function loadLive() {
    const d = await P.api("GET", "/api/bandwidth/live");
    $("rxNow").textContent = P.fmtMbps(d.current.rx_mbps);
    $("txNow").textContent = P.fmtMbps(d.current.tx_mbps);
    $("rxToday").textContent = P.fmtBytes(d.today.bytes_recv);
    $("txToday").textContent = P.fmtBytes(d.today.bytes_sent);
    $("rxCounter").textContent = P.fmtBytes(d.current.counter_recv);
    $("txCounter").textContent = P.fmtBytes(d.current.counter_sent);
    $("bwErr").innerHTML = d.error ? `<span class="bad-text"><i class="bi bi-exclamation-octagon"></i> ${P.esc(d.error)}</span>` : "";
    $("liveNote").textContent = `· sampled every ${d.sample_seconds}s`;
    liveChart.data.datasets[0].data = d.live.map((p) => ({ x: Date.parse(p.t), y: p.rx_mbps }));
    liveChart.data.datasets[1].data = d.live.map((p) => ({ x: Date.parse(p.t), y: p.tx_mbps }));
    if (d.live.length > 1) P.setXRange(liveChart, Date.parse(d.live[0].t), Date.parse(d.live[d.live.length - 1].t));
    P.setChartEmpty(liveChart, d.live.length < 2);
    liveChart.update("none");
  }

  async function loadHistory() {
    const d = await P.api("GET", `/api/bandwidth/history?window=${histWindow}`);
    histChart.data.datasets[0].data = d.points.map((p) => ({ x: Date.parse(p.t), y: p.rx_mbps }));
    histChart.data.datasets[1].data = d.points.map((p) => ({ x: Date.parse(p.t), y: p.tx_mbps }));
    P.setXRange(histChart, Date.now() - SPAN[histWindow], Date.now());
    P.setChartEmpty(histChart, !d.points.length);
    histChart.update();
    $("winRx").textContent = P.fmtBytes(d.totals.bytes_recv);
    $("winTx").textContent = P.fmtBytes(d.totals.bytes_sent);
    const q = new URLSearchParams({ window: histWindow });
    if (iface !== "all") q.set("interface", iface);
    $("exportBw").href = `/export/bandwidth.csv?${q}`;
  }

  async function loadDaily() {
    const d = await P.api("GET", "/api/bandwidth/daily?days=14");
    dailyChart.data.labels = d.days.map((x) => dayLabel(x.day));
    dailyChart.data.datasets[0].data = d.days.map((x) => x.bytes_recv);
    dailyChart.data.datasets[1].data = d.days.map((x) => x.bytes_sent);
    P.setChartEmpty(dailyChart, !d.days.length);
    dailyChart.update();
    $("dailyRows").innerHTML = d.days.length ? d.days.slice().reverse().map((x) => `<tr>
      <td>${P.esc(dayLabel(x.day))}</td><td class="text-end tabular">${P.fmtBytes(x.bytes_recv)}</td><td class="text-end tabular">${P.fmtBytes(x.bytes_sent)}</td>
      <td class="text-end tabular hide-xs">${P.fmtMbps(x.peak_rx_mbps)} Mbps</td><td class="text-end tabular hide-xs">${P.fmtMbps(x.peak_tx_mbps)} Mbps</td></tr>`).join("")
      : `<tr><td colspan="5">${P.emptyState("bi-calendar-x", "No data yet", "Daily totals appear after Pe3k has been running for a few minutes.")}</td></tr>`;
  }

  $("ifaceSelect").addEventListener("change", async (e) => {
    try {
      await P.api("PUT", "/api/bandwidth/interface", { interface: e.target.value });
      P.toast(`Now measuring ${e.target.value === "all" ? "all interfaces" : e.target.value}.`, "ok");
      await loadInterfaces();
      liveChart.data.datasets.forEach((ds) => { ds.data = []; });
      liveChart.update("none");
      loadHistory(); loadDaily(); loadLive();
    } catch (err) { P.toast(err.message, "error"); loadInterfaces(); }
  });
  document.querySelectorAll("#histWindow .btn").forEach((btn) => btn.addEventListener("click", () => {
    document.querySelectorAll("#histWindow .btn").forEach((b) => { b.classList.remove("active"); b.setAttribute("aria-pressed", "false"); });
    btn.classList.add("active"); btn.setAttribute("aria-pressed", "true");
    histWindow = btn.dataset.w;
    loadHistory().catch((e) => P.toast(e.message, "error"));
  }));

  $("dailyRows").innerHTML = P.skeletonRows(5, 4);
  loadInterfaces().then(() => { P.poll(loadHistory, 60000); P.poll(loadDaily, 300000); }).catch((e) => P.toast(e.message, "error"));
  P.poll(loadLive, 5000);
})();
