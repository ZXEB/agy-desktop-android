package com.ai.codex;

import android.content.Context;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import android.util.AtomicFile;
import com.ai.codex.install.GuestIdentity;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;

/** Installs APK-owned Google Antigravity guest session scripts, IME/graphics bridges, and Phone MCP plugins. */
public final class CodexLocalTools {
    private CodexLocalTools() {}

    public static File install(Context context, GuestIdentity identity) throws Exception {
        File files = context.getFilesDir().getCanonicalFile();
        int uid = context.getApplicationInfo().uid;
        File guestRoot = new File(files, "debian").getCanonicalFile();
        StructStat guestState = Os.lstat(guestRoot.getPath());
        if (!guestRoot.toPath().startsWith(files.toPath()) || guestRoot.equals(files)
                || !OsConstants.S_ISDIR(guestState.st_mode) || guestState.st_uid != uid) {
            throw new IOException("Antigravity guest root is outside the owned application files");
        }
        File tools = directory(files, "agy-tools", uid);
        writeAsset(context, tools, "phone_relay.py", "agy-android/scripts/phone_relay.py", uid);

        JSONObject config = new JSONObject();
        config.put("schema", "agy.local-tools.v1");
        config.put("uid", uid);
        config.put("packageName", context.getPackageName());
        config.put("filesDir", files.getPath());
        config.put("guestHome", identity.home);
        config.put("guestUser", identity.user);
        config.put("guestIds", identity.prootIds());
        config.put("versionCode", context.getPackageManager().getPackageInfo(context.getPackageName(), 0).getLongVersionCode());
        write(new File(tools, "installation.json"), (config.toString(2) + "\n").getBytes(StandardCharsets.UTF_8), uid);

        File contextDir = directory(guestRoot, "usr/local/lib/codex", uid);
        File share = directory(guestRoot, "usr/local/share/codex", uid);

        writeAsset(context, contextDir, "install_phone_mcp.py", "agy-tools/install_phone_mcp.py", uid);
        writeAsset(context, contextDir, "codex_native_dialogs.py", "agy-tools/codex_native_dialogs.py", uid);
        writeAsset(context, contextDir, "codex-phone-dialogs.css", "agy-tools/codex-phone-dialogs.css", uid);
        writeAsset(context, contextDir, "codex_ime.py", "agy-tools/codex_ime.py", uid);
        writeAsset(context, contextDir, "keyboard-focus.js", "agy-tools/keyboard-focus.js", uid);
        writeAsset(context, contextDir, "codex-graphics.sh", "agy-tools/codex-graphics.sh", uid);
        writeAsset(context, contextDir, "codex-software-probe.py", "agy-tools/codex-software-probe.py", uid);

        File guestBin = directory(guestRoot, "usr/local/bin", uid);
        writeAsset(context, guestBin, "agy-session", "agy-tools/agy-session.sh", uid);
        Os.chmod(new File(guestBin, "agy-session").getPath(), 0700);

        JSONObject environment;
        try (InputStream input = context.getAssets().open("agy-tools/agent-environment.v1.json")) {
            environment = new JSONObject(new String(InputStreams.readAllBytes(input), StandardCharsets.UTF_8));
        }
        JSONObject host = environment.getJSONObject("clientHost");
        String device = android.os.Build.MANUFACTURER + " " + android.os.Build.MODEL;
        host.put("referenceDevice", device);
        host.put("androidRoot", CodexDeviceFeatures.enabled(context, "root"));
        host.put("referenceApi", android.os.Build.VERSION.SDK_INT);
        host.put("architecture", android.os.Build.SUPPORTED_ABIS[0]);
        host.put("applicationName", context.getApplicationInfo().loadLabel(context.getPackageManager()).toString());
        host.put("androidVersion", android.os.Build.VERSION.RELEASE);
        host.put("socModel", android.os.Build.VERSION.SDK_INT >= 31 ? android.os.Build.SOC_MODEL : "unknown");
        host.put("kernelVersion", System.getProperty("os.version", "unknown"));
        host.put("timezone", java.util.TimeZone.getDefault().getID());
        host.put("sharedStorage", SharedProjectStorage.inspect(context));
        write(new File(share, "agent-environment.v1.json"), (environment.toString(2) + "\n").getBytes(StandardCharsets.UTF_8), uid);

        JSONObject bridge = new JSONObject().put("schema", "codex.android.bridge.v1").put("androidUid", uid)
                .put("httpUrl", "http://127.0.0.1:3090").put("httpToken", CodexDeviceHttp.token(context));
        write(new File(share, "android-bridge.json"), (bridge.toString(2) + "\n").getBytes(StandardCharsets.UTF_8), uid);

        installPluginAssets(context, guestRoot, "agy-android", "usr/local/share/codex/plugins/agy-android", uid);
        return tools;
    }

    private static void installPluginAssets(Context context, File files, String asset, String relative, int uid) throws Exception {
        String[] children = context.getAssets().list(asset);
        if (children == null) throw new IOException("Missing Android plugin assets");
        File destination = directory(files, relative, uid);
        for (String child : children) {
            if (!child.matches("[A-Za-z0-9_.-]+")) throw new IOException("Unexpected Android plugin asset name");
            String entry = asset + "/" + child;
            String[] nested = context.getAssets().list(entry);
            if (nested != null && nested.length > 0) installPluginAssets(context, files, entry, relative + "/" + child, uid);
            else writeAsset(context, destination, child, entry, uid);
        }
    }

    private static File directory(File root, String relative, int uid) throws Exception {
        File current = root;
        for (String part : relative.split("/")) {
            current = new File(current, part);
            try { Os.mkdir(current.getPath(), 0700); }
            catch (ErrnoException exists) { if (exists.errno != OsConstants.EEXIST) throw exists; }
            StructStat state = Os.lstat(current.getPath());
            if (!OsConstants.S_ISDIR(state.st_mode) || state.st_uid != uid) {
                throw new IOException("Antigravity tool directory is not app-owned: " + relative);
            }
        }
        return current;
    }

    private static void writeAsset(Context context, File directory, String name, String asset, int uid) throws Exception {
        try (InputStream stream = context.getAssets().open(asset)) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int count;
            while ((count = stream.read(buffer)) != -1) {
                if (bytes.size() + count > 131072) throw new IOException("Antigravity tool asset is too large");
                bytes.write(buffer, 0, count);
            }
            write(new File(directory, name), bytes.toByteArray(), uid);
        }
    }

    private static void write(File file, byte[] bytes, int uid) throws Exception {
        try {
            StructStat state = Os.lstat(file.getPath());
            if (!OsConstants.S_ISREG(state.st_mode) || state.st_uid != uid || state.st_nlink != 1) {
                throw new IOException("Antigravity tool destination is not an owned regular file: " + file.getName());
            }
            if (Arrays.equals(Files.readAllBytes(file.toPath()), bytes)) return;
        } catch (ErrnoException absent) {
            if (absent.errno != OsConstants.ENOENT) throw absent;
        }
        AtomicFile atomic = new AtomicFile(file);
        FileOutputStream output = null;
        try {
            output = atomic.startWrite();
            output.write(bytes);
            Os.fchmod(output.getFD(), 0600);
            atomic.finishWrite(output);
        } catch (Exception error) {
            if (output != null) atomic.failWrite(output);
            throw error;
        }
    }
}
