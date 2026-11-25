#!/usr/bin/env bash
set -euo pipefail
repo=$(realpath "${1:?Pass_the_WSL_checkout_path}")
task_root="$HOME/codex-android"
prefix="$task_root/engine-deps/openssl"
archive="$repo/downloads/openssl-3.6.3.tar.gz"
mkdir -p "$repo/downloads" "$task_root/engine-deps" "$task_root/openssl-source"
if [[ ! -f "$archive" ]]; then
    curl --fail --location --connect-timeout 15 --max-time 180 \
        https://github.com/openssl/openssl/releases/download/openssl-3.6.3/openssl-3.6.3.tar.gz \
        --output "$archive.part"
    printf '%s  %s\n' 243a86649cf6f23eeb6a2ff2456e09e5d77dd9018a54d3d96b0c6bdd6ba6c7f1 "$archive.part" | sha256sum -c -
    mv "$archive.part" "$archive"
fi
printf '%s  %s\n' 243a86649cf6f23eeb6a2ff2456e09e5d77dd9018a54d3d96b0c6bdd6ba6c7f1 "$archive" | sha256sum -c -
if [[ ! -f "$prefix/lib/libcrypto.a" || ! -f "$prefix/lib/libssl.a" ]]; then
    if [[ ! -d "$task_root/openssl-source/openssl-3.6.3" ]]; then
        tar -xzf "$archive" -C "$task_root/openssl-source" --no-same-owner
    fi
    cd "$task_root/openssl-source/openssl-3.6.3"
    ./Configure linux-aarch64 no-shared no-tests --cross-compile-prefix=aarch64-linux-gnu- \
        --prefix="$prefix" --libdir=lib > "$task_root/openssl-configure.log" 2>&1
    make -j "${CODEX_ENGINE_JOBS:-8}" > "$task_root/openssl-build.log" 2>&1
    make install_sw > "$task_root/openssl-install.log" 2>&1
fi
python3 - "$archive" "$task_root/engine-deps" <<'PY'
import hashlib,json,sys
from pathlib import Path
archive,prefix=map(Path,sys.argv[1:])
def sha(p):
    with p.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()
record={'schema':'codex.gnu-engine-dependencies.v1','target':'aarch64-unknown-linux-gnu',
 'openssl':{'version':'3.6.3','source':{'url':'https://github.com/openssl/openssl/releases/download/openssl-3.6.3/openssl-3.6.3.tar.gz',
 'sha256':sha(archive),'archive':str(archive)},'configureTarget':'linux-aarch64','compilerTarget':'aarch64-linux-gnu',
 'archives':{name:sha(prefix/'openssl/lib'/name) for name in ('libssl.a','libcrypto.a')}}}
(prefix/'dependencies.json').write_text(json.dumps(record,indent=2)+'\n')
print('ARM64 OpenSSL dependencies ready:',prefix/'dependencies.json')
PY
base="$task_root/engine-base.git"
manifest="${CODEX_ENGINE_MANIFEST:-$repo/recovery/engine/manifest.json}"
selected_base=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["base"])' "$manifest")
selected_tag=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tag"])' "$manifest")
upstream=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["upstream"])' "$manifest")
if [[ ! -d "$base" ]]; then
    git clone --bare --single-branch --branch "$selected_tag" "$upstream" "$base"
fi
if ! git -C "$base" cat-file -e "$selected_base^{commit}" 2>/dev/null \
    || ! git -C "$base" cat-file -e "$selected_tag^{commit}" 2>/dev/null; then
    git -C "$base" fetch "$upstream" "refs/tags/$selected_tag:refs/tags/$selected_tag"
fi
[[ "$(git -C "$base" rev-parse "$selected_tag^{commit}")" == "$selected_base" ]]
git -C "$base" update-ref refs/heads/android-build-base "$selected_base"
git -C "$base" symbolic-ref HEAD refs/heads/android-build-base
git -C "$base" rev-parse HEAD
