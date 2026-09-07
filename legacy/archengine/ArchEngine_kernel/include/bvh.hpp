/**
 * @file bvh.hpp
 * @brief Bounding Volume Hierarchy for GPU path tracing
 *
 * This file contains structures and algorithms for building a BVH
 * optimized for GPU ray traversal. Uses SAH (Surface Area Heuristic)
 * for high-quality tree construction.
 */

#pragma once

#include "types.hpp"
#include <vector>
#include <span>
#include <limits>

namespace arch {

/**
 * @brief Axis-Aligned Bounding Box
 */
struct AABB {
    vec3 min = vec3(std::numeric_limits<f32>::max());
    vec3 max = vec3(std::numeric_limits<f32>::lowest());

    AABB() = default;
    AABB(const vec3& min, const vec3& max) : min(min), max(max) {}

    /** @brief Expand box to include a point */
    void expand(const vec3& point) {
        min = glm::min(min, point);
        max = glm::max(max, point);
    }

    /** @brief Expand box to include another box */
    void expand(const AABB& other) {
        min = glm::min(min, other.min);
        max = glm::max(max, other.max);
    }

    /** @brief Get surface area (for SAH) */
    f32 surfaceArea() const {
        vec3 d = max - min;
        return 2.0f * (d.x * d.y + d.y * d.z + d.z * d.x);
    }

    /** @brief Get centroid */
    vec3 centroid() const {
        return (min + max) * 0.5f;
    }

    /** @brief Get diagonal */
    vec3 diagonal() const {
        return max - min;
    }

    /** @brief Get the longest axis (0=X, 1=Y, 2=Z) */
    u32 longestAxis() const {
        vec3 d = diagonal();
        if (d.x > d.y && d.x > d.z) return 0;
        if (d.y > d.z) return 1;
        return 2;
    }

    /** @brief Check if box is valid (min <= max) */
    bool isValid() const {
        return min.x <= max.x && min.y <= max.y && min.z <= max.z;
    }
};

/**
 * @brief GPU-friendly BVH node (32 bytes, cache-aligned)
 *
 * For internal nodes:
 *   boundsMin.w = left child index (as float bits)
 *   boundsMax.w = right child index (as float bits)
 *
 * For leaf nodes:
 *   boundsMin.w = -(primitiveOffset + 1) (negative indicates leaf)
 *   boundsMax.w = primitiveCount
 */
struct alignas(16) GPUBVHNode {
    vec4 boundsMin;  // xyz = min bounds, w = child/prim info
    vec4 boundsMax;  // xyz = max bounds, w = child/prim info

    void setInternalNode(const AABB& bounds, u32 leftChild, u32 rightChild) {
        boundsMin = vec4(bounds.min, 0.0f);
        boundsMax = vec4(bounds.max, 0.0f);
        // Store indices as float bits
        std::memcpy(&boundsMin.w, &leftChild, sizeof(u32));
        std::memcpy(&boundsMax.w, &rightChild, sizeof(u32));
    }

    void setLeafNode(const AABB& bounds, u32 primOffset, u32 primCount) {
        boundsMin = vec4(bounds.min, 0.0f);
        boundsMax = vec4(bounds.max, 0.0f);
        // Negative offset indicates leaf
        i32 negOffset = -static_cast<i32>(primOffset + 1);
        std::memcpy(&boundsMin.w, &negOffset, sizeof(i32));
        std::memcpy(&boundsMax.w, &primCount, sizeof(u32));
    }

    bool isLeaf() const {
        i32 val;
        std::memcpy(&val, &boundsMin.w, sizeof(i32));
        return val < 0;
    }

    u32 getLeftChild() const {
        u32 val;
        std::memcpy(&val, &boundsMin.w, sizeof(u32));
        return val;
    }

    u32 getRightChild() const {
        u32 val;
        std::memcpy(&val, &boundsMax.w, sizeof(u32));
        return val;
    }

    u32 getPrimOffset() const {
        i32 val;
        std::memcpy(&val, &boundsMin.w, sizeof(i32));
        return static_cast<u32>(-val - 1);
    }

    u32 getPrimCount() const {
        u32 val;
        std::memcpy(&val, &boundsMax.w, sizeof(u32));
        return val;
    }
};

/**
 * @brief GPU triangle for path tracing (48 bytes)
 *
 * Stores triangle vertices and material index.
 */
struct alignas(16) GPUTriangle {
    vec4 v0;  // xyz = position, w = material index (as float bits)
    vec4 v1;  // xyz = position, w = packed normal.x
    vec4 v2;  // xyz = position, w = packed normal.y (normal.z derived)

    void set(const vec3& p0, const vec3& p1, const vec3& p2, u32 materialIndex) {
        v0 = vec4(p0, 0.0f);
        v1 = vec4(p1, 0.0f);
        v2 = vec4(p2, 0.0f);
        std::memcpy(&v0.w, &materialIndex, sizeof(u32));

        // Compute and pack face normal
        vec3 edge1 = p1 - p0;
        vec3 edge2 = p2 - p0;
        vec3 normal = glm::normalize(glm::cross(edge1, edge2));
        v1.w = normal.x;
        v2.w = normal.y;
        // normal.z can be derived: sqrt(1 - x^2 - y^2) * sign
    }

    vec3 getPosition0() const { return vec3(v0); }
    vec3 getPosition1() const { return vec3(v1); }
    vec3 getPosition2() const { return vec3(v2); }

    u32 getMaterialIndex() const {
        u32 val;
        std::memcpy(&val, &v0.w, sizeof(u32));
        return val;
    }

    vec3 getNormal() const {
        f32 nx = v1.w;
        f32 ny = v2.w;
        f32 nz2 = 1.0f - nx * nx - ny * ny;
        f32 nz = nz2 > 0.0f ? std::sqrt(nz2) : 0.0f;
        return vec3(nx, ny, nz);
    }

    AABB getBounds() const {
        AABB box;
        box.expand(getPosition0());
        box.expand(getPosition1());
        box.expand(getPosition2());
        return box;
    }

    vec3 getCentroid() const {
        return (getPosition0() + getPosition1() + getPosition2()) / 3.0f;
    }
};

/**
 * @brief GPU material for path tracing (64 bytes)
 */
struct alignas(16) GPUPTMaterial {
    vec4 albedo;      // rgb = albedo color, a = alpha
    vec4 emission;    // rgb = emission color, a = intensity
    vec4 properties;  // x = roughness, y = metallic, z = ior, w = transmission
    vec4 texIndices;  // x = albedo tex, y = roughness tex, z = normal tex, w = emission tex

    void setDefault() {
        albedo = vec4(0.8f, 0.8f, 0.8f, 1.0f);
        emission = vec4(0.0f, 0.0f, 0.0f, 0.0f);
        properties = vec4(0.5f, 0.0f, 1.5f, 0.0f);  // roughness=0.5, metallic=0, ior=1.5, transmission=0
        texIndices = vec4(-1.0f);  // No textures
    }
};

/**
 * @brief Primitive info during BVH construction
 */
struct BVHPrimitive {
    u32 index;      // Original triangle index
    AABB bounds;    // Bounding box
    vec3 centroid;  // Centroid for partitioning
};

/**
 * @brief BVH build node (used during construction)
 */
struct BVHBuildNode {
    AABB bounds;
    BVHBuildNode* children[2] = {nullptr, nullptr};
    u32 splitAxis = 0;
    u32 firstPrimOffset = 0;
    u32 primCount = 0;

    bool isLeaf() const { return primCount > 0; }
};

/**
 * @brief SAH-based BVH builder
 *
 * Builds a high-quality BVH using the Surface Area Heuristic.
 * Outputs a flat array suitable for GPU traversal.
 */
class BVHBuilder {
public:
    /**
     * @brief Build configuration
     */
    struct Config {
        u32 maxPrimsInNode = 4;     // Max primitives per leaf
        u32 sahBuckets = 12;        // Number of SAH buckets
        f32 traversalCost = 1.0f;   // Relative cost of traversal vs intersection
        f32 intersectCost = 1.0f;
    };

    BVHBuilder(const Config& config = Config{});
    ~BVHBuilder();

    /**
     * @brief Build BVH from triangles
     * @param triangles Input triangle array
     * @return true if build succeeded
     */
    bool build(const std::vector<GPUTriangle>& triangles);

    /**
     * @brief Get flat node array for GPU upload
     */
    const std::vector<GPUBVHNode>& getNodes() const { return m_nodes; }

    /**
     * @brief Get reordered triangle indices
     *
     * Triangles are reordered for cache-friendly leaf access.
     */
    const std::vector<u32>& getOrderedPrimIndices() const { return m_orderedPrimIndices; }

    /**
     * @brief Get total node count
     */
    u32 getNodeCount() const { return static_cast<u32>(m_nodes.size()); }

    /**
     * @brief Get tree depth
     */
    u32 getTreeDepth() const { return m_treeDepth; }

    /**
     * @brief Get leaf count
     */
    u32 getLeafCount() const { return m_leafCount; }

private:
    BVHBuildNode* buildRecursive(
        std::span<BVHPrimitive> prims,
        u32& totalNodes,
        std::vector<u32>& orderedPrims
    );

    u32 flattenBVH(BVHBuildNode* node, u32* offset);

    void deleteBuildTree(BVHBuildNode* node);

    // SAH partition evaluation
    struct SAHBucket {
        u32 count = 0;
        AABB bounds;
    };

    f32 evaluateSAH(
        std::span<BVHPrimitive> prims,
        const AABB& centroidBounds,
        u32 axis,
        u32 splitBucket,
        const std::vector<SAHBucket>& buckets
    );

    Config m_config;
    std::vector<GPUBVHNode> m_nodes;
    std::vector<u32> m_orderedPrimIndices;
    BVHBuildNode* m_root = nullptr;
    u32 m_treeDepth = 0;
    u32 m_leafCount = 0;
};

/**
 * @brief Build BVH from scene geometry
 *
 * Convenience function to build a BVH from Building elements.
 *
 * @param elements Structural elements to process
 * @param outTriangles Output triangle array (reordered by BVH)
 * @param outNodes Output BVH node array
 * @param outMaterials Output material array
 * @return true if build succeeded
 */
bool buildSceneBVH(
    const std::vector<StructuralElement>& elements,
    std::vector<GPUTriangle>& outTriangles,
    std::vector<GPUBVHNode>& outNodes,
    std::vector<GPUPTMaterial>& outMaterials
);

/**
 * @brief Build BVH from scene geometry including terrain
 *
 * Overload that includes terrain mesh in the scene.
 *
 * @param elements Structural elements to process
 * @param terrain Optional terrain mesh (nullptr to skip)
 * @param terrainMaterialName Material name for terrain texturing
 * @param outTriangles Output triangle array (reordered by BVH)
 * @param outNodes Output BVH node array
 * @param outMaterials Output material array
 * @return true if build succeeded
 */
bool buildSceneBVH(
    const std::vector<StructuralElement>& elements,
    const TerrainMesh* terrain,
    const std::string& terrainMaterialName,
    std::vector<GPUTriangle>& outTriangles,
    std::vector<GPUBVHNode>& outNodes,
    std::vector<GPUPTMaterial>& outMaterials
);

} // namespace arch
