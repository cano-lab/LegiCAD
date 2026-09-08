#version 450

// Input from vertex shader
layout(location = 0) in vec3 fragColor;
layout(location = 1) in vec3 fragNormal;
layout(location = 2) in vec3 fragPosition;
layout(location = 3) in float fragStress;
layout(location = 4) in vec4 fragLightSpacePos;
layout(location = 5) in vec4 fragMaterial;  // x=metallic, y=roughness, z=ao, w=emission
layout(location = 6) in vec2 fragTexCoord;

// Outputs (MRT for SSR)
layout(location = 0) out vec4 outColor;
layout(location = 1) out vec4 outNormal;  // xyz = world normal (packed), w = roughness

// Shared UBO definition (includes override mask constants)
#include "include/ubo.glsl"

// Push constants (per-draw data including element overrides)
layout(push_constant) uniform PushConstants {
    mat4 model;
    vec4 color;
    vec4 material;       // x = metallic, y = roughness, z = ao, w = emission
    uint overrideMask;   // Which overrides are active
    float _pad1, _pad2, _pad3;  // Padding for vec4 alignment
    vec4 overrides1;     // x=uvScale, y=normalStrength, z=brightness, w=contrast
    vec4 overrides2;     // x=saturation, y=roughness, z=metallic, w=aoStrength
    vec4 overrides3;     // rgb=tint, w=uvRotation (radians)
} push;

// Shadow map sampler with depth comparison
// Using 2D sampler for now (first layer only) until array sampling is debugged
layout(set = 0, binding = 1) uniform sampler2DShadow shadowMap;

// Material textures (set 1 = per-material)
layout(set = 1, binding = 0) uniform sampler2D albedoMap;
layout(set = 1, binding = 1) uniform sampler2D normalMap;
layout(set = 1, binding = 2) uniform sampler2D roughnessMap;
layout(set = 1, binding = 3) uniform sampler2D metallicMap;
layout(set = 1, binding = 4) uniform sampler2D aoMap;
layout(set = 1, binding = 5) uniform sampler2D emissiveMap;
layout(set = 1, binding = 6) uniform sampler2D opacityMap;
layout(set = 1, binding = 7) uniform sampler2D heightMap;  // For tessellation displacement

// IBL textures (set 2 = environment-based lighting)
layout(set = 2, binding = 0) uniform samplerCube irradianceMap;   // Diffuse IBL
layout(set = 2, binding = 1) uniform samplerCube prefilteredMap;  // Specular IBL (with mip chain)
layout(set = 2, binding = 2) uniform sampler2D brdfLUT;           // BRDF lookup table

// IBL parameters (could be in UBO, hardcoded for now)
const float MAX_REFLECTION_LOD = 5.0;  // Should match prefilteredMipLevels - 1

// Stress color constants (matching types.hpp)
const vec3 STRESS_SAFE     = vec3(0.133, 0.773, 0.369);  // Green
const vec3 STRESS_WARNING  = vec3(0.918, 0.702, 0.031);  // Yellow
const vec3 STRESS_CRITICAL = vec3(0.976, 0.451, 0.086);  // Orange
const vec3 STRESS_FAILURE  = vec3(0.937, 0.267, 0.267);  // Red

// PBR Constants
const float PI = 3.14159265359;

// Lighting constants
const vec3 sunLightColor = vec3(1.0, 0.98, 0.95);
const float sunLightIntensity = 3.0;
const vec3 ambientColor = vec3(0.03);

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

// ==================== Multi-Light Functions ====================

// Point light attenuation (inverse square with range cutoff)
float getPointAttenuation(float distance, float range) {
    // Smooth falloff to zero at range
    float att = 1.0 / (1.0 + distance * distance);
    float rangeFalloff = clamp(1.0 - pow(distance / range, 4.0), 0.0, 1.0);
    return att * rangeFalloff * rangeFalloff;
}

// Spot light cone factor
float getSpotCone(vec3 lightDir, vec3 spotDir, float innerCos, float outerCos) {
    float theta = dot(lightDir, -spotDir);
    // Smooth transition from inner to outer cone
    return clamp((theta - outerCos) / max(innerCos - outerCos, 0.0001), 0.0, 1.0);
}

// Calculate contribution from a single light
vec3 calculateLightContribution(GPULight light, vec3 N, vec3 V, vec3 fragPos,
                                 vec3 albedo, float metallic, float roughness, vec3 F0) {
    uint lightType = uint(light.positionType.w);
    vec3 lightColor = light.colorIntensity.rgb;
    float intensity = light.colorIntensity.a;

    vec3 L;
    float attenuation = 1.0;

    if (lightType == LIGHT_TYPE_DIRECTIONAL) {
        // Directional light - parallel rays
        L = normalize(-light.directionRange.xyz);
    }
    else if (lightType == LIGHT_TYPE_POINT) {
        // Point light - radial from position
        vec3 lightPos = light.positionType.xyz;
        vec3 toLight = lightPos - fragPos;
        float distance = length(toLight);
        L = toLight / distance;

        float range = light.directionRange.w;
        attenuation = getPointAttenuation(distance, range);
    }
    else if (lightType == LIGHT_TYPE_SPOT) {
        // Spot light - radial with cone
        vec3 lightPos = light.positionType.xyz;
        vec3 toLight = lightPos - fragPos;
        float distance = length(toLight);
        L = toLight / distance;

        float range = light.directionRange.w;
        attenuation = getPointAttenuation(distance, range);

        // Apply cone falloff
        vec3 spotDir = normalize(light.directionRange.xyz);
        float innerCos = light.spotParams.x;
        float outerCos = light.spotParams.y;
        attenuation *= getSpotCone(L, spotDir, innerCos, outerCos);
    }
    else {
        return vec3(0.0);  // Unknown light type
    }

    // Skip if light contribution is negligible
    if (attenuation < 0.001) {
        return vec3(0.0);
    }

    // Standard PBR calculation
    vec3 H = normalize(V + L);
    float NdotL = max(dot(N, L), 0.0);
    float NdotV = max(dot(N, V), 0.0);

    // Cook-Torrance BRDF
    float NDF = DistributionGGX(N, H, roughness);
    float G = GeometrySmith(N, V, L, roughness);
    vec3 F = fresnelSchlick(max(dot(H, V), 0.0), F0);

    vec3 numerator = NDF * G * F;
    float denominator = 4.0 * NdotV * NdotL + 0.0001;
    vec3 specular = numerator / denominator;

    vec3 kS = F;
    vec3 kD = vec3(1.0) - kS;
    kD *= 1.0 - metallic;

    // Calculate radiance with attenuation
    vec3 radiance = lightColor * intensity * attenuation;

    return (kD * albedo / PI + specular) * radiance * NdotL;
}

// Perturb normal using tangent space normal map
vec3 perturbNormal(vec3 N, vec3 V, vec2 texCoord, float normalStrength) {
    // Sample normal map (stored as RGB = XYZ in [0,1] range)
    vec3 tangentNormal = texture(normalMap, texCoord).rgb * 2.0 - 1.0;
    tangentNormal = normalize(vec3(tangentNormal.xy * normalStrength, tangentNormal.z));

    // Compute TBN matrix using derivatives (no pre-computed tangents needed)
    vec3 Q1 = dFdx(fragPosition);
    vec3 Q2 = dFdy(fragPosition);
    vec2 st1 = dFdx(texCoord);
    vec2 st2 = dFdy(texCoord);

    vec3 T = normalize(Q1 * st2.t - Q2 * st1.t);
    vec3 B = normalize(cross(N, T));
    mat3 TBN = mat3(T, B, N);

    return normalize(TBN * tangentNormal);
}

// Compute TBN matrix for POM (returns transpose for view->tangent space transform)
mat3 computeTBN(vec3 N, vec2 texCoord) {
    vec3 Q1 = dFdx(fragPosition);
    vec3 Q2 = dFdy(fragPosition);
    vec2 st1 = dFdx(texCoord);
    vec2 st2 = dFdy(texCoord);

    vec3 T = normalize(Q1 * st2.t - Q2 * st1.t);
    vec3 B = normalize(cross(N, T));
    return mat3(T, B, N);
}

// Parallax Occlusion Mapping (POM)
// Ray marches through height map to find surface intersection
// Returns displaced UV coordinates
vec2 parallaxOcclusionMapping(vec2 texCoord, vec3 viewDirTangent, float heightScale, float minLayers, float maxLayers) {
    // Safety: skip POM if viewing nearly parallel to surface (would cause artifacts)
    if (abs(viewDirTangent.z) < 0.001) {
        return texCoord;
    }

    // Number of layers based on view angle (more layers at grazing angles)
    float numLayers = mix(maxLayers, minLayers, abs(dot(vec3(0.0, 0.0, 1.0), viewDirTangent)));
    numLayers = clamp(numLayers, 4.0, 128.0);  // Safety clamp

    // Calculate the size of each layer
    float layerDepth = 1.0 / numLayers;
    float currentLayerDepth = 0.0;

    // Direction and amount to shift UV per layer
    vec2 P = viewDirTangent.xy / viewDirTangent.z * heightScale;
    vec2 deltaTexCoords = P / numLayers;

    // Current UV coordinates and height
    vec2 currentTexCoords = texCoord;
    float currentDepthMapValue = 1.0 - texture(heightMap, currentTexCoords).r;

    // Ray march until we find intersection (with iteration limit for safety)
    int maxIterations = int(numLayers) + 1;
    int iterations = 0;
    while (currentLayerDepth < currentDepthMapValue && iterations < maxIterations) {
        currentTexCoords -= deltaTexCoords;
        currentDepthMapValue = 1.0 - texture(heightMap, currentTexCoords).r;
        currentLayerDepth += layerDepth;
        iterations++;
    }

    // Binary search refinement for more accurate intersection
    vec2 prevTexCoords = currentTexCoords + deltaTexCoords;

    float afterDepth = currentDepthMapValue - currentLayerDepth;
    float beforeDepth = (1.0 - texture(heightMap, prevTexCoords).r) - currentLayerDepth + layerDepth;

    // Safety: avoid division by zero
    float denom = afterDepth - beforeDepth;
    if (abs(denom) < 0.0001) {
        return currentTexCoords;
    }

    float weight = afterDepth / denom;
    weight = clamp(weight, 0.0, 1.0);  // Safety clamp

    return mix(currentTexCoords, prevTexCoords, weight);
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

// Soft shadow with slope-scaled bias for grazing angles
// Temporarily using single 2D shadow map until array sampling is debugged
float calculateShadow(vec3 worldPos, vec3 normal, vec3 lightDir) {
    // Use first shadow map matrix
    vec4 lightSpacePos = ubo.lightViewProj[0] * vec4(worldPos, 1.0);

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

    // Slope-scaled bias: more bias at grazing angles (roof problem fix)
    float NdotL = max(dot(normal, lightDir), 0.0);
    float slopeBias = ubo.shadowBias * sqrt(1.0 - NdotL * NdotL) / max(NdotL, 0.1);
    float totalBias = ubo.shadowBias + clamp(slopeBias, 0.0, 0.05);

    vec2 texelSize = 1.0 / vec2(textureSize(shadowMap, 0));
    float shadow = 0.0;

    // Spread factor for shadow edges (lower = sharper, less bleeding)
    float spread = 1.5;

    // 3x3 PCF for smooth shadow edges
    for (int x = -1; x <= 1; x++) {
        for (int y = -1; y <= 1; y++) {
            vec2 offset = vec2(float(x), float(y)) * texelSize * spread;
            shadow += texture(shadowMap, vec3(projCoords.xy + offset, projCoords.z - totalBias));
        }
    }
    shadow /= 9.0;

    // Clean up near-lit areas to avoid subtle artifacts
    if (shadow > 0.95) shadow = 1.0;

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

    // Calculate UV coordinates with override support (replacement, not additive)
    float uvScale = ubo.materialParams.x;
    float uvRotation = 0.0;  // Default: no rotation

    // Use push constant override for UV scale (only if UV scale bit is set)
    if ((push.overrideMask & OVERRIDE_UV_SCALE) != 0u) {
        uvScale = push.overrides1.x;  // Use push constant override value
    }
    // Use push constant override for UV rotation
    if ((push.overrideMask & OVERRIDE_UV_ROTATION) != 0u) {
        uvRotation = push.overrides3.w;  // Rotation in radians
    }

    // Apply scale first
    vec2 uv = fragTexCoord * uvScale;

    // Apply rotation around center (0.5, 0.5) if rotation is set
    if (uvRotation != 0.0) {
        vec2 center = vec2(0.5) * uvScale;  // Center point scales with UV
        float cosR = cos(uvRotation);
        float sinR = sin(uvRotation);
        vec2 offset = uv - center;
        uv = vec2(
            offset.x * cosR - offset.y * sinR,
            offset.x * sinR + offset.y * cosR
        ) + center;
    }

    // Apply Parallax Occlusion Mapping if enabled
    if (ubo.pomParams.x > 0.5) {
        // Compute camera position from inverse view matrix
        mat4 invView = inverse(ubo.view);
        vec3 cameraPos = invView[3].xyz;

        // World-space view direction (from surface to camera)
        vec3 viewDirWorld = normalize(cameraPos - fragPosition);

        // Compute TBN matrix and transform view direction to tangent space
        mat3 TBN = computeTBN(N, uv);
        mat3 TBN_transpose = transpose(TBN);  // World -> Tangent space
        vec3 viewDirTangent = normalize(TBN_transpose * viewDirWorld);

        // Apply POM
        float pomHeightScale = ubo.pomParams.y;
        float pomMinLayers = ubo.pomParams.z;
        float pomMaxLayers = ubo.pomParams.w;

        uv = parallaxOcclusionMapping(uv, viewDirTangent, pomHeightScale, pomMinLayers, pomMaxLayers);
    }

    // Normal strength with override support (use push constants)
    float normalStrength = ubo.materialParams.y;
    if ((push.overrideMask & OVERRIDE_NORMAL_STRENGTH) != 0u) {
        normalStrength = push.overrides1.y;
    }

    // Sample material textures
    vec3 texAlbedo = texture(albedoMap, uv).rgb;
    vec3 texNormal = texture(normalMap, uv).rgb;
    float texRoughness = texture(roughnessMap, uv).r;
    float texMetallic = texture(metallicMap, uv).r;
    float texAO = texture(aoMap, uv).r;
    vec3 texEmissive = texture(emissiveMap, uv).rgb;
    float texOpacity = texture(opacityMap, uv).r;

    // Perturb normal using normal map (only if not flat normal and normal mapping is enabled)
    if ((ubo.effectFlags & EFFECT_NORMAL_MAPPING) != 0u && length(texNormal - vec3(0.5, 0.5, 1.0)) > 0.01) {
        N = perturbNormal(N, V, uv, normalStrength);
    }

    // Extract push constant material properties (used as multipliers/overrides)
    float metallic = fragMaterial.x * texMetallic;
    float roughness = max(fragMaterial.y * texRoughness, 0.04);  // Clamp to avoid artifacts
    float materialAO = fragMaterial.z * texAO;
    float emission = fragMaterial.w;

    // Apply material adjustments from UBO with override support (replacement for most, additive for roughness/metallic)
    float brightness = ubo.materialParams.z;
    float contrast = ubo.materialParams.w;
    float saturation = ubo.materialParams2.x;
    float roughnessOffset = ubo.materialParams2.y;  // Additive offset
    float metallicOffset = ubo.materialParams2.z;    // Additive offset
    float aoStrength = ubo.materialParams2.w;
    vec3 tint = ubo.materialTint.rgb;

    // Apply element overrides from push constants (all per-element overrides)
    if ((push.overrideMask & OVERRIDE_BRIGHTNESS) != 0u) {
        brightness = push.overrides1.z;
    }
    if ((push.overrideMask & OVERRIDE_CONTRAST) != 0u) {
        contrast = push.overrides1.w;
    }
    if ((push.overrideMask & OVERRIDE_SATURATION) != 0u) {
        saturation = push.overrides2.x;
    }
    if ((push.overrideMask & OVERRIDE_ROUGHNESS) != 0u) {
        roughnessOffset = push.overrides2.y;
    }
    if ((push.overrideMask & OVERRIDE_METALLIC) != 0u) {
        metallicOffset = push.overrides2.z;
    }
    if ((push.overrideMask & OVERRIDE_AO_STRENGTH) != 0u) {
        aoStrength = push.overrides2.w;
    }
    if ((push.overrideMask & OVERRIDE_TINT) != 0u) {
        tint = push.overrides3.rgb;
    }

    // Apply roughness/metallic with offset (additive), AO and others as direct values
    roughness = clamp(roughness + roughnessOffset, 0.04, 1.0);
    metallic = clamp(metallic + metallicOffset, 0.0, 1.0);
    materialAO = clamp(materialAO * aoStrength, 0.0, 1.0);

    // Albedo: multiply texture by vertex color for tinting capability
    vec3 albedo = texAlbedo * fragColor;

    // Apply brightness, contrast, saturation, and tint adjustments
    // Brightness: add to color
    albedo += vec3(brightness);
    // Contrast: scale around 0.5
    albedo = (albedo - 0.5) * contrast + 0.5;
    // Saturation: lerp toward grayscale
    float gray = dot(albedo, vec3(0.299, 0.587, 0.114));
    albedo = mix(vec3(gray), albedo, saturation);
    // Tint: multiply
    albedo *= tint;

    // Clamp to valid range
    albedo = clamp(albedo, 0.0, 1.0);

    // Use stress coloring if stress is significant (override textures)
    if (fragStress > 0.01) {
        albedo = getStressColor(fragStress);
    }

    // Calculate reflectance at normal incidence (F0)
    // For dielectrics, use 0.04 (typical for non-metals)
    // For metals, use albedo color
    vec3 F0 = vec3(0.04);
    F0 = mix(F0, albedo, metallic);

    // Calculate shadow factor (with slope-scaled bias for grazing angles)
    float shadow = 1.0;
    if (ubo.enableShadows != 0u) {
        shadow = calculateShadow(fragPosition, N, L);
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

    // Direct lighting (sun) - can be toggled via effect flags
    vec3 Lo = vec3(0.0);
    if ((ubo.effectFlags & EFFECT_DIRECT_LIGHT) != 0u) {
        vec3 sunRadiance = sunLightColor * sunLightIntensity;
        Lo = (kD * albedo / PI + specular) * sunRadiance * NdotL * shadow;

        // Additional lights from UBO array
        for (uint i = 0u; i < ubo.numLights && i < MAX_LIGHTS; i++) {
            Lo += calculateLightContribution(ubo.lights[i], N, V, fragPosition, albedo, metallic, roughness, F0);
        }
    }

    // ==================== Image-Based Lighting (IBL) ====================
    // Split-sum approximation for the specular part of the rendering equation
    // Intensity multipliers from ubo.iblParams: x=overall, y=diffuse, z=specular, w=fresnel

    vec3 kS_ambient = fresnelSchlickRoughness(NdotV, F0, roughness);
    // Apply fresnel intensity adjustment
    kS_ambient *= ubo.iblParams.w;
    vec3 kD_ambient = 1.0 - kS_ambient;
    kD_ambient *= 1.0 - metallic;

    // Diffuse IBL: Sample irradiance map (pre-convolved for Lambertian)
    vec3 irradiance = texture(irradianceMap, N).rgb;
    // Fallback to simple gradient if irradiance map is not populated
    if (length(irradiance) < 0.001) {
        vec3 skyAmbient = vec3(0.18, 0.22, 0.28);
        vec3 groundAmbient = vec3(0.12, 0.10, 0.08);
        float skyBlend = N.y * 0.5 + 0.5;
        irradiance = ambientColor + mix(groundAmbient, skyAmbient, skyBlend);
    }
    // Apply diffuse IBL intensity
    vec3 diffuseIBL = irradiance * albedo * ubo.iblParams.y;

    // Specular IBL: Sample pre-filtered environment map + BRDF LUT
    vec3 R = reflect(-V, N);  // Reflection direction
    float mipLevel = roughness * MAX_REFLECTION_LOD;
    vec3 prefilteredColor = textureLod(prefilteredMap, R, mipLevel).rgb;

    // Sample BRDF LUT (x = NdotV, y = roughness)
    vec2 brdf = texture(brdfLUT, vec2(NdotV, roughness)).rg;

    // Fallback for BRDF LUT (Schlick approximation if LUT not populated)
    if (brdf.x < 0.001 && brdf.y < 0.001) {
        brdf = vec2(1.0 - roughness * 0.5, roughness * 0.1);
    }

    // Specular IBL contribution: F0 * scale + bias
    // Apply specular IBL intensity
    vec3 specularIBL = prefilteredColor * (F0 * brdf.x + brdf.y) * ubo.iblParams.z;

    // Fallback if prefiltered map not populated
    if (length(prefilteredColor) < 0.001) {
        specularIBL = irradiance * F0 * (1.0 - roughness * 0.7) * ubo.iblParams.z;
    }

    // IBL ambient - can be toggled via effect flags
    // Apply overall IBL intensity multiplier
    vec3 ambient = vec3(0.0);
    if ((ubo.effectFlags & EFFECT_IBL) != 0u) {
        ambient = (kD_ambient * diffuseIBL + specularIBL) * ao * ubo.iblParams.x;
    } else {
        // Minimal ambient when IBL is disabled (so objects aren't completely black)
        ambient = albedo * 0.03;
    }

    // Combine direct and ambient lighting
    vec3 result = ambient + Lo;

    // Add emission (use emissive texture when present, fall back to albedo)
    vec3 emissiveColor = (length(texEmissive) > 0.001) ? texEmissive : albedo;
    result += emissiveColor * emission;

    // Material debug visualization modes (controlled via UI)
    // Note: Still output normal for MRT consistency
    if (ubo.materialDebugMode == 1u) {
        // Displacement: show height map value as grayscale
        float height = texture(heightMap, uv).r;
        outColor = vec4(vec3(height), 1.0);
        outNormal = vec4(N * 0.5 + 0.5, roughness);
        return;
    } else if (ubo.materialDebugMode == 2u) {
        // POM Depth: show parallax depth as blue gradient
        // Compare original UV with POM-displaced UV
        vec2 uvDiff = abs(uv - fragTexCoord * uvScale);
        float pomDepth = length(uvDiff) * 10.0;  // Scale for visibility
        outColor = vec4(0.0, pomDepth * 0.5, pomDepth, 1.0);
        outNormal = vec4(N * 0.5 + 0.5, roughness);
        return;
    } else if (ubo.materialDebugMode == 3u) {
        // Normals: show world-space normals as RGB
        outColor = vec4(N * 0.5 + 0.5, 1.0);
        outNormal = vec4(N * 0.5 + 0.5, roughness);
        return;
    } else if (ubo.materialDebugMode == 4u) {
        // UVs: show UV coordinates as RG
        outColor = vec4(fract(uv), 0.0, 1.0);
        outNormal = vec4(N * 0.5 + 0.5, roughness);
        return;
    } else if (ubo.materialDebugMode == 5u) {
        // AO Map: show ambient occlusion texture
        outColor = vec4(vec3(texAO), 1.0);
        outNormal = vec4(N * 0.5 + 0.5, roughness);
        return;
    } else if (ubo.materialDebugMode == 6u) {
        // Specular IBL: show specular reflection contribution
        outColor = vec4(specularIBL, 1.0);
        outNormal = vec4(N * 0.5 + 0.5, roughness);
        return;
    } else if (ubo.materialDebugMode == 7u) {
        // Diffuse IBL: show diffuse ambient contribution
        outColor = vec4(diffuseIBL, 1.0);
        outNormal = vec4(N * 0.5 + 0.5, roughness);
        return;
    } else if (ubo.materialDebugMode == 8u) {
        // Total ambient: show combined ambient term
        outColor = vec4(ambient, 1.0);
        outNormal = vec4(N * 0.5 + 0.5, roughness);
        return;
    } else if (ubo.materialDebugMode == 9u) {
        // BRDF LUT values: show scale and bias from LUT
        outColor = vec4(brdf.x, brdf.y, 0.0, 1.0);
        outNormal = vec4(N * 0.5 + 0.5, roughness);
        return;
    } else if (ubo.materialDebugMode == 10u) {
        // Direct lighting only (sun + lights, no ambient)
        outColor = vec4(Lo, 1.0);
        outNormal = vec4(N * 0.5 + 0.5, roughness);
        return;
    } else if (ubo.materialDebugMode == 11u) {
        // Fresnel (kS_ambient): shows how reflective surfaces are
        outColor = vec4(kS_ambient, 1.0);
        outNormal = vec4(N * 0.5 + 0.5, roughness);
        return;
    }

    // SHADOW DEBUG: Uncomment one to diagnose shadow issues
    // outColor = vec4(vec3(shadow), 1.0); return;     // Shadow factor (white=lit, black=shadow)
    // vec3 lsPos = fragLightSpacePos.xyz / fragLightSpacePos.w;
    // outColor = vec4(lsPos * 0.5 + 0.5, 1.0); return;  // Light space position (RGB=XYZ)
    // outColor = vec4(vec3(lsPos.z), 1.0); return;      // Light space depth (closer=darker)

    // Calculate alpha for transparency (glass has low roughness)
    // Glass materials: roughness < 0.35 = transparent
    float alpha = 1.0;
    if (roughness < 0.35 && metallic < 0.1) {
        // Glass: semi-transparent with fresnel effect (more opaque at grazing angles)
        float fresnel = pow(1.0 - NdotV, 3.0);
        alpha = mix(0.3, 0.7, fresnel);  // 30% to 70% opacity based on view angle
    }
    // Clamp opacity so glass doesn't vanish when opacity maps are too dark
    alpha *= clamp(texOpacity, 0.05, 1.0);

    // Write normal + roughness to MRT 1 for SSR
    // Pack world-space normal to [0,1] range, store roughness in alpha
    outNormal = vec4(N * 0.5 + 0.5, roughness);

    // When rendering to HDR buffer, output linear values (tonemapping done in composite pass)
    if (ubo.outputLinearHDR != 0u) {
        outColor = vec4(result, alpha);
        return;
    }

    // Direct rendering path: apply exposure, tonemapping and gamma correction here
    // Apply exposure
    result = result * ubo.exposure;

    // ACES Filmic Tonemapping (matches composite pass for consistent look)
    // https://knarkowicz.wordpress.com/2016/01/06/aces-filmic-tone-mapping-curve/
    {
        float a = 2.51;
        float b = 0.03;
        float c = 2.43;
        float d = 0.59;
        float e = 0.14;
        result = clamp((result * (a * result + b)) / (result * (c * result + d) + e), 0.0, 1.0);
    }

    // Gamma correction
    result = pow(result, vec3(1.0 / 2.2));

    outColor = vec4(result, alpha);
}
