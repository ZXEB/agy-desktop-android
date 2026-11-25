"""Recover unchanged native inputs from an explicitly pinned, signed installed APK.

This records a reused binary baseline, not a native rebuild or new device qualification.
It never copies credentials, app data or a signing private key.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import zipfile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def recover(args):
    apk = args.apk.resolve(strict=True)
    if sha(apk) != args.apk_sha256:
        raise ValueError('Pinned installed APK digest differs')
    signature = subprocess.check_output([str(args.java), '-jar', str(args.apksigner_jar),
        'verify', '--verbose', '--print-certs', str(apk)], text=True)
    actual = re.findall(r'Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]+)', signature)
    if [x.lower() for x in actual] != [args.cert_sha256.lower()]:
        raise ValueError('Installed APK signer differs from the explicitly selected original identity')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'baseline-signature.txt').write_text(signature)
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate APK entries')
        deployment = json.loads(archive.read('assets/codex-executor-deployment.json'))
        native = deployment['nativeLibraries']
        transport = {'libcodex_shizuku_transport.so', 'libcodex_bionic_cwd.so'}
        runtime = {'libproot.so', 'libproot-loader.so', 'libproot-loader32.so', 'libtalloc.so', 'libandroid-shmem.so'}
        records = {}

        def copy(member, relative, expected=None):
            parts = PurePosixPath(relative)
            if parts.is_absolute() or '..' in parts.parts or '\\' in relative:
                raise ValueError('Noncanonical recovered path')
            destination = args.output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open('xb') as output:
                shutil.copyfileobj(source, output)
            digest = sha(destination)
            if expected is not None and digest != expected:
                raise ValueError('Installed native input differs from its deployment: ' + member)
            records[relative] = {'apkEntry': member, 'bytes': destination.stat().st_size, 'sha256': digest}

        for name, digest in native.items():
            if Path(name).name != name:
                raise ValueError('Invalid native inventory name')
            category = 'transport' if name in transport else 'executor/jniLibs'
            copy('lib/arm64-v8a/' + name, category + '/arm64-v8a/' + name, digest)
            if name.startswith(('libcodex_py_', 'libpython')) or name in {
                    'libcodex_python_cli.so', 'libcrypto_python.so', 'libssl_python.so', 'libsqlite3_python.so'}:
                copy('lib/arm64-v8a/' + name, 'debug-jni/arm64-v8a/' + name, digest)
        for name in runtime:
            copy('lib/arm64-v8a/' + name, 'runtime/arm64-v8a/' + name)
        copy('lib/arm64-v8a/libXlorie.so', 'x11/arm64-v8a/libXlorie.so')
        metadata = {'codex-executor-deployment.json', 'codex-executor-evidence.json',
                    'codex-executor-manifest.json', 'codex-executor-qualification.json', 'codex-app-launch-build.json'}
        for name in names:
            if not name.startswith('assets/') or name.endswith('/'):
                continue
            relative = name.removeprefix('assets/')
            if relative in metadata or relative.startswith('codex-executor/'):
                copy(name, 'executor/assets/' + relative)
            elif relative == 'codex-python-runtime.json' or relative.startswith(('bionic-python/', 'phone-runtime/')):
                copy(name, 'debug-assets/' + relative)
    (args.output / 'recovered-inputs.json').write_text(json.dumps({
        'schema': 'codex.installed-apk-inputs.v1', 'apkSha256': args.apk_sha256,
        'certificateSha256': args.cert_sha256, 'nativeRebuilt': False, 'newDeviceQualification': False,
        'scope': 'Unchanged native and Python inputs from the pinned installed APK', 'files': records}, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'files': len(records), 'nativeRebuilt': False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('apk', 'java', 'apksigner-jar', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('apk-sha256', 'cert-sha256'):
        parser.add_argument('--' + name, required=True)
    recover(parser.parse_args())


if __name__ == '__main__':
    main()
