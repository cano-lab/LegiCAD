#version 450

// Final composite pass: combines HDR scene + SSAO + bloom + SSR, applies tonemapping

layout(location = 0) in vec2 fragTexCoord;
layout(location = 0) out vec4 outColor;

layout(set = 0, binding = 0) uniform sampler2D hdrScene;
layout(set = 0, binding = 1) uniform sampler2D ssaoTexture;
layout(set = 0, binding = 2) uniform sampler2D bloomTexture;
layout(set = 0, binding = 3) uniform sampler2D ssrTexture;      // SSR reflections (rgb=color, a=confidence)
layout(set = 0, binding = 4) uniform sampler2D normalRoughness; // Normal + roughness for SSR blend

layout(push_constant) uniform CompositeParams {
    float bloomIntensity;
    float exposure;
    float ssaoIntensity;
    uint enableSSAO;
    uint enableBloom;
    uint tonemapMode;  // 0=Reinhard, 1=ACES, 2=Uncharted2
    uint debugMode;    // 0=None, 1=SSAO, 2=Bloom, 3=HDRScene, 4=Depth, 5=SSR, 6=Normals
    float nearPlane;
    float farPlane;
    uint enableSSR;     // SSR enabled flag
    float ssrIntensity; // SSR intensity multiplier
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

// Linearize depth for visualization
float linearizeDepth(float depth) {
    float z = depth * 2.0 - 1.0;  // NDC
    return (2.0 * params.nearPlane * params.farPlane) / (params.farPlane + params.nearPlane - z * (params.farPlane - params.nearPlane));
}

void main() {
    // Debug modes - show individual buffers
    if (params.debugMode == 1u) {
        // SSAO Only - grayscale
        float ao = texture(ssaoTexture, fragTexCoord).r;
        outColor = vec4(vec3(ao), 1.0);
        return;
    } else if (params.debugMode == 2u) {
        // Bloom Only
        vec3 bloom = texture(bloomTexture, fragTexCoord).rgb;
        // Apply gamma for visibility
        bloom = pow(bloom, vec3(1.0 / 2.2));
        outColor = vec4(bloom, 1.0);
        return;
    } else if (params.debugMode == 3u) {
        // HDR Scene without effects
        vec3 hdr = texture(hdrScene, fragTexCoord).rgb;
        hdr *= params.exposure;
        vec3 mapped = ACESFilm(hdr);
        mapped = pow(mapped, vec3(1.0 / 2.2));
        outColor = vec4(mapped, 1.0);
        return;
    } else if (params.debugMode == 4u) {
        // Depth visualization - need to sample from depth somehow
        // For now, show SSAO inverted as proxy for depth edges
        float ao = 1.0 - texture(ssaoTexture, fragTexCoord).r;
        outColor = vec4(vec3(ao), 1.0);
        return;
    } else if (params.debugMode == 5u) {
        // SSR Only - show reflections
        vec4 ssr = texture(ssrTexture, fragTexCoord);
        vec3 ssrColor = ssr.rgb * ssr.a;  // Color weighted by confidence
        ssrColor = pow(ssrColor, vec3(1.0 / 2.2));
        outColor = vec4(ssrColor, 1.0);
        return;
    } else if (params.debugMode == 6u) {
        // Normals visualization
        vec3 normal = texture(normalRoughness, fragTexCoord).rgb;
        outColor = vec4(normal, 1.0);  // Already packed in [0,1]
        return;
    }

    // Normal rendering path
    vec3 hdrColor = texture(hdrScene, fragTexCoord).rgb;

    // Apply SSAO
    if (params.enableSSAO != 0u) {
        float ao = texture(ssaoTexture, fragTexCoord).r;
        ao = mix(1.0, ao, params.ssaoIntensity);
        hdrColor *= ao;
    }

    // Apply SSR (screen-space reflections)
    if (params.enableSSR != 0u) {
        vec4 ssrData = texture(ssrTexture, fragTexCoord);
        vec3 ssrColor = ssrData.rgb;
        float ssrConfidence = ssrData.a;

        // Get roughness from normal buffer to modulate reflection intensity
        float roughness = texture(normalRoughness, fragTexCoord).a;

        // Calculate reflection blend factor:
        // - Lower roughness = stronger reflections
        // - Higher SSR confidence = more visible reflection
        float reflectivity = (1.0 - roughness) * ssrConfidence * params.ssrIntensity;

        // Blend reflections additively (reflections add light)
        // For more physically accurate results, this should be multiplied by metallic
        hdrColor += ssrColor * reflectivity * 0.5;
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
