#!/usr/bin/env bash
# Run as WSL root before a large release link. No global WSL/fstab changes.
set -euo pipefail
test "$(id -u)" = 0
root=/home/codex-build/codex-android
test "$(realpath "$root")" = "$root"
swap="$root/build.swap"
if [[ -L "$swap" || ( -e "$swap" && ! -f "$swap" ) ]]; then
    printf 'Refusing a non-regular build swap path\n' >&2
    exit 1
fi
if [[ ! -e "$swap" ]]; then
    install -m 600 /dev/null "$swap"
    fallocate -l 8G "$swap"
    mkswap "$swap"
fi
test "$(stat -c '%U:%a:%s' "$swap")" = 'root:600:8589934592'
if ! swapon --show --noheadings --raw --output NAME | grep -Fxq "$swap"; then
    swapon "$swap"
fi
free -h
