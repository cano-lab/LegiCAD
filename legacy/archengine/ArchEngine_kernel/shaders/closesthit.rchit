#version 460
#extension GL_EXT_ray_tracing : require
#extension GL_EXT_nonuniform_qualifier : require
#extension GL_EXT_scalar_block_layout : require

layout(binding = 0, set = 0) uniform accelerationStructureEXT topLevelAS;
layout(binding = 2, set = 0) uniform CameraUBO {
    mat4 viewInverse;
    mat4 projInverse;
    mat4 prevViewProj;
    vec4 lightDir;
    vec4 cameraPos;
    uint frameCount;
    uint sampleCount;
    float time;
    float exposure;
    uint enableDenoising;
    float denoiseStrength;
    float pad[2];
} camera;

// Material data - matches RTMaterial struct (32 bytes)
struct Material {
    vec4 albedoAndMetallic;      // rgb = albedo, a = metallic
    vec4 roughnessAoEmissionIor; // r = roughness, g = ao, b = emission, a = ior
};

layout(binding = 3, set = 0, scalar) buffer Materials { Material materials[]; };

// Vertex data for interpolation
struct Vertex {
    vec3 position;
    vec3 normal;
    vec3 color;
};

layout(binding = 4, set = 0, scalar) buffer Vertices { Vertex vertices[]; };
layout(binding = 5, set = 0) buffer Indices { uint indices[]; };

layout(location = 0) rayPayloadInEXT vec3 hitValue;
layout(location = 1) rayPayloadEXT bool isShadowed;

hitAttributeEXT vec2 attribs;

const float PI = 3.14159265359;
const int MAX_BOUNCES = 3;  // Number of indirect light bounces

// ============================================================================
// Random number generation
// ============================================================================

uint pcgHash(uint inputValue) {
    uint state = inputValue * 747796405u + 2891336453u;
    uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}

float randomFloat(inout uint seed) {
    seed = pcgHash(seed);
    return float(seed) / float(0xFFFFFFFFu);
}

vec2 randomVec2(inout uint seed) {
    return vec2(randomFloat(seed), randomFloat(seed));
}

// Cosine-weighted hemisphere sampling for diffuse
vec3 cosineSampleHemisphere(vec3 normal, inout uint seed) {
    float r1 = randomFloat(seed);
    float r2 = randomFloat(seed);

    float phi = 2.0 * PI * r1;
    float cosTheta = sqrt(1.0 - r2);
    float sinTheta = sqrt(r2);

    vec3 w = normalize(normal);
    vec3 u = normalize(cross(abs(w.x) > 0.1 ? vec3(0,1,0) : vec3(1,0,0), w));
    vec3 v = cross(w, u);

    return normalize(u * cos(phi) * sinTheta + v * sin(phi) * sinTheta + w * cosTheta);
}

// GGX importance sampling for specular
vec3 importanceSampleGGX(vec2 Xi, vec3 N, float roughness) {
    float a = roughness * roughness;

    float phi = 2.0 * PI * Xi.x;
    float cosTheta = sqrt((1.0 - Xi.y) / (1.0 + (a*a - 1.0) * Xi.y));
    float sinTheta = sqrt(1.0 - cosTheta * cosTheta);

    // Spherical to cartesian
    vec3 H;
    H.x = cos(phi) * sinTheta;
    H.y = sin(phi) * sinTheta;
    H.z = cosTheta;

    // Tangent space to world
    vec3 up = abs(N.z) < 0.999 ? vec3(0, 0, 1) : vec3(1, 0, 0);
    vec3 tangent = normalize(cross(up, N));
    vec3 bitangent = cross(N, tangent);

    return normalize(tangent * H.x + bitangent * H.y + N * H.z);
}

// ============================================================================
// PBR Functions (Cook-Torrance BRDF)
// ============================================================================

float DistributionGGX(vec3 N, vec3 H, float roughness) {
    float a = roughness * roughness;
    float a2 = a * a;
    float NdotH = max(dot(N, H), 0.0);
    float NdotH2 = NdotH * NdotH;

    float denom = (NdotH2 * (a2 - 1.0) + 1.0);
    denom = PI * denom * denom;

    return a2 / max(denom, 0.0001);
}

float GeometrySchlickGGX(float NdotV, float roughness) {
    float r = (roughness + 1.0);
    float k = (r * r) / 8.0;
    return NdotV / (NdotV * (1.0 - k) + k);
}

float GeometrySmith(vec3 N, vec3 V, vec3 L, float roughness) {
    float NdotV = max(dot(N, V), 0.0);
    float NdotL = max(dot(N, L), 0.0);
    float ggx2 = GeometrySchlickGGX(NdotV, roughness);
    float ggx1 = GeometrySchlickGGX(NdotL, roughness);
    return ggx1 * ggx2;
}

vec3 fresnelSchlick(float cosTheta, vec3 F0) {
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

vec3 fresnelSchlickRoughness(float cosTheta, vec3 F0, float roughness) {
    return F0 + (max(vec3(1.0 - roughness), F0) - F0) * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

// ============================================================================
// Glass/Refraction helpers
// ============================================================================

float fresnelDielectric(float cosThetaI, float etaI, float etaT) {
    cosThetaI = clamp(cosThetaI, -1.0, 1.0);

    // Swap if we're inside the object
    if (cosThetaI < 0.0) {
        float temp = etaI;
        etaI = etaT;
        etaT = temp;
        cosThetaI = -cosThetaI;
    }

    float eta = etaI / etaT;
    float sinThetaT2 = eta * eta * (1.0 - cosThetaI * cosThetaI);

    // Total internal reflection
    if (sinThetaT2 > 1.0) return 1.0;

    float cosThetaT = sqrt(1.0 - sinThetaT2);

    float rs = (etaI * cosThetaI - etaT * cosThetaT) / (etaI * cosThetaI + etaT * cosThetaT);
    float rp = (etaT * cosThetaI - etaI * cosThetaT) / (etaT * cosThetaI + etaI * cosThetaT);

    return (rs * rs + rp * rp) * 0.5;
}

vec3 refractRay(vec3 I, vec3 N, float eta) {
    float cosI = -dot(N, I);
    float sinT2 = eta * eta * (1.0 - cosI * cosI);
    if (sinT2 > 1.0) return reflect(I, N);  // Total internal reflection
    float cosT = sqrt(1.0 - sinT2);
    return eta * I + (eta * cosI - cosT) * N;
}

// ============================================================================
// Sky/Environment sampling
// ============================================================================

vec3 sampleSky(vec3 direction) {
    float t = 0.5 * (direction.y + 1.0);

    vec3 horizonColor = vec3(0.9, 0.92, 0.95);
    vec3 zenithColor = vec3(0.5, 0.7, 0.9);
    vec3 groundColor = vec3(0.3, 0.3, 0.3);

    vec3 skyColor;
    if (direction.y < 0.0) {
        float groundT = -direction.y;
        skyColor = mix(horizonColor, groundColor, groundT);
    } else {
        skyColor = mix(horizonColor, zenithColor, t);
    }

    // Sun contribution
    vec3 sunDir = normalize(-camera.lightDir.xyz);
    float sunDot = dot(direction, sunDir);
    if (sunDot > 0.995) {
        skyColor = vec3(1.0, 0.98, 0.9) * 3.0;
    } else if (sunDot > 0.98) {
        float glow = (sunDot - 0.98) / 0.015;
        skyColor = mix(skyColor, vec3(1.0, 0.95, 0.8), glow * 0.5);
    }

    return skyColor;
}

// ============================================================================
// Main hit shader
// ============================================================================

void main() {
    // Get primitive and instance indices
    uint primitiveId = gl_PrimitiveID;
    uint instanceId = gl_InstanceCustomIndexEXT;

    // Get vertex indices for this triangle
    uint i0 = indices[primitiveId * 3 + 0];
    uint i1 = indices[primitiveId * 3 + 1];
    uint i2 = indices[primitiveId * 3 + 2];

    // Get vertices
    Vertex v0 = vertices[i0];
    Vertex v1 = vertices[i1];
    Vertex v2 = vertices[i2];

    // Barycentric coordinates
    vec3 barycentrics = vec3(1.0 - attribs.x - attribs.y, attribs.x, attribs.y);

    // Interpolate position and normal
    vec3 localPosition = v0.position * barycentrics.x + v1.position * barycentrics.y + v2.position * barycentrics.z;
    vec3 localNormal = normalize(v0.normal * barycentrics.x + v1.normal * barycentrics.y + v2.normal * barycentrics.z);

    // Transform to world space
    mat4x3 objectToWorld = gl_ObjectToWorldEXT;
    vec3 position = objectToWorld * vec4(localPosition, 1.0);
    vec3 normal = normalize(mat3(objectToWorld) * localNormal);

    // Get material from buffer
    Material mat = materials[instanceId];
    vec3 albedo = mat.albedoAndMetallic.rgb;
    float metallic = mat.albedoAndMetallic.a;
    float roughness = mat.roughnessAoEmissionIor.r;
    float ao = mat.roughnessAoEmissionIor.g;
    float emission = mat.roughnessAoEmissionIor.b;
    float ior = mat.roughnessAoEmissionIor.a;

    // Check if this is a glass/transparent material (IOR > 1 and low roughness)
    bool isGlass = (ior > 1.4 && ior < 1.6 && roughness < 0.1 && metallic < 0.5);

    // Random seed based on pixel and frame
    uint seed = pcgHash(gl_LaunchIDEXT.x + gl_LaunchIDEXT.y * gl_LaunchSizeEXT.x + camera.frameCount * 1000007u + primitiveId * 37u);

    // View direction
    vec3 V = normalize(camera.cameraPos.xyz - position);
    vec3 L = normalize(-camera.lightDir.xyz);
    float NdotV = max(dot(normal, V), 0.0);
    float NdotL = max(dot(normal, L), 0.0);

    // ========================================================================
    // Handle glass/transparent materials
    // ========================================================================
    if (isGlass) {
        // Determine if we're entering or exiting the glass
        bool entering = dot(normal, V) > 0.0;
        vec3 N = entering ? normal : -normal;
        float etaI = entering ? 1.0 : ior;
        float etaT = entering ? ior : 1.0;

        // Fresnel reflection amount
        float fresnel = fresnelDielectric(dot(N, V), etaI, etaT);

        // Randomly choose between reflection and refraction based on Fresnel
        bool doReflect = randomFloat(seed) < fresnel;

        vec3 newDirection;
        if (doReflect) {
            newDirection = reflect(-V, N);
        } else {
            newDirection = refractRay(-V, N, etaI / etaT);
        }

        // Trace refracted/reflected ray
        vec3 glassOrigin = position + newDirection * 0.002;

        traceRayEXT(
            topLevelAS,
            gl_RayFlagsOpaqueEXT,
            0xFF,
            0, 0, 0,
            glassOrigin,
            0.001,
            newDirection,
            10000.0,
            0
        );

        // Tint the light passing through glass
        vec3 tint = albedo;
        hitValue = hitValue * tint;
        return;
    }

    // ========================================================================
    // Calculate F0 (surface reflection at zero incidence)
    // ========================================================================
    vec3 F0 = vec3(0.04);
    F0 = mix(F0, albedo, metallic);

    // ========================================================================
    // Direct lighting
    // ========================================================================

    // Shadow ray for direct light
    isShadowed = true;
    if (NdotL > 0.0) {
        traceRayEXT(
            topLevelAS,
            gl_RayFlagsTerminateOnFirstHitEXT | gl_RayFlagsOpaqueEXT | gl_RayFlagsSkipClosestHitShaderEXT,
            0xFF,
            0, 0, 1,  // missIndex 1 = shadow miss
            position + normal * 0.001,
            0.001,
            L,
            1000.0,
            1  // payload location for shadow
        );
    }

    float shadow = isShadowed ? 0.15 : 1.0;

    // Cook-Torrance BRDF for direct light
    vec3 H = normalize(V + L);
    float NDF = DistributionGGX(normal, H, roughness);
    float G = GeometrySmith(normal, V, L, roughness);
    vec3 F = fresnelSchlick(max(dot(H, V), 0.0), F0);

    vec3 kS = F;
    vec3 kD = (vec3(1.0) - kS) * (1.0 - metallic);

    vec3 numerator = NDF * G * F;
    float denominator = 4.0 * NdotV * NdotL + 0.0001;
    vec3 specular = numerator / denominator;

    // Sun light (warm directional light)
    vec3 sunColor = vec3(1.0, 0.98, 0.92) * 4.0;
    vec3 directLo = (kD * albedo / PI + specular) * sunColor * NdotL * shadow;

    // ========================================================================
    // Indirect lighting (GI with path tracing)
    // ========================================================================
    vec3 indirectLo = vec3(0.0);

    // Choose between diffuse and specular bounce based on material
    vec3 fresnel = fresnelSchlickRoughness(NdotV, F0, roughness);
    float specularChance = (fresnel.r + fresnel.g + fresnel.b) / 3.0;
    specularChance = mix(specularChance, 1.0, metallic);  // Metals are fully specular

    bool doSpecular = randomFloat(seed) < specularChance;

    vec3 bounceDirection;
    float pdf;

    if (doSpecular) {
        // Specular bounce - importance sample GGX
        vec2 Xi = randomVec2(seed);
        vec3 H = importanceSampleGGX(Xi, normal, roughness);
        bounceDirection = reflect(-V, H);

        // Avoid sampling below hemisphere
        if (dot(bounceDirection, normal) <= 0.0) {
            bounceDirection = cosineSampleHemisphere(normal, seed);
        }
    } else {
        // Diffuse bounce - cosine weighted sampling
        bounceDirection = cosineSampleHemisphere(normal, seed);
    }

    // Trace indirect ray
    vec3 indirectOrigin = position + normal * 0.001;

    traceRayEXT(
        topLevelAS,
        gl_RayFlagsOpaqueEXT,
        0xFF,
        0, 0, 0,
        indirectOrigin,
        0.001,
        bounceDirection,
        10000.0,
        0
    );

    // The hitValue now contains the result from the bounce
    vec3 bounceRadiance = hitValue;

    // Compute indirect contribution
    float NdotBounce = max(dot(normal, bounceDirection), 0.0);

    if (doSpecular) {
        // Specular contribution
        vec3 H = normalize(V + bounceDirection);
        vec3 F_indirect = fresnelSchlick(max(dot(H, V), 0.0), F0);
        indirectLo = bounceRadiance * F_indirect;
    } else {
        // Diffuse contribution
        vec3 kD_indirect = (vec3(1.0) - fresnel) * (1.0 - metallic);
        indirectLo = bounceRadiance * kD_indirect * albedo;
    }

    // ========================================================================
    // Ambient occlusion and sky lighting
    // ========================================================================

    // Simple hemisphere ambient from sky
    vec3 skyUp = sampleSky(normal);
    vec3 skyAmbient = skyUp * 0.15 * albedo * ao;

    // ========================================================================
    // Emission
    // ========================================================================
    vec3 emissive = albedo * emission * 10.0;

    // ========================================================================
    // Final composition
    // ========================================================================
    vec3 color = directLo + indirectLo + skyAmbient + emissive;

    hitValue = color;
}
