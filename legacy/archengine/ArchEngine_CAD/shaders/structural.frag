#version 450

// Input from vertex shader
layout(location = 0) in vec3 fragColor;
layout(location = 1) in vec3 fragNormal;
layout(location = 2) in vec3 fragPosition;
layout(location = 3) in float fragStress;
layout(location = 4) in vec4 fragLightSpacePos;
layout(location = 5) in vec4 fragMaterial;  // x=metallic, y=roughness, z=ao, w=emission

// Output
layout(location = 0) out vec4 outColor;

// Uniform buffer
layout(set = 0, binding = 0) uniform UniformBufferObject {
    mat4 view;
    mat4 proj;
    mat4 lightViewProj;
    vec4 lightDirection;
    vec4 clipPlane;
    float time;
    float shadowBias;
    uint enableClipping;
    uint enableShadows;
} ubo;

// Shadow map sampler with depth comparison
layout(set = 0, binding = 1) uniform sampler2DShadow shadowMap;

// Stress color constants (matching types.hpp)
const vec3 STRESS_SAFE     = vec3(0.133, 0.773, 0.369);  // Green
const vec3 STRESS_WARNING  = vec3(0.918, 0.702, 0.031);  // Yellow
const vec3 STRESS_CRITICAL = vec3(0.976, 0.451, 0.086);  // Orange
const vec3 STRESS_FAILURE  = vec3(0.937, 0.267, 0.267);  // Red

// Lighting constants
const vec3 lightColor = vec3(1.0, 0.98, 0.95);
const float lightIntensity = 3.0;
const vec3 ambientColor = vec3(0.03);

// PBR Constants
const float PI = 3.14159265359;

// ==================== PBR Functions ====================

// Normal Distribution Function (GGX/Trowbridge-Reitz)
float DistributionGGX(vec3 N, vec3 H, float roughness) {
    float a = roughness * roughness;
    float a2 = a * a;
    float NdotH = max(dot(N, H), 0.0);
    float NdotH2 = NdotH * NdotH;

    float num = a2;
    float denom = (NdotH2 * (a2 - 1.0) + 1.0);
    denom = PI * denom * denom;

    return num / max(denom, 0.0001);
}

// Geometry function (Schlick-GGX)
float GeometrySchlickGGX(float NdotV, float roughness) {
    float r = roughness + 1.0;
    float k = (r * r) / 8.0;

    float num = NdotV;
    float denom = NdotV * (1.0 - k) + k;

    return num / max(denom, 0.0001);
}

// Smith's method for geometry
float GeometrySmith(vec3 N, vec3 V, vec3 L, float roughness) {
    float NdotV = max(dot(N, V), 0.0);
    float NdotL = max(dot(N, L), 0.0);
    float ggx2 = GeometrySchlickGGX(NdotV, roughness);
    float ggx1 = GeometrySchlickGGX(NdotL, roughness);

    return ggx1 * ggx2;
}

// Fresnel-Schlick approximation
vec3 fresnelSchlick(float cosTheta, vec3 F0) {
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

// Fresnel-Schlick with roughness for ambient lighting
vec3 fresnelSchlickRoughness(float cosTheta, vec3 F0, float roughness) {
    return F0 + (max(vec3(1.0 - roughness), F0) - F0) * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

// Calculate stress color based on utilization ratio
vec3 getStressColor(float stress) {
    if (stress < 0.7) {
        return STRESS_SAFE;
    } else if (stress < 0.9) {
        float t = (stress - 0.7) / 0.2;
        return mix(STRESS_SAFE, STRESS_WARNING, t);
    } else if (stress < 1.0) {
        float t = (stress - 0.9) / 0.1;
        return mix(STRESS_WARNING, STRESS_CRITICAL, t);
    } else {
        float t = min((stress - 1.0) / 0.5, 1.0);
        return mix(STRESS_CRITICAL, STRESS_FAILURE, t);
    }
}

// Poisson disk samples for soft shadow PCF (16 samples)
const vec2 poissonDisk[16] = vec2[](
    vec2(-0.94201624, -0.39906216),
    vec2( 0.94558609, -0.76890725),
    vec2(-0.09418410, -0.92938870),
    vec2( 0.34495938,  0.29387760),
    vec2(-0.91588581,  0.45771432),
    vec2(-0.81544232, -0.87912464),
    vec2(-0.38277543,  0.27676845),
    vec2( 0.97484398,  0.75648379),
    vec2( 0.44323325, -0.97511554),
    vec2( 0.53742981, -0.47373420),
    vec2(-0.26496911, -0.41893023),
    vec2( 0.79197514,  0.19090188),
    vec2(-0.24188840,  0.99706507),
    vec2(-0.81409955,  0.91437590),
    vec2( 0.19984126,  0.78641367),
    vec2( 0.14383161, -0.14100790)
);

// Soft shadow calculation with Poisson disk PCF
float calculateShadow(vec4 lightSpacePos) {
    // Perspective divide
    vec3 projCoords = lightSpacePos.xyz / lightSpacePos.w;

    // Transform to [0,1] range for texture sampling
    projCoords.xy = projCoords.xy * 0.5 + 0.5;

    // Check if outside shadow map bounds
    if (projCoords.x < 0.0 || projCoords.x > 1.0 ||
        projCoords.y < 0.0 || projCoords.y > 1.0 ||
        projCoords.z < 0.0 || projCoords.z > 1.0) {
        return 1.0;  // Fully lit outside bounds
    }

    // Soft PCF with Poisson disk sampling
    float shadow = 0.0;
    vec2 texelSize = 1.0 / vec2(textureSize(shadowMap, 0));
    float spreadRadius = 2.5;  // Spread of the soft shadow (in texels)

    for (int i = 0; i < 16; i++) {
        vec2 offset = poissonDisk[i] * texelSize * spreadRadius;
        shadow += texture(shadowMap, vec3(projCoords.xy + offset, projCoords.z - ubo.shadowBias));
    }
    shadow /= 16.0;

    // Return shadow factor (1.0 = fully lit, 0.0 = fully in shadow)
    return shadow;
}

// Calculate fake ambient occlusion based on geometry
float calculateAO(vec3 normal, vec3 position) {
    // Simple hemisphere occlusion - surfaces facing down receive less ambient light
    float hemisphereAO = (normal.y + 1.0) * 0.5;  // 0 = facing down, 1 = facing up
    hemisphereAO = mix(0.6, 1.0, hemisphereAO);   // Remap to 0.6-1.0 range

    return clamp(hemisphereAO, 0.4, 1.0);
}

void main() {
    // Normalize interpolated normal
    vec3 N = normalize(fragNormal);

    // Calculate view direction (camera is at origin in view space)
    vec3 viewSpacePos = (ubo.view * vec4(fragPosition, 1.0)).xyz;
    vec3 V = normalize(-viewSpacePos);

    // Get light direction from UBO (negated because it points toward light)
    vec3 L = normalize(-ubo.lightDirection.xyz);
    vec3 H = normalize(V + L);

    // Extract material properties
    float metallic = fragMaterial.x;
    float roughness = max(fragMaterial.y, 0.04);  // Clamp to avoid artifacts
    float materialAO = fragMaterial.z;
    float emission = fragMaterial.w;

    // Use stress coloring if stress is significant, otherwise use vertex color
    vec3 albedo = fragColor;
    if (fragStress > 0.01) {
        albedo = getStressColor(fragStress);
    }

    // Calculate reflectance at normal incidence (F0)
    // For dielectrics, use 0.04 (typical for non-metals)
    // For metals, use albedo color
    vec3 F0 = vec3(0.04);
    F0 = mix(F0, albedo, metallic);

    // Calculate shadow factor
    float shadow = 1.0;
    if (ubo.enableShadows != 0u) {
        shadow = calculateShadow(fragLightSpacePos);
    }

    // Calculate geometric ambient occlusion
    float geoAO = calculateAO(N, fragPosition);
    float ao = geoAO * materialAO;

    // ==================== Cook-Torrance BRDF ====================
    float NdotL = max(dot(N, L), 0.0);
    float NdotV = max(dot(N, V), 0.0);

    // Calculate Cook-Torrance specular BRDF components
    float NDF = DistributionGGX(N, H, roughness);
    float G = GeometrySmith(N, V, L, roughness);
    vec3 F = fresnelSchlick(max(dot(H, V), 0.0), F0);

    // Calculate specular and diffuse contributions
    vec3 numerator = NDF * G * F;
    float denominator = 4.0 * NdotV * NdotL + 0.0001;
    vec3 specular = numerator / denominator;

    // Energy conservation: diffuse + specular = 1
    vec3 kS = F;  // Specular contribution
    vec3 kD = vec3(1.0) - kS;  // Diffuse contribution
    kD *= 1.0 - metallic;  // Metals have no diffuse

    // Direct lighting (sun)
    vec3 radiance = lightColor * lightIntensity;
    vec3 Lo = (kD * albedo / PI + specular) * radiance * NdotL * shadow;

    // Ambient lighting (simplified IBL approximation)
    vec3 kS_ambient = fresnelSchlickRoughness(NdotV, F0, roughness);
    vec3 kD_ambient = 1.0 - kS_ambient;
    kD_ambient *= 1.0 - metallic;

    // Diffuse ambient
    vec3 irradiance = ambientColor + vec3(0.15, 0.18, 0.22);  // Sky-ish ambient
    vec3 diffuseAmbient = irradiance * albedo;

    // Simple specular ambient (approximate)
    vec3 specularAmbient = irradiance * F0 * (1.0 - roughness * 0.7);

    vec3 ambient = (kD_ambient * diffuseAmbient + specularAmbient) * ao;

    // Combine direct and ambient lighting
    vec3 result = ambient + Lo;

    // Add emission
    result += albedo * emission;

    // Tone mapping (ACES-ish)
    result = result / (result + vec3(1.0));

    // Gamma correction
    result = pow(result, vec3(1.0 / 2.2));

    outColor = vec4(result, 1.0);
}