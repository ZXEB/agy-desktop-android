package com.ai.codex;

import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.Objects;

/** The same staged filesystem transaction is exercised by Linux host tests. */
public final class CodexDocumentWrite {
    public final Path target, temporary;
    private final BasicFileAttributes before;
    public CodexDocumentWrite(Path target, boolean truncate) throws IOException {
        this.target = target;
        before = Files.readAttributes(target, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        if (!before.isRegularFile()) throw new IOException("不是普通文件");
        temporary = Files.createTempFile(target.getParent(), ".codex-saf-", ".tmp");
        try { if (!truncate) Files.copy(target, temporary, StandardCopyOption.REPLACE_EXISTING); }
        catch (IOException error) { Files.deleteIfExists(temporary); throw error; }
    }
    public void commit() throws IOException {
        BasicFileAttributes current = Files.readAttributes(target, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        if (!current.isRegularFile() || !Objects.equals(current.fileKey(), before.fileKey()) || current.size() != before.size()
                || !current.lastModifiedTime().equals(before.lastModifiedTime())) throw new IOException("原文件已被其他进程修改");
        try (FileChannel channel = FileChannel.open(temporary, StandardOpenOption.WRITE)) { channel.force(true); }
        Files.move(temporary, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    }
    public void abort() throws IOException { Files.deleteIfExists(temporary); }
}
