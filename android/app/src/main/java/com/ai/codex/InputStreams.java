package com.ai.codex;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Objects;

/** Stream reads using APIs available below Android 13. The caller owns the stream. */
public final class InputStreams {
    private static final boolean PLATFORM_READS = platformReadsAvailable();

    private InputStreams() { }

    /** Read up to limit bytes, returning a shorter array only at end of stream. */
    public static byte[] readNBytes(InputStream input, int limit) throws IOException {
        if (PLATFORM_READS) return Api33.readNBytes(input, limit);
        return readNBytesCompat(input, limit);
    }

    public static byte[] readAllBytes(InputStream input) throws IOException {
        if (PLATFORM_READS) return Api33.readAllBytes(input);
        return readNBytesCompat(input, Integer.MAX_VALUE);
    }

    // Keep the fallback independently testable on the host JVM.
    static byte[] readNBytesCompat(InputStream input, int limit) throws IOException {
        Objects.requireNonNull(input, "input");
        if (limit < 0) throw new IllegalArgumentException("Negative read limit");
        int capacity = Math.min(limit, 8192);
        ByteArrayOutputStream output = new ByteArrayOutputStream(capacity);
        byte[] buffer = new byte[capacity];
        int remaining = limit;
        while (remaining > 0) {
            int count = input.read(buffer, 0, Math.min(buffer.length, remaining));
            if (count < 0) break;
            if (count == 0) {
                // A nonstandard stream may make no progress on a bulk read.
                int value = input.read();
                if (value < 0) break;
                output.write(value);
                remaining--;
            } else {
                output.write(buffer, 0, count);
                remaining -= count;
            }
        }
        return output.toByteArray();
    }

    private static boolean platformReadsAvailable() {
        // Android provides both methods from API 33. Detect their presence once
        // so this utility also remains usable by the standalone JVM installer tests.
        try {
            InputStream.class.getMethod("readNBytes", int.class);
            InputStream.class.getMethod("readAllBytes");
            return true;
        } catch (NoSuchMethodException unavailable) {
            return false;
        }
    }

    @SuppressWarnings("NewApi") // Invoked only after both platform methods were found.
    private static final class Api33 {
        static byte[] readNBytes(InputStream input, int limit) throws IOException {
            return input.readNBytes(limit);
        }

        static byte[] readAllBytes(InputStream input) throws IOException {
            return input.readAllBytes();
        }
    }
}
