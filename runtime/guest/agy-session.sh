#!/bin/bash
set -euo pipefail

desktop_bin="/opt/antigravity/Antigravity-arm64/antigravity"
if [[ ! -x "$desktop_bin" ]]; then
    echo "Google Antigravity binary not found at $desktop_bin" >&2
    exit 1
fi

if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    exec dbus-run-session -- "$0"
fi

# UTF-8 is available in the pristine Debian base; Electron selects Simplified Chinese.
export LANG="${LANG:-C.UTF-8}"
export LANGUAGE="${LANGUAGE:-zh_CN:zh:en}"
export CODEX_CDP_PORT="${CODEX_CDP_PORT:-9223}"
export XDG_RUNTIME_DIR="/tmp/runtime-$(id -u)"
mkdir -p "$XDG_RUNTIME_DIR" "$HOME/.local/state" "$HOME/.gemini/config" "$HOME/.gemini/antigravity/brain"
chmod 700 "$XDG_RUNTIME_DIR"

# Unlock GNOME keyring backed by Android Keystore vault
timeout 20s python3 /usr/local/lib/codex/codex_keyring.py || true

# Register Phone MCP & Android Device MCP into ~/.gemini/config/mcp_config.json and skills
python3 -B /usr/local/lib/codex/install_phone_mcp.py || true

# GTK native file pickers scale independently of Chromium content zoom
export GDK_SCALE=2 GDK_DPI_SCALE=1
python3 -B /usr/local/lib/codex/codex_native_dialogs.py prepare || true

# Select Mesa Zink/Turnip hardware acceleration or llvmpipe compatibility mode
source /usr/local/lib/codex/codex-graphics.sh
codex_select_graphics

if [[ -f /usr/local/lib/codex/libquiet_xext.so ]]; then
    export LD_PRELOAD="/usr/local/lib/codex/libquiet_xext.so${LD_PRELOAD:+:$LD_PRELOAD}"
fi

# Start Chinese IME focus bridge (watches Electron CDP port 9223)
python3 -u /usr/local/lib/codex/codex_ime.py > "$HOME/.local/state/codex-ime.log" 2>&1 &
ime_pid=$!

# Lightweight window manager without duplicate compositor under PRoot
xfwm4 --compositor=off > "$HOME/.local/state/codex-wm.log" 2>&1 &
wm_pid=$!

# Start user-space PulseAudio server for microphone/speaker bridging
export PULSE_SERVER=127.0.0.1:4713
if [[ -f /usr/local/share/codex/pulseaudio.pa ]]; then
    pulseaudio -k 2>/dev/null || true
    pulseaudio -n -F /usr/local/share/codex/pulseaudio.pa --daemonize=true || true
fi

dialogs_pid=""
trap 'kill "$ime_pid" "$wm_pid" ${dialogs_pid:+"$dialogs_pid"} 2>/dev/null || true; pulseaudio -k 2>/dev/null || true' EXIT

# Chromium / Electron compatibility flags for PRoot on Android
client_compat_args=(
    --no-sandbox
    --no-zygote
    --disable-gpu-sandbox
    --disable-dev-shm-usage
    --enable-logging=stderr
)

"$desktop_bin" \
    "${client_compat_args[@]}" \
    "${CODEX_GRAPHICS_CLIENT_ARGS[@]}" \
    --lang="${CODEX_LANGUAGE:-zh-CN}" \
    --ozone-platform=x11 \
    --force-device-scale-factor="${CODEX_SCALE:-1.5}" \
    --start-maximized \
    --remote-debugging-address=127.0.0.1 \
    --remote-debugging-port="$CODEX_CDP_PORT" &
client_pid=$!

python3 -B /usr/local/lib/codex/codex_native_dialogs.py watch --pid "$client_pid" \
    > "$HOME/.local/state/codex-dialogs.log" 2>&1 &
dialogs_pid=$!

# Wait for the Antigravity X11 window to map, maximize/fullscreen it, and signal readiness to Android
while kill -0 "$client_pid" 2>/dev/null; do
    if clients=$(wmctrl -lpx 2>/dev/null); then
        window=$(awk -v pid="$client_pid" '$3 == pid || tolower($4) ~ /antigravity/ { print $1; exit }' <<< "$clients")
    else
        window=""
    fi
    if [[ -n "$window" ]]; then
        wmctrl -i -r "$window" -b add,fullscreen || wmctrl -i -r "$window" -b add,maximized_vert,maximized_horz || true
        if [[ -n "${CODEX_SESSION_TOKEN:-}" ]]; then
            printf '%s\n' "$CODEX_SESSION_TOKEN" > /tmp/codex-client-ready
        fi
        break
    fi
    sleep 0.2
done

client_exit=0
wait "$client_pid" || client_exit=$?
if [[ "$client_exit" == 0 && -n "${CODEX_SESSION_TOKEN:-}" ]]; then
    printf '%s\n' "$CODEX_SESSION_TOKEN" > /tmp/codex-client-stopped
fi
exit "$client_exit"
