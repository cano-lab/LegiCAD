#pragma once

#include "types.hpp"
#include "vulkan_context.hpp"

namespace arch {

class Mesh {
public:
    Mesh(VulkanContext& context, const std::vector<Vertex>& vertices,
         const std::vector<u32>& indices);
    ~Mesh();

    // Non-copyable, movable
    Mesh(const Mesh&) = delete;
    Mesh& operator=(const Mesh&) = delete;
    Mesh(Mesh&& other) noexcept;
    Mesh& operator=(Mesh&& other) noexcept;

    void bind(VkCommandBuffer commandBuffer);
    void draw(VkCommandBuffer commandBuffer);
    void drawInstanced(VkCommandBuffer commandBuffer, u32 instanceCount);

    u32 getVertexCount() const { return m_vertexCount; }
    u32 getIndexCount() const { return m_indexCount; }

private:
    void createVertexBuffer(const std::vector<Vertex>& vertices);
    void createIndexBuffer(const std::vector<u32>& indices);

    VulkanContext& m_context;

    VkBuffer m_vertexBuffer = VK_NULL_HANDLE;
    VkDeviceMemory m_vertexBufferMemory = VK_NULL_HANDLE;
    VkBuffer m_indexBuffer = VK_NULL_HANDLE;
    VkDeviceMemory m_indexBufferMemory = VK_NULL_HANDLE;

    u32 m_vertexCount = 0;
    u32 m_indexCount = 0;
};

// Geometry generators for structural elements
namespace Geometry {

// Generate beam mesh (box along axis)
std::pair<std::vector<Vertex>, std::vector<u32>>
createBeam(vec3 start, vec3 end, f32 width, f32 height, vec3 color = {0.7f, 0.7f, 0.7f});

// Generate column mesh (vertical box)
std::pair<std::vector<Vertex>, std::vector<u32>>
createColumn(vec3 position, f32 width, f32 depth, f32 height, vec3 color = {0.6f, 0.6f, 0.6f});

// Generate floor slab mesh
std::pair<std::vector<Vertex>, std::vector<u32>>
createFloorSlab(vec3 position, f32 width, f32 depth, f32 thickness, vec3 color = {0.5f, 0.5f, 0.5f});

// Generate deflected beam (curved due to load)
std::pair<std::vector<Vertex>, std::vector<u32>>
createDeflectedBeam(vec3 start, vec3 end, f32 width, f32 height,
                    f32 deflection, u32 segments = 16, vec3 color = {0.7f, 0.7f, 0.7f});

// Generate grid lines (for reference)
std::pair<std::vector<Vertex>, std::vector<u32>>
createGrid(f32 size, f32 spacing, vec3 color = {0.3f, 0.3f, 0.3f});

// Generate sphere mesh (for material previews)
std::pair<std::vector<Vertex>, std::vector<u32>>
createSphere(f32 radius = 1.0f, u32 rings = 24, u32 sectors = 48, vec3 color = {1.0f, 1.0f, 1.0f});

// Generate arrow (for load visualization)
std::pair<std::vector<Vertex>, std::vector<u32>>
createArrow(vec3 start, vec3 end, f32 headSize = 0.3f, vec3 color = {1.0f, 0.5f, 0.0f});

// Apply stress coloring to vertices
void applyStressColoring(std::vector<Vertex>& vertices, f32 stress);

// Generate door mesh (rectangle with frame cutout)
std::pair<std::vector<Vertex>, std::vector<u32>>
createDoor(vec3 position, f32 width, f32 height, f32 depth, vec3 color = {0.55f, 0.35f, 0.15f});

// Generate window mesh (rectangle with glass panel)
std::pair<std::vector<Vertex>, std::vector<u32>>
createWindow(vec3 position, f32 width, f32 height, f32 depth, vec3 color = {0.6f, 0.8f, 0.9f});

// Generate roof mesh (flat or pitched hip roof)
std::pair<std::vector<Vertex>, std::vector<u32>>
createRoof(vec3 position, f32 width, f32 depth, f32 height, f32 pitch = 0.0f, vec3 color = {0.4f, 0.35f, 0.35f});

// Generate gable roof (2 sloped planes meeting at ridge)
std::pair<std::vector<Vertex>, std::vector<u32>>
createGableRoof(vec3 position, f32 width, f32 depth, f32 wallHeight, f32 pitch,
                f32 overhang = 2.0f, vec3 color = {0.4f, 0.35f, 0.35f});

// Generate gable wall (pentagon shape - rectangle with triangular top)
std::pair<std::vector<Vertex>, std::vector<u32>>
createGableWall(vec3 position, f32 width, f32 wallHeight, f32 gableHeight, f32 thickness,
                vec3 color = {0.85f, 0.82f, 0.78f});

// CSG Operations - combine/subtract geometry
namespace CSG {

// Union: Combine two meshes into one
std::pair<std::vector<Vertex>, std::vector<u32>>
meshUnion(const std::pair<std::vector<Vertex>, std::vector<u32>>& a,
          const std::pair<std::vector<Vertex>, std::vector<u32>>& b);

// Create a wall with rectangular opening (door/window cutout)
std::pair<std::vector<Vertex>, std::vector<u32>>
wallWithOpening(vec3 wallStart, vec3 wallEnd, f32 wallHeight, f32 thickness,
                vec3 openingPos, f32 openingWidth, f32 openingHeight,
                vec3 color = {0.85f, 0.82f, 0.78f});
// Create a wall with multiple rectangular openings
std::pair<std::vector<Vertex>, std::vector<u32>>
wallWithMultipleOpenings(vec3 wallStart, vec3 wallEnd, f32 wallHeight, f32 thickness,
                         const std::vector<std::array<f32, 4>>& openings, vec3 color);

} // namespace CSG

} // namespace Geometry

} // namespace arch
