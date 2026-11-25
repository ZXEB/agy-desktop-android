"""GitHub Actions cloud release orchestrator for Google Antigravity Desktop Android.

Freezes the official Google Antigravity Linux ARM64 desktop URL, builds/reuses
Debian 13 ARM64 and Mesa Zink/Turnip, extracts verified PRoot/Termux:X11 native
libraries, assembles agy-phone-rootfs.tar.gz, builds & signs the full APK, and
publishes a GitHub Release.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work/manual-release"
GETTING_STARTED_MD = "https://antigravity.google/docs/getting-started.md"
FALLBACK_DESKTOP_URL = (
    "https://storage.googleapis.com/antigravity-public/antigravity-hub/"
    "2.35.1-4615540875067392/linux-arm/Antigravity.tar.gz"
)
DESKTOP_URL_RE = re.compile(
    r"https://storage\.googleapis\.com/antigravity-public/antigravity-hub/"
    r"([A-Za-z0-9._\-]+)/linux-arm/Antigravity\.tar\.gz"
)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def state():
    return json.loads((WORK / "plan.json").read_text(encoding="utf-8"))


def run(argv, *, cwd=ROOT, env=None, input=None):
    return subprocess.check_output(list(map(str, argv)), cwd=cwd, env=env,
                                   input=input, text=True).strip()


def command(label, argv, *, cwd=ROOT, env=None, input=None):
    logs = WORK / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    print(f"::group::{label}", flush=True)
    with (logs / (label + ".log")).open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            list(map(str, argv)), cwd=cwd, env=env, text=True,
            stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, errors="replace")
        if input is not None:
            process.stdin.write(input)
            process.stdin.close()
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
        process.stdout.close()
        code = process.wait()
    print("::endgroup::", flush=True)
    if code:
        raise RuntimeError(f"{label} failed ({code}); see work/manual-release/logs/{label}.log")
    return (logs / (label + ".log")).read_text(encoding="utf-8")


def fetch(url, destination, *, expected=None, limit=2 * 1024**3):
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("Only HTTPS build inputs are allowed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    if temporary.exists():
        temporary.unlink()
    request = urllib.request.Request(url, headers={"User-Agent": "agy-android-cloud-build"})
    count, sha = 0, hashlib.sha256()
    with urllib.request.urlopen(request, timeout=180) as response, temporary.open("xb") as output:
        if urllib.parse.urlsplit(response.url).scheme != "https":
            raise ValueError("Build input redirected away from HTTPS")
        while block := response.read(1024 * 1024):
            count += len(block)
            if count > limit:
                raise ValueError("Build input exceeds its size bound")
            sha.update(block)
            output.write(block)
    if expected is not None and sha.hexdigest() != expected:
        raise ValueError("Build input SHA-256 differs: " + destination.name)
    temporary.rename(destination)
    return {"sha256": sha.hexdigest(), "bytes": count}


def resolve_antigravity_desktop(selector: str, explicit_url: str):
    if explicit_url:
        if urllib.parse.urlsplit(explicit_url).scheme != "https":
            raise ValueError("desktop_url must be HTTPS")
        m = DESKTOP_URL_RE.search(explicit_url)
        version = m.group(1).split("-", 1)[0] if m else (selector if selector and selector != "latest" else "custom")
        return version, explicit_url

    if selector and selector != "latest" and "-" in selector:
        url = f"https://storage.googleapis.com/antigravity-public/antigravity-hub/{selector}/linux-arm/Antigravity.tar.gz"
        return selector.split("-", 1)[0], url

    # Discover latest official ARM64 desktop URL from https://antigravity.google/docs/getting-started.md
    try:
        req = urllib.request.Request(GETTING_STARTED_MD, headers={"User-Agent": "agy-android-cloud-build"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            doc = resp.read().decode("utf-8", errors="replace")
        matches = list(DESKTOP_URL_RE.finditer(doc))
        if matches:
            match = matches[-1]
            return match.group(1).split("-", 1)[0], match.group(0)
    except Exception as exc:
        print(f"Warning: live docs lookup failed ({exc}); using pinned fallback URL", flush=True)

    match = DESKTOP_URL_RE.search(FALLBACK_DESKTOP_URL)
    return match.group(1).split("-", 1)[0], FALLBACK_DESKTOP_URL


def prepare_workspace():
    for path in (WORK, ROOT / "downloads"):
        path.mkdir(parents=True, exist_ok=True)
        if not os.access(path, os.W_OK | os.X_OK):
            raise RuntimeError("Build output is not writable by the runner: " + str(path))


def plan():
    if (WORK / "plan.json").exists():
        raise FileExistsError("Retain previous attempts; use a fresh checkout for another build")
    prepare_workspace()
    selector = os.environ.get("INPUT_DESKTOP_VERSION", "latest").strip() or "latest"
    explicit_url = os.environ.get("INPUT_DESKTOP_URL", "").strip()
    desktop_version, desktop_url = resolve_antigravity_desktop(selector, explicit_url)

    app = (ROOT / "android/app/build.gradle").read_text(encoding="utf-8")
    source_code = int(re.search(r"agyVersionCode.*getOrElse\((\d+)\)", app)[1])
    supplied_code = os.environ.get("INPUT_VERSION_CODE", "").strip()
    code = int(supplied_code or source_code + int(os.environ.get("GITHUB_RUN_NUMBER", "1")))
    if not source_code < code <= 2100000000:
        raise ValueError("Use a versionCode larger than the current source version")
    tag = os.environ.get("INPUT_RELEASE_TAG", "").strip() or f"v{code}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,99}", tag):
        raise ValueError("Invalid release tag")

    baseline = json.loads((ROOT / "config/android/native-baseline.json").read_text(encoding="utf-8"))
    if (baseline.get("schema") != "codex.ci-native-baseline.v1"
            or not re.fullmatch(r"[0-9a-f]{64}", baseline.get("sha256", ""))
            or not re.fullmatch(r"[0-9a-f]{64}", baseline.get("certificateSha256", ""))):
        raise ValueError("Invalid native baseline descriptor")

    save(WORK / "plan.json", {
        "desktopSelector": selector,
        "desktopVersion": desktop_version,
        "desktopUrl": desktop_url,
        "versionCode": code,
        "versionName": f"0.1.0-agy.{code}",
        "releaseTag": tag,
        "nativeBaseline": baseline,
        "sourceCommit": os.environ.get("GITHUB_SHA") or run(["git", "rev-parse", "HEAD"]),
    })
    outputs = os.environ.get("GITHUB_OUTPUT")
    if outputs:
        with Path(outputs).open("a") as stream:
            stream.write(f"release_tag={tag}\nversion_code={code}\ndesktop_version={desktop_version}\n")
    print(json.dumps(state(), indent=2))


def acquire_client():
    value = state()
    upstream = WORK / "official-client"
    upstream.mkdir(parents=True, exist_ok=True)
    tarball = upstream / "Antigravity.tar.gz"
    info = fetch(value["desktopUrl"], tarball, limit=1536 * 1024 * 1024)

    # Verify the tarball contains an ARM64 Antigravity Electron desktop layout
    has_binary = False
    has_asar = False
    with tarfile.open(tarball, "r:gz") as archive:
        for member in archive:
            name = member.name.lstrip("./")
            if name.endswith("/antigravity") or name.endswith("/Antigravity"):
                has_binary = True
            if name.endswith("/resources/app.asar"):
                has_asar = True
    if not has_binary or not has_asar:
        raise ValueError("Downloaded Antigravity.tar.gz does not contain the expected Electron layout")

    meta = {
        "schema": "agy.official-desktop.v1",
        "product": "Google Antigravity",
        "architecture": "arm64",
        "version": value["desktopVersion"],
        "url": value["desktopUrl"],
        "filename": tarball.name,
        "sha256": info["sha256"],
        "bytes": info["bytes"],
    }
    save(upstream / "client-meta.json", meta)
    print("Verified official Google Antigravity ARM64 tarball: " + json.dumps(meta))


def base():
    output = command("debian-base", ["sudo", "env", "CODEX_APT_FORCE_IPV4=1", sys.executable, "-B",
                                     ROOT / "tools/install/build_rootfs.py", "build"])
    result = json.loads(output.splitlines()[-1])
    value = state()
    value["baseArchive"] = str(Path(result["output"]) / "debian-13-arm64-rootfs.tar.gz")
    value["baseSha256"] = result["sha256"]
    value["baseBuildDirectory"] = result["buildDirectory"]
    save(WORK / "plan.json", value)


def gpu():
    command("mesa", ["sudo", "env", "CODEX_MESA_JOBS=2", "bash", ROOT / "tools/gpu/build-mesa.sh"])
    archives = list((ROOT / "downloads/gpu").glob("codex-mesa-*-arm64.tar.gz"))
    if len(archives) != 1:
        raise ValueError("Expected exactly one Mesa release archive")
    value = state()
    value.update(gpuArchive=str(archives[0]), gpuSha256=digest(archives[0]))
    save(WORK / "plan.json", value)


def image():
    value = state()
    command("phone-image", [
        "sudo", sys.executable, "-B", ROOT / "tools/install/build-phone-image.py",
        "--base", value["baseArchive"], "--base-sha256", value["baseSha256"],
        "--gpu", value["gpuArchive"], "--gpu-sha256", value["gpuSha256"],
        "--official-input", WORK / "official-client",
        "--output", WORK / "phone-image", "--embed-archive",
    ])
    command("image-owner", ["sudo", "chown", "-R", f"{os.getuid()}:{os.getgid()}", WORK / "phone-image"])


def acquire_native_baseline():
    value = state()
    baseline = value["nativeBaseline"]
    apk_path = WORK / "native-baseline.apk"
    if apk_path.exists():
        if digest(apk_path) != baseline["sha256"]:
            raise ValueError("Previously downloaded native baseline SHA-256 differs")
    else:
        fetch(baseline["url"], apk_path, expected=baseline["sha256"])
    print("Native baseline download verified", flush=True)
    return apk_path


def recover_native():
    baseline = state()["nativeBaseline"]
    apk_path = acquire_native_baseline()
    sdk = Path(os.environ["ANDROID_HOME"])
    apksigner = sdk / "build-tools/36.0.0/lib/apksigner.jar"
    signature = run([Path(os.environ["JAVA_HOME"]) / "bin/java", "-jar", apksigner,
                     "verify", "--verbose", "--print-certs", apk_path])
    actual_certs = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]+)", signature)
    if [c.lower() for c in actual_certs] != [baseline["certificateSha256"].lower()]:
        raise ValueError("Native baseline APK certificate differs")

    out = WORK / "native"
    if out.exists():
        shutil.rmtree(out)
    runtime_libs = (
        "libproot.so", "libproot-loader.so", "libproot-loader32.so",
        "libtalloc.so", "libandroid-shmem.so",
    )
    with zipfile.ZipFile(apk_path) as zf:
        for name in runtime_libs:
            target = out / "runtime/arm64-v8a" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open("lib/arm64-v8a/" + name) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        x11_target = out / "x11/arm64-v8a/libXlorie.so"
        x11_target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open("lib/arm64-v8a/libXlorie.so") as src, x11_target.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    print("Extracted 6 verified ARM64 PRoot/Termux:X11 native libraries", flush=True)


def prepare_keystore():
    key = Path(os.environ.get("RUNNER_TEMP", WORK / "private")) / "agy-release.keystore"
    key.parent.mkdir(parents=True, exist_ok=True)
    if key.exists():
        key.unlink()
    encoded = os.environ.get("AGY_KEYSTORE_BASE64", "").strip()
    store_pass = os.environ.get("AGY_SIGNING_STORE_PASSWORD", "").strip() or "android"
    key_alias = os.environ.get("AGY_SIGNING_KEY_ALIAS", "").strip() or "agyrelease"
    key_pass = os.environ.get("AGY_SIGNING_KEY_PASSWORD", "").strip() or store_pass
    if encoded:
        with key.open("xb") as stream:
            os.chmod(key, 0o600)
            stream.write(base64.b64decode(encoded, validate=True))
    else:
        keytool = Path(os.environ["JAVA_HOME"]) / "bin/keytool"
        command("generate-keystore", [
            keytool, "-genkeypair", "-v",
            "-keystore", key, "-storetype", "PKCS12",
            "-storepass", store_pass, "-keypass", key_pass,
            "-alias", key_alias, "-keyalg", "RSA", "-keysize", "2048",
            "-validity", "10000",
            "-dname", "CN=Google Antigravity Android, O=AGY Mobile, C=US",
        ])
        os.chmod(key, 0o600)
    return key, store_pass, key_alias, key_pass


def apk():
    value = state()
    native = WORK / "native"
    sdk = Path(os.environ["ANDROID_HOME"])
    key, store_pass, key_alias, key_pass = prepare_keystore()
    env = dict(
        os.environ,
        CODEX_SIGNING_KEYSTORE=str(key),
        CODEX_SIGNING_STORE_PASSWORD=store_pass,
        CODEX_SIGNING_KEY_ALIAS=key_alias,
        CODEX_SIGNING_KEY_PASSWORD=key_pass,
    )
    try:
        command("gradle-assemble", [
            shutil.which("gradle"), "-p", ROOT / "android", "--no-daemon", "--stacktrace",
            f"-PcodexRuntimeJni={native / 'runtime'}",
            f"-PcodexX11Jni={native / 'x11'}",
            "-PcodexBuildToolsVersion=36.0.0",
            f"-PagyPhoneImageAssets={WORK / 'phone-image/assets'}",
            "-PagyEmbedPhoneImage=true",
            f"-PagyVersionCode={value['versionCode']}",
            f"-PagyVersionName={value['versionName']}",
            "assembleDebug",
        ], env=env)
    finally:
        key.unlink(missing_ok=True)

    built_apk = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
    if not built_apk.is_file():
        raise FileNotFoundError("Gradle did not produce expected APK: " + str(built_apk))

    # Verify APK signature and mandatory embedded entries
    apksigner = sdk / "build-tools/36.0.0/lib/apksigner.jar"
    command("apksigner-verify", [
        Path(os.environ["JAVA_HOME"]) / "bin/java", "-jar", apksigner,
        "verify", "--verbose", "--print-certs", built_apk,
    ])
    with zipfile.ZipFile(built_apk) as zf:
        names = set(zf.namelist())
        required_entries = {
            "assets/phone-runtime/agy-phone-rootfs.tgz",
            "assets/phone-runtime/release.json",
            "assets/phone-runtime/inventory.json",
            "assets/agy-tools/agy-session.sh",
            "assets/agy-tools/install_phone_mcp.py",
            "lib/arm64-v8a/libproot.so",
            "lib/arm64-v8a/libXlorie.so",
            "lib/arm64-v8a/libcodex-install.so",
            "lib/arm64-v8a/libcodex-device-files.so",
        }
        missing = sorted(required_entries - names)
        if missing:
            raise ValueError("Built APK is missing required entries: " + ", ".join(missing))

    if built_apk.stat().st_size >= 2 * 1024**3:
        raise ValueError("Full APK exceeds the 2 GiB GitHub Release asset limit")

    release = WORK / "release"
    release.mkdir(parents=True, exist_ok=True)
    destination = release / f"Antigravity-Android-{value['releaseTag']}-full.apk"
    shutil.copyfile(built_apk, destination)
    value.update(
        apk=destination.name,
        apkSha256=digest(destination),
        apkBytes=destination.stat().st_size,
        description=(ROOT / "config/android/release-notes.txt").read_text(encoding="utf-8").strip(),
    )
    save(release / "build-info.json", value)
    (release / "SHA256SUMS").write_text(value["apkSha256"] + "  " + destination.name + "\n", encoding="utf-8")
    print(json.dumps({"apk": destination.name, "sha256": value["apkSha256"], "bytes": value["apkBytes"]}))


def upload_release_asset(repository, release_id, path):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    endpoint = f"https://uploads.github.com/repos/{repository}/releases/{release_id}/assets?"
    endpoint += urllib.parse.urlencode({"name": path.name})
    with path.open("rb") as stream:
        request = urllib.request.Request(endpoint, data=stream, method="POST", headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "User-Agent": "agy-android-cloud-build",
            "Content-Type": "application/octet-stream",
            "Content-Length": str(path.stat().st_size),
        })
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=300) as response:
            return json.load(response)


def create_release(repository, tag, source_commit, title, description):
    endpoint = f"repos/{repository}/releases"
    body = json.dumps({
        "tag_name": tag,
        "target_commitish": source_commit,
        "name": title,
        "body": description,
        "draft": True,
    }).encode("utf-8")
    for attempt in range(1, 5):
        pages = json.loads(run(["gh", "api", "--paginate", "--slurp", endpoint + "?per_page=100"]))
        matches = [release for page in pages for release in page if release["tag_name"] == tag]
        if matches:
            if len(matches) != 1 or matches[0]["target_commitish"] != source_commit:
                raise ValueError(f"Release tag {tag} is already associated with another release")
            return matches[0]

        request = urllib.request.Request(
            f"https://api.github.com/{endpoint}", data=body, method="POST", headers={
                "Authorization": "Bearer " + os.environ["GH_TOKEN"],
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "agy-android-cloud-build",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in {500, 502, 503, 504} or attempt == 4:
                raise
            print(f"Release creation returned HTTP {error.code}; checking for a draft before retrying.",
                  flush=True)
            time.sleep(2 ** attempt)


def publish():
    value = json.loads((WORK / "release/build-info.json").read_text(encoding="utf-8"))
    env = os.environ
    repository, tag = env["GITHUB_REPOSITORY"], value["releaseTag"]
    files = [WORK / "release" / name for name in (value["apk"], "build-info.json", "SHA256SUMS")]
    description = (
        f"{value['description']}\n\n"
        f"- **Antigravity Linux ARM64 版本**：`{value['desktopVersion']}`\n"
        f"- **应用包名**：`com.ai.agy`\n"
        f"- **APK SHA-256**：`{value['apkSha256']}`\n"
    )
    metadata = create_release(
        repository, tag, value["sourceCommit"],
        f"Antigravity Android {tag} (Desktop {value['desktopVersion']})", description,
    )
    assets = {asset["name"]: asset for asset in metadata["assets"]}
    for path in files:
        if path.name in assets:
            asset = assets[path.name]
            if asset["state"] != "uploaded" or asset.get("digest") != f"sha256:{digest(path)}":
                raise ValueError(f"Release {tag} already has a different asset named {path.name}")
        elif metadata["draft"]:
            upload_release_asset(repository, metadata["id"], path)
        else:
            raise ValueError(f"Published release {tag} is missing {path.name}")
    result = metadata
    if metadata["draft"]:
        pub_json = WORK / "publish-release.json"
        save(pub_json, {"draft": False, "body": description})
        result = json.loads(command("release-publish", [
            "gh", "api", "--method", "PATCH",
            f"repos/{repository}/releases/{metadata['id']}", "--input", pub_json,
        ]))
    print(result["html_url"])
    if env.get("GITHUB_STEP_SUMMARY"):
        with Path(env["GITHUB_STEP_SUMMARY"]).open("a") as stream:
            stream.write(
                f"### Google Antigravity Desktop Android `{tag}`\n\n"
                f"- Download: [{value['apk']}]({result['html_url']})\n"
                f"- Antigravity Linux ARM64: `{value['desktopVersion']}`\n"
                f"- SHA-256: `{value['apkSha256']}`\n"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("plan", "client", "baseline", "base", "gpu", "image", "native", "apk", "publish"))
    stage = parser.parse_args().stage
    {
        "plan": plan, "client": acquire_client, "baseline": acquire_native_baseline,
        "base": base, "gpu": gpu, "image": image, "native": recover_native,
        "apk": apk, "publish": publish,
    }[stage]()
