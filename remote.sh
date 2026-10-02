#!/usr/bin/env bash
# ===========================================================================
# Universal Android TV & Projector Terminal Remote (POSIX / Bash)
# Lightweight, zero-install CLI remote for Linux, macOS, Raspberry Pi & BSD
# ===========================================================================

set -e

# Default Target IP (can be overridden via first argument)
TARGET_IP="${1:-192.168.100.5}"
TARGET_PORT="5555"

# ---------------------------------------------------------------------------
# ADB Binary Resolution
# ---------------------------------------------------------------------------
resolve_adb() {
    if command -v adb >/dev/null 2>&1; then
        echo "adb"
        return 0
    elif [ -x "./adb" ]; then
        echo "./adb"
        return 0
    elif [ -x "./platform-tools/adb" ]; then
        echo "./platform-tools/adb"
        return 0
    elif [ -x "/usr/lib/android-sdk/platform-tools/adb" ]; then
        echo "/usr/lib/android-sdk/platform-tools/adb"
        return 0
    fi
    return 1
}

if ! ADB_BIN=$(resolve_adb); then
    echo "============================================================"
    echo " [ERROR] Android Debug Bridge (adb) was not found."
    echo "============================================================"
    echo " Please install adb using your system package manager:"
    echo "   - Debian/Ubuntu/Mint:  sudo apt install adb"
    echo "   - Arch/Manjaro:        sudo pacman -S android-tools"
    echo "   - Fedora/RHEL:         sudo dnf install android-tools"
    echo "   - macOS (Homebrew):    brew install android-platform-tools"
    echo " Or download official platform-tools from Google:"
    echo "   https://dl.google.com/android/repository/platform-tools-latest-linux.zip"
    echo "============================================================"
    exit 1
fi

DEVICE="${TARGET_IP}:${TARGET_PORT}"

echo "============================================================"
echo " Universal Android TV & Projector Terminal Remote"
echo " ADB Binary : ${ADB_BIN}"
echo " Target     : ${DEVICE}"
echo "============================================================"

# Attempt connection
echo "[CONNECT] Connecting to ${DEVICE}..."
${ADB_BIN} connect "${DEVICE}" || true

send_key() {
    local keycode="$1"
    ${ADB_BIN} -s "${DEVICE}" shell input keyevent "${keycode}" >/dev/null 2>&1 &
}

send_text() {
    local str="$1"
    # Replace spaces with %s for input text compatibility
    local encoded="${str// /%s}"
    ${ADB_BIN} -s "${DEVICE}" shell input text "${encoded}" >/dev/null 2>&1
}

launch_app() {
    local app="$1"
    case "$app" in
        youtube)
            ${ADB_BIN} -s "${DEVICE}" shell "monkey -p com.google.android.youtube.tv -c android.intent.category.LAUNCHER 1 || am start -a android.intent.action.VIEW -d https://www.youtube.com" >/dev/null 2>&1 &
            ;;
        netflix)
            ${ADB_BIN} -s "${DEVICE}" shell "monkey -p com.netflix.ninja -c android.intent.category.LAUNCHER 1" >/dev/null 2>&1 &
            ;;
        settings)
            ${ADB_BIN} -s "${DEVICE}" shell "am start -a android.settings.SETTINGS || input keyevent KEYCODE_SETTINGS" >/dev/null 2>&1 &
            ;;
    esac
}

show_help() {
    echo ""
    echo " [KEYMAP CHEATSHEET]"
    echo "  Navigation : Arrow Keys or W / A / S / D"
    echo "  OK/Select  : Enter or Space"
    echo "  Back       : Esc, Backspace, or B"
    echo "  Home       : H"
    echo "  Menu       : M"
    echo "  Settings   : O"
    echo "  Power      : P"
    echo "  Volume Up  : + or ="
    echo "  Volume Down: - or _"
    echo "  Mute       : X"
    echo "  Text Input : T (prompts for string)"
    echo "  YouTube    : Y"
    echo "  Netflix    : N"
    echo "  Quit       : Q"
    echo "  Help       : ?"
    echo ""
}

show_help

# Configure terminal raw mode for non-blocking keypress capture
old_stty_cfg=$(stty -g 2>/dev/null || true)
cleanup() {
    if [ -n "${old_stty_cfg}" ]; then
        stty "${old_stty_cfg}" 2>/dev/null || true
    fi
    echo ""
    echo "[EXIT] Remote disconnected. Goodbye."
}
trap cleanup EXIT INT TERM

if [ -t 0 ]; then
    stty -icanon -echo min 1 time 0 2>/dev/null || true
fi

while true; do
    key=""
    char=$(dd bs=1 count=1 2>/dev/null || true)

    if [ "$char" = $'\x1b' ]; then
        # Escape sequence detected (e.g. arrow keys)
        read -r -t 0.05 rest 2>/dev/null || true
        case "$rest" in
            "[A") key="UP" ;;
            "[B") key="DOWN" ;;
            "[C") key="RIGHT" ;;
            "[D") key="LEFT" ;;
            *) key="ESC" ;;
        esac
    else
        case "$char" in
            "") key="ENTER" ;;
            $'\x0a') key="ENTER" ;;
            $'\x0d') key="ENTER" ;;
            " ") key="ENTER" ;;
            $'\x7f') key="BACK" ;;
            $'\x08') key="BACK" ;;
            w|W) key="UP" ;;
            s|S) key="DOWN" ;;
            a|A) key="LEFT" ;;
            d|D) key="RIGHT" ;;
            b|B) key="BACK" ;;
            h|H) key="HOME" ;;
            m|M) key="MENU" ;;
            o|O) key="SETTINGS" ;;
            p|P) key="POWER" ;;
            +|'=') key="VOL_UP" ;;
            -|_) key="VOL_DOWN" ;;
            x|X) key="MUTE" ;;
            y|Y) key="YOUTUBE" ;;
            n|N) key="NETFLIX" ;;
            t|T) key="TEXT" ;;
            q|Q) break ;;
            '?'|'/') key="HELP" ;;
            *) key="UNKNOWN" ;;
        esac
    fi

    case "$key" in
        UP)
            printf "\r[KEY] DPAD_UP        "
            send_key "KEYCODE_DPAD_UP"
            ;;
        DOWN)
            printf "\r[KEY] DPAD_DOWN      "
            send_key "KEYCODE_DPAD_DOWN"
            ;;
        LEFT)
            printf "\r[KEY] DPAD_LEFT      "
            send_key "KEYCODE_DPAD_LEFT"
            ;;
        RIGHT)
            printf "\r[KEY] DPAD_RIGHT     "
            send_key "KEYCODE_DPAD_RIGHT"
            ;;
        ENTER)
            printf "\r[KEY] OK / SELECT    "
            send_key "KEYCODE_ENTER"
            ;;
        BACK|ESC)
            printf "\r[KEY] BACK           "
            send_key "KEYCODE_BACK"
            ;;
        HOME)
            printf "\r[KEY] HOME           "
            send_key "KEYCODE_HOME"
            ;;
        MENU)
            printf "\r[KEY] MENU           "
            send_key "KEYCODE_MENU"
            ;;
        SETTINGS)
            printf "\r[KEY] SETTINGS       "
            send_key "KEYCODE_SETTINGS"
            ;;
        POWER)
            printf "\r[KEY] POWER TOGGLE   "
            send_key "KEYCODE_POWER"
            ;;
        VOL_UP)
            printf "\r[KEY] VOLUME +       "
            send_key "KEYCODE_VOLUME_UP"
            ;;
        VOL_DOWN)
            printf "\r[KEY] VOLUME -       "
            send_key "KEYCODE_VOLUME_DOWN"
            ;;
        MUTE)
            printf "\r[KEY] MUTE           "
            send_key "KEYCODE_MUTE"
            ;;
        YOUTUBE)
            printf "\r[APP] YOUTUBE        "
            launch_app "youtube"
            ;;
        NETFLIX)
            printf "\r[APP] NETFLIX        "
            launch_app "netflix"
            ;;
        TEXT)
            # Restore normal terminal mode temporarily for input
            if [ -n "${old_stty_cfg}" ]; then
                stty "${old_stty_cfg}" 2>/dev/null || true
            fi
            echo ""
            printf " Enter text to send to device: "
            read -r user_text
            if [ -n "${user_text}" ]; then
                echo " Sending: ${user_text}"
                send_text "${user_text}"
            fi
            if [ -t 0 ]; then
                stty -icanon -echo min 1 time 0 2>/dev/null || true
            fi
            ;;
        HELP)
            if [ -n "${old_stty_cfg}" ]; then
                stty "${old_stty_cfg}" 2>/dev/null || true
            fi
            show_help
            if [ -t 0 ]; then
                stty -icanon -echo min 1 time 0 2>/dev/null || true
            fi
            ;;
        *)
            ;;
    esac
done
