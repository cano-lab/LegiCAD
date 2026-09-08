#version 450

// simple.vert — demo-milestone shader (NOT a legacy port).
// The legacy `structural.vert` needs the full texture/shadow/IBL stack
// (ubo.glsl MAX_LIGHTS×GPULight, set 1 material maps, set 2 cubemaps);
// this minimal variant renders vertex-color meshes with a single UBO and
// push-constant model/color so the interactive viewer runs before the
// texture and IBL re-adds land (see questions.md A4 checklist).
//
// Vertex layout matches C++ `Vertex::getAttributeDescriptions` exactly
// (48-byte stride).

layout(location = 0) in vec3 inPosition;
layout(location = 1) in vec3 inNormal;
layout(location = 2) in vec3 inColor;
layout(location = 3) in vec2 inTexCoord;
layout(location = 4) in float inStress;

layout(std140, set = 0, binding = 0) uniform SimpleUbo {
    mat4 view;
    mat4 proj;
    vec4 lightDirection;  // xyz = sun dir, w = intensity (matches path tracer)
} ubo;

layout(push_constant) uniform PushConstants {
    mat4 model;
    vec4 color;  // RGB = albedo, A = stress (as structural.vert)
} push;

layout(location = 0) out vec3 fragColor;
layout(location = 1) out vec3 fragNormal;
layout(location = 2) out float fragStress;

void main() {
    vec4 worldPos = push.model * vec4(inPosition, 1.0);
    gl_Position = ubo.proj * ubo.view * worldPos;

    // As structural.vert: model matrix is orthonormal for these elements.
    fragNormal = normalize(mat3(push.model) * inNormal);

    fragStress = push.color.a;
    // As structural.vert: fall back to vertex color when no override.
    bool hasOverride = push.color.r > 0.01 || push.color.g > 0.01 || push.color.b > 0.01;
    fragColor = hasOverride ? push.color.rgb : inColor;
}
