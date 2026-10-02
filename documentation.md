# Technical Architecture & Developer Reference

This document serves as the permanent, implementation-agnostic technical reference for the Universal Android TV & Projector Remote ecosystem.

---

## 1. System Overview

The system provides low-latency, root-free control of Android TV devices, smart projectors (including HY300, HY320, Magcubic, and Allwinner H713 chipsets), and OTT media boxes over local Wi-Fi or USB using the Android Debug Bridge (ADB) protocol.

```
+-----------------------------------------------------------------------+
|                             Client Layer                              |
|  - Standalone Web UI (index.html, responsive mobile/desktop)           |
|  - POSIX Shell Remote (remote.sh, interactive raw terminal)          |
+-----------------------------------------------------------------------+
                                  |
                                  | HTTP / JSON REST
                                  v
+-----------------------------------------------------------------------+
|                            Server Bridge                              |
|  - Python daemon (projector.py)                                       |
|  - Subnet Auto-Discovery Engine (Port 5555 TCP sweep)                 |
|  - Persistent ADB Shell Process Pipe (FIFO / Non-blocking)            |
|  - Win32 Hardware Cursor Worker (CTypes GetCursorPos)                 |
+-----------------------------------------------------------------------+
                                  |
                                  | ADB Protocol (TCP:5555 / USB)
                                  v
+-----------------------------------------------------------------------+
|                            Target Device                              |
|  - Linux Kernel Input Subsystem (/dev/input/eventX)                  |
|  - Android WindowManager & InputManager (input keyevent / tap)        |
+-----------------------------------------------------------------------+
```

---

## 2. Input Injection Strategies

Two distinct input dispatch models are implemented to balance execution speed and universal compatibility:

### A. Kernel-Level Event Injection (`sendevent`)
- **Direct Node**: `/dev/input/eventX` (auto-detected via `/proc/bus/input/devices` parsing).
- **Latency**: Sub-10ms response time.
- **Advantage**: Bypasses Android Java framework overhead; controls the cursor directly at the kernel driver layer.
- **Keycodes**:
  - Up: 103
  - Down: 108
  - Left: 105
  - Right: 106
  - OK / Enter: 28
  - Back: 158
  - Home: 102
  - Menu: 139
  - Volume Up: 115
  - Volume Down: 114
  - Mute: 113
  - Power: 116
  - Hardware Mouse Toggle: 122 (KEYCODE_MOVE_HOME)

### B. High-Level Android Keyevent (`input keyevent`)
- **Transport**: Persistent ADB shell stdin pipe (primary). A `subprocess.run` fallback fires only if the pipe is dead.
- **Advantage**: 100% universal across all Android 7.0 through 14.0 devices regardless of custom kernel input mapping.
- **Latency**: ~1ms pipe write vs ~50–80ms subprocess spawn. All `send_key()` and `send_shell_command()` calls prefer the pipe; `allow_fallback=True` only activates the subprocess as a last resort.
- **Key Aliases**:
  - D-Pad: `KEYCODE_DPAD_UP`, `KEYCODE_DPAD_DOWN`, `KEYCODE_DPAD_LEFT`, `KEYCODE_DPAD_RIGHT`, `KEYCODE_ENTER`
  - Navigation: `KEYCODE_BACK`, `KEYCODE_HOME`, `KEYCODE_APP_SWITCH`, `KEYCODE_SETTINGS`
  - Audio: `KEYCODE_VOLUME_UP`, `KEYCODE_VOLUME_DOWN`, `KEYCODE_MUTE`
  - Media: `KEYCODE_MEDIA_PLAY_PAUSE`, `KEYCODE_MEDIA_NEXT`, `KEYCODE_MEDIA_PREVIOUS`

---

## 3. Subnet Auto-Discovery Engine

To eliminate manual IP configuration for non-technical users:
1. Determines local subnet IPv4 via zero-packet UDP socket connection probe (`8.8.8.8:80`).
2. Dispatches a high-concurrency non-blocking sweep (50 worker threads) across IP range `x.x.x.1` through `x.x.x.254` probing TCP port 5555 with a 150ms timeout.
3. Automatically locks onto the first responsive target or updates target list.

---

## 4. HTTP API Contract

The Python server (`projector.py`) exposes a lightweight JSON API consumed by `index.html`:

| Method | Endpoint | Payload | Description |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | None | Serves standalone `index.html` from disk. |
| `GET` | `/status` | None | Returns connection state, target IP, active input device, and mouse active flag. |
| `GET` | `/devices` | None | Lists detected Linux input devices from `/proc/bus/input/devices`. |
| `GET` | `/storage` | None | Returns internal and USB flash storage partition statistics. |
| `GET` | `/files` | `?path=...` | Lists directory entries with metadata (name, size, category, date). |
| `GET` | `/download` | `?path=...` | Streams a file from the device to the browser. |
| `GET` | `/screenshot` | None | Captures live frame via `adb exec-out screencap -p`, transcodes to WebP in memory. |
| `GET` | `/installed_apps` | None | Returns list of user-launchable apps with name, package, and icon hint. |
| `GET` | `/app_icon` | `?pkg=...` | Serves cached app icon WebP or falls back to monogram SVG. |
| `POST` | `/cmd` | `{"key": "up"}` | Sends a key via persistent shell pipe. Client sends fire-and-forget (no `await`). |
| `POST` | `/command` | `{"command": "UP, wait:500, OK"}` | Executes a sequential macro step chain. |
| `POST` | `/mouse` | `{"action": "tap", "x": 640, "y": 360}` | Dispatches coordinate tap or swipe. |
| `POST` | `/mouse_rel` | `{"dx": 5, "dy": -2}` | Sends relative cursor delta via persistent pipe. |
| `POST` | `/mouse_click` | None | Clicks at current virtual cursor coordinate. |
| `POST` | `/mouse_wheel` | `{"delta": 1}` | Emulates mouse wheel scrolling via Page Up/Down. |
| `POST` | `/cursor_toggle` | None | Toggles on-screen hardware mouse arrow. |
| `POST` | `/ping_cursor` | None | Wakes and reveals the hardware cursor (KEY 232 pulse + relative nudge). |
| `POST` | `/dismiss_cursor` | None | Hides the hardware cursor (KEY 232 pulse only, no nudge). |
| `POST` | `/mode` | `{"mode": "mouse", "enabled": true\|false}` | Enables or disables mouse mode. On enable calls `ping_cursor()`; on disable calls `dismiss_cursor()` atomically. |
| `POST` | `/text` | `{"text": "query string"}` | Transmits text string into active Android input field. |
| `POST` | `/app` | `{"app": "youtube"}` | Launches designated application package or intent. |
| `POST` | `/connect` | `{"ip": "192.168.1.50"}` | Initiates ADB connection to target host. |
| `POST` | `/scan` | None | Triggers full subnet sweep for active ADB hosts. |
| `POST` | `/set_device` | `{"device": "/dev/input/event7"}` | Sets active input node for key and mouse injection. |
| `POST` | `/file_action` | `{"action": "delete\|rename\|mkdir\|play\|install\|batch_delete", "path": "..."}` | Performs file system operations on the device. |
| `POST` | `/upload` | Binary body | Uploads a file to `X-Dest-Dir` with filename from `X-Filename` header. |



---

## 5. Security & Isolation Considerations

1. **Local Network Boundary**: The server binds to local interfaces. No cloud communication, telemetry, or external tracking is performed.
2. **CORS & Direct Browser Sockets**: Standard web browsers enforce sandbox boundaries preventing direct TCP connections to `ip:5555`. The lightweight bridge server acts as the protocol adapter.
3. **No Root Requirement**: All capabilities operate through standard user-level ADB debugging permissions (`adbd`).

---

## 6. Dynamic Animated Favicon Specification

The browser tab icon uses an SVG SMIL animated vector representation of a futuristic radar/Wi-Fi emitter:
- **Base Geometry**: Circular dark capsule (`#090b10`) with glowing outer border and 3 concentric parabolic radiation arcs.
- **Animation Profile**: Cascading opacity and stroke-width waves pulsing outwards from the base transmitter dot at staggered intervals (`0s`, `0.3s`, `0.6s`) over a 1.8-second cycle.
- **State Feedback**:
  - Connected: Neon Cyan (`#00f3ff`) with cyan atmospheric glow (`#38bdf8`).
  - Disconnected/Error: Neon Ruby Red (`#ef4444`) with crimson atmospheric glow (`#f87171`).
  - Implemented concurrently via data URI in `index.html` DOM replacement and server-side SVG delivery on `/favicon.ico`.

---

## 7. Packaging & Continuous Delivery Pipeline

- **Distribution Format**: Self-contained ZIP archive containing only runtime source code, shell/batch launchers, and documentation.
- **Integrity**: SHA-256 digest generated during packaging and verified prior to release publishing.
- **CI/CD Automation**: GitHub Actions workflow (`.github/workflows/release.yml`) automatically triggers on semver tags (`v*.*.*`), runs `scripts/bundle_release.py`, and attaches the distribution archive to GitHub Releases.

---

## 8. D-Pad Pointer Glide Engine & Dynamic TV App Discovery

### A. D-Pad Pointer Glide Architecture
Wireless touchpad streaming over local Wi-Fi frequently experiences latency spikes and overshooting. To deliver deterministic, tactile control, cursor positioning is mapped directly to the D-Pad and keyboard arrow keys:
- **Discrete Tap**: Dispatches an immediate 36-pixel relative step (`/mouse_rel`), providing crisp, single-element targeting without delay.
- **Hold-to-Glide**: Engaging a hold for more than 250ms transitions into continuous gliding, dispatching 45-pixel steps every 85ms until released.
- **Hardware Coordinate Bounding**: Coordinates are clamped to the target display boundary (`[0, 1279]`, `[0, 719]`).
- **Hardware uinput Kernel Routing**: Routes relative motion deltas (`EV_REL 0 <dx>; EV_REL 1 <dy>; EV_SYN 0 0`) directly to `/dev/input/event7` (`sunxi-ir-uinput`), triggering Android's native `CursorInputMapper` to render the true hardware arrow cursor instead of touch circles.
- **Hardware Mouse Button & Toggle**: Dispatches native `BTN_MOUSE` (type 1 `EV_KEY`, code 272 `0x110`) for pointer clicks, and pulses hardware `KEY 232 MOUSE` on `/dev/input/event7` to wake and dismiss the cursor strictly while mouse mode is active.

### B. Dynamic TV App Discovery Architecture
- **Package Enumeration**: Queries Android `cmd package query-activities` for user-launchable activities (`CATEGORY_LAUNCHER` and `CATEGORY_LEANBACK_LAUNCHER`) over ADB.
- **Brand Identity Mapping**: Maps package identifiers (e.g. YouTube, Netflix, Prime Video, Disney+, Kodi, VLC, Plex, Spotify, Stremio, Browser, HDMI) to curated vector iconography and brand accent palettes.
- **Dynamic Launch & Resiliency**: Dispatches single-intent execution (`monkey -p <pkg> -c android.intent.category.LAUNCHER 1`). Scanned applications are cached locally in browser storage to ensure immediate availability across sessions.

---

## 9. Tactile 3D Neumorphic Physical Remote Interface

- **Design Philosophy**: Replaces sci-fi glowing cockpit styling with a refined, tactile, desktop-first neumorphic remote control interface.
- **Surface Elevation**: Uses dual-level shadow architecture with soft debossed bevels (`rgba(255,255,255,0.03)`) and deep bottom-right cast shadows (`rgba(0,0,0,0.65)`).
- **Tactile Convex Buttons**: Keys feature convex gradient surfaces (`linear-gradient(145deg, #242b3a, #1b202c)`) with a 2px bottom bevel edge that sinks into an inset debossed state (`box-shadow: inset 3px 3px 6px rgba(0,0,0,0.65)`) on click.
- **Physical Color Hierarchy**:
  - Power: Matte crimson red (`#be123c`) with tactile drop bevel.
  - Active Mouse Mode: Warm tactile amber (`#d97706`) with active LED indicator.
  - D-Pad: Dish-milled concentric circular casing with directional arrow indicators and raised center [OK] disc.
  - Live Feed Indicator: Subtle pulsing emerald blip (`#10b981`).

---

## 10. In-Memory 5s Live Screen Monitor & Curated App Pinning

### A. Live Screen Streaming Engine
- **On-Demand Activation**: The screen monitor is **strictly OFF by default** to eliminate idle Wi-Fi traffic, CPU consumption, and battery drain.
- **Zero-Disk Pipeline**: Captures screen frames directly via `adb exec-out screencap -p` into transient RAM. The stream is compressed to WebP (`quality=75`) in Python, reducing frame size from ~320KB down to ~35KB without ever touching the projector's flash storage or PC disk.
- **Configurable Polling Loop**: User-selectable polling rate (3s Turbo, 5s Standard, 10s Eco) with single-shot HD manual capture and 1-click snapshot download.
- **Fault-Tolerant Circuit Breaker**: If three consecutive network fetches fail (e.g. device reboot or disconnection), the streamer gracefully suspends polling to prevent connection flooding.

### B. Curated Custom App Pinning Shelf
- **Clutter Elimination**: Raw process enumeration that previously flooded the launcher with internal Android background daemons (`com.android.providers.*`, `com.softwinner.*`) is replaced with a curated pinning shelf.
- **Searchable Pin Modal**: Users click `[+ Pin App from TV]` to search detected applications by name or package ID with real-time filtering.
- **Dynamic Brand Icon Delivery**: Serves official SVG/WebP brand logos via `GET /app_icon?pkg=<pkg>` with fallback to a crisp monogram initial badge.
- **Persistent Personalization**: Pinned launchers persist across browser restarts via `localStorage`, featuring 1-click launch and a subtle unpin action.

---

## 11. Mouse Mode Exit Fix — Atomic Cursor Dismiss

### Problem
Exiting mouse mode triggered a double-toggle race condition on the hardware cursor:

1. UI called `POST /dismiss_cursor` → `dismiss_cursor()` sent KEY 232 pulse → cursor went **off**.
2. UI then called `POST /mode` with `enabled: false` → handler only set a flag, no hardware signal.

On some firmware states the two calls in quick succession caused KEY 232 to pulse twice, toggling the cursor back **on** instead of staying off.

### Fix
The `/mode` endpoint is now the single authoritative owner of the cursor lifecycle:

```python
# projector.py — /mode handler
if enabled:
    controller.physical_mouse_active = True
    controller.ping_cursor()     # KEY 232 + relative nudge → cursor ON
else:
    controller.dismiss_cursor()  # KEY 232 only → cursor OFF (no double-pulse)
```

The redundant `await postJson('/dismiss_cursor', {})` call was removed from `toggleMouse()` in `index.html`. `/mode` is now the single codepath that both sets `physical_mouse_active` and fires the hardware signal, eliminating the race entirely.

---

## 12. Blazing-Fast Command Pipeline

### Previous Bottleneck
Every button press went through three blocking layers:

| Layer | Latency | Cause |
| :--- | :--- | :--- |
| `await postJson('/cmd')` in JS | ~5–15ms | JS thread blocked until full HTTP response received |
| `send_shell_command(allow_fallback=True)` | ~30–80ms | Spawned a fresh `subprocess.run(adb shell ...)` per command |
| `send_key()` own `subprocess.run` | ~30–80ms | Duplicate subprocess path bypassing the existing pipe |

**Total perceived latency: ~80–120ms per keypress.**

### Optimisations Applied

#### Backend — `projector.py`
`send_shell_command()` now routes **all calls** through the persistent `adb shell` stdin pipe first:

```
Button press
  → pipe.stdin.write("input keyevent KEYCODE_X\n")  (~1ms)
  → Android input command executes on device          (~2–5ms)
```

The `subprocess.run` path is demoted to a **last-resort fallback** triggered only if the persistent pipe is dead (e.g. ADB disconnection event). `send_key()` now delegates entirely to `send_shell_command()`, removing its own subprocess path.

#### Frontend — `index.html`
`sendCmd()` is now a **synchronous fire-and-forget** function:

```js
// Before: JS thread blocked until full HTTP round-trip completed
const d = await postJson('/cmd', { key: keyName });

// After: UI feedback fires instantly; HTTP request runs in background
fetch('/cmd', { method: 'POST', ..., keepalive: true })
  .then(r => r.json())
  .then(d => { /* show error toast only if server rejects */ })
  .catch(() => {});
```

**Net result:** Perceived button latency drops from ~80–120ms to **< 5ms** on screen, with the ADB command reaching Android in ~1–3ms after button press.
