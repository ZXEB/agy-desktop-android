package com.ai.codex;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.util.AttributeSet;
import android.view.View;
import android.view.animation.DecelerateInterpolator;

/** Quiet terminal backdrop. Only animates when a new startup snapshot arrives. */
public final class StartupLogView extends View {
    private final Paint textPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint shade = new Paint();
    private final float inset, lineHeight;
    private String snapshot = "";
    private String[] lines = new String[0];
    private ValueAnimator scroll;
    private float offset;
    private Shader centerShade, edgeShade;

    public StartupLogView(Context context, AttributeSet attributes) {
        super(context, attributes);
        float density = getResources().getDisplayMetrics().density;
        inset = 18 * density;
        textPaint.setTypeface(Typeface.MONOSPACE);
        textPaint.setTextSize(10 * getResources().getDisplayMetrics().scaledDensity);
        textPaint.setColor(Color.rgb(190, 205, 198));
        textPaint.setAlpha(62);
        lineHeight = Math.max(17 * density, textPaint.getFontSpacing() * 1.35f);
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        setFocusable(false);
    }

    public void setTranscript(String value) {
        if (value == null || value.equals(snapshot)) return;
        boolean hasPrevious = !snapshot.isEmpty();
        snapshot = value;
        lines = value.isEmpty() ? new String[0] : value.split("\n");
        int visible = Math.max(1, (int) ((getHeight() - 2 * inset) / lineHeight));
        boolean animate = hasPrevious && lines.length > visible && isShown() && ValueAnimator.areAnimatorsEnabled();
        cancelScroll();
        if (animate) {
            scroll = ValueAnimator.ofFloat(lineHeight, 0);
            scroll.setDuration(280);
            scroll.setInterpolator(new DecelerateInterpolator());
            scroll.addUpdateListener(frame -> {
                offset = (float) frame.getAnimatedValue();
                invalidate();
            });
            scroll.start();
        }
        invalidate();
    }

    @Override protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
        super.onSizeChanged(width, height, oldWidth, oldHeight);
        if (width == 0 || height == 0) return;
        centerShade = new RadialGradient(width / 2f, height / 2f,
                Math.max(1, Math.min(width * .68f, height * .58f)),
                new int[]{0x80171717, 0x7b171717, 0x00171717},
                new float[]{0, .43f, 1}, Shader.TileMode.CLAMP);
        edgeShade = new LinearGradient(0, 0, 0, height,
                new int[]{0xf0171717, 0x00171717, 0x00171717, 0xf0171717},
                new float[]{0, .09f, .89f, 1}, Shader.TileMode.CLAMP);
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.save();
        canvas.clipRect(inset, 0, getWidth() - inset, getHeight());
        int visible = Math.max(1, (int) ((getHeight() - 2 * inset) / lineHeight));
        int first = Math.max(0, lines.length - visible - 1);
        float y = inset - textPaint.ascent() + offset;
        if (lines.length > visible) y -= lineHeight;
        for (int index = first; index < lines.length; index++, y += lineHeight) {
            canvas.drawText(lines[index], inset, y, textPaint);
        }
        canvas.restore();
        if (centerShade != null) {
            shade.setShader(centerShade);
            canvas.drawRect(0, 0, getWidth(), getHeight(), shade);
            shade.setShader(edgeShade);
            canvas.drawRect(0, 0, getWidth(), getHeight(), shade);
        }
    }

    private void cancelScroll() {
        if (scroll != null) { scroll.cancel(); scroll = null; }
        offset = 0;
    }

    @Override protected void onVisibilityChanged(View changedView, int visibility) {
        super.onVisibilityChanged(changedView, visibility);
        if (visibility != VISIBLE) cancelScroll();
    }

    @Override protected void onWindowVisibilityChanged(int visibility) {
        super.onWindowVisibilityChanged(visibility);
        if (visibility != VISIBLE) cancelScroll();
    }

    @Override protected void onDetachedFromWindow() {
        cancelScroll();
        super.onDetachedFromWindow();
    }
}
