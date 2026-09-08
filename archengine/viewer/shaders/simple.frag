#version 450

// simple.frag — demo-milestone shader (NOT a legacy port), pairs with
// simple.vert. Single directional light (Lambert + ambient), stress
// colouring from the C++ scheme (green → yellow → red as stress → 1+).

layout(location = 0) in vec3 fragColor;
layout(location = 1) in vec3 fragNormal;
layout(location = 2) in float fragStress;

layout(std140, set = 0, binding = 0) uniform SimpleUbo {
    mat4 view;
    mat4 proj;
    vec4 lightDirection;
} ubo;

layout(location = 0) out vec4 outColor;

// C++ stress visualization ramp (applyStressColoring / StressColors):
// 0 = green, 0.5 = yellow, 1 = red, >1 = saturated red.
vec3 stressColor(float s) {
    s = clamp(s, 0.0, 1.0);
    return mix(vec3(0.1, 0.8, 0.2), vec3(1.0, 0.1, 0.05), s);
}

void main() {
    vec3 base = fragColor;
    if (fragStress > 0.001) {
        base = stressColor(fragStress);
    }

    vec3 n = normalize(fragNormal);
    vec3 l = normalize(-ubo.lightDirection.xyz);
    float diffuse = max(dot(n, l), 0.0);
    float ambient = 0.25;
    vec3 lit = base * (ambient + (1.0 - ambient) * diffuse) * ubo.lightDirection.w;

    // Gamma to match the swapchain's SRGB surface (as the C++ composite).
    outColor = vec4(pow(lit, vec3(1.0 / 2.2)), 1.0);
}
