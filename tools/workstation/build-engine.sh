#!/usr/bin/env bash
# Build only the GNU ARM64 controller/Code Mode pair. No APK/ADB operation.
set -euo pipefail
repo=$(realpath "${1:?Pass_the_WSL_checkout_path}")
task_root="$HOME/codex-android"
manifest="${CODEX_ENGINE_MANIFEST:-$repo/recovery/engine/manifest.json}"
base=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["base"])' "$manifest")
tag=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tag"])' "$manifest")
patch_name=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["patch"])' "$manifest")
patch="$(dirname "$manifest")/$patch_name"
checkout="$HOME/src/codex-native-${tag#rust-v}"
export PATH="$HOME/.cargo/bin:$PATH"
export RUSTUP_TOOLCHAIN="${CODEX_RUST_TOOLCHAIN:-1.99.1}"
export CARGO_NET_GIT_FETCH_WITH_CLI=true
if [[ -n "${CODEX_BUILD_PROXY:-}" ]]; then
    export CARGO_HTTP_PROXY="$CODEX_BUILD_PROXY"
    export HTTPS_PROXY="$CODEX_BUILD_PROXY" HTTP_PROXY="$CODEX_BUILD_PROXY" ALL_PROXY="$CODEX_BUILD_PROXY"
fi
test -f "$task_root/engine-deps/dependencies.json"
test -d "$task_root/engine-base.git"
mkdir -p "$HOME/src" "$repo/work"
if [[ ! -e "$checkout" ]]; then
    git -C "$task_root/engine-base.git" worktree add --detach "$checkout" "$base"
fi
if ! git -C "$checkout" apply --reverse --check "$patch" 2>/dev/null; then
    git -C "$checkout" apply --index --check "$patch"
    git -C "$checkout" apply --index "$patch"
fi
state=$(python3 "$repo/tools/executor/build-gnu-engine.py" prepare \
    --verified-checkout --engine "$checkout" \
    --recovery-manifest "$manifest" \
    --build-root "$task_root/engine-builds" --target-dir "$task_root/engine-target" \
    --dependencies "$task_root/engine-deps" --dependency-manifest "$task_root/engine-deps/dependencies.json" \
    --cargo-home "$HOME/.cargo" --rustup-home "$HOME/.rustup")
printf '%s\n' "$state" > "$repo/work/engine-build-state.txt"
python3 "$repo/tools/executor/build-gnu-engine.py" build --state "$state" --jobs "${CODEX_ENGINE_JOBS:-2}"
printf 'Completed ARM64 backend build. State: %s\n' "$state"
