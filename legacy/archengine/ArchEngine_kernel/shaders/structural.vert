#version 450

// Vertex attributes (binding 0 - per vertex)
layout(location = 0) in vec3 inPosition;
layout(location = 1) in vec3 inNormal;
layout(location = 2) in vec3 inColor;
layout(location = 3) in vec2 inTexCoord;
layout(location = 4) in float inStress;

// Shared UBO definition
#include "include/ubo.glsl"

// Push constants (per-draw data including element overrides)
layout(push_constant) uniform PushConstants {
    mat4 model;
    vec4 color;          // RGB = albedo override, A = stress
    vec4 material;       // x = metallic, y = roughness, z = ao, w = emission
    uint overrideMask;   // Which overrides are active
    float _pad1, _pad2, _pad3;  // Padding for vec4 alignment
    vec4 overrides1;     // x=uvScale, y=normalStrength, z=brightness, w=contrast
    vec4 overrides2;     // x=saturation, y=roughness, z=metallic, w=aoStrength
    vec4 overrides3;     // rgb=tint, w=uvRotation (radians)
} push;

// Output to fragment shader
layout(location = 0) out vec3 fragColor;
layout(location = 1) out vec3 fragNormal;
layout(location = 2) out vec3 fragPosition;
layout(location = 3) out float fragStress;
layout(location = 4) out vec4 fragLightSpacePos;
layout(location = 5) out vec4 fragMaterial;
layout(location = 6) out vec2 fragTexCoord;

// Explicitly declare gl_ClipDistance array size for multi-plane clipping
out float gl_ClipDistance[6];

void main() {
    mat4 modelMatrix = push.model;
    vec4 colorData = push.color;

    // Transform position
    vec4 worldPos = modelMatrix * vec4(inPosition, 1.0);
    gl_Position = ubo.proj * ubo.view * worldPos;

    // Transform normal to world space
    // For orthonormal transforms (rotation + translation) or uniform scaling,
    // we can use the model matrix directly - normalize() handles uniform scaling
    fragNormal = normalize(mat3(modelMatrix) * inNormal);

    // Pass through data
    fragPosition = worldPos.xyz;

    // Extract stress from color data (stored in alpha)
    fragStress = colorData.a;

    // Set color from push constant or default white (will be multiplied with texture)
    if (colorData.r > 0.01 || colorData.g > 0.01 || colorData.b > 0.01) {
        fragColor = colorData.rgb;
    } else {
        fragColor = vec3(1.0);  // Default white so texture shows correctly
    }

    // Light space position for shadow mapping (first shadow map layer, for compatibility)
    fragLightSpacePos = ubo.lightViewProj[0] * worldPos;

    // Pass material properties to fragment shader
    fragMaterial = push.material;

    // Pass texture coordinates (for material textures)
    fragTexCoord = inTexCoord;

    // Clip distances for section clipping (up to 6 planes for section box)
    // Each plane clips fragments on its negative side
    // For section box: use 6 planes to define a 3D bounding region
    for (uint i = 0u; i < MAX_CLIP_PLANES; i++) {
        if (i < ubo.numClipPlanes && (ubo.enableClipping & (1u << i)) != 0u) {
            // Plane equation: ax + by + cz + d = 0
            // clipPlane.xyz = normal, clipPlane.w = -d (distance from origin)
            gl_ClipDistance[i] = dot(worldPos, ubo.clipPlanes[i]);
        } else {
            gl_ClipDistance[i] = 1.0;  // Positive = not clipped (plane disabled)
        }
    }
}
