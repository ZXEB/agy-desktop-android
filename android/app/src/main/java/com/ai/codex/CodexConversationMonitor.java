package com.ai.codex;

import android.os.FileObserver;
import android.util.Log;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

/** Watches Antigravity's local ~/.gemini/antigravity/brain conversation transcripts
 * to drive Live Updates / Dynamic Island notifications without touching app state. */
public final class CodexConversationMonitor implements AutoCloseable {
    public interface Listener { void changed(String thread, String title, ConversationActivity.Change change, int active, String status); }
    private static final int MAX_LINE = 4 * 1024 * 1024;
    private final ExecutorService worker = Executors.newSingleThreadExecutor(r -> new Thread(r, "Agy-conversations"));
    private final Map<File, FileObserver> watches = new HashMap<>();
    private final Map<File, Tail> tails = new HashMap<>();
    private final Set<String> activeThreads = new HashSet<>();
    private final Map<String, String> statuses = new HashMap<>();
    private final File brainRoot;
    private final Listener listener;
    private volatile boolean closed;

    private static final class Tail {
        long offset;
        boolean oversized;
        final ByteArrayOutputStream pending = new ByteArrayOutputStream();
    }

    public CodexConversationMonitor(File brainRoot, Listener listener) {
        this.brainRoot = brainRoot;
        this.listener = listener;
    }

    public java.util.concurrent.CompletableFuture<Void> start() {
        return java.util.concurrent.CompletableFuture.runAsync(() -> {
            if (!brainRoot.isDirectory() && !brainRoot.mkdirs()) {
                Log.w("Agy-conversations", "Brain directory unavailable");
                return;
            }
            scan(brainRoot, 0, true);
        }, worker);
    }

    private void scan(File directory, int depth, boolean baseline) {
        if (closed || depth > 4 || Files.isSymbolicLink(directory.toPath()) || !directory.isDirectory()) return;
        if (!watches.containsKey(directory)) {
            FileObserver observer = new FileObserver(directory,
                    FileObserver.CREATE | FileObserver.MOVED_TO | FileObserver.MODIFY | FileObserver.CLOSE_WRITE) {
                @Override public void onEvent(int event, String path) {
                    if (closed || path == null || path.contains("/") || path.equals("..")) return;
                    try {
                        worker.execute(() -> {
                            File child = new File(directory, path);
                            if (child.isDirectory()) scan(child, depth + 1, false);
                            else if ("transcript.jsonl".equals(child.getName())) read(child, false);
                        });
                    } catch (java.util.concurrent.RejectedExecutionException ignored) { }
                }
            };
            watches.put(directory, observer);
            observer.startWatching();
        }
        File[] children = directory.listFiles();
        if (children == null) return;
        for (File child : children) {
            if (child.isDirectory()) scan(child, depth + 1, baseline);
            else if ("transcript.jsonl".equals(child.getName())) read(child, baseline);
        }
    }

    private String conversationIdFor(File transcript) {
        File current = transcript.getParentFile();
        while (current != null && !current.equals(brainRoot)) {
            File parent = current.getParentFile();
            if (brainRoot.equals(parent)) return current.getName();
            current = parent;
        }
        return "agy-session";
    }

    private void read(File file, boolean baseline) {
        if (closed || Files.isSymbolicLink(file.toPath()) || !file.isFile()) return;
        String thread = conversationIdFor(file);
        Tail tail = tails.computeIfAbsent(file, key -> new Tail());
        try (RandomAccessFile input = new RandomAccessFile(file, "r")) {
            if (baseline) { tail.offset = input.length(); return; }
            if (input.length() < tail.offset) { tail.offset = 0; tail.pending.reset(); tail.oversized = false; }
            input.seek(tail.offset);
            byte[] buffer = new byte[16384];
            int count;
            while (!closed && (count = input.read(buffer)) > 0) {
                tail.offset += count;
                for (int i = 0; i < count; i++) {
                    if (buffer[i] == '\n') {
                        if (!tail.oversized) handleEvent(thread, tail.pending.toString(StandardCharsets.UTF_8.name()));
                        tail.pending.reset();
                        tail.oversized = false;
                    } else if (!tail.oversized) {
                        if (tail.pending.size() == MAX_LINE) { tail.pending.reset(); tail.oversized = true; }
                        else tail.pending.write(buffer[i]);
                    }
                }
            }
        } catch (Exception error) {
            Log.w("Agy-conversations", "Transcript observation failed", error);
        }
    }

    private void handleEvent(String thread, String line) {
        if (closed || line.isEmpty() || line.charAt(0) != '{') return;
        try {
            JSONObject record = new JSONObject(line);
            String type = record.optString("type", record.optString("role", "")).toLowerCase();
            String toolName = record.optString("tool", record.optString("name", "")).toLowerCase();
            String status = null;
            ConversationActivity.Change change = ConversationActivity.Change.NONE;
            if (type.contains("user") || type.contains("prompt")) {
                activeThreads.add(thread);
                status = "思考中";
                change = ConversationActivity.Change.STARTED;
            } else if (type.contains("tool") || !toolName.isEmpty()) {
                boolean added = activeThreads.add(thread);
                if (toolName.contains("command") || toolName.contains("shell")) status = "执行命令";
                else if (toolName.contains("edit") || toolName.contains("write")) status = "修改文件";
                else if (toolName.contains("read") || toolName.contains("search")) status = "阅读代码";
                else status = "调用工具";
                change = added ? ConversationActivity.Change.STARTED : ConversationActivity.Change.UPDATED;
            } else if (type.contains("assistant") || type.contains("model") || type.contains("complete") || type.contains("done")) {
                if (activeThreads.remove(thread)) {
                    status = "已完成";
                    change = ConversationActivity.Change.COMPLETED;
                }
            }
            if (change != ConversationActivity.Change.NONE) {
                if (status != null) statuses.put(thread, status);
                listener.changed(thread, "Antigravity 对话", change, activeThreads.size(), statuses.getOrDefault(thread, "处理中"));
                if (change == ConversationActivity.Change.COMPLETED) statuses.remove(thread);
            }
        } catch (Exception ignored) { }
    }

    @Override public synchronized void close() {
        if (closed) return;
        closed = true;
        worker.execute(() -> {
            for (FileObserver observer : watches.values()) observer.stopWatching();
            watches.clear();
            tails.clear();
            activeThreads.clear();
            statuses.clear();
        });
        worker.shutdown();
    }
}
