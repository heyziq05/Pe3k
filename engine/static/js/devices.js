/* Trusted Devices page */
(function () {
  "use strict";
  const P = window.Pe3k;
  const $ = (id) => document.getElementById(id);
  const form = $("deviceForm");
  const modal = new bootstrap.Modal($("deviceModal"));
  let devices = [];
  let debounce = null;

  function query() {
    const q = new URLSearchParams();
    ["search", "status", "type", "trusted"].forEach((k) => {
      const v = $("filters").elements[k].value.trim();
      if (v) q.set(k, v);
    });
    return q.toString();
  }

  async function load(showSkeleton) {
    if (showSkeleton) $("rows").innerHTML = P.skeletonRows(8, 5);
    try {
      const data = await P.api("GET", `/api/devices?${query()}`);
      devices = data.devices;
      render(data);
    } catch (e) {
      $("rows").innerHTML = `<tr><td colspan="8">${P.emptyState("bi-wifi-off", "Couldn't load devices", e.message)}</td></tr>`;
    }
  }

  function render(data) {
    const filtered = query() !== "";
    $("resultCount").textContent = `${devices.length} of ${data.counts.total} device${data.counts.total === 1 ? "" : "s"}`;
    if (!devices.length) {
      $("rows").innerHTML = `<tr><td colspan="8">${filtered
        ? P.emptyState("bi-funnel", "No matching devices", "Try a different search or clear the filters.")
        : P.emptyState("bi-hdd-network", "No trusted devices yet", "Add your router, computers and other known devices. You can also trust devices from scan alerts.",
          '<button class="btn btn-accent btn-sm" data-act="add"><i class="bi bi-plus-lg"></i>Add your first device</button>')}</td></tr>`;
      return;
    }
    $("rows").innerHTML = devices.map((d) => `
      <tr data-id="${d.id}">
        <td><span class="device-name">${P.typeIcon(d.device_type)} ${P.esc(d.name)}</span>
          <span class="sub mono">${P.esc(d.ip_address)}</span>
          <span class="sub d-sm-none mono">${P.esc(d.mac_address || "")}</span></td>
        <td class="hide-xs mono text-2">${P.esc(d.mac_address || "—")}</td>
        <td>${d.monitoring_enabled ? P.statusPill(d.status, d.consecutive_failures ? `${d.consecutive_failures} consecutive failed checks` : "") : '<span class="chip"><i class="bi bi-pause-fill"></i>Paused</span>'}</td>
        <td class="text-end tabular hide-xs">${d.status === "offline" ? "—" : P.fmtMs(d.last_latency_ms)}</td>
        <td class="hide-xs text-2" title="${P.esc(P.fmtDateTime(d.last_seen))}">${P.esc(P.timeAgo(d.last_seen))}</td>
        <td class="hide-xs">
          <div class="form-check form-switch m-0" title="${d.trusted ? "Trusted" : "Not trusted"}">
            <input class="form-check-input" type="checkbox" role="switch" data-act="trust" ${d.trusted ? "checked" : ""} aria-label="Trusted: ${P.esc(d.name)}">
          </div></td>
        <td class="hide-xs text-2">${P.esc(P.fmtDateTime(d.date_added).split(",").slice(0, 2).join(","))}</td>
        <td><div class="table-actions">
          <button class="btn btn-glass btn-sm hide-xs" data-act="ping" title="Ping now" aria-label="Ping ${P.esc(d.name)} now"><i class="bi bi-broadcast"></i></button>
          <a class="btn btn-glass btn-sm hide-xs" href="/history/${d.id}" title="History" aria-label="History for ${P.esc(d.name)}"><i class="bi bi-clock-history"></i></a>
          <button class="btn btn-glass btn-sm" data-act="edit" title="Edit" aria-label="Edit ${P.esc(d.name)}"><i class="bi bi-pencil"></i></button>
          <button class="btn btn-danger-soft btn-sm" data-act="delete" title="Remove" aria-label="Remove ${P.esc(d.name)}"><i class="bi bi-trash3"></i></button>
        </div></td>
      </tr>`).join("");
  }

  // ------------------------------------------------------------------ modal
  function openModal(device) {
    P.clearErrors(form);
    form.reset();
    $("deviceModalTitle").textContent = device ? `Edit ${device.name}` : "Add device";
    form.elements.id.value = device ? device.id : "";
    if (device) {
      form.elements.name.value = device.name;
      form.elements.device_type.value = device.device_type;
      form.elements.ip_address.value = device.ip_address;
      form.elements.mac_address.value = device.mac_address || "";
      form.elements.notes.value = device.notes || "";
      form.elements.trusted.checked = !!device.trusted;
      form.elements.monitoring_enabled.checked = !!device.monitoring_enabled;
    }
    modal.show();
    setTimeout(() => form.elements.name.focus(), 300);
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const id = form.elements.id.value;
    const payload = {
      name: form.elements.name.value, device_type: form.elements.device_type.value, ip_address: form.elements.ip_address.value,
      mac_address: form.elements.mac_address.value, notes: form.elements.notes.value,
      trusted: form.elements.trusted.checked, monitoring_enabled: form.elements.monitoring_enabled.checked,
    };
    P.setBusy($("saveDevice"), true, "Saving");
    try {
      await P.api(id ? "PUT" : "POST", id ? `/api/devices/${id}` : "/api/devices", payload);
      modal.hide();
      P.toast(id ? "Device updated." : `${payload.name} added — first check runs within the ping interval.`, "ok");
      load();
      P.updateNav();
    } catch (e) {
      P.showErrors(form, e);
    } finally { P.setBusy($("saveDevice"), false); }
  });

  // ---------------------------------------------------------------- actions
  $("rows").addEventListener("click", async (ev) => {
    const el = ev.target.closest("[data-act]");
    if (!el) return;
    const act = el.dataset.act;
    if (act === "add") return openModal(null);
    const id = Number(el.closest("tr").dataset.id);
    const device = devices.find((d) => d.id === id);
    if (act === "edit") openModal(device);
    if (act === "delete") {
      const ok = await P.confirm({ title: "Remove device?", okText: "Remove", danger: true,
        body: `<p class="mb-1"><strong>${P.esc(device.name)}</strong> (<span class="mono">${P.esc(device.ip_address)}</span>) and its monitoring history will be deleted.</p><p class="mb-0 small">If it appears in a future scan it will be reported as an unknown device.</p>` });
      if (!ok) return;
      try { await P.api("DELETE", `/api/devices/${id}`); P.toast("Device removed.", "ok"); load(); P.updateNav(); }
      catch (e) { P.toast(e.message, "error"); }
    }
    if (act === "ping") {
      P.setBusy(el, true);
      try {
        const res = await P.api("POST", `/api/devices/${id}/check`);
        const d = res.device;
        P.toast(d.status === "online" ? `${d.name} replied in ${P.fmtMs(d.last_latency_ms)}.` : `${d.name} did not reply (${d.consecutive_failures} consecutive failure${d.consecutive_failures === 1 ? "" : "s"}).`,
          d.status === "online" ? "ok" : "warn");
        load();
      } catch (e) { P.toast(e.message, "error"); } finally { P.setBusy(el, false); }
    }
  });
  $("rows").addEventListener("change", async (ev) => {
    const el = ev.target.closest("[data-act='trust']");
    if (!el) return;
    const id = Number(el.closest("tr").dataset.id);
    try {
      await P.api("POST", `/api/devices/${id}/trust`, { trusted: el.checked });
      P.toast(el.checked ? "Device trusted." : "Device marked as not trusted — it will be reported in scans.", el.checked ? "ok" : "warn");
      P.updateNav();
    } catch (e) { el.checked = !el.checked; P.toast(e.message, "error"); }
  });

  $("addDevice").addEventListener("click", () => openModal(null));
  $("filters").addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(() => load(), 250); });
  $("fReset").addEventListener("click", () => { $("filters").reset(); load(); });

  $("rows").innerHTML = P.skeletonRows(8, 5);
  if (location.hash === "#add") { openModal(null); history.replaceState(null, "", location.pathname); }
  P.poll(() => (document.querySelector(".modal.show") ? null : load()), 20000);
})();
