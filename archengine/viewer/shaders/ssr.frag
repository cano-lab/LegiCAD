#version 450

/**
 * Screen-Space Reflections (SSR) Shader
 *
 * Performs ray marching in screen space to find reflections.
 * Uses hierarchical tracing with binary search refinement for accuracy.
 */

layout(location = 0) in vec2 fragTexCoord;

// Output: RGB = reflection color, A = confidence/hit (0 = miss, 1 = hit)
layout(location = 0) out vec4 outReflection;

// Input textures from G-buffer
layout(set = 0, binding = 0) uniform sampler2D hdrScene;      // HDR color
layout(set = 0, binding = 1) uniform sampler2D normalRough;   // xyz = normal (packed), w = roughness
layout(set = 0, binding = 2) uniform sampler2D depthTexture;  // Depth buffer

// SSR parameters
layout(push_constant) uniform SSRParams {
    mat4 projection;
    mat4 invProjection;
    mat4 view;
    vec4 params;    // x = maxDistance, y = thickness, z = stride, w = iterations
    vec4 params2;   // x = fadeStart, y = fadeEnd, z = jitter, w = unused
} ssr;

// Constants
const int MAX_ITERATIONS = 64;
const int BINARY_SEARCH_ITERATIONS = 8;

// Reconstruct view-space position from depth
vec3 reconstructViewPos(vec2 uv, float depth) {
    vec4 clipPos = vec4(uv * 2.0 - 1.0, depth, 1.0);
    vec4 viewPos = ssr.invProjection * clipPos;
    return viewPos.xyz / viewPos.w;
}

// Project view-space position to screen UV
vec3 projectToScreen(vec3 viewPos) {
    vec4 clipPos = ssr.projection * vec4(viewPos, 1.0);
    clipPos.xyz /= clipPos.w;
    return vec3(clipPos.xy * 0.5 + 0.5, clipPos.z);
}

// Linear interpolation for binary search
float linearizeDepth(float depth, float near, float far) {
    return near * far / (far - depth * (far - near));
}

// Check if UV is within screen bounds
bool isInsideScreen(vec2 uv) {
    return uv.x >= 0.0 && uv.x <= 1.0 && uv.y >= 0.0 && uv.y <= 1.0;
}

// SSR ray march with binary search refinement
vec4 traceSSR(vec3 viewPos, vec3 viewDir, float roughness) {
    float maxDistance = ssr.params.x;
    float thickness = ssr.params.y;
    float stride = ssr.params.z;
    int iterations = int(ssr.params.w);

    // Clamp iterations
    iterations = min(iterations, MAX_ITERATIONS);

    // Ray direction in view space
    vec3 rayDir = normalize(viewDir);

    // Start position
    vec3 rayPos = viewPos;

    // Adaptive stride based on roughness (rougher = larger stride for performance)
    float adaptiveStride = stride * (1.0 + roughness * 2.0);

    // Initial step
    vec3 rayStep = rayDir * adaptiveStride;

    // March through screen space
    vec2 hitUV = vec2(0.0);
    float hitDepth = 0.0;
    bool hit = false;

    for (int i = 0; i < iterations && !hit; i++) {
        rayPos += rayStep;

        // Project to screen
        vec3 screenPos = projectToScreen(rayPos);

        // Check bounds
        if (!isInsideScreen(screenPos.xy)) {
            break;
        }

        // Sample depth
        float sceneDepth = texture(depthTexture, screenPos.xy).r;

        // Check intersection
        if (screenPos.z > sceneDepth && screenPos.z - sceneDepth < thickness) {
            hitUV = screenPos.xy;
            hitDepth = sceneDepth;
            hit = true;
        }

        // Increase stride as we go further (hierarchical stepping)
        rayStep *= 1.02;
    }

    // Binary search refinement
    if (hit) {
        vec3 minPos = rayPos - rayStep;
        vec3 maxPos = rayPos;

        for (int i = 0; i < BINARY_SEARCH_ITERATIONS; i++) {
            vec3 midPos = (minPos + maxPos) * 0.5;
            vec3 screenPos = projectToScreen(midPos);

            if (!isInsideScreen(screenPos.xy)) {
                break;
            }

            float sceneDepth = texture(depthTexture, screenPos.xy).r;

            if (screenPos.z > sceneDepth) {
                maxPos = midPos;
                hitUV = screenPos.xy;
            } else {
                minPos = midPos;
            }
        }
    }

    if (!hit) {
        return vec4(0.0);
    }

    // Sample reflected color
    vec3 reflectedColor = texture(hdrScene, hitUV).rgb;

    // Calculate confidence based on various factors
    float confidence = 1.0;

    // Fade based on distance from screen edges
    float fadeStart = ssr.params2.x;
    float fadeEnd = ssr.params2.y;

    vec2 edgeDist = abs(hitUV - 0.5) * 2.0;  // 0 at center, 1 at edge
    float edgeFade = 1.0 - smoothstep(fadeStart, fadeEnd, max(edgeDist.x, edgeDist.y));
    confidence *= edgeFade;

    // Fade based on roughness (rough surfaces have less sharp reflections)
    float roughnessFade = 1.0 - smoothstep(0.3, 0.8, roughness);
    confidence *= roughnessFade;

    // Fade based on ray distance (far reflections are less reliable)
    float rayDistance = length(rayPos - viewPos);
    float distanceFade = 1.0 - smoothstep(maxDistance * 0.5, maxDistance, rayDistance);
    confidence *= distanceFade;

    return vec4(reflectedColor, confidence);
}

void main() {
    // Sample G-buffer
    float depth = texture(depthTexture, fragTexCoord).r;

    // Skip sky (depth = 1.0 or very close)
    if (depth > 0.9999) {
        outReflection = vec4(0.0);
        return;
    }

    // Get normal and roughness
    vec4 normalData = texture(normalRough, fragTexCoord);
    vec3 normal = normalData.rgb * 2.0 - 1.0;  // Unpack from [0,1] to [-1,1]
    normal = normalize(normal);
    float roughness = normalData.a;

    // Skip very rough surfaces (no visible reflections)
    if (roughness > 0.85) {
        outReflection = vec4(0.0);
        return;
    }

    // Reconstruct view-space position
    vec3 viewPos = reconstructViewPos(fragTexCoord, depth);

    // View direction (in view space, looking toward -Z)
    vec3 viewDir = normalize(viewPos);

    // Transform normal to view space
    vec3 viewNormal = normalize((ssr.view * vec4(normal, 0.0)).xyz);

    // Calculate reflection direction
    vec3 reflectDir = reflect(viewDir, viewNormal);

    // Don't trace reflections pointing away from camera
    if (reflectDir.z > 0.0) {
        outReflection = vec4(0.0);
        return;
    }

    // Trace SSR
    outReflection = traceSSR(viewPos, reflectDir, roughness);
}
