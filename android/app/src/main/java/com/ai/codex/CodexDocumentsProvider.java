package com.ai.codex;

import android.database.Cursor;
import android.database.MatrixCursor;
import android.os.CancellationSignal;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract.Document;
import android.provider.DocumentsContract.Root;
import android.provider.DocumentsProvider;
import android.system.Os;
import android.system.OsConstants;
import android.util.Base64;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Standard SAF access to the complete .codex tree, only after a system URI grant. */
public final class CodexDocumentsProvider extends DocumentsProvider {
    private static final String[] ROOT_COLUMNS = {Root.COLUMN_ROOT_ID, Root.COLUMN_DOCUMENT_ID,
        Root.COLUMN_TITLE, Root.COLUMN_SUMMARY, Root.COLUMN_FLAGS, Root.COLUMN_MIME_TYPES, Root.COLUMN_ICON};
    private static final String[] DOCUMENT_COLUMNS = {Document.COLUMN_DOCUMENT_ID, Document.COLUMN_DISPLAY_NAME,
        Document.COLUMN_MIME_TYPE, Document.COLUMN_FLAGS, Document.COLUMN_SIZE, Document.COLUMN_LAST_MODIFIED};
    private final ConcurrentHashMap<Path, Write> writes = new ConcurrentHashMap<>();
    private final Object gate = new Object();
    private Handler closeHandler;
    @Override public boolean onCreate() {
        HandlerThread thread = new HandlerThread("Codex-document-commit"); thread.start();
        closeHandler = new Handler(thread.getLooper());
        return true;
    }
    private Path root() throws IOException { return CodexStoragePaths.codexHome(getContext()); }
    private String epoch() throws IOException {
        synchronized (gate) {
            Path root = root();
            BasicFileAttributes state = Files.readAttributes(root, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            String identity = root + ":" + state.fileKey();
            android.content.SharedPreferences prefs = getContext().getSharedPreferences("document-root", 0);
            if (!identity.equals(prefs.getString("identity", ""))) {
                if (!prefs.edit().putString("identity", identity).putString("epoch", UUID.randomUUID().toString()).commit())
                    throw new IOException("无法保存目录授权标识");
            }
            return prefs.getString("epoch", "");
        }
    }
    private String id(Path path) throws IOException {
        String relative = root().relativize(path).toString();
        return "codex:" + epoch() + ":" + Base64.encodeToString(relative.getBytes(StandardCharsets.UTF_8), Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING);
    }
    private Path path(String id) throws IOException {
        String[] parts = id.split(":", -1);
        if (parts.length != 3 || !parts[0].equals("codex") || !parts[1].equals(epoch())) throw new IOException("目录授权已失效，请重新选择 .codex");
        String relative;
        try { relative = new String(Base64.decode(parts[2], Base64.URL_SAFE | Base64.NO_WRAP | Base64.NO_PADDING), StandardCharsets.UTF_8); }
        catch (IllegalArgumentException bad) { throw new IOException("无效文档标识"); }
        Path root = root(), current = root;
        if (relative.isEmpty()) return root;
        for (String name : relative.split("/", -1)) {
            validateName(name); current = current.resolve(name);
            if (Files.isSymbolicLink(current)) throw new IOException("不通过目录授权展开符号链接");
        }
        if (!current.normalize().startsWith(root)) throw new IOException("文档超出授权目录");
        return current;
    }
    private static void validateName(String name) throws IOException {
        if (name.isEmpty() || name.equals(".") || name.equals("..") || name.indexOf('/') >= 0 || name.indexOf('\\') >= 0 || name.indexOf('\0') >= 0
                || name.startsWith(".codex-saf-")) throw new IOException("无效文档名称");
    }
    private static FileNotFoundException failure(Exception error) {
        FileNotFoundException result = new FileNotFoundException(error.getMessage()); result.initCause(error); return result;
    }
    private void await(Path path) throws IOException {
        Write write = writes.get(path);
        if (write == null) return;
        try {
            if (!write.done.await(15, TimeUnit.SECONDS)) throw new IOException("文件仍在写入，请稍后重试");
        } catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new IOException("文档操作已取消"); }
        writes.remove(path, write);
        if (write.error != null) throw new IOException("文件未提交：" + write.error.getMessage(), write.error);
    }
    @Override public Cursor queryRoots(String[] projection) {
        MatrixCursor cursor = new MatrixCursor(projection == null ? ROOT_COLUMNS : projection);
        try {
            String id = id(root());
            MatrixCursor.RowBuilder row = cursor.newRow();
            for (String column : cursor.getColumnNames()) {
                switch (column) {
                    case Root.COLUMN_ROOT_ID: row.add(column, "codex-" + epoch()); break;
                    case Root.COLUMN_DOCUMENT_ID: row.add(column, id); break;
                    case Root.COLUMN_TITLE: row.add(column, "Antigravity"); break;
                    case Root.COLUMN_SUMMARY: row.add(column, ".gemini 配置目录 · 含 mcp_config.json、skills 与 rules"); break;
                    case Root.COLUMN_FLAGS: row.add(column, Root.FLAG_SUPPORTS_CREATE | Root.FLAG_SUPPORTS_IS_CHILD); break;
                    case Root.COLUMN_MIME_TYPES: row.add(column, "*/*"); break;
                    case Root.COLUMN_ICON: row.add(column, R.drawable.codex_icon); break;
                }
            }
        } catch (IOException unavailable) { cursor.setExtras(unavailable(unavailable.getMessage())); }
        return cursor;
    }
    private static android.os.Bundle unavailable(String message) {
        android.os.Bundle extras = new android.os.Bundle(); extras.putString(android.provider.DocumentsContract.EXTRA_ERROR, message); return extras;
    }
    private void document(MatrixCursor cursor, Path path) throws IOException {
        BasicFileAttributes state = Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        if (!state.isDirectory() && !state.isRegularFile()) return;
        int flags = state.isDirectory() ? Document.FLAG_DIR_SUPPORTS_CREATE : Document.FLAG_SUPPORTS_WRITE | Document.FLAG_SUPPORTS_DELETE;
        if (state.isDirectory() && !path.equals(root())) {
            try (var children = Files.list(path)) { if (!children.findAny().isPresent()) flags |= Document.FLAG_SUPPORTS_DELETE; }
        }
        MatrixCursor.RowBuilder row = cursor.newRow();
        for (String column : cursor.getColumnNames()) {
            switch (column) {
                case Document.COLUMN_DOCUMENT_ID: row.add(column, id(path)); break;
                case Document.COLUMN_DISPLAY_NAME: row.add(column, path.equals(root()) ? ".gemini" : path.getFileName().toString()); break;
                case Document.COLUMN_MIME_TYPE: row.add(column, state.isDirectory() ? Document.MIME_TYPE_DIR : mime(path)); break;
                case Document.COLUMN_FLAGS: row.add(column, flags); break;
                case Document.COLUMN_SIZE: row.add(column, state.isDirectory() ? 0 : state.size()); break;
                case Document.COLUMN_LAST_MODIFIED: row.add(column, state.lastModifiedTime().toMillis()); break;
            }
        }
    }
    private static String mime(Path path) {
        String name = path.getFileName().toString();
        return name.endsWith(".toml") ? "application/toml" : name.endsWith(".json") ? "application/json" : name.endsWith(".md") ? "text/markdown" : "application/octet-stream";
    }
    @Override public Cursor queryDocument(String documentId, String[] projection) throws FileNotFoundException {
        MatrixCursor cursor = new MatrixCursor(projection == null ? DOCUMENT_COLUMNS : projection);
        try { Path path = path(documentId); await(path); document(cursor, path); return cursor; }
        catch (Exception error) { throw failure(error); }
    }
    @Override public Cursor queryChildDocuments(String parentId, String[] projection, String sortOrder) throws FileNotFoundException {
        MatrixCursor cursor = new MatrixCursor(projection == null ? DOCUMENT_COLUMNS : projection);
        try (var children = Files.newDirectoryStream(path(parentId))) {
            for (Path child : children) {
                if (child.getFileName().toString().startsWith(".codex-saf-") || Files.isSymbolicLink(child)) continue;
                document(cursor, child);
            }
            return cursor;
        } catch (Exception error) { throw failure(error); }
    }
    @Override public boolean isChildDocument(String parentId, String documentId) {
        try { Path parent = path(parentId), child = path(documentId); return !child.equals(parent) && child.startsWith(parent); }
        catch (IOException error) { return false; }
    }
    @Override public String createDocument(String parentId, String mime, String name) throws FileNotFoundException {
        try {
            validateName(name);
            synchronized (gate) {
                Path parent = path(parentId), child = parent.resolve(name);
                if (Document.MIME_TYPE_DIR.equals(mime)) Files.createDirectory(child);
                else Files.createFile(child);
                Os.chmod(child.toString(), Document.MIME_TYPE_DIR.equals(mime) ? 0700 : 0600);
                return id(child);
            }
        } catch (Exception error) { throw failure(error); }
    }
    @Override public void deleteDocument(String documentId) throws FileNotFoundException {
        try {
            Path path = path(documentId); await(path);
            synchronized (gate) {
                if (path.equals(root())) throw new IOException("不能删除授权根目录");
                Files.delete(path); // Directories must be empty; never follows guest links.
            }
        } catch (Exception error) { throw failure(error); }
    }
    @Override public ParcelFileDescriptor openDocument(String documentId, String mode, CancellationSignal signal) throws FileNotFoundException {
        try {
            if (signal != null) signal.throwIfCanceled();
            Path path = path(documentId); await(path);
            synchronized (gate) {
                path = path(documentId);
                if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException("不是普通文件");
                int flags = ParcelFileDescriptor.parseMode(mode);
                if (mode.equals("r")) {
                    java.io.FileDescriptor fd = Os.open(path.toString(), OsConstants.O_RDONLY | OsConstants.O_NOFOLLOW, 0);
                    try { return ParcelFileDescriptor.dup(fd); } finally { Os.close(fd); }
                }
                if (writes.containsKey(path)) throw new IOException("文件正在写入");
                CodexDocumentWrite transaction = new CodexDocumentWrite(path, mode.contains("t") || mode.equals("w"));
                Path temp = transaction.temporary;
                Write write = new Write(path, temp, transaction, Os.stat(path.toString()).st_mode & 0777);
                try {
                    Os.chmod(temp.toString(), 0600);
                    writes.put(path, write);
                    return ParcelFileDescriptor.open(temp.toFile(), flags, closeHandler, error -> commit(write, error));
                } catch (Exception error) { writes.remove(path, write); Files.deleteIfExists(temp); throw error; }
            }
        } catch (Exception error) { throw failure(error); }
    }
    private void commit(Write write, IOException closeError) {
        try {
            synchronized (gate) {
                if (closeError != null) throw closeError;
                // Revalidate the tree after a possibly long external edit.
                if (!path(id(write.path)).equals(write.path)) throw new IOException("目录身份发生变化");
                Os.chmod(write.temp.toString(), write.mode);
                write.transaction.commit();
                java.io.FileDescriptor dir = Os.open(write.path.getParent().toString(), OsConstants.O_RDONLY | OsConstants.O_NOFOLLOW, 0);
                try {
                    if (!OsConstants.S_ISDIR(Os.fstat(dir).st_mode)) throw new IOException("提交目录身份发生变化");
                    Os.fsync(dir);
                } finally { Os.close(dir); }
                getContext().getContentResolver().notifyChange(android.provider.DocumentsContract.buildDocumentUri(getContext().getPackageName() + ".documents", id(write.path)), null);
            }
        } catch (Exception error) { write.error = error; }
        finally {
            try { Files.deleteIfExists(write.temp); } catch (IOException ignored) {}
            write.done.countDown();
        }
    }
    private static final class Write {
        final Path path, temp;
        final CodexDocumentWrite transaction;
        final int mode;
        final CountDownLatch done = new CountDownLatch(1);
        volatile Exception error;
        Write(Path path, Path temp, CodexDocumentWrite transaction, int mode) { this.path = path; this.temp = temp; this.transaction = transaction; this.mode = mode; }
    }
}
