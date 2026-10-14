# Changelog

All notable changes to **Pe3k**, the local network watch by [heyziq05](https://github.com/heyziq05), are listed here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Dates use local time (UTC+8).

---

## [1.2.1] — 2026-10-15

### Changed
- **Project layout:** the Python package folder was renamed from `pe3k/` to **`engine/`**.
  Imports are now `from engine import …`. App start-up (`python app.py`, `start-pe3k.bat`) is
  unchanged, and so are your database (`data/pe3k.sqlite3`), logs and `.env` settings.
- **Authorship:** heyziq05 is credited as the author in the README (top and an "Author" section),
  the code headers (`app.py`, `config.py`, `engine/__init__.py` with `__author__`), the pages'
  `author` meta tag and the launch scripts.
- `start-pe3k.bat` now uses Windows (CRLF) line endings.

### Added
- This changelog.
- `.gitignore` now also excludes local databases (`*.sqlite3`)

---

## [1.2.0] — 2026-10-15

### Added
- **Settings modes: Simple and Pro.**
  - **Simple** (the new default) uses recommended presets and locks the advanced settings: scan
    interval/timeout, ping interval/timeout/retries, failure threshold, ping method, strict scope,
    ARP cache and the phone profile. You only choose the scanner, subnet, authorization and
    automatic scans.
  - **Pro** unlocks every setting. Your Pro values are kept while Simple mode is on and restored
    when you switch back.
  - The server enforces the lock as well: changing a locked setting in Simple mode is rejected.
- **Reset** (Settings → Danger zone, red **Reset…** button) with a confirmation step:
  - *Reset settings only* restores the defaults and keeps devices, history, alerts and bandwidth
    logs. You must tick a confirmation box.
  - *Factory reset* deletes all devices, history, alerts, bandwidth and scan logs and settings, and
    forgets the theme, like a fresh install. You must type `RESET`, and it is refused while a scan
    is running.
- **Unsaved-changes prompt:** leaving Settings with unsaved changes asks "Save your changes?"
  (Yes, save / No, discard). Closing the tab or refreshing triggers the browser's own warning.
- **Sticky save bar** at the bottom of Settings showing "All changes saved" or "Unsaved changes",
  with Discard and Save buttons.
- `PE3K_SETTINGS_MODE` option in `.env.example`.
- Tests for modes, locking and both reset types.

### Changed
- The **Save settings** button at the top of Settings was removed. Saving happens from the
  sticky save bar.
- **Run a scan now** was removed from Settings. Use **Scan now** on the Dashboard, which uses the
  saved settings.

### Fixed
- Buttons inside pop-up dialogs (Add device, Trust device, Reset) could be blocked by the dark
  overlay behind the dialog because of the page animations. Dialogs now always sit on top.

---

## [1.1.0] — 2026-10-14

### Added
- **ARP cache merge:** after every Nmap or Scapy scan, Pe3k also reads this computer's list of
  recently seen devices (`arp -a` on Windows, `ip neigh` on Linux, `arp -an` on macOS).
  - It catches devices that were asleep during the scan, such as locked iPhones, and fills in MAC
    addresses Nmap couldn't read without admin rights.
  - Their alerts are labelled e.g. `scapy+arp-cache`, and Recent scans show
    "incl. N from ARP cache".
  - No packets are sent, only entries inside the authorized subnet are used, and it can be turned
    off in Settings.
- **Phone and tablet ping profile:** devices typed *Phone* or *Tablet* get a longer timeout (3 s),
  more retries (4) spaced further apart (0.75 s), and need 6 failed checks in a row before they
  count as offline. This stops sleeping phones flipping to unstable or offline. The values are
  configurable, and a phone check must finish within one ping interval.
- **Alerts time range:** last hour, 6 hours, 24 hours, 7 days, 30 days, all time, or a custom
  From/To range. **Export CSV** downloads exactly the filtered list, and the file name includes the
  range.
- **Database migrations:** new columns are added to existing databases automatically on start-up.
- **Logo "comes alive" on hover:** it grows with a springy bounce, tilts, glows and blinks, and
  the iris follows the cursor across the top bar.
- **Smooth page transitions:** content fades out when you leave a page and the cards rise in on the
  next one. This works in every browser. With Windows animation effects turned off you get a
  gentle fade instead.
- **Footer credit:** "Made by @heyziq05 on GitHub", linking to the profile.

### Changed
- **New logo:** a white eye with a bright green iris on a green rotated-square tile, with no
  outline. The browser-tab icon matches.
- The subtitle under the logo now reads **Network Watch**.
- Bandwidth CSV export now respects the 1 h and 6 h views; they previously exported 24 h.
- The version number in asset links busts the browser cache, so style and script updates show up
  without a hard refresh.

### Fixed
- **Scapy:** scans crashed with `TypeError: 'list' object is not an iterator` when the subnet
  covered only one or two addresses (`/32`, `/31`).
- **Subnet entry:** a bare IP such as `192.168.0.1` was silently treated as a single-address
  network (`/32`), so scans only found the router. It is now rejected with a hint like
  "use 192.168.0.0/24".

---

## [1.0.0] — 2026-10-14

First release: a self-hosted network monitoring, security and bandwidth tool for home, lab,
classroom and small-office networks.

### Added
- **Stack:** Python + Flask (served by Waitress), SQLite, APScheduler, ping3, psutil, Scapy and
  optional Nmap. Bootstrap, Chart.js, Bootstrap Icons and the Inter font are bundled, so the app
  works fully offline.
- **Trusted devices:** add, edit and remove devices, with search and filters. Each device has a
  name, IP, MAC, type (router, laptop, desktop, phone, tablet, printer, server, IoT, other),
  trusted flag, status, last seen, date added and notes.
- **Availability monitoring:** pings every 30–60 s with timeouts and retries, tracking latency,
  uptime %, total, successful and failed checks, and outage history.
  - A device is marked offline only after a set number of failed checks in a row; a single lost
    ping shows as *unstable*.
  - Pe3k uses the system `ping` command, and shows this in Settings, when Windows doesn't allow
    ping3's direct ping method.
- **Discovery engines:** Nmap, Scapy (ARP) or Manual.
  - Requirements and permissions are checked before every scan, with setup instructions.
  - Pe3k never silently switches to another engine, and overlapping scans are prevented.
  - Settings shows the active engine, scan status, last scan time, errors and the number of
    devices found.
- **Authorized scope:** scanning needs an authorized subnet and an "I own / am authorized"
  checkbox.
  - *Strict scope* (switchable) limits scans to private ranges up to /22 and monitoring to private
    IPs.
  - Nothing outside the subnet is ever recorded.
- **Unknown-device alerts:** one alert per device (repeat sightings update it instead of creating
  new ones), with Trust Device, Ignore and Resolve actions. Offline alerts are created
  automatically and resolve themselves when the device comes back.
- **Bandwidth monitor:** live download/upload Mbps for the computer running Pe3k, totals, daily
  totals, history charts and an interface picker. The page clearly notes that it measures this
  computer only, not every device on the network.
- **CSV exports:** trusted devices, a device's monitoring history, alerts, bandwidth logs and the
  uptime summary. Exports are Excel-friendly and protected against spreadsheet formula injection.
- **Pages:** Dashboard, Trusted Devices, Alerts, Device History, Bandwidth Usage and Settings,
  including a dependency and permission health panel.
- **Design:** an original glass-style interface with matching light and dark themes. The toggle is
  remembered and defaults to the system preference. Green, amber and red always come with an icon
  and label. Works on desktop, tablet and mobile.
- **Demo mode** (`PE3K_DEMO_MODE=true`): sample devices, a week of history and a simulated
  scanner, with no network traffic.
- **Reliability and security:**
  - Database transactions and parameterised SQL, with input validation and structured JSON logs.
  - The background scheduler starts once and shuts down cleanly, and old logs are cleaned up
    automatically after a set number of days.
  - Pe3k is only reachable from this computer by default, with an optional password, protection
    against cross-site requests and strict security headers.
- **Tooling:** `requirements.txt`, `.env.example`, Windows and Linux/macOS launchers, a thorough
  README and an automated test suite (validation, uptime, alert de-duplication and scanner
  selection).

[1.2.1]: #121--2026-10-15
[1.2.0]: #120--2026-10-15
[1.1.0]: #110--2026-10-14
[1.0.0]: #100--2026-10-14
