#pragma once
#include "types.hpp"
#include <vector>
#include <unordered_map>
#include <unordered_set>

namespace arch {
namespace CSG {

// A proper CSG library needs:
// 1. Mesh representation with half-edges for connectivity
// 2. Plane/triangle intersection
// 3. Triangle splitting along intersection edges
// 4. Inside/outside classification using BSP or ray casting
// 5. Result triangulation

struct Triangle {
    vec3 v[3];
    vec3 normal;

    Triangle() = default;
    Triangle(vec3 a, vec3 b, vec3 c) : v{a, b, c} {
        normal = glm::normalize(glm::cross(b - a, c - a));
    }

    vec3 center() const { return (v[0] + v[1] + v[2]) / 3.0f; }
};

struct Mesh {
    std::vector<Triangle> triangles;

    // Build from vertices and indices
    static Mesh fromVerticesIndices(const std::vector<vec3>& verts,
                                     const std::vector<std::array<u32, 3>>& faces);

    // Compute axis-aligned bounding box
    void getBounds(vec3& minB, vec3& maxB) const;

    // Check if point is inside mesh (ray casting)
    bool containsPoint(const vec3& p) const;
};

// Plane representation for splitting
struct Plane {
    vec3 normal;
    f32 d;  // ax + by + cz + d = 0

    Plane() : normal(0, 1, 0), d(0) {}
    Plane(vec3 n, f32 dist) : normal(glm::normalize(n)), d(dist) {}
    Plane(vec3 a, vec3 b, vec3 c);  // From 3 points

    f32 signedDistance(const vec3& p) const {
        return glm::dot(normal, p) + d;
    }

    // Classify point: -1 = behind, 0 = on plane, 1 = in front
    int classify(const vec3& p, f32 epsilon = 0.0001f) const {
        f32 dist = signedDistance(p);
        if (dist > epsilon) return 1;
        if (dist < -epsilon) return -1;
        return 0;
    }
};

// Split a triangle by a plane
// Returns: coplanar, front, back triangles
void splitTriangle(const Triangle& tri, const Plane& plane,
                   std::vector<Triangle>& coplanar,
                   std::vector<Triangle>& front,
                   std::vector<Triangle>& back);

// BSP Tree for efficient inside/outside testing
class BSPNode {
public:
    Plane plane;
    std::vector<Triangle> coplanar;
    std::unique_ptr<BSPNode> front;
    std::unique_ptr<BSPNode> back;

    BSPNode() = default;

    // Build BSP tree from triangles
    static std::unique_ptr<BSPNode> build(std::vector<Triangle> triangles);

    // Clip triangles to this BSP tree (keep parts inside)
    void clipTo(std::vector<Triangle>& triangles) const;

    // Invert the BSP tree (swap inside/outside)
    void invert();

    // Get all triangles from tree
    void getAllTriangles(std::vector<Triangle>& result) const;
};

// Main CSG operations
class CSGOperations {
public:
    // Union: A + B (combine both, remove internal faces)
    static Mesh meshUnion(const Mesh& a, const Mesh& b);

    // Intersection: A & B (keep only overlapping region)
    static Mesh meshIntersection(const Mesh& a, const Mesh& b);

    // Difference: A - B (subtract B from A)
    static Mesh meshDifference(const Mesh& a, const Mesh& b);
};

// Convert between formats
std::pair<std::vector<Vertex>, std::vector<u32>>
meshToVerticesIndices(const Mesh& mesh, vec3 color = {0.7f, 0.7f, 0.7f});

Mesh verticesIndicesToMesh(const std::vector<Vertex>& verts,
                           const std::vector<u32>& indices);

} // namespace CSG
} // namespace arch
