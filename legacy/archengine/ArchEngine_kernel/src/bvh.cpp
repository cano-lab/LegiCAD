/**
 * @file bvh.cpp
 * @brief SAH-based BVH construction for GPU path tracing
 */

#include "bvh.hpp"
#include <algorithm>
#include <numeric>
#include <iostream>
#include <cmath>
#include <fstream>
#include <filesystem>
#include <unordered_map>

// JSON parsing
#include <nlohmann/json.hpp>
using json = nlohmann::json;

namespace arch {

// ============================================================================
// BVHBuilder Implementation
// ============================================================================

BVHBuilder::BVHBuilder(const Config& config)
    : m_config(config)
{
}

BVHBuilder::~BVHBuilder() {
    if (m_root) {
        deleteBuildTree(m_root);
        m_root = nullptr;
    }
}

void BVHBuilder::deleteBuildTree(BVHBuildNode* node) {
    if (!node) return;
    if (node->children[0]) deleteBuildTree(node->children[0]);
    if (node->children[1]) deleteBuildTree(node->children[1]);
    delete node;
}

bool BVHBuilder::build(const std::vector<GPUTriangle>& triangles) {
    if (triangles.empty()) {
        std::cerr << "[BVH] No triangles to build BVH from\n";
        return false;
    }

    // Clean up previous build
    if (m_root) {
        deleteBuildTree(m_root);
        m_root = nullptr;
    }
    m_nodes.clear();
    m_orderedPrimIndices.clear();
    m_treeDepth = 0;
    m_leafCount = 0;

    // Create primitive info for each triangle
    std::vector<BVHPrimitive> primitives;
    primitives.reserve(triangles.size());

    for (u32 i = 0; i < triangles.size(); ++i) {
        BVHPrimitive prim;
        prim.index = i;
        prim.bounds = triangles[i].getBounds();
        prim.centroid = triangles[i].getCentroid();
        primitives.push_back(prim);
    }

    // Build tree recursively
    u32 totalNodes = 0;
    std::vector<u32> orderedPrims;
    orderedPrims.reserve(triangles.size());

    m_root = buildRecursive(primitives, totalNodes, orderedPrims);

    // Flatten tree to array
    m_nodes.resize(totalNodes);
    m_orderedPrimIndices = std::move(orderedPrims);

    u32 offset = 0;
    flattenBVH(m_root, &offset);

    std::cout << "[BVH] Built with " << totalNodes << " nodes, "
              << m_leafCount << " leaves, depth " << m_treeDepth
              << " from " << triangles.size() << " triangles\n";

    return true;
}

BVHBuildNode* BVHBuilder::buildRecursive(
    std::span<BVHPrimitive> prims,
    u32& totalNodes,
    std::vector<u32>& orderedPrims)
{
    BVHBuildNode* node = new BVHBuildNode();
    totalNodes++;

    // Compute bounds of all primitives
    AABB bounds;
    for (const auto& prim : prims) {
        bounds.expand(prim.bounds);
    }
    node->bounds = bounds;

    u32 numPrims = static_cast<u32>(prims.size());

    // Create leaf if few primitives
    if (numPrims <= m_config.maxPrimsInNode) {
        node->firstPrimOffset = static_cast<u32>(orderedPrims.size());
        node->primCount = numPrims;
        for (const auto& prim : prims) {
            orderedPrims.push_back(prim.index);
        }
        m_leafCount++;
        return node;
    }

    // Compute centroid bounds for partitioning
    AABB centroidBounds;
    for (const auto& prim : prims) {
        centroidBounds.expand(prim.centroid);
    }

    // Choose split axis (longest extent of centroid bounds)
    u32 axis = centroidBounds.longestAxis();

    // If centroids are coincident, create leaf
    if (centroidBounds.max[axis] == centroidBounds.min[axis]) {
        node->firstPrimOffset = static_cast<u32>(orderedPrims.size());
        node->primCount = numPrims;
        for (const auto& prim : prims) {
            orderedPrims.push_back(prim.index);
        }
        m_leafCount++;
        return node;
    }

    // SAH partitioning
    constexpr u32 nBuckets = 12;
    std::vector<SAHBucket> buckets(nBuckets);

    // Assign primitives to buckets
    for (const auto& prim : prims) {
        f32 centroid = prim.centroid[axis];
        f32 offset = (centroid - centroidBounds.min[axis]) /
                     (centroidBounds.max[axis] - centroidBounds.min[axis]);
        u32 b = static_cast<u32>(nBuckets * offset);
        if (b >= nBuckets) b = nBuckets - 1;
        buckets[b].count++;
        buckets[b].bounds.expand(prim.bounds);
    }

    // Compute costs for splitting after each bucket
    std::vector<f32> costs(nBuckets - 1);
    f32 boundsArea = bounds.surfaceArea();

    for (u32 i = 0; i < nBuckets - 1; ++i) {
        AABB b0, b1;
        u32 count0 = 0, count1 = 0;

        for (u32 j = 0; j <= i; ++j) {
            b0.expand(buckets[j].bounds);
            count0 += buckets[j].count;
        }
        for (u32 j = i + 1; j < nBuckets; ++j) {
            b1.expand(buckets[j].bounds);
            count1 += buckets[j].count;
        }

        f32 area0 = b0.isValid() ? b0.surfaceArea() : 0.0f;
        f32 area1 = b1.isValid() ? b1.surfaceArea() : 0.0f;

        costs[i] = m_config.traversalCost +
                   (count0 * area0 + count1 * area1) / boundsArea * m_config.intersectCost;
    }

    // Find best split
    f32 minCost = costs[0];
    u32 minCostSplit = 0;
    for (u32 i = 1; i < nBuckets - 1; ++i) {
        if (costs[i] < minCost) {
            minCost = costs[i];
            minCostSplit = i;
        }
    }

    // Compare with cost of not splitting (leaf)
    f32 leafCost = m_config.intersectCost * numPrims;

    // Create leaf or split
    if (numPrims > m_config.maxPrimsInNode || minCost < leafCost) {
        // Partition primitives
        auto midIter = std::partition(
            prims.begin(), prims.end(),
            [&](const BVHPrimitive& prim) {
                f32 centroid = prim.centroid[axis];
                f32 offset = (centroid - centroidBounds.min[axis]) /
                             (centroidBounds.max[axis] - centroidBounds.min[axis]);
                u32 b = static_cast<u32>(nBuckets * offset);
                if (b >= nBuckets) b = nBuckets - 1;
                return b <= minCostSplit;
            }
        );

        size_t mid = std::distance(prims.begin(), midIter);

        // Handle edge case where partition failed
        if (mid == 0 || mid == prims.size()) {
            mid = prims.size() / 2;
            std::nth_element(
                prims.begin(), prims.begin() + mid, prims.end(),
                [axis](const BVHPrimitive& a, const BVHPrimitive& b) {
                    return a.centroid[axis] < b.centroid[axis];
                }
            );
        }

        node->splitAxis = axis;
        node->children[0] = buildRecursive(
            prims.subspan(0, mid), totalNodes, orderedPrims);
        node->children[1] = buildRecursive(
            prims.subspan(mid), totalNodes, orderedPrims);
    } else {
        // Create leaf
        node->firstPrimOffset = static_cast<u32>(orderedPrims.size());
        node->primCount = numPrims;
        for (const auto& prim : prims) {
            orderedPrims.push_back(prim.index);
        }
        m_leafCount++;
    }

    return node;
}

u32 BVHBuilder::flattenBVH(BVHBuildNode* node, u32* offset) {
    GPUBVHNode& linearNode = m_nodes[*offset];
    u32 myOffset = (*offset)++;

    if (node->isLeaf()) {
        linearNode.setLeafNode(node->bounds, node->firstPrimOffset, node->primCount);
    } else {
        // Internal node - recurse
        flattenBVH(node->children[0], offset);
        u32 rightChildOffset = flattenBVH(node->children[1], offset);
        linearNode.setInternalNode(node->bounds, myOffset + 1, rightChildOffset);
    }

    // Track depth
    static u32 currentDepth = 0;
    currentDepth++;
    if (currentDepth > m_treeDepth) m_treeDepth = currentDepth;
    currentDepth--;

    return myOffset;
}

// ============================================================================
// Scene BVH Building Helper
// ============================================================================

// Debug counters
static int g_customMeshCount = 0;
static int g_fallbackCount = 0;

/**
 * @brief Generate mesh triangles from a structural element
 */
static void generateElementTriangles(
    const StructuralElement& elem,
    u32 materialIndex,
    std::vector<GPUTriangle>& triangles)
{
    // If element has custom mesh, use that
    if (elem.mesh.hasData()) {
        const auto& vertices = elem.mesh.vertices;
        const auto& faces = elem.mesh.faces;

        g_customMeshCount++;
        std::cout << "[BVH] Custom mesh for " << static_cast<int>(elem.type)
                  << " with " << vertices.size() << " verts, " << faces.size() << " faces\n";

        for (const auto& face : faces) {
            if (face[0] < vertices.size() && face[1] < vertices.size() && face[2] < vertices.size()) {
                GPUTriangle tri;
                tri.set(vertices[face[0]], vertices[face[1]], vertices[face[2]], materialIndex);
                triangles.push_back(tri);
            }
        }
        return;
    }

    g_fallbackCount++;

    // Generate procedural geometry based on element type
    vec3 start = elem.start;
    vec3 end = elem.end;
    f32 w = elem.width;
    f32 d = elem.depth;

    switch (elem.type) {
        case ElementType::Beam: {
            // Simple box beam
            vec3 dir = end - start;
            f32 len = glm::length(dir);
            if (len < 0.001f) return;
            dir /= len;

            vec3 up(0, 1, 0);
            if (std::abs(glm::dot(dir, up)) > 0.99f) {
                up = vec3(1, 0, 0);
            }
            vec3 right = glm::normalize(glm::cross(dir, up));
            vec3 localUp = glm::cross(right, dir);

            vec3 hw = right * (w * 0.5f);
            vec3 hd = localUp * (d * 0.5f);

            // 8 corners
            vec3 corners[8] = {
                start - hw - hd, start + hw - hd, start + hw + hd, start - hw + hd,
                end - hw - hd, end + hw - hd, end + hw + hd, end - hw + hd
            };

            // 6 faces, 2 triangles each
            auto addQuad = [&](int a, int b, int c, int d) {
                GPUTriangle t1, t2;
                t1.set(corners[a], corners[b], corners[c], materialIndex);
                t2.set(corners[a], corners[c], corners[d], materialIndex);
                triangles.push_back(t1);
                triangles.push_back(t2);
            };

            addQuad(0, 1, 2, 3);  // Start face
            addQuad(5, 4, 7, 6);  // End face
            addQuad(0, 4, 5, 1);  // Bottom
            addQuad(2, 6, 7, 3);  // Top
            addQuad(1, 5, 6, 2);  // Right
            addQuad(4, 0, 3, 7);  // Left
            break;
        }

        case ElementType::Column: {
            // Vertical box
            vec3 base = start;
            f32 height = end.y - start.y;
            if (height < 0.001f) height = 1.0f;

            vec3 hw(w * 0.5f, 0, 0);
            vec3 hd(0, 0, d * 0.5f);
            vec3 h(0, height, 0);

            vec3 corners[8] = {
                base - hw - hd, base + hw - hd, base + hw + hd, base - hw + hd,
                base - hw - hd + h, base + hw - hd + h, base + hw + hd + h, base - hw + hd + h
            };

            auto addQuad = [&](int a, int b, int c, int d) {
                GPUTriangle t1, t2;
                t1.set(corners[a], corners[b], corners[c], materialIndex);
                t2.set(corners[a], corners[c], corners[d], materialIndex);
                triangles.push_back(t1);
                triangles.push_back(t2);
            };

            addQuad(0, 1, 2, 3);  // Bottom
            addQuad(5, 4, 7, 6);  // Top
            addQuad(0, 4, 5, 1);  // Front
            addQuad(2, 6, 7, 3);  // Back
            addQuad(1, 5, 6, 2);  // Right
            addQuad(4, 0, 3, 7);  // Left
            break;
        }

        case ElementType::Floor:
        case ElementType::Roof: {
            // Use custom mesh if available (QBD/IFC have proper geometry)
            if (elem.mesh.hasData()) {
                const auto& verts = elem.mesh.vertices;
                const auto& faces = elem.mesh.faces;
                for (const auto& face : faces) {
                    if (face[0] < verts.size() && face[1] < verts.size() && face[2] < verts.size()) {
                        GPUTriangle t;
                        t.set(verts[face[0]], verts[face[1]], verts[face[2]], materialIndex);
                        triangles.push_back(t);
                    }
                }
                break;
            }

            // Fallback: Simple thin slab matching real-time renderer logic
            f32 slabWidth = end.x - start.x;
            f32 slabDepth = end.z - start.z;

            // For both floors and roofs: use end.y - start.y as thickness
            // This matches the real-time renderer behavior
            f32 thickness = end.y - start.y;
            if (std::abs(thickness) < 0.01f) {
                thickness = 0.3f;  // Default thin slab if no vertical extent
            }

            std::cout << "[BVH] " << (elem.type == ElementType::Floor ? "Floor" : "Roof")
                      << " fallback: start=(" << start.x << "," << start.y << "," << start.z
                      << ") end=(" << end.x << "," << end.y << "," << end.z
                      << ") w=" << slabWidth << " d=" << slabDepth << " t=" << thickness << "\n";

            // Skip invalid slabs
            if (std::abs(slabWidth) < 0.01f || std::abs(slabDepth) < 0.01f) {
                std::cout << "[BVH] Skipping invalid slab (width or depth near zero)\n";
                break;
            }

            // Create slab at start position extending to end
            vec3 corners[8] = {
                vec3(start.x, start.y, start.z),
                vec3(end.x, start.y, start.z),
                vec3(end.x, start.y, end.z),
                vec3(start.x, start.y, end.z),
                vec3(start.x, start.y + thickness, start.z),
                vec3(end.x, start.y + thickness, start.z),
                vec3(end.x, start.y + thickness, end.z),
                vec3(start.x, start.y + thickness, end.z)
            };

            auto addQuad = [&](int a, int b, int c, int d) {
                GPUTriangle t1, t2;
                t1.set(corners[a], corners[b], corners[c], materialIndex);
                t2.set(corners[a], corners[c], corners[d], materialIndex);
                triangles.push_back(t1);
                triangles.push_back(t2);
            };

            addQuad(0, 3, 2, 1);  // Bottom (normal down)
            addQuad(4, 7, 6, 5);  // Top (normal up - reversed winding for correct lighting)
            addQuad(0, 1, 5, 4);  // Front
            addQuad(2, 3, 7, 6);  // Back
            addQuad(1, 2, 6, 5);  // Right
            addQuad(3, 0, 4, 7);  // Left
            break;
        }

        case ElementType::Wall: {
            // Use custom mesh if available (e.g., gable walls)
            if (elem.mesh.hasData()) {
                const auto& verts = elem.mesh.vertices;
                const auto& faces = elem.mesh.faces;
                for (const auto& face : faces) {
                    if (face[0] < verts.size() && face[1] < verts.size() && face[2] < verts.size()) {
                        GPUTriangle t;
                        t.set(verts[face[0]], verts[face[1]], verts[face[2]], materialIndex);
                        triangles.push_back(t);
                    }
                }
                break;
            }

            // Fallback: Vertical wall slab
            vec3 wallDir = end - start;
            f32 wallLen = glm::length(vec2(wallDir.x, wallDir.z));
            if (wallLen < 0.001f) return;

            vec3 wallDirNorm = glm::normalize(vec3(wallDir.x, 0, wallDir.z));
            vec3 perpDir(-wallDirNorm.z, 0, wallDirNorm.x);

            f32 height = end.y - start.y;
            if (height < 0.001f) height = start.y > 0 ? start.y : 8.0f;

            vec3 hw = perpDir * (w * 0.5f);

            vec3 corners[8] = {
                start - hw, start + hw,
                end + hw, end - hw,
                start - hw + vec3(0, height, 0), start + hw + vec3(0, height, 0),
                end + hw + vec3(0, height, 0), end - hw + vec3(0, height, 0)
            };

            auto addQuad = [&](int a, int b, int c, int d) {
                GPUTriangle t1, t2;
                t1.set(corners[a], corners[b], corners[c], materialIndex);
                t2.set(corners[a], corners[c], corners[d], materialIndex);
                triangles.push_back(t1);
                triangles.push_back(t2);
            };

            addQuad(0, 1, 2, 3);  // Bottom
            addQuad(5, 4, 7, 6);  // Top
            addQuad(0, 4, 5, 1);  // Front
            addQuad(3, 7, 6, 2);  // Back
            addQuad(1, 5, 6, 2);  // Right (end)
            addQuad(4, 0, 3, 7);  // Left (start)
            break;
        }

        case ElementType::Window: {
            // Window: simple flat quad (glass pane)
            f32 width = w > 0.01f ? w : 1.0f;
            f32 height = end.y - start.y;
            if (height < 0.01f) height = 1.5f;

            // Window is oriented based on start/end direction
            vec3 dir = end - start;
            f32 len = glm::length(vec2(dir.x, dir.z));
            if (len < 0.001f) {
                // Vertical window, face along X
                vec3 corners[4] = {
                    start,
                    start + vec3(width, 0, 0),
                    start + vec3(width, height, 0),
                    start + vec3(0, height, 0)
                };
                GPUTriangle t1, t2;
                t1.set(corners[0], corners[1], corners[2], materialIndex);
                t2.set(corners[0], corners[2], corners[3], materialIndex);
                triangles.push_back(t1);
                triangles.push_back(t2);
            } else {
                // Oriented window - window should be parallel to wall (not perpendicular)
                // Wall goes from start to end, window should face perpendicular to that
                vec3 dirNorm = glm::normalize(vec3(dir.x, 0, dir.z));
                // Window width runs ALONG the wall direction
                vec3 along = dirNorm * (width * 0.5f);
                vec3 up(0, height, 0);

                vec3 center = (start + end) * 0.5f;
                center.y = start.y;

                vec3 corners[4] = {
                    center - along,
                    center + along,
                    center + along + up,
                    center - along + up
                };
                GPUTriangle t1, t2;
                t1.set(corners[0], corners[1], corners[2], materialIndex);
                t2.set(corners[0], corners[2], corners[3], materialIndex);
                triangles.push_back(t1);
                triangles.push_back(t2);
            }
            break;
        }

        case ElementType::Door: {
            // Door: thin box like a wall
            f32 doorWidth = w > 0.01f ? w : 0.9f;
            f32 doorHeight = end.y - start.y;
            if (doorHeight < 0.01f) doorHeight = 2.1f;
            f32 doorThickness = d > 0.01f ? d : 0.05f;

            vec3 dir = end - start;
            f32 len = glm::length(vec2(dir.x, dir.z));

            vec3 dirNorm = len > 0.001f ? glm::normalize(vec3(dir.x, 0, dir.z)) : vec3(1, 0, 0);
            vec3 perpDir(-dirNorm.z, 0, dirNorm.x);

            vec3 hw = perpDir * (doorThickness * 0.5f);
            vec3 center = (start + end) * 0.5f;
            center.y = start.y;

            vec3 corners[8] = {
                center - hw - dirNorm * (doorWidth * 0.5f),
                center - hw + dirNorm * (doorWidth * 0.5f),
                center + hw + dirNorm * (doorWidth * 0.5f),
                center + hw - dirNorm * (doorWidth * 0.5f),
                center - hw - dirNorm * (doorWidth * 0.5f) + vec3(0, doorHeight, 0),
                center - hw + dirNorm * (doorWidth * 0.5f) + vec3(0, doorHeight, 0),
                center + hw + dirNorm * (doorWidth * 0.5f) + vec3(0, doorHeight, 0),
                center + hw - dirNorm * (doorWidth * 0.5f) + vec3(0, doorHeight, 0)
            };

            auto addQuad = [&](int a, int b, int c, int d) {
                GPUTriangle t1, t2;
                t1.set(corners[a], corners[b], corners[c], materialIndex);
                t2.set(corners[a], corners[c], corners[d], materialIndex);
                triangles.push_back(t1);
                triangles.push_back(t2);
            };

            addQuad(0, 1, 2, 3);  // Bottom
            addQuad(5, 4, 7, 6);  // Top
            addQuad(0, 4, 5, 1);  // Front
            addQuad(3, 7, 6, 2);  // Back
            addQuad(1, 5, 6, 2);  // Right
            addQuad(4, 0, 3, 7);  // Left
            break;
        }

        default:
            // Skip other element types
            break;
    }
}

// Global material texture index cache (populated by loadMaterialMap)
static std::unordered_map<std::string, int> g_materialTextureIndices;
static std::unordered_map<std::string, std::string> g_nameOverrides;
static std::unordered_map<std::string, std::string> g_categoryDefaults;
static bool g_materialMapLoaded = false;

/**
 * @brief Load material map from JSON file
 */
static void loadMaterialMap(const std::string& materialsDir) {
    if (g_materialMapLoaded) return;

    namespace fs = std::filesystem;
    std::string mapPath = materialsDir + "/material_map.json";

    if (!fs::exists(mapPath)) {
        // Try relative path
        mapPath = "materials/material_map.json";
        if (!fs::exists(mapPath)) {
            std::cerr << "[BVH] material_map.json not found\n";
            g_materialMapLoaded = true;
            return;
        }
    }

    std::ifstream mapFile(mapPath);
    if (!mapFile.is_open()) {
        g_materialMapLoaded = true;
        return;
    }

    try {
        json materialMap;
        mapFile >> materialMap;

        // Load name overrides
        if (materialMap.contains("name_overrides")) {
            for (auto& [key, value] : materialMap["name_overrides"].items()) {
                g_nameOverrides[key] = value.get<std::string>();
            }
        }

        // Load category defaults
        if (materialMap.contains("category_defaults")) {
            for (auto& [key, value] : materialMap["category_defaults"].items()) {
                g_categoryDefaults[key] = value.get<std::string>();
            }
        }

        // Build texture index map for polyhaven materials
        // Each polyhaven material uses 4 consecutive texture layers
        int texIndex = 0;
        if (materialMap.contains("materials")) {
            for (auto& [key, value] : materialMap["materials"].items()) {
                if (key.find("polyhaven/") == 0 && value.contains("folder")) {
                    g_materialTextureIndices[key] = texIndex;
                    texIndex += 4;  // Each material has 4 texture layers
                }
            }
        }

        std::cout << "[BVH] Loaded material map with " << g_materialTextureIndices.size()
                  << " textured materials\n";

    } catch (const std::exception& e) {
        std::cerr << "[BVH] Failed to parse material_map.json: " << e.what() << "\n";
    }

    g_materialMapLoaded = true;
}

/**
 * @brief Get texture index for a material name
 */
static int getTextureIndexForMaterial(const std::string& materialName, ElementType elemType) {
    // First check name overrides
    auto overrideIt = g_nameOverrides.find(materialName);
    if (overrideIt != g_nameOverrides.end()) {
        auto texIt = g_materialTextureIndices.find(overrideIt->second);
        if (texIt != g_materialTextureIndices.end()) {
            return texIt->second;
        }
    }

    // Check for direct polyhaven material name
    auto directIt = g_materialTextureIndices.find(materialName);
    if (directIt != g_materialTextureIndices.end()) {
        return directIt->second;
    }

    // Try category defaults based on element type
    std::string category;
    switch (elemType) {
        case ElementType::Wall:
            if (materialName.find("Ext") != std::string::npos ||
                materialName.find("brick") != std::string::npos ||
                materialName.find("Brick") != std::string::npos) {
                category = "Walls_Exterior";
            } else {
                category = "Walls";
            }
            break;
        case ElementType::Floor:
            if (materialName.find("Wood") != std::string::npos ||
                materialName.find("wood") != std::string::npos) {
                category = "Floors_Wood";
            } else {
                category = "Floors";
            }
            break;
        case ElementType::Roof:
            if (materialName.find("Metal") != std::string::npos ||
                materialName.find("metal") != std::string::npos) {
                category = "Roofs_Metal";
            } else {
                category = "Roofs";
            }
            break;
        default:
            break;
    }

    if (!category.empty()) {
        auto catIt = g_categoryDefaults.find(category);
        if (catIt != g_categoryDefaults.end()) {
            auto texIt = g_materialTextureIndices.find(catIt->second);
            if (texIt != g_materialTextureIndices.end()) {
                return texIt->second;
            }
        }
    }

    return -1;  // No texture
}

/**
 * @brief Map material keyword to Poly Haven texture (matching renderer's resolveMaterialName)
 */
static std::string mapMaterialKeyword(const std::string& key, ElementType type) {
    // Convert to lowercase for matching
    std::string lower = key;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    // Keyword-based mapping (same as renderer)
    if (lower.find("brick") != std::string::npos) {
        return "polyhaven/brick_wall_006";
    }
    if (lower.find("concrete") != std::string::npos || lower.find("cement") != std::string::npos ||
        lower.find("stone") != std::string::npos) {
        return "polyhaven/concrete_wall_008";
    }
    if (lower.find("drywall") != std::string::npos || lower.find("plaster") != std::string::npos ||
        lower.find("gypsum") != std::string::npos || lower.find("paint") != std::string::npos ||
        lower.find("stucco") != std::string::npos || lower.find("interior") != std::string::npos ||
        lower.find("tyvek") != std::string::npos || lower.find("membrane") != std::string::npos ||
        lower.find("poly") != std::string::npos || lower.find("vapor") != std::string::npos) {
        return "polyhaven/concrete_wall_008";  // Use concrete for interior walls and membranes
    }
    if (lower.find("tile") != std::string::npos || lower.find("ceramic") != std::string::npos) {
        return "polyhaven/concrete_floor_003";  // Use floor concrete for tiles
    }
    if (lower.find("wood") != std::string::npos || lower.find("timber") != std::string::npos ||
        lower.find("osb") != std::string::npos || lower.find("plywood") != std::string::npos) {
        return "polyhaven/wood_floor_deck";
    }
    if (lower.find("vinyl") != std::string::npos || lower.find("siding") != std::string::npos) {
        return "polyhaven/concrete_wall_008";
    }
    if (lower.find("glass") != std::string::npos || lower.find("glazing") != std::string::npos) {
        return "glass";
    }
    if (lower.find("metal") != std::string::npos || lower.find("steel") != std::string::npos ||
        lower.find("aluminum") != std::string::npos) {
        return "polyhaven/metal_plate_02";
    }
    if (lower.find("shingle") != std::string::npos || lower.find("asphalt") != std::string::npos ||
        lower.find("roof") != std::string::npos || lower.find("slate") != std::string::npos) {
        return "polyhaven/roof_slates_02";
    }
    if (lower.find("grass") != std::string::npos || lower.find("lawn") != std::string::npos) {
        return "polyhaven/grass_path_2";
    }
    if (lower.find("gravel") != std::string::npos || lower.find("patio") != std::string::npos) {
        return "polyhaven/gravel_concrete";
    }
    if (lower.find("asphalt") != std::string::npos || lower.find("pavement") != std::string::npos) {
        return "polyhaven/asphalt_04";
    }

    // Generic "wall" without specific material - use concrete for interior appearance
    if (lower == "wall" || lower == "interior" || lower == "partition") {
        return "polyhaven/concrete_wall_008";
    }

    // Default based on element type
    switch (type) {
        case ElementType::Wall:
            return "polyhaven/brick_wall_006";
        case ElementType::Floor:
            return "polyhaven/concrete_floor_003";
        case ElementType::Roof:
            return "polyhaven/roof_slates_02";
        case ElementType::Door:
        case ElementType::Beam:
        case ElementType::Column:
            return "polyhaven/wood_floor_deck";
        case ElementType::Window:
            return "glass";
        default:
            return "polyhaven/concrete_wall_008";
    }
}

/**
 * @brief Resolve material name similar to how renderer does it
 */
static std::string resolvePathTracerMaterial(const StructuralElement& elem) {
    const std::string& matName = elem.material;

    // If material already specifies a polyhaven texture, use it directly
    if (matName.find("polyhaven/") != std::string::npos) {
        return matName;
    }

    // If material is specified, map it using keywords
    if (!matName.empty() && matName != "default") {
        std::string resolved = mapMaterialKeyword(matName, elem.type);
        std::cout << "[BVH] Material mapping: '" << matName << "' -> '" << resolved << "'\n";
        return resolved;
    }

    // Default materials based on element type
    std::string defaultMat = mapMaterialKeyword("", elem.type);
    std::cout << "[BVH] Using default material for type " << static_cast<int>(elem.type) << ": '" << defaultMat << "'\n";
    return defaultMat;
}

/**
 * @brief Get material properties from element type
 */
static GPUPTMaterial getMaterialForElement(const StructuralElement& elem) {
    GPUPTMaterial mat;
    mat.setDefault();

    // Try to load material map
    loadMaterialMap("materials");

    // Resolve material name (same logic as real-time renderer)
    std::string matName = resolvePathTracerMaterial(elem);

    // Get texture index for this material
    int texIndex = getTextureIndexForMaterial(matName, elem.type);
    mat.texIndices.x = static_cast<f32>(texIndex);

    // Match Poly Haven material colors for consistency with real-time renderer
    if (matName.find("polyhaven/brick") != std::string::npos || matName.find("brick") != std::string::npos || matName.find("Brick") != std::string::npos) {
        // polyhaven/brick_wall_006 - reddish-brown brick
        mat.albedo = vec4(0.45f, 0.28f, 0.22f, 1.0f);
        mat.properties.x = 0.85f;   // Roughness
        mat.properties.y = 0.0f;    // Metallic
    } else if (matName.find("polyhaven/concrete") != std::string::npos || matName.find("concrete") != std::string::npos || matName.find("Concrete") != std::string::npos) {
        // polyhaven/concrete_wall_008 - grey concrete
        mat.albedo = vec4(0.5f, 0.48f, 0.45f, 1.0f);
        mat.properties.x = 0.9f;    // Roughness
        mat.properties.y = 0.0f;    // Metallic
    } else if (matName.find("polyhaven/wood") != std::string::npos || matName.find("wood") != std::string::npos || matName.find("Wood") != std::string::npos) {
        // polyhaven/wood_floor_deck - warm wood
        mat.albedo = vec4(0.4f, 0.28f, 0.18f, 1.0f);
        mat.properties.x = 0.65f;
        mat.properties.y = 0.0f;
    } else if (matName.find("polyhaven/roof") != std::string::npos || matName.find("roof_slates") != std::string::npos) {
        // polyhaven/roof_slates_02 - dark slate
        mat.albedo = vec4(0.25f, 0.24f, 0.23f, 1.0f);
        mat.properties.x = 0.75f;
        mat.properties.y = 0.0f;
    } else if (matName.find("polyhaven/asphalt") != std::string::npos || matName.find("asphalt") != std::string::npos) {
        // polyhaven/asphalt_04 - dark grey asphalt
        mat.albedo = vec4(0.15f, 0.15f, 0.15f, 1.0f);
        mat.properties.x = 0.9f;
        mat.properties.y = 0.0f;
    } else if (matName.find("polyhaven/grass") != std::string::npos || matName.find("grass") != std::string::npos) {
        // polyhaven/grass_path_2 - green grass
        mat.albedo = vec4(0.25f, 0.35f, 0.15f, 1.0f);
        mat.properties.x = 0.9f;
        mat.properties.y = 0.0f;
    } else if (matName.find("polyhaven/gravel") != std::string::npos || matName.find("gravel") != std::string::npos) {
        // polyhaven/gravel_concrete - grey gravel
        mat.albedo = vec4(0.45f, 0.42f, 0.4f, 1.0f);
        mat.properties.x = 0.95f;
        mat.properties.y = 0.0f;
    } else if (matName.find("polyhaven/metal") != std::string::npos || matName.find("steel") != std::string::npos || matName.find("Steel") != std::string::npos) {
        // polyhaven/metal_plate_02 or steel
        mat.albedo = vec4(0.55f, 0.55f, 0.55f, 1.0f);
        mat.properties.x = 0.35f;   // Roughness
        mat.properties.y = 0.9f;    // Metallic
    } else if (matName.find("glass") != std::string::npos || matName.find("Glass") != std::string::npos) {
        mat.albedo = vec4(0.9f, 0.9f, 0.95f, 0.3f);
        mat.properties.x = 0.05f;
        mat.properties.y = 0.0f;
        mat.properties.z = 1.5f;    // IOR
        mat.properties.w = 0.9f;    // Transmission
    } else {
        // Default based on element type - use Poly Haven-matching colors
        switch (elem.type) {
            case ElementType::Wall:
                // Match polyhaven/brick_wall_006
                mat.albedo = vec4(0.45f, 0.28f, 0.22f, 1.0f);
                mat.properties.x = 0.85f;
                break;
            case ElementType::Floor:
                // Match polyhaven/concrete_floor_003 or wood
                mat.albedo = vec4(0.5f, 0.48f, 0.45f, 1.0f);
                mat.properties.x = 0.85f;
                break;
            case ElementType::Roof:
                // Match polyhaven/roof_slates_02
                mat.albedo = vec4(0.25f, 0.24f, 0.23f, 1.0f);
                mat.properties.x = 0.75f;
                break;
            case ElementType::Window:
                mat.albedo = vec4(0.9f, 0.95f, 1.0f, 0.2f);
                mat.properties.x = 0.02f;  // Very smooth glass
                mat.properties.y = 0.0f;   // Non-metallic
                mat.properties.z = 1.5f;   // IOR for glass
                mat.properties.w = 0.95f;  // High transmission
                break;
            default:
                mat.albedo = vec4(0.5f, 0.5f, 0.5f, 1.0f);
                mat.properties.x = 0.7f;
                break;
        }
    }

    return mat;
}

bool buildSceneBVH(
    const std::vector<StructuralElement>& elements,
    std::vector<GPUTriangle>& outTriangles,
    std::vector<GPUBVHNode>& outNodes,
    std::vector<GPUPTMaterial>& outMaterials)
{
    if (elements.empty()) {
        std::cerr << "[BVH] No elements to build scene from\n";
        return false;
    }

    // Reset debug counters
    g_customMeshCount = 0;
    g_fallbackCount = 0;

    outTriangles.clear();
    outMaterials.clear();

    std::cout << "[BVH] Building scene from " << elements.size() << " elements\n";

    // Generate triangles and materials from elements
    for (size_t i = 0; i < elements.size(); ++i) {
        const auto& elem = elements[i];
        u32 matIndex = static_cast<u32>(outMaterials.size());

        // Add material
        outMaterials.push_back(getMaterialForElement(elem));

        // Generate triangles
        generateElementTriangles(elem, matIndex, outTriangles);
    }

    if (outTriangles.empty()) {
        std::cerr << "[BVH] No triangles generated from " << elements.size() << " elements\n";
        return false;
    }

    // Build BVH
    BVHBuilder builder;
    if (!builder.build(outTriangles)) {
        return false;
    }

    // Copy nodes
    outNodes = builder.getNodes();

    // Reorder triangles according to BVH
    const auto& orderedIndices = builder.getOrderedPrimIndices();
    std::vector<GPUTriangle> reorderedTriangles;
    reorderedTriangles.reserve(outTriangles.size());
    for (u32 idx : orderedIndices) {
        reorderedTriangles.push_back(outTriangles[idx]);
    }
    outTriangles = std::move(reorderedTriangles);

    std::cout << "[BVH] Scene built: " << outTriangles.size() << " triangles, "
              << outNodes.size() << " nodes, " << outMaterials.size() << " materials\n";
    std::cout << "[BVH] Geometry: " << g_customMeshCount << " custom meshes, "
              << g_fallbackCount << " fallback generated\n";

    return true;
}

/**
 * @brief Generate terrain material for path tracing
 */
static GPUPTMaterial getTerrainMaterial(const std::string& materialName) {
    GPUPTMaterial mat;
    mat.setDefault();

    // Load material map if not already loaded
    loadMaterialMap("materials");

    // Get texture index for this material
    int texIndex = -1;
    if (!materialName.empty()) {
        // Check for direct polyhaven material
        auto it = g_materialTextureIndices.find(materialName);
        if (it != g_materialTextureIndices.end()) {
            texIndex = it->second;
        } else {
            // Try with polyhaven prefix
            std::string fullName = "polyhaven/" + materialName;
            auto it2 = g_materialTextureIndices.find(fullName);
            if (it2 != g_materialTextureIndices.end()) {
                texIndex = it2->second;
            }
        }
    }

    mat.texIndices.x = static_cast<f32>(texIndex);

    // Set terrain material properties based on name
    std::string lower = materialName;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    if (lower.find("grass") != std::string::npos) {
        mat.albedo = vec4(0.25f, 0.35f, 0.15f, 1.0f);
        mat.properties.x = 0.9f;  // Rough
    } else if (lower.find("gravel") != std::string::npos) {
        mat.albedo = vec4(0.45f, 0.42f, 0.4f, 1.0f);
        mat.properties.x = 0.95f;
    } else if (lower.find("asphalt") != std::string::npos) {
        mat.albedo = vec4(0.15f, 0.15f, 0.15f, 1.0f);
        mat.properties.x = 0.9f;
    } else if (lower.find("sand") != std::string::npos) {
        mat.albedo = vec4(0.76f, 0.70f, 0.50f, 1.0f);
        mat.properties.x = 0.95f;
    } else if (lower.find("mud") != std::string::npos || lower.find("dirt") != std::string::npos) {
        mat.albedo = vec4(0.35f, 0.25f, 0.18f, 1.0f);
        mat.properties.x = 0.9f;
    } else if (lower.find("rock") != std::string::npos || lower.find("stone") != std::string::npos) {
        mat.albedo = vec4(0.4f, 0.38f, 0.35f, 1.0f);
        mat.properties.x = 0.85f;
    } else if (lower.find("snow") != std::string::npos) {
        mat.albedo = vec4(0.95f, 0.95f, 0.98f, 1.0f);
        mat.properties.x = 0.7f;
    } else if (lower.find("concrete") != std::string::npos) {
        mat.albedo = vec4(0.5f, 0.48f, 0.45f, 1.0f);
        mat.properties.x = 0.9f;
    } else {
        // Default terrain - greenish brown
        mat.albedo = vec4(0.35f, 0.32f, 0.22f, 1.0f);
        mat.properties.x = 0.85f;
    }

    mat.properties.y = 0.0f;  // Non-metallic

    // Set terrain flag in texIndices.w for shader to use simple XZ UV projection
    mat.texIndices.w = 1.0f;

    return mat;
}

/**
 * @brief Generate triangles from terrain mesh
 */
static void generateTerrainTriangles(
    const TerrainMesh& terrain,
    u32 materialIndex,
    std::vector<GPUTriangle>& triangles)
{
    const auto& vertices = terrain.vertices;
    const auto& indices = terrain.indices;

    if (indices.size() < 3) return;

    // Process triangles
    for (size_t i = 0; i + 2 < indices.size(); i += 3) {
        u32 i0 = indices[i];
        u32 i1 = indices[i + 1];
        u32 i2 = indices[i + 2];

        if (i0 >= vertices.size() || i1 >= vertices.size() || i2 >= vertices.size()) {
            continue;
        }

        GPUTriangle tri;
        tri.set(vertices[i0].position, vertices[i1].position, vertices[i2].position, materialIndex);
        triangles.push_back(tri);
    }
}

bool buildSceneBVH(
    const std::vector<StructuralElement>& elements,
    const TerrainMesh* terrain,
    const std::string& terrainMaterialName,
    std::vector<GPUTriangle>& outTriangles,
    std::vector<GPUBVHNode>& outNodes,
    std::vector<GPUPTMaterial>& outMaterials)
{
    // Reset debug counters
    g_customMeshCount = 0;
    g_fallbackCount = 0;

    outTriangles.clear();
    outMaterials.clear();

    std::cout << "[BVH] Building scene from " << elements.size() << " elements";
    if (terrain && terrain->hasData()) {
        std::cout << " + terrain (" << terrain->indices.size() / 3 << " triangles)";
    }
    std::cout << "\n";

    // Generate triangles and materials from elements
    for (size_t i = 0; i < elements.size(); ++i) {
        const auto& elem = elements[i];
        u32 matIndex = static_cast<u32>(outMaterials.size());

        // Add material
        outMaterials.push_back(getMaterialForElement(elem));

        // Generate triangles
        generateElementTriangles(elem, matIndex, outTriangles);
    }

    // Add terrain if present
    if (terrain && terrain->hasData()) {
        u32 terrainMatIndex = static_cast<u32>(outMaterials.size());
        outMaterials.push_back(getTerrainMaterial(terrainMaterialName));
        generateTerrainTriangles(*terrain, terrainMatIndex, outTriangles);
        std::cout << "[BVH] Added terrain with material '" << terrainMaterialName << "'\n";
    }

    if (outTriangles.empty()) {
        std::cerr << "[BVH] No triangles generated\n";
        return false;
    }

    // Build BVH
    BVHBuilder builder;
    if (!builder.build(outTriangles)) {
        return false;
    }

    // Copy nodes
    outNodes = builder.getNodes();

    // Reorder triangles according to BVH
    const auto& orderedIndices = builder.getOrderedPrimIndices();
    std::vector<GPUTriangle> reorderedTriangles;
    reorderedTriangles.reserve(outTriangles.size());
    for (u32 idx : orderedIndices) {
        reorderedTriangles.push_back(outTriangles[idx]);
    }
    outTriangles = std::move(reorderedTriangles);

    std::cout << "[BVH] Scene built: " << outTriangles.size() << " triangles, "
              << outNodes.size() << " nodes, " << outMaterials.size() << " materials\n";
    std::cout << "[BVH] Geometry: " << g_customMeshCount << " custom meshes, "
              << g_fallbackCount << " fallback generated\n";

    return true;
}

} // namespace arch
