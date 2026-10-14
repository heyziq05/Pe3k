/* Settings page */
(function () {
  "use strict";
  const P = window.Pe3k;
  const $ = (id) => document.getElementById(id);
  const form = $("settingsForm");

  const NUMBERS = ["scan_interval_seconds", "scan_timeout_seconds", "ping_interval_seconds", "ping_timeout_seconds", "ping_retries", "failure_threshold",
    "phone_ping_timeout_seconds", "phone_ping_retries", "phone_retry_delay_seconds", "phone_failure_threshold"];
  const BOOLS = ["strict_scope", "auto_scan_enabled", "scan_authorized_ack", "offline_alerts_enabled", "use_arp_cache", "phone_tuning_enabled"];
  const TEXT = ["authorized_subnet", "nmap_path", "ping_method"];
  const PHONE_FIELDS = ["phone_ping_timeout_seconds", "phone_ping_retries", "phone_retry_delay_seconds", "phone_failure_threshold"];
  const BASIC = ["discovery_engine", "authorized_subnet", "nmap_path", "auto_scan_enabled", "scan_authorized_ack"];

  let saved = null;        // effective saved settings
  let preset = {};         // Simple-mode preset values
  let advanced = [];       // keys locked in Simple mode
  let proDraft = {};       // Pro values being edited (kept while Simple is selected)
  let snapshot = "";       // collect() at last load/save -> dirty detection

  const labelFor = (e) => ({ nmap: "Nmap", scapy: "Scapy (ARP)", manual: "Manual", demo: "Demo (simulated)" }[e] || e);
  const mode = () => (form.querySelector('input[name="settings_mode"]:checked') || {}).value || "simple";
  const engine = () => (form.querySelector('input[name="discovery_engine"]:checked') || {}).value;

  // ------------------------------------------------------------ field I/O
  function setField(k, v) {
    const el = form.elements[k];
    if (!el) return;
    if (BOOLS.includes(k)) el.checked = !!v; else el.value = v ?? "";
  }
  function getField(k) {
    const el = form.elements[k];
    if (BOOLS.includes(k)) return el.checked;
    return TEXT.includes(k) ? el.value.trim() : el.value;
  }
  const readAdvanced = () => Object.fromEntries(advanced.map((k) => [k, getField(k)]));
  const writeAdvanced = (obj) => advanced.forEach((k) => setField(k, obj[k]));

  function fill(d) {
    saved = d.settings;
    preset = d.simple_preset;
    advanced = d.advanced_keys;
    proDraft = { ...d.pro_settings };
    form.querySelectorAll('input[name="settings_mode"]').forEach((r) => { r.checked = r.value === saved.settings_mode; });
    form.querySelectorAll('input[name="discovery_engine"]').forEach((r) => { r.checked = r.value === saved.discovery_engine; });
    ["authorized_subnet", "nmap_path", "auto_scan_enabled", "scan_authorized_ack"].forEach((k) => setField(k, saved[k]));
    writeAdvanced(saved.settings_mode === "simple" ? preset : proDraft);
    syncUi();
    snapshot = JSON.stringify(collect());
    updateDirty();
  }

  function collect() {
    const out = { settings_mode: mode() };
    BASIC.forEach((k) => { out[k] = k === "discovery_engine" ? engine() : getField(k); });
    if (out.settings_mode === "pro") Object.assign(out, readAdvanced());
    return out;
  }

  // ----------------------------------------------------------------- UI state
  function syncUi() {
    const simple = mode() === "simple";
    const manual = engine() === "manual";
    advanced.forEach((k) => {
      const el = form.elements[k];
      if (!el) return;
      const wrap = el.closest('[class*="col-"]') || el.parentElement;
      wrap.classList.toggle("is-locked", simple);
      el.disabled = simple;
      const label = wrap.querySelector(".form-label, .form-check-label");
      let badge = label && label.querySelector(".lock-badge");
      if (simple && label && !badge) label.insertAdjacentHTML("beforeend", '<span class="lock-badge" title="Preset (Simple mode)"><i class="bi bi-lock-fill"></i><span class="txt"> Preset</span></span>');
      if (!simple && badge) badge.remove();
    });
    document.querySelectorAll(".simple-lock").forEach((n) => n.classList.toggle("d-none", !simple));
    if (!simple) {
      ["scan_interval_seconds", "scan_timeout_seconds", "use_arp_cache"].forEach((k) => { form.elements[k].disabled = manual; });
      PHONE_FIELDS.forEach((k) => { form.elements[k].disabled = !form.elements.phone_tuning_enabled.checked; });
    }
    form.elements.auto_scan_enabled.disabled = manual;
    $("activeEngine").innerHTML = saved
      ? `<span class="chip chip-accent"><i class="bi bi-check2-circle"></i>Active: ${P.esc(labelFor(saved.discovery_engine))} · ${saved.settings_mode === "pro" ? "Pro" : "Simple"} mode</span>` : "";
  }

  const isDirty = () => !!snapshot && JSON.stringify(collect()) !== snapshot;
  function updateDirty() {
    const dirty = isDirty();
    $("saveBar").classList.toggle("dirty", dirty);
    $("resetForm").disabled = !dirty;
    $("saveState").innerHTML = dirty
      ? '<i class="bi bi-exclamation-circle-fill warn-text" aria-hidden="true"></i>Unsaved changes — scans and monitoring use the saved settings'
      : '<i class="bi bi-check2-circle ok-text" aria-hidden="true"></i>All changes saved';
  }

  async function loadSettings() {
    fill(await P.api("GET", "/api/settings"));
  }

  /* Save the form. Resolves true on success, false when validation failed (errors are shown). */
  async function save() {
    P.setBusy($("saveBottom"), true, "Saving");
    try {
      await P.api("PUT", "/api/settings", collect());
      P.clearErrors(form);
      await loadSettings();
      P.toast("Settings saved.", "ok");
      loadHealth(true).catch(() => {});
      P.updateNav();
      return true;
    } catch (e) {
      P.showErrors(form, e);
      P.toast(e.message, "error");
      return false;
    } finally { P.setBusy($("saveBottom"), false); }
  }

  // ------------------------------------------------------------------ health
  function checksHtml(h) {
    const items = h.checks.map((c) => {
      const icon = c.ok ? "bi-check-circle-fill ok-text" : c.level === "warning" ? "bi-exclamation-triangle-fill warn-text" : c.level === "info" ? "bi-info-circle-fill info-text" : "bi-x-circle-fill bad-text";
      return `<li><i class="bi ${icon}" aria-hidden="true"></i><div><strong>${P.esc(c.name)}</strong><br><span class="text-2">${P.esc(c.detail)}</span></div></li>`;
    }).join("");
    const steps = h.instructions && h.instructions.length
      ? `<details class="mt-2"${h.ready ? "" : " open"}><summary class="small fw-semibold">Setup instructions</summary><ol class="small text-2 mt-2 mb-0 ps-3">${h.instructions.map((s) => `<li class="mb-1">${P.esc(s)}</li>`).join("")}</ol></details>`
      : "";
    return `<ul class="check-list">${items}</ul>${steps}`;
  }
  function chip(h) {
    if (h.engine === "manual") return '<span class="chip"><i class="bi bi-pause-circle"></i>No requirements</span>';
    if (!h.ready) return '<span class="status status-offline"><i class="bi bi-x-circle-fill"></i>Not ready</span>';
    const limited = h.checks.some((c) => !c.ok);
    return limited ? '<span class="status status-unstable"><i class="bi bi-exclamation-triangle-fill"></i>Ready with limits</span>'
      : '<span class="status status-online"><i class="bi bi-check-circle-fill"></i>Ready</span>';
  }

  async function loadHealth(refresh) {
    const h = await P.api("GET", `/api/health${refresh ? "?refresh=1" : ""}`);
    Object.entries(h.engines).forEach(([name, eh]) => {
      const card = document.querySelector(`.engine-health[data-engine="${name}"]`);
      if (card) card.innerHTML = chip(eh) + (eh.version ? ` <span class="chip">v${P.esc(eh.version)}</span>` : "");
      const box = document.querySelector(`[data-health="${name}"]`);
      if (box) box.innerHTML = checksHtml(eh);
      const c2 = document.querySelector(`[data-health-chip="${name}"]`);
      if (c2) c2.innerHTML = chip(eh);
    });
    const p = h.pinger;
    $("pingActive").innerHTML = `${P.esc(p.active)}${p.active !== p.configured ? ` <span class="chip chip-warn">configured: ${P.esc(p.configured)}</span>` : ""}`;
    $("pingNotes").innerHTML = p.notes.map((n) => `<div class="notice warn mt-2"><i class="bi bi-info-circle"></i><div>${P.esc(n)}</div></div>`).join("");

    const pl = h.platform;
    $("systemHealth").innerHTML = `
      <div class="stat-row"><span class="k">Operating system</span><span class="v">${P.esc(pl.system)} ${P.esc(pl.release)}</span></div>
      <div class="stat-row"><span class="k">Python</span><span class="v">${P.esc(pl.python)}</span></div>
      <div class="stat-row"><span class="k">Elevated privileges</span><span class="v">${pl.elevated ? '<span class="ok-text"><i class="bi bi-check-circle-fill"></i> Yes</span>' : '<span class="warn-text"><i class="bi bi-exclamation-triangle-fill"></i> No</span>'}</span></div>
      ${pl.npcap === null ? "" : `<div class="stat-row"><span class="k">Npcap</span><span class="v">${pl.npcap ? '<span class="ok-text"><i class="bi bi-check-circle-fill"></i> Installed</span>' : '<span class="warn-text"><i class="bi bi-exclamation-triangle-fill"></i> Not found</span>'}</span></div>`}
      <div class="stat-row"><span class="k">Host name</span><span class="v">${P.esc(pl.hostname)}</span></div>
      <div class="stat-row"><span class="k">Database</span><span class="v mono small text-break">${P.esc(h.database.path)}</span></div>`;
    $("pkgHealth").innerHTML = Object.entries(h.packages).map(([name, ver]) => `<div class="stat-row"><span class="k">${P.esc(name)}</span><span class="v">${ver
      ? `<span class="ok-text"><i class="bi bi-check-circle-fill"></i></span> ${P.esc(ver)}`
      : `<span class="${name === "scapy" || name === "waitress" || name === "python-dotenv" ? "warn-text" : "bad-text"}"><i class="bi bi-x-circle-fill"></i> not installed</span>`}</span></div>`).join("");
    const jobs = h.scheduler.jobs;
    $("jobHealth").innerHTML = !h.scheduler.running
      ? '<div class="notice warn"><i class="bi bi-pause-circle"></i><div>Background monitoring is not running (started via <span class="mono">python app.py</span>).</div></div>'
      : jobs.map((j) => `<div class="stat-row"><span class="k">${P.esc(j.label)}<span class="d-block small">every ${j.interval_seconds >= 3600 ? `${j.interval_seconds / 3600}h` : `${j.interval_seconds}s`}</span></span>
          <span class="v small">${j.last_error ? `<span class="bad-text"><i class="bi bi-x-octagon"></i> ${P.esc(j.last_error)}</span><br>` : ""}next ${P.esc(P.fmtTime(j.next_run))}${j.last_run ? ` · last ${P.esc(P.timeAgo(j.last_run))}` : ""}</span></div>`).join("")
        + (jobs.some((j) => j.id === "scan") ? "" : '<div class="small text-muted mt-2">Scheduled scans are off (manual mode, auto-scan disabled, or authorization/subnet missing).</div>');
  }

  async function loadScans() {
    const d = await P.api("GET", "/api/scan/logs?limit=15");
    $("scanRows").innerHTML = d.scans.length ? d.scans.map((s) => `<tr>
      <td title="${P.esc(s.started_at)}">${P.esc(P.fmtDateTime(s.started_at, true))}</td>
      <td>${P.esc(labelFor(s.engine))}</td>
      <td class="hide-xs mono">${P.esc(s.subnet || "—")}</td>
      <td class="hide-xs text-2">${P.esc(s.trigger)}</td>
      <td>${s.status === "success" ? `<span class="ok-text"><i class="bi bi-check-circle-fill"></i> ${s.hosts_found} hosts · ${s.unknown_found} unknown</span>${s.cached_found ? `<span class="d-block small text-muted">incl. ${s.cached_found} from ARP cache</span>` : ""}`
        : s.status === "running" ? '<span class="info-text"><span class="spinner-border spinner-border-sm"></span> Running</span>'
        : `<span class="bad-text"><i class="bi bi-x-circle-fill"></i> ${P.esc(s.error || s.status)}</span>`}</td>
      <td class="text-end tabular hide-xs">${s.duration_ms != null ? `${(s.duration_ms / 1000).toFixed(1)} s` : "—"}</td></tr>`).join("")
      : `<tr><td colspan="6">${P.emptyState("bi-radar", "No scans yet", "Choose Nmap or Scapy, set the authorized subnet and confirm authorization to start scanning.")}</td></tr>`;
  }

  // ------------------------------------------------------------------ events
  form.addEventListener("submit", (ev) => { ev.preventDefault(); save(); });
  form.addEventListener("input", updateDirty);
  form.addEventListener("change", (ev) => {
    if (ev.target.name === "settings_mode") {
      if (ev.target.value === "simple") { proDraft = readAdvanced(); writeAdvanced(preset); }
      else { writeAdvanced(proDraft); }
      P.clearErrors(form);
    }
    syncUi();
    updateDirty();
  });
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("[data-to-pro]");
    if (!a) return;
    ev.preventDefault();
    const pro = form.querySelector('input[name="settings_mode"][value="pro"]');
    pro.checked = true;
    pro.dispatchEvent(new Event("change", { bubbles: true }));
    pro.closest(".glass-card").scrollIntoView({ behavior: "smooth", block: "center" });
  });
  $("resetForm").addEventListener("click", () => { P.clearErrors(form); loadSettings().catch((e) => P.toast(e.message, "error")); });
  $("refreshHealth").addEventListener("click", async () => {
    P.setBusy($("refreshHealth"), true, "Checking");
    try { await loadHealth(true); P.toast("Dependency checks refreshed.", "ok"); } catch (e) { P.toast(e.message, "error"); }
    finally { P.setBusy($("refreshHealth"), false); }
  });
  $("detectSubnet").addEventListener("click", async () => {
    try {
      const d = await P.api("GET", "/api/network/suggest-subnet");
      $("subnetSuggestions").innerHTML = d.suggestions.length
        ? `<span class="small text-muted align-self-center">Suggestions:</span>` + d.suggestions.map((s) =>
          `<button type="button" class="btn btn-glass btn-sm" data-subnet="${P.esc(s.subnet)}" title="From ${P.esc(s.interface)} (${P.esc(s.address)})"><span class="mono">${P.esc(s.subnet)}</span> <span class="text-muted">${P.esc(s.interface)}</span></button>`).join("")
        : '<span class="small text-muted">No private IPv4 networks found on this computer\'s interfaces.</span>';
    } catch (e) { P.toast(e.message, "error"); }
  });
  $("subnetSuggestions").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-subnet]");
    if (b) { form.elements.authorized_subnet.value = b.dataset.subnet; form.elements.authorized_subnet.focus(); updateDirty(); }
  });
  $("reloadScans").addEventListener("click", (e) => { e.preventDefault(); loadScans(); });

  // ------------------------------------------------- unsaved-changes guard
  const unsavedModal = new bootstrap.Modal($("unsavedModal"));
  let pendingUrl = null;

  function go(url) {
    snapshot = "";  // stop the beforeunload prompt
    document.body.classList.add("pe3k-leaving");
    setTimeout(() => { location.href = url; }, 180);
  }
  // Capture phase: runs before the global page-transition handler.
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("a[href]");
    if (!a || !isDirty() || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
    if ((a.target && a.target !== "_self") || a.hasAttribute("download") || a.getAttribute("href").startsWith("#")) return;
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin || url.pathname.startsWith("/export/")) return;
    ev.preventDefault();
    ev.stopImmediatePropagation();
    pendingUrl = url.href;
    $("unsavedError").classList.add("d-none");
    unsavedModal.show();
  }, true);
  $("leaveNoSave").addEventListener("click", () => { unsavedModal.hide(); if (pendingUrl) go(pendingUrl); });
  $("leaveSave").addEventListener("click", async () => {
    P.setBusy($("leaveSave"), true, "Saving");
    const ok = await save();
    P.setBusy($("leaveSave"), false);
    if (ok) { unsavedModal.hide(); if (pendingUrl) go(pendingUrl); return; }
    $("unsavedError").textContent = "Couldn't save — some settings need fixing. Close this box to see the highlighted fields.";
    $("unsavedError").classList.remove("d-none");
  });
  window.addEventListener("beforeunload", (ev) => {
    if (isDirty()) { ev.preventDefault(); ev.returnValue = ""; }
  });

  // ---------------------------------------------------------------- reset
  const resetModal = new bootstrap.Modal($("resetModal"));
  const factoryForm = $("factoryForm");
  const scope = () => factoryForm.querySelector('input[name="scope"]:checked').value;
  function syncReset() {
    const all = scope() === "all";
    $("confirmTyped").classList.toggle("d-none", !all);
    $("confirmCheckWrap").classList.toggle("d-none", all);
    $("doReset").innerHTML = all ? '<i class="bi bi-trash3"></i>Erase everything' : '<i class="bi bi-arrow-counterclockwise"></i>Reset settings';
    $("doReset").disabled = all ? $("resetConfirm").value.trim() !== "RESET" : !$("resetConfirmCheck").checked;
  }
  $("openReset").addEventListener("click", () => {
    factoryForm.reset();
    P.clearErrors(factoryForm);
    syncReset();
    resetModal.show();
  });
  factoryForm.addEventListener("input", syncReset);
  factoryForm.addEventListener("change", syncReset);
  factoryForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const all = scope() === "all";
    P.setBusy($("doReset"), true, all ? "Erasing" : "Resetting");
    try {
      await P.api("POST", "/api/reset", { scope: scope(), confirm: all ? $("resetConfirm").value.trim() : true });
      resetModal.hide();
      if (all) {
        try { localStorage.removeItem("pe3k-theme"); } catch (e) { /* storage unavailable */ }
        P.toast("Pe3k was reset to a fresh install.", "ok");
        snapshot = "";
        setTimeout(() => go("/"), 900);
      } else {
        P.toast("Settings restored to defaults. Devices and history were kept.", "ok");
        P.clearErrors(form);
        await loadSettings();
        loadHealth(true).catch(() => {});
        loadScans().catch(() => {});
        P.updateNav();
      }
    } catch (e) {
      P.showErrors(factoryForm, e);
      P.toast(e.message, "error");
      P.setBusy($("doReset"), false);
      syncReset();
    }
  });

  loadSettings().catch((e) => P.toast(e.message, "error"));
  loadHealth(false).catch((e) => P.toast(e.message, "error"));
  $("scanRows").innerHTML = P.skeletonRows(6, 3);
  P.poll(loadScans, 15000);
})();
