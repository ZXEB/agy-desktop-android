package com.ai.codex;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.Locale;

/** Small display-only transcript. Never tails a previous launch or changes runtime output. */
public final class CodexStartupLog {
    private static final int MAX_BYTES = 16 * 1024;
    private static final int MAX_LINES = 64;
    private static final int MAX_COLUMNS = 192;
    private final ArrayDeque<String> steps = new ArrayDeque<>();
    private long startedAt;
    private String lastStep = "", runtime = "";

    public void reset(long now) {
        steps.clear();
        startedAt = now;
        lastStep = runtime = "";
    }

    public boolean step(String message, long now) {
        String clean = sanitize(message);
        if (clean.isEmpty() || clean.equals(lastStep)) return false;
        lastStep = clean;
        String elapsed = String.format(Locale.ROOT, "[%06.1fs] ", Math.max(0, now - startedAt) / 1000d);
        for (String line : clean.split("\n")) steps.addLast(elapsed + line);
        while (steps.size() > 12) steps.removeFirst();
        return true;
    }

    public boolean runtime(String text) {
        String clean = sanitize(text);
        if (runtime.equals(clean)) return false;
        runtime = clean;
        return true;
    }

    public String snapshot() {
        String joined = String.join("\n", steps);
        return limit(joined + (joined.isEmpty() || runtime.isEmpty() ? "" : "\n") + runtime);
    }

    /** Called only on the startup worker after this launch has opened runtime.log. */
    public static String readTail(File file) {
        try (RandomAccessFile input = new RandomAccessFile(file, "r")) {
            long length = input.length();
            long start = Math.max(0, length - MAX_BYTES);
            input.seek(start);
            byte[] bytes = new byte[(int) Math.min(MAX_BYTES, length - start)];
            int size = 0, count;
            while (size < bytes.length && (count = input.read(bytes, size, bytes.length - size)) > 0) size += count;
            int offset = 0;
            if (start > 0) {
                // Skip the cut line, including any incomplete UTF-8 character or credential.
                while (offset < size && bytes[offset++] != '\n') { }
            }
            return sanitize(new String(bytes, offset, size - offset, StandardCharsets.UTF_8));
        } catch (IOException | SecurityException ignored) {
            return ""; // A missing or rotated decoration must never fail startup.
        }
    }

    static String sanitize(String text) {
        if (text == null || text.isEmpty()) return "";
        // A broadcast and each draw stay bounded even if one producer emits a very long line.
        if (text.length() > MAX_BYTES) {
            int newline = text.indexOf('\n', text.length() - MAX_BYTES);
            text = newline < 0 ? "" : text.substring(newline + 1);
        }
        text = text.replaceAll("\\x1b\\][^\\x07\\x1b]*(?:\\x07|\\x1b\\\\)", "")
                .replaceAll("\\x1b\\[[0-?]*[ -/]*[@-~]", "")
                .replace("\r\n", "\n").replace('\r', '\n')
                .replaceAll("[\\p{Cntrl}&&[^\n\t]]", "").replace("\t", "  ");
        text = CodexLogExport.redact(text)
                .replaceAll("(?im)((?:proxy-)?authorization[\"']?\\s*[:=]\\s*)[^\r\n]+", "$1[REDACTED]")
                .replaceAll("(?i)((?:[a-z0-9_]*(?:password|passwd|secret|session_token|id_token|code_verifier))\\s*[\"']?\\s*[:=]\\s*[\"']?)[^\\s\"',}]+", "$1[REDACTED]")
                .replaceAll("([?&][A-Za-z0-9_.~-]+=)[^\\s&#\"']+", "$1[REDACTED]");
        return limit(text);
    }

    private static String limit(String text) {
        ArrayDeque<String> lines = new ArrayDeque<>();
        for (String line : text.split("\n")) {
            if (line.trim().isEmpty()) continue;
            lines.addLast(line.length() > MAX_COLUMNS ? line.substring(0, MAX_COLUMNS - 1) + "…" : line);
            if (lines.size() > MAX_LINES) lines.removeFirst();
        }
        return String.join("\n", lines);
    }
}
