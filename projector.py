"""Universal Android TV & Projector Remote - Desktop Command Control Panel
High-performance, low-latency web remote with native Linux kernel sendevent streaming,
dynamic input device discovery, hardware cursor tracking, on-screen pointer toggle,
mouse-wheel scrolling, command terminal with history, configurable hotkeys, and desktop UI.
"""

import argparse
import concurrent.futures
import ctypes
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser

# ---------------------------------------------------------------------------
# Configuration & Constants
# ---------------------------------------------------------------------------
DEFAULT_PORT = 7070
DEFAULT_IP = "192.168.100.5"
PROJECTOR_WIDTH = 1280
PROJECTOR_HEIGHT = 720

def resolve_adb_path():
    """Resolves ADB binary across system PATH, local directory, or platform-tools subfolder."""
    exe = "adb.exe" if os.name == "nt" else "adb"
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), exe)
    if os.path.isfile(local_path):
        return local_path
    sub_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "platform-tools", exe)
    if os.path.isfile(sub_path):
        return sub_path
    sys_path = shutil.which("adb")
    if sys_path:
        return sys_path
    return exe

ADB_PATH = resolve_adb_path()

# Linux Input Event Codes for Linux kernel input subsystem
# Dispatches directly to the kernel to bypass Android Java runtime overhead
LINUX_KEY_CODES = {
    "up": 103,
    "down": 108,
    "left": 105,
    "right": 106,
    "ok": 28,
    "enter": 28,
    "back": 158,
    "home": 102,
    "menu": 139,
    "vol_up": 115,
    "vol_down": 114,
    "mute": 113,
    "power": 116,
    "mouse": 122,  # KEYCODE_MOVE_HOME (HY300 Hardware Remote's Mouse Arrow Toggle)
}

# Android Keymap with Universal TV Aliases
KEYMAP = {
    "power": "KEYCODE_POWER",
    "standby": "KEYCODE_POWER",
    "mute": "KEYCODE_MUTE",
    "up": "KEYCODE_DPAD_UP",
    "down": "KEYCODE_DPAD_DOWN",
    "left": "KEYCODE_DPAD_LEFT",
    "right": "KEYCODE_DPAD_RIGHT",
    "ok": "KEYCODE_ENTER",
    "enter": "KEYCODE_ENTER",
    "select": "KEYCODE_ENTER",
    "return": "KEYCODE_ENTER",
    "back": "KEYCODE_BACK",
    "escape": "KEYCODE_BACK",
    "settings": "KEYCODE_SETTINGS",
    "config": "KEYCODE_SETTINGS",
    "home": "KEYCODE_HOME",
    "vol_up": "KEYCODE_VOLUME_UP",
    "volup": "KEYCODE_VOLUME_UP",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volumeup": "KEYCODE_VOLUME_UP",
    "vol_down": "KEYCODE_VOLUME_DOWN",
    "voldown": "KEYCODE_VOLUME_DOWN",
    "volume_down": "KEYCODE_VOLUME_DOWN",
    "volumedown": "KEYCODE_VOLUME_DOWN",
    "menu": "KEYCODE_MENU",
    "recents": "KEYCODE_APP_SWITCH",
    "mouse": "KEYCODE_MOVE_HOME",
    "airplay": "KEYCODE_MEDIA_PLAY",
    "miracast": "KEYCODE_MEDIA_FAST_FORWARD",
    "play": "KEYCODE_MEDIA_PLAY_PAUSE",
    "pause": "KEYCODE_MEDIA_PLAY_PAUSE",
    "play_pause": "KEYCODE_MEDIA_PLAY_PAUSE",
    "playpause": "KEYCODE_MEDIA_PLAY_PAUSE",
    "sleep": "KEYCODE_SLEEP",
    "screen_off": "KEYCODE_SLEEP",
    "hdmi": "KEYCODE_TV_INPUT",
    "input": "KEYCODE_TV_INPUT",
    "source": "KEYCODE_TV_INPUT",
}

# ---------------------------------------------------------------------------
# Win32 Hardware Cursor Tracking
# ---------------------------------------------------------------------------
WINDOWS_USER32 = ctypes.windll.user32 if os.name == "nt" else None


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_cursor_pos():
    if WINDOWS_USER32 is None:
        return None
    point = POINT()
    if WINDOWS_USER32.GetCursorPos(ctypes.byref(point)):
        return point.x, point.y
    return None


# ---------------------------------------------------------------------------
# Subnet Auto-Discovery Engine
# ---------------------------------------------------------------------------
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def probe_port(ip, timeout=0.15):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        if s.connect_ex((ip, 5555)) == 0:
            return ip
    except Exception:
        pass
    finally:
        s.close()
    return None


def scan_subnet_for_adb(base_ip=None):
    if not base_ip:
        base_ip = get_local_ip()
    parts = base_ip.split(".")
    if len(parts) != 4 or base_ip == "127.0.0.1":
        return []

    prefix = ".".join(parts[:3])
    targets = [f"{prefix}.{i}" for i in range(1, 255)]
    found = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(probe_port, ip): ip for ip in targets}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                found.append(res)
    return found


# ---------------------------------------------------------------------------
# High-Speed Persistent ADB Shell Engine
# ---------------------------------------------------------------------------
class AdbController:
    def __init__(self, adb_path, target_ip):
        self.adb_path = adb_path
        self.target_ip = target_ip
        self.lock = threading.Lock()
        self.shell_proc = None
        self.is_connected = False
        self.physical_mouse_active = False
        self.visual_touches_enabled = False
        self.input_device = "/dev/input/event7"  # IR remote control node
        self.mouse_device = "/dev/input/event7"  # Relative mouse node
        self.cursor_x = PROJECTOR_WIDTH // 2
        self.cursor_y = PROJECTOR_HEIGHT // 2
        self.mouse_worker_in_flight = False

    def connect(self, target_ip=None):
        if target_ip:
            self.target_ip = target_ip
        self.close_shell()

        try:
            res = subprocess.run(
                [self.adb_path, "connect", f"{self.target_ip}:5555"],
                capture_output=True,
                text=True,
                timeout=4,
            )
            out = (res.stdout + res.stderr).lower()
            self.is_connected = "connected" in out or "already" in out
        except Exception:
            self.is_connected = False

        if self.is_connected:
            self._detect_input_devices()
            self._spawn_shell()
            # Ensure touch cursor circle is OFF on connect
            self.send_shell_command("settings put system show_touches 0")
        return self.is_connected

    def _detect_input_devices(self):
        """Scans /proc/bus/input/devices, prioritizing IR handlers for keys and pointer handlers for mouse."""
        self.detected_devices = []
        try:
            res = subprocess.run(
                [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", "cat /proc/bus/input/devices"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            text = res.stdout
            if text:
                blocks = text.strip().split("\n\n")
                ir_dev = None
                mouse_dev = None
                for block in blocks:
                    name_match = re.search(r'N:\s*Name="([^"]+)"', block)
                    handler_match = re.search(r"H:\s*Handlers=.*?(event\d+)", block)
                    has_rel = "REL=" in block or "mouse" in block.lower()
                    if handler_match:
                        ev_name = handler_match.group(1)
                        dev_path = f"/dev/input/{ev_name}"
                        dev_name = name_match.group(1) if name_match else ev_name
                        is_mouse = has_rel or "mouse" in dev_name.lower()
                        is_ir = "sunxi-ir" in dev_name.lower() or "ir" in dev_name.lower()
                        self.detected_devices.append({
                            "path": dev_path,
                            "name": dev_name,
                            "is_mouse": is_mouse,
                            "is_ir": is_ir,
                        })
                        if is_ir and not ir_dev:
                            ir_dev = dev_path
                        if is_mouse and not mouse_dev:
                            mouse_dev = dev_path

                if ir_dev:
                    self.input_device = ir_dev
                elif mouse_dev:
                    self.input_device = mouse_dev

                if mouse_dev:
                    self.mouse_device = mouse_dev
                else:
                    self.mouse_device = self.input_device
        except Exception:
            pass

        if not self.input_device:
            self.input_device = "/dev/input/event7"
        if not self.mouse_device:
            self.mouse_device = self.input_device

    def set_input_device(self, dev_path):
        if dev_path.startswith("/dev/input/event"):
            self.input_device = dev_path
            self.mouse_device = dev_path
            return True
        return False

    def _spawn_shell(self):
        try:
            self.shell_proc = subprocess.Popen(
                [self.adb_path, "-s", f"{self.target_ip}:5555", "shell"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except Exception:
            self.shell_proc = None

    def close_shell(self):
        with self.lock:
            if self.shell_proc:
                try:
                    self.shell_proc.terminate()
                except Exception:
                    pass
                self.shell_proc = None

    def send_shell_command(self, cmd_line, allow_fallback=True):
        if not self.is_connected:
            return False

        # For discrete actions or whenever fallback is allowed: execute direct, robust subprocess.run
        # This completely avoids Windows anonymous pipe buffering issues, ensuring 100% command delivery.
        if allow_fallback:
            try:
                res = subprocess.run(
                    [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", cmd_line],
                    capture_output=True,
                    text=True,
                    timeout=2.5,
                )
                return res.returncode == 0
            except Exception:
                return False

        # For continuous high-frequency mouse streams (allow_fallback=False): use the persistent pipe
        with self.lock:
            if self.shell_proc is None or self.shell_proc.poll() is not None:
                self._spawn_shell()

            if self.shell_proc and self.shell_proc.poll() is None:
                try:
                    self.shell_proc.stdin.write(cmd_line + "\n")
                    self.shell_proc.stdin.flush()
                    return True
                except (BrokenPipeError, OSError):
                    self._spawn_shell()
                    if self.shell_proc and self.shell_proc.poll() is None:
                        try:
                            self.shell_proc.stdin.write(cmd_line + "\n")
                            self.shell_proc.stdin.flush()
                            return True
                        except Exception:
                            pass
        return False

    def send_key(self, key_name):
        k = key_name.lower().strip()
        if k == "airplay":
            return self.launch_app("airplay")
        if k == "miracast":
            return self.launch_app("miracast")

        if not self.is_connected:
            return False

        keycode = KEYMAP.get(k, key_name)
        if not keycode.startswith("KEYCODE_") and not keycode.isdigit():
            keycode = f"KEYCODE_{keycode.upper()}"

        # Dispatch input keyevent via ADB shell with fast timeout
        try:
            res = subprocess.run(
                [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", f"input keyevent {keycode}"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            return res.returncode == 0
        except Exception:
            return False

    def send_relative_mouse(self, dx, dy):
        idx = int(dx)
        idy = int(dy)
        if idx == 0 and idy == 0:
            return True

        self.cursor_x = max(0, min(PROJECTOR_WIDTH - 1, self.cursor_x + idx))
        self.cursor_y = max(0, min(PROJECTOR_HEIGHT - 1, self.cursor_y + idy))

        # Direct Linux kernel relative hardware mouse packet (EV_REL 0=REL_X, 1=REL_Y, EV_SYN 0=SYN_REPORT)
        # Bypasses touchscreen emulation to keep native hardware arrow cursor active on-screen
        cmd = (
            f"sendevent /dev/input/event7 2 0 {idx} 2>/dev/null; "
            f"sendevent /dev/input/event7 2 1 {idy} 2>/dev/null; "
            f"sendevent /dev/input/event7 0 0 0 2>/dev/null || "
            f"input mouse swipe {int(self.cursor_x)} {int(self.cursor_y)} {int(self.cursor_x + idx)} {int(self.cursor_y + idy)} 20"
        )
        return self.send_shell_command(cmd, allow_fallback=True)

    def send_mouse_click(self):
        """Dispatches on-screen mouse click at the current cursor coordinates."""
        cx = int(self.cursor_x)
        cy = int(self.cursor_y)
        # Native hardware BTN_MOUSE (EV_KEY 0x110 / 272) click on uinput mouse node with fallback
        cmd = (
            "sendevent /dev/input/event7 1 272 1 2>/dev/null; sendevent /dev/input/event7 0 0 0 2>/dev/null; "
            "sendevent /dev/input/event7 1 272 0 2>/dev/null; sendevent /dev/input/event7 0 0 0 2>/dev/null || "
            f"input mouse tap {cx} {cy} || input tap {cx} {cy} || input keyevent KEYCODE_DPAD_CENTER"
        )
        return self.send_shell_command(cmd, allow_fallback=True)

    def send_mouse_wheel(self, delta):
        val = int(delta)
        if val == 0:
            return True
        key = "KEYCODE_PAGE_UP" if val > 0 else "KEYCODE_PAGE_DOWN"
        return self.send_key(key)

    def toggle_remote_mouse(self):
        """Toggles the hardware mouse arrow on the projector/TV screen."""
        if not self.physical_mouse_active:
            return self.ping_cursor()
        else:
            return self.dismiss_cursor()

    def ping_cursor(self):
        """Wakes up and reveals the on-screen cursor on the projector display."""
        self.physical_mouse_active = True
        self.visual_touches_enabled = True
        # Pulse KEY 232 (MOUSE toggle defined in sunxi-ir-uinput.kl) and relative micro-nudge to display arrow
        cmd = (
            "sendevent /dev/input/event7 1 232 1 2>/dev/null; sendevent /dev/input/event7 0 0 0 2>/dev/null; "
            "sendevent /dev/input/event7 1 232 0 2>/dev/null; sendevent /dev/input/event7 0 0 0 2>/dev/null; "
            "sendevent /dev/input/event7 2 0 1 2>/dev/null; sendevent /dev/input/event7 0 0 0 2>/dev/null; "
            "sendevent /dev/input/event7 2 0 -1 2>/dev/null; sendevent /dev/input/event7 0 0 0 2>/dev/null"
        )
        return self.send_shell_command(cmd, allow_fallback=True)

    def dismiss_cursor(self):
        """Hides and dismisses the on-screen mouse pointer and restores grid navigation."""
        self.physical_mouse_active = False
        self.visual_touches_enabled = False
        # Pulse KEY 232 to dismiss the hardware pointer
        cmd = (
            "sendevent /dev/input/event7 1 232 1 2>/dev/null; sendevent /dev/input/event7 0 0 0 2>/dev/null; "
            "sendevent /dev/input/event7 1 232 0 2>/dev/null; sendevent /dev/input/event7 0 0 0 2>/dev/null"
        )
        return self.send_shell_command(cmd, allow_fallback=True)

    def toggle_visual_touches(self):
        self.visual_touches_enabled = not self.visual_touches_enabled
        val = "1" if self.visual_touches_enabled else "0"
        return self.send_shell_command(f"settings put system show_touches {val}")

    def send_text(self, text_str):
        if not text_str:
            return True
        # Plain text streaming: dispatch words directly and spaces via KEYCODE_SPACE
        # This eliminates any %s, %25, or character encoding artifacts on the projector
        words = text_str.split(" ")
        for i, word in enumerate(words):
            if word:
                safe = word.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
                self.send_shell_command(f'input text "{safe}"', allow_fallback=True)
            if i < len(words) - 1:
                self.send_shell_command("input keyevent KEYCODE_SPACE", allow_fallback=True)
        return True

    def launch_app(self, app_type, custom_pkg=""):
        app = app_type.lower().strip()
        if app in ("youtube", "yt"):
            return self.send_shell_command(
                "monkey -p com.google.android.youtube.tv -c android.intent.category.LAUNCHER 1 || "
                "am start -a android.intent.action.VIEW -d https://www.youtube.com || "
                "monkey -p com.google.android.youtube -c android.intent.category.LAUNCHER 1"
            )
        elif app in ("netflix", "nflx"):
            return self.send_shell_command(
                "monkey -p com.netflix.ninja -c android.intent.category.LAUNCHER 1 || "
                "monkey -p com.netflix.mediaclient -c android.intent.category.LAUNCHER 1"
            )
        elif app in ("prime", "amazon", "primevideo"):
            return self.send_shell_command(
                "monkey -p com.amazon.amazonvideo.livingroom -c android.intent.category.LAUNCHER 1 || "
                "am start -a android.intent.action.VIEW -d https://app.primevideo.com"
            )
        elif app in ("browser", "web", "chrome"):
            return self.send_shell_command(
                "am start -a android.intent.action.VIEW -d https://www.google.com || "
                "monkey -p com.android.browser -c android.intent.category.LAUNCHER 1"
            )
        elif app in ("settings", "config"):
            return self.send_shell_command(
                "am start -a android.settings.SETTINGS || input keyevent KEYCODE_SETTINGS"
            )
        elif app in ("hdmi", "source", "input"):
            return self.send_shell_command(
                "am start -n com.softwinner.externalscreen/.MainActivity || "
                "input keyevent KEYCODE_TV_INPUT"
            )
        elif app in ("cast", "miracast"):
            return self.send_shell_command(
                "monkey -p com.softwinner.miracast -c android.intent.category.LAUNCHER 1 || "
                "am start -n com.softwinner.miracast/.MainActivity || "
                "am start -a android.settings.CAST_SETTINGS || "
                "am start -a android.settings.WIRELESS_DISPLAY_SETTINGS"
            )
        elif app in ("airplay", "airpin"):
            return self.send_shell_command(
                "monkey -p com.waxrain.airplaydmr -c android.intent.category.LAUNCHER 1 || "
                "am start -n com.waxrain.airplaydmr/.MainActivity || "
                "am start -a android.settings.CAST_SETTINGS"
            )
        elif app in ("recents", "task_switch", "switch"):
            return self.send_key("recents")
        elif app in ("screenshot", "snap"):
            return self.send_shell_command("input keyevent KEYCODE_SYSRQ")
        elif app in ("sleep", "screen_off", "standby"):
            return self.send_shell_command("input keyevent KEYCODE_SLEEP")
        elif app == "custom" and custom_pkg:
            pkg = custom_pkg.strip().replace(";", "").replace("&", "")
            return self.send_shell_command(
                f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1"
            )
        return False

    def run_custom_command(self, cmd_input):
        if not cmd_input or not cmd_input.strip():
            return []

        raw_steps = [s.strip() for s in cmd_input.replace("\n", ",").split(",") if s.strip()]
        executed = []

        aliases = {
            "volup": "vol_up",
            "volumeup": "vol_up",
            "volume_up": "vol_up",
            "voldown": "vol_down",
            "volumedown": "vol_down",
            "volume_down": "vol_down",
            "enter": "ok",
            "select": "ok",
            "return": "ok",
            "escape": "back",
            "yt": "youtube",
            "nflx": "netflix",
            "pause": "pause",
            "play": "play",
            "playpause": "play_pause",
        }

        for step in raw_steps:
            norm = step.lower()
            if norm in aliases:
                norm = aliases[norm]

            if norm.startswith("wait:") or norm.startswith("delay:"):
                try:
                    ms = int(norm.split(":")[1].strip())
                    time.sleep(ms / 1000.0)
                    executed.append(f"WAIT:{ms}ms")
                except Exception:
                    time.sleep(0.2)
                    executed.append("WAIT:200ms")
            elif norm in ("youtube", "yt", "netflix", "nflx", "prime", "browser", "settings", "hdmi", "cast", "recents", "screenshot", "sleep"):
                self.launch_app(norm)
                executed.append(f"APP:{norm.upper()}")
            elif norm in LINUX_KEY_CODES:
                self.send_key(norm)
                executed.append(f"KEY:{norm.upper()}")
            elif norm in KEYMAP:
                self.send_shell_command(f"input keyevent {KEYMAP[norm]}")
                executed.append(f"KEYEVENT:{KEYMAP[norm]}")
            elif norm.startswith("text:"):
                txt = step[5:].strip()
                self.send_text(txt)
                executed.append(f"TEXT:{txt}")
            elif norm == "cursor" or norm == "mouse":
                self.toggle_remote_mouse()
                executed.append("TOGGLE:CURSOR")
            elif norm == "ping_cursor":
                self.ping_cursor()
                executed.append("PULSE:CURSOR")
            elif norm in ("dismiss_cursor", "hide_cursor", "cursor_off", "mouse_off"):
                self.dismiss_cursor()
                executed.append("DISMISS:CURSOR")
            elif any(norm.startswith(prefix) for prefix in ("input ", "monkey ", "am ", "pm ", "settings ", "sendevent ")):
                self.send_shell_command(step)
                executed.append(f"RAW:{step}")
            else:
                kc = norm if norm.lower().startswith("keycode_") else f"keycode_{norm}"
                self.send_shell_command(f"input keyevent {kc.upper()}")
                executed.append(f"KEY:{kc.upper()}")

            if len(raw_steps) > 1 and not norm.startswith("wait:") and not norm.startswith("delay:"):
                time.sleep(0.06)

        return executed

    def get_storage_info(self):
        """Fetches storage statistics from df and inspects mounted internal and USB volumes."""
        if not self.is_connected:
            return {"connected": False, "volumes": []}

        volumes = []
        try:
            res = subprocess.run(
                [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", "df -k /sdcard; df -k /storage/* 2>/dev/null"],
                capture_output=True,
                text=True,
                timeout=4.0,
            )
            seen_mounts = set()
            for line in res.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 6 and parts[1].isdigit():
                    total_k = int(parts[1])
                    used_k = int(parts[2])
                    free_k = int(parts[3])
                    percent_str = parts[4].rstrip("%")
                    mount = parts[5]

                    if mount in seen_mounts or total_k == 0:
                        continue

                    is_usb = "/storage/" in mount and not any(sub in mount for sub in ("emulated", "self"))
                    if not is_usb and "/sdcard" not in mount and "/storage/emulated" not in mount:
                        continue

                    seen_mounts.add(mount)
                    name = "USB Flash Drive" if is_usb else "Internal Storage"
                    percent = int(percent_str) if percent_str.isdigit() else (round((used_k / total_k) * 100) if total_k else 0)

                    def fmt_k(k):
                        if k >= 1024 * 1024:
                            return f"{k / (1024 * 1024):.1f} GB"
                        elif k >= 1024:
                            return f"{k / 1024:.1f} MB"
                        return f"{k} KB"

                    volumes.append({
                        "name": name,
                        "mount": mount,
                        "is_usb": is_usb,
                        "total_k": total_k,
                        "used_k": used_k,
                        "free_k": free_k,
                        "total_fmt": fmt_k(total_k),
                        "used_fmt": fmt_k(used_k),
                        "free_fmt": fmt_k(free_k),
                        "percent": percent,
                    })
        except Exception:
            pass

        return {
            "connected": self.is_connected,
            "volumes": volumes,
        }

    def list_files(self, remote_path="/sdcard"):
        """Lists directory contents safely with detailed metadata and file categories."""
        if not self.is_connected:
            return {"ok": False, "error": "Not connected to projector", "path": remote_path, "entries": []}

        safe_path = os.path.normpath(remote_path).replace("\\", "/")
        if not safe_path.startswith("/"):
            safe_path = "/" + safe_path
        safe_path = re.sub(r'[\'";`$]', '', safe_path)
        if not safe_path.endswith("/"):
            safe_path += "/"

        try:
            res = subprocess.run(
                [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", f"ls -la -L '{safe_path}' 2>/dev/null || ls -la '{safe_path}'"],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            entries = []
            for line in res.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("total "):
                    continue
                parts = line.split(None, 7)
                if len(parts) < 8:
                    continue
                perms = parts[0]
                is_dir = perms.startswith("d")
                is_link = perms.startswith("l")

                size_str = parts[4]
                size_bytes = int(size_str) if size_str.isdigit() else 0
                date_str = f"{parts[5]} {parts[6]}"
                name = parts[7]

                if name in (".", ".."):
                    continue

                if " -> " in name:
                    raw_name = name.split(" -> ")[0]
                else:
                    raw_name = name

                ext = os.path.splitext(raw_name)[1].lower()
                is_dir_resolved = is_dir or (is_link and not ext)
                category = "folder" if is_dir_resolved else "other"
                if not is_dir_resolved:
                    if ext in (".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".ts", ".m4v", ".webm"):
                        category = "video"
                    elif ext in (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".opus"):
                        category = "audio"
                    elif ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"):
                        category = "image"
                    elif ext in (".apk", ".xapk"):
                        category = "apk"
                    elif ext in (".srt", ".vtt", ".sub", ".ass"):
                        category = "subtitle"
                    elif ext in (".zip", ".rar", ".7z", ".tar", ".gz"):
                        category = "archive"
                    elif ext in (".pdf", ".txt", ".doc", ".docx", ".log", ".json"):
                        category = "document"

                def fmt_bytes(b):
                    if b >= 1024 * 1024 * 1024:
                        return f"{b / (1024 * 1024 * 1024):.2f} GB"
                    elif b >= 1024 * 1024:
                        return f"{b / (1024 * 1024):.1f} MB"
                    elif b >= 1024:
                        return f"{b / 1024:.1f} KB"
                    return f"{b} B"

                entries.append({
                    "name": raw_name,
                    "is_dir": is_dir_resolved,
                    "is_link": is_link,
                    "size_bytes": size_bytes,
                    "size_fmt": "-" if is_dir_resolved else fmt_bytes(size_bytes),
                    "date": date_str,
                    "category": category,
                    "ext": ext,
                })

            entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

            parent_path = "/".join(safe_path.rstrip("/").split("/")[:-1])
            if not parent_path:
                parent_path = "/"

            return {
                "ok": True,
                "path": safe_path.rstrip("/"),
                "parent": parent_path,
                "entries": entries,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "path": safe_path, "entries": []}

    def pull_file_temp(self, remote_path):
        """Pulls a remote file to a local temp file and returns the local temp file path."""
        if not self.is_connected:
            return None
        safe_path = re.sub(r'[\'";`$]', '', remote_path)
        base = os.path.basename(safe_path)
        temp_dir = tempfile.gettempdir()
        local_path = os.path.join(temp_dir, f"hy300_pull_{int(time.time())}_{base}")
        try:
            res = subprocess.run(
                [self.adb_path, "-s", f"{self.target_ip}:5555", "pull", safe_path, local_path],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if res.returncode == 0 and os.path.exists(local_path):
                return local_path
        except Exception:
            pass
        return None

    def push_temp_file(self, temp_path, filename, dest_dir="/sdcard/Download"):
        """Pushes a local file directly into the remote projector directory and triggers media scanning."""
        if not self.is_connected:
            return {"ok": False, "error": "Not connected to projector"}
        safe_filename = os.path.basename(re.sub(r'[^\w\.-]', '_', filename))
        if not safe_filename or safe_filename in (".", ".."):
            safe_filename = f"file_{int(time.time())}"
        safe_dest_dir = os.path.normpath(dest_dir).replace("\\", "/")
        if not safe_dest_dir.startswith("/"):
            safe_dest_dir = "/" + safe_dest_dir
        safe_dest_dir = re.sub(r'[\'";`$]', '', safe_dest_dir).rstrip("/")

        remote_dest = f"{safe_dest_dir}/{safe_filename}"
        try:
            filesize = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
            timeout_sec = max(180, int(filesize / (200 * 1024))) # Adaptive timeout for large media
            res = subprocess.run(
                [self.adb_path, "-s", f"{self.target_ip}:5555", "push", temp_path, remote_dest],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            ok = res.returncode == 0
            if ok:
                subprocess.run(
                    [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d 'file://{remote_dest}'"],
                    capture_output=True,
                    timeout=4,
                )
            return {"ok": ok, "path": remote_dest, "filename": safe_filename}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

    def push_file_data(self, filename, data_bytes, dest_dir="/sdcard/Download"):
        """Pushes binary data directly into the remote projector directory and indexes it."""
        safe_filename = os.path.basename(re.sub(r'[^\w\.-]', '_', filename))
        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"hy300_push_{int(time.time())}_{safe_filename}")
        try:
            with open(temp_path, "wb") as f:
                f.write(data_bytes)
            return self.push_temp_file(temp_path, safe_filename, dest_dir)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def file_action(self, action, target_path="", extra="", paths=None):
        """Executes a file management action: delete, batch_delete, rename, new_file, mkdir, play, or install."""
        if not self.is_connected:
            return {"ok": False, "error": "Not connected to projector"}
        safe_path = re.sub(r'[\'";`$]', '', target_path)
        try:
            if action == "delete":
                res = subprocess.run(
                    [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", f"rm -rf '{safe_path}'"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                return {"ok": res.returncode == 0}
            elif action == "batch_delete":
                items = paths if paths and isinstance(paths, list) else [p.strip() for p in extra.split(",") if p.strip()]
                safe_items = [re.sub(r'[\'";`$]', '', p) for p in items if p.strip()]
                if not safe_items:
                    return {"ok": False, "error": "No items specified for deletion"}
                # Batch rm in single shell call
                quoted_paths = " ".join(f"'{p}'" for p in safe_items)
                res = subprocess.run(
                    [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", f"rm -rf {quoted_paths}"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                return {"ok": res.returncode == 0, "count": len(safe_items)}
            elif action == "rename":
                safe_name = os.path.basename(re.sub(r'[\'";`$]', '', extra).strip())
                if not safe_name:
                    return {"ok": False, "error": "Invalid target name"}
                parent = os.path.dirname(safe_path.rstrip("/"))
                new_path = f"{parent}/{safe_name}"
                res = subprocess.run(
                    [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", f"mv '{safe_path}' '{new_path}'"],
                    capture_output=True,
                    text=True,
                    timeout=6,
                )
                ok = res.returncode == 0
                if ok:
                    subprocess.run(
                        [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d 'file://{new_path}'"],
                        capture_output=True,
                        timeout=3,
                    )
                return {"ok": ok, "path": new_path, "name": safe_name}
            elif action == "new_file":
                safe_name = os.path.basename(re.sub(r'[\'";`$]', '', extra).strip())
                if not safe_name:
                    return {"ok": False, "error": "Invalid file name"}
                new_file = f"{safe_path.rstrip('/')}/{safe_name}"
                res = subprocess.run(
                    [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", f"touch '{new_file}'"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return {"ok": res.returncode == 0, "path": new_file, "name": safe_name}
            elif action == "mkdir":
                safe_name = re.sub(r'[^\w\.-]', '_', extra)
                new_dir = f"{safe_path.rstrip('/')}/{safe_name}"
                res = subprocess.run(
                    [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", f"mkdir -p '{new_dir}'"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return {"ok": res.returncode == 0, "path": new_dir}
            elif action == "play":
                ext = os.path.splitext(safe_path)[1].lower()
                mime = "video/*"
                if ext in (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"):
                    mime = "audio/*"
                elif ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
                    mime = "image/*"
                res = subprocess.run(
                    [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", f"am start -a android.intent.action.VIEW -d 'file://{safe_path}' -t '{mime}'"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return {"ok": res.returncode == 0}
            elif action == "install":
                res = subprocess.run(
                    [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", f"pm install -r '{safe_path}'"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return {"ok": "success" in res.stdout.lower() or res.returncode == 0, "output": res.stdout.strip()}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "Unknown action"}

    def get_installed_apps(self):
        """Scans the connected TV/projector for launchable Leanback and standard applications."""
        if not self.is_connected:
            return {"ok": False, "error": "Device offline", "apps": []}

        cmd = (
            "cmd package query-activities -c android.intent.category.LEANBACK_LAUNCHER -a android.intent.action.MAIN 2>/dev/null || "
            "pm query-intent-activities -a android.intent.action.MAIN -c android.intent.category.LEANBACK_LAUNCHER 2>/dev/null || "
            "cmd package query-activities -c android.intent.category.LAUNCHER -a android.intent.action.MAIN 2>/dev/null || "
            "pm list packages -3"
        )
        try:
            res = subprocess.run(
                [self.adb_path, "-s", f"{self.target_ip}:5555", "shell", cmd],
                capture_output=True,
                text=True,
                timeout=6.0,
            )
            raw = res.stdout or ""
        except Exception as e:
            return {"ok": False, "error": str(e), "apps": []}

        found_packages = set()
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.search(r'(?:package:)?([a-zA-Z0-9_\.]+(?:\.[a-zA-Z0-9_]+)+)', line)
            if match:
                pkg = match.group(1).strip()
                if any(pkg.startswith(p) for p in (
                    "com.android.keyguard",
                    "com.android.systemui",
                    "com.android.providers",
                    "com.android.cts",
                    "android.overlay",
                    "com.google.android.ext.services",
                    "com.android.packageinstaller",
                    "com.google.android.inputmethod"
                )):
                    continue
                found_packages.add(pkg)

        BRAND_MAP = {
            "com.google.android.youtube.tv": {"name": "YouTube", "icon": "youtube", "color": "#ef4444"},
            "com.google.android.youtube": {"name": "YouTube", "icon": "youtube", "color": "#ef4444"},
            "com.liskovsoft.videomanager": {"name": "SmartTube", "icon": "youtube", "color": "#ef4444"},
            "com.liskovsoft.smarttubetv.beta": {"name": "SmartTube Beta", "icon": "youtube", "color": "#ef4444"},
            "com.netflix.ninja": {"name": "Netflix", "icon": "netflix", "color": "#e50914"},
            "com.netflix.mediaclient": {"name": "Netflix", "icon": "netflix", "color": "#e50914"},
            "com.amazon.amazonvideo.livingroom": {"name": "Prime Video", "icon": "prime", "color": "#00a8e1"},
            "com.amazon.avod": {"name": "Prime Video", "icon": "prime", "color": "#00a8e1"},
            "com.disney.disneyplus": {"name": "Disney+", "icon": "disney", "color": "#113ccf"},
            "org.xbmc.kodi": {"name": "Kodi", "icon": "kodi", "color": "#17b2e7"},
            "org.videolan.vlc": {"name": "VLC Player", "icon": "vlc", "color": "#ff8800"},
            "com.plexapp.android": {"name": "Plex", "icon": "plex", "color": "#e5a00d"},
            "com.spotify.tv.android": {"name": "Spotify", "icon": "spotify", "color": "#1ed760"},
            "com.spotify.music": {"name": "Spotify", "icon": "spotify", "color": "#1ed760"},
            "com.stremio.one": {"name": "Stremio", "icon": "stremio", "color": "#7f5af0"},
            "com.android.chrome": {"name": "Chrome", "icon": "browser", "color": "#38bdf8"},
            "com.android.browser": {"name": "Browser", "icon": "browser", "color": "#38bdf8"},
            "com.softwinner.externalscreen": {"name": "HDMI Input", "icon": "hdmi", "color": "#f59e0b"},
            "com.android.settings": {"name": "Settings", "icon": "settings", "color": "#94a3b8"},
            "tv.twitch.android.app": {"name": "Twitch", "icon": "twitch", "color": "#9146ff"},
            "com.hulu.livingroomplus": {"name": "Hulu", "icon": "hulu", "color": "#1ce783"},
            "com.apple.atve.androidtv.appletv": {"name": "Apple TV", "icon": "appletv", "color": "#f8fafc"},
        }

        app_list = []
        for pkg in sorted(found_packages):
            if pkg in BRAND_MAP:
                meta = BRAND_MAP[pkg]
                app_list.append({
                    "package": pkg,
                    "name": meta["name"],
                    "icon": meta["icon"],
                    "color": meta["color"],
                    "is_known": True,
                })
            else:
                parts = pkg.split(".")
                name_cand = parts[-1] if len(parts) > 1 else pkg
                name_cand = re.sub(r'([a-z])([A-Z])', r'\1 \2', name_cand)
                clean_name = name_cand.replace("_", " ").replace("-", " ").title()
                app_list.append({
                    "package": pkg,
                    "name": clean_name,
                    "icon": "generic",
                    "color": "#f59e0b",
                    "is_known": False,
                })

        return {"ok": True, "count": len(app_list), "apps": app_list}


# Global Controller
controller = AdbController(ADB_PATH, DEFAULT_IP)


# ---------------------------------------------------------------------------
# Background Physical Cursor Poller
# ---------------------------------------------------------------------------
def send_mouse_move(dx, dy):
    if not dx and not dy or not controller.is_connected:
        return

    # Dynamic mouse motion scaling
    scale = 5
    x1 = PROJECTOR_WIDTH // 2
    y1 = PROJECTOR_HEIGHT // 2
    x2 = max(0, min(PROJECTOR_WIDTH - 1, x1 + int(dx * scale)))
    y2 = max(0, min(PROJECTOR_HEIGHT - 1, y1 + int(dy * scale)))

    controller.send_shell_command(
        f"input mouse swipe {x1} {y1} {x2} {y2} 50 || input swipe {x1} {y1} {x2} {y2} 50",
        allow_fallback=True
    )


def physical_mouse_worker():
    previous = get_cursor_pos()

    while True:
        time.sleep(0.035)

        if not controller.physical_mouse_active or not controller.is_connected:
            previous = get_cursor_pos()
            continue

        current = get_cursor_pos()
        if current is None:
            continue

        if previous is None:
            previous = current
            continue

        dx = current[0] - previous[0]
        dy = current[1] - previous[1]
        previous = current

        if dx or dy:
            send_mouse_move(dx, dy)


# ---------------------------------------------------------------------------
# Desktop Workstation Control Panel Interface
# ---------------------------------------------------------------------------
def load_html_page():
    """Dynamically loads index.html from disk for instant live updates. Falls back to minimal error page if missing."""
    html_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    if os.path.exists(html_file):
        try:
            with open(html_file, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as err:
            return f"<!DOCTYPE html><html><body><h2>Error loading index.html: {err}</h2></body></html>"
    return "<!DOCTYPE html><html><body><h2>index.html not found</h2><p>Please place index.html in the same directory as projector.py.</p></body></html>"


# ---------------------------------------------------------------------------
# Multi-threaded HTTP Request Handler
# ---------------------------------------------------------------------------
class MasterHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format_str, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path_only = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path_only == "/" or path_only.startswith("/?"):
            self._serve_html(load_html_page())
        elif path_only == "/status":
            self._json(
                {
                    "connected": controller.is_connected,
                    "ip": controller.target_ip,
                    "mouse_active": controller.physical_mouse_active,
                    "touches_active": controller.visual_touches_enabled,
                    "input_device": controller.input_device,
                    "devices": getattr(controller, "detected_devices", []),
                }
            )
        elif path_only == "/devices":
            self._json(
                {
                    "current": controller.input_device,
                    "devices": getattr(controller, "detected_devices", []),
                }
            )
        elif path_only == "/storage":
            self._json(controller.get_storage_info())
        elif path_only == "/favicon.ico":
            main_color = "#00f3ff" if controller.is_connected else "#ef4444"
            glow_color = "#38bdf8" if controller.is_connected else "#f87171"
            svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<defs>
  <linearGradient id="wf" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" stop-color="{main_color}"/>
    <stop offset="100%" stop-color="{glow_color}"/>
  </linearGradient>
  <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
    <feGaussianBlur stdDeviation="2.5" result="b"/>
    <feComposite in="SourceGraphic" in2="b" operator="over"/>
  </filter>
</defs>
<rect width="100" height="100" rx="24" fill="#090b10" stroke="{main_color}" stroke-width="3" stroke-opacity="0.4"/>
<path d="M 18 34 A 45 45 0 0 1 82 34" fill="none" stroke="url(#wf)" stroke-width="7" stroke-linecap="round" filter="url(#glow)">
  <animate attributeName="opacity" values="0.25;1;0.25" dur="1.8s" begin="0.6s" repeatCount="indefinite"/>
  <animate attributeName="stroke-width" values="6.5;8.5;6.5" dur="1.8s" begin="0.6s" repeatCount="indefinite"/>
</path>
<path d="M 30 49 A 28 28 0 0 1 70 49" fill="none" stroke="url(#wf)" stroke-width="7" stroke-linecap="round" filter="url(#glow)">
  <animate attributeName="opacity" values="0.25;1;0.25" dur="1.8s" begin="0.3s" repeatCount="indefinite"/>
  <animate attributeName="stroke-width" values="7;9;7" dur="1.8s" begin="0.3s" repeatCount="indefinite"/>
</path>
<path d="M 41 64 A 13 13 0 0 1 59 64" fill="none" stroke="url(#wf)" stroke-width="7" stroke-linecap="round" filter="url(#glow)">
  <animate attributeName="opacity" values="0.3;1;0.3" dur="1.8s" begin="0s" repeatCount="indefinite"/>
  <animate attributeName="stroke-width" values="7.5;9.5;7.5" dur="1.8s" begin="0s" repeatCount="indefinite"/>
</path>
<circle cx="50" cy="78" r="6" fill="{main_color}" filter="url(#glow)">
  <animate attributeName="r" values="5;7.5;5" dur="1.8s" repeatCount="indefinite"/>
  <animate attributeName="opacity" values="0.6;1;0.6" dur="1.8s" repeatCount="indefinite"/>
</circle>
</svg>'''
            body = svg_content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(body)
        elif path_only == "/files":
            target = query.get("path", ["/sdcard"])[0]
            self._json(controller.list_files(target))
        elif path_only == "/installed_apps":
            self._json(controller.get_installed_apps())
        elif path_only == "/download":
            target = query.get("path", [""])[0]
            if not target:
                self.send_error(400, "Missing path parameter")
                return
            temp_file = controller.pull_file_temp(target)
            if not temp_file or not os.path.exists(temp_file):
                self.send_error(404, "File not found or transfer failed")
                return
            try:
                filesize = os.path.getsize(temp_file)
                filename = os.path.basename(target)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(filesize))
                self.send_header("Connection", "close")
                self.end_headers()
                with open(temp_file, "rb") as f:
                    shutil.copyfileobj(f, self.wfile)
            finally:
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except Exception:
                        pass
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path_only = parsed.path

        if path_only == "/upload":
            try:
                dest = self.headers.get("X-Dest-Dir", "/sdcard/Download")
                raw_name = self.headers.get("X-Filename", "uploaded_file")
                filename = urllib.parse.unquote(raw_name)
                safe_filename = os.path.basename(re.sub(r'[^\w\.-]', '_', filename))
                if not safe_filename or safe_filename in (".", ".."):
                    safe_filename = f"file_{int(time.time())}"
                length = int(self.headers.get("Content-Length", 0))
                temp_dir = tempfile.gettempdir()
                temp_path = os.path.join(temp_dir, f"hy300_stream_{int(time.time())}_{safe_filename}")
                bytes_left = length
                with open(temp_path, "wb") as f_out:
                    while bytes_left > 0:
                        chunk_size = min(bytes_left, 1024 * 1024)
                        chunk = self.rfile.read(chunk_size)
                        if not chunk:
                            break
                        f_out.write(chunk)
                        bytes_left -= len(chunk)
                result = controller.push_temp_file(temp_path, safe_filename, dest)
                self._json(result)
            except Exception as e:
                self._json({"ok": False, "error": str(e)})
            return

        body = self._read_json()
        if body is None and path_only not in ("/scan", "/cursor_toggle", "/touches_toggle", "/mouse_click", "/ping_cursor", "/dismiss_cursor"):
            body = {}

        if path_only == "/cmd":
            key = body.get("key", "")
            ok = controller.send_key(key)
            self._json({"ok": ok})

        elif path_only == "/command":
            cmd_str = body.get("command", "")
            executed = controller.run_custom_command(cmd_str)
            self._json({"ok": True, "executed": executed})
        elif path_only == "/mouse":
            if not body:
                body = {}
            action = body.get("action")
            if action == "tap":
                x = self._bounded_int(body.get("x", PROJECTOR_WIDTH // 2), 0, PROJECTOR_WIDTH - 1)
                y = self._bounded_int(body.get("y", PROJECTOR_HEIGHT // 2), 0, PROJECTOR_HEIGHT - 1)
                controller.cursor_x = x
                controller.cursor_y = y
                ok = controller.send_shell_command(
                    f"input mouse tap {x} {y} || input tap {x} {y}",
                    allow_fallback=True
                )
                self._json({"ok": ok})
                return

            if action == "swipe":
                x1 = self._bounded_int(body.get("x1", 640), 0, PROJECTOR_WIDTH - 1)
                y1 = self._bounded_int(body.get("y1", 360), 0, PROJECTOR_HEIGHT - 1)
                x2 = self._bounded_int(body.get("x2", 640), 0, PROJECTOR_WIDTH - 1)
                y2 = self._bounded_int(body.get("y2", 360), 0, PROJECTOR_HEIGHT - 1)
                duration = self._bounded_int(body.get("duration", 100), 40, 1000)
                controller.cursor_x = x2
                controller.cursor_y = y2
                ok = controller.send_shell_command(
                    f"input mouse swipe {x1} {y1} {x2} {y2} {duration} || input swipe {x1} {y1} {x2} {y2} {duration}",
                    allow_fallback=True
                )
                self._json({"ok": ok})
                return

            self._json({"ok": False, "error": "unknown mouse action"})
            return

        elif path_only == "/mouse_rel":
            dx = body.get("dx", 0)
            dy = body.get("dy", 0)
            ok = controller.send_relative_mouse(dx, dy)
            self._json({"ok": ok, "x": controller.cursor_x, "y": controller.cursor_y})

        elif path_only == "/mouse_click":
            ok = controller.send_mouse_click()
            self._json({"ok": ok, "x": controller.cursor_x, "y": controller.cursor_y})

        elif path_only == "/mouse_wheel":
            delta = body.get("delta", 0)
            ok = controller.send_mouse_wheel(delta)
            self._json({"ok": ok})

        elif path_only == "/cursor_toggle":
            ok = controller.toggle_remote_mouse()
            self._json({"ok": ok, "active": controller.physical_mouse_active, "x": controller.cursor_x, "y": controller.cursor_y})

        elif path_only == "/ping_cursor":
            ok = controller.ping_cursor()
            self._json({"ok": ok, "active": controller.physical_mouse_active, "x": controller.cursor_x, "y": controller.cursor_y})

        elif path_only == "/dismiss_cursor":
            ok = controller.dismiss_cursor()
            self._json({"ok": ok, "active": False, "x": controller.cursor_x, "y": controller.cursor_y})

        elif path_only == "/touches_toggle":
            ok = controller.toggle_visual_touches()
            self._json({"ok": ok, "enabled": controller.visual_touches_enabled})

        elif path_only == "/set_device":
            dev_path = body.get("device", "")
            ok = controller.set_input_device(dev_path)
            self._json({"ok": ok, "input_device": controller.input_device})

        elif path_only == "/text":
            text_str = str(body.get("text", ""))
            ok = controller.send_text(text_str)
            self._json({"ok": ok})

        elif path_only == "/mode":
            mode = body.get("mode")
            enabled = bool(body.get("enabled"))
            if mode == "mouse":
                controller.physical_mouse_active = enabled
                if enabled:
                    controller.ping_cursor()
                self._json({"ok": True, "enabled": enabled})
            else:
                self._json({"ok": False, "error": "unknown mode"})

        elif path_only == "/app":
            app_type = body.get("app")
            custom_pkg = body.get("package", "")
            ok = controller.launch_app(app_type, custom_pkg)
            self._json({"ok": ok})

        elif path_only == "/file_action":
            action = body.get("action", "")
            target_path = body.get("path", "")
            extra = body.get("extra", "")
            paths = body.get("paths", [])
            res = controller.file_action(action, target_path, extra, paths=paths)
            self._json(res)

        elif path_only == "/connect":
            ip = body.get("ip", DEFAULT_IP)
            connected = controller.connect(ip)
            self._json({"ok": True, "connected": connected, "ip": ip})

        elif path_only == "/scan":
            found = scan_subnet_for_adb()
            self._json({"ok": True, "found": found})

        else:
            self.send_error(404)

    @staticmethod
    def _bounded_int(value, low, high):
        try:
            return max(low, min(high, int(value)))
        except (TypeError, ValueError):
            return low

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return None

    def _serve_html(self, content):
        body = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Server Launcher
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Universal Android TV & Projector Remote - Command Control Panel")
    parser.add_argument("--ip", default=DEFAULT_IP, help="Target device IP")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Web server port")
    parser.add_argument("--no-scan", action="store_true", help="Skip startup subnet scan")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args()

    target_ip = args.ip

    print("=" * 60)
    print("  Universal Android TV & Projector Remote - Control Panel Pro")
    print(f"  Local ADB Path : {ADB_PATH}")
    print(f"  Initial Target : {target_ip}:5555")
    print("=" * 60)

    # Blazing Fast Startup: Probe default target first (sub-100ms)
    direct_active = probe_port(target_ip, timeout=0.18)
    if direct_active:
        print(f"[DISCOVERY] Target {target_ip}:5555 is responsive. Bypassing full subnet scan.")
    elif not args.no_scan:
        print(f"[DISCOVERY] Target {target_ip} did not reply immediately; sweeping local subnet...")
        discovered = scan_subnet_for_adb()
        if discovered:
            print(f"[DISCOVERY] Found ADB target(s): {', '.join(discovered)}")
            if target_ip not in discovered:
                target_ip = discovered[0]
                print(f"[DISCOVERY] Switching to active target: {target_ip}")
        else:
            print(f"[DISCOVERY] No active probe reply; falling back to {target_ip}")

    print(f"[ADB] Connecting to {target_ip}:5555...")
    connected = controller.connect(target_ip)
    if connected:
        print(f"[ADB] Connected successfully. Input node: {controller.input_device}")
    else:
        print("[ADB] Warning: Could not connect immediately. You can reconfigure via UI.")

    if os.name == "nt":
        cursor_thread = threading.Thread(target=physical_mouse_worker, daemon=True)
        cursor_thread.start()
        print("[MOUSE] Win32 hardware cursor tracking worker initialized.")

    server_address = ("0.0.0.0", args.port)
    try:
        httpd = http.server.ThreadingHTTPServer(server_address, MasterHandler)
    except OSError as e:
        print(f"[ERROR] Port {args.port} is busy: {e}")
        sys.exit(1)

    url = f"http://127.0.0.1:{args.port}"
    print(f"[READY] Web interface serving at: {url}")
    print("  - Hotkeys: 'O' = Settings, 'Y' = YouTube, 'M' = Mute, etc.")
    print("  - Custom command line enabled (e.g. 'UP, RIGHT, OK')")
    print("  - Mouse wheel scrolling enabled on trackpad")
    print("  - Press Ctrl+C in console to stop server")

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[STOPPING] Shutting down remote server...")
    finally:
        controller.close_shell()
        httpd.server_close()
        print("[STOPPED] Goodbye.")


if __name__ == "__main__":
    main()
