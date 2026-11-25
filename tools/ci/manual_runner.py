"""Tooling and disk housekeeping restricted to disposable GitHub-hosted VMs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

from manual_release import ROOT, WORK, command, fetch, state


def hosted():
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
            or sys.platform != "linux" or not str(ROOT).startswith("/home/runner/work/")):
        raise RuntimeError("Runner setup/cleanup requires a disposable GitHub-hosted Linux VM")


def remove(path, *, private_build=False):
    path = Path(path)
    if not path.exists():
        return
    resolved = path.resolve(strict=True)
    if path.is_symlink() or resolved != path or not path.is_dir():
        raise ValueError("Refuse unexpected cleanup directory")
    if private_build:
        valid = resolved.is_relative_to(WORK) and resolved != WORK
        valid |= resolved.parent == Path("/var/tmp") and resolved.name.startswith(("codex-rootfs-", "codex-phone-image-", "agy-phone-image-"))
        if not valid:
            raise ValueError("Cleanup path is outside this disposable build")
    # No recursive deletion may traverse a surviving chroot/bind mount.
    for row in Path("/proc/self/mountinfo").read_text().splitlines():
        target = row.split()[4].replace("\\040", " ")
        if target == str(path) or target.startswith(str(path) + "/"):
            raise ValueError("Refuse cleanup of a mounted tree")
    subprocess.run(["sudo", "rm", "-rf", "--", str(path)], check=True)


def prepare():
    hosted()
    # This existing helper validates all fixed preinstalled SDK paths and the
    # project-local Rustup selection. Android tools are reinstalled after Rust.
    command("runner-space", [sys.executable, "-B", ROOT / "tools/ci/prepare-runner-storage.py"])
    command("host-tools", ["sudo", "apt-get", "update"])
    command("host-dependencies", ["sudo", "apt-get", "install", "--no-install-recommends", "-y",
        "build-essential", "gcc-aarch64-linux-gnu", "g++-aarch64-linux-gnu", "binutils-aarch64-linux-gnu",
        "qemu-user", "qemu-user-static", "binfmt-support", "mmdebstrap", "debootstrap", "arch-test",
        "debian-archive-keyring", "python3-venv", "python3-yaml", "gpg", "gpgv", "curl", "unzip",
        "pkg-config", "libssl-dev", "clang", "cmake", "ninja-build", "perl", "file"])
    command("arm-binfmt", ["sudo", "update-binfmts", "--enable", "qemu-aarch64"])


def compact():
    hosted()
    value = state()
    # Retain frozen sources, archives, manifests and evidence. Cargo outputs and
    # inactive rootfs trees are rebuildable and are never public release inputs.
    remove(WORK / "engine-target", private_build=True)
    remove(WORK / "client-check", private_build=True)
    if value.get("baseBuildDirectory"):
        remove(Path(value["baseBuildDirectory"]), private_build=True)
    evidence = WORK / "phone-image/evidence/build-directory.txt"
    remove(Path(evidence.read_text().strip()), private_build=True)
    print(json.dumps({"freeBytesBeforeAndroid": shutil.disk_usage(ROOT).free}))


def android():
    hosted()
    sdk = WORK / "android-sdk"
    # Resolve Google's command-line tools from its own repository manifest,
    # retaining and verifying its published archive checksum before extraction.
    metadata = WORK / "android-repository.xml"
    fetch("https://dl.google.com/android/repository/repository2-1.xml", metadata, limit=16 * 1024**2)
    tree = ET.fromstring(metadata.read_bytes())
    package = next(p for p in tree.findall("remotePackage") if p.attrib["path"] == "cmdline-tools;latest")
    selected = next(a.find("complete") for a in package.findall("archives/archive") if a.findtext("host-os") == "linux")
    archive = WORK / "command-line-tools.zip"
    fetch("https://dl.google.com/android/repository/" + selected.findtext("url"), archive)
    checksum = selected.find("checksum")
    algorithm = checksum.attrib.get("type", "sha1").replace("-", "").lower()
    with archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, algorithm).hexdigest()
    if actual != checksum.text.strip() or archive.stat().st_size != int(selected.findtext("size")):
        raise ValueError("Android tools differ from Google's repository metadata")
    with zipfile.ZipFile(archive) as zipped:
        for name in zipped.namelist():
            path = Path(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("Unexpected Android tools ZIP path")
        zipped.extractall(sdk)
    tools = sdk / "cmdline-tools"
    staged = sdk / "latest"
    tools.rename(staged)
    tools.mkdir()
    staged.rename(tools / "latest")
    for executable in (tools / "latest/bin").iterdir():
        executable.chmod(0o755)
    manager = tools / "latest/bin/sdkmanager"
    command("android-licenses", [manager, f"--sdk_root={sdk}", "--licenses"], input="y\n" * 200)
    command("android-sdk", [manager, f"--sdk_root={sdk}", "platforms;android-37.0", "build-tools;36.0.0",
        "ndk;29.0.14206865", "cmake;3.22.1"], input="y\n" * 200)
    # Android/Gradle versions follow the project's build configuration. Codex
    # backend and desktop versions are separately selected at dispatch time.
    gradle = WORK / "gradle.zip"
    checksum_file = WORK / "gradle.sha256"
    base = "https://services.gradle.org/distributions/gradle-9.7.1-bin.zip"
    fetch(base + ".sha256", checksum_file, limit=1024)
    fetch(base, gradle, expected=checksum_file.read_text().strip())
    with zipfile.ZipFile(gradle) as zipped:
        zipped.extractall(WORK / "gradle")
    executable = WORK / "gradle/gradle-9.7.1/bin/gradle"
    executable.chmod(0o755)
    with Path(os.environ["GITHUB_PATH"]).open("a") as stream:
        stream.write(str(executable.parent) + "\n")
    with Path(os.environ["GITHUB_ENV"]).open("a") as stream:
        stream.write(f"ANDROID_HOME={sdk}\nANDROID_SDK_ROOT={sdk}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "compact", "android"))
    globals()[parser.parse_args().stage]()
