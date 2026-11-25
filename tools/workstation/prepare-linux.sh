#!/usr/bin/env bash
# Prepare a Linux build workspace and dependencies. This script never compiles an APK.
set -euo pipefail
source_root=$(realpath "${1:?Pass_the_WSL_checkout_path}")
windows_sdk=$(realpath "${2:?Pass_the_WSL_Android_SDK_path}")
task_root="$HOME/codex-android"
sdk="$task_root/android-sdk"
destination="$task_root/source"
system_java=/usr/lib/jvm/java-21-openjdk-amd64
export JAVA_HOME="$task_root/jdk-21"
test -x "$system_java/bin/java"
command -v rsync >/dev/null
mkdir -p "$JAVA_HOME"
rsync -aL --no-owner --no-group --exclude docs --exclude src.zip "$system_java/" "$JAVA_HOME/"
export PATH="$JAVA_HOME/bin:$PATH"
export GRADLE_USER_HOME="$task_root/gradle-home"
export RUSTUP_TOOLCHAIN=1.99.1
test -f "$source_root/android/app/build.gradle"
test -x "$JAVA_HOME/bin/java"
command -v rsync >/dev/null
mkdir -p "$destination" "$sdk/platforms" "$sdk/licenses" "$GRADLE_USER_HOME"
test "$(realpath "$destination")" = "$HOME/codex-android/source"
rsync -a --delete --no-owner --no-group \
    --exclude '/work/' --exclude '/downloads/' --exclude '/artifacts/' --exclude '/.tooling/' \
    --exclude '/.git/' --exclude '.gradle/' --exclude 'build/' --exclude '__pycache__/' \
    --exclude '.cxx/' --exclude 'local.properties' --exclude '*.keystore' --exclude '*.jks' \
    "$source_root/" "$destination/"
cp -n "$windows_sdk/licenses/"* "$sdk/licenses/" 2>/dev/null || true
for platform in "$windows_sdk"/platforms/android-37*; do
    test -d "$platform" || continue
    link="$sdk/platforms/$(basename "$platform")"
    if [[ -L "$link" ]]; then
        test "$(realpath "$link")" = "$(realpath "$platform")"
        backup="$task_root/$(basename "$platform").windows-link"
        test ! -e "$backup" && test ! -L "$backup"
        mv -T -- "$link" "$backup"
    fi
    if [[ ! -f "$link/android.jar" ]]; then
        mkdir -p "$link"
        rsync -a --no-owner --no-group --chmod=D755,F644 "$platform/" "$link/"
    fi
done
classpath="$windows_sdk/cmdline-tools/latest/lib/sdkmanager-classpath.jar"
test -f "$classpath"
java -cp "$classpath" com.android.sdklib.tool.sdkmanager.SdkManagerCli \
    --sdk_root="$sdk" 'build-tools;36.0.0' 'ndk;29.0.14206865' 'cmake;3.22.1'
printf 'sdk.dir=%s\n' "$sdk" > "$destination/android/local.properties"
mkdir -p "$task_root/gradle"
if [[ ! -f "$task_root/gradle/gradle-9.7.1/bin/gradle" ]]; then
    unzip -q "$source_root/downloads/gradle-9.7.1-bin.zip" -d "$task_root/gradle"
fi
printf 'Source: %s\nSDK: %s\nGradle cache: %s\n' "$destination" "$sdk" "$GRADLE_USER_HOME"
java -version
"$HOME/.cargo/bin/rustc" --version
"$HOME/.cargo/bin/rustup" target list --installed --toolchain 1.99.1
bash "$task_root/gradle/gradle-9.7.1/bin/gradle" --version
