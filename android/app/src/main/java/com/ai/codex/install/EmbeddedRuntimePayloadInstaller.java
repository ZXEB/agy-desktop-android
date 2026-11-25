package com.ai.codex.install;

import android.content.Context;
import android.content.res.AssetManager;
import android.os.PowerManager;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import com.ai.codex.InputStreams;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.Collections;
import java.util.function.Consumer;
import org.json.JSONObject;

/** Cover updates reuse the APK-owned agy-phone-rootfs.tgz image to refresh
 * /opt/antigravity when upgrading an existing installation, keeping accounts,
 * ~/.gemini config, projects, and installed Debian packages intact. */
public final class EmbeddedRuntimePayloadInstaller {
    private static final String TEMP_PREFIX = ".agy-payload-update-";
    private static final String DESKTOP = "opt/antigravity";

    private EmbeddedRuntimePayloadInstaller() { }

    public static synchronized void install(Context context, File installedRoot, Consumer<String> progress)
            throws Exception {
        AssetManager assets = context.getAssets();
        String[] runtimeAssets = assets.list("phone-runtime");
        if (runtimeAssets == null || !Arrays.asList(runtimeAssets).contains("agy-phone-rootfs.tgz")) return;
        JSONObject release = metadata(assets, "phone-runtime/release.json");
        if (!"agy.phone-image.v1".equals(release.getString("format"))
                || !"agy-phone-rootfs.tar.gz".equals(release.getString("archive"))
                || release.getBoolean("accountIncluded") || release.getBoolean("keyringIncluded")) {
            throw new IOException("Unsupported embedded image payloads");
        }
        String expectedVersion = release.getJSONObject("client").getString("version");
        Path files = context.getFilesDir().getCanonicalFile().toPath();
        Path root = installedRoot.getCanonicalFile().toPath();
        if (root.equals(files) || !root.startsWith(files)) throw new IOException("Image update root is not app-owned");
        int uid = context.getApplicationInfo().uid;
        requireDirectory(root, uid);

        Path versionFile = root.resolve(DESKTOP + "/.antigravity-linux-version");
        if (Files.isRegularFile(versionFile, LinkOption.NOFOLLOW_LINKS)) {
            String installedVersion = Files.readString(versionFile, StandardCharsets.UTF_8).trim();
            if (expectedVersion.equals(installedVersion)) return;
        }

        try (DirectoryStream<Path> children = Files.newDirectoryStream(files, TEMP_PREFIX + "*")) {
            for (Path child : children) { requireDirectory(child, uid); removeTree(child); }
        }
        JSONObject value = release.getJSONObject("spec");
        RootfsExtractor.Spec spec = new RootfsExtractor.Spec(value.getString("sha256"),
                value.getLong("compressedBytes"), value.getLong("payloadBytes"),
                value.getLong("maxTarBytes"), value.getInt("members"));
        if (files.toFile().getUsableSpace() < spec.compressedBytes + 512L * 1024 * 1024) {
            throw new IOException("内部存储空间不足，请释放空间后重试 Antigravity 更新。");
        }
        PowerManager.WakeLock wake = context.getSystemService(PowerManager.class)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Antigravity:payload-update");
        wake.acquire();
        Path temporary = null;
        try {
            progress.accept("正在从完整环境中更新 Google Antigravity 桌面端…");
            temporary = Files.createTempDirectory(files, TEMP_PREFIX,
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            Path payload;
            try (InputStream input = assets.open("phone-runtime/agy-phone-rootfs.tgz", AssetManager.ACCESS_STREAMING)) {
                payload = RootfsExtractor.prepareSubset(input, temporary, spec,
                        new AndroidRootfsTransaction.Posix(), Collections.singleton(DESKTOP)).root;
            }
            Path extractedDesktop = payload.resolve(DESKTOP);
            if (!Files.isDirectory(extractedDesktop, LinkOption.NOFOLLOW_LINKS)) {
                throw new IOException("Updated Antigravity desktop payload is missing");
            }
            Path optDir = root.resolve("opt");
            Files.createDirectories(optDir);
            Path target = root.resolve(DESKTOP);
            Path backup = root.resolve("opt/.antigravity-previous");
            if (Files.exists(backup, LinkOption.NOFOLLOW_LINKS)) removeTree(backup);
            if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) {
                Files.move(target, backup, StandardCopyOption.ATOMIC_MOVE);
            }
            try {
                Files.move(extractedDesktop, target, StandardCopyOption.ATOMIC_MOVE);
            } catch (Exception moveError) {
                if (Files.exists(backup, LinkOption.NOFOLLOW_LINKS) && !Files.exists(target, LinkOption.NOFOLLOW_LINKS)) {
                    Files.move(backup, target, StandardCopyOption.ATOMIC_MOVE);
                }
                throw moveError;
            }
            if (Files.exists(backup, LinkOption.NOFOLLOW_LINKS)) removeTree(backup);
            progress.accept("Google Antigravity 桌面端更新完成，正在启动…");
        } finally {
            try { if (temporary != null) removeTree(temporary); }
            finally { wake.release(); }
        }
    }

    private static JSONObject metadata(AssetManager assets, String name) throws Exception {
        try (InputStream input = assets.open(name)) {
            byte[] bytes = InputStreams.readNBytes(input, 65537);
            if (bytes.length > 65536) throw new IOException("Image payload metadata exceeds its bound");
            return new JSONObject(new String(bytes, StandardCharsets.UTF_8));
        }
    }

    private static void requireDirectory(Path path, int uid) throws Exception {
        StructStat state = Os.lstat(path.toString());
        if (!OsConstants.S_ISDIR(state.st_mode) || state.st_uid != uid || (state.st_mode & 0022) != 0
                || !path.equals(path.toRealPath())) {
            throw new IOException("Image update directory is not app-owned");
        }
    }

    private static void removeTree(Path path) throws Exception {
        if (Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) {
            Os.chmod(path.toString(), 0700);
            try (DirectoryStream<Path> children = Files.newDirectoryStream(path)) {
                for (Path child : children) removeTree(child);
            }
        }
        Files.delete(path);
    }
}
