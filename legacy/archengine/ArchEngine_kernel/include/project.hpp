#pragma once

#include "types.hpp"
#include "post_process.hpp"
#include <string>
#include <unordered_map>
#include <nlohmann/json.hpp>

namespace arch {

// Forward declarations
class Renderer;
struct ElementMaterialOverride;

/**
 * @brief Render settings for project serialization
 *
 * Contains all render-related settings that should be saved/loaded with a project.
 */
struct RenderSettings {
    // Shadows
    bool shadowsEnabled = true;
    f32 shadowBias = 0.02f;
    vec3 lightDirection = glm::normalize(vec3(-0.5f, -1.0f, -0.3f));

    // Post-processing
    SSAOConfig ssao;
    BloomConfig bloom;
    CompositeConfig composite;
    bool ssaoEnabled = true;
    bool bloomEnabled = true;
    bool postProcessingEnabled = false;

    // Material defaults
    f32 defaultMetallic = 0.0f;
    f32 defaultRoughness = 0.5f;
    f32 defaultAO = 1.0f;
    f32 defaultEmission = 0.0f;

    // Material adjustments
    f32 materialUVScale = 1.0f;
    f32 normalStrength = 1.0f;
    f32 materialBrightness = 0.0f;
    f32 materialContrast = 1.0f;
    f32 materialSaturation = 1.0f;
    f32 materialRoughnessOffset = 0.0f;
    f32 materialMetallicOffset = 0.0f;
    f32 materialAOStrength = 1.0f;
    vec3 materialTint = vec3(1.0f);

    // Tessellation & POM
    bool tessellationEnabled = false;
    bool pomEnabled = false;
    f32 tessellationLevel = 8.0f;
    f32 displacementScale = 0.1f;
    f32 pomHeightScale = 0.05f;
    f32 pomMinLayers = 8.0f;
    f32 pomMaxLayers = 32.0f;

    // Clipping
    bool clippingEnabled = false;
    bool clipFlipped = false;
    int clipAxis = 1;
    f32 clipHeight = 0.0f;

    // Style
    VisualizationMode vizMode = VisualizationMode::Material;
    MaterialStyle materialStyle = MaterialStyle::Realistic;
};

/**
 * @brief Complete project data for save/load
 *
 * Contains all data needed to fully restore a project state.
 */
struct ProjectData {
    static constexpr u32 CURRENT_VERSION = 1;

    u32 version = CURRENT_VERSION;
    std::string name;
    std::string description;
    std::string createdAt;
    std::string modifiedAt;

    Building building;
    CameraState camera;
    RenderSettings renderSettings;
    std::unordered_map<int, ElementMaterialOverride> elementOverrides;
};

/**
 * @brief Project manager for saving and loading .archproj files
 *
 * Provides static methods for project serialization and state management.
 */
class ProjectManager {
public:
    /**
     * @brief Save a project to a file
     * @param filepath Path to save the project (should end in .archproj)
     * @param project The project data to save
     * @return true if save succeeded
     */
    static bool saveProject(const std::string& filepath, const ProjectData& project);

    /**
     * @brief Load a project from a file
     * @param filepath Path to the project file
     * @return Loaded project data (empty project on failure)
     */
    static ProjectData loadProject(const std::string& filepath);

    /**
     * @brief Capture current state from renderer and building
     * @param name Project name
     * @param building Current building geometry
     * @param renderer Current renderer (for settings and camera)
     * @param camera Current camera state
     * @return ProjectData with captured state
     */
    static ProjectData captureState(const std::string& name,
                                    const Building& building,
                                    const Renderer& renderer,
                                    const Camera& camera);

    /**
     * @brief Apply loaded project state to renderer and building
     * @param project The project data to apply
     * @param building Building to update (output)
     * @param renderer Renderer to update (output)
     * @param camera Camera to update (output)
     */
    static void applyState(const ProjectData& project,
                           Building& building,
                           Renderer& renderer,
                           Camera& camera);

    /**
     * @brief Get current timestamp in ISO 8601 format
     * @return Timestamp string (e.g., "2024-01-15T10:30:00Z")
     */
    static std::string getCurrentTimestamp();

    /**
     * @brief Check if a file is an ArchEngine project file
     * @param filepath Path to check
     * @return true if file appears to be an .archproj file
     */
    static bool isProjectFile(const std::string& filepath);
};

// JSON serialization declarations
void to_json(nlohmann::json& j, const CameraState& c);
void from_json(const nlohmann::json& j, CameraState& c);

void to_json(nlohmann::json& j, const RenderSettings& r);
void from_json(const nlohmann::json& j, RenderSettings& r);

void to_json(nlohmann::json& j, const ProjectData& p);
void from_json(const nlohmann::json& j, ProjectData& p);

} // namespace arch
