#!/usr/bin/env bash
# Compile app and native-phone test classes only. No APK/AAB task or signing.
set -euo pipefail
repo=$(realpath "${1:?Pass_the_WSL_checkout_path}")
runtime_jni=$(realpath "${2:?Pass_the_reviewed_runtime_JNI_directory}")
task_root="$HOME/codex-android"
destination="$task_root/source"
test "$(realpath "$destination")" = "$HOME/codex-android/source"
rsync -a --delete --no-owner --no-group \
    --exclude '/work/' --exclude '/downloads/' --exclude '/artifacts/' --exclude '/.tooling/' \
    --exclude '/.git/' --exclude '.gradle/' --exclude 'build/' --exclude '__pycache__/' \
    --exclude '.cxx/' --exclude 'local.properties' --exclude '*.keystore' --exclude '*.jks' \
    "$repo/" "$destination/"
export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
export PATH="$JAVA_HOME/bin:$PATH"
export GRADLE_USER_HOME="$task_root/gradle-home"
printf 'sdk.dir=%s\n' "$task_root/android-sdk" > "$destination/android/local.properties"
cd "$destination/android"
extra_args=()
if [[ -n "${CODEX_GRADLE_INIT:-}" ]]; then
    extra_args+=(--init-script "$(realpath "$CODEX_GRADLE_INIT")")
fi
bash "$task_root/gradle/gradle-9.7.1/bin/gradle" \
    --no-daemon --console=plain --max-workers=1 \
    '-Dorg.gradle.jvmargs=-Xmx1g -Dfile.encoding=UTF-8' \
    -Pkotlin.compiler.execution.strategy=in-process -PcodexPhoneTestsOnly \
    "-PcodexRuntimeJni=$runtime_jni" \
    "${extra_args[@]}" \
    :app:compileDebugKotlin :app:compileDebugJavaWithJavac \
    :app:compileDebugUnitTestKotlin :app:compileDebugUnitTestJavaWithJavac
