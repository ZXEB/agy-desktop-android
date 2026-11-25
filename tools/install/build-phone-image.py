"""Assemble a complete first-install Google Antigravity ARM64 phone image.

Run as Linux build-host root inside GitHub Actions. Combines pristine Debian 13
ARM64 base, Mesa Zink/Turnip, official Google Antigravity Linux ARM64 tarball,
optional agy CLI, and guest integration helpers into agy-phone-rootfs.tar.gz.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

import phone_image as image

ROOT = Path(__file__).resolve().parents[2]


def run(args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def install_guest_sources(root):
    mapping = {
        "runtime/guest/agy-session.sh": ("usr/local/bin/agy-session", 0o700),
        "runtime/guest/codex_keyring.py": ("usr/local/lib/codex/codex_keyring.py", 0o644),
        "runtime/guest/codex_ime.py": ("usr/local/lib/codex/codex_ime.py", 0o644),
        "runtime/guest/keyboard-focus.js": ("usr/local/lib/codex/keyboard-focus.js", 0o644),
        "runtime/guest/codex-graphics.sh": ("usr/local/lib/codex/codex-graphics.sh", 0o644),
        "runtime/guest/codex-software-probe.py": ("usr/local/lib/codex/codex-software-probe.py", 0o644),
        "tools/browser/codex-open.py": ("usr/local/bin/xdg-open", 0o755),
        "tools/install/initialize_keyring.py": ("usr/local/lib/codex/install/initialize_keyring.py", 0o600),
        "tools/install/supervise_keyring.py": ("usr/local/lib/codex/install/supervise_keyring.py", 0o600),
        "tools/runtime/install_phone_mcp.py": ("usr/local/lib/codex/install_phone_mcp.py", 0o644),
        "tools/runtime/codex_native_dialogs.py": ("usr/local/lib/codex/codex_native_dialogs.py", 0o644),
        "tools/runtime/codex-phone-dialogs.css": ("usr/local/lib/codex/codex-phone-dialogs.css", 0o644),
        "config/pulseaudio/codex-pulse.pa": ("usr/local/share/codex/pulseaudio.pa", 0o644),
        "config/agent-context/agy.v1.json": ("usr/local/share/codex/agent-environment.v1.json", 0o644),
    }
    for source, (destination, mode) in mapping.items():
        target = root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / source).read_bytes().replace(b"\r\n", b"\n"))
        target.chmod(mode)

    # Copy Phone & Android MCP plugin assets
    plugin_src = ROOT / "plugins/codex-android"
    plugin_dst = root / "usr/local/share/codex/plugins/agy-android"
    if plugin_dst.exists():
        shutil.rmtree(plugin_dst)
    shutil.copytree(plugin_src, plugin_dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for path in plugin_dst.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            if b"\0" not in data:
                path.write_bytes(data.replace(b"\r\n", b"\n"))
            path.chmod(0o755 if path.suffix == ".py" else 0o644)


def install_antigravity_client(root, client_dir):
    meta = json.loads((client_dir / "client-meta.json").read_text(encoding="utf-8"))
    tarball = client_dir / meta["filename"]
    if image.digest(tarball) != meta["sha256"]:
        raise ValueError("Official Antigravity tarball SHA-256 differs from client metadata")

    opt_dir = root / "opt/antigravity"
    opt_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as archive:
        for member in archive.getmembers():
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                raise ValueError("Unsafe path in Antigravity tarball: " + member.name)
        archive.extractall(opt_dir, filter="data")

    app_dir = opt_dir / "Antigravity-arm64"
    binary = app_dir / "antigravity"
    if not binary.is_file():
        # Handle any alternative top-level folder name inside tarball cleanly
        candidates = list(opt_dir.glob("*/antigravity")) + list(opt_dir.glob("*/Antigravity"))
        if not candidates:
            raise ValueError("Antigravity executable not found after tarball extraction")
        found_dir = candidates[0].parent
        if found_dir != app_dir:
            found_dir.rename(app_dir)
        if not binary.is_file() and (app_dir / "Antigravity").is_file():
            (app_dir / "Antigravity").rename(binary)
    binary.chmod(0o755)
    (opt_dir / ".antigravity-linux-version").write_text(meta["version"] + "\n", encoding="utf-8")
    (opt_dir / ".antigravity-linux-source-url").write_text(meta["url"] + "\n", encoding="utf-8")

    # Symlink /usr/local/bin/antigravity -> /opt/antigravity/Antigravity-arm64/antigravity
    usr_local_bin = root / "usr/local/bin"
    usr_local_bin.mkdir(parents=True, exist_ok=True)
    link = usr_local_bin / "antigravity"
    if link.exists() or link.is_symlink():
        link.unlink()
    os.symlink("/opt/antigravity/Antigravity-arm64/antigravity", link)

    # Also install optional agy CLI if staged in client_dir
    cli_bin = client_dir / "agy"
    if cli_bin.is_file():
        target_cli = usr_local_bin / "agy"
        shutil.copy2(cli_bin, target_cli)
        target_cli.chmod(0o755)

    return meta


def assemble(args):
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("Use build-host Linux root; no Android root is needed")
    if args.output.exists():
        raise FileExistsError("Output must be a new release directory")
    args.output.mkdir(mode=0o755)
    evidence = args.output / "evidence"
    evidence.mkdir()
    if image.digest(args.base) != args.base_sha256 or image.digest(args.gpu) != args.gpu_sha256:
        raise ValueError("Explicit base/GPU release input digest differs")

    work = Path(tempfile.mkdtemp(prefix="agy-phone-image-", dir="/var/tmp"))
    root = work / "rootfs"
    root.mkdir()
    (evidence / "build-directory.txt").write_text(str(work) + "\n")

    run(["tar", "--extract", "--gzip", "--file", args.base, "--directory", root, "--numeric-owner"])
    run([sys.executable, "-B", ROOT / "tools/install/verify_rootfs.py", root],
        stdout=(evidence / "pristine-base-verification.json").open("w"))

    client_meta = install_antigravity_client(root, args.official_input)
    install_guest_sources(root)

    with tarfile.open(args.gpu, "r:gz") as archive:
        if any(not x.name.startswith("opt/codex-gpu/mesa-26.2.2-codex5") for x in archive.getmembers()):
            raise ValueError("GPU payload has an unexpected prefix")
        archive.extractall(root, filter="data")

    image.require_pristine_profile(root)
    immutable = image.inventory(root)
    assets = args.output / "assets/phone-runtime"
    assets.mkdir(parents=True)
    inventory_bytes = image.canonical(immutable)
    (assets / "inventory.json").write_bytes(inventory_bytes)

    archive = args.output / "agy-phone-rootfs.tar.gz"
    with archive.open("xb") as output:
        tar = subprocess.Popen(
            ["tar", "--sort=name", "--hard-dereference", "--numeric-owner",
             "--format=posix", "--pax-option=delete=atime,delete=ctime", "-C", root, "-cf", "-", "."],
            stdout=subprocess.PIPE)
        run(["gzip", "-n", "-6"], stdin=tar.stdout, stdout=output)
        tar.stdout.close()
        if tar.wait() != 0:
            raise RuntimeError("Phone image tar failed")

    spec = image.inspect_archive(archive, image.digest(archive))
    release = {
        "format": image.FORMAT,
        "archive": archive.name,
        "spec": spec,
        "inventorySha256": hashlib.sha256(inventory_bytes).hexdigest(),
        "inventoryBytes": len(inventory_bytes),
        "initializerSha256": image.digest(root / "usr/local/lib/codex/install/initialize_keyring.py"),
        "supervisorSha256": image.digest(root / "usr/local/lib/codex/install/supervise_keyring.py"),
        "baseSha256": args.base_sha256,
        "gpuSha256": args.gpu_sha256,
        "client": client_meta,
        "accountIncluded": False,
        "keyringIncluded": False,
        "androidExecuted": False,
    }
    (assets / "release.json").write_bytes(image.canonical(release))
    if getattr(args, "embed_archive", False):
        os.link(archive, assets / archive.name)

    print(json.dumps({"output": str(args.output), "image": spec, "clientVersion": client_meta["version"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "gpu", "official-input", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("base-sha256", "gpu-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--embed-archive", action="store_true", help="Include the archive in assets/ for a self-contained APK")
    assemble(parser.parse_args())
