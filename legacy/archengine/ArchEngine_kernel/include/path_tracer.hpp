/**
 * @file path_tracer.hpp
 * @brief Offline path tracer for high-quality renders
 *
 * Implements a compute shader-based path tracer that works on any Vulkan GPU.
 * Uses progressive rendering with Monte Carlo integration for photorealistic
 * global illumination.
 *
 * Features:
 * - BVH-accelerated ray tracing
 * - PBR material model (GGX microfacet)
 * - Next Event Estimation (direct light sampling)
 * - Russian Roulette path termination
 * - Environment map importance sampling
 * - Progressive accumulation for noise reduction
 */

#pragma once

#include "types.hpp"
#include "vulkan_context.hpp"
#include "bvh.hpp"
#include "environment_map.hpp"
#include <string>
#include <functional>
#include <atomic>
#include <unordered_map>

namespace arch {

/**
 * @brief Path tracer configuration
 */
struct PathTracerConfig {
    u32 width = 1920;               // Output width in pixels
    u32 height = 1080;              // Output height in pixels
    u32 samplesPerPixel = 64;       // Total samples per pixel
    u32 maxBounces = 8;             // Maximum path depth
    u32 samplesPerFrame = 1;        // Samples per progressive frame
    bool enableDenoising = true;    // Apply denoising to final result
    bool enableNEE = true;          // Next Event Estimation (direct light sampling)
    bool enableRR = true;           // Russian Roulette path termination
    u32 rrStartDepth = 3;           // Depth at which RR starts
    f32 exposure = 1.0f;            // Exposure for tonemapping
    u32 tonemapMode = 1;            // 0=Reinhard, 1=ACES, 2=Uncharted2
};

/**
 * @brief GPU uniform buffer for path tracing
 */
struct alignas(16) PathTraceUBO {
    mat4 cameraInvView;             // Inverse view matrix
    mat4 cameraInvProj;             // Inverse projection matrix
    vec4 cameraPosition;            // Camera world position (w = unused)
    vec4 lightDirection;            // Directional light (w = intensity)
    vec4 lightColor;                // Light color (w = unused)
    vec4 envMapInfo;                // x = has env map, y = intensity, z = rotation, w = unused
    vec4 clipPlane;                 // Section clipping plane (xyz = normal, w = distance)
    u32 frameIndex;                 // Current frame for random seed
    u32 sampleCount;                // Current accumulated sample count
    u32 maxBounces;                 // Max path depth
    u32 triangleCount;              // Number of triangles
    u32 nodeCount;                  // Number of BVH nodes
    u32 materialCount;              // Number of materials
    u32 enableNEE;                  // Next event estimation flag
    u32 enableRR;                   // Russian roulette flag
    u32 rrStartDepth;               // RR start depth
    f32 exposure;                   // Exposure value
    u32 tonemapMode;                // Tonemap mode
    u32 width;                      // Image width
    u32 height;                     // Image height
    u32 enableClipping;             // Section clipping enabled flag
    f32 uvScale;                    // UV scale to match live renderer (base=0.001 * this value)
    u32 _pad[1];                    // Padding to 16-byte alignment
};

/**
 * @brief Path tracer state
 */
enum class PathTracerState {
    Idle,           // Ready to start
    Rendering,      // Progressive render in progress
    Complete,       // Render complete
    Error           // Error occurred
};

/**
 * @brief Offline path tracer for V-Ray quality renders
 *
 * This class provides an offline path tracer that produces high-quality
 * photorealistic images suitable for final presentation renders.
 *
 * Usage:
 * @code
 * PathTracer pt(context);
 * pt.setScene(building);
 * pt.setCamera(camera);
 * pt.setConfig(config);
 *
 * pt.startRender();
 * while (!pt.isComplete()) {
 *     pt.renderFrame();
 *     float progress = pt.getProgress();
 *     // Update progress bar
 * }
 * pt.savePNG("output.png", 1.0f);
 * @endcode
 */
class PathTracer {
public:
    /**
     * @brief Construct a path tracer
     * @param context Vulkan context for GPU operations
     */
    PathTracer(VulkanContext& context);

    /**
     * @brief Destructor - cleans up all GPU resources
     */
    ~PathTracer();

    // Non-copyable
    PathTracer(const PathTracer&) = delete;
    PathTracer& operator=(const PathTracer&) = delete;

    /**
     * @brief Set the scene to render
     * @param elements Structural elements making up the scene
     * @return true if scene was successfully uploaded to GPU
     */
    bool setScene(const std::vector<StructuralElement>& elements);

    /**
     * @brief Set the scene to render with terrain
     * @param elements Structural elements making up the scene
     * @param terrain Optional terrain mesh (nullptr to skip)
     * @param terrainMaterialName Material name for terrain texturing
     * @return true if scene was successfully uploaded to GPU
     */
    bool setScene(const std::vector<StructuralElement>& elements,
                  const TerrainMesh* terrain,
                  const std::string& terrainMaterialName);

    /**
     * @brief Set the camera
     * @param camera Camera parameters (position, target, FOV, etc.)
     */
    void setCamera(const Camera& camera);

    /**
     * @brief Set render configuration
     * @param config Path tracer configuration
     */
    void setConfig(const PathTracerConfig& config);

    /**
     * @brief Get current configuration
     */
    const PathTracerConfig& getConfig() const { return m_config; }

    /**
     * @brief Set environment map for IBL
     * @param envMap Environment map to use (nullptr for procedural sky)
     */
    void setEnvironmentMap(EnvironmentMap* envMap);

    /**
     * @brief Set section clipping plane
     * @param plane Clipping plane (xyz = normal, w = distance)
     * @param enabled Whether clipping is enabled
     */
    void setClipPlane(const vec4& plane, bool enabled);

    /**
     * @brief Set UV scale to match live renderer
     * @param scale UV scale multiplier (live renderer uses base 0.001 * scale)
     *
     * The path tracer uses world-space UV projection. To match the live renderer's
     * appearance, set this to the same value as the live renderer's material UV scale.
     * Default is 100.0 which gives 0.001 * 100 = 0.1 effective scale.
     */
    void setUVScale(f32 scale) { m_uvScale = scale; }

    /**
     * @brief Get current UV scale
     */
    f32 getUVScale() const { return m_uvScale; }

    /**
     * @brief Load PBR textures from materials directory
     * @param materialsDir Path to materials directory containing polyhaven folder
     * @return true if textures were loaded successfully
     */
    bool loadMaterialTextures(const std::string& materialsDir);

    /**
     * @brief Get texture index for a material name
     * @param materialName Material name (e.g., "polyhaven/brick_wall_006")
     * @return Texture base index or -1 if not found
     */
    int getTextureIndex(const std::string& materialName) const;

    /**
     * @brief Update material texture indices after textures are loaded
     * @param elements Scene elements to resolve material names from
     *
     * Call this after both setScene() and loadMaterialTextures() to
     * ensure materials use the correct texture indices.
     */
    void updateMaterialTextureIndices(const std::vector<StructuralElement>& elements);

    /**
     * @brief Start progressive render
     *
     * Resets accumulation and begins rendering.
     * Call renderFrame() repeatedly until isComplete() returns true.
     */
    void startRender();

    /**
     * @brief Render one progressive frame
     * @return true if more frames needed, false if complete
     *
     * Each call adds samplesPerFrame samples to the accumulation buffer.
     */
    bool renderFrame();

    /**
     * @brief Stop rendering early
     */
    void stopRender();

    /**
     * @brief Check if render is complete
     */
    bool isComplete() const { return m_state == PathTracerState::Complete; }

    /**
     * @brief Check if rendering is in progress
     */
    bool isRendering() const { return m_state == PathTracerState::Rendering; }

    /**
     * @brief Get current state
     */
    PathTracerState getState() const { return m_state; }

    /**
     * @brief Get current sample count
     */
    u32 getCurrentSample() const { return m_currentSample; }

    /**
     * @brief Get render progress (0.0 to 1.0)
     */
    f32 getProgress() const;

    /**
     * @brief Save result as PNG
     * @param filepath Output file path
     * @param exposure Exposure adjustment for tonemapping
     * @return true if save succeeded
     */
    bool savePNG(const std::string& filepath, f32 exposure = 1.0f);

    /**
     * @brief Save result as EXR (HDR)
     * @param filepath Output file path
     * @return true if save succeeded
     */
    bool saveEXR(const std::string& filepath);

    /**
     * @brief Apply denoising to the current result
     *
     * Uses temporal accumulation-based denoising suitable for path traced output.
     */
    void applyDenoising();

    /**
     * @brief Get raw HDR pixel data
     *
     * Returns accumulated HDR radiance values (not tonemapped).
     * Format: RGBA32F, row-major, top-to-bottom.
     */
    const std::vector<f32>& getHDRPixels() const { return m_hdrPixels; }

    /**
     * @brief Get LDR pixel data (tonemapped)
     *
     * Returns tonemapped RGBA8 pixels ready for display.
     */
    const std::vector<u8>& getLDRPixels() const { return m_ldrPixels; }

    /**
     * @brief Set progress callback
     * @param callback Function called with progress (0.0-1.0) after each frame
     */
    void setProgressCallback(std::function<void(f32)> callback) {
        m_progressCallback = std::move(callback);
    }

private:
    void createComputePipeline();
    void createDescriptorSets();
    void createBuffers();
    void createAccumulationImage();
    void createTextureArray();
    void cleanupTextures();
    void cleanupRenderResources();  // Clean up render resources only (keep scene data)
    void updateUBO();
    void downloadResult();
    void tonemapResult();
    void cleanup();  // Full cleanup including scene data

    VkShaderModule loadShaderModule(const std::string& filename);

    VulkanContext& m_context;

    // Configuration
    PathTracerConfig m_config;
    Camera m_camera;
    EnvironmentMap* m_envMap = nullptr;
    vec4 m_clipPlane = vec4(0.0f, 1.0f, 0.0f, 0.0f);  // Default: horizontal plane at y=0
    bool m_enableClipping = false;
    f32 m_uvScale = 100.0f;  // Default UV scale: 0.001 * 100 = 0.1 effective scale

    // State
    PathTracerState m_state = PathTracerState::Idle;
    u32 m_currentSample = 0;
    u32 m_frameIndex = 0;
    std::atomic<bool> m_stopRequested{false};
    std::function<void(f32)> m_progressCallback;

    // Scene data
    std::vector<GPUTriangle> m_triangles;
    std::vector<GPUBVHNode> m_bvhNodes;
    std::vector<GPUPTMaterial> m_materials;
    bool m_sceneValid = false;
    std::string m_terrainMaterialName;  // Store terrain material name for texture index update

    // GPU buffers
    VkBuffer m_triangleBuffer = VK_NULL_HANDLE;
    VkDeviceMemory m_triangleMemory = VK_NULL_HANDLE;
    VkBuffer m_bvhBuffer = VK_NULL_HANDLE;
    VkDeviceMemory m_bvhMemory = VK_NULL_HANDLE;
    VkBuffer m_materialBuffer = VK_NULL_HANDLE;
    VkDeviceMemory m_materialMemory = VK_NULL_HANDLE;
    VkBuffer m_uboBuffer = VK_NULL_HANDLE;
    VkDeviceMemory m_uboMemory = VK_NULL_HANDLE;
    void* m_uboMapped = nullptr;

    // Accumulation image (HDR, RGBA32F)
    VkImage m_accumImage = VK_NULL_HANDLE;
    VkDeviceMemory m_accumMemory = VK_NULL_HANDLE;
    VkImageView m_accumView = VK_NULL_HANDLE;

    // Output staging buffer
    VkBuffer m_stagingBuffer = VK_NULL_HANDLE;
    VkDeviceMemory m_stagingMemory = VK_NULL_HANDLE;

    // Compute pipeline
    VkDescriptorPool m_descriptorPool = VK_NULL_HANDLE;
    VkDescriptorSetLayout m_descriptorSetLayout = VK_NULL_HANDLE;
    VkDescriptorSet m_descriptorSet = VK_NULL_HANDLE;
    VkPipelineLayout m_pipelineLayout = VK_NULL_HANDLE;
    VkPipeline m_pipeline = VK_NULL_HANDLE;

    // Result data
    std::vector<f32> m_hdrPixels;
    std::vector<u8> m_ldrPixels;

    // Texture array for PBR materials
    VkImage m_textureArray = VK_NULL_HANDLE;
    VkDeviceMemory m_textureArrayMemory = VK_NULL_HANDLE;
    VkImageView m_textureArrayView = VK_NULL_HANDLE;
    VkSampler m_textureSampler = VK_NULL_HANDLE;
    u32 m_textureArrayLayers = 0;
    u32 m_textureResolution = 1024;  // Textures resized to this resolution
    bool m_texturesLoaded = false;

    // Material name to texture array index mapping
    // Each material has 4 consecutive layers: albedo, normal, roughness, ao
    std::unordered_map<std::string, int> m_materialTextureIndices;
    std::vector<std::string> m_loadedMaterials;
    std::string m_materialsBasePath;  // Base path for loading textures
};

} // namespace arch
