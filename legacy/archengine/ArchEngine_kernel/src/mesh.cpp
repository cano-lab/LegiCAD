#include "mesh.hpp"
#include <algorithm>
#include <stdexcept>
#include <cstring>

namespace arch {

Mesh::Mesh(VulkanContext& context, const std::vector<Vertex>& vertices,
           const std::vector<u32>& indices)
    : m_context(context), m_vertexCount(static_cast<u32>(vertices.size())),
      m_indexCount(static_cast<u32>(indices.size())) {

    createVertexBuffer(vertices);
    createIndexBuffer(indices);
}

Mesh::~Mesh() {
    if (m_indexBuffer != VK_NULL_HANDLE) {
        vkDestroyBuffer(m_context.getDevice(), m_indexBuffer, nullptr);
        vkFreeMemory(m_context.getDevice(), m_indexBufferMemory, nullptr);
    }
    if (m_vertexBuffer != VK_NULL_HANDLE) {
        vkDestroyBuffer(m_context.getDevice(), m_vertexBuffer, nullptr);
        vkFreeMemory(m_context.getDevice(), m_vertexBufferMemory, nullptr);
    }
}

Mesh::Mesh(Mesh&& other) noexcept
    : m_context(other.m_context),
      m_vertexBuffer(other.m_vertexBuffer),
      m_vertexBufferMemory(other.m_vertexBufferMemory),
      m_indexBuffer(other.m_indexBuffer),
      m_indexBufferMemory(other.m_indexBufferMemory),
      m_vertexCount(other.m_vertexCount),
      m_indexCount(other.m_indexCount) {

    other.m_vertexBuffer = VK_NULL_HANDLE;
    other.m_vertexBufferMemory = VK_NULL_HANDLE;
    other.m_indexBuffer = VK_NULL_HANDLE;
    other.m_indexBufferMemory = VK_NULL_HANDLE;
}

Mesh& Mesh::operator=(Mesh&& other) noexcept {
    if (this != &other) {
        // Clean up existing resources
        if (m_indexBuffer != VK_NULL_HANDLE) {
            vkDestroyBuffer(m_context.getDevice(), m_indexBuffer, nullptr);
            vkFreeMemory(m_context.getDevice(), m_indexBufferMemory, nullptr);
        }
        if (m_vertexBuffer != VK_NULL_HANDLE) {
            vkDestroyBuffer(m_context.getDevice(), m_vertexBuffer, nullptr);
            vkFreeMemory(m_context.getDevice(), m_vertexBufferMemory, nullptr);
        }

        // Move resources
        m_vertexBuffer = other.m_vertexBuffer;
        m_vertexBufferMemory = other.m_vertexBufferMemory;
        m_indexBuffer = other.m_indexBuffer;
        m_indexBufferMemory = other.m_indexBufferMemory;
        m_vertexCount = other.m_vertexCount;
        m_indexCount = other.m_indexCount;

        other.m_vertexBuffer = VK_NULL_HANDLE;
        other.m_vertexBufferMemory = VK_NULL_HANDLE;
        other.m_indexBuffer = VK_NULL_HANDLE;
        other.m_indexBufferMemory = VK_NULL_HANDLE;
    }
    return *this;
}

void Mesh::bind(VkCommandBuffer commandBuffer) {
    VkBuffer buffers[] = {m_vertexBuffer};
    VkDeviceSize offsets[] = {0};
    vkCmdBindVertexBuffers(commandBuffer, 0, 1, buffers, offsets);
    vkCmdBindIndexBuffer(commandBuffer, m_indexBuffer, 0, VK_INDEX_TYPE_UINT32);
}

void Mesh::draw(VkCommandBuffer commandBuffer) {
    vkCmdDrawIndexed(commandBuffer, m_indexCount, 1, 0, 0, 0);
}

void Mesh::drawInstanced(VkCommandBuffer commandBuffer, u32 instanceCount) {
    vkCmdDrawIndexed(commandBuffer, m_indexCount, instanceCount, 0, 0, 0);
}

void Mesh::createVertexBuffer(const std::vector<Vertex>& vertices) {
    VkDeviceSize bufferSize = sizeof(Vertex) * vertices.size();

    // Staging buffer
    VkBuffer stagingBuffer;
    VkDeviceMemory stagingBufferMemory;
    m_context.createBuffer(bufferSize, VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
                           VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
                           stagingBuffer, stagingBufferMemory);

    // Copy data to staging buffer
    void* data;
    vkMapMemory(m_context.getDevice(), stagingBufferMemory, 0, bufferSize, 0, &data);
    std::memcpy(data, vertices.data(), bufferSize);
    vkUnmapMemory(m_context.getDevice(), stagingBufferMemory);

    // Create device-local buffer
    m_context.createBuffer(bufferSize,
                           VK_BUFFER_USAGE_TRANSFER_DST_BIT | VK_BUFFER_USAGE_VERTEX_BUFFER_BIT,
                           VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
                           m_vertexBuffer, m_vertexBufferMemory);

    // Copy from staging to device
    m_context.copyBuffer(stagingBuffer, m_vertexBuffer, bufferSize);

    // Cleanup staging buffer
    vkDestroyBuffer(m_context.getDevice(), stagingBuffer, nullptr);
    vkFreeMemory(m_context.getDevice(), stagingBufferMemory, nullptr);
}

void Mesh::createIndexBuffer(const std::vector<u32>& indices) {
    VkDeviceSize bufferSize = sizeof(u32) * indices.size();

    // Staging buffer
    VkBuffer stagingBuffer;
    VkDeviceMemory stagingBufferMemory;
    m_context.createBuffer(bufferSize, VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
                           VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
                           stagingBuffer, stagingBufferMemory);

    // Copy data
    void* data;
    vkMapMemory(m_context.getDevice(), stagingBufferMemory, 0, bufferSize, 0, &data);
    std::memcpy(data, indices.data(), bufferSize);
    vkUnmapMemory(m_context.getDevice(), stagingBufferMemory);

    // Create device-local buffer
    m_context.createBuffer(bufferSize,
                           VK_BUFFER_USAGE_TRANSFER_DST_BIT | VK_BUFFER_USAGE_INDEX_BUFFER_BIT,
                           VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
                           m_indexBuffer, m_indexBufferMemory);

    m_context.copyBuffer(stagingBuffer, m_indexBuffer, bufferSize);

    vkDestroyBuffer(m_context.getDevice(), stagingBuffer, nullptr);
    vkFreeMemory(m_context.getDevice(), stagingBufferMemory, nullptr);
}

// Geometry generation functions
namespace Geometry {

std::pair<std::vector<Vertex>, std::vector<u32>>
createBeam(vec3 start, vec3 end, f32 width, f32 height, vec3 color) {
    std::vector<Vertex> vertices;
    std::vector<u32> indices;

    // Beam direction and perpendicular vectors
    vec3 dir = glm::normalize(end - start);

    // For beams, we want the "top" face to face upward when possible
    // Use world up as reference, but handle edge cases
    vec3 worldUp = vec3(0, 1, 0);
    vec3 right, localUp;

    f32 upDot = std::abs(glm::dot(dir, worldUp));

    if (upDot > 0.99f) {
        // Nearly vertical beam - use world X as reference
        right = vec3(1, 0, 0);
        localUp = glm::normalize(glm::cross(right, dir));
        right = glm::normalize(glm::cross(dir, localUp));
    } else {
        // Normal case - project world up onto plane perpendicular to beam
        // This keeps the "top" of the beam facing upward
        localUp = glm::normalize(worldUp - dir * glm::dot(worldUp, dir));
        right = glm::normalize(glm::cross(dir, localUp));
    }

    f32 hw = width * 0.5f;
    f32 hh = height * 0.5f;

    // 8 corners of the beam box
    vec3 corners[8] = {
        start - right * hw - localUp * hh,  // 0: back-bottom-left
        start + right * hw - localUp * hh,  // 1: back-bottom-right
        start + right * hw + localUp * hh,  // 2: back-top-right
        start - right * hw + localUp * hh,  // 3: back-top-left
        end - right * hw - localUp * hh,    // 4: front-bottom-left
        end + right * hw - localUp * hh,    // 5: front-bottom-right
        end + right * hw + localUp * hh,    // 6: front-top-right
        end - right * hw + localUp * hh,    // 7: front-top-left
    };

    // UV scale factor (1 unit = 1 meter, texture tiles every meter)
    const f32 uvScale = 0.001f;  // 1mm to UV units (textures tile per meter)

    // Generate 6 faces with proper normals and UVs
    // UVs are based on world position for seamless tiling across surfaces
    auto addFace = [&](u32 i0, u32 i1, u32 i2, u32 i3, vec3 normal) {
        u32 baseIndex = static_cast<u32>(vertices.size());

        // Calculate UV based on world position projected onto face plane
        // Use the two axes perpendicular to the normal
        vec3 uAxis, vAxis;
        if (std::abs(normal.y) > 0.9f) {
            // Horizontal face (floor/ceiling) - use XZ
            uAxis = vec3(1, 0, 0);
            vAxis = vec3(0, 0, 1);
        } else if (std::abs(normal.x) > std::abs(normal.z)) {
            // Facing X - use ZY
            uAxis = vec3(0, 0, 1);
            vAxis = vec3(0, 1, 0);
        } else {
            // Facing Z - use XY
            uAxis = vec3(1, 0, 0);
            vAxis = vec3(0, 1, 0);
        }

        auto calcUV = [&](vec3 pos) -> vec2 {
            return vec2(glm::dot(pos, uAxis) * uvScale, glm::dot(pos, vAxis) * uvScale);
        };

        Vertex v0 = {corners[i0], normal, color, calcUV(corners[i0])};
        Vertex v1 = {corners[i1], normal, color, calcUV(corners[i1])};
        Vertex v2 = {corners[i2], normal, color, calcUV(corners[i2])};
        Vertex v3 = {corners[i3], normal, color, calcUV(corners[i3])};

        vertices.push_back(v0);
        vertices.push_back(v1);
        vertices.push_back(v2);
        vertices.push_back(v3);

        indices.push_back(baseIndex + 0);
        indices.push_back(baseIndex + 1);
        indices.push_back(baseIndex + 2);
        indices.push_back(baseIndex + 0);
        indices.push_back(baseIndex + 2);
        indices.push_back(baseIndex + 3);
    };

    addFace(0, 1, 2, 3, -dir);      // Back face
    addFace(5, 4, 7, 6, dir);        // Front face
    addFace(4, 0, 3, 7, -right);     // Left face
    addFace(1, 5, 6, 2, right);      // Right face
    addFace(3, 2, 6, 7, localUp);    // Top face
    addFace(4, 5, 1, 0, -localUp);   // Bottom face

    return {vertices, indices};
}

// Helper function to calculate UV from position relative to a reference point
// UV scale of 1.0 means 1 world unit = 1 texture tile (good for 1m textures like brick)
// Using fract() to keep UVs in 0-1 range avoids precision issues with large world coordinates
static vec2 calcWorldUV(vec3 pos, vec3 normal, f32 uvScale = 1.0f) {
    vec3 uAxis, vAxis;
    if (std::abs(normal.y) > 0.9f) {
        // Horizontal face (floor/ceiling) - use XZ
        uAxis = vec3(1, 0, 0);
        vAxis = vec3(0, 0, 1);
    } else if (std::abs(normal.x) > std::abs(normal.z)) {
        // Facing X - use ZY
        uAxis = vec3(0, 0, 1);
        vAxis = vec3(0, 1, 0);
    } else {
        // Facing Z - use XY
        uAxis = vec3(1, 0, 0);
        vAxis = vec3(0, 1, 0);
    }
    // Keep full UV values - don't use fract() here as that breaks interpolation
    // The shader will handle wrapping via texture repeat mode
    f32 u = glm::dot(pos, uAxis) * uvScale;
    f32 v = glm::dot(pos, vAxis) * uvScale;
    return vec2(u, v);
}

std::pair<std::vector<Vertex>, std::vector<u32>>
createColumn(vec3 position, f32 width, f32 depth, f32 height, vec3 color) {
    std::vector<Vertex> vertices;
    std::vector<u32> indices;

    f32 hw = width * 0.5f;
    f32 hd = depth * 0.5f;

    // 8 corners of the column
    vec3 corners[8] = {
        position + vec3(-hw, 0, -hd),       // 0: bottom-back-left
        position + vec3(hw, 0, -hd),        // 1: bottom-back-right
        position + vec3(hw, 0, hd),         // 2: bottom-front-right
        position + vec3(-hw, 0, hd),        // 3: bottom-front-left
        position + vec3(-hw, height, -hd),  // 4: top-back-left
        position + vec3(hw, height, -hd),   // 5: top-back-right
        position + vec3(hw, height, hd),    // 6: top-front-right
        position + vec3(-hw, height, hd),   // 7: top-front-left
    };

    auto addFace = [&](u32 i0, u32 i1, u32 i2, u32 i3, vec3 normal) {
        u32 baseIndex = static_cast<u32>(vertices.size());
        vertices.push_back({corners[i0], normal, color, calcWorldUV(corners[i0], normal)});
        vertices.push_back({corners[i1], normal, color, calcWorldUV(corners[i1], normal)});
        vertices.push_back({corners[i2], normal, color, calcWorldUV(corners[i2], normal)});
        vertices.push_back({corners[i3], normal, color, calcWorldUV(corners[i3], normal)});

        indices.push_back(baseIndex + 0);
        indices.push_back(baseIndex + 1);
        indices.push_back(baseIndex + 2);
        indices.push_back(baseIndex + 0);
        indices.push_back(baseIndex + 2);
        indices.push_back(baseIndex + 3);
    };

    addFace(0, 1, 5, 4, vec3(0, 0, -1));  // Back
    addFace(2, 3, 7, 6, vec3(0, 0, 1));   // Front
    addFace(3, 0, 4, 7, vec3(-1, 0, 0));  // Left
    addFace(1, 2, 6, 5, vec3(1, 0, 0));   // Right
    addFace(4, 5, 6, 7, vec3(0, 1, 0));   // Top
    addFace(3, 2, 1, 0, vec3(0, -1, 0));  // Bottom

    return {vertices, indices};
}

std::pair<std::vector<Vertex>, std::vector<u32>>
createFloorSlab(vec3 position, f32 width, f32 depth, f32 thickness, vec3 color) {
    return createColumn(position - vec3(0, thickness, 0), width, depth, thickness, color);
}

std::pair<std::vector<Vertex>, std::vector<u32>>
createDeflectedBeam(vec3 start, vec3 end, f32 width, f32 height,
                    f32 deflection, u32 segments, vec3 color) {
    std::vector<Vertex> vertices;
    std::vector<u32> indices;

    vec3 dir = end - start;
    f32 length = glm::length(dir);
    dir = glm::normalize(dir);

    vec3 up = vec3(0, 1, 0);
    if (std::abs(glm::dot(dir, up)) > 0.99f) {
        up = vec3(1, 0, 0);
    }

    vec3 right = glm::normalize(glm::cross(dir, up));
    vec3 localUp = glm::normalize(glm::cross(right, dir));

    f32 hw = width * 0.5f;
    f32 hh = height * 0.5f;

    // Generate segments along the beam with parabolic deflection
    for (u32 i = 0; i <= segments; ++i) {
        f32 t = static_cast<f32>(i) / static_cast<f32>(segments);
        vec3 pos = start + dir * (length * t);

        // Parabolic deflection: max at center, zero at ends
        f32 deflectionFactor = 4.0f * t * (1.0f - t);  // Parabola
        pos -= localUp * (deflection * deflectionFactor);

        // Add 4 vertices for this cross-section
        vertices.push_back({pos - right * hw - localUp * hh, -localUp, color});
        vertices.push_back({pos + right * hw - localUp * hh, -localUp, color});
        vertices.push_back({pos + right * hw + localUp * hh, localUp, color});
        vertices.push_back({pos - right * hw + localUp * hh, localUp, color});
    }

    // Generate indices for the segments
    for (u32 i = 0; i < segments; ++i) {
        u32 base = i * 4;

        // Bottom face
        indices.push_back(base + 0); indices.push_back(base + 4); indices.push_back(base + 5);
        indices.push_back(base + 0); indices.push_back(base + 5); indices.push_back(base + 1);

        // Right face
        indices.push_back(base + 1); indices.push_back(base + 5); indices.push_back(base + 6);
        indices.push_back(base + 1); indices.push_back(base + 6); indices.push_back(base + 2);

        // Top face
        indices.push_back(base + 2); indices.push_back(base + 6); indices.push_back(base + 7);
        indices.push_back(base + 2); indices.push_back(base + 7); indices.push_back(base + 3);

        // Left face
        indices.push_back(base + 3); indices.push_back(base + 7); indices.push_back(base + 4);
        indices.push_back(base + 3); indices.push_back(base + 4); indices.push_back(base + 0);
    }

    // End caps
    // Start cap
    u32 startBase = static_cast<u32>(vertices.size());
    vec3 startCenter = start;
    vertices.push_back({start - right * hw - localUp * hh, -dir, color});
    vertices.push_back({start + right * hw - localUp * hh, -dir, color});
    vertices.push_back({start + right * hw + localUp * hh, -dir, color});
    vertices.push_back({start - right * hw + localUp * hh, -dir, color});
    indices.push_back(startBase + 0); indices.push_back(startBase + 2); indices.push_back(startBase + 1);
    indices.push_back(startBase + 0); indices.push_back(startBase + 3); indices.push_back(startBase + 2);

    // End cap
    u32 endBase = static_cast<u32>(vertices.size());
    vertices.push_back({end - right * hw - localUp * hh, dir, color});
    vertices.push_back({end + right * hw - localUp * hh, dir, color});
    vertices.push_back({end + right * hw + localUp * hh, dir, color});
    vertices.push_back({end - right * hw + localUp * hh, dir, color});
    indices.push_back(endBase + 0); indices.push_back(endBase + 1); indices.push_back(endBase + 2);
    indices.push_back(endBase + 0); indices.push_back(endBase + 2); indices.push_back(endBase + 3);

    return {vertices, indices};
}

std::pair<std::vector<Vertex>, std::vector<u32>>
createGrid(f32 size, f32 spacing, vec3 color) {
    std::vector<Vertex> vertices;
    std::vector<u32> indices;

    f32 halfSize = size * 0.5f;
    i32 lineCount = static_cast<i32>(size / spacing) + 1;

    vec3 normal(0, 1, 0);

    // Lines along X axis (slightly below Y=0 to avoid Z-fighting with floor)
    const f32 gridY = -0.05f;
    for (i32 i = 0; i < lineCount; ++i) {
        f32 z = -halfSize + i * spacing;
        u32 baseIndex = static_cast<u32>(vertices.size());

        vertices.push_back({{-halfSize, gridY, z}, normal, color});
        vertices.push_back({{halfSize, gridY, z}, normal, color});

        // Create thin quad for line
        vertices.push_back({{-halfSize, gridY + 0.01f, z}, normal, color});
        vertices.push_back({{halfSize, gridY + 0.01f, z}, normal, color});

        indices.push_back(baseIndex + 0);
        indices.push_back(baseIndex + 1);
        indices.push_back(baseIndex + 3);
        indices.push_back(baseIndex + 0);
        indices.push_back(baseIndex + 3);
        indices.push_back(baseIndex + 2);
    }

    // Lines along Z axis
    for (i32 i = 0; i < lineCount; ++i) {
        f32 x = -halfSize + i * spacing;
        u32 baseIndex = static_cast<u32>(vertices.size());

        vertices.push_back({{x, gridY, -halfSize}, normal, color});
        vertices.push_back({{x, gridY, halfSize}, normal, color});

        vertices.push_back({{x, gridY + 0.01f, -halfSize}, normal, color});
        vertices.push_back({{x, gridY + 0.01f, halfSize}, normal, color});

        indices.push_back(baseIndex + 0);
        indices.push_back(baseIndex + 1);
        indices.push_back(baseIndex + 3);
        indices.push_back(baseIndex + 0);
        indices.push_back(baseIndex + 3);
        indices.push_back(baseIndex + 2);
    }

    return {vertices, indices};
}

std::pair<std::vector<Vertex>, std::vector<u32>>
createSphere(f32 radius, u32 rings, u32 sectors, vec3 color) {
    std::vector<Vertex> vertices;
    std::vector<u32> indices;

    const f32 PI = 3.14159265359f;

    // Generate vertices
    for (u32 r = 0; r <= rings; ++r) {
        f32 theta = static_cast<f32>(r) / static_cast<f32>(rings) * PI;  // 0 to PI
        f32 sinTheta = std::sin(theta);
        f32 cosTheta = std::cos(theta);

        for (u32 s = 0; s <= sectors; ++s) {
            f32 phi = static_cast<f32>(s) / static_cast<f32>(sectors) * 2.0f * PI;  // 0 to 2PI
            f32 sinPhi = std::sin(phi);
            f32 cosPhi = std::cos(phi);

            // Sphere position
            vec3 pos;
            pos.x = radius * sinTheta * cosPhi;
            pos.y = radius * cosTheta;
            pos.z = radius * sinTheta * sinPhi;

            // Normal is same as position (normalized) for a sphere centered at origin
            vec3 normal = glm::normalize(pos);

            // UV coordinates (equirectangular projection)
            vec2 uv;
            uv.x = static_cast<f32>(s) / static_cast<f32>(sectors);
            uv.y = static_cast<f32>(r) / static_cast<f32>(rings);

            vertices.push_back({pos, normal, color, uv});
        }
    }

    // Generate indices for triangles
    for (u32 r = 0; r < rings; ++r) {
        for (u32 s = 0; s < sectors; ++s) {
            u32 i0 = r * (sectors + 1) + s;
            u32 i1 = i0 + 1;
            u32 i2 = (r + 1) * (sectors + 1) + s;
            u32 i3 = i2 + 1;

            // First triangle
            indices.push_back(i0);
            indices.push_back(i2);
            indices.push_back(i1);

            // Second triangle
            indices.push_back(i1);
            indices.push_back(i2);
            indices.push_back(i3);
        }
    }

    return {vertices, indices};
}

std::pair<std::vector<Vertex>, std::vector<u32>>
createArrow(vec3 start, vec3 end, f32 headSize, vec3 color) {
    std::vector<Vertex> vertices;
    std::vector<u32> indices;

    vec3 dir = glm::normalize(end - start);
    vec3 up = vec3(0, 1, 0);
    if (std::abs(glm::dot(dir, up)) > 0.99f) {
        up = vec3(1, 0, 0);
    }

    vec3 right = glm::normalize(glm::cross(dir, up));
    vec3 localUp = glm::normalize(glm::cross(right, dir));

    f32 shaftRadius = headSize * 0.15f;
    vec3 headBase = end - dir * headSize;

    // Shaft (simplified as box)
    auto [shaftVerts, shaftIndices] = createBeam(start, headBase, shaftRadius * 2, shaftRadius * 2, color);
    vertices = shaftVerts;
    indices = shaftIndices;

    // Arrow head (cone approximation with 6 sides)
    u32 baseIndex = static_cast<u32>(vertices.size());
    u32 coneSegments = 6;

    // Tip vertex
    vertices.push_back({end, dir, color});

    // Base vertices
    for (u32 i = 0; i < coneSegments; ++i) {
        f32 angle = static_cast<f32>(i) / static_cast<f32>(coneSegments) * 2.0f * 3.14159f;
        vec3 offset = right * cos(angle) * headSize * 0.5f + localUp * sin(angle) * headSize * 0.5f;
        vec3 pos = headBase + offset;
        vec3 normal = glm::normalize(offset + dir * 0.5f);
        vertices.push_back({pos, normal, color});
    }

    // Cone faces
    for (u32 i = 0; i < coneSegments; ++i) {
        u32 next = (i + 1) % coneSegments;
        indices.push_back(baseIndex);  // Tip
        indices.push_back(baseIndex + 1 + i);
        indices.push_back(baseIndex + 1 + next);
    }

    // Base cap
    u32 centerIndex = static_cast<u32>(vertices.size());
    vertices.push_back({headBase, -dir, color});
    for (u32 i = 0; i < coneSegments; ++i) {
        u32 next = (i + 1) % coneSegments;
        indices.push_back(centerIndex);
        indices.push_back(baseIndex + 1 + next);
        indices.push_back(baseIndex + 1 + i);
    }

    return {vertices, indices};
}

void applyStressColoring(std::vector<Vertex>& vertices, f32 stress) {
    vec3 color = StressColors::fromStress(stress);
    for (auto& vertex : vertices) {
        vertex.color = color;
    }
}

std::pair<std::vector<Vertex>, std::vector<u32>>
createDoor(vec3 position, f32 width, f32 height, f32 depth, vec3 color) {
    // Door with frame, panels, and handle
    std::vector<Vertex> vertices;
    std::vector<u32> indices;

    f32 hw = width * 0.5f;
    f32 hd = depth * 0.5f;

    // Colors for different parts
    vec3 frameColor = vec3(0.35f, 0.22f, 0.12f);  // Dark wood frame
    vec3 panelColor = color;                       // Door panel color (passed in)
    vec3 handleColor = vec3(0.7f, 0.55f, 0.2f);   // Brass/gold handle

    // Frame dimensions
    f32 frameWidth = 0.25f;  // Width of frame trim
    f32 frameDepth = depth * 0.3f;  // Frame protrudes slightly

    // Helper to add a box
    auto addBox = [&](vec3 minP, vec3 maxP, vec3 boxColor) {
        u32 base = static_cast<u32>(vertices.size());

        // 8 corners
        vec3 c[8] = {
            {minP.x, minP.y, minP.z}, {maxP.x, minP.y, minP.z},
            {maxP.x, minP.y, maxP.z}, {minP.x, minP.y, maxP.z},
            {minP.x, maxP.y, minP.z}, {maxP.x, maxP.y, minP.z},
            {maxP.x, maxP.y, maxP.z}, {minP.x, maxP.y, maxP.z}
        };

        auto addFace = [&](int i0, int i1, int i2, int i3, vec3 n) {
            u32 b = static_cast<u32>(vertices.size());
            vertices.push_back({c[i0], n, boxColor});
            vertices.push_back({c[i1], n, boxColor});
            vertices.push_back({c[i2], n, boxColor});
            vertices.push_back({c[i3], n, boxColor});
            indices.insert(indices.end(), {b, b+1, b+2, b, b+2, b+3});
        };

        addFace(0, 1, 5, 4, vec3(0, 0, -1));  // Front
        addFace(2, 3, 7, 6, vec3(0, 0, 1));   // Back
        addFace(3, 0, 4, 7, vec3(-1, 0, 0));  // Left
        addFace(1, 2, 6, 5, vec3(1, 0, 0));   // Right
        addFace(4, 5, 6, 7, vec3(0, 1, 0));   // Top
        addFace(3, 2, 1, 0, vec3(0, -1, 0));  // Bottom
    };

    // Door frame - left vertical
    addBox(position + vec3(-hw, 0, -hd),
           position + vec3(-hw + frameWidth, height, hd),
           frameColor);

    // Door frame - right vertical
    addBox(position + vec3(hw - frameWidth, 0, -hd),
           position + vec3(hw, height, hd),
           frameColor);

    // Door frame - top horizontal
    addBox(position + vec3(-hw + frameWidth, height - frameWidth, -hd),
           position + vec3(hw - frameWidth, height, hd),
           frameColor);

    // Main door panel (recessed slightly)
    f32 panelInset = frameWidth * 0.5f;
    addBox(position + vec3(-hw + frameWidth, 0, -hd + panelInset),
           position + vec3(hw - frameWidth, height - frameWidth, hd - panelInset),
           panelColor);

    // Door handle (right side, at typical handle height ~3ft)
    f32 handleHeight = 3.0f;  // 3 feet from ground
    f32 handleSize = 0.15f;
    if (handleHeight < height - frameWidth) {
        addBox(position + vec3(hw - frameWidth - 0.4f, handleHeight - handleSize, hd - 0.1f),
               position + vec3(hw - frameWidth - 0.1f, handleHeight + handleSize, hd + 0.15f),
               handleColor);
    }

    return {vertices, indices};
}

std::pair<std::vector<Vertex>, std::vector<u32>>
createWindow(vec3 position, f32 width, f32 height, f32 depth, vec3 color) {
    // Window with frame, glass panel, and mullions
    std::vector<Vertex> vertices;
    std::vector<u32> indices;

    f32 hw = width * 0.5f;
    f32 hd = depth * 0.5f;

    // Colors for different parts
    vec3 frameColor = vec3(0.9f, 0.9f, 0.92f);  // White painted frame
    vec3 glassColor = vec3(0.7f, 0.85f, 0.95f); // Light blue tinted glass
    vec3 sillColor = vec3(0.85f, 0.85f, 0.87f); // Slightly darker sill

    // Frame dimensions
    f32 frameWidth = 0.15f;  // Width of frame trim
    f32 mullionWidth = 0.08f; // Width of mullion dividers

    // Helper to add a box
    auto addBox = [&](vec3 minP, vec3 maxP, vec3 boxColor) {
        u32 base = static_cast<u32>(vertices.size());

        vec3 c[8] = {
            {minP.x, minP.y, minP.z}, {maxP.x, minP.y, minP.z},
            {maxP.x, minP.y, maxP.z}, {minP.x, minP.y, maxP.z},
            {minP.x, maxP.y, minP.z}, {maxP.x, maxP.y, minP.z},
            {maxP.x, maxP.y, maxP.z}, {minP.x, maxP.y, maxP.z}
        };

        auto addFace = [&](int i0, int i1, int i2, int i3, vec3 n) {
            u32 b = static_cast<u32>(vertices.size());
            vertices.push_back({c[i0], n, boxColor});
            vertices.push_back({c[i1], n, boxColor});
            vertices.push_back({c[i2], n, boxColor});
            vertices.push_back({c[i3], n, boxColor});
            indices.insert(indices.end(), {b, b+1, b+2, b, b+2, b+3});
        };

        addFace(0, 1, 5, 4, vec3(0, 0, -1));  // Front
        addFace(2, 3, 7, 6, vec3(0, 0, 1));   // Back
        addFace(3, 0, 4, 7, vec3(-1, 0, 0));  // Left
        addFace(1, 2, 6, 5, vec3(1, 0, 0));   // Right
        addFace(4, 5, 6, 7, vec3(0, 1, 0));   // Top
        addFace(3, 2, 1, 0, vec3(0, -1, 0));  // Bottom
    };

    // Window frame - left vertical
    addBox(position + vec3(-hw, 0, -hd),
           position + vec3(-hw + frameWidth, height, hd),
           frameColor);

    // Window frame - right vertical
    addBox(position + vec3(hw - frameWidth, 0, -hd),
           position + vec3(hw, height, hd),
           frameColor);

    // Window frame - top horizontal
    addBox(position + vec3(-hw + frameWidth, height - frameWidth, -hd),
           position + vec3(hw - frameWidth, height, hd),
           frameColor);

    // Window sill - bottom horizontal (slightly thicker and protruding)
    f32 sillProtrusion = 0.1f;
    addBox(position + vec3(-hw - sillProtrusion, 0, -hd - sillProtrusion),
           position + vec3(hw + sillProtrusion, frameWidth * 1.2f, hd),
           sillColor);

    // Glass pane (thin, recessed slightly)
    f32 glassInset = depth * 0.3f;
    addBox(position + vec3(-hw + frameWidth, frameWidth * 1.2f, -glassInset),
           position + vec3(hw - frameWidth, height - frameWidth, glassInset),
           glassColor);

    // Add mullions (cross dividers) for classic window look
    f32 innerWidth = width - 2.0f * frameWidth;
    f32 innerHeight = height - frameWidth - frameWidth * 1.2f;

    // Horizontal mullion (middle)
    f32 midHeight = frameWidth * 1.2f + innerHeight * 0.5f;
    addBox(position + vec3(-hw + frameWidth, midHeight - mullionWidth * 0.5f, -hd * 0.5f),
           position + vec3(hw - frameWidth, midHeight + mullionWidth * 0.5f, hd * 0.5f),
           frameColor);

    // Vertical mullion (middle)
    addBox(position + vec3(-mullionWidth * 0.5f, frameWidth * 1.2f, -hd * 0.5f),
           position + vec3(mullionWidth * 0.5f, height - frameWidth, hd * 0.5f),
           frameColor);

    return {vertices, indices};
}

std::pair<std::vector<Vertex>, std::vector<u32>>
createRoof(vec3 position, f32 width, f32 depth, f32 height, f32 pitch, vec3 color) {
    std::vector<Vertex> vertices;
    std::vector<u32> indices;

    // Add overhang (eaves)
    f32 overhang = 2.0f;  // 2ft overhang
    f32 hw = (width * 0.5f) + overhang;
    f32 hd = (depth * 0.5f) + overhang;

    if (pitch <= 0.01f) {
        // Flat roof with overhang
        vec3 corners[8] = {
            position + vec3(-hw, 0, -hd),
            position + vec3(hw, 0, -hd),
            position + vec3(hw, 0, hd),
            position + vec3(-hw, 0, hd),
            position + vec3(-hw, height, -hd),
            position + vec3(hw, height, -hd),
            position + vec3(hw, height, hd),
            position + vec3(-hw, height, hd),
        };

        auto addFace = [&](u32 i0, u32 i1, u32 i2, u32 i3, vec3 normal) {
            u32 baseIndex = static_cast<u32>(vertices.size());
            vertices.push_back({corners[i0], normal, color});
            vertices.push_back({corners[i1], normal, color});
            vertices.push_back({corners[i2], normal, color});
            vertices.push_back({corners[i3], normal, color});
            indices.push_back(baseIndex + 0);
            indices.push_back(baseIndex + 1);
            indices.push_back(baseIndex + 2);
            indices.push_back(baseIndex + 0);
            indices.push_back(baseIndex + 2);
            indices.push_back(baseIndex + 3);
        };

        addFace(0, 1, 5, 4, vec3(0, 0, -1));
        addFace(2, 3, 7, 6, vec3(0, 0, 1));
        addFace(3, 0, 4, 7, vec3(-1, 0, 0));
        addFace(1, 2, 6, 5, vec3(1, 0, 0));
        addFace(4, 5, 6, 7, vec3(0, 1, 0));
        addFace(3, 2, 1, 0, vec3(0, -1, 0));
    } else {
        // Hip roof (4 sloped sides) with overhang
        f32 ridgeHeight = height + pitch * std::min(hw, hd);

        // Base corners (at eaves level, with overhang)
        vec3 p0 = position + vec3(-hw, 0, -hd);  // back-left
        vec3 p1 = position + vec3(hw, 0, -hd);   // back-right
        vec3 p2 = position + vec3(hw, 0, hd);    // front-right
        vec3 p3 = position + vec3(-hw, 0, hd);   // front-left

        // Ridge line (shorter than base, centered)
        f32 ridgeLen = std::max(0.0f, (width - depth) * 0.5f);
        vec3 r0 = position + vec3(-ridgeLen, ridgeHeight, 0);  // ridge left
        vec3 r1 = position + vec3(ridgeLen, ridgeHeight, 0);   // ridge right

        // If building is roughly square, ridge becomes a point (pyramid)
        if (ridgeLen < 1.0f) {
            // Pyramid roof (4 triangular faces meeting at apex)
            vec3 apex = position + vec3(0, ridgeHeight, 0);

            // Front slope
            vec3 frontNormal = glm::normalize(glm::cross(p2 - p3, apex - p3));
            u32 base = static_cast<u32>(vertices.size());
            vertices.push_back({p3, frontNormal, color});
            vertices.push_back({p2, frontNormal, color});
            vertices.push_back({apex, frontNormal, color});
            indices.push_back(base + 0); indices.push_back(base + 1); indices.push_back(base + 2);

            // Right slope
            vec3 rightNormal = glm::normalize(glm::cross(p1 - p2, apex - p2));
            base = static_cast<u32>(vertices.size());
            vertices.push_back({p2, rightNormal, color});
            vertices.push_back({p1, rightNormal, color});
            vertices.push_back({apex, rightNormal, color});
            indices.push_back(base + 0); indices.push_back(base + 1); indices.push_back(base + 2);

            // Back slope
            vec3 backNormal = glm::normalize(glm::cross(p0 - p1, apex - p1));
            base = static_cast<u32>(vertices.size());
            vertices.push_back({p1, backNormal, color});
            vertices.push_back({p0, backNormal, color});
            vertices.push_back({apex, backNormal, color});
            indices.push_back(base + 0); indices.push_back(base + 1); indices.push_back(base + 2);

            // Left slope
            vec3 leftNormal = glm::normalize(glm::cross(p3 - p0, apex - p0));
            base = static_cast<u32>(vertices.size());
            vertices.push_back({p0, leftNormal, color});
            vertices.push_back({p3, leftNormal, color});
            vertices.push_back({apex, leftNormal, color});
            indices.push_back(base + 0); indices.push_back(base + 1); indices.push_back(base + 2);
        } else {
            // Hip roof with ridge line
            // Front slope (trapezoid)
            vec3 frontNormal = glm::normalize(glm::cross(p2 - p3, r0 - p3));
            u32 base = static_cast<u32>(vertices.size());
            vertices.push_back({p3, frontNormal, color});
            vertices.push_back({p2, frontNormal, color});
            vertices.push_back({r1, frontNormal, color});
            vertices.push_back({r0, frontNormal, color});
            indices.push_back(base + 0); indices.push_back(base + 1); indices.push_back(base + 2);
            indices.push_back(base + 0); indices.push_back(base + 2); indices.push_back(base + 3);

            // Back slope (trapezoid)
            vec3 backNormal = glm::normalize(glm::cross(p0 - p1, r1 - p1));
            base = static_cast<u32>(vertices.size());
            vertices.push_back({p1, backNormal, color});
            vertices.push_back({p0, backNormal, color});
            vertices.push_back({r0, backNormal, color});
            vertices.push_back({r1, backNormal, color});
            indices.push_back(base + 0); indices.push_back(base + 1); indices.push_back(base + 2);
            indices.push_back(base + 0); indices.push_back(base + 2); indices.push_back(base + 3);

            // Right hip (triangle)
            vec3 rightNormal = glm::normalize(glm::cross(p1 - p2, r1 - p2));
            base = static_cast<u32>(vertices.size());
            vertices.push_back({p2, rightNormal, color});
            vertices.push_back({p1, rightNormal, color});
            vertices.push_back({r1, rightNormal, color});
            indices.push_back(base + 0); indices.push_back(base + 1); indices.push_back(base + 2);

            // Left hip (triangle)
            vec3 leftNormal = glm::normalize(glm::cross(p3 - p0, r0 - p0));
            base = static_cast<u32>(vertices.size());
            vertices.push_back({p0, leftNormal, color});
            vertices.push_back({p3, leftNormal, color});
            vertices.push_back({r0, leftNormal, color});
            indices.push_back(base + 0); indices.push_back(base + 1); indices.push_back(base + 2);
        }
    }

    return {vertices, indices};
}


std::pair<std::vector<Vertex>, std::vector<u32>>
createGableRoof(vec3 position, f32 width, f32 depth, f32 wallHeight, f32 pitch,
                f32 overhang, vec3 color) {
    std::vector<Vertex> vertices;
    std::vector<u32> indices;

    f32 hw = (width * 0.5f) + overhang;
    f32 hd = (depth * 0.5f) + overhang;
    f32 ridgeHeight = wallHeight + pitch * (width * 0.5f);

    vec3 p0 = position + vec3(-hw, wallHeight, -hd);
    vec3 p1 = position + vec3(hw, wallHeight, -hd);
    vec3 p2 = position + vec3(hw, wallHeight, hd);
    vec3 p3 = position + vec3(-hw, wallHeight, hd);
    vec3 r0 = position + vec3(0, ridgeHeight, -hd);
    vec3 r1 = position + vec3(0, ridgeHeight, hd);

    vec3 leftNormal = glm::normalize(glm::cross(p3 - p0, r0 - p0));
    u32 base = static_cast<u32>(vertices.size());
    vertices.push_back({p0, leftNormal, color});
    vertices.push_back({p3, leftNormal, color});
    vertices.push_back({r1, leftNormal, color});
    vertices.push_back({r0, leftNormal, color});
    indices.push_back(base + 0); indices.push_back(base + 1); indices.push_back(base + 2);
    indices.push_back(base + 0); indices.push_back(base + 2); indices.push_back(base + 3);

    vec3 rightNormal = glm::normalize(glm::cross(r0 - p1, p2 - p1));
    base = static_cast<u32>(vertices.size());
    vertices.push_back({p1, rightNormal, color});
    vertices.push_back({r0, rightNormal, color});
    vertices.push_back({r1, rightNormal, color});
    vertices.push_back({p2, rightNormal, color});
    indices.push_back(base + 0); indices.push_back(base + 1); indices.push_back(base + 2);
    indices.push_back(base + 0); indices.push_back(base + 2); indices.push_back(base + 3);

    return {vertices, indices};
}

std::pair<std::vector<Vertex>, std::vector<u32>>
createGableWall(vec3 position, f32 width, f32 wallHeight, f32 gableHeight, f32 thickness,
                vec3 color) {
    std::vector<Vertex> vertices;
    std::vector<u32> indices;

    f32 hw = width * 0.5f;
    f32 ht = thickness * 0.5f;

    vec3 p0 = position + vec3(-hw, 0, 0);
    vec3 p1 = position + vec3(hw, 0, 0);
    vec3 p2 = position + vec3(hw, wallHeight, 0);
    vec3 p3 = position + vec3(0, wallHeight + gableHeight, 0);
    vec3 p4 = position + vec3(-hw, wallHeight, 0);

    // Front pentagon
    u32 base = static_cast<u32>(vertices.size());
    vertices.push_back({p0 + vec3(0,0,ht), vec3(0,0,1), color});
    vertices.push_back({p1 + vec3(0,0,ht), vec3(0,0,1), color});
    vertices.push_back({p2 + vec3(0,0,ht), vec3(0,0,1), color});
    vertices.push_back({p3 + vec3(0,0,ht), vec3(0,0,1), color});
    vertices.push_back({p4 + vec3(0,0,ht), vec3(0,0,1), color});
    indices.push_back(base+0); indices.push_back(base+1); indices.push_back(base+2);
    indices.push_back(base+0); indices.push_back(base+2); indices.push_back(base+3);
    indices.push_back(base+0); indices.push_back(base+3); indices.push_back(base+4);

    // Back pentagon
    base = static_cast<u32>(vertices.size());
    vertices.push_back({p0 + vec3(0,0,-ht), vec3(0,0,-1), color});
    vertices.push_back({p4 + vec3(0,0,-ht), vec3(0,0,-1), color});
    vertices.push_back({p3 + vec3(0,0,-ht), vec3(0,0,-1), color});
    vertices.push_back({p2 + vec3(0,0,-ht), vec3(0,0,-1), color});
    vertices.push_back({p1 + vec3(0,0,-ht), vec3(0,0,-1), color});
    indices.push_back(base+0); indices.push_back(base+1); indices.push_back(base+2);
    indices.push_back(base+0); indices.push_back(base+2); indices.push_back(base+3);
    indices.push_back(base+0); indices.push_back(base+3); indices.push_back(base+4);

    return {vertices, indices};
}

namespace CSG {

std::pair<std::vector<Vertex>, std::vector<u32>>
meshUnion(const std::pair<std::vector<Vertex>, std::vector<u32>>& a,
          const std::pair<std::vector<Vertex>, std::vector<u32>>& b) {
    std::vector<Vertex> vertices = a.first;
    std::vector<u32> indices = a.second;
    u32 offset = static_cast<u32>(vertices.size());
    vertices.insert(vertices.end(), b.first.begin(), b.first.end());
    for (u32 idx : b.second) {
        indices.push_back(idx + offset);
    }
    return {vertices, indices};
}

std::pair<std::vector<Vertex>, std::vector<u32>>
wallWithOpening(vec3 wallStart, vec3 wallEnd, f32 wallHeight, f32 thickness,
                vec3 openingPos, f32 openingWidth, f32 openingHeight, vec3 color) {
    // Creates a wall with a rectangular opening (door/window cutout)
    // Wall aligned to wallStart->wallEnd direction
    // openingPos.x = offset along wall from start, openingPos.y = height from floor
    std::vector<Vertex> vertices;
    std::vector<u32> indices;

    vec3 wallDir = wallEnd - wallStart;
    f32 wallLength = glm::length(vec3(wallDir.x, 0.0f, wallDir.z));
    if (wallLength < 0.01f) return {vertices, indices};

    vec3 wallDirNorm = glm::normalize(vec3(wallDir.x, 0.0f, wallDir.z));
    vec3 wallPerp = vec3(-wallDirNorm.z, 0.0f, wallDirNorm.x);  // Perpendicular in XZ
    f32 ht = thickness * 0.5f;

    f32 openLeft = glm::clamp(openingPos.x, 0.0f, wallLength);
    f32 openRight = glm::clamp(openingPos.x + openingWidth, 0.0f, wallLength);
    f32 openBottom = glm::clamp(openingPos.y, 0.0f, wallHeight);
    f32 openTop = glm::clamp(openingPos.y + openingHeight, 0.0f, wallHeight);

    // Helper: add a wall-aligned box segment
    auto addSegment = [&](f32 alongStart, f32 alongEnd, f32 yStart, f32 yEnd) {
        if (alongEnd <= alongStart || yEnd <= yStart) return;

        // 8 corners of the box
        vec3 corners[8];
        for (int i = 0; i < 8; i++) {
            f32 along = (i & 1) ? alongEnd : alongStart;
            f32 y = (i & 2) ? yEnd : yStart;
            f32 perp = (i & 4) ? ht : -ht;
            corners[i] = wallStart + wallDirNorm * along + vec3(0, y, 0) + wallPerp * perp;
        }

        u32 base = static_cast<u32>(vertices.size());

        // Add 6 faces (each face: 4 verts, 2 triangles)
        auto addFace = [&](int i0, int i1, int i2, int i3, vec3 normal) {
            u32 b = static_cast<u32>(vertices.size());
            vertices.push_back({corners[i0], normal, color});
            vertices.push_back({corners[i1], normal, color});
            vertices.push_back({corners[i2], normal, color});
            vertices.push_back({corners[i3], normal, color});
            indices.insert(indices.end(), {b, b+1, b+2, b, b+2, b+3});
        };

        // Front face (positive perp direction)
        addFace(4, 5, 7, 6, wallPerp);
        // Back face (negative perp direction)
        addFace(1, 0, 2, 3, -wallPerp);
        // Top face
        addFace(2, 6, 7, 3, vec3(0, 1, 0));
        // Bottom face
        addFace(0, 1, 5, 4, vec3(0, -1, 0));
        // Left face (toward wallStart)
        addFace(0, 4, 6, 2, -wallDirNorm);
        // Right face (toward wallEnd)
        addFace(5, 1, 3, 7, wallDirNorm);
    };

    // Create 4 segments around the opening:
    // 1. Bottom strip (full width, floor to opening bottom)
    if (openBottom > 0.01f) {
        addSegment(0.0f, wallLength, 0.0f, openBottom);
    }
    // 2. Top strip (full width, opening top to ceiling)
    if (openTop < wallHeight - 0.01f) {
        addSegment(0.0f, wallLength, openTop, wallHeight);
    }
    // 3. Left strip (start to opening left, at opening height)
    if (openLeft > 0.01f) {
        addSegment(0.0f, openLeft, openBottom, openTop);
    }
    // 4. Right strip (opening right to end, at opening height)
    if (openRight < wallLength - 0.01f) {
        addSegment(openRight, wallLength, openBottom, openTop);
    }

    return {vertices, indices};
}


std::pair<std::vector<Vertex>, std::vector<u32>>
wallWithMultipleOpenings(vec3 wallStart, vec3 wallEnd, f32 wallHeight, f32 thickness,
                         const std::vector<std::array<f32, 4>>& openings, vec3 color) {
    // openings: vector of {offset, width, bottom, height}
    // Creates wall with multiple rectangular cutouts
    std::vector<Vertex> vertices;
    std::vector<u32> indices;

    vec3 wallDir = wallEnd - wallStart;
    f32 wallLength = glm::length(vec3(wallDir.x, 0.0f, wallDir.z));
    if (wallLength < 0.01f) return {vertices, indices};

    vec3 wallDirNorm = glm::normalize(vec3(wallDir.x, 0.0f, wallDir.z));
    vec3 wallPerp = vec3(-wallDirNorm.z, 0.0f, wallDirNorm.x);
    f32 ht = thickness * 0.5f;

    // Helper: add a wall-aligned box segment
    auto addSegment = [&](f32 alongStart, f32 alongEnd, f32 yStart, f32 yEnd) {
        if (alongEnd <= alongStart + 0.01f || yEnd <= yStart + 0.01f) return;

        vec3 corners[8];
        for (int i = 0; i < 8; i++) {
            f32 along = (i & 1) ? alongEnd : alongStart;
            f32 y = (i & 2) ? yEnd : yStart;
            f32 perp = (i & 4) ? ht : -ht;
            corners[i] = wallStart + wallDirNorm * along + vec3(0, y, 0) + wallPerp * perp;
        }

        auto addFace = [&](int i0, int i1, int i2, int i3, vec3 normal) {
            u32 b = static_cast<u32>(vertices.size());
            vertices.push_back({corners[i0], normal, color});
            vertices.push_back({corners[i1], normal, color});
            vertices.push_back({corners[i2], normal, color});
            vertices.push_back({corners[i3], normal, color});
            indices.insert(indices.end(), {b, b+1, b+2, b, b+2, b+3});
        };

        addFace(4, 5, 7, 6, wallPerp);
        addFace(1, 0, 2, 3, -wallPerp);
        addFace(2, 6, 7, 3, vec3(0, 1, 0));
        addFace(0, 1, 5, 4, vec3(0, -1, 0));
        addFace(0, 4, 6, 2, -wallDirNorm);
        addFace(5, 1, 3, 7, wallDirNorm);
    };

    if (openings.empty()) {
        // No openings - solid wall
        addSegment(0.0f, wallLength, 0.0f, wallHeight);
        return {vertices, indices};
    }

    // Sort openings by offset
    auto sorted = openings;
    std::sort(sorted.begin(), sorted.end(), [](const auto& a, const auto& b) {
        return a[0] < b[0];
    });

    // Create vertical columns separated by openings
    std::vector<f32> xBoundaries = {0.0f};
    for (const auto& op : sorted) {
        f32 left = glm::clamp(op[0], 0.0f, wallLength);
        f32 right = glm::clamp(op[0] + op[1], 0.0f, wallLength);
        xBoundaries.push_back(left);
        xBoundaries.push_back(right);
    }
    xBoundaries.push_back(wallLength);

    // Remove duplicates and sort
    std::sort(xBoundaries.begin(), xBoundaries.end());
    xBoundaries.erase(std::unique(xBoundaries.begin(), xBoundaries.end()), xBoundaries.end());

    // For each column, determine what segments to create
    for (size_t i = 0; i + 1 < xBoundaries.size(); i++) {
        f32 colLeft = xBoundaries[i];
        f32 colRight = xBoundaries[i + 1];
        f32 colMid = (colLeft + colRight) * 0.5f;

        // Find openings that overlap this column
        std::vector<std::pair<f32, f32>> yGaps;  // {bottom, top} of openings in this column
        for (const auto& op : sorted) {
            f32 opLeft = glm::clamp(op[0], 0.0f, wallLength);
            f32 opRight = glm::clamp(op[0] + op[1], 0.0f, wallLength);
            if (opLeft < colRight && opRight > colLeft) {
                // Opening overlaps this column
                f32 opBottom = glm::clamp(op[2], 0.0f, wallHeight);
                f32 opTop = glm::clamp(op[2] + op[3], 0.0f, wallHeight);
                yGaps.push_back({opBottom, opTop});
            }
        }

        if (yGaps.empty()) {
            // No openings in this column - full height wall
            addSegment(colLeft, colRight, 0.0f, wallHeight);
        } else {
            // Sort gaps by bottom
            std::sort(yGaps.begin(), yGaps.end());

            // Create segments around gaps
            f32 currentY = 0.0f;
            for (const auto& gap : yGaps) {
                if (gap.first > currentY) {
                    addSegment(colLeft, colRight, currentY, gap.first);
                }
                currentY = std::max(currentY, gap.second);
            }
            if (currentY < wallHeight) {
                addSegment(colLeft, colRight, currentY, wallHeight);
            }
        }
    }

    return {vertices, indices};
}

} // namespace CSG

} // namespace Geometry
} // namespace arch
