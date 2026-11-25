#!/usr/bin/env bash
# Package the completed backend against authenticated Debian library fixtures.
set -euo pipefail
repo=$(realpath "${1:?Pass_the_WSL_checkout_path}")
task_root="$HOME/codex-android"
state=$(cat "$repo/work/engine-build-state.txt")
build=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["build"])' "$state")
evidence=$(dirname "$state")
fixture="$task_root/debian-compat"
archive="$fixture/library-rootfs.tar.gz"
(cd "$fixture" && sha256sum -c library-rootfs.sha256)
digest=$(sha256sum "$archive" | cut -d ' ' -f 1)
libraries="$task_root/engine-libraries-$(basename "$evidence")"
python3 "$repo/tools/executor/collect-gnu-rootfs-libraries.py" \
    --rootfs-archive "$archive" --rootfs-sha256 "$digest" \
    --binaries "$build/unstripped" --output "$libraries"
python3 - "$libraries/collection.json" "$fixture/provenance.json" <<'PY'
from pathlib import Path
import hashlib,json,sys
path,provenance=map(Path,sys.argv[1:])
record=json.loads(path.read_text())
record['fixtureScope']='Minimal authenticated Debian 13 library fixture; not collected from the phone'
record['aptProvenanceSha256']=hashlib.sha256(provenance.read_bytes()).hexdigest()
path.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
PY
cp "$fixture/provenance.json" "$evidence/debian-library-provenance.json"
cp "$fixture/library-rootfs.sha256" "$evidence/debian-library-rootfs.sha256"
python3 "$repo/tools/executor/build-gnu-engine.py" package --state "$state" --libraries "$libraries"
version=$(python3 -c 'import json,sys,tomllib; from pathlib import Path; source=Path(json.load(open(sys.argv[1]))["source"]); print(tomllib.loads((source/"codex-rs/Cargo.toml").read_text())["workspace"]["package"]["version"])' "$state")
assets="$task_root/engine-apk-assets-$version"
python3 "$repo/tools/executor/stage-gnu-engine-assets.py" --state "$state" --output "$assets"
printf '%s\n' "$assets" > "$repo/work/engine-assets-path.txt"
timeout -k 2s 20s qemu-aarch64 -L "$fixture/rootfs" "$build/unstripped/codex" --version \
    > "$evidence/qemu-codex-version.txt" 2>&1
timeout -k 2s 20s qemu-aarch64 -L "$fixture/rootfs" "$build/unstripped/codex-code-mode-host" --help \
    > "$evidence/qemu-code-mode-help.txt" 2>&1
printf 'Backend package and PC startup checks completed: %s\n' "$evidence"
