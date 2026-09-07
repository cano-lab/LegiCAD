#version 450

// Bloom bright pass - extracts pixels above threshold

layout(location = 0) in vec2 fragTexCoord;
layout(location = 0) out vec4 outBright;

layout(set = 0, binding = 0) uniform sampler2D hdrTexture;

layout(push_constant) uniform BloomParams {
    float threshold;
    float softThreshold;
    float intensity;
    float _padding;
} params;

void main() {
    vec3 color = texture(hdrTexture, fragTexCoord).rgb;

    // Calculate luminance
    float luminance = dot(color, vec3(0.2126, 0.7152, 0.0722));

    // Soft threshold with knee
    float soft = luminance - params.threshold + params.softThreshold;
    soft = clamp(soft, 0.0, 2.0 * params.softThreshold);
    soft = soft * soft / (4.0 * params.softThreshold + 0.00001);

    float contribution = max(soft, luminance - params.threshold);
    contribution /= max(luminance, 0.00001);

    outBright = vec4(color * contribution, 1.0);
}
