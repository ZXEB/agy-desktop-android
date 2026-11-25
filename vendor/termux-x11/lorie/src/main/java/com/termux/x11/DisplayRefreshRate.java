package com.termux.x11;

/** Prefer the physical mode over the app's compatibility override, without a fixed FPS cap. */
public final class DisplayRefreshRate {
    private DisplayRefreshRate() { }
    public static float current(float modeRate, float appRate) {
        if (Float.isFinite(modeRate) && modeRate > 0) return modeRate;
        if (Float.isFinite(appRate) && appRate > 0) return appRate;
        return 0;
    }
    /** The existing native window-change protocol carries an integer Hz value. */
    public static int x11(float rate) {
        return rate > 0 && Float.isFinite(rate) ? Math.max(1, Math.round(rate)) : 0;
    }
    /** Keep resolution unchanged; let Android enforce user/power limits on this preference. */
    public static int fastestAtSize(int width, int height, int[] widths, int[] heights, float[] rates) {
        if (widths.length != heights.length || widths.length != rates.length) throw new IllegalArgumentException("Mode arrays differ");
        int selected = -1;
        float fastest = 0;
        for (int i = 0; i < rates.length; i++) {
            if (widths[i] == width && heights[i] == height && Float.isFinite(rates[i]) && rates[i] > fastest) {
                fastest = rates[i]; selected = i;
            }
        }
        return selected;
    }
}
