#!/bin/bash
# Sourced by codex-session. Hardware is admitted by an actual bounded GLX test,
# not by phone branding or an msm DRM sysfs name (this build uses KGSL).
codex_select_graphics() {
    local requested=${CODEX_GRAPHICS_MODE:-auto}
    local prefix=${CODEX_GPU_PREFIX:-/opt/codex-gpu/mesa-26.2.2-codex5}
    local state="$HOME/.local/state" reason="software requested" selected=software
    mkdir -p "$state"
    : > "$state/codex-gpu-probe.log"
    case "$requested" in auto|software|hardware) ;; *) echo "Unknown graphics mode: $requested" >&2; return 1 ;; esac
    # Keep unrelated loader paths (native execution/keyring), remove only our GPU prefix.
    local library_path="" part
    IFS=: read -ra codex_library_parts <<< "${LD_LIBRARY_PATH:-}"
    for part in "${codex_library_parts[@]}"; do
        [[ -z "$part" || "$part" == "$prefix/lib" ]] && continue
        library_path="${library_path:+$library_path:}$part"
    done
    unset VK_DRIVER_FILES VK_ICD_FILENAMES MESA_LOADER_DRIVER_OVERRIDE GALLIUM_DRIVER LIBGL_ALWAYS_SOFTWARE
    export LD_LIBRARY_PATH="$library_path"
    if [[ "$requested" != software ]]; then
        reason="KGSL device or required acceleration libraries unavailable"
        local device=${CODEX_KGSL_DEVICE:-/dev/kgsl-3d0}
        if [[ -r "$device" && -w "$device" && -x "$prefix/bin/glx-clear-probe" \
                && -r "$prefix/lib/libGL.so.1" && -r "$prefix/lib/libEGL.so.1" \
                && -r "$prefix/lib/libvulkan_freedreno.so" && -r "$prefix/share/vulkan/icd.d/freedreno_icd.aarch64.json" ]]; then
            reason="hardware probe failed or timed out; see codex-gpu-probe.log"
            if timeout --kill-after=2s 8s env \
                    LD_LIBRARY_PATH="$prefix/lib${library_path:+:$library_path}" \
                    VK_DRIVER_FILES="$prefix/share/vulkan/icd.d/freedreno_icd.aarch64.json" \
                    MESA_LOADER_DRIVER_OVERRIDE=zink GALLIUM_DRIVER=zink \
                    "$prefix/bin/glx-clear-probe" > "$state/codex-gpu-probe.log" 2>&1; then
                selected=hardware
                reason="bounded Zink/Adreno GLX clear and shader readback passed"
                export LD_LIBRARY_PATH="$prefix/lib${library_path:+:$library_path}"
                export VK_DRIVER_FILES="$prefix/share/vulkan/icd.d/freedreno_icd.aarch64.json"
                export MESA_LOADER_DRIVER_OVERRIDE=zink GALLIUM_DRIVER=zink
            fi
        else
            printf '%s\n' "$reason" > "$state/codex-gpu-probe.log"
        fi
        if [[ "$selected" != hardware && "$requested" == hardware ]]; then
            printf '{"requested":"hardware","selected":"unavailable","reason":"%s"}\n' "$reason" > "$state/codex-graphics.json"
            echo "Codex acceleration unavailable: $reason. Select compatibility mode in Android tools." >&2
            return 1
        fi
    fi
    if [[ "$selected" == software ]]; then
        export LIBGL_ALWAYS_SOFTWARE=true GALLIUM_DRIVER=llvmpipe
        # Actual rendering is verified on the selected X server before launching
        # the desktop. The path override also permits isolated host policy tests.
        local software_probe=${CODEX_SOFTWARE_PROBE:-/usr/local/lib/codex/codex-software-probe.py}
        if ! timeout --kill-after=2s 12s python3 -B "$software_probe" >> "$state/codex-gpu-probe.log" 2>&1; then
            printf '{"requested":"%s","selected":"unavailable","reason":"Debian llvmpipe GLX probe failed"}\n' "$requested" > "$state/codex-graphics.json"
            echo "Codex software graphics unavailable; see codex-gpu-probe.log. A complete Debian Mesa installation is required." >&2
            return 1
        fi
        # Do not let Electron/ANGLE reselect a proprietary Vulkan path in compatibility mode.
        CODEX_GRAPHICS_CLIENT_ARGS=(--use-gl=angle --use-angle=gl)
        echo "Codex graphics: Debian Mesa llvmpipe ($reason)"
    else
        CODEX_GRAPHICS_CLIENT_ARGS=()
        echo "Codex graphics: Mesa Zink/Turnip ($reason)"
    fi
    printf '{"requested":"%s","selected":"%s","reason":"%s"}\n' "$requested" "$selected" "$reason" > "$state/codex-graphics.json"
}
