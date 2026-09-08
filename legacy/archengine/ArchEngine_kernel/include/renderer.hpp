/**
 * @file renderer.hpp
 * @brief Main rendering interface for ArchEngine
 *
 * This file contains the Renderer class which provides the primary interface
 * for all rendering operations in ArchEngine. It manages the Vulkan rendering
 * pipeline, including frame management, draw calls, post-processing effects,
 * and visualization modes for architectural analysis.
 *
 * @see VulkanContext for low-level Vulkan operations
 * @see PostProcess for SSAO, bloom, and tonemapping
 * @see ShadowMap for shadow mapping implementation
 */

#pragma once

#include "types.hpp"
#include <set>
#include <functional>
#include <cstddef>
#include <iostream>
#include "vulkan_context.hpp"
#include "pipeline.hpp"
#include "mesh.hpp"
#include "shadow_map.hpp"
#include "environment_map.hpp"
#include "post_process.hpp"
#include "texture.hpp"
#include "project.hpp"
#include "lights.hpp"
#include <unordered_map>

namespace arch {

/**
 * @brief Statistics collected during rendering
 *
 * Contains performance metrics and rendering statistics that can be
 * used for profiling and debugging.
 */
struct RenderStats {
    u32 drawCalls = 0;      ///< Number of draw calls this frame
    u32 triangles = 0;      ///< Total triangles rendered this frame
    u32 culledElements = 0; ///< Elements culled by frustum this frame
    f32 frameTimeMs = 0.0f; ///< CPU frame time in milliseconds
    f32 gpuTimeMs = 0.0f;   ///< GPU frame time in milliseconds
};

/**
 * @brief Per-element material override
 *
 * Stores material property adjustments for a specific element.
 * Values are additive: final_value = global_value + adjustment.
 * Set all values to 0.0 (and tint to 1.0) to use global defaults.
 */
struct ElementMaterialOverride {
    bool active = false;        ///< True if any override has been set

    // Per-parameter override flags
    bool hasUVScale = false;
    bool hasUVRotation = false;
    bool hasNormalStrength = false;
    bool hasBrightness = false;
    bool hasContrast = false;
    bool hasSaturation = false;
    bool hasRoughness = false;
    bool hasMetallic = false;
    bool hasAOStrength = false;
    bool hasTint = false;

    // Direct replacement values (not additive)
    float uvScale = 1.0f;           ///< Direct UV scale value (0.1 to 200)
    float uvRotation = 0.0f;        ///< UV rotation in degrees (0 to 360)
    float normalStrength = 1.0f;    ///< Direct normal strength value (0 to 5)
    float brightness = 0.0f;        ///< Direct brightness value (-1 to 1)
    float contrast = 1.0f;          ///< Direct contrast value (0 to 2)
    float saturation = 1.0f;        ///< Direct saturation value (0 to 2)
    float roughness = 0.5f;         ///< Direct roughness value (0 to 1)
    float metallic = 0.0f;          ///< Direct metallic value (0 to 1)
    float aoStrength = 1.0f;        ///< Direct AO strength value (0 to 2)
    float tint[3] = {0, 0, 0};      ///< Tint offset values (-1 to 1, additive color)
};

/**
 * @brief Main rendering class for ArchEngine
 *
 * The Renderer class is the primary interface for all rendering operations.
 * It manages:
 * - Frame lifecycle (begin/end frame)
 * - Render passes (main, HDR, shadow, composite)
 * - Structural element drawing with stress visualization
 * - Post-processing effects (SSAO, bloom, tonemapping)
 * - Material and PBR settings
 * - Visualization modes for different analysis types
 *
 * @note This class is non-copyable. Only one Renderer should exist per VulkanContext.
 *
 * Example usage:
 * @code
 * VulkanContext context(window, config);
 * Renderer renderer(context);
 *
 * renderer.setCamera(camera);
 * renderer.setShadowsEnabled(true);
 * renderer.setSSAOEnabled(true);
 *
 * while (!window.shouldClose()) {
 *     if (renderer.beginFrame()) {
 *         renderer.beginHDRRenderPass();
 *         renderer.drawStructuralFrame(elements, building);
 *         renderer.drawSky();
 *         renderer.endHDRRenderPass();
 *         renderer.runPostProcessing();
 *         renderer.beginCompositePass();
 *         // ImGui rendering here
 *         renderer.endFrame();
 *     }
 * }
 * @endcode
 */
class Renderer {
public:
    /**
     * @brief Construct a new Renderer
     * @param context Reference to the VulkanContext for GPU operations
     */
    Renderer(VulkanContext& context);

    /**
     * @brief Destructor - cleans up all Vulkan resources
     */
    ~Renderer();

    /// @name Non-copyable
    /// @{
    Renderer(const Renderer&) = delete;
    Renderer& operator=(const Renderer&) = delete;
    /// @}

    /// @name Frame Management
    /// @{

    /**
     * @brief Begin a new frame
     * @return true if frame was successfully started, false if swapchain needs recreation
     *
     * Acquires the next swapchain image and begins command buffer recording.
     * Must be called before any draw commands.
     */
    bool beginFrame();

    /**
     * @brief End the current frame
     *
     * Submits the command buffer and presents the image to the swapchain.
     * Must be called after all draw commands are complete.
     */
    void endFrame();

    /**
     * @brief Clear the mesh cache to free GPU resources
     *
     * Call this before loading a new scene to prevent memory leaks.
     * Waits for GPU to finish using resources before clearing.
     */
    void clearMeshCache();
    /// @}

    /// @name Render Pass Management
    /// @{

    /**
     * @brief Begin the main render pass (SDR path)
     * @param clearColor Background clear color (RGBA)
     *
     * Use this for simple rendering without post-processing.
     * For HDR rendering with effects, use beginHDRRenderPass() instead.
     */
    void beginRenderPass(vec4 clearColor = {0.1f, 0.1f, 0.15f, 1.0f});

    /**
     * @brief End the main render pass
     */
    void endRenderPass();

    /**
     * @brief Enable or disable the HDR post-processing pipeline
     * @param enabled True to enable HDR rendering with SSAO, bloom, and tonemapping
     */
    void setPostProcessingEnabled(bool enabled) { m_postProcessingEnabled = enabled; }

    /**
     * @brief Check if post-processing is enabled
     * @return True if HDR pipeline is active
     */
    bool isPostProcessingEnabled() const { return m_postProcessingEnabled; }

    /**
     * @brief Set post-process debug visualization mode
     * @param mode Debug mode (None, SSAOOnly, BloomOnly, HDRScene, Depth)
     */
    void setPostProcessDebugMode(PostProcessDebugMode mode);

    /**
     * @brief Get current post-process debug mode
     * @return Current debug mode
     */
    PostProcessDebugMode getPostProcessDebugMode() const;

    /**
     * @brief Set material/displacement debug visualization mode
     * @param mode Debug mode (None, Displacement, POMDepth, Normals, UVs, AO)
     */
    void setMaterialDebugMode(MaterialDebugMode mode) { m_materialDebugMode = mode; }

    /**
     * @brief Get current material debug mode
     * @return Current material debug mode
     */
    MaterialDebugMode getMaterialDebugMode() const { return m_materialDebugMode; }

    /**
     * @brief Begin HDR render pass for post-processing path
     * @param clearColor Background clear color (RGBA)
     * @return true if HDR pass started successfully, false to fallback to SDR
     *
     * Renders to an HDR float buffer instead of the swapchain.
     * Follow with endHDRRenderPass(), runPostProcessing(), beginCompositePass().
     */
    bool beginHDRRenderPass(vec4 clearColor = {0.1f, 0.1f, 0.15f, 1.0f});

    /**
     * @brief End the HDR render pass
     */
    void endHDRRenderPass();

    /**
     * @brief Run post-processing effects (SSAO, bloom)
     *
     * Must be called after endHDRRenderPass() and before beginCompositePass().
     */
    void runPostProcessing();

    /**
     * @brief Begin the composite pass to output to swapchain
     *
     * Composites HDR scene with effects and applies tonemapping.
     * Leaves render pass open for ImGui overlay rendering.
     */
    void beginCompositePass();
    /// @}

    /// @name Shadow Mapping
    /// @{

    /**
     * @brief Render the shadow pass for directional light shadows
     * @param elements Structural elements to render to shadow map
     *
     * Call before beginRenderPass() or beginHDRRenderPass().
     */
    void renderShadowPass(const std::vector<StructuralElement>& elements);
    /// @}

    /// @name Camera
    /// @{

    /**
     * @brief Set the camera for rendering
     * @param camera Camera containing position, target, FOV, and projection settings
     */
    void setCamera(const Camera& camera);
    /// @}

    /// @name Drawing Functions
    /// @{

    /**
     * @brief Draw a mesh with transform and color
     * @param mesh The mesh to draw
     * @param transform Model transformation matrix
     * @param color RGB color for the mesh
     * @param stress Stress value [0-1+] for stress coloring visualization
     */
    void drawMesh(Mesh& mesh, const mat4& transform, vec3 color, f32 stress = 0.0f);

    /**
     * @brief Draw a structural beam
     * @param start Start position of the beam
     * @param end End position of the beam
     * @param width Width of the beam cross-section
     * @param height Height of the beam cross-section
     * @param color RGB color
     * @param stress Stress ratio [0-1+] where 1.0 = at capacity
     * @param deflection Deflection value for visualization
     */
    void drawBeam(vec3 start, vec3 end, f32 width, f32 height, vec3 color, f32 stress = 0.0f, f32 deflection = 0.0f);

    /**
     * @brief Draw a structural column
     * @param position Base position of the column
     * @param width Width (X dimension)
     * @param depth Depth (Z dimension)
     * @param height Height (Y dimension)
     * @param color RGB color
     * @param stress Stress ratio [0-1+]
     */
    void drawColumn(vec3 position, f32 width, f32 depth, f32 height, vec3 color, f32 stress = 0.0f);

    /**
     * @brief Draw a column with explicit PBR material parameters
     * @param position Base position
     * @param width Width (X dimension)
     * @param depth Depth (Z dimension)
     * @param height Height (Y dimension)
     * @param color RGB color
     * @param stress Stress ratio
     * @param material Vec4 with (metallic, roughness, ao, emission)
     */
    void drawColumnWithMaterial(vec3 position, f32 width, f32 depth, f32 height, vec3 color, f32 stress, vec4 material);

    /**
     * @brief Draw a floor slab
     * @param position Corner position of the floor
     * @param width Width (X dimension)
     * @param depth Depth (Z dimension)
     * @param thickness Thickness (Y dimension)
     * @param color RGB color
     * @param stress Stress ratio [0-1+]
     */
    void drawFloor(vec3 position, f32 width, f32 depth, f32 thickness, vec3 color, f32 stress = 0.0f);

    /**
     * @brief Draw a door opening
     * @param position Position of the door
     * @param width Width of the door
     * @param height Height of the door
     * @param depth Thickness of the door
     * @param color RGB color
     * @param stress Stress ratio (typically 0 for doors)
     */
    void drawDoor(vec3 position, f32 width, f32 height, f32 depth, vec3 color, f32 stress = 0.0f);

    /**
     * @brief Draw a window
     * @param position Position of the window
     * @param width Width of the window
     * @param height Height of the window
     * @param depth Thickness/depth of the window
     * @param color RGB color (typically blueish for glass)
     * @param stress Stress ratio (typically 0 for windows)
     */
    void drawWindow(vec3 position, f32 width, f32 height, f32 depth, vec3 color, f32 stress = 0.0f);

    /**
     * @brief Draw a roof element
     * @param position Base corner position
     * @param width Width (X dimension)
     * @param depth Depth (Z dimension)
     * @param height Peak height (Y dimension)
     * @param color RGB color
     * @param stress Stress ratio [0-1+]
     */
    void drawRoof(vec3 position, f32 width, f32 depth, f32 height, vec3 color, f32 stress = 0.0f);

    /**
     * @brief Draw custom mesh geometry
     * @param meshData Vertex and index data for the mesh
     * @param color RGB color
     * @param stress Stress ratio [0-1+]
     */
    void drawCustomMesh(const MeshData& meshData, vec3 color, f32 stress = 0.0f);

    /**
     * @brief Draw custom mesh with explicit material parameters
     * @param meshData Vertex and index data
     * @param color RGB color
     * @param stress Stress ratio
     * @param material Vec4 with (metallic, roughness, ao, emission)
     */
    void drawCustomMeshWithMaterial(const MeshData& meshData, vec3 color, f32 stress, vec4 material);

    /**
     * @brief Draw mesh with explicit material parameters
     * @param mesh The mesh to draw
     * @param transform Model transformation matrix
     * @param color RGB color
     * @param stress Stress ratio
     * @param material Vec4 with (metallic, roughness, ao, emission)
     */
    void drawMeshWithMaterial(Mesh& mesh, const mat4& transform, vec3 color, f32 stress, vec4 material);

    /**
     * @brief Draw mesh with material and per-element override support
     * @param elementId Element index to look up overrides (-1 = no override)
     */
    void drawMeshWithMaterialAndOverride(Mesh& mesh, const mat4& transform, vec3 color, f32 stress, vec4 material, int elementId);

    /**
     * @brief Draw a reference grid on the ground plane
     * @param size Total size of the grid
     * @param spacing Distance between grid lines
     */
    void drawGrid(f32 size = 50.0f, f32 spacing = 1.0f);

    /**
     * @brief Draw an arrow indicating a load
     * @param start Start position of the arrow
     * @param end End position (tip) of the arrow
     * @param magnitude Load magnitude for scaling
     */
    void drawLoadArrow(vec3 start, vec3 end, f32 magnitude);

    /**
     * @brief Draw the sky (procedural or cubemap)
     *
     * Uses environment map if loaded, otherwise renders procedural sky.
     */
    void drawSky();

    /**
     * @brief Draw all structural elements from a building
     * @param elements Vector of structural elements to draw
     * @param building Building data containing thermal/acoustic info for visualization
     * @param selectedIndices Set of element indices that are selected (highlighted)
     *
     * This is the main function for rendering a complete structural frame.
     * Elements are colored based on the current visualization mode.
     */
    void drawStructuralFrame(const std::vector<StructuralElement>& elements, const Building& building, const std::set<int>& selectedIndices = {});

    /**
     * @brief Draw terrain mesh with elevation-based coloring
     * @param terrain TerrainMesh data from building
     *
     * Renders the terrain mesh if it has data. Uses pre-computed vertex colors
     * for elevation visualization. Terrain is rendered with identity transform
     * (pre-positioned in world space).
     */
    void drawTerrain(const TerrainMesh& terrain);

    /**
     * @brief Invalidate terrain mesh cache
     *
     * Call this when terrain data has been modified externally (e.g., via API)
     * to force the renderer to rebuild the GPU mesh on next draw.
     */
    void invalidateTerrainCache() { m_lastTerrainData = nullptr; m_terrainMesh.reset(); }

    /**
     * @brief Set terrain material/texture name
     * @param materialName Material name (e.g., "polyhaven/grass_path_2") or empty for vertex colors
     */
    void setTerrainMaterial(const std::string& materialName) { m_terrainMaterialName = materialName; }
    const std::string& getTerrainMaterial() const { return m_terrainMaterialName; }

    /**
     * @brief Draw material test scene (PBR validation)
     *
     * Renders a grid of spheres with varying roughness (X-axis) and metallic (Y-axis).
     * This is the standard way to validate PBR rendering and tune IBL parameters.
     * Only renders if the material test scene is enabled.
     */
    void drawMaterialTestScene();

    /** @brief Enable/disable material test scene */
    void setShowMaterialTestScene(bool show) { m_showMaterialTestScene = show; }

    /** @brief Check if material test scene is enabled */
    bool getShowMaterialTestScene() const { return m_showMaterialTestScene; }

    /** @brief Set material test grid size (NxN spheres) */
    void setMaterialTestGridSize(int size) { m_materialTestGridSize = std::clamp(size, 3, 9); }

    /** @brief Get material test grid size */
    int getMaterialTestGridSize() const { return m_materialTestGridSize; }

    /** @brief Set material test preset (0=Full, 1=Dielectrics, 2=Metals, 3=Roughness, 4=Metallic) */
    void setMaterialTestPreset(int preset) { m_materialTestPreset = std::clamp(preset, 0, 4); }

    /** @brief Get material test preset */
    int getMaterialTestPreset() const { return m_materialTestPreset; }

    /** @brief Get camera position to view material test scene */
    vec3 getMaterialTestSceneCameraPosition() const;

    /** @brief Get camera target to view material test scene */
    vec3 getMaterialTestSceneCameraTarget() const;
    /// @}

    /// @name Visualization Settings
    /// @{

    /**
     * @brief Set the visualization mode
     * @param mode Visualization mode (Structural, Thermal, Lighting, Acoustic, Material, Wireframe)
     *
     * Changes how elements are colored:
     * - Structural: Stress-based coloring (green=safe, red=failure)
     * - Thermal: Temperature gradient
     * - Lighting: Daylight/lux levels
     * - Acoustic: Sound absorption
     * - Material: Material type coloring
     * - Wireframe: Wire outline mode
     */
    void setVisualizationMode(VisualizationMode mode) { m_vizMode = mode; }

    /** @brief Get current visualization mode */
    VisualizationMode getVisualizationMode() const { return m_vizMode; }
    /// @}

    /// @name Shadow Settings
    /// @{

    /** @brief Enable or disable shadow mapping */
    void setShadowsEnabled(bool enabled) { m_shadowsEnabled = enabled; }

    /** @brief Check if shadows are enabled */
    bool getShadowsEnabled() const { return m_shadowsEnabled; }

    /**
     * @brief Set the directional light direction
     * @param dir Direction vector (will be normalized)
     */
    void setLightDirection(const vec3& dir) { m_lightDirection = glm::normalize(dir); }

    /** @brief Get the current light direction */
    const vec3& getLightDirection() const { return m_lightDirection; }

    /**
     * @brief Set shadow depth bias to reduce shadow acne
     * @param bias Bias value (typically 0.001 - 0.05)
     */
    void setShadowBias(f32 bias) { m_shadowBias = bias; }

    /** @brief Get current shadow bias */
    f32 getShadowBias() const { return m_shadowBias; }
    /// @}

    /// @name Multi-Light System
    /// @{

    /**
     * @brief Add a light to the scene
     * @param light The light to add
     * @return Index of the added light, or -1 if max lights reached
     */
    i32 addLight(const Light& light);

    /**
     * @brief Remove a light by index
     * @param index Index of the light to remove
     */
    void removeLight(u32 index);

    /**
     * @brief Remove all lights from the scene
     */
    void clearLights();

    /**
     * @brief Get number of active lights
     * @return Number of lights currently in the scene
     */
    u32 getLightCount() const { return static_cast<u32>(m_lights.size()); }

    /**
     * @brief Get a mutable reference to a light
     * @param index Light index
     * @return Pointer to light, or nullptr if index invalid
     */
    Light* getLight(u32 index);

    /**
     * @brief Get a const reference to a light
     * @param index Light index
     * @return Const pointer to light, or nullptr if index invalid
     */
    const Light* getLight(u32 index) const;

    /**
     * @brief Get all lights
     * @return Vector of all lights in the scene
     */
    const std::vector<Light>& getLights() const { return m_lights; }

    /**
     * @brief Set all lights at once (e.g., from loaded scene)
     * @param lights Vector of lights to set
     */
    void setLights(const std::vector<Light>& lights);

    /**
     * @brief Set light group enabled state
     * @param group Group index (0-3 for Interior, Exterior, Accent, Custom)
     * @param enabled Whether the group is enabled
     */
    void setLightGroupEnabled(int group, bool enabled);

    /**
     * @brief Set light group intensity multiplier
     * @param group Group index (0-3)
     * @param intensity Intensity multiplier (0.0-2.0)
     */
    void setLightGroupIntensity(int group, float intensity);

    /**
     * @brief Draw a placement marker at the given position
     * @param position World position for the marker
     * @param color Marker color
     * @param size Size of the marker
     */
    void drawPlacementMarker(vec3 position, vec3 color = vec3(1.0f, 1.0f, 0.0f), f32 size = 0.5f);

    /**
     * @brief Draw visual indicators for all placed lights
     * Shows small glowing spheres at each light position
     * @param selectedIndex Index of the currently selected light (-1 for none)
     */
    void drawLightIndicators(int selectedIndex = -1);

    /// @}

    /// @name Environment Map Settings
    /// @{

    /**
     * @brief Load an HDR environment map for image-based lighting
     * @param filepath Path to equirectangular HDR image
     * @return true if successfully loaded
     */
    bool loadHdrEnvironment(const std::string& filepath);

    /**
     * @brief Switch back to procedural sky (from HDRI)
     */
    void useProceduralSky();

    /** @brief Enable or disable HDR environment map usage */
    void setUseHdrEnvMap(bool use) { m_useHdrEnvMap = use; }

    /** @brief Check if HDR environment map is being used */
    bool getUseHdrEnvMap() const { return m_useHdrEnvMap; }

    /** @brief Check if an HDR environment map is loaded */
    bool hasHdrEnvMap() const { return m_envMap && m_envMap->isLoaded(); }

    /** @brief Get the environment map (for path tracer integration) */
    EnvironmentMap* getEnvironmentMap() const { return m_envMap.get(); }
    /// @}

    /// @name SSAO Settings
    /// @{

    /** @brief Enable or disable Screen-Space Ambient Occlusion */
    void setSSAOEnabled(bool enabled);

    /** @brief Check if SSAO is enabled */
    bool getSSAOEnabled() const { return m_ssaoEnabled; }

    /**
     * @brief Set SSAO sampling radius
     * @param radius Radius in view space (typically 0.1 - 1.0)
     */
    void setSSAORadius(f32 radius);

    /** @brief Get current SSAO radius */
    f32 getSSAORadius() const;

    /**
     * @brief Set SSAO intensity/strength
     * @param intensity Intensity multiplier (typically 1.0 - 3.0)
     */
    void setSSAOIntensity(f32 intensity);

    /** @brief Get current SSAO intensity */
    f32 getSSAOIntensity() const;

    /**
     * @brief Set SSAO depth bias
     * @param bias Bias to prevent self-occlusion (typically 0.01 - 0.1)
     */
    void setSSAOBias(f32 bias);

    /** @brief Get current SSAO bias */
    f32 getSSAOBias() const;

    /** @brief Get raw pointer to PostProcess for advanced configuration */
    PostProcess* getPostProcess() { return m_postProcess.get(); }
    /// @}

    /// @name Bloom Settings
    /// @{

    /** @brief Enable or disable bloom effect */
    void setBloomEnabled(bool enabled);

    /** @brief Check if bloom is enabled */
    bool getBloomEnabled() const { return m_bloomEnabled; }

    /**
     * @brief Set bloom brightness threshold
     * @param threshold Luminance threshold for bloom extraction (typically 0.8 - 2.0)
     */
    void setBloomThreshold(f32 threshold);

    /** @brief Get current bloom threshold */
    f32 getBloomThreshold() const;

    /**
     * @brief Set bloom intensity
     * @param intensity Bloom strength multiplier (typically 0.1 - 1.0)
     */
    void setBloomIntensity(f32 intensity);

    /** @brief Get current bloom intensity */
    f32 getBloomIntensity() const;

    /**
     * @brief Set number of bloom blur iterations
     * @param iterations Number of blur passes (more = softer bloom)
     */
    void setBloomIterations(u32 iterations);

    /** @brief Get current bloom blur iterations */
    u32 getBloomIterations() const;
    /// @}

    /// @name SSR (Screen Space Reflections) Settings
    /// @{

    /** @brief Enable or disable screen space reflections */
    void setSSREnabled(bool enabled);

    /** @brief Check if SSR is enabled */
    bool getSSREnabled() const { return m_ssrEnabled; }

    /** @brief Set SSR configuration */
    void setSSRConfig(const SSRConfig& config);

    /** @brief Get current SSR configuration */
    SSRConfig getSSRConfig() const;
    /// @}

    /// @name Shader Effect Toggles
    /// @{

    /** @brief Enable or disable IBL (Image-Based Lighting) */
    void setIBLEnabled(bool enabled) { m_iblEnabled = enabled; }
    bool getIBLEnabled() const { return m_iblEnabled; }

    /** @brief IBL intensity controls */
    void setIBLIntensity(f32 intensity) { m_iblIntensity = intensity; }
    f32 getIBLIntensity() const { return m_iblIntensity; }

    void setIBLDiffuseIntensity(f32 intensity) { m_iblDiffuseIntensity = intensity; }
    f32 getIBLDiffuseIntensity() const { return m_iblDiffuseIntensity; }

    void setIBLSpecularIntensity(f32 intensity) { m_iblSpecularIntensity = intensity; }
    f32 getIBLSpecularIntensity() const { return m_iblSpecularIntensity; }

    void setFresnelIntensity(f32 intensity) { m_fresnelIntensity = intensity; }
    f32 getFresnelIntensity() const { return m_fresnelIntensity; }

    /** @brief Enable or disable direct sun lighting */
    void setDirectLightEnabled(bool enabled) { m_directLightEnabled = enabled; }
    bool getDirectLightEnabled() const { return m_directLightEnabled; }

    /** @brief Enable or disable normal mapping */
    void setNormalMappingEnabled(bool enabled) { m_normalMappingEnabled = enabled; }
    bool getNormalMappingEnabled() const { return m_normalMappingEnabled; }
    /// @}

    /// @name Tonemapping Settings
    /// @{

    /**
     * @brief Set exposure value for HDR tonemapping
     * @param exposure Exposure multiplier (typically 0.5 - 3.0)
     */
    void setExposure(f32 exposure);

    /** @brief Get current exposure value */
    f32 getExposure() const;

    /**
     * @brief Set tonemapping operator
     * @param mode 0=Reinhard, 1=ACES Filmic, 2=Uncharted2
     */
    void setTonemapMode(u32 mode);

    /** @brief Get current tonemapping mode */
    u32 getTonemapMode() const;
    /// @}

    /// @name Section Clipping Settings
    /// @{

    /** @brief Enable or disable section clipping (legacy single plane) */
    void setClippingEnabled(bool enabled) { m_clippingEnabled = enabled ? 1u : 0u; }

    /** @brief Check if any clipping is enabled */
    bool getClippingEnabled() const { return m_clippingEnabled != 0; }

    /**
     * @brief Set the clipping plane directly (legacy single plane, uses plane 0)
     * @param plane Plane equation (normal.xyz, distance.w)
     */
    void setClipPlane(const vec4& plane) { m_clipPlanes[0] = plane; m_numClipPlanes = 1; }

    /** @brief Get current clipping plane (legacy, returns plane 0) */
    const vec4& getClipPlane() const { return m_clipPlanes[0]; }

    /**
     * @brief Set clipping axis (legacy single plane)
     * @param axis 0=X, 1=Y, 2=Z
     */
    void setClipAxis(int axis) { m_clipAxis = axis; updateClipPlane(); }

    /** @brief Get current clipping axis */
    int getClipAxis() const { return m_clipAxis; }

    /**
     * @brief Set clipping plane height/position along axis (legacy single plane)
     * @param height Position along the clip axis
     */
    void setClipHeight(f32 height) { m_clipHeight = height; updateClipPlane(); }

    /** @brief Get current clip height */
    f32 getClipHeight() const { return m_clipHeight; }

    /**
     * @brief Flip the clipping direction (legacy single plane)
     * @param flipped True to clip below instead of above
     */
    void setClipFlipped(bool flipped) { m_clipFlipped = flipped; updateClipPlane(); }

    /** @brief Check if clipping is flipped */
    bool getClipFlipped() const { return m_clipFlipped; }

    // ========== Multi-Plane Clipping (Section Box) ==========

    /**
     * @brief Set a specific clip plane directly
     * @param index Plane index (0-5)
     * @param plane Plane equation (normal.xyz, distance.w)
     * @param enabled Whether this plane is active
     */
    void setClipPlaneAt(u32 index, const vec4& plane, bool enabled = true);

    /**
     * @brief Get a specific clip plane
     * @param index Plane index (0-5)
     * @return Plane equation
     */
    const vec4& getClipPlaneAt(u32 index) const;

    /**
     * @brief Enable or disable a specific clip plane
     * @param index Plane index (0-5)
     * @param enabled Whether the plane should be active
     */
    void setClipPlaneEnabled(u32 index, bool enabled);

    /**
     * @brief Check if a specific clip plane is enabled
     * @param index Plane index (0-5)
     */
    bool getClipPlaneEnabled(u32 index) const;

    /**
     * @brief Set number of active clip planes
     * @param count Number of planes (0-6)
     */
    void setNumClipPlanes(u32 count) { m_numClipPlanes = std::min(count, 6u); }

    /** @brief Get number of active clip planes */
    u32 getNumClipPlanes() const { return m_numClipPlanes; }

    /**
     * @brief Set up a section box (6 clip planes forming a 3D box)
     * @param minBounds Minimum corner of the box (x, y, z)
     * @param maxBounds Maximum corner of the box (x, y, z)
     *
     * Creates 6 clip planes that isolate geometry within the specified box.
     * Fragments outside the box will be clipped.
     */
    void setSectionBox(const vec3& minBounds, const vec3& maxBounds);

    /**
     * @brief Clear section box (disable all clip planes)
     */
    void clearSectionBox();

    /**
     * @brief Check if section box is active
     * @return True if all 6 planes are enabled
     */
    bool hasSectionBox() const { return m_numClipPlanes == 6 && m_clippingEnabled == 0x3F; }

    /**
     * @brief Get section box bounds (if active)
     * @param outMin Output: minimum corner
     * @param outMax Output: maximum corner
     * @return True if section box is active
     */
    bool getSectionBoxBounds(vec3& outMin, vec3& outMax) const;
    /// @}

    /// @name Statistics
    /// @{

    /**
     * @brief Get rendering statistics from the last frame
     * @return RenderStats with draw calls, triangles, and timing
     */
    const RenderStats& getStats() const { return m_stats; }
    /// @}

    /// @name PBR Material Settings
    /// @{

    /**
     * @brief Set default metallic value for elements without textures
     * @param metallic Metallic value [0-1] where 1 = fully metallic
     */
    void setDefaultMetallic(f32 metallic) { m_defaultMetallic = metallic; }

    /** @brief Get default metallic value */
    f32 getDefaultMetallic() const { return m_defaultMetallic; }

    /**
     * @brief Set default roughness value
     * @param roughness Roughness value [0-1] where 0 = mirror smooth
     */
    void setDefaultRoughness(f32 roughness) { m_defaultRoughness = roughness; }

    /** @brief Get default roughness value */
    f32 getDefaultRoughness() const { return m_defaultRoughness; }

    /**
     * @brief Set default ambient occlusion value
     * @param ao AO value [0-1] where 1 = fully lit
     */
    void setDefaultAO(f32 ao) { m_defaultAO = ao; }

    /** @brief Get default AO value */
    f32 getDefaultAO() const { return m_defaultAO; }

    /**
     * @brief Set default emission intensity
     * @param emission Emission multiplier [0+]
     */
    void setDefaultEmission(f32 emission) { m_defaultEmission = emission; }

    /** @brief Get default emission value */
    f32 getDefaultEmission() const { return m_defaultEmission; }
    /// @}

    /// @name Wall Material Settings
    /// @{

    /** @brief Set metallic value for wall elements */
    void setWallMetallic(f32 metallic) { m_wallMetallic = metallic; }
    f32 getWallMetallic() const { return m_wallMetallic; }

    /** @brief Set roughness value for wall elements */
    void setWallRoughness(f32 roughness) { m_wallRoughness = roughness; }
    f32 getWallRoughness() const { return m_wallRoughness; }

    /** @brief Set AO value for wall elements */
    void setWallAO(f32 ao) { m_wallAO = ao; }
    f32 getWallAO() const { return m_wallAO; }

    /** @brief Set emission value for wall elements */
    void setWallEmission(f32 emission) { m_wallEmission = emission; }
    f32 getWallEmission() const { return m_wallEmission; }
    /// @}

    /// @name Roof Material Settings
    /// @{

    /** @brief Set metallic value for roof elements */
    void setRoofMetallic(f32 metallic) { m_roofMetallic = metallic; }
    f32 getRoofMetallic() const { return m_roofMetallic; }

    /** @brief Set roughness value for roof elements */
    void setRoofRoughness(f32 roughness) { m_roofRoughness = roughness; }
    f32 getRoofRoughness() const { return m_roofRoughness; }

    /** @brief Set AO value for roof elements */
    void setRoofAO(f32 ao) { m_roofAO = ao; }
    f32 getRoofAO() const { return m_roofAO; }

    /** @brief Set emission value for roof elements */
    void setRoofEmission(f32 emission) { m_roofEmission = emission; }
    f32 getRoofEmission() const { return m_roofEmission; }

    /**
     * @brief Set UV scale for material texture tiling
     * @param scale UV multiplier (higher = more repetition)
     */
    void setMaterialUVScale(f32 scale) {
        static int callCount = 0;
        if (callCount < 10 || scale != m_materialUVScale) {
            std::cout << "[setMaterialUVScale] " << m_materialUVScale << " -> " << scale << " (call #" << callCount << ")" << std::endl;
            callCount++;
        }
        m_materialUVScale = scale;
    }
    f32 getMaterialUVScale() const {
        static int callCount = 0;
        if (callCount < 10) {
            std::cout << "[getMaterialUVScale] returning " << m_materialUVScale << " (call #" << callCount << ")" << std::endl;
            callCount++;
        }
        return m_materialUVScale;
    }

    /**
     * @brief Set normal map strength
     * @param strength Normal map intensity multiplier
     */
    void setNormalStrength(f32 strength) { m_normalStrength = strength; }
    f32 getNormalStrength() const { return m_normalStrength; }

    // Material adjustment parameters
    void setMaterialBrightness(f32 v) { m_materialBrightness = v; }
    f32 getMaterialBrightness() const { return m_materialBrightness; }
    void setMaterialContrast(f32 v) { m_materialContrast = v; }
    f32 getMaterialContrast() const { return m_materialContrast; }
    void setMaterialSaturation(f32 v) { m_materialSaturation = v; }
    f32 getMaterialSaturation() const { return m_materialSaturation; }
    void setMaterialRoughnessOffset(f32 v) { m_materialRoughnessOffset = v; }
    f32 getMaterialRoughnessOffset() const { return m_materialRoughnessOffset; }
    void setMaterialMetallicOffset(f32 v) { m_materialMetallicOffset = v; }
    f32 getMaterialMetallicOffset() const { return m_materialMetallicOffset; }
    void setMaterialAOStrength(f32 v) { m_materialAOStrength = v; }
    f32 getMaterialAOStrength() const { return m_materialAOStrength; }
    void setMaterialTint(vec3 v) { m_materialTint = v; }
    vec3 getMaterialTint() const { return m_materialTint; }
    /// @}

    /// @name Tessellation Settings
    /// @{

    /** @brief Enable or disable tessellation-based displacement mapping */
    void setTessellationEnabled(bool enabled) { m_tessellationEnabled = enabled; }
    bool getTessellationEnabled() const { return m_tessellationEnabled; }

    /**
     * @brief Set tessellation subdivision level
     * @param level Subdivision level (1-64, higher = more detail)
     */
    void setTessellationLevel(f32 level) { m_tessellationLevel = glm::clamp(level, 1.0f, 128.0f); }
    f32 getTessellationLevel() const { return m_tessellationLevel; }

    /**
     * @brief Set displacement scale for height map
     * @param scale Displacement amount (0 = flat, higher = more displacement)
     */
    void setDisplacementScale(f32 scale) { m_displacementScale = scale; }
    f32 getDisplacementScale() const { return m_displacementScale; }
    /// @}

    /// @name Parallax Occlusion Mapping (POM)
    /// @{

    /** @brief Enable or disable Parallax Occlusion Mapping */
    void setPOMEnabled(bool enabled) { m_pomEnabled = enabled; }
    bool getPOMEnabled() const { return m_pomEnabled; }

    /** @brief Set POM height scale (depth of parallax effect) */
    void setPOMHeightScale(f32 scale) { m_pomHeightScale = scale; }
    f32 getPOMHeightScale() const { return m_pomHeightScale; }

    /** @brief Set POM layer counts for quality (min layers at perpendicular, max at grazing angles) */
    void setPOMLayers(f32 minLayers, f32 maxLayers) { m_pomMinLayers = minLayers; m_pomMaxLayers = maxLayers; }
    f32 getPOMMinLayers() const { return m_pomMinLayers; }
    f32 getPOMMaxLayers() const { return m_pomMaxLayers; }
    /// @}

    /// @name Material Style
    /// @{

    /**
     * @brief Set the overall material style preset
     * @param style MaterialStyle (Realistic, Clean, Schematic, Blueprint)
     *
     * Applies a preset of material settings optimized for the style.
     */
    void setMaterialStyle(MaterialStyle style) { m_materialStyle = style; applyMaterialStyle(); }

    /** @brief Get current material style */
    MaterialStyle getMaterialStyle() const { return m_materialStyle; }
    /// @}

    /// @name Material Library
    /// @{

    /** @brief Get the root directory for material textures */
    const std::string& getMaterialRoot() const { return m_materialRoot; }

    /**
     * @brief Reload materials from a directory
     * @param root Root directory containing material subdirectories
     * @return true if successfully loaded
     */
    bool reloadMaterialLibrary(const std::string& root);

    /**
     * @brief Get list of loaded material names
     * @return Vector of material names available for use
     */
    std::vector<std::string> getMaterialNames() const;

    /**
     * @brief Get material preset for an element type
     * @param type The element type (Beam, Column, Wall, etc.)
     * @return MaterialPreset with appropriate PBR values for the style
     */
    MaterialPreset getMaterialForElement(ElementType type) const;

    /**
     * @brief Get ImGui texture descriptor for material preview thumbnail
     * @param materialName Name of the material
     * @return VkDescriptorSet for ImGui Image(), or VK_NULL_HANDLE if not available
     *
     * Generates and caches material preview thumbnails on first call.
     * Returns ImGui-compatible texture descriptor for displaying material previews.
     */
    VkDescriptorSet getMaterialPreviewDescriptor(const std::string& materialName);

    /**
     * @brief Check if material preview is ready
     * @param materialName Name of the material
     * @return true if preview texture is available
     */
    bool hasMaterialPreview(const std::string& materialName) const;

    /**
     * @brief Generate material preview thumbnails for all materials
     *
     * Renders all materials to thumbnail textures for display in the material library.
     * This can take a moment if there are many materials.
     */
    void generateMaterialPreviews();
    /// @}

    /// @name Per-Element Material Overrides
    /// @{

    /**
     * @brief Set material override for a specific element
     * @param elementId Unique ID of the element (typically the index in elements vector)
     * @param override Material override parameters to apply
     *
     * Override values are added to global material values.
     * This allows per-element material customization (e.g., make one wall darker).
     */
    void setElementOverride(int elementId, const ElementMaterialOverride& override);

    /**
     * @brief Set material override for an element (individual parameters)
     * @param elementId Unique ID of the element
     * @param mask Override mask bitfield
     * @param uvScale UV scale value
     * @param normalStrength Normal strength value
     * @param brightness Brightness value
     * @param contrast Contrast value
     */
    void setElementOverride(int elementId, u32 mask, float uvScale, float normalStrength, float brightness, float contrast);

    /**
     * @brief Check if element has a material override
     * @param elementId Unique ID of the element
     * @return True if element has override, false otherwise
     */
    bool hasElementOverride(int elementId) const;

    /**
     * @brief Get material override for an element
     * @param elementId Unique ID of the element
     * @return Pointer to override if exists, nullptr otherwise
     */
    const ElementMaterialOverride* getElementOverride(int elementId) const;

    /**
     * @brief Remove override for a specific element
     * @param elementId Unique ID of the element
     */
    void clearElementOverride(int elementId);

    /**
     * @brief Remove all element material overrides
     */
    void clearAllElementOverrides();

    /**
     * @brief Get count of elements with active overrides
     * @return Number of elements with overrides
     */
    size_t getOverrideCount() const { return m_elementMaterialOverrides.size(); }

    /**
     * @brief Get all element material overrides
     * @return Reference to the overrides map
     */
    const std::unordered_map<int, ElementMaterialOverride>& getAllElementOverrides() const {
        return m_elementMaterialOverrides;
    }

    /**
     * @brief Set all element material overrides at once
     * @param overrides Map of element ID to override settings
     */
    void setAllElementOverrides(const std::unordered_map<int, ElementMaterialOverride>& overrides) {
        m_elementMaterialOverrides = overrides;
    }

    /**
     * @brief Get all render settings as a single struct
     * @return RenderSettings containing all current settings
     */
    RenderSettings getRenderSettings() const;

    /**
     * @brief Apply all render settings from a struct
     * @param settings RenderSettings to apply
     */
    void setRenderSettings(const RenderSettings& settings);

    /**
     * @brief Get the current camera
     * @return Reference to the current camera
     */
    const Camera& getCamera() const { return m_camera; }

    /**
     * @brief Get indices of all elements with overrides
     * @param outIndices Output array to fill with indices
     * @param maxIndices Maximum number of indices to retrieve
     * @return Number of indices actually retrieved
     */
    size_t getElementOverrideIndices(int* outIndices, size_t maxIndices) const;

    /**
     * @brief Apply element override to UBO (internal use by drawStructuralFrame)
     * @param elementId ID of the element to apply overrides for
     * @return Override mask bitfield (0 if no override)
     *
     * This updates the UBO element override fields for the current element
     * and returns a mask indicating which override parameters are active.
     */
    u32 applyElementOverrideToUBO(int elementId);
    /// @}

    /// @name Vulkan Access
    /// @{

    /** @brief Get the render pass handle for ImGui integration */
    VkRenderPass getRenderPass() const { return m_renderPass; }
    VkPipelineLayout getPipelineLayout() const { return m_pipelineLayout; }

    /** @brief Get the current command buffer for custom draw commands */
    VkCommandBuffer getCurrentCommandBuffer() const { return m_currentCommandBuffer; }
    /// @}

    /// @name Resize Handling
    /// @{

    /**
     * @brief Handle window/swapchain resize
     *
     * Call when the window size changes to recreate framebuffers.
     */
    void onResize();
    /// @}

    /// @name High-Resolution Rendering
    /// @{

    /**
     * @brief Render the current scene to a high-resolution offscreen buffer
     * @param elements Structural elements to render
     * @param building Building data for visualization
     * @param width Target width in pixels
     * @param height Target height in pixels
     * @param samples Number of samples for anti-aliasing accumulation
     * @param progressCallback Optional callback for progress updates (0.0 - 1.0)
     * @return true if rendering succeeded
     *
     * This function renders the scene to an offscreen buffer at the specified
     * resolution. For multi-sample renders, it accumulates multiple frames with
     * jittered camera positions for high-quality anti-aliasing.
     */
    bool renderHighRes(
        const std::vector<StructuralElement>& elements,
        const Building& building,
        u32 width,
        u32 height,
        int samples = 1,
        float brightness = 1.3f,
        std::function<void(float)> progressCallback = nullptr
    );

    /**
     * @brief Get the high-res render result as raw pixel data
     * @return Vector of RGBA8 pixel data (4 bytes per pixel)
     *
     * Call after renderHighRes() to retrieve the rendered image.
     * The data is in row-major order, top-to-bottom, left-to-right.
     */
    const std::vector<u8>& getHighResPixels() const { return m_highResPixels; }

    /**
     * @brief Get high-res render width
     */
    u32 getHighResWidth() const { return m_highResWidth; }

    /**
     * @brief Get high-res render height
     */
    u32 getHighResHeight() const { return m_highResHeight; }

    /**
     * @brief Save the high-res render to a PNG file
     * @param filepath Output file path
     * @return true if save succeeded
     */
    bool saveHighResPNG(const std::string& filepath);

    /**
     * @brief Save the high-res render to an EXR (HDR) file
     * @param filepath Output file path
     * @return true if save succeeded
     */
    bool saveHighResEXR(const std::string& filepath);

    /**
     * @brief Quick preview render (1080p, 1 sample) for fast print preview
     * Much faster than full high-res render, allows iterating on post-processing settings
     * @param elements Scene elements to render
     * @param building Building data
     * @param filepath Output file path
     * @param brightness Brightness multiplier
     * @return true if render succeeded
     */
    bool renderPreview(const std::vector<StructuralElement>& elements,
                      const Building& building,
                      const std::string& filepath,
                      float brightness = 1.0f);
    /// @}

    /// @name Live Preview Rendering
    /// @{

    /**
     * @brief Create persistent GPU resources for inline preview rendering
     *
     * Creates a fixed-resolution (640x360) render target that stays on GPU
     * for fast ImGui display. Only call once; resources persist until cleanup.
     */
    void createPreviewResources();

    /**
     * @brief Clean up preview rendering resources
     *
     * Must be called before ImGui shutdown. Removes ImGui texture descriptor
     * and destroys all Vulkan resources.
     */
    void cleanupPreviewResources();

    /**
     * @brief Render scene to preview texture for ImGui display
     * @param elements Structural elements to render
     * @param building Building data for visualization
     * @return true if rendering succeeded
     *
     * Renders at 640x360, single sample, directly to GPU texture.
     * Result is immediately available via getPreviewDescriptor().
     */
    bool renderPreviewToTexture(const std::vector<StructuralElement>& elements,
                                const Building& building);

    /**
     * @brief Get ImGui-compatible descriptor for preview texture
     * @return VkDescriptorSet suitable for ImGui::Image(), or VK_NULL_HANDLE if not created
     */
    VkDescriptorSet getPreviewDescriptor() const { return m_previewImGuiDescriptor; }

    /** @brief Get preview width in pixels */
    u32 getPreviewWidth() const { return kPreviewWidth; }

    /** @brief Get preview height in pixels */
    u32 getPreviewHeight() const { return kPreviewHeight; }

    /** @brief Check if preview resources are ready */
    bool hasPreviewResources() const { return m_previewResourcesCreated; }
    /// @}

private:
    static constexpr u32 kMaxMaterialSets = 128;

    // Preview rendering constants (1080p for high-quality inline preview)
    static constexpr u32 kPreviewWidth = 1920;
    static constexpr u32 kPreviewHeight = 1080;

    void createRenderPass();
    void createFramebuffers();
    void createCommandBuffers();
    void createSyncObjects();
    void createDescriptorPool();
    void createDescriptorSets();
    void createMaterialDescriptorSetLayout();
    void createIBLDescriptorSetLayout();
    void updateIBLDescriptorSet();
    void createDefaultMaterialDescriptorSet();
    void createUniformBuffers();
    void createPipeline();
    void createSkyPipeline();

    void cleanupSwapchain();
    void recreateSwapchain();

    void updateUniformBuffer(u32 frameIndex);

    VkDescriptorSet createMaterialDescriptorSetForMaterial(const Material& material);
    void buildMaterialDescriptorSets();
    void bindIBLDescriptorSet();
    void bindMaterialDescriptorSet(const std::string& materialName);
    std::string resolveMaterialName(const StructuralElement& element) const;

    // Get element color based on visualization mode
    vec3 getElementColor(const StructuralElement& element, const Building& building, size_t index) const;

    // Apply material style presets to current settings
    void applyMaterialStyle();

    VulkanContext& m_context;

    // Render pass and framebuffers
    VkRenderPass m_renderPass = VK_NULL_HANDLE;
    std::vector<VkFramebuffer> m_framebuffers;

    // Command buffers
    std::vector<VkCommandBuffer> m_commandBuffers;

    // Sync objects - per frame in flight
    std::vector<VkSemaphore> m_imageAvailableSemaphores;  // Per frame in flight
    std::vector<VkSemaphore> m_renderFinishedSemaphores;  // Per frame in flight
    std::vector<VkFence> m_inFlightFences;                // Per frame in flight
    std::vector<VkFence> m_imagesInFlight;                // Per swapchain image - tracks which fence is using each image

    // Descriptors
    VkDescriptorPool m_descriptorPool = VK_NULL_HANDLE;
    VkDescriptorSetLayout m_descriptorSetLayout = VK_NULL_HANDLE;
    std::vector<VkDescriptorSet> m_descriptorSets;

    // Material descriptor set (set 1)
    VkDescriptorSetLayout m_materialDescriptorSetLayout = VK_NULL_HANDLE;
    VkDescriptorSet m_defaultMaterialDescriptorSet = VK_NULL_HANDLE;
    VkDescriptorSet m_lastBoundMaterialSet = VK_NULL_HANDLE;  // Track for redundant bind skipping
    std::unordered_map<std::string, VkDescriptorSet> m_materialDescriptorSets;
    std::unique_ptr<MaterialLibrary> m_materialLibrary;
    std::string m_materialRoot = "materials";

    // IBL descriptor set (set 2) - irradiance, prefiltered, BRDF LUT
    VkDescriptorSetLayout m_iblDescriptorSetLayout = VK_NULL_HANDLE;
    VkDescriptorSet m_iblDescriptorSet = VK_NULL_HANDLE;
    bool m_iblDescriptorSetValid = false;

    // Uniform buffers
    std::vector<VkBuffer> m_uniformBuffers;
    std::vector<VkDeviceMemory> m_uniformBuffersMemory;
    std::vector<void*> m_uniformBuffersMapped;

    // Pipeline
    VkPipelineLayout m_pipelineLayout = VK_NULL_HANDLE;
    std::unique_ptr<Pipeline> m_pipeline;
    std::unique_ptr<Pipeline> m_wireframePipeline;
    std::unique_ptr<Pipeline> m_transparentPipeline;  // For glass/transparent materials

    // HDR pipelines (for post-processing path - no MSAA, HDR render pass)
    std::unique_ptr<Pipeline> m_hdrPipeline;
    std::unique_ptr<Pipeline> m_hdrWireframePipeline;
    std::unique_ptr<Pipeline> m_hdrTransparentPipeline;  // For glass/transparent in HDR mode

    // Tessellation pipelines (with displacement mapping)
    std::unique_ptr<Pipeline> m_tessPipeline;
    std::unique_ptr<Pipeline> m_tessWireframePipeline;
    std::unique_ptr<Pipeline> m_hdrTessPipeline;
    std::unique_ptr<Pipeline> m_hdrTessWireframePipeline;

    // Sky pipeline
    VkPipelineLayout m_skyPipelineLayout = VK_NULL_HANDLE;
    VkPipeline m_skyPipeline = VK_NULL_HANDLE;

    // Dynamic meshes (cached for reuse)
    std::unordered_map<std::string, std::unique_ptr<Mesh>> m_meshCache;
    std::unordered_map<const MeshData*, std::string> m_customMeshKeyCache;  // Maps custom mesh pointers to cache keys
    std::unique_ptr<Mesh> m_gridMesh;

    // Material test scene (PBR validation grid of spheres)
    std::unique_ptr<Mesh> m_testSphereMesh;
    bool m_showMaterialTestScene = false;
    int m_materialTestGridSize = 5;  // 5x5 grid of spheres
    int m_materialTestPreset = 0;    // 0=Full, 1=Dielectrics, 2=Metals, 3=Roughness Row, 4=Metallic Column

    // Terrain mesh (separate from element meshes, recreated on terrain data change)
    std::unique_ptr<Mesh> m_terrainMesh;
    const TerrainMesh* m_lastTerrainData = nullptr;  // Track if terrain data changed
    std::string m_terrainMaterialName;  // Material/texture name for terrain (empty = use vertex colors)

    // Frame state
    u32 m_currentFrame = 0;
    u32 m_imageIndex = 0;
    bool m_frameStarted = false;
    VkCommandBuffer m_currentCommandBuffer = VK_NULL_HANDLE;
    int m_currentDrawElementId = -1;  // Element ID for per-element overrides (-1 = none)

    // Camera, frustum, and time
    Camera m_camera;
    Frustum m_frustum;  // Cached frustum for culling
    f32 m_time = 0.0f;
    u32 m_culledCount = 0;  // Debug: elements culled this frame

    // Visualization mode
    VisualizationMode m_vizMode = VisualizationMode::Material;

    // Material style
    MaterialStyle m_materialStyle = MaterialStyle::Realistic;

    // Shadow mapping
    std::unique_ptr<ShadowMap> m_shadowMap;
    bool m_shadowsEnabled = true;
    vec3 m_lightDirection = glm::normalize(vec3(-0.5f, -1.0f, -0.3f));
    f32 m_shadowBias = 0.02f;  // Adjustable shadow bias
    bool m_outputLinearHDR = false;  // True when rendering to HDR buffer (skip in-shader tonemapping)
    VkDescriptorSet m_shadowHeightMapDescriptorSet = VK_NULL_HANDLE;  // For tessellated shadows

    // Multiple light sources
    std::vector<Light> m_lights;  // Up to MAX_LIGHTS (16)
    bool m_lightGroupEnabled[4] = {true, true, true, true};  // Per-group enabled flags
    float m_lightGroupIntensity[4] = {1.0f, 1.0f, 1.0f, 1.0f};  // Per-group intensity multipliers
    u32 m_activeShadowMaps = 0;  // Number of active shadow-casting lights

    // Environment mapping
    std::unique_ptr<EnvironmentMap> m_envMap;
    VkDescriptorSetLayout m_skyDescriptorSetLayout = VK_NULL_HANDLE;
    std::vector<VkDescriptorSet> m_skyDescriptorSets;
    bool m_useHdrEnvMap = false;

    // Post-processing (SSAO, bloom, SSR, etc.)
    std::unique_ptr<PostProcess> m_postProcess;
    bool m_ssaoEnabled = true;
    bool m_bloomEnabled = true;
    bool m_ssrEnabled = true;
    bool m_postProcessingEnabled = false;  // Master switch for HDR pipeline (TODO: need HDR-compatible sky pipeline)

    // Shader effect toggles (for debugging)
    bool m_iblEnabled = true;           // Image-Based Lighting (ambient)
    bool m_directLightEnabled = true;   // Direct sun/light contribution
    bool m_normalMappingEnabled = true; // Normal mapping from textures

    // IBL intensity controls
    f32 m_iblIntensity = 1.0f;          // Overall IBL intensity multiplier
    f32 m_iblDiffuseIntensity = 1.0f;   // Diffuse IBL intensity
    f32 m_iblSpecularIntensity = 0.4f;  // Specular IBL intensity (reduced to prevent white film)
    f32 m_fresnelIntensity = 0.6f;      // Fresnel reflection intensity (reduced for less edge glare)

    // Debug visualization modes
    MaterialDebugMode m_materialDebugMode = MaterialDebugMode::None;

    // Section clipping (multi-plane for section box)
    u32 m_clippingEnabled = 0;  // Bitmask: bit 0-5 = plane enabled
    u32 m_numClipPlanes = 0;    // Number of active clip planes (0-6)
    vec4 m_clipPlanes[6] = {    // Up to 6 planes for section box
        vec4(0.0f, 1.0f, 0.0f, 0.0f),   // Default: Y-up plane at origin
        vec4(0.0f), vec4(0.0f), vec4(0.0f), vec4(0.0f), vec4(0.0f)
    };
    // Legacy single-plane controls (update plane 0)
    int m_clipAxis = 1;      // 0=X, 1=Y, 2=Z
    f32 m_clipHeight = 0.0f; // Clip plane position along axis
    bool m_clipFlipped = false;
    // Section box bounds (cached for getSectionBoxBounds)
    vec3 m_sectionBoxMin = vec3(0.0f);
    vec3 m_sectionBoxMax = vec3(0.0f);

    void updateClipPlane();  // Updates plane 0 from axis/height/flipped

    // PBR Material defaults (general)
    f32 m_defaultMetallic = 0.0f;
    f32 m_defaultRoughness = 0.5f;
    f32 m_defaultAO = 1.0f;
    f32 m_defaultEmission = 0.0f;

    // Wall material
    f32 m_wallMetallic = 0.0f;
    f32 m_wallRoughness = 0.9f;
    f32 m_wallAO = 1.0f;
    f32 m_wallEmission = 0.0f;

    // Roof material
    f32 m_roofMetallic = 0.0f;
    f32 m_roofRoughness = 0.7f;
    f32 m_roofAO = 1.0f;
    f32 m_roofEmission = 0.0f;
    f32 m_materialUVScale = 1.0f;
    f32 m_normalStrength = 1.0f;
    f32 m_materialBrightness = 0.0f;
    f32 m_materialContrast = 1.0f;
    f32 m_materialSaturation = 1.0f;
    f32 m_materialRoughnessOffset = 0.0f;
    f32 m_materialMetallicOffset = 0.0f;
    f32 m_materialAOStrength = 1.0f;
    vec3 m_materialTint = vec3(1.0f);

    // Tessellation settings
    bool m_tessellationEnabled = false;
    f32 m_tessellationLevel = 8.0f;
    f32 m_displacementScale = 0.1f;

    // Parallax Occlusion Mapping settings
    bool m_pomEnabled = false;
    f32 m_pomHeightScale = 0.05f;   // Depth of parallax effect
    f32 m_pomMinLayers = 8.0f;      // Layers at perpendicular view
    f32 m_pomMaxLayers = 32.0f;     // Layers at grazing angles

    // Per-element material overrides (sparse map for memory efficiency)
    std::unordered_map<int, ElementMaterialOverride> m_elementMaterialOverrides;

    // Note: Element overrides are now stored entirely in UBO, no push constant cache needed



    // Stats
    RenderStats m_stats;

    // High-res rendering resources
    VkImage m_highResImage = VK_NULL_HANDLE;
    VkDeviceMemory m_highResMemory = VK_NULL_HANDLE;
    VkImageView m_highResView = VK_NULL_HANDLE;
    VkImage m_highResNormalImage = VK_NULL_HANDLE;  // MRT: normal/roughness buffer
    VkDeviceMemory m_highResNormalMemory = VK_NULL_HANDLE;
    VkImageView m_highResNormalView = VK_NULL_HANDLE;
    VkImage m_highResDepthImage = VK_NULL_HANDLE;
    VkDeviceMemory m_highResDepthMemory = VK_NULL_HANDLE;
    VkImageView m_highResDepthView = VK_NULL_HANDLE;
    VkFramebuffer m_highResFramebuffer = VK_NULL_HANDLE;
    VkRenderPass m_highResRenderPass = VK_NULL_HANDLE;
    std::unique_ptr<Pipeline> m_highResPipeline;  // Single-sample pipeline for high-res
    std::unique_ptr<Pipeline> m_highResTransparentPipeline;  // Transparent pipeline for high-res
    std::vector<u8> m_highResPixels;
    std::vector<f32> m_highResHDRPixels;  // For EXR export
    u32 m_highResWidth = 0;
    u32 m_highResHeight = 0;

    void createHighResResources(u32 width, u32 height);
    void cleanupHighResResources();
    void copyHighResImageToBuffer();

    // Live preview rendering resources (GPU-direct, stays on GPU for ImGui)
    VkImage m_previewImage = VK_NULL_HANDLE;
    VkDeviceMemory m_previewMemory = VK_NULL_HANDLE;
    VkImageView m_previewImageView = VK_NULL_HANDLE;
    VkSampler m_previewSampler = VK_NULL_HANDLE;
    VkImage m_previewDepthImage = VK_NULL_HANDLE;
    VkDeviceMemory m_previewDepthMemory = VK_NULL_HANDLE;
    VkImageView m_previewDepthView = VK_NULL_HANDLE;
    VkFramebuffer m_previewFramebuffer = VK_NULL_HANDLE;
    VkRenderPass m_previewRenderPass = VK_NULL_HANDLE;
    VkDescriptorSet m_previewImGuiDescriptor = VK_NULL_HANDLE;
    std::unique_ptr<Pipeline> m_previewPipeline;
    std::unique_ptr<Pipeline> m_previewTransparentPipeline;
    bool m_previewResourcesCreated = false;

    // Material preview thumbnails
    static constexpr u32 kMaterialPreviewSize = 256;  // Thumbnail size (larger for better visibility)
    struct MaterialPreview {
        VkImage image = VK_NULL_HANDLE;
        VkDeviceMemory memory = VK_NULL_HANDLE;
        VkImageView imageView = VK_NULL_HANDLE;
        VkDescriptorSet imGuiDescriptor = VK_NULL_HANDLE;
    };
    std::unordered_map<std::string, MaterialPreview> m_materialPreviews;
    VkRenderPass m_materialPreviewRenderPass = VK_NULL_HANDLE;
    VkSampler m_materialPreviewSampler = VK_NULL_HANDLE;
    std::unique_ptr<Pipeline> m_materialPreviewPipeline;  // Simple pipeline for preview rendering
    bool m_materialPreviewResourcesCreated = false;
    std::unique_ptr<Mesh> m_materialPreviewSphere;  // Sphere mesh for preview rendering
    VkBuffer m_materialPreviewSphereVertexBuffer = VK_NULL_HANDLE;
    VkDeviceMemory m_materialPreviewSphereVertexMemory = VK_NULL_HANDLE;
    VkBuffer m_materialPreviewSphereIndexBuffer = VK_NULL_HANDLE;
    VkDeviceMemory m_materialPreviewSphereIndexMemory = VK_NULL_HANDLE;
    u32 m_materialPreviewSphereIndexCount = 0;

    // Dedicated UBO for preview rendering (avoids conflicts with main renderer)
    VkBuffer m_materialPreviewUBO = VK_NULL_HANDLE;
    VkDeviceMemory m_materialPreviewUBOMemory = VK_NULL_HANDLE;
    VkDescriptorSet m_materialPreviewDescriptorSet = VK_NULL_HANDLE;  // UBO descriptor set

    void createMaterialPreviewResources();
    void cleanupMaterialPreviewResources();
    bool renderMaterialPreview(const std::string& materialName);
    MaterialPreview createMaterialPreviewTexture();
    void createMaterialPreviewSphereMesh();
    void cleanupMaterialPreviewSphereMesh();
    void createMaterialPreviewUBO();
    void cleanupMaterialPreviewUBO();
};

} // namespace arch
