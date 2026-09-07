#include "project.hpp"
#include "renderer.hpp"
#include "geometry_loader.hpp"
#include <fstream>
#include <iostream>
#include <chrono>
#include <iomanip>
#include <sstream>

namespace arch {

using json = nlohmann::json;

// ============================================================================
// Timestamp utility
// ============================================================================

std::string ProjectManager::getCurrentTimestamp() {
    auto now = std::chrono::system_clock::now();
    auto time = std::chrono::system_clock::to_time_t(now);
    std::tm tm = *std::gmtime(&time);

    std::ostringstream oss;
    oss << std::put_time(&tm, "%Y-%m-%dT%H:%M:%SZ");
    return oss.str();
}

bool ProjectManager::isProjectFile(const std::string& filepath) {
    // Check extension
    if (filepath.size() < 9) return false;  // ".archproj" = 9 chars
    std::string ext = filepath.substr(filepath.size() - 9);
    // Convert to lowercase for comparison
    for (auto& c : ext) c = static_cast<char>(std::tolower(c));
    return ext == ".archproj";
}

// ============================================================================
// JSON serialization for CameraState
// ============================================================================

void to_json(json& j, const CameraState& c) {
    j["position"] = {c.position.x, c.position.y, c.position.z};
    j["target"] = {c.target.x, c.target.y, c.target.z};
    j["up"] = {c.up.x, c.up.y, c.up.z};
    j["fov"] = c.fov;
    j["near_plane"] = c.nearPlane;
    j["far_plane"] = c.farPlane;
    j["speed"] = c.speed;
    j["sensitivity"] = c.sensitivity;
    j["is_orthographic"] = c.isOrthographic;
    j["ortho_size"] = c.orthoSize;
    j["view"] = static_cast<int>(c.view);
}

void from_json(const json& j, CameraState& c) {
    if (j.contains("position") && j["position"].size() >= 3) {
        c.position = {j["position"][0], j["position"][1], j["position"][2]};
    }
    if (j.contains("target") && j["target"].size() >= 3) {
        c.target = {j["target"][0], j["target"][1], j["target"][2]};
    }
    if (j.contains("up") && j["up"].size() >= 3) {
        c.up = {j["up"][0], j["up"][1], j["up"][2]};
    }
    c.fov = j.value("fov", 45.0f);
    c.nearPlane = j.value("near_plane", 0.1f);
    c.farPlane = j.value("far_plane", 1000.0f);
    c.speed = j.value("speed", 10.0f);
    c.sensitivity = j.value("sensitivity", 0.1f);
    c.isOrthographic = j.value("is_orthographic", false);
    c.orthoSize = j.value("ortho_size", 50.0f);
    c.view = static_cast<CameraView>(j.value("view", 0));
}

// ============================================================================
// JSON serialization for post-process configs
// ============================================================================

void to_json(json& j, const SSAOConfig& c) {
    j["kernel_size"] = c.kernelSize;
    j["radius"] = c.radius;
    j["bias"] = c.bias;
    j["intensity"] = c.intensity;
    j["power"] = c.power;
    j["enabled"] = c.enabled;
}

void from_json(const json& j, SSAOConfig& c) {
    c.kernelSize = j.value("kernel_size", 64u);
    c.radius = j.value("radius", 0.5f);
    c.bias = j.value("bias", 0.025f);
    c.intensity = j.value("intensity", 1.5f);
    c.power = j.value("power", 2.0f);
    c.enabled = j.value("enabled", true);
}

void to_json(json& j, const BloomConfig& c) {
    j["threshold"] = c.threshold;
    j["soft_threshold"] = c.softThreshold;
    j["intensity"] = c.intensity;
    j["iterations"] = c.iterations;
    j["enabled"] = c.enabled;
}

void from_json(const json& j, BloomConfig& c) {
    c.threshold = j.value("threshold", 1.0f);
    c.softThreshold = j.value("soft_threshold", 0.5f);
    c.intensity = j.value("intensity", 0.3f);
    c.iterations = j.value("iterations", 5u);
    c.enabled = j.value("enabled", true);
}

void to_json(json& j, const CompositeConfig& c) {
    j["exposure"] = c.exposure;
    j["tonemap_mode"] = c.tonemapMode;
    j["enabled"] = c.enabled;
}

void from_json(const json& j, CompositeConfig& c) {
    c.exposure = j.value("exposure", 1.0f);
    c.tonemapMode = j.value("tonemap_mode", 1u);
    c.enabled = j.value("enabled", true);
}

// ============================================================================
// JSON serialization for RenderSettings
// ============================================================================

void to_json(json& j, const RenderSettings& r) {
    // Shadows
    j["shadows"] = {
        {"enabled", r.shadowsEnabled},
        {"bias", r.shadowBias},
        {"light_direction", {r.lightDirection.x, r.lightDirection.y, r.lightDirection.z}}
    };

    // Post-processing
    json ssaoJ, bloomJ, compositeJ;
    to_json(ssaoJ, r.ssao);
    to_json(bloomJ, r.bloom);
    to_json(compositeJ, r.composite);

    j["ssao"] = ssaoJ;
    j["ssao"]["enabled"] = r.ssaoEnabled;  // Override with top-level enable flag
    j["bloom"] = bloomJ;
    j["bloom"]["enabled"] = r.bloomEnabled;
    j["composite"] = compositeJ;
    j["post_processing_enabled"] = r.postProcessingEnabled;

    // Material defaults
    j["material_defaults"] = {
        {"metallic", r.defaultMetallic},
        {"roughness", r.defaultRoughness},
        {"ao", r.defaultAO},
        {"emission", r.defaultEmission}
    };

    // Material adjustments
    j["material_adjustments"] = {
        {"uv_scale", r.materialUVScale},
        {"normal_strength", r.normalStrength},
        {"brightness", r.materialBrightness},
        {"contrast", r.materialContrast},
        {"saturation", r.materialSaturation},
        {"roughness_offset", r.materialRoughnessOffset},
        {"metallic_offset", r.materialMetallicOffset},
        {"ao_strength", r.materialAOStrength},
        {"tint", {r.materialTint.r, r.materialTint.g, r.materialTint.b}}
    };

    // Tessellation & POM
    j["tessellation"] = {
        {"enabled", r.tessellationEnabled},
        {"level", r.tessellationLevel},
        {"displacement_scale", r.displacementScale}
    };

    j["pom"] = {
        {"enabled", r.pomEnabled},
        {"height_scale", r.pomHeightScale},
        {"min_layers", r.pomMinLayers},
        {"max_layers", r.pomMaxLayers}
    };

    // Clipping
    j["clipping"] = {
        {"enabled", r.clippingEnabled},
        {"flipped", r.clipFlipped},
        {"axis", r.clipAxis},
        {"height", r.clipHeight}
    };

    // Style
    j["visualization_mode"] = static_cast<int>(r.vizMode);
    j["material_style"] = static_cast<int>(r.materialStyle);
}

void from_json(const json& j, RenderSettings& r) {
    // Shadows
    if (j.contains("shadows")) {
        const auto& s = j["shadows"];
        r.shadowsEnabled = s.value("enabled", true);
        r.shadowBias = s.value("bias", 0.02f);
        if (s.contains("light_direction") && s["light_direction"].size() >= 3) {
            r.lightDirection = glm::normalize(vec3(
                s["light_direction"][0],
                s["light_direction"][1],
                s["light_direction"][2]
            ));
        }
    }

    // Post-processing
    if (j.contains("ssao")) {
        from_json(j["ssao"], r.ssao);
        r.ssaoEnabled = j["ssao"].value("enabled", true);
    }
    if (j.contains("bloom")) {
        from_json(j["bloom"], r.bloom);
        r.bloomEnabled = j["bloom"].value("enabled", true);
    }
    if (j.contains("composite")) {
        from_json(j["composite"], r.composite);
    }
    r.postProcessingEnabled = j.value("post_processing_enabled", false);

    // Material defaults
    if (j.contains("material_defaults")) {
        const auto& md = j["material_defaults"];
        r.defaultMetallic = md.value("metallic", 0.0f);
        r.defaultRoughness = md.value("roughness", 0.5f);
        r.defaultAO = md.value("ao", 1.0f);
        r.defaultEmission = md.value("emission", 0.0f);
    }

    // Material adjustments
    if (j.contains("material_adjustments")) {
        const auto& ma = j["material_adjustments"];
        r.materialUVScale = ma.value("uv_scale", 1.0f);
        r.normalStrength = ma.value("normal_strength", 1.0f);
        r.materialBrightness = ma.value("brightness", 0.0f);
        r.materialContrast = ma.value("contrast", 1.0f);
        r.materialSaturation = ma.value("saturation", 1.0f);
        r.materialRoughnessOffset = ma.value("roughness_offset", 0.0f);
        r.materialMetallicOffset = ma.value("metallic_offset", 0.0f);
        r.materialAOStrength = ma.value("ao_strength", 1.0f);
        if (ma.contains("tint") && ma["tint"].size() >= 3) {
            r.materialTint = {ma["tint"][0], ma["tint"][1], ma["tint"][2]};
        }
    }

    // Tessellation
    if (j.contains("tessellation")) {
        const auto& t = j["tessellation"];
        r.tessellationEnabled = t.value("enabled", false);
        r.tessellationLevel = t.value("level", 8.0f);
        r.displacementScale = t.value("displacement_scale", 0.1f);
    }

    // POM
    if (j.contains("pom")) {
        const auto& p = j["pom"];
        r.pomEnabled = p.value("enabled", false);
        r.pomHeightScale = p.value("height_scale", 0.05f);
        r.pomMinLayers = p.value("min_layers", 8.0f);
        r.pomMaxLayers = p.value("max_layers", 32.0f);
    }

    // Clipping
    if (j.contains("clipping")) {
        const auto& c = j["clipping"];
        r.clippingEnabled = c.value("enabled", false);
        r.clipFlipped = c.value("flipped", false);
        r.clipAxis = c.value("axis", 1);
        r.clipHeight = c.value("height", 0.0f);
    }

    // Style
    r.vizMode = static_cast<VisualizationMode>(j.value("visualization_mode", 4));  // Material = 4
    r.materialStyle = static_cast<MaterialStyle>(j.value("material_style", 0));    // Realistic = 0
}

// ============================================================================
// JSON serialization for ElementMaterialOverride
// ============================================================================

static void to_json(json& j, const ElementMaterialOverride& o) {
    j["active"] = o.active;

    // Save flags
    j["has_uv_scale"] = o.hasUVScale;
    j["has_uv_rotation"] = o.hasUVRotation;
    j["has_normal_strength"] = o.hasNormalStrength;
    j["has_brightness"] = o.hasBrightness;
    j["has_contrast"] = o.hasContrast;
    j["has_saturation"] = o.hasSaturation;
    j["has_roughness"] = o.hasRoughness;
    j["has_metallic"] = o.hasMetallic;
    j["has_ao_strength"] = o.hasAOStrength;
    j["has_tint"] = o.hasTint;

    // Save values (only if flag is set to save space)
    if (o.hasUVScale) j["uv_scale"] = o.uvScale;
    if (o.hasUVRotation) j["uv_rotation"] = o.uvRotation;
    if (o.hasNormalStrength) j["normal_strength"] = o.normalStrength;
    if (o.hasBrightness) j["brightness"] = o.brightness;
    if (o.hasContrast) j["contrast"] = o.contrast;
    if (o.hasSaturation) j["saturation"] = o.saturation;
    if (o.hasRoughness) j["roughness"] = o.roughness;
    if (o.hasMetallic) j["metallic"] = o.metallic;
    if (o.hasAOStrength) j["ao_strength"] = o.aoStrength;
    if (o.hasTint) j["tint"] = {o.tint[0], o.tint[1], o.tint[2]};
}

static void from_json(const json& j, ElementMaterialOverride& o) {
    o.active = j.value("active", false);

    // Load flags
    o.hasUVScale = j.value("has_uv_scale", false);
    o.hasUVRotation = j.value("has_uv_rotation", false);
    o.hasNormalStrength = j.value("has_normal_strength", false);
    o.hasBrightness = j.value("has_brightness", false);
    o.hasContrast = j.value("has_contrast", false);
    o.hasSaturation = j.value("has_saturation", false);
    o.hasRoughness = j.value("has_roughness", false);
    o.hasMetallic = j.value("has_metallic", false);
    o.hasAOStrength = j.value("has_ao_strength", false);
    o.hasTint = j.value("has_tint", false);

    // Load values
    o.uvScale = j.value("uv_scale", 1.0f);
    o.uvRotation = j.value("uv_rotation", 0.0f);
    o.normalStrength = j.value("normal_strength", 1.0f);
    o.brightness = j.value("brightness", 0.0f);
    o.contrast = j.value("contrast", 1.0f);
    o.saturation = j.value("saturation", 1.0f);
    o.roughness = j.value("roughness", 0.5f);
    o.metallic = j.value("metallic", 0.0f);
    o.aoStrength = j.value("ao_strength", 1.0f);

    if (j.contains("tint") && j["tint"].size() >= 3) {
        o.tint[0] = j["tint"][0];
        o.tint[1] = j["tint"][1];
        o.tint[2] = j["tint"][2];
    }
}

// ============================================================================
// JSON serialization for ProjectData
// ============================================================================

void to_json(json& j, const ProjectData& p) {
    j["version"] = p.version;
    j["name"] = p.name;
    j["description"] = p.description;
    j["created_at"] = p.createdAt;
    j["modified_at"] = p.modifiedAt;

    // Camera
    json cameraJ;
    to_json(cameraJ, p.camera);
    j["camera"] = cameraJ;

    // Render settings
    json renderJ;
    to_json(renderJ, p.renderSettings);
    j["render_settings"] = renderJ;

    // Building (use existing serialization)
    json buildingJ;
    arch::to_json(buildingJ, p.building);
    j["building"] = buildingJ;

    // Element material overrides
    json overridesJ = json::array();
    for (const auto& [elementIndex, override] : p.elementOverrides) {
        json o;
        o["element_index"] = elementIndex;
        to_json(o, override);
        overridesJ.push_back(o);
    }
    j["element_material_overrides"] = overridesJ;
}

void from_json(const json& j, ProjectData& p) {
    p.version = j.value("version", 1u);
    p.name = j.value("name", "Untitled Project");
    p.description = j.value("description", "");
    p.createdAt = j.value("created_at", "");
    p.modifiedAt = j.value("modified_at", "");

    // Camera
    if (j.contains("camera")) {
        arch::from_json(j["camera"], p.camera);
    }

    // Render settings
    if (j.contains("render_settings")) {
        arch::from_json(j["render_settings"], p.renderSettings);
    }

    // Building
    if (j.contains("building")) {
        arch::from_json(j["building"], p.building);
    }

    // Element material overrides
    p.elementOverrides.clear();
    if (j.contains("element_material_overrides") && j["element_material_overrides"].is_array()) {
        for (const auto& o : j["element_material_overrides"]) {
            if (o.contains("element_index")) {
                int idx = o["element_index"];
                ElementMaterialOverride override;
                from_json(o, override);
                p.elementOverrides[idx] = override;
            }
        }
    }
}

// ============================================================================
// ProjectManager implementation
// ============================================================================

bool ProjectManager::saveProject(const std::string& filepath, const ProjectData& project) {
    try {
        json j;
        to_json(j, project);

        std::ofstream file(filepath);
        if (!file.is_open()) {
            std::cerr << "Failed to open file for writing: " << filepath << "\n";
            return false;
        }

        file << j.dump(2);  // Pretty print with 2-space indent
        file.close();

        std::cout << "Project saved: " << filepath << "\n";
        return true;

    } catch (const std::exception& e) {
        std::cerr << "Failed to save project: " << e.what() << "\n";
        return false;
    }
}

ProjectData ProjectManager::loadProject(const std::string& filepath) {
    ProjectData project;

    try {
        std::ifstream file(filepath);
        if (!file.is_open()) {
            std::cerr << "Failed to open project file: " << filepath << "\n";
            return project;
        }

        json j = json::parse(file);
        from_json(j, project);

        std::cout << "Project loaded: " << project.name << " (v" << project.version << ")\n";

    } catch (const std::exception& e) {
        std::cerr << "Failed to load project: " << e.what() << "\n";
    }

    return project;
}

ProjectData ProjectManager::captureState(const std::string& name,
                                         const Building& building,
                                         const Renderer& renderer,
                                         const Camera& camera) {
    ProjectData project;

    project.version = ProjectData::CURRENT_VERSION;
    project.name = name;
    project.createdAt = getCurrentTimestamp();
    project.modifiedAt = project.createdAt;

    project.building = building;
    project.camera = CameraState::fromCamera(camera);
    project.renderSettings = renderer.getRenderSettings();
    project.elementOverrides = renderer.getAllElementOverrides();

    return project;
}

void ProjectManager::applyState(const ProjectData& project,
                                Building& building,
                                Renderer& renderer,
                                Camera& camera) {
    building = project.building;
    camera = project.camera.toCamera();
    renderer.setRenderSettings(project.renderSettings);
    renderer.setAllElementOverrides(project.elementOverrides);
    renderer.setCamera(camera);
}

} // namespace arch
