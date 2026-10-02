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
- **Transport**: Persistent ADB shell process with fallback to atomic execution.
- **Advantage**: 100% universal across all Android 7.0 through 14.0 devices regardless of custom kernel input mapping.
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
| `GET` | `/status` | None | Returns connection state, target IP, and active input device. |
| `GET` | `/devices` | None | Lists detected Linux input devices from `/proc/bus/input/devices`. |
| `GET` | `/storage` | None | Returns internal and USB flash storage partition statistics. |
| `POST` | `/cmd` | `{"key": "up"}` | Sends a single directional or functional key. |
| `POST` | `/mouse` | `{"action": "tap", "x": 640, "y": 360}` | Dispatches coordinate tap or swipe. |
| `POST` | `/mouse_rel` | `{"dx": 5, "dy": -2}` | Sends relative cursor delta. |
| `POST` | `/mouse_click` | None | Clicks at current virtual cursor coordinate. |
| `POST` | `/mouse_wheel` | `{"delta": 1}` | Emulates mouse wheel scrolling via Page Up/Down. |
| `POST` | `/cursor_toggle` | None | Toggles on-screen hardware mouse arrow on the display. |
| `POST` | `/text` | `{"text": "query string"}` | Transmits text string into active Android input field. |
| `POST` | `/app` | `{"app": "youtube"}` | Launches designated application package or intent. |
| `POST` | `/command` | `{"command": "UP, RIGHT, OK"}` | Executes sequential macro steps. |
| `POST` | `/connect` | `{"ip": "192.168.1.50"}` | Initiates ADB connection to target host. |
| `POST` | `/scan` | None | Triggers full subnet sweep for active ADB hosts. |

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
- **Tactile Selection**: Center OK, Enter, and Spacebar dispatch an immediate touch click at the exact coordinates of the virtual pointer.
- **Hardware Wake Signaling**: Awakens the hardware cursor via raw Linux kernel input event generation (`EV_KEY 122 KEYCODE_MOVE_HOME`) sent directly to `/dev/input/eventX` alongside system touch indicators.

### B. Dynamic TV App Discovery Architecture
- **Package Enumeration**: Queries Android `cmd package query-activities` for user-launchable activities (`CATEGORY_LAUNCHER` and `CATEGORY_LEANBACK_LAUNCHER`) over ADB.
- **Brand Identity Mapping**: Maps package identifiers (e.g. YouTube, Netflix, Prime Video, Disney+, Kodi, VLC, Plex, Spotify, Stremio, Browser, HDMI) to curated vector iconography and brand accent palettes.
- **Dynamic Launch & Resiliency**: Dispatches single-intent execution (`monkey -p <pkg> -c android.intent.category.LAUNCHER 1`). Scanned applications are cached locally in browser storage to ensure immediate availability across sessions.

