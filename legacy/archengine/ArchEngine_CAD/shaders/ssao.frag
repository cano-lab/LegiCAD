#version 450

layout(location = 0) in vec2 fragTexCoord;
layout(location = 0) out float outOcclusion;

// Input textures
layout(set = 0, binding = 0) uniform sampler2D depthTexture;
layout(set = 0, binding = 1) uniform sampler2D normalTexture;
layout(set = 0, binding = 2) uniform sampler2D noiseTexture;

// SSAO parameters
layout(set = 0, binding = 3) uniform SSAOParams {
    mat4 projection;
    mat4 view;
    vec4 samples[64];  // Hemisphere samples
    vec4 params;       // x=radius, y=bias, z=intensity, w=power
    vec2 noiseScale;   // Screen dimensions / noise texture size
    int kernelSize;
    float _padding;
} ssao;

// Reconstruct view-space position from depth
vec3 reconstructPosition(vec2 uv, float depth) {
    // Convert UV to NDC
    vec4 clipPos = vec4(uv * 2.0 - 1.0, depth, 1.0);

    // Unproject to view space
    vec4 viewPos = inverse(ssao.projection) * clipPos;
    return viewPos.xyz / viewPos.w;
}

// Reconstruct normal from depth buffer using derivatives
vec3 reconstructNormal(vec2 uv) {
    vec2 texelSize = 1.0 / textureSize(depthTexture, 0);

    float depthC = texture(depthTexture, uv).r;
    float depthL = texture(depthTexture, uv - vec2(texelSize.x, 0)).r;
    float depthR = texture(depthTexture, uv + vec2(texelSize.x, 0)).r;
    float depthT = texture(depthTexture, uv - vec2(0, texelSize.y)).r;
    float depthB = texture(depthTexture, uv + vec2(0, texelSize.y)).r;

    vec3 posC = reconstructPosition(uv, depthC);
    vec3 posL = reconstructPosition(uv - vec2(texelSize.x, 0), depthL);
    vec3 posR = reconstructPosition(uv + vec2(texelSize.x, 0), depthR);
    vec3 posT = reconstructPosition(uv - vec2(0, texelSize.y), depthT);
    vec3 posB = reconstructPosition(uv + vec2(0, texelSize.y), depthB);

    // Use the smaller delta for better edges
    vec3 ddx = (abs(depthR - depthC) < abs(depthC - depthL)) ? (posR - posC) : (posC - posL);
    vec3 ddy = (abs(depthB - depthC) < abs(depthC - depthT)) ? (posB - posC) : (posC - posT);

    vec3 normal = normalize(cross(ddy, ddx));
    return normal;
}

void main() {
    float depth = texture(depthTexture, fragTexCoord).r;

    // Skip sky/far plane
    if (depth >= 1.0) {
        outOcclusion = 1.0;
        return;
    }

    // Reconstruct view-space position and normal
    vec3 fragPos = reconstructPosition(fragTexCoord, depth);
    vec3 normal = reconstructNormal(fragTexCoord);

    // Sample noise for random rotation
    vec3 randomVec = texture(noiseTexture, fragTexCoord * ssao.noiseScale).xyz;

    // Create TBN matrix for hemisphere orientation
    vec3 tangent = normalize(randomVec - normal * dot(randomVec, normal));
    vec3 bitangent = cross(normal, tangent);
    mat3 TBN = mat3(tangent, bitangent, normal);

    // Sample hemisphere and accumulate occlusion
    float occlusion = 0.0;
    float radius = ssao.params.x;
    float bias = ssao.params.y;

    for (int i = 0; i < ssao.kernelSize; i++) {
        // Get sample position in view space
        vec3 sampleDir = TBN * ssao.samples[i].xyz;
        vec3 samplePos = fragPos + sampleDir * radius;

        // Project sample to screen space
        vec4 offset = ssao.projection * vec4(samplePos, 1.0);
        offset.xyz /= offset.w;
        offset.xy = offset.xy * 0.5 + 0.5;

        // Sample depth at this position
        float sampleDepth = texture(depthTexture, offset.xy).r;
        vec3 sampleViewPos = reconstructPosition(offset.xy, sampleDepth);

        // Range check to prevent false occlusion from distant objects
        float rangeCheck = smoothstep(0.0, 1.0, radius / abs(fragPos.z - sampleViewPos.z));

        // Check if sample is occluded
        occlusion += (sampleViewPos.z >= samplePos.z + bias ? 1.0 : 0.0) * rangeCheck;
    }

    // Average and invert (1 = no occlusion, 0 = full occlusion)
    occlusion = 1.0 - (occlusion / float(ssao.kernelSize));

    // Apply intensity and power curve
    occlusion = pow(occlusion, ssao.params.w) * ssao.params.z;
    occlusion = clamp(occlusion, 0.0, 1.0);

    outOcclusion = occlusion;
}
