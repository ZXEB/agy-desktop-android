"""Verify source completeness before running expensive cloud image/APK jobs."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = (
    "android/app/build.gradle",
    "android/app/src/main/AndroidManifest.xml",
    "android/app/src/main/java/com/termux/x11/CodexRuntimeService.java",
    "android/install-native/CMakeLists.txt",
    "android/install-native/install-files.c",
    "tools/recovery/android-signing.gradle",
    "config/agent-context/agy.v1.json",
    "config/pulseaudio/codex-pulse.pa",
    "config/android/native-baseline.json",
    "config/android/release-notes.txt",
    "runtime/guest/agy-session.sh",
    "runtime/guest/codex_ime.py",
    "runtime/guest/keyboard-focus.js",
    "runtime/guest/codex-graphics.sh",
    "runtime/guest/codex-software-probe.py",
    "runtime/guest/codex_keyring.py",
    "plugins/codex-android/scripts/server.py",
    "plugins/codex-android/scripts/phone_relay.py",
    "plugins/codex-android/skills/phone/SKILL.md",
    "plugins/codex-android/skills/android/SKILL.md",
    "tools/runtime/install_phone_mcp.py",
    "tools/install/build_rootfs.py",
    "tools/install/verify_rootfs.py",
    "tools/install/build-phone-image.py",
    "tools/install/phone_image.py",
    "tools/gpu/build-mesa.sh",
    "vendor/termux-x11/lorie/build.gradle",
)


def main():
    errors = []
    checked = 0
    for relative in REQUIRED:
        path = ROOT / relative
        checked += 1
        if not path.is_file() or not path.stat().st_size:
            errors.append("Missing or empty source: " + relative)
    settings = (ROOT / "android/settings.gradle").read_text(encoding="utf-8")
    for relative in re.findall(r"projectDir\s*=\s*file\('([^']+)'\)", settings):
        p = (ROOT / "android" / relative / "build.gradle").resolve()
        if not p.is_file():
            errors.append("Missing Gradle module: " + relative)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Source integrity verified: {checked} required files and Gradle modules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
