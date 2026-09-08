#pragma once

#include "types.hpp"
#include "vulkan_context.hpp"
#include "mesh.hpp"
#include <unordered_map>

namespace arch {

// ============================================================================
// InstanceBatch - Manages instance data buffer for batched rendering
// ============================================================================
class InstanceBatch {
public:
    explicit InstanceBatch(VulkanContext& context, u32 maxInstances = 10000);
    ~InstanceBatch();

    // Non-copyable
    InstanceBatch(const InstanceBatch&) = delete;
    InstanceBatch& operator=(const InstanceBatch&) = delete;

    // Clear all instances for new frame
    void clear();

    // Add an instance to the batch
    void addInstance(const std::string& meshKey, const InstanceData& instance);

    // Upload instance data to GPU buffer
    void upload();

    // Bind the instance buffer for rendering
    void bind(VkCommandBuffer cmd);

    // Get instance count for a specific mesh
    u32 getInstanceCount(const std::string& meshKey) const;

    // Get the starting instance index for a mesh
    u32 getInstanceOffset(const std::string& meshKey) const;

    // Get all mesh keys that have instances
    std::vector<std::string> getMeshKeys() const;

    // Get total instance count
    u32 getTotalInstances() const { return m_totalInstances; }

    // Get max instances capacity
    u32 getMaxInstances() const { return m_maxInstances; }

private:
    VulkanContext& m_context;
    u32 m_maxInstances;
    u32 m_totalInstances = 0;

    // Instance buffer (GPU)
    VkBuffer m_instanceBuffer = VK_NULL_HANDLE;
    VkDeviceMemory m_instanceBufferMemory = VK_NULL_HANDLE;
    void* m_mappedMemory = nullptr;

    // CPU-side instance data organized by mesh key
    struct MeshBatch {
        std::vector<InstanceData> instances;
        u32 offset = 0;  // Starting index in the combined buffer
    };
    std::unordered_map<std::string, MeshBatch> m_batches;

    // Combined instance data for upload
    std::vector<InstanceData> m_combinedInstances;
};

// ============================================================================
// BatchedRenderer - Helper for organizing draw calls by mesh
// ============================================================================
class BatchedRenderer {
public:
    BatchedRenderer(VulkanContext& context, u32 maxInstances = 10000);

    // Begin a new frame of batched rendering
    void beginFrame();

    // Submit an instance for batched rendering
    void submit(const std::string& meshKey, const mat4& transform, const vec4& color);

    // Flush all batched instances to GPU
    void flush();

    // Execute all batched draw calls
    void render(VkCommandBuffer cmd,
                std::unordered_map<std::string, std::unique_ptr<Mesh>>& meshCache,
                VkPipelineLayout pipelineLayout);

    // Get statistics
    u32 getDrawCallCount() const { return m_drawCallCount; }
    u32 getInstanceCount() const { return m_batch.getTotalInstances(); }

private:
    VulkanContext& m_context;
    InstanceBatch m_batch;
    u32 m_drawCallCount = 0;
    bool m_flushed = false;
};

} // namespace arch
