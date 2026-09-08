#version 460
#extension GL_EXT_ray_tracing : require

layout(binding = 2, set = 0) uniform CameraUBO {
    mat4 viewInverse;
    mat4 projInverse;
    mat4 prevViewProj;
    vec4 lightDir;
    vec4 cameraPos;
    uint frameCount;
    uint sampleCount;
    float time;
    float exposure;
    uint enableDenoising;
    float denoiseStrength;
    float pad[2];
} camera;

layout(location = 0) rayPayloadInEXT vec3 hitValue;

void main() {
    // Sky gradient based on ray direction
    vec3 direction = gl_WorldRayDirectionEXT;

    // Simple sky gradient from horizon to zenith
    float t = 0.5 * (direction.y + 1.0);

    // Horizon color (light gray/white)
    vec3 horizonColor = vec3(0.9, 0.92, 0.95);
    // Zenith color (light blue)
    vec3 zenithColor = vec3(0.5, 0.7, 0.9);

    // Ground color (darker)
    vec3 groundColor = vec3(0.3, 0.3, 0.3);

    if (direction.y < 0.0) {
        // Below horizon - blend to ground
        float groundT = -direction.y;
        hitValue = mix(horizonColor, groundColor, groundT);
    } else {
        // Above horizon - sky gradient
        hitValue = mix(horizonColor, zenithColor, t);
    }

    // Add sun disc
    vec3 sunDir = normalize(-camera.lightDir.xyz);
    float sunDot = dot(direction, sunDir);
    if (sunDot > 0.995) {
        // Sun disc
        hitValue = vec3(1.0, 0.98, 0.9) * 2.0;
    } else if (sunDot > 0.98) {
        // Sun glow
        float glow = (sunDot - 0.98) / 0.015;
        hitValue = mix(hitValue, vec3(1.0, 0.95, 0.8), glow * 0.5);
    }
}
