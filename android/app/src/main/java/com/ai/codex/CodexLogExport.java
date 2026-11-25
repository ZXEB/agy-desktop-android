package com.ai.codex;

import android.content.Context;
import android.os.Build;
import android.os.Environment;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.zip.*;
import org.json.JSONObject;

/** Explicit user export of diagnostic logs; never collects auth/config/chat files. */
public final class CodexLogExport {
    private static final int LIMIT = 2 * 1024 * 1024;
    private CodexLogExport() {}
    public static File export(Context context) throws Exception {
        if (!Environment.isExternalStorageManager()) throw new IOException("请先允许所有文件访问，再点击导出日志");
        Path volume = Environment.getExternalStorageDirectory().toPath().toRealPath();
        Path folder = volume;
        for (String part : new String[]{"agy", "log"}) {
            folder = folder.resolve(part);
            if (Files.isSymbolicLink(folder)) throw new IOException("日志目录不能是符号链接");
            Files.createDirectories(folder);
            if (!folder.toRealPath().startsWith(volume)) throw new IOException("日志目录超出共享存储");
        }
        String name = "agy-logs-" + new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.ROOT).format(new Date()) + "-" + UUID.randomUUID().toString().substring(0, 8) + ".zip";
        Path target = folder.resolve(name), temporary = folder.resolve("." + name + ".partial");
        StringBuilder notes = new StringBuilder("Google Antigravity Android diagnostics. Each source is limited to its last 2 MiB.\nKnown credential patterns are redacted; inspect before sharing.\n");
        try {
            try (ZipOutputStream zip = new ZipOutputStream(Files.newOutputStream(temporary, StandardOpenOption.CREATE_NEW))) {
                JSONObject device = new JSONObject().put("manufacturer", Build.MANUFACTURER).put("model", Build.MODEL)
                    .put("android", Build.VERSION.RELEASE).put("api", Build.VERSION.SDK_INT).put("abi", Arrays.toString(Build.SUPPORTED_ABIS))
                    .put("kernel", System.getProperty("os.version")).put("graphicsRequested", CodexGraphics.mode(context))
                    .put("versionName", context.getPackageManager().getPackageInfo(context.getPackageName(), 0).versionName)
                    .put("versionCode", context.getPackageManager().getPackageInfo(context.getPackageName(), 0).getLongVersionCode());
                entry(zip, "device.json", device.toString(2));
                for (String file : new String[]{"runtime.log", "last-startup-error.txt", "shared-storage-status.json"})
                    collect(zip, context.getFilesDir().toPath().resolve(file), file, notes);
                try {
                    Path state = CodexStoragePaths.guestHome(context).resolve(".local/state");
                    for (String file : new String[]{"codex-ime.log", "codex-wm.log", "codex-dialogs.log", "codex-gpu-probe.log", "codex-graphics.json"})
                        collect(zip, state.resolve(file), "guest/" + file, notes);
                } catch (Exception error) { notes.append("Guest logs unavailable: ").append(error.getMessage()).append('\n'); }
                Path capture = Files.createTempFile(context.getCacheDir().toPath(), "agy-logcat-", ".txt");
                try {
                    Process process = new ProcessBuilder("/system/bin/logcat", "-d", "--uid=" + android.os.Process.myUid(), "-v", "threadtime", "-t", "1500")
                        .redirectErrorStream(true).redirectOutput(capture.toFile()).start();
                    if (!process.waitFor(4, TimeUnit.SECONDS)) { process.destroyForcibly(); process.waitFor(1, TimeUnit.SECONDS); notes.append("Logcat collection timed out; partial output included.\n"); }
                    collect(zip, capture, "android-logcat.txt", notes);
                } catch (Exception error) { notes.append("Logcat unavailable: ").append(error.getMessage()).append('\n'); }
                finally { Files.deleteIfExists(capture); }
                entry(zip, "README.txt", notes.toString());
            }
            Files.move(temporary, target);
            return target.toFile();
        } catch (Exception error) { Files.deleteIfExists(temporary); throw error; }
    }
    private static void collect(ZipOutputStream zip, Path file, String name, StringBuilder notes) throws IOException {
        if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)) { notes.append("Not available: ").append(name).append('\n'); return; }
        try (RandomAccessFile stream = new RandomAccessFile(file.toFile(), "r")) {
            long start = Math.max(0, stream.length() - LIMIT); stream.seek(start);
            byte[] bytes = new byte[(int)Math.min(stream.length() - start, LIMIT)];
            int total = 0, count;
            while (total < bytes.length && (count = stream.read(bytes, total, bytes.length - total)) > 0) total += count;
            entry(zip, name, new String(bytes, 0, total, StandardCharsets.UTF_8));
            if (start > 0) notes.append("Tail only: ").append(name).append('\n');
        } catch (IOException error) { notes.append("Read failed: ").append(name).append(" (may have rotated)\n"); }
    }
    static String redact(String text) {
        return text.replaceAll("(?i)((?:proxy-)?authorization[\"']?\\s*[:=]\\s*[\"']?(?:bearer\\s+)?)[^\\s\"',}]+", "$1[REDACTED]")
            .replaceAll("(?im)(cookie\\s*:\\s*)[^\\r\\n]+", "$1[REDACTED]")
            .replaceAll("(?i)((?:api[_-]?key|access_token|refresh_token|experimental_bearer_token|cookie)\\s*[\"']?\\s*[:=]\\s*[\"']?)[^\\s\"',}]+", "$1[REDACTED]")
            .replaceAll("\\b(?:sk-|AIza|ya29\\.)[A-Za-z0-9_.-]{12,}", "[REDACTED]");
    }
    private static void entry(ZipOutputStream zip, String name, String text) throws IOException {
        zip.putNextEntry(new ZipEntry(name)); zip.write(redact(text).getBytes(StandardCharsets.UTF_8)); zip.closeEntry();
    }
}
