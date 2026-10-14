/* Alerts page */
(function () {
  "use strict";
  const P = window.Pe3k;
  const $ = (id) => document.getElementById(id);
  const trustForm = $("trustForm");
  const trustModal = new bootstrap.Modal($("trustModal"));
  let status = "open";
  let alerts = [];
  let trustingId = null;

  const STATUS_CHIP = {
    open: '<span class="chip chip-warn"><i class="bi bi-circle-fill" style="font-size:.5em"></i>Open</span>',
    ignored: '<span class="chip"><i class="bi bi-eye-slash"></i>Ignored</span>',
    resolved: '<span class="chip chip-info"><i class="bi bi-check2"></i>Resolved</span>',
    trusted: '<span class="chip chip-accent"><i class="bi bi-shield-check"></i>Trusted</span>',
  };

  const RANGE_TEXT = { "1h": "in the last hour", "6h": "in the last 6 hours", "24h": "in the last 24 hours",
    "7d": "in the last 7 days", "30d": "in the last 30 days", all: "at any time" };
  const STATUS_TEXT = { open: "Open", ignored: "Ignored", resolved: "Resolved", trusted: "Trusted", all: "All" };
  let custom = { since: "", until: "" };

  // datetime-local value (local time, no zone) -> UTC ISO string without milliseconds
  const localToIso = (v) => (v ? new Date(v).toISOString().replace(/\.\d{3}Z$/, "Z") : "");

  function filterQuery() {
    const q = new URLSearchParams({ status });
    if ($("typeFilter").value) q.set("type", $("typeFilter").value);
    const w = $("rangeFilter").value;
    q.set("window", w);
    if (w === "custom") {
      if (custom.since) q.set("since", custom.since);
      if (custom.until) q.set("until", custom.until);
    }
    return q;
  }

  function rangeText() {
    const w = $("rangeFilter").value;
    if (w !== "custom") return RANGE_TEXT[w];
    if (!custom.since && !custom.until) return "at any time";
    const f = (iso) => P.fmtDateTime(iso);
    if (custom.since && custom.until) return `between ${f(custom.since)} and ${f(custom.until)}`;
    return custom.since ? `since ${f(custom.since)}` : `until ${f(custom.until)}`;
  }

  async function load() {
    const q = filterQuery();
    $("exportAlerts").href = `/export/alerts.csv?${q}`;
    try {
      const data = await P.api("GET", `/api/alerts?${q}`);
      alerts = data.alerts;
      document.querySelector('[data-c="open"]').textContent = data.counts.open;
      document.querySelector('[data-c="ignored"]').textContent = data.counts.ignored;
      $("rangeSummary").textContent = `${alerts.length} ${STATUS_TEXT[status].toLowerCase() === "all" ? "" : STATUS_TEXT[status].toLowerCase() + " "}alert${alerts.length === 1 ? "" : "s"} seen ${rangeText()}. Export CSV downloads exactly this list.`;
      render();
    } catch (e) {
      $("rows").innerHTML = `<tr><td colspan="7">${P.emptyState("bi-wifi-off", "Couldn't load alerts", e.message)}</td></tr>`;
    }
  }

  function actions(a) {
    const btns = [];
    if (a.alert_type === "unknown_device" && (a.status === "open" || a.status === "ignored")) {
      btns.push(`<button class="btn btn-ok-soft btn-sm" data-act="trust"><i class="bi bi-shield-check"></i><span class="hide-xs">Trust Device</span></button>`);
    }
    if (a.status === "open") btns.push(`<button class="btn btn-glass btn-sm" data-act="ignore" title="Ignore: keep watching but stop alerting for this device"><i class="bi bi-eye-slash"></i><span class="hide-xs">Ignore</span></button>`);
    if (a.status === "open" || a.status === "ignored") btns.push(`<button class="btn btn-glass btn-sm" data-act="resolve" title="Resolve"><i class="bi bi-check2-circle"></i><span class="hide-xs">Resolve</span></button>`);
    if (a.status === "resolved" || a.status === "ignored") btns.push(`<button class="btn btn-glass btn-sm" data-act="reopen" title="Reopen"><i class="bi bi-arrow-counterclockwise"></i></button>`);
    return btns.join("");
  }

  function render() {
    if (!alerts.length) {
      const msg = status === "open"
        ? P.emptyState("bi-shield-check", "No open alerts", "Your network looks as expected. New unknown or offline devices will appear here.")
        : P.emptyState("bi-inbox", "Nothing here", "No alerts match this filter.");
      $("rows").innerHTML = `<tr><td colspan="7">${msg}</td></tr>`;
      return;
    }
    $("rows").innerHTML = alerts.map((a) => {
      const unknown = a.alert_type === "unknown_device";
      const who = unknown ? (a.hostname || a.vendor || "Unrecognised hardware") : (a.device_name || "Removed device");
      return `<tr data-id="${a.id}">
        <td><div class="d-flex gap-2 align-items-start">
          <span class="alert-ico ${unknown ? "warn" : "bad"} rounded-3 d-grid" style="width:32px;height:32px;place-items:center"><i class="bi ${unknown ? "bi-question-octagon" : "bi-wifi-off"}" aria-hidden="true"></i></span>
          <div><span class="device-name">${unknown ? "Unknown device" : "Device offline"}</span>
          <span class="sub">${P.esc(who)}${a.occurrences > 1 ? ` · seen ${a.occurrences}×` : ""}</span></div></div></td>
        <td><span class="mono">${P.esc(a.ip_address || "—")}</span><span class="sub mono">${P.esc(a.mac_address || (unknown ? "MAC unavailable" : ""))}</span></td>
        <td class="hide-xs text-2">${P.esc(a.engine || "—")}</td>
        <td class="hide-xs text-2" title="${P.esc(P.fmtDateTime(a.first_seen, true))}">${P.esc(P.fmtDateTime(a.first_seen))}</td>
        <td class="text-2" title="${P.esc(P.fmtDateTime(a.last_seen, true))}">${P.esc(P.timeAgo(a.last_seen))}</td>
        <td class="hide-xs">${STATUS_CHIP[a.status] || P.esc(a.status)}${a.resolution && a.status !== "open" ? `<span class="sub">${P.esc(a.resolution)}</span>` : ""}</td>
        <td><div class="table-actions">${actions(a)}</div></td>
      </tr>`;
    }).join("");
  }

  $("rows").addEventListener("click", async (ev) => {
    const el = ev.target.closest("[data-act]");
    if (!el) return;
    const id = Number(el.closest("tr").dataset.id);
    const a = alerts.find((x) => x.id === id);
    const act = el.dataset.act;
    if (act === "trust") {
      trustingId = id;
      P.clearErrors(trustForm);
      trustForm.reset();
      trustForm.elements.ip_address.value = a.ip_address || "";
      trustForm.elements.mac_address.value = a.mac_address || "";
      trustForm.elements.name.value = (a.hostname || "").split(".")[0] || (a.vendor && !a.vendor.startsWith("(") ? `${a.vendor} device` : "");
      trustModal.show();
      setTimeout(() => trustForm.elements.name.focus(), 300);
      return;
    }
    P.setBusy(el, true);
    try {
      await P.api("POST", `/api/alerts/${id}/${act}`);
      P.toast({ ignore: "Alert ignored — this device won't raise new alerts until resolved.", resolve: "Alert resolved.", reopen: "Alert reopened." }[act], "ok");
      load();
      P.updateNav();
    } catch (e) { P.toast(e.message, "error"); P.setBusy(el, false); }
  });

  trustForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    P.setBusy($("trustSave"), true, "Saving");
    try {
      const res = await P.api("POST", `/api/alerts/${trustingId}/trust`, {
        name: trustForm.elements.name.value, device_type: trustForm.elements.device_type.value,
        monitoring_enabled: trustForm.elements.monitoring_enabled.checked,
      });
      trustModal.hide();
      P.toast(`${res.device.name} added to trusted devices.`, "ok");
      load();
      P.updateNav();
    } catch (e) { P.showErrors(trustForm, e); } finally { P.setBusy($("trustSave"), false); }
  });

  document.querySelectorAll("#statusTabs .btn").forEach((btn) => btn.addEventListener("click", () => {
    document.querySelectorAll("#statusTabs .btn").forEach((b) => { b.classList.remove("active"); b.setAttribute("aria-pressed", "false"); });
    btn.classList.add("active"); btn.setAttribute("aria-pressed", "true");
    status = btn.dataset.s;
    $("rows").innerHTML = P.skeletonRows(7, 4);
    load();
  }));
  $("typeFilter").addEventListener("change", load);
  $("rangeFilter").addEventListener("change", () => {
    const isCustom = $("rangeFilter").value === "custom";
    $("customRange").classList.toggle("d-none", !isCustom);
    if (isCustom) {
      if (!$("rangeFrom").value) {
        const d = new Date(Date.now() - 86400e3);
        d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
        $("rangeFrom").value = d.toISOString().slice(0, 16);
      }
      $("rangeFrom").focus();
      return; // wait for Apply
    }
    $("rows").innerHTML = P.skeletonRows(7, 4);
    load();
  });
  $("customRange").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const since = localToIso($("rangeFrom").value), until = localToIso($("rangeTo").value);
    if (since && until && since > until) { P.toast("'From' must be before 'To'.", "warn"); return; }
    custom = { since, until };
    $("rows").innerHTML = P.skeletonRows(7, 4);
    load();
  });

  $("rows").innerHTML = P.skeletonRows(7, 4);
  P.poll(() => (document.querySelector(".modal.show") ? null : load()), 15000);
})();
