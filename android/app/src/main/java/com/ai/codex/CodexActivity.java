package com.ai.codex;

import android.app.ActivityOptions;
import android.app.KeyguardManager;
import android.content.Intent;
import android.content.IntentSender;
import android.content.res.Configuration;
import android.net.Uri;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.util.Log;
import android.view.View;
import android.view.Display;
import android.view.WindowManager;
import com.termux.x11.DisplayRefreshRate;
import android.widget.Toast;
import com.termux.x11.CodexRuntimeService;
import com.termux.x11.CodexDisplayActivity;

/** Display host with a peer-credential checked IME endpoint. No text crosses this bridge. */
public final class CodexActivity extends CodexDisplayActivity {
    private static final String ENVIRONMENT_RELEASES_URL =
            "https://github.com/ZXEB/agy-desktop-android/releases/latest";
    private static volatile boolean visible;
    private static volatile boolean windowFocused;
    private static volatile CodexActivity current;
    public static boolean isVisible() { return visible && windowFocused; }
    /** One nonblocking input frame on the Android main looper. No text is logged. */
    public static int sendLinuxInput(int code, boolean unicode, boolean down) {
        CodexActivity activity = current;
        if (activity == null || !isVisible() || !activity.desktopDisplayAllowed
                || !activity.canHandleDisplayTransition() || !activity.getLorieView().connected()) return -1;
        return activity.getLorieView().sendInputEventChecked(code, unicode, down);
    }
    /** Release an already issued key even when Android took focus in the meantime. */
    public static int releaseLinuxKey(int key) {
        CodexActivity activity = current;
        if (activity == null || !activity.getLorieView().connected()) return -1;
        return activity.getLorieView().sendInputEventChecked(key, false, false);
    }
    private volatile boolean resumed;
    private final CodexImeBridge imeBridge = CodexImeBridge.get();
    private final CodexUrlBridge urlBridge = CodexUrlBridge.get();
    private CodexPostureController posture;
    private boolean desktopDisplayAllowed;
    private boolean redirecting;
    private String pendingConnectorCallback;
    private final EnvironmentLaunchGate environmentLaunchGate = new EnvironmentLaunchGate();
    private androidx.appcompat.app.AlertDialog environmentDialog;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        current = this;
        getOnBackPressedDispatcher().addCallback(this, new androidx.activity.OnBackPressedCallback(true) {
            @Override public void handleOnBackPressed() { showExitOptions(); }
        });
        CodexAndroidBridge.start(this);
        com.ai.codex.phone.PhoneControl.get(this).startHost();
        acceptConnectorCallback(getIntent());
        // The desktop client enforces a minimum window height. Keep its canvas
        // and let LorieView follow the input cursor above the Android keyboard.
        prefs.Reseed.put(false);
        // Background computation uses the service's partial CPU wake lock.
        // The display must follow Android's normal idle/screen-off policy.
        prefs.screenIdleTimeout.put("system");
        if (!getPreferences(MODE_PRIVATE).getBoolean("configured", false)) {
            prefs.fullscreen.put(true);
            // Let X11 follow the actual phone viewport in both orientations.
            // Desktop UI scaling is configured separately in the runtime.
            prefs.displayResolutionMode.put("native");
            prefs.showAdditionalKbd.put(false);
            prefs.touchMode.put("3");
            getPreferences(MODE_PRIVATE).edit().putBoolean("configured", true).apply();
        }
        imeBridge.attach(this);
        urlBridge.attach(this);
        // Gate the containing view, since the X11 view manages its own visibility
        // when the server reconnects. Apply the device profile before showing it.
        findViewById(android.R.id.content).setVisibility(View.INVISIBLE);
        if (getResources().getBoolean(R.bool.codex_require_inner_display)) {
            posture = new CodexPostureController(this, this::onPostureChanged);
            posture.start();
        } else {
            refreshDisplayPolicy();
        }
    }
    @Override public void onResume() {
        super.onResume();
        preferDisplayRefresh(true);
        // Let Android's current display policy supply high-refresh VSYNC, with no 60 Hz vote.
        if (android.os.Build.VERSION.SDK_INT >= 35)
            getWindow().getDecorView().setRequestedFrameRate(View.REQUESTED_FRAME_RATE_CATEGORY_HIGH);
        resumed = true;
        com.ai.codex.phone.PhoneControl.get(this).getPrompts().attachActivity(this, this);
        visible = true;
        imeBridge.resume(this);
        urlBridge.resume(this);
        refreshDisplayPolicy();
    }
    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        acceptConnectorCallback(intent);
        requestRuntimeLaunch();
        refreshDisplayPolicy();
    }
    @Override public void onPause() {
        preferDisplayRefresh(false);
        if (android.os.Build.VERSION.SDK_INT >= 35)
            getWindow().getDecorView().setRequestedFrameRate(View.REQUESTED_FRAME_RATE_CATEGORY_DEFAULT);
        resumed = false;
        visible = false;
        imeBridge.pause(this);
        urlBridge.pause(this);
        super.onPause();
    }
    @Override public void onConfigurationChanged(Configuration configuration) {
        super.onConfigurationChanged(configuration);
        refreshDisplayPolicy();
    }
    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        windowFocused = hasFocus;
        // A posture notification may arrive while the screen is turning off or
        // the keyguard owns the window. Reconsider it when this Activity really
        // becomes interactive; never wake/unlock the device to finish a handoff.
        if (hasFocus) refreshDisplayPolicy();
    }
    private void refreshDisplayPolicy() {
        if (resumed) preferDisplayRefresh(true);
        if (posture != null) posture.refreshDisplay();
        onPostureChanged(posture == null ? CodexPostureController.State.UNAVAILABLE : posture.getState());
    }
    private void preferDisplayRefresh(boolean active) {
        WindowManager.LayoutParams attributes = getWindow().getAttributes();
        int preferred = 0;
        Display display = getDisplay();
        if (active && display != null && display.isValid()) {
            Display.Mode currentMode = display.getMode();
            Display.Mode[] modes = display.getSupportedModes();
            int[] widths = new int[modes.length], heights = new int[modes.length];
            float[] rates = new float[modes.length];
            for (int i = 0; i < modes.length; i++) {
                widths[i] = modes[i].getPhysicalWidth(); heights[i] = modes[i].getPhysicalHeight();
                rates[i] = modes[i].getRefreshRate();
            }
            int index = DisplayRefreshRate.fastestAtSize(currentMode.getPhysicalWidth(), currentMode.getPhysicalHeight(), widths, heights, rates);
            if (index >= 0) preferred = modes[index].getModeId();
        }
        // Release on Activity pause, not IME/window focus changes.
        if (attributes.preferredDisplayModeId != preferred || attributes.preferredRefreshRate != 0) {
            attributes.preferredDisplayModeId = preferred;
            attributes.preferredRefreshRate = 0;
            getWindow().setAttributes(attributes);
        }
    }
    private boolean canHandleDisplayTransition() {
        PowerManager power = getSystemService(PowerManager.class);
        KeyguardManager keyguard = getSystemService(KeyguardManager.class);
        return resumed && hasWindowFocus() && power != null && power.isInteractive()
                && keyguard != null && !keyguard.isKeyguardLocked() && !keyguard.isDeviceLocked();
    }
    private boolean isPostureBypassed() {
        return getIntent() != null && getIntent().getBooleanExtra("com.ai.codex.BYPASS_POSTURE", false);
    }
    private void acceptConnectorCallback(Intent intent) {
        if (intent == null || !Intent.ACTION_VIEW.equals(intent.getAction()) || intent.getData() == null) return;
        try {
            String callback = CodexConnectorCallback.validate(intent.getDataString());
            if (pendingConnectorCallback != null && !pendingConnectorCallback.equals(callback)) {
                intent.setData(android.net.Uri.parse(pendingConnectorCallback));
                Toast.makeText(this, "已有一个登录回调正在等待处理，请在完成后继续。", Toast.LENGTH_LONG).show();
                return;
            }
            pendingConnectorCallback = callback;
        } catch (IllegalArgumentException error) {
            intent.setData(pendingConnectorCallback == null ? null : android.net.Uri.parse(pendingConnectorCallback));
            Log.w("Codex-Connector", "Rejected invalid connector callback");
            Toast.makeText(this, "Codex 无法识别此登录回调。", Toast.LENGTH_LONG).show();
        }
    }
    private void startRuntimeWithPendingActions() {
        if (!hasPendingRuntimeLaunch()) return;
        boolean sendCallback = pendingConnectorCallback != null && canHandleDisplayTransition();
        if (pendingConnectorCallback != null && !sendCallback) return;
        if (!environmentReadyForLaunch()) return;
        Intent start = new Intent(this, CodexRuntimeService.class).setAction(CodexRuntimeService.ACTION_START);
        String thread = getIntent().getStringExtra(CodexRuntimeService.EXTRA_THREAD);
        if (thread != null) start.putExtra(CodexRuntimeService.EXTRA_THREAD, thread);
        if (sendCallback) start.putExtra(CodexRuntimeService.EXTRA_CONNECTOR_CALLBACK, pendingConnectorCallback);
        try {
            startForegroundService(start);
            runtimeLaunchDispatched();
            getIntent().removeExtra(CodexRuntimeService.EXTRA_THREAD);
            if (sendCallback) {
                pendingConnectorCallback = null;
                getIntent().setData(null); // Activity recreation must not resubmit the callback.
            }
        } catch (RuntimeException error) {
            if (!sendCallback) throw error;
            // Android exceptions may include Intent extras; log no exception payload.
            Log.e("Codex-Connector", "Could not start the runtime for the pending action");
            Toast.makeText(this, "Codex 未能接收登录回调，请在启动后重试。", Toast.LENGTH_LONG).show();
        }
    }
    @Override protected void onRuntimeRetryRequested() {
        environmentLaunchGate.retry();
        refreshDisplayPolicy();
    }
    @Override protected void onRuntimePrerequisiteRequested() {
        environmentLaunchGate.retry();
        refreshDisplayPolicy();
    }
    private boolean environmentReadyForLaunch() {
        boolean needsInstall = com.ai.codex.install.EnvironmentPackageSource.needsInstall(this);
        boolean externalPackageRequired = needsInstall;
        if (needsInstall) {
            try {
                String[] assets = getAssets().list("phone-runtime");
                externalPackageRequired = assets == null
                        || !java.util.Arrays.asList(assets).contains("agy-phone-rootfs.tgz");
            } catch (java.io.IOException unavailable) {
                // Let the normal source validator report any asset read error.
            }
        }
        boolean access = !externalPackageRequired || com.ai.codex.install.EnvironmentPackageSource.hasDownloadsAccess();
        boolean present = access && (!externalPackageRequired
                || java.nio.file.Files.isRegularFile(
                        com.ai.codex.install.EnvironmentPackageSource.archiveFile().toPath(),
                        java.nio.file.LinkOption.NOFOLLOW_LINKS));
        EnvironmentLaunchGate.State state = EnvironmentLaunchGate.evaluate(externalPackageRequired, access, present);
        if (state == EnvironmentLaunchGate.State.READY) {
            if (environmentDialog != null) { environmentDialog.dismiss(); environmentDialog = null; }
            clearRuntimePrerequisite();
            return true;
        }
        String title = state == EnvironmentLaunchGate.State.ACCESS_REQUIRED
                ? "允许读取 Download 环境包" : "请先下载运行环境";
        String detail = state == EnvironmentLaunchGate.State.ACCESS_REQUIRED
                ? "首次安装需要读取 Download 目录中的环境包。请在系统设置中允许所有文件访问；授权后会自动检查，无需选择文件。"
                : "请从发布页面下载 agy-phone-rootfs.tar.gz，保存到手机内部存储的 Download 目录。无需解压，请保留原文件名。下载完成后返回 Antigravity，应用会自动检查，也可以点击重新检查。";
        showRuntimePrerequisite(title, detail);
        if (!environmentLaunchGate.shouldPrompt(state) || environmentDialog != null) return false;
        environmentLaunchGate.presented(state);
        androidx.appcompat.app.AlertDialog.Builder dialog = new androidx.appcompat.app.AlertDialog.Builder(this)
                .setTitle(title).setMessage(detail).setNegativeButton("稍后", null);
        if (state == EnvironmentLaunchGate.State.ACCESS_REQUIRED) {
            dialog.setPositiveButton("去授权", (view, which) -> openEnvironmentAccessSettings());
        } else {
            dialog.setPositiveButton("前往下载", (view, which) -> {
                try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(ENVIRONMENT_RELEASES_URL))); }
                catch (android.content.ActivityNotFoundException unavailable) {
                    Toast.makeText(this, "未找到浏览器，请从项目发布页面下载环境包到 Download 目录。", Toast.LENGTH_LONG).show();
                }
            });
            dialog.setNeutralButton("重新检查", (view, which) -> getWindow().getDecorView().post(() -> {
                environmentLaunchGate.retry();
                refreshDisplayPolicy();
            }));
        }
        environmentDialog = dialog.create();
        environmentDialog.setOnDismissListener(view -> environmentDialog = null);
        environmentDialog.show();
        return false;
    }
    private void openEnvironmentAccessSettings() {
        try {
            startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                    .setData(Uri.parse("package:" + getPackageName())));
        } catch (android.content.ActivityNotFoundException unavailable) {
            try { startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)); }
            catch (android.content.ActivityNotFoundException missing) {
                Toast.makeText(this, "请在系统设置中允许 Codex 的所有文件访问权限，然后返回重试。", Toast.LENGTH_LONG).show();
            }
        }
    }
    @Override public void onBackPressed() { getOnBackPressedDispatcher().onBackPressed(); }
    @Override protected void onRuntimeStopped() { com.ai.codex.phone.PhoneControl.get(this).onEngineStopped(); CodexDeviceFeatures.turnOffTorch(this); finishAndRemoveTask(); }
    private void showExitOptions() {
        android.view.WindowInsets insets = getWindow().getDecorView().getRootWindowInsets();
        if (insets != null && insets.isVisible(android.view.WindowInsets.Type.ime())) {
            getLorieView().setKeyboardVisible(false);
            return;
        }
        new androidx.appcompat.app.AlertDialog.Builder(this).setTitle("退出 Codex")
                .setMessage("安全退出会结束正在运行的任务并清理临时文件。仅返回后台会继续运行。")
                .setPositiveButton("安全退出", (dialog, which) -> startService(
                        new Intent(this, CodexRuntimeService.class).setAction(CodexRuntimeService.ACTION_STOP)))
                .setNeutralButton("返回后台", (dialog, which) -> moveTaskToBack(true))
                .setNegativeButton("取消", null).show();
    }
    private boolean isDesktopEnvironment() {
        Configuration config = getResources().getConfiguration();
        try {
            java.lang.reflect.Field field = config.getClass().getField("semDesktopModeEnabled");
            if (field.getInt(config) == 1) return true;
        } catch (Throwable ignored) { }
        android.app.UiModeManager uiModeManager = getSystemService(android.app.UiModeManager.class);
        if (uiModeManager != null && uiModeManager.getCurrentModeType() == Configuration.UI_MODE_TYPE_DESK) {
            return true;
        }
        return false;
    }
    private void onPostureChanged(CodexPostureController.State state) {
        if (isDestroyed() || isFinishing()) return;
        boolean bypassed = isPostureBypassed() || isDesktopEnvironment();
        desktopDisplayAllowed = !getResources().getBoolean(R.bool.codex_require_inner_display)
                || bypassed || state == CodexPostureController.State.INNER;
        findViewById(android.R.id.content).setVisibility(desktopDisplayAllowed ? View.VISIBLE : View.INVISIBLE);
        if (desktopDisplayAllowed) {
            if (canHandleDisplayTransition()) {
                startRuntimeWithPendingActions();
            }
            return;
        }
        getLorieView().setKeyboardVisible(false);
        if (!canHandleDisplayTransition() || state == CodexPostureController.State.WAITING || redirecting) return;
        // A return from Android's browser also reaches the Linux client if the
        // phone was folded during authorization, before display handoff finishes.
        if (pendingConnectorCallback != null) startRuntimeWithPendingActions();
        redirecting = true;
        if (state == CodexPostureController.State.UNAVAILABLE) {
            Toast.makeText(this, "无法检测折叠屏内屏。", Toast.LENGTH_LONG).show();
        }
        try {
            if (android.os.Build.VERSION.SDK_INT >= 33) {
                // Public API that is not filtered by package visibility. The
                // package was verified on the device; no exported class is fixed.
                IntentSender launch = getPackageManager().getLaunchIntentSenderForPackage("com.openai.chatgpt");
                Bundle options = null;
                if (android.os.Build.VERSION.SDK_INT >= 36) {
                    // Delegate only the authority this visible Activity already
                    // holds, as required by current PendingIntent launch rules.
                    options = ActivityOptions.makeBasic().setPendingIntentBackgroundActivityStartMode(
                            ActivityOptions.MODE_BACKGROUND_ACTIVITY_START_ALLOW_IF_VISIBLE).toBundle();
                }
                startIntentSender(launch, null, 0, 0, 0, options);
            } else {
                Intent launch = getPackageManager().getLaunchIntentForPackage("com.openai.chatgpt");
                if (launch != null) startActivity(launch);
            }
        } catch (IntentSender.SendIntentException | RuntimeException exception) {
            Log.w("Codex-Posture", "Official Android client could not be opened", exception);
            Toast.makeText(this, "请在折叠屏内屏上打开 Codex。", Toast.LENGTH_LONG).show();
        }
        // Finish only the display Activity. The independent started foreground
        // service keeps Linux/tasks alive until the explicit notification Stop.
        finish();
    }
    @Override protected void onDestroy() {
        if (environmentDialog != null) { environmentDialog.dismiss(); environmentDialog = null; }
        if (current == this) current = null;
        resumed = false;
        if (posture != null) posture.close();
        imeBridge.detach(this);
        urlBridge.detach(this);
        super.onDestroy();
    }
    boolean applyImeVisibility(boolean show) {
        boolean allowed = !isDestroyed() && !isFinishing() && (!show || (desktopDisplayAllowed && resumed && hasWindowFocus()));
        if (allowed) getLorieView().setKeyboardVisible(show);
        return allowed;
    }
}
