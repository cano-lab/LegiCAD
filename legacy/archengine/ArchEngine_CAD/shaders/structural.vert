#version 450

// Vertex attributes (binding 0 - per vertex)
layout(location = 0) in vec3 inPosition;
layout(location = 1) in vec3 inNormal;
layout(location = 2) in vec3 inColor;
layout(location = 3) in vec2 inTexCoord;
layout(location = 4) in float inStress;

// Uniform buffer
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

// Push constants
layout(push_constant) uniform PushConstants {
    mat4 model;
    vec4 color;      // RGB = albedo override, A = stress
    vec4 material;   // x = metallic, y = roughness, z = ao, w = emission
} push;

// Output to fragment shader
layout(location = 0) out vec3 fragColor;
layout(location = 1) out vec3 fragNormal;
layout(location = 2) out vec3 fragPosition;
layout(location = 3) out float fragStress;
layout(location = 4) out vec4 fragLightSpacePos;
layout(location = 5) out vec4 fragMaterial;

void main() {
    mat4 modelMatrix = push.model;
    vec4 colorData = push.color;

    // Transform position
    vec4 worldPos = modelMatrix * vec4(inPosition, 1.0);
    gl_Position = ubo.proj * ubo.view * worldPos;

    // Transform normal to world space
    mat3 normalMatrix = transpose(inverse(mat3(modelMatrix)));
    fragNormal = normalize(normalMatrix * inNormal);

    // Pass through data
    fragPosition = worldPos.xyz;
    fragColor = inColor;

    // Extract stress from color data (stored in alpha)
    fragStress = colorData.a;

    // Override color with push color if it's not default
    if (colorData.r > 0.01 || colorData.g > 0.01 || colorData.b > 0.01) {
        fragColor = colorData.rgb;
    }

    // Light space position for shadow mapping
    fragLightSpacePos = ubo.lightViewProj * worldPos;

    // Pass material properties to fragment shader
    fragMaterial = push.material;

    // Clip distance for section clipping
    // Always write a value to avoid undefined behavior
    if (ubo.enableClipping != 0u) {
        gl_ClipDistance[0] = dot(worldPos, ubo.clipPlane);
    } else {
        gl_ClipDistance[0] = 1.0;  // Positive = not clipped
    }
}