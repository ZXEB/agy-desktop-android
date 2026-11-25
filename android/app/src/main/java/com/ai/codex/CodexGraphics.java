package com.ai.codex;

import android.content.Context;
import android.util.AtomicFile;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

/** A small file is used instead of cross-process SharedPreferences caching. */
public final class CodexGraphics {
    public static final String[] MODES = {"auto", "software", "hardware"};
    public static final String[] LABELS = {"自动（推荐）", "兼容模式（软件渲染）", "加速模式（Zink / Turnip）"};
    private CodexGraphics() {}
    public static String mode(Context context) {
        try {
            String value = new String(new AtomicFile(new File(context.getFilesDir(), "graphics-mode.txt")).readFully(), StandardCharsets.UTF_8).trim();
            for (String allowed : MODES) if (allowed.equals(value)) return value;
        } catch (Exception ignored) {}
        return "auto";
    }
    public static void set(Context context, String value) throws Exception {
        if (!java.util.Arrays.asList(MODES).contains(value)) throw new IllegalArgumentException("未知图形模式");
        AtomicFile file = new AtomicFile(new File(context.getFilesDir(), "graphics-mode.txt"));
        FileOutputStream stream = null;
        try {
            stream = file.startWrite();
            stream.write((value + "\n").getBytes(StandardCharsets.UTF_8));
            file.finishWrite(stream);
        } catch (Exception error) { if (stream != null) file.failWrite(stream); throw error; }
    }
    public static int selected(Context context) {
        String value = mode(context);
        for (int i = 0; i < MODES.length; i++) if (MODES[i].equals(value)) return i;
        return 0;
    }
}
