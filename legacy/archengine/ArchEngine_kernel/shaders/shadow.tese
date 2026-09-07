#version 450

// Tessellation Evaluation Shader for shadow pass
// Samples height map and displaces vertices for accurate shadow casting

layout(triangles, equal_spacing, ccw) in;

// Input from tessellation control shader
layout(location = 0) in vec3 inPosition[];
layout(location = 1) in vec3 inNormal[];
layout(location = 2) in vec2 inTexCoord[];

// Push constants
layout(push_constant) uniform ShadowPushConstants {
    mat4 lightViewProj;
    mat4 model;
    float tessLevel;
    float dispScale;
    float uvScale;
    float padding;
} push;

// Height map sampler
layout(set = 0, binding = 0) uniform sampler2D heightMap;

// Interpolate using barycentric coordinates
vec3 interpolate3(vec3 v0, vec3 v1, vec3 v2) {
    return gl_TessCoord.x * v0 + gl_TessCoord.y * v1 + gl_TessCoord.z * v2;
}

vec2 interpolate2(vec2 v0, vec2 v1, vec2 v2) {
    return gl_TessCoord.x * v0 + gl_TessCoord.y * v1 + gl_TessCoord.z * v2;
}

void main() {
    // Interpolate vertex attributes
    vec3 position = interpolate3(inPosition[0], inPosition[1], inPosition[2]);
    vec3 normal = normalize(interpolate3(inNormal[0], inNormal[1], inNormal[2]));
    vec2 texCoord = interpolate2(inTexCoord[0], inTexCoord[1], inTexCoord[2]);

    // Apply UV scale
    vec2 scaledTexCoord = texCoord * push.uvScale;

    // Sample height map and displace
    if (push.dispScale > 0.0) {
        float height = texture(heightMap, scaledTexCoord).r;
        height = height - 0.5;  // Center around 0
        position += normal * (height * push.dispScale);
    }

    // Transform to light clip space
    gl_Position = push.lightViewProj * push.model * vec4(position, 1.0);
}
