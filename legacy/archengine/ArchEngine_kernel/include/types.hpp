#pragma once

#include <cstdint>
#include <cstddef>
#include <memory>
#include <vector>
#include <array>
#include <string>
#include <optional>
#include <functional>
#include <span>
#include <utility>

#include <vulkan/vulkan.h>

#define GLM_FORCE_RADIANS
#define GLM_FORCE_DEPTH_ZERO_TO_ONE
#define GLM_ENABLE_EXPERIMENTAL
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/type_ptr.hpp>
#include <glm/gtx/hash.hpp>

namespace arch {

// Forward declaration for Light (full definition in lights.hpp)
struct Light;

// Type aliases
using u8  = uint8_t;
using u16 = uint16_t;
using u32 = uint32_t;
using u64 = uint64_t;
using i8  = int8_t;
using i16 = int16_t;
using i32 = int32_t;
using i64 = int64_t;
using f32 = float;
using f64 = double;

using vec2 = glm::vec2;
using vec3 = glm::vec3;
using vec4 = glm::vec4;
using mat3 = glm::mat3;
using mat4 = glm::mat4;
using quat = glm::quat;

// Vertex structure for structural elements
struct Vertex {
    vec3 position;
    vec3 normal;
    vec3 color;      // RGB color (stress visualization)
    vec2 texCoord   = {0.0f, 0.0f};
    f32  stress     = 0.0f;     // Stress/utilization value [0-1+]

    static std::array<VkVertexInputBindingDescription, 1> getBindingDescriptions() {
        return {{
            {0, sizeof(Vertex), VK_VERTEX_INPUT_RATE_VERTEX}
        }};
    }

    static std::array<VkVertexInputAttributeDescription, 5> getAttributeDescriptions() {
        return {{
            {0, 0, VK_FORMAT_R32G32B32_SFLOAT, offsetof(Vertex, position)},
            {1, 0, VK_FORMAT_R32G32B32_SFLOAT, offsetof(Vertex, normal)},
            {2, 0, VK_FORMAT_R32G32B32_SFLOAT, offsetof(Vertex, color)},
            {3, 0, VK_FORMAT_R32G32_SFLOAT,    offsetof(Vertex, texCoord)},
            {4, 0, VK_FORMAT_R32_SFLOAT,       offsetof(Vertex, stress)}
        }};
    }
};

// Instance data for instanced rendering (Phase 3)
// Used for batching multiple objects with the same mesh
struct InstanceData {
    mat4 model;      // Model transformation matrix
    vec4 color;      // RGB color + stress in alpha

    // Binding 1 uses per-instance rate
    static VkVertexInputBindingDescription getBindingDescription() {
        VkVertexInputBindingDescription binding{};
        binding.binding = 1;
        binding.stride = sizeof(InstanceData);
        binding.inputRate = VK_VERTEX_INPUT_RATE_INSTANCE;
        return binding;
    }

    // Instance attributes at locations 5-9 (mat4 = 4 vec4s + color vec4)
    static std::array<VkVertexInputAttributeDescription, 5> getAttributeDescriptions() {
        std::array<VkVertexInputAttributeDescription, 5> attrs{};

        // mat4 model takes locations 5, 6, 7, 8 (one vec4 per row)
        for (u32 i = 0; i < 4; i++) {
            attrs[i].binding = 1;
            attrs[i].location = 5 + i;
            attrs[i].format = VK_FORMAT_R32G32B32A32_SFLOAT;
            attrs[i].offset = sizeof(vec4) * i;
        }

        // vec4 color at location 9
        attrs[4].binding = 1;
        attrs[4].location = 9;
        attrs[4].format = VK_FORMAT_R32G32B32A32_SFLOAT;
        attrs[4].offset = sizeof(mat4);

        return attrs;
    }
};

// Structural element types
enum class ElementType : u32 {
    Beam,       // 0
    Column,     // 1
    Floor,      // 2
    Wall,       // 3
    Foundation, // 4
    Connection, // 5
    Door,       // 6
    Window,     // 7
    Roof        // 8
};

// Custom mesh data (from IFC)
struct MeshData {
    std::vector<vec3> vertices;
    std::vector<std::array<u32, 3>> faces;  // Triangle indices
    bool hasData() const { return !vertices.empty() && !faces.empty(); }
};

// Terrain mesh data (from elevation API)
struct TerrainMesh {
    std::vector<Vertex> vertices;  // Pre-colored vertices (elevation gradient in color)
    std::vector<u32> indices;

    f32 width_ft = 0.0f;           // Original width in feet
    f32 depth_ft = 0.0f;           // Original depth in feet
    f32 min_elevation = 0.0f;      // Minimum elevation (feet)
    f32 max_elevation = 0.0f;      // Maximum elevation (feet)

    bool hasData() const { return !vertices.empty() && !indices.empty(); }

    /**
     * @brief Generate a procedural test terrain
     * @param width_ft Width in feet
     * @param depth_ft Depth in feet
     * @param grid_size Number of vertices per side (e.g., 64 = 64x64 grid)
     * @param base_elevation Base elevation in feet
     * @param height_range Height variation in feet
     * @return TerrainMesh with procedural hills
     */
    static TerrainMesh generateTestTerrain(f32 width_ft, f32 depth_ft, u32 grid_size = 64,
                                           f32 base_elevation = 100.0f, f32 height_range = 50.0f);
};

// Structural element for rendering
struct StructuralElement {
    ElementType type;
    vec3 start;
    vec3 end;
    f32 width;           // Width of the element
    f32 depth;           // Depth of the element
    f32 stress;          // 0.0 = no stress, 1.0 = at limit, >1.0 = failing
    f32 deflection;      // Deflection amount (scaled for visualization)
    std::string material;  // Material name (e.g., "steel", "concrete")
    bool failed;
    MeshData mesh;       // Optional actual mesh geometry from IFC
    f32 rotation = -1000.0f; // Rotation angle in radians (-1000 = not set, use from host wall)
};

// Camera view modes
enum class CameraView : u32 {
    Perspective,
    Top,
    Front,
    Right,
    Left,
    Back
};

// Camera
struct Camera {
    vec3 position   = {0.0f, 5.0f, 20.0f};
    vec3 target     = {0.0f, 0.0f, 0.0f};    // Look-at target
    vec3 up         = {0.0f, 1.0f, 0.0f};
    f32 fov         = 45.0f;
    f32 nearPlane   = 0.1f;
    f32 farPlane    = 1000.0f;
    f32 speed       = 10.0f;
    f32 sensitivity = 0.1f;
    bool isOrthographic = false;
    f32 orthoSize   = 50.0f;  // Half-width for orthographic projection
    CameraView view = CameraView::Perspective;

    mat4 getViewMatrix() const {
        return glm::lookAt(position, target, up);
    }

    mat4 getProjectionMatrix(f32 aspectRatio) const {
        if (isOrthographic) {
            f32 halfWidth = orthoSize;
            f32 halfHeight = orthoSize / aspectRatio;
            return glm::ortho(-halfWidth, halfWidth, -halfHeight, halfHeight, nearPlane, farPlane);
        }
        return glm::perspective(glm::radians(fov), aspectRatio, nearPlane, farPlane);
    }
};

// Serializable camera state for project save/load
struct CameraState {
    vec3 position = {0.0f, 5.0f, 20.0f};
    vec3 target = {0.0f, 0.0f, 0.0f};
    vec3 up = {0.0f, 1.0f, 0.0f};
    f32 fov = 45.0f;
    f32 nearPlane = 0.1f;
    f32 farPlane = 1000.0f;
    f32 speed = 10.0f;
    f32 sensitivity = 0.1f;
    bool isOrthographic = false;
    f32 orthoSize = 50.0f;
    CameraView view = CameraView::Perspective;

    // Convert to Camera for rendering
    Camera toCamera() const {
        Camera cam;
        cam.position = position;
        cam.target = target;
        cam.up = up;
        cam.fov = fov;
        cam.nearPlane = nearPlane;
        cam.farPlane = farPlane;
        cam.speed = speed;
        cam.sensitivity = sensitivity;
        cam.isOrthographic = isOrthographic;
        cam.orthoSize = orthoSize;
        cam.view = view;
        return cam;
    }

    // Create from Camera
    static CameraState fromCamera(const Camera& cam) {
        CameraState state;
        state.position = cam.position;
        state.target = cam.target;
        state.up = cam.up;
        state.fov = cam.fov;
        state.nearPlane = cam.nearPlane;
        state.farPlane = cam.farPlane;
        state.speed = cam.speed;
        state.sensitivity = cam.sensitivity;
        state.isOrthographic = cam.isOrthographic;
        state.orthoSize = cam.orthoSize;
        state.view = cam.view;
        return state;
    }
};

// Maximum number of lights supported in a single frame
constexpr u32 MAX_LIGHTS = 16;

// Maximum number of shadow-casting lights (shadow map array size)
constexpr u32 MAX_SHADOW_MAPS = 4;

// Maximum number of clip planes for section box (6 planes = box)
constexpr u32 MAX_CLIP_PLANES = 6;

// Light types for the multi-light system
enum class LightType : u32 {
    Directional = 0,  // Sun/moon light - parallel rays, no falloff
    Point = 1,        // Omnidirectional light with distance falloff
    Spot = 2          // Cone-shaped light with direction and falloff
};

// GPU-friendly light structure for UBO (matches GLSL layout exactly)
struct GPULight {
    vec4 positionType;      // xyz = world position, w = type (cast to LightType)
    vec4 directionRange;    // xyz = direction (for spot/directional), w = range (for point/spot)
    vec4 colorIntensity;    // rgb = color, a = intensity
    vec4 spotParams;        // x = innerAngle (cos), y = outerAngle (cos), z = shadowIndex (-1 = none), w = reserved
};

// Push constants for shaders (per-draw data including element overrides)
struct PushConstants {
    mat4 model;              // 64 bytes
    vec4 color;              // 16 bytes - RGB = albedo, A = stress
    vec4 material;           // 16 bytes - x = metallic, y = roughness, z = ao, w = emission
    // Per-element overrides (set per draw call for proper GPU sync)
    u32 overrideMask;        // 4 bytes - which overrides are active
    f32 _pad1, _pad2, _pad3; // 12 bytes padding for vec4 alignment
    vec4 overrides1;         // 16 bytes - x=uvScale, y=normalStrength, z=brightness, w=contrast
    vec4 overrides2;         // 16 bytes - x=saturation, y=roughness, z=metallic, w=aoStrength
    vec4 overrides3;         // 16 bytes - rgb=tint, w=unused
    // Total: 160 bytes (most GPUs support 256+)
};

// Uniform buffer object
struct UniformBufferObject {
    mat4 view;
    mat4 proj;
    mat4 lightViewProj[MAX_SHADOW_MAPS];  // Shadow mapping matrices (up to 4 shadow-casting lights)
    vec4 lightDirection;    // Directional light direction (sun)
    vec4 clipPlanes[MAX_CLIP_PLANES];  // Section clipping planes (6 for section box)
    f32 time;
    f32 shadowBias;         // Shadow mapping bias
    u32 enableClipping;     // Section clipping enabled flag (bitmask: bit 0-5 = plane enabled)
    u32 numClipPlanes;      // Number of active clip planes (0-6)
    u32 enableShadows;      // Shadow mapping enabled flag
    u32 outputLinearHDR;    // Output linear HDR (skip tonemapping in shader)
    u32 numShadowMaps;      // Number of active shadow maps (0-4)
    f32 exposure;           // Exposure multiplier for tonemapping
    f32 tessellationLevel;  // Tessellation subdivision level (1-64)
    f32 displacementScale;  // Height map displacement scale
    f32 _padAlign1, _padAlign2;  // Padding to align vec4 to 16-byte boundary (std140)
    vec4 materialParams;    // x = UV scale, y = normal strength, z = brightness, w = contrast
    vec4 materialParams2;   // x = saturation, y = roughnessOffset, z = metallicOffset, w = aoStrength
    vec4 materialTint;      // RGB tint multiplier, w = unused
    vec4 pomParams;         // x = enabled (0/1), y = heightScale, z = minLayers, w = maxLayers
    vec4 iblParams;         // x = overall intensity, y = diffuse intensity, z = specular intensity, w = fresnel intensity
    // Debug visualization
    u32 materialDebugMode;  // 0=None, 1=Displacement, 2=POMDepth, 3=Normals, 4=UVs, 5=AO, 6-11=IBL debug
    // Per-element material overrides (added to global values when override mask bit is set)
    u32 overrideMask;       // Bitfield for which element overrides are active
    // Shader effect flags (for debugging/toggling individual effects)
    u32 effectFlags;        // Bitfield: bit0=IBL, bit1=directLight, bit2=normalMapping
    f32 _pad1;              // Padding to maintain 16-byte alignment for next vec4
    vec4 elementOverride1;  // x = uvScale, y = normalStrength, z = brightness, w = contrast
    vec4 elementOverride2;  // x = saturation, y = roughness, z = metallic, w = aoStrength
    vec4 elementOverride3;  // RGB = tint, w = unused
    // Multiple light sources
    u32 numLights;          // Number of active lights (0-16)
    f32 _pad3, _pad4, _pad5;  // Padding for alignment
    GPULight lights[MAX_LIGHTS];  // Array of lights
};

// Material override mask bits (for PushConstants::overrideMask)
namespace MaterialOverrideBits {
    constexpr u32 UVScale       = (1u << 0);  // Bit 0: UV scale override
    constexpr u32 UVRotation    = (1u << 1);  // Bit 1: UV rotation override
    constexpr u32 NormalStrength = (1u << 2);  // Bit 2: Normal strength override
    constexpr u32 Brightness    = (1u << 3);  // Bit 3: Brightness override
    constexpr u32 Contrast      = (1u << 4);  // Bit 4: Contrast override
    constexpr u32 Saturation    = (1u << 5);  // Bit 5: Saturation override
    constexpr u32 Roughness     = (1u << 6);  // Bit 6: Roughness override
    constexpr u32 Metallic      = (1u << 7);  // Bit 7: Metallic override
    constexpr u32 AOStrength    = (1u << 8);  // Bit 8: AO strength override
    constexpr u32 Tint          = (1u << 9);  // Bit 9: Tint override
}

// Effect flags (for UBO effectFlags - toggles shader features for debugging)
namespace EffectFlags {
    constexpr u32 IBL           = (1u << 0);  // Image-Based Lighting enabled
    constexpr u32 DirectLight   = (1u << 1);  // Direct sun/light contribution enabled
    constexpr u32 NormalMapping = (1u << 2);  // Normal mapping enabled
    constexpr u32 All           = IBL | DirectLight | NormalMapping;  // All effects enabled
}

// Visualization modes
enum class VisualizationMode : u32 {
    Structural,   // Stress/utilization colors
    Thermal,      // Temperature gradient
    Lighting,     // Daylight factor / lux
    Acoustic,     // RT60 / sound levels
    Material,     // Material types
    Wireframe     // Wireframe overlay
};

// Material styles for visual appearance
enum class MaterialStyle : u32 {
    Realistic,    // Full PBR materials (wood grain, metal, glass reflections)
    Clean,        // Clean matte surfaces with subtle shading
    Schematic,    // Flat colors for technical drawings
    Blueprint     // Blue/white blueprint style
};

// Material preset for PBR rendering
struct MaterialPreset {
    vec3 baseColor = vec3(0.8f);
    f32 metallic = 0.0f;
    f32 roughness = 0.5f;
    f32 ao = 1.0f;
    f32 emission = 0.0f;
};

// Predefined material presets
namespace Materials {
    // Wood materials
    inline MaterialPreset OakWood() { return {{0.55f, 0.35f, 0.18f}, 0.0f, 0.7f, 1.0f, 0.0f}; }
    inline MaterialPreset DarkWood() { return {{0.35f, 0.22f, 0.12f}, 0.0f, 0.65f, 1.0f, 0.0f}; }
    inline MaterialPreset PineWood() { return {{0.75f, 0.6f, 0.4f}, 0.0f, 0.75f, 1.0f, 0.0f}; }

    // Metal materials
    inline MaterialPreset Steel() { return {{0.56f, 0.57f, 0.58f}, 0.9f, 0.3f, 1.0f, 0.0f}; }
    inline MaterialPreset Aluminum() { return {{0.91f, 0.92f, 0.92f}, 0.85f, 0.35f, 1.0f, 0.0f}; }
    inline MaterialPreset Brass() { return {{0.7f, 0.55f, 0.2f}, 0.8f, 0.25f, 1.0f, 0.0f}; }
    inline MaterialPreset Copper() { return {{0.72f, 0.45f, 0.2f}, 0.85f, 0.25f, 1.0f, 0.0f}; }

    // Wall materials
    inline MaterialPreset Drywall() { return {{0.9f, 0.88f, 0.85f}, 0.0f, 0.95f, 1.0f, 0.0f}; }
    inline MaterialPreset Brick() { return {{0.6f, 0.25f, 0.15f}, 0.0f, 0.85f, 0.9f, 0.0f}; }
    inline MaterialPreset Concrete() { return {{0.55f, 0.55f, 0.55f}, 0.0f, 0.9f, 0.85f, 0.0f}; }
    inline MaterialPreset Stucco() { return {{0.85f, 0.82f, 0.75f}, 0.0f, 0.92f, 0.95f, 0.0f}; }

    // Glass materials
    inline MaterialPreset Glass() { return {{0.7f, 0.85f, 0.95f}, 0.1f, 0.05f, 1.0f, 0.0f}; }
    inline MaterialPreset TintedGlass() { return {{0.3f, 0.4f, 0.5f}, 0.1f, 0.08f, 1.0f, 0.0f}; }

    // Roof materials
    inline MaterialPreset Asphalt() { return {{0.2f, 0.2f, 0.22f}, 0.0f, 0.85f, 0.8f, 0.0f}; }
    inline MaterialPreset TerracottaTile() { return {{0.7f, 0.35f, 0.2f}, 0.0f, 0.7f, 0.9f, 0.0f}; }
    inline MaterialPreset MetalRoof() { return {{0.4f, 0.42f, 0.45f}, 0.7f, 0.4f, 1.0f, 0.0f}; }

    // Floor materials
    inline MaterialPreset Hardwood() { return {{0.45f, 0.3f, 0.15f}, 0.0f, 0.6f, 1.0f, 0.0f}; }
    inline MaterialPreset Tile() { return {{0.8f, 0.8f, 0.8f}, 0.1f, 0.3f, 1.0f, 0.0f}; }
    inline MaterialPreset Carpet() { return {{0.3f, 0.35f, 0.4f}, 0.0f, 0.98f, 0.9f, 0.0f}; }
}

// Thermal data for elements
struct ThermalData {
    f32 temperature;        // Temperature in F or C
    f32 uValue;            // U-value (thermal transmittance)
    f32 heatLoss;          // Heat loss BTU/hr
    f32 surfaceTemp;       // Surface temperature
};

// Lighting data for spaces
struct LightingData {
    f32 daylightFactor;    // Daylight factor percentage
    f32 illuminanceLux;    // Illuminance in lux
    f32 uniformity;        // Lighting uniformity ratio
    bool meetsCode;        // Code compliance
};

// Acoustic data for spaces
struct AcousticData {
    f32 rt60;              // Reverberation time (seconds)
    f32 absorptionCoeff;   // Average absorption coefficient
    f32 soundLevel;        // Sound pressure level (dB)
    std::string quality;   // Quality assessment
};

// Stress color palette (matches Python visualizations)
namespace StressColors {
    constexpr vec3 SAFE      = {0.133f, 0.773f, 0.369f};  // #22c55e green
    constexpr vec3 WARNING   = {0.918f, 0.702f, 0.031f};  // #eab308 yellow
    constexpr vec3 CRITICAL  = {0.976f, 0.451f, 0.086f};  // #f97316 orange
    constexpr vec3 FAILURE   = {0.937f, 0.267f, 0.267f};  // #ef4444 red

    inline vec3 fromStress(f32 stress) {
        if (stress < 0.7f) return SAFE;
        if (stress < 0.9f) return glm::mix(SAFE, WARNING, (stress - 0.7f) / 0.2f);
        if (stress < 1.0f) return glm::mix(WARNING, CRITICAL, (stress - 0.9f) / 0.1f);
        return glm::mix(CRITICAL, FAILURE, glm::min((stress - 1.0f) / 0.5f, 1.0f));
    }
}

// Thermal color palette (cold to hot)
namespace ThermalColors {
    constexpr vec3 COLD     = {0.118f, 0.565f, 1.000f};  // #1E90FF blue
    constexpr vec3 COOL     = {0.000f, 0.808f, 0.820f};  // #00CED1 cyan
    constexpr vec3 NEUTRAL  = {0.565f, 0.933f, 0.565f};  // #90EE90 light green
    constexpr vec3 WARM     = {1.000f, 0.843f, 0.000f};  // #FFD700 gold
    constexpr vec3 HOT      = {1.000f, 0.271f, 0.000f};  // #FF4500 red-orange

    inline vec3 fromTemperature(f32 temp, f32 minTemp = 50.0f, f32 maxTemp = 90.0f) {
        f32 t = glm::clamp((temp - minTemp) / (maxTemp - minTemp), 0.0f, 1.0f);
        if (t < 0.25f) return glm::mix(COLD, COOL, t * 4.0f);
        if (t < 0.50f) return glm::mix(COOL, NEUTRAL, (t - 0.25f) * 4.0f);
        if (t < 0.75f) return glm::mix(NEUTRAL, WARM, (t - 0.50f) * 4.0f);
        return glm::mix(WARM, HOT, (t - 0.75f) * 4.0f);
    }
}

// Lighting color palette (dark to bright)
namespace LightingColors {
    constexpr vec3 DARK     = {0.157f, 0.157f, 0.235f};  // Dark blue-gray
    constexpr vec3 DIM      = {0.392f, 0.392f, 0.471f};  // Medium gray
    constexpr vec3 ADEQUATE = {0.784f, 0.784f, 0.627f};  // Light yellow
    constexpr vec3 BRIGHT   = {1.000f, 0.980f, 0.804f};  // Lemon chiffon
    constexpr vec3 GLARE    = {1.000f, 1.000f, 0.878f};  // Light yellow (glare)

    inline vec3 fromLux(f32 lux, f32 targetLux = 500.0f) {
        f32 ratio = lux / targetLux;
        if (ratio < 0.3f) return glm::mix(DARK, DIM, ratio / 0.3f);
        if (ratio < 0.7f) return glm::mix(DIM, ADEQUATE, (ratio - 0.3f) / 0.4f);
        if (ratio < 1.0f) return glm::mix(ADEQUATE, BRIGHT, (ratio - 0.7f) / 0.3f);
        return glm::mix(BRIGHT, GLARE, glm::min((ratio - 1.0f), 1.0f));
    }
}

// Acoustic color palette (dead to reverberant)
namespace AcousticColors {
    constexpr vec3 DEAD     = {0.282f, 0.239f, 0.545f};  // Dark slate blue
    constexpr vec3 DRY      = {0.416f, 0.353f, 0.804f};  // Slate blue
    constexpr vec3 OPTIMAL  = {0.486f, 0.988f, 0.000f};  // Lawn green
    constexpr vec3 LIVE     = {1.000f, 0.647f, 0.000f};  // Orange
    constexpr vec3 REVERB   = {0.863f, 0.078f, 0.235f};  // Crimson

    inline vec3 fromRT60(f32 rt60, f32 targetRT60 = 0.6f) {
        f32 ratio = rt60 / targetRT60;
        if (ratio < 0.5f) return glm::mix(DEAD, DRY, ratio * 2.0f);
        if (ratio < 1.0f) return glm::mix(DRY, OPTIMAL, (ratio - 0.5f) * 2.0f);
        if (ratio < 1.5f) return glm::mix(OPTIMAL, LIVE, (ratio - 1.0f) * 2.0f);
        return glm::mix(LIVE, REVERB, glm::min((ratio - 1.5f), 1.0f));
    }
}

// Wall layer functions (for layer-to-layer connections)
enum class LayerFunction : u32 {
    ExteriorFinish,   // Siding, brick, stucco
    Sheathing,        // OSB, plywood
    Insulation,       // Fiberglass, foam
    Structure,        // Studs, framing
    InteriorFinish,   // Drywall, plaster
    AirGap,           // Ventilation cavity
    Membrane          // Vapor barrier, house wrap
};

// ============================================================================
// ASSEMBLY RECIPE TYPES (Universal Assembly Schema)
// ============================================================================

// Fastener types for assembly connections
enum class FastenerType : u32 {
    Nail,             // Common/box/sinker nails
    Screw,            // Wood/drywall/structural screws
    Bolt,             // Machine/carriage/lag bolts
    Staple,           // Staples for sheathing/membrane
    Anchor,           // Concrete anchors
    Strap,            // Metal straps (hurricane ties, etc.)
    Hanger,           // Joist hangers, beam hangers
    Clip,             // Framing clips
    Adhesive          // Construction adhesive
};

// Fastener specification for a layer connection
struct LayerFastener {
    std::string name;           // e.g., "3\" 16d Common Nail"
    FastenerType type;
    std::string material;       // "steel", "galvanized", "stainless"
    f32 diameter;               // Diameter in inches
    f32 length;                 // Length in inches
    f32 fieldSpacing;           // On-center spacing in field (inches)
    f32 edgeSpacing;            // On-center spacing at edges (inches)
    std::string codeReference;  // e.g., "OBC 9.23.3.4"
    f32 shearCapacity;          // Allowable shear (lbs)
    f32 withdrawalCapacity;     // Allowable withdrawal (lbs)
};

// Constraint types for code compliance
enum class ConstraintType : u32 {
    StructuralBearing,    // Load-bearing requirements
    FireRating,           // Fire resistance rating (1-hr, 2-hr)
    ThermalPerformance,   // R-value / U-value targets
    SoundTransmission,    // STC rating
    MoistureControl,      // Vapor permeance requirements
    AirBarrier,           // Air leakage requirements
    WindResistance,       // Wind speed rating
    SeismicCategory,      // Seismic design category
    MaxSpan,              // Maximum span limits
    MinThickness,         // Minimum thickness requirements
    CodeSection           // General code section reference
};

// Assembly constraint (code requirement)
struct AssemblyConstraint {
    ConstraintType type;
    std::string name;           // Human-readable name
    std::string value;          // Target value (e.g., "R-24", "1-hour")
    std::string codeSection;    // e.g., "OBC 9.25.2.1"
    std::string description;    // Detailed explanation
    bool isMet = false;         // Validation flag
};

// Intent categories for design rationale
enum class IntentCategory : u32 {
    Performance,      // Performance targets (thermal, acoustic, etc.)
    Constructability, // Ease of construction considerations
    Cost,             // Budget/cost considerations
    Sustainability,   // Environmental/green building
    Durability,       // Longevity and maintenance
    Aesthetic,        // Visual/design intent
    CodeCompliance    // Regulatory requirements
};

// Intent block for design rationale (why this assembly was chosen)
struct IntentBlock {
    IntentCategory category;
    std::string title;          // e.g., "High-Performance Envelope"
    std::string description;    // Detailed rationale
    std::string target;         // Target metric (e.g., "R-24 effective")
    std::vector<std::string> relatedCodes;  // Relevant code sections
    bool validated = false;     // Has this intent been verified?
};

// ============================================================================
// WALL ASSEMBLY TYPES
// ============================================================================

// Single layer in a wall assembly
struct WallLayer {
    std::string name;           // e.g., "2x6 Stud"
    std::string material;       // e.g., "wood", "fiberglass"
    LayerFunction function;     // What this layer does
    f32 thickness;              // Thickness in feet
    vec3 color;                 // Render color
    f32 rValue = 0.0f;          // R-value for thermal calculations

    // Assembly recipe extensions
    std::vector<LayerFastener> fasteners;  // Fasteners used to attach this layer
};

// Wall type (assembly of layers)
struct WallType {
    std::string id;                      // Unique identifier for JSON reference
    std::string name;                    // e.g., "2x6 Exterior Wall"
    std::vector<WallLayer> layers;       // Ordered exterior to interior

    // Assembly recipe extensions
    std::vector<AssemblyConstraint> constraints;  // Code requirements for this assembly
    std::vector<IntentBlock> intents;             // Design rationale

    // Intent block (matches manifesto schema)
    struct Intent {
        f32 rValueTarget = 0.0f;         // Target R-value
        std::string structuralRole;       // "load_bearing", "non_bearing", "shear"
        std::string climateZone;          // OBC climate zone
    } intent;

    f32 getTotalThickness() const {
        f32 total = 0.0f;
        for (const auto& layer : layers) total += layer.thickness;
        return total;
    }

    f32 getTotalRValue() const {
        f32 total = 0.0f;
        for (const auto& layer : layers) total += layer.rValue;
        return total;
    }

    // Check if all constraints are met
    bool allConstraintsMet() const {
        for (const auto& c : constraints) {
            if (!c.isMet) return false;
        }
        return true;
    }
};

// Corner joint types
enum class CornerType : u32 {
    None,           // No connection
    Butt,           // One wall stops at other
    Miter,          // Both walls cut at angle
    LCorner,        // L-shaped corner
    TIntersection   // T-shaped intersection
};

// Wall corner connection info
struct WallCorner {
    u32 wall1Index;         // First wall index
    u32 wall2Index;         // Second wall index
    vec2 location;          // XZ position of corner
    CornerType type;        // How walls connect
    bool isStart1;          // Is this at start of wall1?
    bool isStart2;          // Is this at start of wall2?
};

// Parametric wall (centerline-based)
struct ParametricWall {
    vec2 startPoint;        // XZ start of centerline
    vec2 endPoint;          // XZ end of centerline
    f32 baseHeight;         // Bottom of wall (Y)
    f32 topHeight;          // Top of wall (Y)
    u32 wallTypeIndex;      // Index into wallTypes array
    std::string id;         // Unique identifier

    // Computed geometry per layer (generated from centerline)
    std::vector<MeshData> layerMeshes;

    // Corner adjustments (computed during corner processing)
    vec2 adjustedStart;     // Start point after corner cleanup
    vec2 adjustedEnd;       // End point after corner cleanup

    f32 getLength() const {
        vec2 diff = endPoint - startPoint;
        return std::sqrt(diff.x * diff.x + diff.y * diff.y);
    }

    vec2 getDirection() const {
        vec2 diff = endPoint - startPoint;
        f32 len = getLength();
        return len > 0.0001f ? diff / len : vec2(1, 0);
    }

    vec2 getNormal() const {
        vec2 dir = getDirection();
        return vec2(-dir.y, dir.x);  // Perpendicular (left side)
    }
};

// ============================================================================
// FRUSTUM CULLING
// ============================================================================

// Frustum plane (ax + by + cz + d = 0)
struct Plane {
    vec3 normal;
    f32 distance;

    // Signed distance from point to plane (positive = in front)
    f32 distanceToPoint(const vec3& point) const {
        return glm::dot(normal, point) + distance;
    }
};

// View frustum for culling (6 planes)
struct Frustum {
    enum { Left = 0, Right, Bottom, Top, Near, Far, Count };
    Plane planes[Count];

    // Extract frustum planes from view-projection matrix
    static Frustum fromViewProjection(const mat4& vp) {
        Frustum f;

        // Left plane
        f.planes[Left].normal.x = vp[0][3] + vp[0][0];
        f.planes[Left].normal.y = vp[1][3] + vp[1][0];
        f.planes[Left].normal.z = vp[2][3] + vp[2][0];
        f.planes[Left].distance = vp[3][3] + vp[3][0];

        // Right plane
        f.planes[Right].normal.x = vp[0][3] - vp[0][0];
        f.planes[Right].normal.y = vp[1][3] - vp[1][0];
        f.planes[Right].normal.z = vp[2][3] - vp[2][0];
        f.planes[Right].distance = vp[3][3] - vp[3][0];

        // Bottom plane
        f.planes[Bottom].normal.x = vp[0][3] + vp[0][1];
        f.planes[Bottom].normal.y = vp[1][3] + vp[1][1];
        f.planes[Bottom].normal.z = vp[2][3] + vp[2][1];
        f.planes[Bottom].distance = vp[3][3] + vp[3][1];

        // Top plane
        f.planes[Top].normal.x = vp[0][3] - vp[0][1];
        f.planes[Top].normal.y = vp[1][3] - vp[1][1];
        f.planes[Top].normal.z = vp[2][3] - vp[2][1];
        f.planes[Top].distance = vp[3][3] - vp[3][1];

        // Near plane
        f.planes[Near].normal.x = vp[0][3] + vp[0][2];
        f.planes[Near].normal.y = vp[1][3] + vp[1][2];
        f.planes[Near].normal.z = vp[2][3] + vp[2][2];
        f.planes[Near].distance = vp[3][3] + vp[3][2];

        // Far plane
        f.planes[Far].normal.x = vp[0][3] - vp[0][2];
        f.planes[Far].normal.y = vp[1][3] - vp[1][2];
        f.planes[Far].normal.z = vp[2][3] - vp[2][2];
        f.planes[Far].distance = vp[3][3] - vp[3][2];

        // Normalize all planes
        for (int i = 0; i < Count; i++) {
            f32 len = glm::length(f.planes[i].normal);
            if (len > 0.0001f) {
                f.planes[i].normal /= len;
                f.planes[i].distance /= len;
            }
        }

        return f;
    }

    // Test if AABB is inside or intersects frustum
    // Returns true if visible (fully or partially inside)
    bool testAABB(const vec3& minPt, const vec3& maxPt) const {
        for (int i = 0; i < Count; i++) {
            // Find the positive vertex (furthest along plane normal)
            vec3 pVertex;
            pVertex.x = (planes[i].normal.x >= 0) ? maxPt.x : minPt.x;
            pVertex.y = (planes[i].normal.y >= 0) ? maxPt.y : minPt.y;
            pVertex.z = (planes[i].normal.z >= 0) ? maxPt.z : minPt.z;

            // If positive vertex is outside, AABB is fully outside
            if (planes[i].distanceToPoint(pVertex) < 0) {
                return false;
            }
        }
        return true;
    }

    // Quick test for a point (useful for small objects)
    bool testPoint(const vec3& point) const {
        for (int i = 0; i < Count; i++) {
            if (planes[i].distanceToPoint(point) < 0) {
                return false;
            }
        }
        return true;
    }
};

// Helper to compute AABB from StructuralElement
inline void getElementAABB(const StructuralElement& elem, vec3& outMin, vec3& outMax) {
    // Use start/end as basis, expand by width/depth
    vec3 halfExtent(elem.width * 0.5f, 0.0f, elem.depth * 0.5f);

    outMin = glm::min(elem.start, elem.end) - halfExtent;
    outMax = glm::max(elem.start, elem.end) + halfExtent;

    // Ensure Y bounds are correct (height)
    if (outMin.y > outMax.y) std::swap(outMin.y, outMax.y);
}

// Building/Scene structure for loading
struct Building {
    std::string name;
    std::vector<StructuralElement> elements;
    std::unordered_map<std::string, ThermalData> thermalData;
    std::unordered_map<std::string, LightingData> lightingData;
    std::unordered_map<std::string, AcousticData> acousticData;

    // Parametric wall system
    std::vector<WallType> wallTypes;
    std::vector<ParametricWall> parametricWalls;
    std::vector<WallCorner> wallCorners;

    // Terrain mesh (from elevation API)
    TerrainMesh terrainMesh;
};

} // namespace arch
