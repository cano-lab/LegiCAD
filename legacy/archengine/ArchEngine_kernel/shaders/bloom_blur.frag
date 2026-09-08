#version 450

// Gaussian blur for bloom (9-tap)

layout(location = 0) in vec2 fragTexCoord;
layout(location = 0) out vec4 outColor;

layout(set = 0, binding = 0) uniform sampler2D inputTexture;

layout(push_constant) uniform BlurParams {
    vec2 direction;  // (1,0) for horizontal, (0,1) for vertical
    vec2 texelSize;
} params;

// 9-tap Gaussian weights (sigma ~1.5)
const float weights[5] = float[](0.227027, 0.1945946, 0.1216216, 0.054054, 0.016216);

void main() {
    vec3 result = texture(inputTexture, fragTexCoord).rgb * weights[0];

    for (int i = 1; i < 5; i++) {
        vec2 offset = params.direction * params.texelSize * float(i);
        result += texture(inputTexture, fragTexCoord + offset).rgb * weights[i];
        result += texture(inputTexture, fragTexCoord - offset).rgb * weights[i];
    }

    // Guard against NaN/Inf propagation
    if (any(isnan(result)) || any(isinf(result))) {
        result = vec3(0.0);
    }

    outColor = vec4(clamp(result, 0.0, 100.0), 1.0);
}
