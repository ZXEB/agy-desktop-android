#!/usr/bin/env bash
# Syntax and source checks only; no Cargo/Gradle compilation or APK packaging.
set -euo pipefail
repo=$(realpath "${1:?Pass_the_WSL_checkout_path}")
export RUSTUP_TOOLCHAIN=1.99.1
python3 "$repo/tools/ci/check-source-integrity.py"
python3 -m compileall -q "$repo/runtime" "$repo/tools" "$repo/config" "$repo/tests"
bash -n "$repo/runtime/guest/codex-session.sh" "$repo/tools/workstation/prepare-linux.sh"
if [[ -f "$repo/.tooling/ktfmt-0.64.jar" ]]; then
    mapfile -d '' kotlin_files < <(find "$repo/android/app/src/main/java/com/ai/codex" \
        "$repo/android/app/src/test/java/com/ai/codex" -name '*.kt' -print0)
    /usr/lib/jvm/java-21-openjdk-amd64/bin/java -jar "$repo/.tooling/ktfmt-0.64.jar" \
        --dry-run --quiet --do-not-remove-unused-imports "${kotlin_files[@]}" > "$repo/work/kotlin-syntax.log"
    printf 'Kotlin syntax parsed: %s files\n' "${#kotlin_files[@]}"
fi
if [[ -f "$repo/work/engine-rust-files.txt" ]]; then
    count=0
    while IFS= read -r path; do
        path=${path%$'\r'}
        "$HOME/.cargo/bin/rustfmt" --edition 2024 --config skip_children=true --emit stdout \
            "$repo/work/upstream/codex-engine-0169/$path" >/dev/null
        count=$((count+1))
    done < "$repo/work/engine-rust-files.txt"
    printf 'Rust syntax parsed: %s files\n' "$count"
fi
