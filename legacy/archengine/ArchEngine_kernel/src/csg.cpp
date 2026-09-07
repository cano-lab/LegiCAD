#include "csg.hpp"
#include <algorithm>
#include <cmath>

namespace arch {
namespace CSG {

constexpr f32 EPSILON = 0.00001f;

// ============ Mesh ============

Mesh Mesh::fromVerticesIndices(const std::vector<vec3>& verts,
                                const std::vector<std::array<u32, 3>>& faces) {
    Mesh mesh;
    mesh.triangles.reserve(faces.size());
    for (const auto& f : faces) {
        mesh.triangles.emplace_back(verts[f[0]], verts[f[1]], verts[f[2]]);
    }
    return mesh;
}

void Mesh::getBounds(vec3& minB, vec3& maxB) const {
    minB = vec3(1e9f);
    maxB = vec3(-1e9f);
    for (const auto& tri : triangles) {
        for (int i = 0; i < 3; i++) {
            minB = glm::min(minB, tri.v[i]);
            maxB = glm::max(maxB, tri.v[i]);
        }
    }
}

bool Mesh::containsPoint(const vec3& p) const {
    // Ray casting: count intersections with +X ray
    int count = 0;
    vec3 dir(1, 0, 0);

    for (const auto& tri : triangles) {
        // Möller–Trumbore intersection
        vec3 edge1 = tri.v[1] - tri.v[0];
        vec3 edge2 = tri.v[2] - tri.v[0];
        vec3 h = glm::cross(dir, edge2);
        f32 a = glm::dot(edge1, h);
        if (std::abs(a) < EPSILON) continue;

        f32 f = 1.0f / a;
        vec3 s = p - tri.v[0];
        f32 u = f * glm::dot(s, h);
        if (u < 0.0f || u > 1.0f) continue;

        vec3 q = glm::cross(s, edge1);
        f32 v = f * glm::dot(dir, q);
        if (v < 0.0f || u + v > 1.0f) continue;

        f32 t = f * glm::dot(edge2, q);
        if (t > EPSILON) count++;
    }

    return (count % 2) == 1;
}

// ============ Plane ============

Plane::Plane(vec3 a, vec3 b, vec3 c) {
    normal = glm::normalize(glm::cross(b - a, c - a));
    d = -glm::dot(normal, a);
}

// ============ Triangle Splitting ============

void splitTriangle(const Triangle& tri, const Plane& plane,
                   std::vector<Triangle>& coplanar,
                   std::vector<Triangle>& front,
                   std::vector<Triangle>& back) {
    // Classify each vertex
    int types[3];
    f32 dists[3];
    int frontCount = 0, backCount = 0;

    for (int i = 0; i < 3; i++) {
        dists[i] = plane.signedDistance(tri.v[i]);
        types[i] = plane.classify(tri.v[i]);
        if (types[i] == 1) frontCount++;
        else if (types[i] == -1) backCount++;
    }

    // All on one side or coplanar
    if (frontCount == 0 && backCount == 0) {
        // Coplanar - check if facing same direction as plane
        if (glm::dot(tri.normal, plane.normal) > 0) {
            coplanar.push_back(tri);
        } else {
            coplanar.push_back(tri);  // Still coplanar, just flipped
        }
        return;
    }
    if (backCount == 0) {
        front.push_back(tri);
        return;
    }
    if (frontCount == 0) {
        back.push_back(tri);
        return;
    }

    // Triangle spans the plane - need to split
    std::vector<vec3> frontVerts, backVerts;

    for (int i = 0; i < 3; i++) {
        int j = (i + 1) % 3;
        const vec3& vi = tri.v[i];
        const vec3& vj = tri.v[j];

        if (types[i] != -1) frontVerts.push_back(vi);
        if (types[i] != 1) backVerts.push_back(vi);

        if ((types[i] | types[j]) == 0) continue;  // Both on plane or same side
        if (types[i] == 0 || types[j] == 0) continue;  // One is on plane
        if (types[i] == types[j]) continue;  // Same side

        // Compute intersection point
        f32 t = dists[i] / (dists[i] - dists[j]);
        vec3 intersection = vi + t * (vj - vi);
        frontVerts.push_back(intersection);
        backVerts.push_back(intersection);
    }

    // Triangulate front polygon (fan triangulation)
    if (frontVerts.size() >= 3) {
        for (size_t i = 1; i + 1 < frontVerts.size(); i++) {
            front.emplace_back(frontVerts[0], frontVerts[i], frontVerts[i + 1]);
        }
    }

    // Triangulate back polygon
    if (backVerts.size() >= 3) {
        for (size_t i = 1; i + 1 < backVerts.size(); i++) {
            back.emplace_back(backVerts[0], backVerts[i], backVerts[i + 1]);
        }
    }
}

// ============ BSP Node ============

std::unique_ptr<BSPNode> BSPNode::build(std::vector<Triangle> triangles) {
    if (triangles.empty()) return nullptr;

    auto node = std::make_unique<BSPNode>();

    // Use first triangle's plane as splitting plane
    node->plane = Plane(triangles[0].v[0], triangles[0].v[1], triangles[0].v[2]);

    std::vector<Triangle> frontTris, backTris;

    for (const auto& tri : triangles) {
        splitTriangle(tri, node->plane, node->coplanar, frontTris, backTris);
    }

    if (!frontTris.empty()) {
        node->front = build(std::move(frontTris));
    }
    if (!backTris.empty()) {
        node->back = build(std::move(backTris));
    }

    return node;
}

void BSPNode::clipTo(std::vector<Triangle>& triangles) const {
    if (triangles.empty()) return;

    std::vector<Triangle> frontTris, backTris;

    for (const auto& tri : triangles) {
        std::vector<Triangle> coplanarTmp;
        splitTriangle(tri, plane, coplanarTmp, frontTris, backTris);
        // Coplanar triangles go to front
        for (auto& t : coplanarTmp) frontTris.push_back(t);
    }

    if (front) {
        front->clipTo(frontTris);
    }
    if (back) {
        back->clipTo(backTris);
    } else {
        backTris.clear();  // Discard triangles behind (inside)
    }

    // Combine results
    triangles = std::move(frontTris);
    triangles.insert(triangles.end(), backTris.begin(), backTris.end());
}

void BSPNode::invert() {
    // Flip all triangles and plane
    for (auto& tri : coplanar) {
        std::swap(tri.v[0], tri.v[2]);
        tri.normal = -tri.normal;
    }
    plane.normal = -plane.normal;
    plane.d = -plane.d;

    // Swap front and back
    std::swap(front, back);

    if (front) front->invert();
    if (back) back->invert();
}

void BSPNode::getAllTriangles(std::vector<Triangle>& result) const {
    result.insert(result.end(), coplanar.begin(), coplanar.end());
    if (front) front->getAllTriangles(result);
    if (back) back->getAllTriangles(result);
}

// ============ CSG Operations ============

Mesh CSGOperations::meshUnion(const Mesh& a, const Mesh& b) {
    // Union = a.clipTo(!b) + b.clipTo(!a)
    auto bspA = BSPNode::build(a.triangles);
    auto bspB = BSPNode::build(b.triangles);

    if (!bspA || !bspB) {
        // One mesh is empty, return the other
        Mesh result;
        if (bspA) result.triangles = a.triangles;
        if (bspB) result.triangles.insert(result.triangles.end(),
                                          b.triangles.begin(), b.triangles.end());
        return result;
    }

    // Clip A to the complement of B
    std::vector<Triangle> aClipped = a.triangles;
    bspB->invert();
    bspB->clipTo(aClipped);
    bspB->invert();

    // Clip B to the complement of A
    std::vector<Triangle> bClipped = b.triangles;
    bspA->invert();
    bspA->clipTo(bClipped);
    bspA->invert();

    // Combine results
    Mesh result;
    result.triangles = std::move(aClipped);
    result.triangles.insert(result.triangles.end(), bClipped.begin(), bClipped.end());

    return result;
}

Mesh CSGOperations::meshIntersection(const Mesh& a, const Mesh& b) {
    // Intersection = !(!a + !b)
    auto bspA = BSPNode::build(a.triangles);
    auto bspB = BSPNode::build(b.triangles);

    if (!bspA || !bspB) return Mesh{};

    bspA->invert();
    bspB->invert();

    std::vector<Triangle> aClipped = a.triangles;
    bspB->clipTo(aClipped);

    std::vector<Triangle> bClipped = b.triangles;
    bspA->clipTo(bClipped);

    Mesh result;
    result.triangles = std::move(aClipped);
    result.triangles.insert(result.triangles.end(), bClipped.begin(), bClipped.end());

    // Flip back
    for (auto& tri : result.triangles) {
        std::swap(tri.v[0], tri.v[2]);
        tri.normal = -tri.normal;
    }

    return result;
}

Mesh CSGOperations::meshDifference(const Mesh& a, const Mesh& b) {
    // Difference = a.clipTo(!b)
    auto bspA = BSPNode::build(a.triangles);
    auto bspB = BSPNode::build(b.triangles);

    if (!bspA) return Mesh{};
    if (!bspB) return a;  // Nothing to subtract

    // A - B = A ∩ !B
    bspB->invert();

    std::vector<Triangle> result = a.triangles;
    bspB->clipTo(result);

    Mesh mesh;
    mesh.triangles = std::move(result);
    return mesh;
}

// ============ Format Conversion ============

std::pair<std::vector<Vertex>, std::vector<u32>>
meshToVerticesIndices(const Mesh& mesh, vec3 color) {
    std::vector<Vertex> vertices;
    std::vector<u32> indices;

    // Simple approach: each triangle gets its own vertices (no sharing)
    for (const auto& tri : mesh.triangles) {
        u32 baseIdx = static_cast<u32>(vertices.size());

        for (int i = 0; i < 3; i++) {
            Vertex v;
            v.position = tri.v[i];
            v.normal = tri.normal;
            v.color = color;
            vertices.push_back(v);
        }

        indices.push_back(baseIdx);
        indices.push_back(baseIdx + 1);
        indices.push_back(baseIdx + 2);
    }

    return {vertices, indices};
}

Mesh verticesIndicesToMesh(const std::vector<Vertex>& verts,
                           const std::vector<u32>& indices) {
    Mesh mesh;
    mesh.triangles.reserve(indices.size() / 3);

    for (size_t i = 0; i + 2 < indices.size(); i += 3) {
        mesh.triangles.emplace_back(
            verts[indices[i]].position,
            verts[indices[i + 1]].position,
            verts[indices[i + 2]].position
        );
    }

    return mesh;
}

} // namespace CSG
} // namespace arch
