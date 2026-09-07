#include "instance_batch.hpp"
#include <stdexcept>
#include <cstring>

namespace arch {

// ============================================================================
// InstanceBatch Implementation
// ============================================================================

InstanceBatch::InstanceBatch(VulkanContext& context, u32 maxInstances)
    : m_context(context), m_maxInstances(maxInstances) {

    VkDeviceSize bufferSize = sizeof(InstanceData) * maxInstances;

    // Create a host-visible buffer for instance data
    // Using HOST_VISIBLE for simplicity; could use staging buffer for better performance
    m_context.createBuffer(
        bufferSize,
        VK_BUFFER_USAGE_VERTEX_BUFFER_BIT,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
        m_instanceBuffer,
        m_instanceBufferMemory
    );

    // Keep the buffer mapped for the lifetime of the batch
    vkMapMemory(m_context.getDevice(), m_instanceBufferMemory, 0, bufferSize, 0, &m_mappedMemory);
}

InstanceBatch::~InstanceBatch() {
    if (m_mappedMemory) {
        vkUnmapMemory(m_context.getDevice(), m_instanceBufferMemory);
    }
    if (m_instanceBuffer != VK_NULL_HANDLE) {
        vkDestroyBuffer(m_context.getDevice(), m_instanceBuffer, nullptr);
    }
    if (m_instanceBufferMemory != VK_NULL_HANDLE) {
        vkFreeMemory(m_context.getDevice(), m_instanceBufferMemory, nullptr);
    }
}

void InstanceBatch::clear() {
    m_batches.clear();
    m_combinedInstances.clear();
    m_totalInstances = 0;
}

void InstanceBatch::addInstance(const std::string& meshKey, const InstanceData& instance) {
    if (m_totalInstances >= m_maxInstances) {
        // Buffer full, skip this instance
        return;
    }

    m_batches[meshKey].instances.push_back(instance);
    m_totalInstances++;
}

void InstanceBatch::upload() {
    if (m_totalInstances == 0) return;

    // Combine all instances into a single array, tracking offsets
    m_combinedInstances.clear();
    m_combinedInstances.reserve(m_totalInstances);

    u32 currentOffset = 0;
    for (auto& [key, batch] : m_batches) {
        batch.offset = currentOffset;
        for (const auto& instance : batch.instances) {
            m_combinedInstances.push_back(instance);
        }
        currentOffset += static_cast<u32>(batch.instances.size());
    }

    // Copy to GPU
    std::memcpy(m_mappedMemory, m_combinedInstances.data(),
                m_combinedInstances.size() * sizeof(InstanceData));
}

void InstanceBatch::bind(VkCommandBuffer cmd) {
    VkBuffer buffers[] = {m_instanceBuffer};
    VkDeviceSize offsets[] = {0};
    vkCmdBindVertexBuffers(cmd, 1, 1, buffers, offsets);  // Binding 1 for instances
}

u32 InstanceBatch::getInstanceCount(const std::string& meshKey) const {
    auto it = m_batches.find(meshKey);
    if (it != m_batches.end()) {
        return static_cast<u32>(it->second.instances.size());
    }
    return 0;
}

u32 InstanceBatch::getInstanceOffset(const std::string& meshKey) const {
    auto it = m_batches.find(meshKey);
    if (it != m_batches.end()) {
        return it->second.offset;
    }
    return 0;
}

std::vector<std::string> InstanceBatch::getMeshKeys() const {
    std::vector<std::string> keys;
    keys.reserve(m_batches.size());
    for (const auto& [key, batch] : m_batches) {
        if (!batch.instances.empty()) {
            keys.push_back(key);
        }
    }
    return keys;
}

// ============================================================================
// BatchedRenderer Implementation
// ============================================================================

BatchedRenderer::BatchedRenderer(VulkanContext& context, u32 maxInstances)
    : m_context(context), m_batch(context, maxInstances) {}

void BatchedRenderer::beginFrame() {
    m_batch.clear();
    m_drawCallCount = 0;
    m_flushed = false;
}

void BatchedRenderer::submit(const std::string& meshKey, const mat4& transform, const vec4& color) {
    InstanceData instance;
    instance.model = transform;
    instance.color = color;
    m_batch.addInstance(meshKey, instance);
}

void BatchedRenderer::flush() {
    if (!m_flushed) {
        m_batch.upload();
        m_flushed = true;
    }
}

void BatchedRenderer::render(VkCommandBuffer cmd,
                              std::unordered_map<std::string, std::unique_ptr<Mesh>>& meshCache,
                              VkPipelineLayout pipelineLayout) {
    if (!m_flushed) {
        flush();
    }

    if (m_batch.getTotalInstances() == 0) return;

    // Bind the instance buffer once
    m_batch.bind(cmd);

    // Draw each mesh type with its instances
    for (const auto& meshKey : m_batch.getMeshKeys()) {
        auto meshIt = meshCache.find(meshKey);
        if (meshIt == meshCache.end() || !meshIt->second) {
            continue;  // Mesh not found in cache
        }

        Mesh& mesh = *meshIt->second;
        u32 instanceCount = m_batch.getInstanceCount(meshKey);
        u32 firstInstance = m_batch.getInstanceOffset(meshKey);

        if (instanceCount == 0) continue;

        // Bind mesh vertex/index buffers (binding 0)
        mesh.bind(cmd);

        // Draw all instances of this mesh
        vkCmdDrawIndexed(cmd, mesh.getIndexCount(), instanceCount, 0, 0, firstInstance);

        m_drawCallCount++;
    }
}

} // namespace arch
