#version 450

// Tessellation Control Shader for shadow pass
// Subdivides triangles for displacement mapping in shadow generation

layout(vertices = 3) out;

// Input from vertex shader
layout(location = 0) in vec3 inPosition[];
layout(location = 1) in vec3 inNormal[];
layout(location = 2) in vec2 inTexCoord[];

// Output to tessellation evaluation shader
layout(location = 0) out vec3 outPosition[];
layout(location = 1) out vec3 outNormal[];
layout(location = 2) out vec2 outTexCoord[];

// Push constants - need tessellation level
layout(push_constant) uniform ShadowPushConstants {
    mat4 lightViewProj;
    mat4 model;
    float tessLevel;
    float dispScale;
    float uvScale;
    float padding;
} push;

void main() {
    // Pass through vertex data
    outPosition[gl_InvocationID] = inPosition[gl_InvocationID];
    outNormal[gl_InvocationID] = inNormal[gl_InvocationID];
    outTexCoord[gl_InvocationID] = inTexCoord[gl_InvocationID];

    // Set tessellation levels (only first invocation)
    if (gl_InvocationID == 0) {
        float level = push.tessLevel;

        gl_TessLevelOuter[0] = level;
        gl_TessLevelOuter[1] = level;
        gl_TessLevelOuter[2] = level;
        gl_TessLevelInner[0] = level;
    }
}
