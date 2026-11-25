"""Check an explicitly supplied update keystore; never creates or installs an APK."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def fingerprint(value):
    value = value.replace(":", "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected a SHA-256 certificate fingerprint")
    return value


def check(keystore, expected, keytool, alias, env):
    with tempfile.TemporaryDirectory(prefix="codex-signing-") as temporary:
        certificate = Path(temporary) / "certificate.der"
        result = subprocess.run(
            [keytool, "-exportcert", "-keystore", str(keystore), "-alias", alias,
             "-storepass:env", "CODEX_SIGNING_STORE_PASSWORD", "-file", str(certificate)],
            env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30, check=False,
        )
        if result.returncode:
            raise ValueError("Cannot read this keystore; check its alias and store password")
        actual = hashlib.sha256(certificate.read_bytes()).hexdigest()
        if actual != fingerprint(expected):
            raise ValueError("Signing certificate differs from the installed app; an in-place update would be refused")
        return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keystore", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--alias", default=os.environ.get("CODEX_SIGNING_KEY_ALIAS", "androiddebugkey"))
    parser.add_argument("--keytool", default=shutil.which("keytool"))
    args = parser.parse_args()
    if not args.keystore.is_file() or not args.keytool:
        parser.error("Select an existing keystore and an installed JDK keytool")
    env = dict(os.environ)
    env.setdefault("CODEX_SIGNING_STORE_PASSWORD", "android")
    try:
        result = check(args.keystore, args.expected_sha256, args.keytool, args.alias, env)
    except (ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + "\n")
    print("Update certificate matches: " + result)


if __name__ == "__main__":
    main()
