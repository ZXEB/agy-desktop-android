package com.ai.codex.phone.a11y

import android.annotation.TargetApi
import android.graphics.RuntimeShader

/** One continuous GPU falloff, rather than a small stack of flat-alpha outlines. */
@TargetApi(33)
internal class EdgeGlowShader33(density: Float) {
    val shader = RuntimeShader(SOURCE)
    init { shader.setFloatUniform("density", density) }

    fun geometry(width: Int, height: Int, inset: Float, corners: List<Float>) {
        shader.setFloatUniform("resolution", width.toFloat(), height.toFloat())
        shader.setFloatUniform("edgeInset", inset)
        shader.setFloatUniform("radii", corners.toFloatArray())
    }
    fun phase(value: Float) = shader.setFloatUniform("phase", value)

    companion object {
        const val SOURCE = """
            uniform float2 resolution;
            uniform float4 radii;
            uniform float edgeInset;
            uniform float density;
            uniform float phase;
            half4 main(float2 xy) {
                float2 p = xy - resolution * 0.5;
                float r = p.x < 0.0 ? (p.y < 0.0 ? radii.x : radii.w)
                                     : (p.y < 0.0 ? radii.y : radii.z);
                float2 q = abs(p) - (resolution * 0.5 - edgeInset - r);
                float sd = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
                float d = abs(sd) / density;
                float alpha = (0.80 * exp(-0.5 * (d / 1.7) * (d / 1.7))
                             + 0.20 * exp(-0.5 * (d / 10.0) * (d / 10.0)))
                             * (1.0 - smoothstep(20.0, 25.0, d));
                float t = fract(atan(p.y, p.x) / 6.2831853 - phase) * 4.0;
                float3 cyan = float3(77.0, 216.0, 255.0) / 255.0;
                float3 blue = float3(112.0, 131.0, 255.0) / 255.0;
                float3 violet = float3(178.0, 113.0, 255.0) / 255.0;
                float3 pink = float3(245.0, 145.0, 213.0) / 255.0;
                float f = smoothstep(0.0, 1.0, fract(t));
                float3 color = t < 1.0 ? mix(cyan, blue, f)
                             : t < 2.0 ? mix(blue, violet, f)
                             : t < 3.0 ? mix(violet, pink, f) : mix(pink, cyan, f);
                // Spatially fixed, sub-byte dither avoids bands without flickering over time.
                float noise = fract(sin(dot(floor(xy), float2(12.9898, 78.233))) * 43758.5453) - 0.5;
                alpha = clamp(alpha + noise / 255.0, 0.0, 1.0);
                color = clamp(color + noise / 255.0, 0.0, 1.0);
                return half4(color * alpha, alpha);
            }
        """
    }
}
