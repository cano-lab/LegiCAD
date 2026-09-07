#include "geometry_loader.hpp"
#include <iostream>
#include <cmath>

namespace arch {

// Feet to millimeters conversion factor
constexpr f32 FT_TO_MM = 304.8f;

// Compute terrain elevation color based on normalized height [0-1]
// Returns darker earth tones that contrast well with building materials
static vec3 getElevationColor(f32 normalizedElevation) {
    // Clamp to [0, 1]
    f32 t = glm::clamp(normalizedElevation, 0.0f, 1.0f);

    // Darker earth tones that contrast with light building materials
    const vec3 lowDark   = vec3(0.15f, 0.20f, 0.10f);   // Dark earth/mud
    const vec3 lowGreen  = vec3(0.20f, 0.35f, 0.15f);   // Dark grass green
    const vec3 midOlive  = vec3(0.35f, 0.40f, 0.20f);   // Olive green
    const vec3 highTan   = vec3(0.50f, 0.45f, 0.30f);   // Muted tan

    // Four-stop gradient with muted colors
    if (t < 0.25f) {
        // Low elevation: dark earth to dark green
        return glm::mix(lowDark, lowGreen, t * 4.0f);
    } else if (t < 0.50f) {
        // Lower-mid: dark green to olive
        return glm::mix(lowGreen, midOlive, (t - 0.25f) * 4.0f);
    } else if (t < 0.75f) {
        // Upper-mid: olive to tan
        return glm::mix(midOlive, highTan, (t - 0.50f) * 4.0f);
    } else {
        // High: muted tan (no bright colors that compete with buildings)
        return glm::mix(highTan, vec3(0.55f, 0.50f, 0.35f), (t - 0.75f) * 4.0f);
    }
}

void GeometryLoader::addColumn(Building& building, vec3 position, f32 width, f32 depth, f32 height,
                               const std::string& material, f32 stress) {
    StructuralElement col;
    col.type = ElementType::Column;
    col.start = position;
    col.end = position + vec3(0, height, 0);
    col.width = width;
    col.depth = depth;
    col.material = material;
    col.stress = stress;
    col.deflection = 0.0f;
    col.failed = stress > 1.0f;
    building.elements.push_back(col);
}

void GeometryLoader::addBeam(Building& building, vec3 start, vec3 end, f32 width, f32 depth,
                             const std::string& material, f32 stress, f32 deflection) {
    StructuralElement beam;
    beam.type = ElementType::Beam;
    beam.start = start;
    beam.end = end;
    beam.width = width;
    beam.depth = depth;
    beam.material = material;
    beam.stress = stress;
    beam.deflection = deflection;
    beam.failed = stress > 1.0f;
    building.elements.push_back(beam);
}

void GeometryLoader::addFloor(Building& building, vec3 position, f32 width, f32 depth, f32 thickness,
                              const std::string& material) {
    StructuralElement floor;
    floor.type = ElementType::Floor;
    floor.start = position;
    floor.end = position + vec3(width, 0, depth);
    floor.width = width;
    floor.depth = thickness;
    floor.material = material;
    floor.stress = 0.0f;
    floor.deflection = 0.0f;
    floor.failed = false;
    building.elements.push_back(floor);
}

void GeometryLoader::addWall(Building& building, vec3 start, vec3 end, f32 height, f32 thickness,
                             const std::string& material) {
    StructuralElement wall;
    wall.type = ElementType::Wall;
    wall.start = start;
    wall.end = vec3(end.x, start.y + height, end.z);
    wall.width = glm::length(vec2(end.x - start.x, end.z - start.z));
    wall.depth = thickness;
    wall.material = material;
    wall.stress = 0.0f;
    wall.deflection = 0.0f;
    wall.failed = false;
    building.elements.push_back(wall);
}

void GeometryLoader::addDoor(Building& building, vec3 position, f32 width, f32 height, f32 depth,
                             const std::string& material) {
    StructuralElement door;
    door.type = ElementType::Door;
    door.start = position;
    door.end = position + vec3(0, height, 0);
    door.width = width;
    door.depth = depth;
    door.material = material;
    door.stress = 0.0f;
    door.deflection = 0.0f;
    door.failed = false;
    building.elements.push_back(door);
}

void GeometryLoader::addWindow(Building& building, vec3 position, f32 width, f32 height, f32 depth,
                               const std::string& material) {
    StructuralElement window;
    window.type = ElementType::Window;
    window.start = position;
    window.end = position + vec3(0, height, 0);
    window.width = width;
    window.depth = depth;
    window.material = material;
    window.stress = 0.0f;
    window.deflection = 0.0f;
    window.failed = false;
    building.elements.push_back(window);
}

void GeometryLoader::addRoof(Building& building, vec3 position, f32 width, f32 depth, f32 thickness,
                             const std::string& material) {
    StructuralElement roof;
    roof.type = ElementType::Roof;
    roof.start = position;
    roof.end = position + vec3(width, thickness, depth);
    roof.width = width;
    roof.depth = thickness;
    roof.material = material;
    roof.stress = 0.0f;
    roof.deflection = 0.0f;
    roof.failed = false;
    building.elements.push_back(roof);
}

Building GeometryLoader::createSimpleFrame(f32 width, f32 depth, f32 height) {
    Building building;
    building.name = "Simple Frame";

    f32 colWidth = 0.83f;
    f32 colDepth = 0.83f;
    f32 beamWidth = 0.52f;
    f32 beamDepth = 1.0f;

    int colsX = 3;
    int colsZ = 2;
    f32 spacingX = width / (colsX - 1);
    f32 spacingZ = depth / (colsZ - 1);

    for (int x = 0; x < colsX; ++x) {
        for (int z = 0; z < colsZ; ++z) {
            vec3 pos(x * spacingX, 0, z * spacingZ);
            f32 stress = 0.3f + 0.2f * ((float)x / colsX) + 0.1f * ((float)z / colsZ);
            addColumn(building, pos, colWidth, colDepth, height, "steel", stress);
        }
    }

    for (int z = 0; z < colsZ; ++z) {
        for (int x = 0; x < colsX - 1; ++x) {
            vec3 start(x * spacingX, height, z * spacingZ);
            vec3 end((x + 1) * spacingX, height, z * spacingZ);
            f32 stress = 0.5f + 0.15f * x;
            f32 deflection = 0.002f * (1.0f + 0.5f * x);
            addBeam(building, start, end, beamWidth, beamDepth, "steel", stress, deflection);
        }
    }

    for (int x = 0; x < colsX; ++x) {
        for (int z = 0; z < colsZ - 1; ++z) {
            vec3 start(x * spacingX, height, z * spacingZ);
            vec3 end(x * spacingX, height, (z + 1) * spacingZ);
            f32 stress = 0.4f + 0.1f * z;
            addBeam(building, start, end, beamWidth, beamDepth * 0.8f, "steel", stress, 0.001f);
        }
    }

    return building;
}

Building GeometryLoader::createMultiStoryFrame(int stories, f32 width, f32 depth, f32 storyHeight) {
    Building building;
    building.name = "Multi-Story Frame (" + std::to_string(stories) + " floors)";

    f32 colWidth = 0.83f;
    f32 colDepth = 0.83f;
    f32 beamWidth = 0.5f;
    f32 beamDepth = 1.0f;

    int colsX = 4;
    int colsZ = 3;
    f32 spacingX = width / (colsX - 1);
    f32 spacingZ = depth / (colsZ - 1);

    for (int story = 0; story < stories; ++story) {
        f32 baseY = story * storyHeight;
        f32 topY = (story + 1) * storyHeight;
        f32 storyStressFactor = 1.0f - (float)story / stories * 0.4f;

        for (int x = 0; x < colsX; ++x) {
            for (int z = 0; z < colsZ; ++z) {
                vec3 pos(x * spacingX, baseY, z * spacingZ);
                f32 stress = 0.4f * storyStressFactor + 0.1f * ((float)(x + z) / (colsX + colsZ));
                addColumn(building, pos, colWidth, colDepth, storyHeight, "steel", stress);
            }
        }

        for (int z = 0; z < colsZ; ++z) {
            for (int x = 0; x < colsX - 1; ++x) {
                vec3 start(x * spacingX, topY, z * spacingZ);
                vec3 end((x + 1) * spacingX, topY, z * spacingZ);
                f32 stress = 0.5f + 0.1f * storyStressFactor;
                addBeam(building, start, end, beamWidth, beamDepth, "steel", stress, 0.002f);
            }
        }

        for (int x = 0; x < colsX; ++x) {
            for (int z = 0; z < colsZ - 1; ++z) {
                vec3 start(x * spacingX, topY, z * spacingZ);
                vec3 end(x * spacingX, topY, (z + 1) * spacingZ);
                f32 stress = 0.45f + 0.05f * storyStressFactor;
                addBeam(building, start, end, beamWidth, beamDepth * 0.9f, "steel", stress, 0.001f);
            }
        }

        addFloor(building, vec3(0, topY, 0), width, depth, 0.5f, "concrete");
    }

    return building;
}

Building GeometryLoader::createWarehouse(f32 width, f32 depth, f32 height) {
    Building building;
    building.name = "Warehouse";

    f32 colWidth = 1.0f;
    f32 colDepth = 1.0f;
    f32 beamWidth = 0.67f;
    f32 beamDepth = 2.0f;

    int colsX = 5;
    int colsZ = 4;
    f32 spacingX = width / (colsX - 1);
    f32 spacingZ = depth / (colsZ - 1);

    for (int x = 0; x < colsX; ++x) {
        addColumn(building, vec3(x * spacingX, 0, 0), colWidth, colDepth, height, "steel", 0.35f);
        addColumn(building, vec3(x * spacingX, 0, depth), colWidth, colDepth, height, "steel", 0.35f);
    }
    for (int z = 1; z < colsZ - 1; ++z) {
        addColumn(building, vec3(0, 0, z * spacingZ), colWidth, colDepth, height, "steel", 0.35f);
        addColumn(building, vec3(width, 0, z * spacingZ), colWidth, colDepth, height, "steel", 0.35f);
    }

    for (int x = 2; x < colsX - 1; x += 2) {
        for (int z = 1; z < colsZ - 1; z += 2) {
            addColumn(building, vec3(x * spacingX, 0, z * spacingZ), colWidth * 1.2f, colDepth * 1.2f,
                     height, "steel", 0.5f);
        }
    }

    for (int z = 0; z < colsZ; ++z) {
        vec3 start(0, height, z * spacingZ);
        vec3 end(width, height, z * spacingZ);
        f32 stress = 0.6f + 0.1f * ((float)z / colsZ);
        addBeam(building, start, end, beamWidth, beamDepth, "steel", stress, 0.005f);
    }

    for (int x = 0; x < colsX; ++x) {
        vec3 start(x * spacingX, height, 0);
        vec3 end(x * spacingX, height, depth);
        addBeam(building, start, end, beamWidth * 0.8f, beamDepth * 0.8f, "steel", 0.5f, 0.003f);
    }

    return building;
}

Building GeometryLoader::createResidential(f32 width, f32 depth, int stories) {
    Building building;
    building.name = "Residential (" + std::to_string(stories) + " story)";

    f32 studWidth = 0.292f;
    f32 studDepth = 0.125f;
    f32 joistWidth = 0.125f;
    f32 joistDepth = 0.792f;
    f32 storyHeight = 9.0f;

    int postsX = 3;
    int postsZ = 2;
    f32 spacingX = width / (postsX - 1);
    f32 spacingZ = depth / (postsZ - 1);

    for (int story = 0; story < stories; ++story) {
        f32 baseY = story * storyHeight;
        f32 topY = (story + 1) * storyHeight;

        for (int x = 0; x < postsX; ++x) {
            for (int z = 0; z < postsZ; ++z) {
                vec3 pos(x * spacingX, baseY, z * spacingZ);
                addColumn(building, pos, studWidth, studDepth, storyHeight, "wood", 0.3f);
            }
        }

        int numJoists = static_cast<int>(width / 1.33f);
        for (int j = 0; j <= numJoists; ++j) {
            f32 jx = j * (width / numJoists);
            vec3 start(jx, topY, 0);
            vec3 end(jx, topY, depth);
            addBeam(building, start, end, joistWidth, joistDepth, "wood", 0.35f, 0.003f);
        }

        addBeam(building, vec3(0, topY, 0), vec3(width, topY, 0), joistWidth, joistDepth, "wood", 0.25f);
        addBeam(building, vec3(0, topY, depth), vec3(width, topY, depth), joistWidth, joistDepth, "wood", 0.25f);
    }

    return building;
}

Building GeometryLoader::loadFromJSON(const std::string& filepath) {
    Building building;

    std::ifstream file(filepath);
    if (!file.is_open()) {
        std::cerr << "Failed to open file: " << filepath << "\n";
        return building;
    }

    try {
        json data = json::parse(file);
        from_json(data, building);
    } catch (const std::exception& e) {
        std::cerr << "Failed to parse JSON: " << e.what() << "\n";
    }

    return building;
}

void GeometryLoader::saveToJSON(const std::string& filepath, const Building& building) {
    json data;
    to_json(data, building);

    std::ofstream file(filepath);
    if (file.is_open()) {
        file << data.dump(2);
    } else {
        std::cerr << "Failed to save to: " << filepath << "\n";
    }
}

void GeometryLoader::saveToJSON(const std::string& filepath, const Building& building, const Renderer& renderer) {
    json data;
    to_json(data, building);

    // Add element material overrides
    json overrides = json::array();
    for (size_t i = 0; i < building.elements.size(); i++) {
        const ElementMaterialOverride* override = renderer.getElementOverride(static_cast<int>(i));
        if (override && override->active) {
            json o;
            o["element_index"] = static_cast<int>(i);

            // Save per-parameter flags and values
            o["has_uv_scale"] = override->hasUVScale;
            o["has_uv_rotation"] = override->hasUVRotation;
            o["has_normal_strength"] = override->hasNormalStrength;
            o["has_brightness"] = override->hasBrightness;
            o["has_contrast"] = override->hasContrast;
            o["has_saturation"] = override->hasSaturation;
            o["has_roughness"] = override->hasRoughness;
            o["has_metallic"] = override->hasMetallic;
            o["has_ao_strength"] = override->hasAOStrength;
            o["has_tint"] = override->hasTint;

            // Only save values if the flag is set (save space)
            if (override->hasUVScale) o["uv_scale"] = override->uvScale;
            if (override->hasUVRotation) o["uv_rotation"] = override->uvRotation;
            if (override->hasNormalStrength) o["normal_strength"] = override->normalStrength;
            if (override->hasBrightness) o["brightness"] = override->brightness;
            if (override->hasContrast) o["contrast"] = override->contrast;
            if (override->hasSaturation) o["saturation"] = override->saturation;
            if (override->hasRoughness) o["roughness"] = override->roughness;
            if (override->hasMetallic) o["metallic"] = override->metallic;
            if (override->hasAOStrength) o["ao_strength"] = override->aoStrength;
            if (override->hasTint) o["tint"] = {override->tint[0], override->tint[1], override->tint[2]};

            overrides.push_back(o);
        }
    }
    data["element_material_overrides"] = overrides;

    std::ofstream file(filepath);
    if (file.is_open()) {
        file << data.dump(2);
    } else {
        std::cerr << "Failed to save to: " << filepath << "\n";
    }
}

Building GeometryLoader::loadFromIFC(const std::string& filepath) {
    Building building;
    building.name = "IFC Import";

    std::string tempJson = "X:/tmp/temp_ifc_import.json";
    std::string scriptPath = "X:/ARCH/Software/ArchEngine/scripts/ifc_import.py";
    std::string cmd = "python \"" + scriptPath + "\" \"" + filepath + "\" \"" + tempJson + "\"";

    int result = system(cmd.c_str());
    if (result != 0) {
        std::cerr << "IFC import failed. Make sure ifcopenshell is installed: pip install ifcopenshell\n";
        return building;
    }

    building = loadFromJSON(tempJson);
    std::remove(tempJson.c_str());

    if (building.elements.empty()) {
        std::cerr << "No elements imported from IFC file\n";
    } else {
        std::cout << "Imported " << building.elements.size() << " elements from IFC\n";
    }

    return building;
}

void GeometryLoader::loadMaterialOverrides(const std::string& filepath, Renderer& renderer) {
    std::ifstream file(filepath);
    if (!file.is_open()) {
        std::cerr << "Failed to open file for material override loading: " << filepath << "\n";
        return;
    }

    try {
        json data = json::parse(file);

        // Check if element_material_overrides section exists
        if (!data.contains("element_material_overrides")) {
            return;  // No overrides in this file, that's fine
        }

        const auto& overrides = data["element_material_overrides"];
        if (!overrides.is_array()) {
            std::cerr << "element_material_overrides is not an array\n";
            return;
        }

        // Load each override
        for (const auto& o : overrides) {
            if (!o.contains("element_index")) {
                continue;
            }

            int elementIndex = o["element_index"];

            ElementMaterialOverride override;
            override.active = true;

            // Load per-parameter flags (new format)
            if (o.contains("has_uv_scale")) {
                override.hasUVScale = o["has_uv_scale"];
                override.hasUVRotation = o.value("has_uv_rotation", false);
                override.hasNormalStrength = o.value("has_normal_strength", false);
                override.hasBrightness = o.value("has_brightness", false);
                override.hasContrast = o.value("has_contrast", false);
                override.hasSaturation = o.value("has_saturation", false);
                override.hasRoughness = o.value("has_roughness", false);
                override.hasMetallic = o.value("has_metallic", false);
                override.hasAOStrength = o.value("has_ao_strength", false);
                override.hasTint = o.value("has_tint", false);

                // Load values (only if flag is true)
                override.uvScale = o.value("uv_scale", 1.0f);
                override.uvRotation = o.value("uv_rotation", 0.0f);
                override.normalStrength = o.value("normal_strength", 1.0f);
                override.brightness = o.value("brightness", 0.0f);
                override.contrast = o.value("contrast", 1.0f);
                override.saturation = o.value("saturation", 1.0f);
                override.roughness = o.value("roughness", 0.5f);
                override.metallic = o.value("metallic", 0.0f);
                override.aoStrength = o.value("ao_strength", 1.0f);

                if (o.contains("tint") && o["tint"].size() >= 3) {
                    override.tint[0] = o["tint"][0];
                    override.tint[1] = o["tint"][1];
                    override.tint[2] = o["tint"][2];
                }
            } else {
                // Old format (without flags) - load and set flags based on value presence
                override.uvScale = o.value("uv_scale", 1.0f);
                override.hasUVScale = o.contains("uv_scale");

                override.uvRotation = o.value("uv_rotation", 0.0f);
                override.hasUVRotation = o.contains("uv_rotation");

                override.normalStrength = o.value("normal_strength", 1.0f);
                override.hasNormalStrength = o.contains("normal_strength");

                override.brightness = o.value("brightness", 0.0f);
                override.hasBrightness = o.contains("brightness");

                override.contrast = o.value("contrast", 1.0f);
                override.hasContrast = o.contains("contrast");

                override.saturation = o.value("saturation", 1.0f);
                override.hasSaturation = o.contains("saturation");

                override.roughness = o.value("roughness", 0.5f);
                override.hasRoughness = o.contains("roughness");

                override.metallic = o.value("metallic", 0.0f);
                override.hasMetallic = o.contains("metallic");

                override.aoStrength = o.value("ao_strength", 1.0f);
                override.hasAOStrength = o.contains("ao_strength");

                if (o.contains("tint") && o["tint"].size() >= 3) {
                    override.tint[0] = o["tint"][0];
                    override.tint[1] = o["tint"][1];
                    override.tint[2] = o["tint"][2];
                    override.hasTint = true;
                }
            }

            renderer.setElementOverride(elementIndex, override);
        }

        std::cout << "Loaded " << overrides.size() << " element material overrides\n";

    } catch (const std::exception& e) {
        std::cerr << "Failed to load material overrides: " << e.what() << "\n";
    }
}

void to_json(json& j, const Building& b) {
    j["name"] = b.name;
    j["elements"] = json::array();

    for (const auto& elem : b.elements) {
        json e;
        e["type"] = static_cast<int>(elem.type);
        e["start"] = {elem.start.x, elem.start.y, elem.start.z};
        e["end"] = {elem.end.x, elem.end.y, elem.end.z};
        e["width"] = elem.width;
        e["depth"] = elem.depth;
        e["material"] = elem.material;
        e["stress"] = elem.stress;
        e["deflection"] = elem.deflection;
        e["failed"] = elem.failed;
        j["elements"].push_back(e);
    }

    // Wall types (assembly recipes)
    j["wallTypes"] = json::array();
    for (const auto& wt : b.wallTypes) {
        json wtj;
        to_json(wtj, wt);
        j["wallTypes"].push_back(wtj);
    }

    // Parametric walls
    j["parametricWalls"] = json::array();
    for (const auto& pw : b.parametricWalls) {
        json pwj;
        to_json(pwj, pw);
        j["parametricWalls"].push_back(pwj);
    }
}

void from_json(const json& j, Building& b) {
    b.name = j.value("name", "Unnamed Building");
    b.elements.clear();

    if (j.contains("elements")) {
        for (const auto& e : j["elements"]) {
            StructuralElement elem;
            elem.type = static_cast<ElementType>(e.value("type", 0));

            if (e.contains("start")) {
                elem.start = {e["start"][0], e["start"][1], e["start"][2]};
            }
            if (e.contains("end")) {
                elem.end = {e["end"][0], e["end"][1], e["end"][2]};
            }

            elem.width = e.value("width", 0.5f);
            elem.depth = e.value("depth", 0.5f);
            elem.material = e.value("material", "steel");
            elem.stress = e.value("stress", 0.0f);
            elem.deflection = e.value("deflection", 0.0f);
            elem.failed = e.value("failed", false);

            // Parse mesh data if present
            if (e.contains("mesh")) {
                const auto& meshData = e["mesh"];
                if (meshData.contains("vertices") && meshData.contains("faces")) {
                    for (const auto& v : meshData["vertices"]) {
                        elem.mesh.vertices.push_back({v[0], v[1], v[2]});
                    }
                    for (const auto& f : meshData["faces"]) {
                        elem.mesh.faces.push_back({f[0], f[1], f[2]});
                    }
                }
            }

            b.elements.push_back(elem);
        }
    }

    // Parse wall types
    if (j.contains("wallTypes")) {
        for (const auto& wt : j["wallTypes"]) {
            WallType wallType;
            from_json(wt, wallType);
            b.wallTypes.push_back(wallType);
        }
    }

    // Parse parametric walls
    if (j.contains("parametricWalls")) {
        for (const auto& pw : j["parametricWalls"]) {
            ParametricWall wall;
            from_json(pw, wall);
            b.parametricWalls.push_back(wall);
        }
    }

    // Parse terrain mesh
    if (j.contains("terrain_mesh")) {
        const auto& tm = j["terrain_mesh"];
        std::cout << "[Terrain] Found terrain_mesh in JSON\n";

        // Get elevation range for color computation
        f32 minElev = tm.value("min_elevation", 0.0f);
        f32 maxElev = tm.value("max_elevation", 100.0f);
        f32 elevRange = maxElev - minElev;
        if (elevRange < 0.001f) elevRange = 1.0f;  // Avoid division by zero

        // Store metadata
        b.terrainMesh.width_ft = tm.value("width_ft", 0.0f);
        b.terrainMesh.depth_ft = tm.value("depth_ft", 0.0f);
        b.terrainMesh.min_elevation = minElev;
        b.terrainMesh.max_elevation = maxElev;

        // Convert min/max elevation from feet to mm for coloring comparison
        f32 minElevMm = minElev * FT_TO_MM;
        f32 maxElevMm = maxElev * FT_TO_MM;
        f32 elevRangeMm = maxElevMm - minElevMm;
        if (elevRangeMm < 0.001f) elevRangeMm = 1.0f;

        // Parse vertices - positions are already in mm from Python
        if (tm.contains("vertices")) {
            std::cout << "[Terrain] Parsing " << tm["vertices"].size() << " vertices\n";
            for (const auto& v : tm["vertices"]) {
                Vertex vert;

                // Position: already in millimeters from Python
                // JSON format: position is [x_mm, y_mm (elevation/up), z_mm (depth)]
                if (v.contains("position") && v["position"].size() >= 3) {
                    f32 x_mm = v["position"][0].get<f32>();
                    f32 y_mm = v["position"][1].get<f32>();  // Elevation (Y is up)
                    f32 z_mm = v["position"][2].get<f32>();  // Depth

                    // Direct mapping - Python uses Y-up coordinate system, same as renderer
                    vert.position = vec3(x_mm, y_mm, z_mm);

                    // Compute color from elevation (Y component)
                    f32 normalizedElev = (y_mm - minElevMm) / elevRangeMm;
                    vert.color = getElevationColor(normalizedElev);
                }

                // Normal - Python uses Y-up, same as renderer
                if (v.contains("normal") && v["normal"].size() >= 3) {
                    f32 nx = v["normal"][0].get<f32>();
                    f32 ny = v["normal"][1].get<f32>();
                    f32 nz = v["normal"][2].get<f32>();
                    vert.normal = glm::normalize(vec3(nx, ny, nz));
                } else {
                    vert.normal = vec3(0.0f, 1.0f, 0.0f);  // Default up
                }

                // UV coordinates - use from JSON if provided, otherwise compute world-space UV
                if (v.contains("uv") && v["uv"].size() >= 2) {
                    vert.texCoord = vec2(v["uv"][0].get<f32>(), v["uv"][1].get<f32>());
                } else {
                    // Compute world-space UV from position (after conversion to mm)
                    // Path tracer uses: worldPos.xz * 0.001 * uvScale
                    // So base texCoord = position.xz * 0.001
                    vert.texCoord = vec2(vert.position.x, vert.position.z) * 0.001f;
                }

                vert.stress = 0.0f;  // Terrain has no stress

                b.terrainMesh.vertices.push_back(vert);
            }
        }

        // Parse indices
        if (tm.contains("indices")) {
            for (const auto& idx : tm["indices"]) {
                b.terrainMesh.indices.push_back(idx.get<u32>());
            }
        }

        if (b.terrainMesh.hasData()) {
            std::cout << "[Terrain] Loaded mesh: " << b.terrainMesh.vertices.size()
                      << " vertices, " << (b.terrainMesh.indices.size() / 3)
                      << " triangles, elevation " << minElev << "-" << maxElev << " ft\n";
        }
    }
}

// ============================================================================
// ASSEMBLY RECIPE JSON SERIALIZATION
// ============================================================================

// Helper: enum to string conversions
static const char* fastenerTypeToString(FastenerType t) {
    switch (t) {
        case FastenerType::Nail: return "nail";
        case FastenerType::Screw: return "screw";
        case FastenerType::Bolt: return "bolt";
        case FastenerType::Staple: return "staple";
        case FastenerType::Anchor: return "anchor";
        case FastenerType::Strap: return "strap";
        case FastenerType::Hanger: return "hanger";
        case FastenerType::Clip: return "clip";
        case FastenerType::Adhesive: return "adhesive";
        default: return "nail";
    }
}

static FastenerType stringToFastenerType(const std::string& s) {
    if (s == "screw") return FastenerType::Screw;
    if (s == "bolt") return FastenerType::Bolt;
    if (s == "staple") return FastenerType::Staple;
    if (s == "anchor") return FastenerType::Anchor;
    if (s == "strap") return FastenerType::Strap;
    if (s == "hanger") return FastenerType::Hanger;
    if (s == "clip") return FastenerType::Clip;
    if (s == "adhesive") return FastenerType::Adhesive;
    return FastenerType::Nail;
}

static const char* constraintTypeToString(ConstraintType t) {
    switch (t) {
        case ConstraintType::StructuralBearing: return "structural_bearing";
        case ConstraintType::FireRating: return "fire_rating";
        case ConstraintType::ThermalPerformance: return "thermal_performance";
        case ConstraintType::SoundTransmission: return "sound_transmission";
        case ConstraintType::MoistureControl: return "moisture_control";
        case ConstraintType::AirBarrier: return "air_barrier";
        case ConstraintType::WindResistance: return "wind_resistance";
        case ConstraintType::SeismicCategory: return "seismic_category";
        case ConstraintType::MaxSpan: return "max_span";
        case ConstraintType::MinThickness: return "min_thickness";
        case ConstraintType::CodeSection: return "code_section";
        default: return "code_section";
    }
}

static ConstraintType stringToConstraintType(const std::string& s) {
    if (s == "structural_bearing") return ConstraintType::StructuralBearing;
    if (s == "fire_rating") return ConstraintType::FireRating;
    if (s == "thermal_performance") return ConstraintType::ThermalPerformance;
    if (s == "sound_transmission") return ConstraintType::SoundTransmission;
    if (s == "moisture_control") return ConstraintType::MoistureControl;
    if (s == "air_barrier") return ConstraintType::AirBarrier;
    if (s == "wind_resistance") return ConstraintType::WindResistance;
    if (s == "seismic_category") return ConstraintType::SeismicCategory;
    if (s == "max_span") return ConstraintType::MaxSpan;
    if (s == "min_thickness") return ConstraintType::MinThickness;
    return ConstraintType::CodeSection;
}

static const char* intentCategoryToString(IntentCategory c) {
    switch (c) {
        case IntentCategory::Performance: return "performance";
        case IntentCategory::Constructability: return "constructability";
        case IntentCategory::Cost: return "cost";
        case IntentCategory::Sustainability: return "sustainability";
        case IntentCategory::Durability: return "durability";
        case IntentCategory::Aesthetic: return "aesthetic";
        case IntentCategory::CodeCompliance: return "code_compliance";
        default: return "performance";
    }
}

static IntentCategory stringToIntentCategory(const std::string& s) {
    if (s == "constructability") return IntentCategory::Constructability;
    if (s == "cost") return IntentCategory::Cost;
    if (s == "sustainability") return IntentCategory::Sustainability;
    if (s == "durability") return IntentCategory::Durability;
    if (s == "aesthetic") return IntentCategory::Aesthetic;
    if (s == "code_compliance") return IntentCategory::CodeCompliance;
    return IntentCategory::Performance;
}

static const char* layerFunctionToString(LayerFunction f) {
    switch (f) {
        case LayerFunction::ExteriorFinish: return "exterior_finish";
        case LayerFunction::Sheathing: return "sheathing";
        case LayerFunction::Insulation: return "insulation";
        case LayerFunction::Structure: return "structure";
        case LayerFunction::InteriorFinish: return "interior_finish";
        case LayerFunction::AirGap: return "air_gap";
        case LayerFunction::Membrane: return "membrane";
        default: return "structure";
    }
}

static LayerFunction stringToLayerFunction(const std::string& s) {
    if (s == "exterior_finish") return LayerFunction::ExteriorFinish;
    if (s == "sheathing") return LayerFunction::Sheathing;
    if (s == "insulation") return LayerFunction::Insulation;
    if (s == "interior_finish") return LayerFunction::InteriorFinish;
    if (s == "air_gap") return LayerFunction::AirGap;
    if (s == "membrane") return LayerFunction::Membrane;
    return LayerFunction::Structure;
}

// LayerFastener serialization
void to_json(json& j, const LayerFastener& f) {
    j["name"] = f.name;
    j["type"] = fastenerTypeToString(f.type);
    j["material"] = f.material;
    j["diameter"] = f.diameter;
    j["length"] = f.length;
    j["field_spacing"] = f.fieldSpacing;
    j["edge_spacing"] = f.edgeSpacing;
    j["code_reference"] = f.codeReference;
    j["shear_capacity"] = f.shearCapacity;
    j["withdrawal_capacity"] = f.withdrawalCapacity;
}

void from_json(const json& j, LayerFastener& f) {
    f.name = j.value("name", "");
    f.type = stringToFastenerType(j.value("type", "nail"));
    f.material = j.value("material", "steel");
    f.diameter = j.value("diameter", 0.131f);
    f.length = j.value("length", 3.0f);
    f.fieldSpacing = j.value("field_spacing", 12.0f);
    f.edgeSpacing = j.value("edge_spacing", 6.0f);
    f.codeReference = j.value("code_reference", "");
    f.shearCapacity = j.value("shear_capacity", 0.0f);
    f.withdrawalCapacity = j.value("withdrawal_capacity", 0.0f);
}

// AssemblyConstraint serialization
void to_json(json& j, const AssemblyConstraint& c) {
    j["type"] = constraintTypeToString(c.type);
    j["name"] = c.name;
    j["value"] = c.value;
    j["code_section"] = c.codeSection;
    j["description"] = c.description;
    j["is_met"] = c.isMet;
}

void from_json(const json& j, AssemblyConstraint& c) {
    c.type = stringToConstraintType(j.value("type", "code_section"));
    c.name = j.value("name", "");
    c.value = j.value("value", "");
    c.codeSection = j.value("code_section", "");
    c.description = j.value("description", "");
    c.isMet = j.value("is_met", false);
}

// IntentBlock serialization
void to_json(json& j, const IntentBlock& i) {
    j["category"] = intentCategoryToString(i.category);
    j["title"] = i.title;
    j["description"] = i.description;
    j["target"] = i.target;
    j["related_codes"] = i.relatedCodes;
    j["validated"] = i.validated;
}

void from_json(const json& j, IntentBlock& i) {
    i.category = stringToIntentCategory(j.value("category", "performance"));
    i.title = j.value("title", "");
    i.description = j.value("description", "");
    i.target = j.value("target", "");
    if (j.contains("related_codes")) {
        for (const auto& code : j["related_codes"]) {
            i.relatedCodes.push_back(code.get<std::string>());
        }
    }
    i.validated = j.value("validated", false);
}

// WallLayer serialization
void to_json(json& j, const WallLayer& l) {
    j["name"] = l.name;
    j["material"] = l.material;
    j["function"] = layerFunctionToString(l.function);
    j["thickness"] = l.thickness;
    j["color"] = {l.color.r, l.color.g, l.color.b};
    j["r_value"] = l.rValue;
    j["fasteners"] = json::array();
    for (const auto& f : l.fasteners) {
        json fj;
        to_json(fj, f);
        j["fasteners"].push_back(fj);
    }
}

void from_json(const json& j, WallLayer& l) {
    l.name = j.value("name", "");
    l.material = j.value("material", "");
    l.function = stringToLayerFunction(j.value("function", "structure"));
    l.thickness = j.value("thickness", 0.0f);
    if (j.contains("color") && j["color"].size() >= 3) {
        l.color = {j["color"][0], j["color"][1], j["color"][2]};
    }
    l.rValue = j.value("r_value", 0.0f);
    l.fasteners.clear();
    if (j.contains("fasteners")) {
        for (const auto& fj : j["fasteners"]) {
            LayerFastener f;
            from_json(fj, f);
            l.fasteners.push_back(f);
        }
    }
}

// WallType serialization
void to_json(json& j, const WallType& w) {
    j["id"] = w.id;
    j["name"] = w.name;

    // Intent block (matches manifesto schema)
    j["intent"] = {
        {"r_value_target", w.intent.rValueTarget},
        {"structural_role", w.intent.structuralRole},
        {"climate_zone", w.intent.climateZone}
    };

    // Layers (recipe)
    j["layers"] = json::array();
    for (const auto& l : w.layers) {
        json lj;
        to_json(lj, l);
        j["layers"].push_back(lj);
    }

    // Constraints
    j["constraints"] = json::array();
    for (const auto& c : w.constraints) {
        json cj;
        to_json(cj, c);
        j["constraints"].push_back(cj);
    }

    // Intents (design rationale)
    j["intents"] = json::array();
    for (const auto& i : w.intents) {
        json ij;
        to_json(ij, i);
        j["intents"].push_back(ij);
    }
}

void from_json(const json& j, WallType& w) {
    w.id = j.value("id", "");
    w.name = j.value("name", "");

    // Intent block
    if (j.contains("intent")) {
        w.intent.rValueTarget = j["intent"].value("r_value_target", 0.0f);
        w.intent.structuralRole = j["intent"].value("structural_role", "");
        w.intent.climateZone = j["intent"].value("climate_zone", "");
    }

    // Layers
    w.layers.clear();
    if (j.contains("layers")) {
        for (const auto& lj : j["layers"]) {
            WallLayer l;
            from_json(lj, l);
            w.layers.push_back(l);
        }
    }

    // Constraints
    w.constraints.clear();
    if (j.contains("constraints")) {
        for (const auto& cj : j["constraints"]) {
            AssemblyConstraint c;
            from_json(cj, c);
            w.constraints.push_back(c);
        }
    }

    // Intents
    w.intents.clear();
    if (j.contains("intents")) {
        for (const auto& ij : j["intents"]) {
            IntentBlock i;
            from_json(ij, i);
            w.intents.push_back(i);
        }
    }
}

// ParametricWall serialization
void to_json(json& j, const ParametricWall& w) {
    j["id"] = w.id;
    j["start_point"] = {w.startPoint.x, w.startPoint.y};
    j["end_point"] = {w.endPoint.x, w.endPoint.y};
    j["base_height"] = w.baseHeight;
    j["top_height"] = w.topHeight;
    j["wall_type_index"] = w.wallTypeIndex;
}

void from_json(const json& j, ParametricWall& w) {
    w.id = j.value("id", "");
    if (j.contains("start_point") && j["start_point"].size() >= 2) {
        w.startPoint = {j["start_point"][0], j["start_point"][1]};
    }
    if (j.contains("end_point") && j["end_point"].size() >= 2) {
        w.endPoint = {j["end_point"][0], j["end_point"][1]};
    }
    w.baseHeight = j.value("base_height", 0.0f);
    w.topHeight = j.value("top_height", 8.0f);
    w.wallTypeIndex = j.value("wall_type_index", 0u);

    // Initialize adjusted points to original
    w.adjustedStart = w.startPoint;
    w.adjustedEnd = w.endPoint;
}

// ============================================================================
// TEST TERRAIN GENERATION
// ============================================================================

TerrainMesh TerrainMesh::generateTestTerrain(f32 width_ft, f32 depth_ft, u32 grid_size,
                                              f32 base_elevation, f32 height_range) {
    TerrainMesh terrain;

    terrain.width_ft = width_ft;
    terrain.depth_ft = depth_ft;

    // Grid spacing
    f32 dx = width_ft / static_cast<f32>(grid_size - 1);
    f32 dz = depth_ft / static_cast<f32>(grid_size - 1);

    // Track min/max elevation
    f32 minElev = base_elevation;
    f32 maxElev = base_elevation;

    // Generate vertices with procedural height
    terrain.vertices.reserve(grid_size * grid_size);

    for (u32 z = 0; z < grid_size; z++) {
        for (u32 x = 0; x < grid_size; x++) {
            // Position in feet
            f32 px = static_cast<f32>(x) * dx - width_ft * 0.5f;  // Center at origin
            f32 pz = static_cast<f32>(z) * dz - depth_ft * 0.5f;

            // Procedural height using multiple sine waves (simple hills)
            f32 nx = px / width_ft;
            f32 nz = pz / depth_ft;

            f32 height = 0.0f;
            // Large hills
            height += std::sin(nx * 3.14159f * 2.0f) * std::cos(nz * 3.14159f * 2.0f) * 0.4f;
            // Medium features
            height += std::sin(nx * 3.14159f * 4.0f + 0.5f) * std::sin(nz * 3.14159f * 3.0f) * 0.25f;
            // Small details
            height += std::sin(nx * 3.14159f * 8.0f) * std::cos(nz * 3.14159f * 7.0f + 1.0f) * 0.15f;

            // Normalize to [0, 1] then scale
            height = (height + 1.0f) * 0.5f;  // Now 0-1
            f32 py = base_elevation + height * height_range;

            minElev = std::min(minElev, py);
            maxElev = std::max(maxElev, py);

            Vertex vert{};
            // Keep in feet (same units as building elements)
            vert.position = vec3(px, py, -pz);  // Flip Z for coordinate system

            // Compute normal (will be refined after all vertices are created)
            vert.normal = vec3(0.0f, 1.0f, 0.0f);

            // UV coordinates - use world-space projection with base scale 0.001
            // This matches building elements and path tracer for consistent texturing
            // Fragment shader will multiply by uvScale to get final UV
            vert.texCoord = vec2(vert.position.x, vert.position.z) * 0.001f;

            // Color will be set after we know the elevation range
            vert.color = vec3(1.0f);

            terrain.vertices.push_back(vert);
        }
    }

    terrain.min_elevation = minElev;
    terrain.max_elevation = maxElev;

    // Now set colors based on actual elevation range
    f32 elevRange = maxElev - minElev;
    if (elevRange < 0.01f) elevRange = 1.0f;

    for (u32 z = 0; z < grid_size; z++) {
        for (u32 x = 0; x < grid_size; x++) {
            u32 idx = z * grid_size + x;
            // Get elevation from Y position (already in feet)
            f32 elev = terrain.vertices[idx].position.y;
            f32 normalizedElev = (elev - minElev) / elevRange;
            terrain.vertices[idx].color = getElevationColor(normalizedElev);
        }
    }

    // Compute proper normals using finite differences
    for (u32 z = 0; z < grid_size; z++) {
        for (u32 x = 0; x < grid_size; x++) {
            u32 idx = z * grid_size + x;

            // Get neighboring heights
            f32 hL = (x > 0) ? terrain.vertices[idx - 1].position.y : terrain.vertices[idx].position.y;
            f32 hR = (x < grid_size - 1) ? terrain.vertices[idx + 1].position.y : terrain.vertices[idx].position.y;
            f32 hD = (z > 0) ? terrain.vertices[idx - grid_size].position.y : terrain.vertices[idx].position.y;
            f32 hU = (z < grid_size - 1) ? terrain.vertices[idx + grid_size].position.y : terrain.vertices[idx].position.y;

            // Compute normal from gradient (all values in feet)
            vec3 normal = glm::normalize(vec3(hL - hR, 2.0f * dx, hD - hU));
            terrain.vertices[idx].normal = normal;
        }
    }

    // Generate indices (two triangles per quad)
    terrain.indices.reserve((grid_size - 1) * (grid_size - 1) * 6);

    for (u32 z = 0; z < grid_size - 1; z++) {
        for (u32 x = 0; x < grid_size - 1; x++) {
            u32 topLeft = z * grid_size + x;
            u32 topRight = topLeft + 1;
            u32 bottomLeft = topLeft + grid_size;
            u32 bottomRight = bottomLeft + 1;

            // Triangle 1 (counter-clockwise for upward-pointing normal)
            terrain.indices.push_back(topLeft);
            terrain.indices.push_back(topRight);
            terrain.indices.push_back(bottomLeft);

            // Triangle 2 (counter-clockwise for upward-pointing normal)
            terrain.indices.push_back(topRight);
            terrain.indices.push_back(bottomRight);
            terrain.indices.push_back(bottomLeft);
        }
    }

    std::cout << "[Terrain] Generated test terrain: " << terrain.vertices.size()
              << " vertices, " << (terrain.indices.size() / 3) << " triangles, "
              << width_ft << "x" << depth_ft << " ft, elevation " << minElev
              << "-" << maxElev << " ft\n";

    return terrain;
}

} // namespace arch
