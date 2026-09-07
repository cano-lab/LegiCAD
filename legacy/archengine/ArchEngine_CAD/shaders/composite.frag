#version 450

// Final composite pass: combines HDR scene + SSAO + bloom, applies tonemapping

layout(location = 0) in vec2 fragTexCoord;
layout(location = 0) out vec4 outColor;

layout(set = 0, binding = 0) uniform sampler2D hdrScene;
layout(set = 0, binding = 1) uniform sampler2D ssaoTexture;
layout(set = 0, binding = 2) uniform sampler2D bloomTexture;

layout(push_constant) uniform CompositeParams {
    float bloomIntensity;
    float exposure;
    float ssaoIntensity;
    uint enableSSAO;
    uint enableBloom;
    uint tonemapMode;  // 0=Reinhard, 1=ACES, 2=Uncharted2
    vec2 _padding;
} params;

// ACES Filmic Tonemapping
// https://knarkowicz.wordpress.com/2016/01/06/aces-filmic-tone-mapping-curve/
vec3 ACESFilm(vec3 x) {
    float a = 2.51;
    float b = 0.03;
    float c = 2.43;
    float d = 0.59;
    float e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

// Uncharted 2 Tonemapping
vec3 Uncharted2Tonemap(vec3 x) {
    float A = 0.15;
    float B = 0.50;
    float C = 0.10;
    float D = 0.20;
    float E = 0.02;
    float F = 0.30;
    return ((x * (A * x + C * B) + D * E) / (x * (A * x + B) + D * F)) - E / F;
}

vec3 Uncharted2(vec3 color) {
    float W = 11.2;
    float exposureBias = 2.0;
    vec3 curr = Uncharted2Tonemap(exposureBias * color);
    vec3 whiteScale = 1.0 / Uncharted2Tonemap(vec3(W));
    return curr * whiteScale;
}

// Simple Reinhard
vec3 Reinhard(vec3 color) {
    return color / (color + vec3(1.0));
}

void main() {
    // Sample HDR scene
    vec3 hdrColor = texture(hdrScene, fragTexCoord).rgb;

    // Apply SSAO
    if (params.enableSSAO != 0u) {
        float ao = texture(ssaoTexture, fragTexCoord).r;
        ao = mix(1.0, ao, params.ssaoIntensity);
        hdrColor *= ao;
    }

    // Apply bloom
    if (params.enableBloom != 0u) {
        vec3 bloom = texture(bloomTexture, fragTexCoord).rgb;
        hdrColor += bloom * params.bloomIntensity;
    }

    // Apply exposure
    hdrColor *= params.exposure;

    // Tonemapping
    vec3 mapped;
    if (params.tonemapMode == 1u) {
        mapped = ACESFilm(hdrColor);
    } else if (params.tonemapMode == 2u) {
        mapped = Uncharted2(hdrColor);
    } else {
        mapped = Reinhard(hdrColor);
    }

    // Gamma correction
    mapped = pow(mapped, vec3(1.0 / 2.2));

    outColor = vec4(mapped, 1.0);
}
