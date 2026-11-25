package com.ai.codex;

import android.content.Context;
import java.util.concurrent.CompletableFuture;

/** Lightweight runtime lifecycle stub for Google Antigravity.
 * Antigravity runs directly inside the PRoot Debian ARM64 container with its
 * bundled language_server and needs no separate Shizuku/Bionic executor. */
public final class CodexExecutorRuntime {
    public static final String ACTION_PREPARE = "com.ai.agy.action.PREPARE_NATIVE_EXECUTOR";
    private final CompletableFuture<Void> closed = CompletableFuture.completedFuture(null);
    private final CompletableFuture<Throwable> failure = new CompletableFuture<>();
    private final CompletableFuture<Void> ownerDeath = new CompletableFuture<>();

    public record Endpoint(String socketPath, int peerUid, String startupManifest, String workspace,
                           String endpointRoot, String pythonRoot, String nativeRoot) {
        public boolean directNative() { return false; }
    }

    public CodexExecutorRuntime(Context context) {
        if (!(context.getPackageName() + ":runtime").equals(android.app.Application.getProcessName())) {
            throw new IllegalStateException("Runtime must be owned by CodexRuntimeService :runtime");
        }
    }

    public boolean isNativeSelected() { return false; }
    public CompletableFuture<Endpoint> prepare() { return CompletableFuture.completedFuture(null); }
    public CompletableFuture<Endpoint> prepare(String controllerHome) { return CompletableFuture.completedFuture(null); }
    public CompletableFuture<Throwable> failure() { return failure; }
    public CompletableFuture<Void> ownerDeath() { return ownerDeath; }
    public boolean retireProcessAfterOwnerDeath(Runnable exit) { return false; }
    public CompletableFuture<Void> requestStop() { return closed; }
    public void shutdownAfterCleanup(Runnable exit) {
        if (exit != null) exit.run();
    }
}
