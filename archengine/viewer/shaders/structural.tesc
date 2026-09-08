#version 450

// Tessellation Control Shader for displacement mapping
// Controls tessellation level based on distance and screen-space edge length

layout(vertices = 3) out;

// Inputs from vertex shader (must match vertex shader outputs)
layout(location = 0) in vec3 inFragColor[];
layout(location = 1) in vec3 inFragNormal[];
layout(location = 2) in vec3 inFragPosition[];
layout(location = 3) in float inFragStress[];
layout(location = 4) in vec4 inFragLightSpacePos[];
layout(location = 5) in vec4 inFragMaterial[];
layout(location = 6) in vec2 inFragTexCoord[];

// Outputs to tessellation evaluation shader
layout(location = 0) out vec3 outFragColor[];
layout(location = 1) out vec3 outFragNormal[];
layout(location = 2) out vec3 outFragPosition[];
layout(location = 3) out float outFragStress[];
layout(location = 4) out vec4 outFragLightSpacePos[];
layout(location = 5) out vec4 outFragMaterial[];
layout(location = 6) out vec2 outFragTexCoord[];

// Shared UBO definition
#include "include/ubo.glsl"

// Compute camera position from inverse view matrix
vec3 getCameraPosition() {
    mat4 invView = inverse(ubo.view);
    return invView[3].xyz;
}

// Compute tessellation level based on edge length in screen space
float screenSpaceEdgeLength(vec3 p0, vec3 p1) {
    vec4 clip0 = ubo.proj * ubo.view * vec4(p0, 1.0);
    vec4 clip1 = ubo.proj * ubo.view * vec4(p1, 1.0);

    // Handle behind-camera cases
    if (clip0.w < 0.001 || clip1.w < 0.001) {
        return 1.0;
    }

    vec2 screen0 = clip0.xy / clip0.w;
    vec2 screen1 = clip1.xy / clip1.w;

    return length(screen1 - screen0) * 500.0; // Scale factor for reasonable tessellation
}

// Compute tessellation level based on distance from camera
float distanceBasedTessLevel(vec3 worldPos) {
    vec3 cameraPos = getCameraPosition();
    float dist = length(worldPos - cameraPos);

    // Tessellation falls off with distance
    float maxDist = 50.0;
    float minDist = 2.0;
    float t = clamp((dist - minDist) / (maxDist - minDist), 0.0, 1.0);

    // Interpolate between max and min tessellation levels
    float maxTess = ubo.tessellationLevel;
    float minTess = 1.0;

    return mix(maxTess, minTess, t * t); // Quadratic falloff
}

void main() {
    // Pass through vertex attributes
    outFragColor[gl_InvocationID] = inFragColor[gl_InvocationID];
    outFragNormal[gl_InvocationID] = inFragNormal[gl_InvocationID];
    outFragPosition[gl_InvocationID] = inFragPosition[gl_InvocationID];
    outFragStress[gl_InvocationID] = inFragStress[gl_InvocationID];
    outFragLightSpacePos[gl_InvocationID] = inFragLightSpacePos[gl_InvocationID];
    outFragMaterial[gl_InvocationID] = inFragMaterial[gl_InvocationID];
    outFragTexCoord[gl_InvocationID] = inFragTexCoord[gl_InvocationID];

    // Only first invocation sets tessellation levels
    if (gl_InvocationID == 0) {
        // Skip tessellation if disabled (level <= 1)
        if (ubo.tessellationLevel <= 1.0 || ubo.displacementScale <= 0.0) {
            gl_TessLevelOuter[0] = 1.0;
            gl_TessLevelOuter[1] = 1.0;
            gl_TessLevelOuter[2] = 1.0;
            gl_TessLevelInner[0] = 1.0;
            return;
        }

        // Compute center of triangle for distance-based tessellation
        vec3 center = (inFragPosition[0] + inFragPosition[1] + inFragPosition[2]) / 3.0;
        float distTess = distanceBasedTessLevel(center);

        // Screen-space edge length for adaptive tessellation
        float edge0 = screenSpaceEdgeLength(inFragPosition[1], inFragPosition[2]);
        float edge1 = screenSpaceEdgeLength(inFragPosition[2], inFragPosition[0]);
        float edge2 = screenSpaceEdgeLength(inFragPosition[0], inFragPosition[1]);

        // Combine distance and edge-based tessellation (take max for quality)
        float tess0 = clamp(max(distTess, edge0), 1.0, ubo.tessellationLevel);
        float tess1 = clamp(max(distTess, edge1), 1.0, ubo.tessellationLevel);
        float tess2 = clamp(max(distTess, edge2), 1.0, ubo.tessellationLevel);

        // Set outer tessellation levels (one per edge)
        gl_TessLevelOuter[0] = tess0;
        gl_TessLevelOuter[1] = tess1;
        gl_TessLevelOuter[2] = tess2;

        // Set inner tessellation level (average of outer levels)
        gl_TessLevelInner[0] = (tess0 + tess1 + tess2) / 3.0;
    }
}
