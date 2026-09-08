#pragma once

#include "types.hpp"
#include <unordered_map>

namespace arch {

class VulkanContext;

// ============================================================================
// DescriptorSetLayoutBuilder - Fluent API for creating descriptor set layouts
// ============================================================================
class DescriptorSetLayoutBuilder {
public:
    explicit DescriptorSetLayoutBuilder(VulkanContext& context);

    DescriptorSetLayoutBuilder& addBinding(
        u32 binding,
        VkDescriptorType type,
        VkShaderStageFlags stageFlags,
        u32 count = 1);

    DescriptorSetLayoutBuilder& addUniformBuffer(
        u32 binding,
        VkShaderStageFlags stageFlags);

    DescriptorSetLayoutBuilder& addSampler(
        u32 binding,
        VkShaderStageFlags stageFlags);

    DescriptorSetLayoutBuilder& addCombinedImageSampler(
        u32 binding,
        VkShaderStageFlags stageFlags);

    DescriptorSetLayoutBuilder& addStorageBuffer(
        u32 binding,
        VkShaderStageFlags stageFlags);

    VkDescriptorSetLayout build();

private:
    VulkanContext& m_context;
    std::vector<VkDescriptorSetLayoutBinding> m_bindings;
};

// ============================================================================
// DescriptorPool - Pool management with automatic reset and growth
// ============================================================================
class DescriptorPool {
public:
    struct PoolSizes {
        u32 uniformBuffers = 0;
        u32 combinedImageSamplers = 0;
        u32 samplers = 0;
        u32 storageBuffers = 0;
        u32 storageImages = 0;
    };

    DescriptorPool(VulkanContext& context, u32 maxSets, const PoolSizes& sizes);
    ~DescriptorPool();

    // Non-copyable
    DescriptorPool(const DescriptorPool&) = delete;
    DescriptorPool& operator=(const DescriptorPool&) = delete;

    // Allocate descriptor sets
    VkDescriptorSet allocate(VkDescriptorSetLayout layout);
    std::vector<VkDescriptorSet> allocate(VkDescriptorSetLayout layout, u32 count);

    // Reset the pool (frees all allocated sets)
    void reset();

    VkDescriptorPool getPool() const { return m_pool; }

private:
    VulkanContext& m_context;
    VkDescriptorPool m_pool = VK_NULL_HANDLE;
};

// ============================================================================
// DescriptorWriter - Helper for writing descriptor set updates
// ============================================================================
class DescriptorWriter {
public:
    explicit DescriptorWriter(VkDescriptorSet set);

    DescriptorWriter& writeBuffer(
        u32 binding,
        VkBuffer buffer,
        VkDeviceSize size,
        VkDeviceSize offset = 0,
        VkDescriptorType type = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER);

    DescriptorWriter& writeImage(
        u32 binding,
        VkImageView imageView,
        VkSampler sampler,
        VkImageLayout layout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
        VkDescriptorType type = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER);

    DescriptorWriter& writeSampler(
        u32 binding,
        VkSampler sampler);

    void update(VkDevice device);

private:
    VkDescriptorSet m_set;
    std::vector<VkWriteDescriptorSet> m_writes;
    std::vector<VkDescriptorBufferInfo> m_bufferInfos;
    std::vector<VkDescriptorImageInfo> m_imageInfos;
};

// ============================================================================
// DescriptorManager - High-level manager for descriptor resources
// ============================================================================
class DescriptorManager {
public:
    explicit DescriptorManager(VulkanContext& context);
    ~DescriptorManager();

    // Non-copyable
    DescriptorManager(const DescriptorManager&) = delete;
    DescriptorManager& operator=(const DescriptorManager&) = delete;

    // Layout management
    VkDescriptorSetLayout createLayout(const std::string& name,
        std::function<void(DescriptorSetLayoutBuilder&)> builder);
    VkDescriptorSetLayout getLayout(const std::string& name) const;

    // Pool management
    void createPool(u32 maxSets, const DescriptorPool::PoolSizes& sizes);
    VkDescriptorSet allocateSet(VkDescriptorSetLayout layout);
    std::vector<VkDescriptorSet> allocateSets(VkDescriptorSetLayout layout, u32 count);
    void resetPool();

    // Standard layouts
    VkDescriptorSetLayout getGlobalLayout() const { return m_globalLayout; }
    VkDescriptorSetLayout getMaterialLayout() const { return m_materialLayout; }

    // Create standard layouts for the renderer
    void createStandardLayouts();

private:
    VulkanContext& m_context;
    std::unordered_map<std::string, VkDescriptorSetLayout> m_layouts;
    std::unique_ptr<DescriptorPool> m_pool;

    // Standard layouts
    VkDescriptorSetLayout m_globalLayout = VK_NULL_HANDLE;    // Set 0: UBO + shadow map
    VkDescriptorSetLayout m_materialLayout = VK_NULL_HANDLE;  // Set 1: Material textures (future)
};

} // namespace arch
