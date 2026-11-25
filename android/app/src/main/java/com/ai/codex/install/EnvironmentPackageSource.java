package com.ai.codex.install;

import android.content.Context;
import android.os.Environment;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;

/** Fixed public Download transport; release hashes remain authenticated by the APK. */
public final class EnvironmentPackageSource {
    public static final String ARCHIVE_NAME = "agy-phone-rootfs.tar.gz";
    private EnvironmentPackageSource() {}

    public static boolean needsInstall(Context context) {
        return !Files.exists(context.getFilesDir().toPath().resolve("debian"), LinkOption.NOFOLLOW_LINKS);
    }

    public static boolean hasDownloadsAccess() { return Environment.isExternalStorageManager(); }

    public static File archiveFile() {
        return new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), ARCHIVE_NAME);
    }

    public static RootfsTransaction.ArchiveSource downloads(RootfsExtractor.Spec spec) throws IOException {
        if (!hasDownloadsAccess())
            throw new IOException("请允许所有文件访问，以自动读取 Download 目录中的运行环境包。");
        Path archive = archiveFile().toPath();
        if (!Files.isRegularFile(archive, LinkOption.NOFOLLOW_LINKS))
            throw new IOException("未找到环境包，请下载 " + ARCHIVE_NAME + " 到 Download 目录后重新检查，无需解压。");
        if (Files.size(archive) != spec.compressedBytes)
            throw new IOException("Download 中的环境包大小不匹配，可能尚未下载完成或版本不兼容，请重新下载配套环境包。");
        return () -> {
            if (!hasDownloadsAccess() || !Files.isRegularFile(archive, LinkOption.NOFOLLOW_LINKS)
                    || Files.size(archive) != spec.compressedBytes)
                throw new IOException("Download 中的环境包已变化或无法读取，请重新检查。");
            return Files.newInputStream(archive, LinkOption.NOFOLLOW_LINKS);
        };
    }
}
