#version 450

// Bloom bright pass - extracts pixels above threshold

layout(location = 0) in vec2 fragTexCoord;
layout(location = 0) out vec4 outBright;

layout(set = 0, binding = 0) uniform sampler2D hdrTexture;

layout(push_constant) uniform BloomParams {
    float threshold;
    float softThreshold;
    float exposure;
    float _padding;
} params;

void main() {
    vec3 color = texture(hdrTexture, fragTexCoord).rgb;

    // Guard against NaN/Inf values that can corrupt bloom
    if (any(isnan(color)) || any(isinf(color))) {
        outBright = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    // Clamp to reasonable HDR range to prevent extreme values
    color = clamp(color, 0.0, 100.0);

    // Calculate luminance in exposure space so threshold responds to scene brightness
    float luminance = dot(color * params.exposure, vec3(0.2126, 0.7152, 0.0722));

    // Soft threshold with knee
    float soft = luminance - params.threshold + params.softThreshold;
    soft = clamp(soft, 0.0, 2.0 * params.softThreshold);
    soft = soft * soft / (4.0 * params.softThreshold + 0.00001);

    float contribution = max(soft, luminance - params.threshold);
    contribution /= max(luminance, 0.00001);

    vec3 result = color * contribution;

    // Final clamp to ensure no bad values escape
    result = clamp(result, 0.0, 100.0);

    outBright = vec4(result, 1.0);
}
