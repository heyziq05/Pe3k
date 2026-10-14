/* Dashboard page */
(function () {
  "use strict";
  const P = window.Pe3k;
  const $ = (id) => document.getElementById(id);
  let latWindow = "6h";

  $("deviceRows").innerHTML = P.skeletonRows(5, 5);

  // ---------------------------------------------------------------- charts
  const latChart = P.makeChart($("latencyChart"), {
    type: "line",
    data: { datasets: [P.lineDataset("Average", "--series-1", [], { pe3kFill: true, fill: "origin" }), P.lineDataset("Slowest device", "--series-2", [])] },
    options: {
      scales: { x: P.timeScale(6 * 3600e3), y: { beginAtZero: true, ticks: { callback: (v) => `${v} ms` } } },
      plugins: { tooltip: { callbacks: { title: (items) => P.fmtDateTime(new Date(items[0].parsed.x).toISOString()),
        label: (ctx) => ` ${ctx.dataset.label}: ${P.fmtMs(ctx.parsed.y)}` } } },
    },
  });
  const bwChart = P.makeChart($("bwChart"), {
    type: "line",
    data: { datasets: [P.lineDataset("Download", "--series-1", [], { pe3kFill: true, fill: "origin" }), P.lineDataset("Upload", "--series-2", [])] },
    options: {
      scales: { x: P.timeScale(3600e3), y: { beginAtZero: true, ticks: { callback: (v) => `${v} Mbps` } } },
      plugins: { tooltip: { callbacks: { title: (items) => P.fmtDateTime(new Date(items[0].parsed.x).toISOString(), true),
        label: (ctx) => ` ${ctx.dataset.label}: ${P.fmtMbps(ctx.parsed.y)} Mbps` } } },
    },
  });

  // ---------------------------------------------------------------- render
  function renderKpis(d) {
    const dv = d.devices, al = d.alerts;
    $("kTotal").textContent = dv.total;
    $("kTrusted").textContent = `${dv.trusted} trusted`;
    $("kOnline").textContent = dv.online + dv.unstable;
    $("kUnstable").innerHTML = dv.unstable ? `<span class="warn-text"><i class="bi bi-exclamation-triangle-fill"></i> ${dv.unstable} unstable</span>` : "All responding normally";
    $("kOffline").textContent = dv.offline;
    $("kOffline").classList.toggle("bad-text", dv.offline > 0);
    $("kPending").textContent = dv.unknown ? `${dv.unknown} awaiting first check` : "Confirmed after consecutive failures";
    $("kUnknown").textContent = al.unknown_open;
    $("kUnknown").classList.toggle("warn-text", al.unknown_open > 0);
    $("kAlerts").textContent = `${al.open} open alert${al.open === 1 ? "" : "s"} · ${al.ignored} ignored`;
  }

  function renderScan(s) {
    const state = s.running
      ? `<span class="status status-running"><span class="dot pulse"></span>Scanning</span>`
      : s.engine === "manual" ? `<span class="status status-unknown"><i class="bi bi-pause-circle"></i>Manual</span>`
      : s.ready ? `<span class="status status-online"><i class="bi bi-check-circle-fill"></i>Ready</span>`
      : `<span class="status status-unstable"><i class="bi bi-exclamation-triangle-fill"></i>Not ready</span>`;
    $("scanState").innerHTML = state;
    const last = s.last_scan;
    const lastLine = last
      ? (last.status === "success"
        ? `<span class="ok-text"><i class="bi bi-check2"></i></span> ${P.esc(P.timeAgo(last.finished_at))} · ${last.hosts_found} hosts, ${last.unknown_found} unknown`
        : `<span class="bad-text"><i class="bi bi-x-octagon"></i> Failed ${P.esc(P.timeAgo(last.finished_at))}</span>`)
      : "No scans yet";
    $("scanBody").innerHTML = `
      <div class="stat-row"><span class="k">Active engine</span><span class="v">${P.esc(s.engine_label)}</span></div>
      <div class="stat-row"><span class="k">Authorized range</span><span class="v mono">${P.esc(s.authorized_subnet || "not set")}</span></div>
      <div class="stat-row"><span class="k">Automatic scans</span><span class="v">${s.auto_scan_enabled ? "On" : "Off"}</span></div>
      <div class="stat-row"><span class="k">Last scan</span><span class="v">${lastLine}</span></div>
      ${last && last.status === "error" ? `<div class="notice bad mt-2"><i class="bi bi-x-octagon"></i><div>${P.esc(last.error)}</div></div>` : ""}
      ${s.engine !== "manual" && !s.ready && !(last && last.status === "error") ? `<div class="notice warn mt-2"><i class="bi bi-tools"></i><div>${P.esc(s.health_summary)} — see Settings for setup steps.</div></div>` : ""}`;
    $("scanNow").disabled = s.running || s.engine === "manual";
    $("scanNow").title = s.engine === "manual" ? "Manual mode: scanning is disabled" : "";
  }

  function renderDevices(list) {
    if (!list.length) {
      $("deviceRows").innerHTML = `<tr><td colspan="5">${P.emptyState("bi-hdd-network", "No devices yet", "Add your router and other trusted devices to start monitoring.",
        '<a class="btn btn-accent btn-sm" href="/devices#add"><i class="bi bi-plus-lg"></i>Add device</a>')}</td></tr>`;
      return;
    }
    $("deviceRows").innerHTML = list.map((d) => `
      <tr>
        <td><a class="device-name" href="/history/${d.id}">${P.esc(d.name)}</a><span class="sub mono">${P.esc(d.ip_address)}</span></td>
        <td>${P.statusPill(d.monitoring_enabled ? d.status : "unknown", d.consecutive_failures ? `${d.consecutive_failures} consecutive failed checks` : "")}
          ${d.monitoring_enabled ? "" : '<span class="chip ms-1">paused</span>'}</td>
        <td class="text-end tabular">${d.status === "offline" ? '<span class="text-muted">—</span>' : P.fmtMs(d.last_latency_ms)}</td>
        <td class="hide-xs text-2" title="${P.esc(P.fmtDateTime(d.last_seen))}">${P.esc(P.timeAgo(d.last_seen))}</td>
        <td class="hide-xs text-2">${P.typeIcon(d.device_type)} ${P.esc(P.TYPE_LABELS[d.device_type] || d.device_type)}</td>
      </tr>`).join("");
  }

  function renderAlerts(list) {
    if (!list.length) {
      $("alertList").innerHTML = P.emptyState("bi-shield-check", "All clear", "No open alerts. Unknown or offline devices will show up here.");
      return;
    }
    $("alertList").innerHTML = list.map((a) => {
      const unknown = a.alert_type === "unknown_device";
      return `<div class="alert-item">
        <span class="alert-ico ${unknown ? "warn" : "bad"}"><i class="bi ${unknown ? "bi-question-octagon" : "bi-wifi-off"}" aria-hidden="true"></i></span>
        <div class="flex-grow-1 min-w-0">
          <div class="title">${unknown ? "Unknown device" : "Device offline"} <span class="mono text-2">${P.esc(a.ip_address || "")}</span></div>
          <div class="meta">${unknown ? `<span class="mono">${P.esc(a.mac_address || "MAC unavailable")}</span> · ` : `${P.esc(a.device_name || "")} · `}${P.esc(P.timeAgo(a.last_seen))}${a.occurrences > 1 ? ` · seen ${a.occurrences}×` : ""}</div>
        </div>
      </div>`;
    }).join("");
  }

  function renderBandwidth(b) {
    $("bwDown").textContent = P.fmtMbps(b.current.rx_mbps);
    $("bwUp").textContent = P.fmtMbps(b.current.tx_mbps);
    $("bwDownToday").textContent = P.fmtBytes(b.today.bytes_recv);
    $("bwUpToday").textContent = P.fmtBytes(b.today.bytes_sent);
    $("bwIface").textContent = b.interface === "all" ? "all interfaces" : b.interface;
    $("bwError").textContent = b.error || "";
    const rx = b.live.map((p) => ({ x: Date.parse(p.t), y: p.rx_mbps }));
    const tx = b.live.map((p) => ({ x: Date.parse(p.t), y: p.tx_mbps }));
    bwChart.data.datasets[0].data = rx;
    bwChart.data.datasets[1].data = tx;
    if (rx.length > 1) P.setXRange(bwChart, rx[0].x, rx[rx.length - 1].x);
    P.setChartEmpty(bwChart, rx.length < 2);
    bwChart.update("none");
  }

  async function loadLatency() {
    const data = await P.api("GET", `/api/latency?window=${latWindow}`);
    latChart.data.datasets[0].data = data.points.map((p) => ({ x: Date.parse(p.t), y: p.avg_ms }));
    latChart.data.datasets[1].data = data.points.map((p) => ({ x: Date.parse(p.t), y: p.max_ms }));
    const now = Date.now();
    P.setXRange(latChart, now - { "1h": 3600e3, "6h": 6 * 3600e3, "24h": 86400e3 }[latWindow], now);
    P.setChartEmpty(latChart, !data.points.length);
    latChart.update();
  }

  async function refresh() {
    const d = await P.api("GET", "/api/overview");
    renderKpis(d);
    renderScan(d.scan);
    renderDevices(d.device_list);
    renderAlerts(d.recent_alerts);
    renderBandwidth(d.bandwidth);
    $("lastUpdated").textContent = `Updated ${P.fmtTime(d.server_time)}`;
  }

  // ---------------------------------------------------------------- events
  document.querySelectorAll("#latWindow .btn").forEach((btn) => btn.addEventListener("click", () => {
    document.querySelectorAll("#latWindow .btn").forEach((b) => { b.classList.remove("active"); b.setAttribute("aria-pressed", "false"); });
    btn.classList.add("active"); btn.setAttribute("aria-pressed", "true");
    latWindow = btn.dataset.w;
    loadLatency().catch((e) => P.toast(e.message, "error"));
  }));

  $("scanNow").addEventListener("click", async () => {
    P.setBusy($("scanNow"), true, "Starting");
    try {
      await P.api("POST", "/api/scan/run");
      P.toast("Scan started — results appear in a moment.", "ok");
      setTimeout(() => main.now(), 1500);
    } catch (e) {
      P.toast(e.message, e.status === 409 ? "warn" : "error");
    } finally { P.setBusy($("scanNow"), false); }
  });

  $("pingNow").addEventListener("click", async () => {
    P.setBusy($("pingNow"), true, "Pinging");
    try {
      await P.api("POST", "/api/monitor/run");
      P.toast("Ping cycle started.", "ok");
      setTimeout(() => { main.now(); loadLatency(); }, 2500);
    } catch (e) { P.toast(e.message, "error"); } finally { setTimeout(() => P.setBusy($("pingNow"), false), 1200); }
  });

  const main = P.poll(() => refresh().catch((e) => { $("lastUpdated").innerHTML = `<span class="bad-text"><i class="bi bi-wifi-off"></i> ${P.esc(e.message)}</span>`; }), 5000);
  P.poll(() => loadLatency(), 60000);
})();
