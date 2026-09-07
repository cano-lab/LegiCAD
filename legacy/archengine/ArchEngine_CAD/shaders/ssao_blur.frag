#version 450

layout(location = 0) in vec2 fragTexCoord;
layout(location = 0) out float outOcclusion;

layout(set = 0, binding = 0) uniform sampler2D ssaoTexture;
layout(set = 0, binding = 1) uniform sampler2D depthTexture;

// Bilateral blur parameters
layout(push_constant) uniform BlurParams {
    vec2 direction;  // (1,0) for horizontal, (0,1) for vertical
    float depthThreshold;
    float _padding;
} params;

void main() {
    vec2 texelSize = 1.0 / textureSize(ssaoTexture, 0);

    float centerDepth = texture(depthTexture, fragTexCoord).r;
    float centerAO = texture(ssaoTexture, fragTexCoord).r;

    float result = centerAO;
    float totalWeight = 1.0;

    // 4-tap bilateral blur
    const float offsets[4] = float[](1.0, 2.0, 3.0, 4.0);
    const float weights[4] = float[](0.324, 0.232, 0.0855, 0.0128);

    for (int i = 0; i < 4; i++) {
        vec2 offset = params.direction * texelSize * offsets[i];

        // Positive direction
        vec2 uvPos = fragTexCoord + offset;
        float depthPos = texture(depthTexture, uvPos).r;
        float aoPos = texture(ssaoTexture, uvPos).r;

        // Depth-aware weight (bilateral filter)
        float depthDiff = abs(centerDepth - depthPos);
        float depthWeight = exp(-depthDiff * depthDiff / (params.depthThreshold * params.depthThreshold));
        float weight = weights[i] * depthWeight;

        result += aoPos * weight;
        totalWeight += weight;

        // Negative direction
        vec2 uvNeg = fragTexCoord - offset;
        float depthNeg = texture(depthTexture, uvNeg).r;
        float aoNeg = texture(ssaoTexture, uvNeg).r;

        depthDiff = abs(centerDepth - depthNeg);
        depthWeight = exp(-depthDiff * depthDiff / (params.depthThreshold * params.depthThreshold));
        weight = weights[i] * depthWeight;

        result += aoNeg * weight;
        totalWeight += weight;
    }

    outOcclusion = result / totalWeight;
}
