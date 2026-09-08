#pragma once

#include "types.hpp"
#include "renderer.hpp"
#include <nlohmann/json.hpp>
#include <fstream>

namespace arch {

using json = nlohmann::json;

class GeometryLoader {
public:
    // Load building from JSON file
    static Building loadFromJSON(const std::string& filepath);

    // Save building to JSON file
    static void saveToJSON(const std::string& filepath, const Building& building);

    // Save building with material overrides
    static void saveToJSON(const std::string& filepath, const Building& building, const Renderer& renderer);

    // Create sample buildings for testing
    static Building createSimpleFrame(f32 width = 40.0f, f32 depth = 30.0f, f32 height = 12.0f);
    static Building createMultiStoryFrame(int stories = 3, f32 width = 60.0f, f32 depth = 40.0f, f32 storyHeight = 12.0f);
    static Building createWarehouse(f32 width = 100.0f, f32 depth = 80.0f, f32 height = 30.0f);
    static Building createResidential(f32 width = 40.0f, f32 depth = 30.0f, int stories = 2);

    // Load from IFC (simplified - just extracts basic geometry)
    static Building loadFromIFC(const std::string& filepath);

    // Load element material overrides from JSON file and apply to renderer
    static void loadMaterialOverrides(const std::string& filepath, Renderer& renderer);

private:
    static void addColumn(Building& building, vec3 position, f32 width, f32 depth, f32 height,
                         const std::string& material = "steel", f32 stress = 0.0f);
    static void addBeam(Building& building, vec3 start, vec3 end, f32 width, f32 depth,
                       const std::string& material = "steel", f32 stress = 0.0f, f32 deflection = 0.0f);
    static void addFloor(Building& building, vec3 position, f32 width, f32 depth, f32 thickness,
                        const std::string& material = "concrete");
    static void addWall(Building& building, vec3 start, vec3 end, f32 height, f32 thickness,
                       const std::string& material = "concrete");
    static void addDoor(Building& building, vec3 position, f32 width, f32 height, f32 depth,
                        const std::string& material = "door");
    static void addWindow(Building& building, vec3 position, f32 width, f32 height, f32 depth,
                          const std::string& material = "glass");
    static void addRoof(Building& building, vec3 position, f32 width, f32 depth, f32 thickness,
                        const std::string& material = "roof");
};

// JSON serialization - Core types
void to_json(json& j, const Building& b);
void from_json(const json& j, Building& b);

// JSON serialization - Assembly recipe types
void to_json(json& j, const LayerFastener& f);
void from_json(const json& j, LayerFastener& f);

void to_json(json& j, const AssemblyConstraint& c);
void from_json(const json& j, AssemblyConstraint& c);

void to_json(json& j, const IntentBlock& i);
void from_json(const json& j, IntentBlock& i);

void to_json(json& j, const WallLayer& l);
void from_json(const json& j, WallLayer& l);

void to_json(json& j, const WallType& w);
void from_json(const json& j, WallType& w);

void to_json(json& j, const ParametricWall& w);
void from_json(const json& j, ParametricWall& w);

} // namespace arch
