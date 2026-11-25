#!/usr/bin/env bash
# Authenticated Debian 13 libraries for PC static/QEMU checks, not a phone image.
set -euo pipefail
work="$HOME/codex-android/debian-compat"
keyring=/usr/share/keyrings/debian-archive-keyring.gpg
test -f "$keyring"
mkdir -p "$work/lists/partial" "$work/archives/partial"
test "$(realpath "$work")" = "$HOME/codex-android/debian-compat"
if [[ -f "$work/library-rootfs.tar.gz" ]]; then
    (cd "$work" && sha256sum -c library-rootfs.sha256)
    exit 0
fi
touch "$work/status"
printf '%s\n' \
    "deb [arch=arm64 signed-by=$keyring] http://deb.debian.org/debian trixie main" \
    "deb [arch=arm64 signed-by=$keyring] http://security.debian.org/debian-security trixie-security main" \
    > "$work/sources.list"
options=(
    -o "Dir::Etc::sourcelist=$work/sources.list" -o Dir::Etc::sourceparts=-
    -o "Dir::State::status=$work/status" -o "Dir::State::lists=$work/lists"
    -o "Dir::Cache::archives=$work/archives" -o "Dir::Cache::pkgcache=$work/pkgcache.bin"
    -o "Dir::Cache::srcpkgcache=$work/srcpkgcache.bin" -o APT::Architecture=arm64
    -o Acquire::AllowInsecureRepositories=false -o APT::Get::AllowUnauthenticated=false
    -o Acquire::ForceIPv4=true
)
apt-get "${options[@]}" update > "$work/apt-update.log" 2>&1
apt-get "${options[@]}" --download-only --no-install-recommends -y \
    install libc6:arm64 libgcc-s1:arm64 libstdc++6:arm64 > "$work/apt-download.log" 2>&1
mkdir -p "$work/rootfs"
for package in "$work/archives/"*.deb; do
    # apt has authenticated these packages against the signed indexes above.
    dpkg-deb --extract "$package" "$work/rootfs"
done
test -e "$work/rootfs/lib" || ln -s usr/lib "$work/rootfs/lib"
python3 - "$work" "$keyring" <<'PY'
from pathlib import Path
import hashlib, json, subprocess, sys
work, keyring = map(Path, sys.argv[1:])
def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
packages = []
for path in sorted((work / 'archives').glob('*.deb')):
    fields = subprocess.check_output(['dpkg-deb', '--field', str(path), 'Package', 'Version', 'Architecture'], text=True)
    packages.append({'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path), 'metadata': fields})
record = {'scope': 'Minimal authenticated Debian 13 library fixture; not an installable phone image',
          'androidCollected': False, 'keyringSha256': sha(keyring), 'packages': packages,
          'signedRepositoryMetadata': {p.name: sha(p) for p in sorted((work / 'lists').iterdir()) if p.is_file()}}
(work / 'provenance.json').write_text(json.dumps(record, indent=2) + '\n')
PY
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
    -C "$work/rootfs" -czf "$work/library-rootfs.tar.gz" .
(cd "$work" && sha256sum library-rootfs.tar.gz > library-rootfs.sha256)
printf 'Debian 13 library fixture: %s\n' "$work/library-rootfs.tar.gz"
