package com.ai.codex;

/** Keeps a pending first launch from repeatedly opening settings or download prompts. */
public final class EnvironmentLaunchGate {
    public enum State { READY, ACCESS_REQUIRED, PACKAGE_REQUIRED }
    private State prompted;

    public static State evaluate(boolean needsInstall, boolean downloadsAccess, boolean packagePresent) {
        if (!needsInstall) return State.READY;
        if (!downloadsAccess) return State.ACCESS_REQUIRED;
        return packagePresent ? State.READY : State.PACKAGE_REQUIRED;
    }

    public boolean shouldPrompt(State state) {
        return state != State.READY && state != prompted;
    }

    public void presented(State state) { prompted = state; }
    public void retry() { prompted = null; }
}
