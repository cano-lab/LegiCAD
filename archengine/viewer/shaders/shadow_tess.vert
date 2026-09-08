#version 450

// Vertex shader for tessellated shadow pass
// Must output data for the tessellation control shader

// Vertex attributes (binding 0 - per vertex)
layout(location = 0) in vec3 inPosition;
layout(location = 1) in vec3 inNormal;
layout(location = 2) in vec3 inColor;       // Unused but must be declared
layout(location = 3) in vec2 inTexCoord;
layout(location = 4) in float inStress;     // Unused but must be declared

// Outputs to tessellation control shader
layout(location = 0) out vec3 outPosition;
layout(location = 1) out vec3 outNormal;
layout(location = 2) out vec2 outTexCoord;

// Push constants for shadow pass
layout(push_constant) uniform ShadowPushConstants {
    mat4 lightViewProj;
    mat4 model;
    float tessLevel;
    float dispScale;
    float uvScale;
    float padding;
} push;

void main() {
    // Transform position to world space for tessellation
    vec4 worldPos = push.model * vec4(inPosition, 1.0);
    outPosition = worldPos.xyz;

    // Transform normal to world space
    outNormal = normalize(mat3(push.model) * inNormal);

    // Pass through texture coordinates
    outTexCoord = inTexCoord;

    // gl_Position will be computed in tessellation evaluation shader
    // But we still need to set it here for the pipeline
    gl_Position = push.lightViewProj * worldPos;
}
