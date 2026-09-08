#version 450

layout(location = 0) in vec3 viewDir;
layout(location = 0) out vec4 outColor;

// Push constants for sky
layout(push_constant) uniform SkyPushConstants {
    vec4 sunDirection;  // xyz = direction, w = useHdr flag
} sky;

// Environment cubemap (for HDR mode)
layout(set = 0, binding = 1) uniform samplerCube envMap;

// Procedural sky colors
const vec3 dayZenith = vec3(0.4, 0.6, 0.9);
const vec3 dayHorizon = vec3(0.7, 0.8, 0.95);
const vec3 sunsetZenith = vec3(0.2, 0.15, 0.4);
const vec3 sunsetHorizon = vec3(1.0, 0.5, 0.2);
const vec3 nightZenith = vec3(0.02, 0.02, 0.05);
const vec3 nightHorizon = vec3(0.05, 0.05, 0.1);

const vec3 dayGround = vec3(0.35, 0.45, 0.3);
const vec3 dayGroundFar = vec3(0.4, 0.5, 0.45);
const vec3 sunsetGround = vec3(0.3, 0.25, 0.2);
const vec3 sunsetGroundFar = vec3(0.4, 0.3, 0.25);
const vec3 nightGround = vec3(0.05, 0.06, 0.05);
const vec3 nightGroundFar = vec3(0.08, 0.08, 0.1);

void main() {
    vec3 dir = normalize(viewDir);
    float sunElevation = -sky.sunDirection.y;
    bool useHdr = sky.sunDirection.w > 0.5;

    vec3 finalColor;

    if (useHdr) {
        // Sample from HDR environment cubemap
        finalColor = texture(envMap, dir).rgb;
        finalColor = finalColor / (finalColor + vec3(1.0));  // Reinhard tonemap
    } else {
        // Procedural sky - use dir.y directly for horizon detection
        vec3 zenithColor, horizonColor, groundColor, groundFarColor;

        if (sunElevation > 0.7) {
            zenithColor = dayZenith;
            horizonColor = dayHorizon;
            groundColor = dayGround;
            groundFarColor = dayGroundFar;
        } else if (sunElevation > 0.2) {
            float t = (sunElevation - 0.2) / 0.5;
            zenithColor = mix(sunsetZenith, dayZenith, t);
            horizonColor = mix(sunsetHorizon, dayHorizon, t);
            groundColor = mix(sunsetGround, dayGround, t);
            groundFarColor = mix(sunsetGroundFar, dayGroundFar, t);
        } else if (sunElevation > 0.0) {
            float t = sunElevation / 0.2;
            zenithColor = mix(nightZenith, sunsetZenith, t);
            horizonColor = mix(nightHorizon, sunsetHorizon, t);
            groundColor = mix(nightGround, sunsetGround, t);
            groundFarColor = mix(nightGroundFar, sunsetGroundFar, t);
        } else {
            zenithColor = nightZenith;
            horizonColor = nightHorizon;
            groundColor = nightGround;
            groundFarColor = nightGroundFar;
        }

        if (dir.y > 0.0) {
            // Sky
            float skyT = pow(dir.y, 0.8);
            finalColor = mix(horizonColor, zenithColor, skyT);

            // Sun glow
            vec3 sunDir = normalize(sky.sunDirection.xyz);
            float sunDot = dot(dir, -sunDir);
            float sunGlow = pow(max(0.0, sunDot), 64.0) * 2.0;
            sunGlow += pow(max(0.0, sunDot), 8.0) * 0.5;
            vec3 sunColor = mix(vec3(1.0, 0.4, 0.1), vec3(1.0, 0.95, 0.8), clamp(sunElevation * 2.0, 0.0, 1.0));
            finalColor += sunGlow * sunColor * step(0.0, sunElevation);
        } else {
            // Ground
            float groundT = pow(-dir.y, 0.5);
            finalColor = mix(groundFarColor, groundColor, groundT);
            float horizonFog = 1.0 - smoothstep(0.0, 0.1, -dir.y);
            finalColor = mix(finalColor, horizonColor * 0.8, horizonFog * 0.6);
        }
    }

    // Gamma correction
    finalColor = pow(finalColor, vec3(1.0 / 2.2));

    outColor = vec4(finalColor, 1.0);
}
