#pragma once

#include "types.hpp"
#include <cmath>

namespace arch {

// Default wall types
inline WallType createExterior2x6Wall() {
    WallType type;
    type.name = "2x6 Exterior Wall";
    type.layers = {
        {"Siding",      "wood",       LayerFunction::ExteriorFinish, 0.0625f, {0.6f, 0.5f, 0.4f}, 0.8f},
        {"House Wrap",  "membrane",   LayerFunction::Membrane,       0.005f,  {0.9f, 0.9f, 0.9f}, 0.0f},
        {"Sheathing",   "osb",        LayerFunction::Sheathing,      0.0417f, {0.8f, 0.7f, 0.5f}, 0.6f},
        {"Insulation",  "fiberglass", LayerFunction::Insulation,     0.458f,  {0.95f, 0.8f, 0.9f}, 19.0f},
        {"2x6 Stud",    "wood",       LayerFunction::Structure,      0.458f,  {0.9f, 0.8f, 0.6f}, 6.9f},
        {"Drywall",     "gypsum",     LayerFunction::InteriorFinish, 0.0417f, {0.95f, 0.95f, 0.92f}, 0.5f}
    };
    return type;
}

inline WallType createExterior2x4Wall() {
    WallType type;
    type.name = "2x4 Exterior Wall";
    type.layers = {
        {"Siding",      "wood",       LayerFunction::ExteriorFinish, 0.0625f, {0.6f, 0.5f, 0.4f}, 0.8f},
        {"House Wrap",  "membrane",   LayerFunction::Membrane,       0.005f,  {0.9f, 0.9f, 0.9f}, 0.0f},
        {"Sheathing",   "osb",        LayerFunction::Sheathing,      0.0417f, {0.8f, 0.7f, 0.5f}, 0.6f},
        {"Insulation",  "fiberglass", LayerFunction::Insulation,     0.292f,  {0.95f, 0.8f, 0.9f}, 13.0f},
        {"2x4 Stud",    "wood",       LayerFunction::Structure,      0.292f,  {0.9f, 0.8f, 0.6f}, 4.4f},
        {"Drywall",     "gypsum",     LayerFunction::InteriorFinish, 0.0417f, {0.95f, 0.95f, 0.92f}, 0.5f}
    };
    return type;
}

inline WallType createInteriorWall() {
    WallType type;
    type.name = "Interior Partition";
    type.layers = {
        {"Drywall",     "gypsum",     LayerFunction::InteriorFinish, 0.0417f, {0.95f, 0.95f, 0.92f}, 0.5f},
        {"2x4 Stud",    "wood",       LayerFunction::Structure,      0.292f,  {0.9f, 0.8f, 0.6f}, 4.4f},
        {"Drywall",     "gypsum",     LayerFunction::InteriorFinish, 0.0417f, {0.95f, 0.95f, 0.92f}, 0.5f}
    };
    return type;
}

class WallSystem {
public:
    // Generate layer meshes for a single wall
    static void generateWallGeometry(ParametricWall& wall, const WallType& type);

    // Detect corners between walls (endpoints within tolerance)
    static std::vector<WallCorner> detectCorners(
        const std::vector<ParametricWall>& walls,
        f32 tolerance = 0.1f
    );

    // Process corners - adjust wall endpoints for proper layer connections
    static void processCorners(
        std::vector<ParametricWall>& walls,
        const std::vector<WallType>& types,
        const std::vector<WallCorner>& corners
    );

    // Generate layer mesh with corner adjustments
    static MeshData generateLayerMesh(
        const ParametricWall& wall,
        const WallLayer& layer,
        f32 layerOffset,  // Distance from centerline to exterior face of this layer
        f32 layerThickness
    );

    // Convert parametric walls to StructuralElements for rendering
    static std::vector<StructuralElement> toStructuralElements(
        const std::vector<ParametricWall>& walls,
        const std::vector<WallType>& types
    );

private:
    // Line-line intersection helper
    static bool lineIntersection(
        vec2 p1, vec2 p2,  // Line 1
        vec2 p3, vec2 p4,  // Line 2
        vec2& intersection
    );

    // Extend/trim layer at corner
    static void adjustLayerAtCorner(
        vec2& point,
        const vec2& direction,
        const vec2& otherWallDirection,
        f32 thisLayerOffset,
        f32 otherLayerOffset,
        CornerType cornerType
    );
};

// Implementation
inline void WallSystem::generateWallGeometry(ParametricWall& wall, const WallType& type) {
    wall.layerMeshes.clear();

    // Calculate total thickness
    f32 totalThickness = 0.0f;
    for (const auto& layer : type.layers) {
        // Insulation shares space with structure, don't double count
        if (layer.function != LayerFunction::Insulation) {
            totalThickness += layer.thickness;
        }
    }

    f32 currentOffset = -totalThickness / 2.0f;  // Start from exterior side

    for (const auto& layer : type.layers) {
        // Skip insulation (shares space with structure)
        if (layer.function == LayerFunction::Insulation) {
            continue;
        }

        MeshData mesh = generateLayerMesh(wall, layer, currentOffset, layer.thickness);
        wall.layerMeshes.push_back(mesh);
        currentOffset += layer.thickness;
    }
}

inline MeshData WallSystem::generateLayerMesh(
    const ParametricWall& wall,
    const WallLayer& layer,
    f32 layerOffset,
    f32 layerThickness
) {
    (void)layer;  // Layer info used for color in future
    MeshData mesh;

    vec2 start = (wall.adjustedStart.x != 0 || wall.adjustedStart.y != 0) ?
                 wall.adjustedStart : wall.startPoint;
    vec2 end = (wall.adjustedEnd.x != 0 || wall.adjustedEnd.y != 0) ?
               wall.adjustedEnd : wall.endPoint;

    vec2 dir = end - start;
    f32 length = std::sqrt(dir.x * dir.x + dir.y * dir.y);
    if (length < 0.001f) return mesh;

    dir = dir / length;
    vec2 normal(-dir.y, dir.x);  // Perpendicular (points left of direction)

    // Layer extents from centerline (negative = exterior, positive = interior)
    vec2 ext1 = start + normal * layerOffset;
    vec2 ext2 = end + normal * layerOffset;
    vec2 int1 = start + normal * (layerOffset + layerThickness);
    vec2 int2 = end + normal * (layerOffset + layerThickness);

    f32 base = wall.baseHeight;
    f32 top = wall.topHeight;

    // Create a box with 8 vertices
    // Bottom face (Y = base): 0-3
    // Top face (Y = top): 4-7
    //
    // Looking down (Y up):
    //   ext1---ext2   (exterior)
    //    |      |
    //   int1---int2   (interior)

    // Bottom vertices
    mesh.vertices.push_back(vec3(ext1.x, base, ext1.y));  // 0 - exterior start bottom
    mesh.vertices.push_back(vec3(ext2.x, base, ext2.y));  // 1 - exterior end bottom
    mesh.vertices.push_back(vec3(int2.x, base, int2.y));  // 2 - interior end bottom
    mesh.vertices.push_back(vec3(int1.x, base, int1.y));  // 3 - interior start bottom

    // Top vertices
    mesh.vertices.push_back(vec3(ext1.x, top, ext1.y));   // 4 - exterior start top
    mesh.vertices.push_back(vec3(ext2.x, top, ext2.y));   // 5 - exterior end top
    mesh.vertices.push_back(vec3(int2.x, top, int2.y));   // 6 - interior end top
    mesh.vertices.push_back(vec3(int1.x, top, int1.y));   // 7 - interior start top

    // All faces with BOTH winding orders to render from both sides
    // Exterior face (looking from outside toward interior)
    mesh.faces.push_back({0, 4, 5}); mesh.faces.push_back({0, 5, 4});
    mesh.faces.push_back({0, 5, 1}); mesh.faces.push_back({0, 1, 5});

    // Interior face (looking from inside toward exterior)
    mesh.faces.push_back({3, 2, 6}); mesh.faces.push_back({3, 6, 2});
    mesh.faces.push_back({3, 6, 7}); mesh.faces.push_back({3, 7, 6});

    // Start cap (at start point)
    mesh.faces.push_back({0, 3, 7}); mesh.faces.push_back({0, 7, 3});
    mesh.faces.push_back({0, 7, 4}); mesh.faces.push_back({0, 4, 7});

    // End cap (at end point)
    mesh.faces.push_back({1, 5, 6}); mesh.faces.push_back({1, 6, 5});
    mesh.faces.push_back({1, 6, 2}); mesh.faces.push_back({1, 2, 6});

    // Bottom face
    mesh.faces.push_back({0, 1, 2}); mesh.faces.push_back({0, 2, 1});
    mesh.faces.push_back({0, 2, 3}); mesh.faces.push_back({0, 3, 2});

    // Top face
    mesh.faces.push_back({4, 7, 6}); mesh.faces.push_back({4, 6, 7});
    mesh.faces.push_back({4, 6, 5}); mesh.faces.push_back({4, 5, 6});

    return mesh;
}

inline std::vector<WallCorner> WallSystem::detectCorners(
    const std::vector<ParametricWall>& walls,
    f32 tolerance
) {
    std::vector<WallCorner> corners;

    for (u32 i = 0; i < walls.size(); i++) {
        for (u32 j = i + 1; j < walls.size(); j++) {
            const auto& w1 = walls[i];
            const auto& w2 = walls[j];

            // Check all endpoint combinations
            vec2 endpoints1[2] = {w1.startPoint, w1.endPoint};
            vec2 endpoints2[2] = {w2.startPoint, w2.endPoint};

            for (int e1 = 0; e1 < 2; e1++) {
                for (int e2 = 0; e2 < 2; e2++) {
                    vec2 diff = endpoints1[e1] - endpoints2[e2];
                    f32 dist = std::sqrt(diff.x * diff.x + diff.y * diff.y);

                    if (dist < tolerance) {
                        WallCorner corner;
                        corner.wall1Index = i;
                        corner.wall2Index = j;
                        corner.location = (endpoints1[e1] + endpoints2[e2]) * 0.5f;
                        corner.isStart1 = (e1 == 0);
                        corner.isStart2 = (e2 == 0);

                        // Determine corner type based on angle
                        vec2 dir1 = w1.getDirection();
                        vec2 dir2 = w2.getDirection();
                        if (!corner.isStart1) dir1 = -dir1;
                        if (!corner.isStart2) dir2 = -dir2;

                        f32 dot = dir1.x * dir2.x + dir1.y * dir2.y;
                        if (std::abs(dot) < 0.1f) {
                            corner.type = CornerType::LCorner;  // ~90 degrees
                        } else if (dot < -0.7f) {
                            corner.type = CornerType::Butt;     // ~180 degrees (continuation)
                        } else {
                            corner.type = CornerType::Miter;    // Other angles
                        }

                        corners.push_back(corner);
                    }
                }
            }
        }
    }

    return corners;
}

inline void WallSystem::processCorners(
    std::vector<ParametricWall>& walls,
    const std::vector<WallType>& types,
    const std::vector<WallCorner>& corners
) {
    // Initialize adjusted points to original points
    for (auto& wall : walls) {
        wall.adjustedStart = wall.startPoint;
        wall.adjustedEnd = wall.endPoint;
    }

    for (const auto& corner : corners) {
        auto& w1 = walls[corner.wall1Index];
        auto& w2 = walls[corner.wall2Index];
        const auto& type1 = types[w1.wallTypeIndex];
        const auto& type2 = types[w2.wallTypeIndex];

        f32 halfThick1 = type1.getTotalThickness() / 2.0f;
        f32 halfThick2 = type2.getTotalThickness() / 2.0f;

        vec2 dir1 = w1.getDirection();
        vec2 dir2 = w2.getDirection();
        vec2 norm1 = w1.getNormal();
        vec2 norm2 = w2.getNormal();

        if (corner.type == CornerType::LCorner) {
            // For L-corners, extend walls to meet at outer corners
            // Wall 1 extends/trims
            if (corner.isStart1) {
                w1.adjustedStart = corner.location - dir1 * halfThick2;
            } else {
                w1.adjustedEnd = corner.location + dir1 * halfThick2;
            }

            // Wall 2 extends/trims
            if (corner.isStart2) {
                w2.adjustedStart = corner.location - dir2 * halfThick1;
            } else {
                w2.adjustedEnd = corner.location + dir2 * halfThick1;
            }
        }
    }

    // Regenerate geometry with adjusted endpoints
    for (size_t i = 0; i < walls.size(); i++) {
        generateWallGeometry(walls[i], types[walls[i].wallTypeIndex]);
    }
}

inline std::vector<StructuralElement> WallSystem::toStructuralElements(
    const std::vector<ParametricWall>& walls,
    const std::vector<WallType>& types
) {
    std::vector<StructuralElement> elements;

    for (const auto& wall : walls) {
        if (wall.wallTypeIndex >= types.size()) continue;
        const auto& type = types[wall.wallTypeIndex];

        // Create one element per layer mesh
        for (size_t meshIdx = 0; meshIdx < wall.layerMeshes.size(); meshIdx++) {
            StructuralElement elem;
            elem.type = ElementType::Wall;
            elem.material = "composite";
            elem.width = type.getTotalThickness();
            elem.depth = type.getTotalThickness();
            elem.stress = 0.0f;
            elem.deflection = 0.0f;
            elem.failed = false;
            elem.mesh = wall.layerMeshes[meshIdx];

            // Set bounding box for selection
            vec2 start = (wall.adjustedStart.x != 0 || wall.adjustedStart.y != 0) ?
                         wall.adjustedStart : wall.startPoint;
            vec2 end = (wall.adjustedEnd.x != 0 || wall.adjustedEnd.y != 0) ?
                       wall.adjustedEnd : wall.endPoint;

            elem.start = vec3(std::min(start.x, end.x), wall.baseHeight, std::min(start.y, end.y));
            elem.end = vec3(std::max(start.x, end.x), wall.topHeight, std::max(start.y, end.y));

            elements.push_back(elem);
        }
    }

    return elements;
}

inline bool WallSystem::lineIntersection(vec2 p1, vec2 p2, vec2 p3, vec2 p4, vec2& intersection) {
    vec2 d1 = p2 - p1;
    vec2 d2 = p4 - p3;

    f32 cross = d1.x * d2.y - d1.y * d2.x;
    if (std::abs(cross) < 0.0001f) return false;  // Parallel

    vec2 d3 = p3 - p1;
    f32 t = (d3.x * d2.y - d3.y * d2.x) / cross;

    intersection = p1 + d1 * t;
    return true;
}

} // namespace arch
