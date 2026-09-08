#version 450

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

layout(location = 0) out vec3 viewDir;

// Fullscreen triangle - no vertex input needed
void main() {
    vec2 positions[3] = vec2[](
        vec2(-1.0, -1.0),
        vec2( 3.0, -1.0),
        vec2(-1.0,  3.0)
    );

    vec2 pos = positions[gl_VertexIndex];
    gl_Position = vec4(pos, 0.9999, 1.0);  // Far plane

    // Unproject from clip space to world space
    mat4 invViewProj = inverse(ubo.proj * ubo.view);

    // Unproject two points along the ray and compute direction
    vec4 nearPoint = invViewProj * vec4(pos, -1.0, 1.0);
    vec4 farPoint = invViewProj * vec4(pos, 1.0, 1.0);

    nearPoint /= nearPoint.w;
    farPoint /= farPoint.w;

    vec3 dir = normalize(farPoint.xyz - nearPoint.xyz);

    // Apply correction rotation around forward axis (roll correction ~-7 degrees)
    float angle = radians(-7.0);
    float c = cos(angle);
    float s = sin(angle);

    // Get the forward direction from view matrix
    vec3 forward = -vec3(ubo.view[0][2], ubo.view[1][2], ubo.view[2][2]);
    forward = normalize(forward);

    // Rodrigues rotation formula around forward axis
    viewDir = dir * c + cross(forward, dir) * s + forward * dot(forward, dir) * (1.0 - c);
}
