package com.ai.codex;

import android.content.Context;
import com.ai.codex.install.GuestIdentity;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;

/** Resolves the installer-owned publication pointer and Antigravity's .gemini config tree. */
public final class CodexStoragePaths {
    private CodexStoragePaths() {}
    public static Path guestRoot(Context context) throws IOException {
        Path files = context.getFilesDir().toPath().toRealPath();
        Path root = files.resolve("debian").toRealPath();
        if (!root.startsWith(files) || root.equals(files) || !Files.isDirectory(root))
            throw new IOException("Linux 运行环境尚未初始化或目录不可用");
        return root;
    }
    public static Path guestHome(Context context) throws IOException {
        Path root = guestRoot(context);
        return root.resolve(GuestIdentity.load(root).home.substring(1));
    }
    public static Path codexHome(Context context) throws IOException {
        Path home = guestHome(context).resolve(".gemini");
        if (!Files.exists(home, LinkOption.NOFOLLOW_LINKS)) {
            Files.createDirectories(home);
        }
        if (!Files.isDirectory(home, LinkOption.NOFOLLOW_LINKS))
            throw new IOException("请先启动 Antigravity，完成 .gemini 目录初始化");
        return home.toRealPath();
    }
}
