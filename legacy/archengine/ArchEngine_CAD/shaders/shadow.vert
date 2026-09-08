#version 450

// Vertex attributes (binding 0 - per vertex)
layout(location = 0) in vec3 inPosition;
layout(location = 1) in vec3 inNormal;      // Unused but must be declared
layout(location = 2) in vec3 inColor;       // Unused but must be declared
layout(location = 3) in vec2 inTexCoord;    // Unused but must be declared
layout(location = 4) in float inStress;     // Unused but must be declared

// Push constants for shadow pass
layout(push_constant) uniform ShadowPushConstants {
    mat4 lightViewProj;
    mat4 model;
} push;

void main() {
    // Transform position directly to light clip space
    gl_Position = push.lightViewProj * push.model * vec4(inPosition, 1.0);
}
