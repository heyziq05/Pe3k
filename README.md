# Pe3k — local network watch

**Author:** [heyziq05](https://github.com/heyziq05) · **Version:** 1.2.1 · [Changelog](CHANGELOG.md)

Pe3k is a self-hosted monitoring, security and bandwidth tool for a home, lab, classroom or
small-office network. It pings your trusted devices, detects unfamiliar hardware with the
discovery engine **you** choose, and tracks the traffic of the computer it runs on — all from a
responsive liquid-glass web UI with light and dark themes.

> **Authorized use only.** Only scan or monitor networks you own or are explicitly authorized to
> monitor. Pe3k scans nothing until you set an authorized subnet *and* tick the authorization box in
> Settings, and it never records hosts outside that range.

---

## Contents

1. [Features](#features)
2. [Quick start](#quick-start)
3. [Discovery engines: Nmap, Scapy, Manual](#discovery-engines)
4. [Configuration](#configuration)
5. [How monitoring works](#how-monitoring-works)
6. [Pages](#pages)
7. [CSV exports](#csv-exports)
8. [Project layout](#project-layout)
9. [Tests](#tests)
10. [Security notes](#security-notes)
11. [Troubleshooting](#troubleshooting)

---

## Features

| Area | What you get |
|---|---|
| **Trusted devices** | Add / edit / remove, search & filter, trust toggle. Fields: name, IP, MAC, type (router, laptop, desktop, phone, tablet, printer, server, IoT, other), trusted, status, last seen, date added, notes. |
| **Availability monitoring** | APScheduler pings every device every 30–60 s (configurable) with timeouts and retries. A device is only **offline** after *N* consecutive failed checks (default 3) — a single lost ping shows as *unstable*, never as an alert. Uptime %, total / successful / failed checks, latency and outage history. |
| **Discovery engine** | Pick **Nmap**, **Scapy (ARP)** or **Manual**. Dependency & privilege checks before every scan, setup instructions, no silent fallback, overlapping scans prevented, subnet validated. |
| **Unknown-device alerts** | Discovered MACs are compared with trusted devices. Alerts show IP, MAC, vendor/hostname, detection time, engine and status, and are de-duplicated. One-click **Trust Device**, **Ignore** or **Resolve**. |
| **Offline alerts** | Created when a device crosses the failure threshold; auto-resolved when it replies again. |
| **Bandwidth** | Live download/upload Mbps of the host computer (psutil), totals, daily totals, history charts, interface picker. |
| **CSV exports** | Devices, a device's monitoring history, alerts, bandwidth logs and uptime summary. |
| **UI** | Light/dark toggle (remembered in `localStorage`, defaults to the OS preference), responsive layout, accessible status badges (icon + label), loading skeletons, empty states. |
| **Reliability** | Transactions, parameterised SQL, validation, structured JSON logs, scheduler started once with graceful shutdown, retention cleanup, demo mode. |

---

## Quick start

Requires **Python 3.10+** (tested on 3.13).

### Windows

```bat
cd C:\projects\Pe3k
start-pe3k.bat
```

The script creates a virtual environment, installs `requirements.txt` and starts Pe3k.
Open **http://localhost:5000**.

Manual equivalent:

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      &REM optional
python app.py
```

### Linux / macOS

```bash
./start-pe3k.sh            # or: python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && python app.py
```

### Try it with demo data (no network access needed)

```bash
# Windows (cmd):   set PE3K_DEMO_MODE=true && python app.py
# PowerShell:      $env:PE3K_DEMO_MODE="true"; python app.py
# Linux/macOS:     PE3K_DEMO_MODE=true python app.py
```

Demo mode seeds 9 sample devices in `192.168.88.0/24`, a week of history, bandwidth logs and a
few alerts. Ping results and the **Demo (simulated)** discovery engine are generated — no packets
are sent — and a banner makes that obvious. Bandwidth figures are always real.

To use a fresh, empty database afterwards: `python app.py reset-db --yes`.

### Commands

| Command | Purpose |
|---|---|
| `python app.py` | Run the web UI and background monitoring (Waitress server). |
| `python app.py init-db` | Create the database and default settings. |
| `python app.py seed-demo [--force]` | Add sample devices & history. Outside demo mode their live pinging is paused. |
| `python app.py reset-db --yes` | Delete **all** Pe3k data. |

---

## Discovery engines

Choose one engine on **Settings → Discovery engine**. Pe3k checks its requirements before each
scan. If anything is missing the scan is recorded as **failed** with the reason — Pe3k never
switches to another engine behind your back. The active engine, scan status, last scan time,
discovered-host count and errors are shown on the Dashboard, the top bar and Settings.

### Manual mode (default — works everywhere)

No scanning. Add devices yourself on **Trusted Devices**. Availability monitoring, alerts for
offline devices, bandwidth and exports all still work. Ideal on Windows without admin rights.

### Nmap

1. Install Nmap from <https://nmap.org/download.html>.
   * **Windows:** run the installer and keep **Npcap** ticked.
   * **Linux:** `sudo apt install nmap` (Debian/Ubuntu) or `sudo dnf install nmap`.
   * **macOS:** `brew install nmap`.
2. Check it works in a *new* terminal: `nmap --version`. If it is not on `PATH`, set the full path
   in Settings (e.g. `C:\Program Files (x86)\Nmap\nmap.exe`). Only an executable named
   `nmap`/`nmap.exe` is accepted.
3. **Privileges:** run Pe3k as Administrator (Windows) or with `sudo` (Linux/macOS) so Nmap can use
   ARP and report **MAC addresses**. Without privileges Nmap still finds hosts via TCP/ICMP probes,
   but MACs are unavailable and unknown devices are matched by IP instead — Settings shows this as
   *Ready with limits*.

Pe3k runs `nmap -sn -oX - --host-timeout <t> --max-retries 1 <authorized-subnet>` (host discovery
only, no port scanning) with the subnet re-validated and passed as a separate argument — no shell.

### Scapy (ARP)

1. `pip install scapy` (already in `requirements.txt`).
2. **Windows:** install **Npcap** from <https://npcap.com> and tick *WinPcap API-compatible mode*.
3. **Privileges are required** — ARP scanning sends raw Ethernet frames:
   * Windows: start the terminal with *Run as administrator*.
   * Linux: `sudo ./start-pe3k.sh`, or grant capabilities once:
     `sudo setcap cap_net_raw,cap_net_admin=eip $(readlink -f .venv/bin/python)`.
   * macOS: `sudo`.

Scapy sends one ARP request per address in the authorized subnet on the interface that routes to
it, waits a few seconds for replies and reports IP + MAC (+ vendor where known).

### ARP cache merge (on by default)

After an Nmap or Scapy scan, Pe3k also reads this computer's own neighbour table (`arp -a` on
Windows, `ip neigh` on Linux, `arp -an` on macOS). This list holds devices the computer exchanged
traffic with recently. It is used in two ways:

* devices that were awake recently but asleep during the scan (typically **locked iPhones**) are
  added, and their alerts show the engine as e.g. `scapy+arp-cache`;
* MAC addresses that Nmap couldn't read (no admin rights) are filled in.

No packets are sent and only entries inside the authorized subnet are used. Recent scans show
“incl. N from ARP cache”. Turn it off in **Settings → Scan scope** ("Also use this computer's ARP
cache").

### Scope controls

* **Authorized subnet** — CIDR (e.g. `192.168.1.0/24`). “Detect” suggests ranges from this
  computer's own interfaces; nothing is saved until you click *Save*.
* **Authorization checkbox** — scans are blocked until ticked.
* **Strict scope** (on by default, can be turned off):
  * on: subnet must be private/link-local and no larger than **/22** (1,024 addresses); only
    private/local IPs can be added as devices or pinged;
  * off: subnets up to **/16** and public device IPs (e.g. monitor `1.1.1.1` as an “internet up”
    check). Scans still never leave the authorized subnet.

---

## Configuration

Runtime settings live in SQLite and are edited on the **Settings** page.

### Simple and Pro mode

* **Simple** (default) — you choose the discovery engine, the authorized subnet, the authorization
  checkbox and whether scans run automatically. Everything else (scan schedule, ping timing,
  retries, failure thresholds, ping method, strict scope, ARP cache, phone profile) uses the
  recommended presets in the table below and is locked.
* **Pro** — every setting can be customised. Your Pro values are kept when you switch to Simple
  and come back when you switch to Pro again.

Changes only take effect after **Save settings** (the sticky bar at the bottom shows when
something is unsaved). If you leave the page with unsaved changes, Pe3k asks whether to save them
first; closing the tab or refreshing triggers the browser's own warning.

### Reset

**Settings → Danger zone → Reset…** offers:

* **Reset settings only** — every setting returns to its default; devices, history, alerts and
  bandwidth logs are kept (tick the confirmation box);
* **Factory reset** — deletes all devices, monitoring history, alerts, bandwidth logs, scan logs
  and settings and forgets the theme choice, like a fresh install (type `RESET` to confirm). It is
  refused while a scan is running.

The defaults / Simple-mode presets:

| Setting | Default | Notes |
|---|---|---|
| Discovery engine | `manual` | `nmap`, `scapy`, `manual` (`demo` in demo mode) |
| Authorized subnet | *(empty)* | Required for scanning |
| Scan interval / timeout | 300 s / 60 s | Timeout must be shorter than the interval |
| Automatic scans | off | Needs subnet + authorization |
| Ping interval | 45 s | 30–60 s recommended (10–3600 allowed) |
| Ping timeout / retries | 1.5 s / 2 | A check passes if any attempt replies |
| Consecutive-failure threshold | 3 | Checks before a device counts as offline |
| Ping method | `auto` | `ping3`, falling back (visibly) to the OS `ping` command if raw ICMP isn't permitted |
| Offline alerts | on | |
| ARP cache merge | on | Adds recently seen devices from `arp -a` to Nmap/Scapy scans |
| Phone & tablet profile | on · 3 s timeout · 4 retries · 0.75 s gap · 6 failures | Used for devices typed *Phone* or *Tablet*; a phone check must finish within one ping interval |
| Bandwidth interface | `all` | All non-loopback interfaces, or a specific one |

Process-level options come from environment variables or a `.env` file — see
[`.env.example`](.env.example). Nothing network-specific (ranges, executable paths, credentials)
is hard-coded.

---

## How monitoring works

```
APScheduler (one per process, coalesce + max_instances=1)
 ├─ ping job (every ping_interval)   → ThreadPool pings → one DB transaction:
 │     monitor_logs row per device, device status / failures / latency, offline alerts
 ├─ scan job (every scan_interval)   → preflight (engine, privileges, subnet, authorization)
 │     → selected engine → match MACs vs trusted devices → de-duplicated unknown-device alerts
 ├─ bandwidth job (every 5 s)        → psutil counters → live series; aggregated row every 60 s
 └─ maintenance (daily)              → prune old monitor/bandwidth/scan logs
```

**Phones and tablets** power-save their Wi-Fi when locked, so devices with type *Phone* or *Tablet*
use a gentler ping profile: longer timeout, more retries spaced further apart, and more
consecutive failures before they count as offline. Set the right device type when you add them.

**Status model:** `online` → (missed reply) `unstable` → (*threshold* consecutive misses)
`offline` → (any reply) `online`. New devices are `pending` until their first reply or until
they reach the threshold.

**Alert de-duplication:** every alert has a key (`unknown:<MAC>`, `unknown-ip:<IP>` when MACs
are unavailable, `offline:<device id>`). While an alert with that key is *open* or *ignored*, new
detections only update `last seen` and the occurrence counter — a partial unique index enforces
this in the database. *Ignore* keeps a device muted; *Resolve* closes it (a later detection opens
a fresh alert); *Trust Device* adds it to trusted devices and closes all its alerts.

**Bandwidth limitation:** Pe3k measures the network interfaces of the computer it runs on. It
cannot see per-device traffic of other machines on your LAN (that needs router/switch-level
monitoring such as SNMP or NetFlow).

**Timestamps** are stored in UTC (`YYYY-MM-DDTHH:MM:SSZ`) and shown in your browser's local time.
Daily bandwidth totals are grouped by the server's local date.

**Logs:** human-readable on the console, JSON lines in `logs/pe3k.log` (rotated, 5 × 5 MB).

---

## Pages

* **Dashboard** — device counts, online/offline, unknown-device alerts, scanner status with
  *Scan now*, live bandwidth, device status table, recent alerts, latency chart.
* **Trusted Devices** — search, filter by status/type/trust, add/edit modal, trust toggle, ping
  now, remove, CSV export.
* **Alerts** — open / ignored / resolved / trusted tabs, type filter, time range (last hour, 6 h,
  24 h, 7 days, 30 days, all time or a custom from/to), Trust / Ignore / Resolve / Reopen, CSV
  export of exactly the filtered list.
* **Device History** — per-device status, uptime (24h/7d/30d), checks, latency stats, latency and
  availability charts, outage list, paginated check log, CSV exports.
* **Bandwidth Usage** — interface picker, current rates, today's totals, live chart, history
  (1h–30d), daily totals chart + table, CSV export.
* **Settings** — engine selection, scope & schedule, monitoring thresholds, dependency &
  permission health (Nmap, Scapy, Npcap, privileges, packages, background jobs), recent scans.

---

## CSV exports

| Export | URL | Where |
|---|---|---|
| Trusted devices | `/export/devices.csv` | Trusted Devices |
| Device history | `/export/devices/<id>/history.csv?window=24h\|7d\|30d\|all` | Device History |
| Alerts | `/export/alerts.csv?status=…&type=…&window=1h\|6h\|24h\|7d\|30d\|all` or `window=custom&since=<ISO>&until=<ISO>` | Alerts |
| Bandwidth logs | `/export/bandwidth.csv?window=1h\|6h\|24h\|7d\|30d\|all&interface=` | Bandwidth |
| Uptime summary | `/export/uptime.csv?window=24h\|7d\|30d\|all` | Device History |

Files are UTF-8 with BOM (opens cleanly in Excel). Cells beginning with `= + - @` are prefixed
with `'` to prevent spreadsheet formula injection from device names or hostnames.

---

## Project layout

```
Pe3k/
├─ app.py                  entry point (server + CLI commands)
├─ config.py               env-driven configuration
├─ requirements.txt  .env.example  start-pe3k.bat  start-pe3k.sh
├─ engine/
│  ├─ __init__.py          app factory, service container, security headers, error pages
│  ├─ schema.sql           devices, monitor_logs, alerts, bandwidth_logs, settings, scan_logs
│  ├─ db.py                connections, transactions (BEGIN IMMEDIATE), schema init
│  ├─ validators.py        IP / MAC / subnet / device / settings validation
│  ├─ logging_setup.py     JSON + console logging
│  ├─ demo.py              sample devices and synthetic history
│  ├─ services/            device, alert, uptime, settings, bandwidth queries, CSV export
│  ├─ monitoring/
│  │  ├─ pinger.py         ping3 / system ping with retries; simulated pinger for demo
│  │  ├─ monitor.py        ping cycle, status transitions, offline alerts
│  │  ├─ scan_service.py   preflight, overlap lock, result processing, scan logs
│  │  ├─ discovery/        nmap_scanner.py, scapy_scanner.py, manual/demo, get_scanner()
│  │  ├─ bandwidth.py      psutil sampler
│  │  ├─ scheduler.py      APScheduler lifecycle
│  │  └─ system.py         privilege & Npcap detection
│  ├─ routes/              pages.py, api.py (JSON), exports.py (CSV)
│  ├─ templates/           Jinja pages + inline SVG logo
│  └─ static/              css/pe3k.css, js/*.js, img/, vendor/ (Bootstrap, Chart.js, icons, Inter)
└─ tests/                  pytest suite
```

All front-end libraries are vendored in `engine/static/vendor`, so Pe3k works fully offline.

---

## Tests

```bash
pip install -r requirements.txt
python -m pytest
```

Covers device/IP/MAC/subnet/settings validation, uptime and outage calculation, the
consecutive-failure status model, alert de-duplication (repeat detections, ignore, resolve, trust,
DB-level uniqueness, offline auto-resolve), scanner selection (no silent fallback, authorization
and manual-mode blocks, oversized subnets, overlapping scans, Nmap XML parsing) and API/CSV smoke
tests including CSRF and formula-escaping.

---

## Security notes

* Binds to `127.0.0.1` by default. To reach Pe3k from other machines set `PE3K_HOST=0.0.0.0`
  **and** `PE3K_AUTH_PASSWORD` (HTTP Basic auth) — preferably behind HTTPS.
* State-changing API calls require an `X-Pe3k-Request` header (a CSRF guard browsers won't send
  cross-site). Strict CSP, `X-Frame-Options: DENY`, `nosniff`.
* All SQL is parameterised; dynamic column names come from fixed whitelists.
* Subprocesses use argument lists (no shell); the Nmap path must point to `nmap`/`nmap.exe`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Every device shows *offline* on Windows | Windows Firewall may block ICMP replies on the targets. Allow “File and Printer Sharing (Echo Request)” on them, or check *Settings → Active ping method*. |
| Settings says “ping3 unavailable … using the system ping command” | Normal without admin rights in `auto` mode. Run elevated to use ping3 directly. |
| Nmap: *Not found* | Open a new terminal after installing, or set the full `nmap.exe` path in Settings. |
| Nmap finds hosts but MACs are “unavailable” | Run Pe3k as Administrator/root (the ARP cache merge fills in many of them anyway). |
| iPhones are missing from scans | Locked iPhones sleep their Wi-Fi. Keep the ARP cache merge on, wake the phone and rescan, or add it manually (Settings → Wi-Fi → (i) shows its IP and Wi-Fi address). Set **Private Wi-Fi Address** to *Fixed*/off for your network. |
| Subnet rejected as “a single address” | Enter a range with a prefix, e.g. `192.168.0.0/24`, or use **Detect**. |
| Scapy: *Not ready – Privileges* / *Npcap* | Run elevated; install Npcap on Windows. |
| Scan fails with “too large” | Use a smaller subnet (≤ /22 with Strict scope, ≤ /16 without). |
| Bandwidth shows “interface not found” | Pick another interface on the Bandwidth page (adapter names change, e.g. VPNs). |
| Database locked errors | Make sure only one Pe3k process uses the same database file. |

---

## Author

Pe3k is created and maintained by **heyziq05** — <https://github.com/heyziq05>.
