#include "descriptor_manager.hpp"
#include "vulkan_context.hpp"
#include <stdexcept>

namespace arch {

// ============================================================================
// DescriptorSetLayoutBuilder Implementation
// ============================================================================

DescriptorSetLayoutBuilder::DescriptorSetLayoutBuilder(VulkanContext& context)
    : m_context(context) {}

DescriptorSetLayoutBuilder& DescriptorSetLayoutBuilder::addBinding(
    u32 binding,
    VkDescriptorType type,
    VkShaderStageFlags stageFlags,
    u32 count) {

    VkDescriptorSetLayoutBinding layoutBinding{};
    layoutBinding.binding = binding;
    layoutBinding.descriptorType = type;
    layoutBinding.descriptorCount = count;
    layoutBinding.stageFlags = stageFlags;
    layoutBinding.pImmutableSamplers = nullptr;

    m_bindings.push_back(layoutBinding);
    return *this;
}

DescriptorSetLayoutBuilder& DescriptorSetLayoutBuilder::addUniformBuffer(
    u32 binding,
    VkShaderStageFlags stageFlags) {
    return addBinding(binding, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, stageFlags);
}

DescriptorSetLayoutBuilder& DescriptorSetLayoutBuilder::addSampler(
    u32 binding,
    VkShaderStageFlags stageFlags) {
    return addBinding(binding, VK_DESCRIPTOR_TYPE_SAMPLER, stageFlags);
}

DescriptorSetLayoutBuilder& DescriptorSetLayoutBuilder::addCombinedImageSampler(
    u32 binding,
    VkShaderStageFlags stageFlags) {
    return addBinding(binding, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, stageFlags);
}

DescriptorSetLayoutBuilder& DescriptorSetLayoutBuilder::addStorageBuffer(
    u32 binding,
    VkShaderStageFlags stageFlags) {
    return addBinding(binding, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, stageFlags);
}

VkDescriptorSetLayout DescriptorSetLayoutBuilder::build() {
    VkDescriptorSetLayoutCreateInfo layoutInfo{};
    layoutInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
    layoutInfo.bindingCount = static_cast<u32>(m_bindings.size());
    layoutInfo.pBindings = m_bindings.data();

    VkDescriptorSetLayout layout;
    if (vkCreateDescriptorSetLayout(m_context.getDevice(), &layoutInfo, nullptr, &layout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create descriptor set layout");
    }

    return layout;
}

// ============================================================================
// DescriptorPool Implementation
// ============================================================================

DescriptorPool::DescriptorPool(VulkanContext& context, u32 maxSets, const PoolSizes& sizes)
    : m_context(context) {

    std::vector<VkDescriptorPoolSize> poolSizes;

    if (sizes.uniformBuffers > 0) {
        poolSizes.push_back({VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, sizes.uniformBuffers});
    }
    if (sizes.combinedImageSamplers > 0) {
        poolSizes.push_back({VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, sizes.combinedImageSamplers});
    }
    if (sizes.samplers > 0) {
        poolSizes.push_back({VK_DESCRIPTOR_TYPE_SAMPLER, sizes.samplers});
    }
    if (sizes.storageBuffers > 0) {
        poolSizes.push_back({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, sizes.storageBuffers});
    }
    if (sizes.storageImages > 0) {
        poolSizes.push_back({VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, sizes.storageImages});
    }

    // Default to at least one uniform buffer if no sizes specified
    if (poolSizes.empty()) {
        poolSizes.push_back({VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, maxSets});
    }

    VkDescriptorPoolCreateInfo poolInfo{};
    poolInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
    poolInfo.flags = VK_DESCRIPTOR_POOL_CREATE_FREE_DESCRIPTOR_SET_BIT;
    poolInfo.maxSets = maxSets;
    poolInfo.poolSizeCount = static_cast<u32>(poolSizes.size());
    poolInfo.pPoolSizes = poolSizes.data();

    if (vkCreateDescriptorPool(m_context.getDevice(), &poolInfo, nullptr, &m_pool) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create descriptor pool");
    }
}

DescriptorPool::~DescriptorPool() {
    if (m_pool != VK_NULL_HANDLE) {
        vkDestroyDescriptorPool(m_context.getDevice(), m_pool, nullptr);
    }
}

VkDescriptorSet DescriptorPool::allocate(VkDescriptorSetLayout layout) {
    VkDescriptorSetAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
    allocInfo.descriptorPool = m_pool;
    allocInfo.descriptorSetCount = 1;
    allocInfo.pSetLayouts = &layout;

    VkDescriptorSet set;
    if (vkAllocateDescriptorSets(m_context.getDevice(), &allocInfo, &set) != VK_SUCCESS) {
        throw std::runtime_error("Failed to allocate descriptor set");
    }

    return set;
}

std::vector<VkDescriptorSet> DescriptorPool::allocate(VkDescriptorSetLayout layout, u32 count) {
    std::vector<VkDescriptorSetLayout> layouts(count, layout);

    VkDescriptorSetAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
    allocInfo.descriptorPool = m_pool;
    allocInfo.descriptorSetCount = count;
    allocInfo.pSetLayouts = layouts.data();

    std::vector<VkDescriptorSet> sets(count);
    if (vkAllocateDescriptorSets(m_context.getDevice(), &allocInfo, sets.data()) != VK_SUCCESS) {
        throw std::runtime_error("Failed to allocate descriptor sets");
    }

    return sets;
}

void DescriptorPool::reset() {
    vkResetDescriptorPool(m_context.getDevice(), m_pool, 0);
}

// ============================================================================
// DescriptorWriter Implementation
// ============================================================================

DescriptorWriter::DescriptorWriter(VkDescriptorSet set)
    : m_set(set) {}

DescriptorWriter& DescriptorWriter::writeBuffer(
    u32 binding,
    VkBuffer buffer,
    VkDeviceSize size,
    VkDeviceSize offset,
    VkDescriptorType type) {

    m_bufferInfos.push_back({buffer, offset, size});

    VkWriteDescriptorSet write{};
    write.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    write.dstSet = m_set;
    write.dstBinding = binding;
    write.dstArrayElement = 0;
    write.descriptorType = type;
    write.descriptorCount = 1;
    // pBufferInfo will be set in update() after all infos are added
    write.pBufferInfo = nullptr;

    m_writes.push_back(write);
    return *this;
}

DescriptorWriter& DescriptorWriter::writeImage(
    u32 binding,
    VkImageView imageView,
    VkSampler sampler,
    VkImageLayout layout,
    VkDescriptorType type) {

    VkDescriptorImageInfo imageInfo{};
    imageInfo.imageLayout = layout;
    imageInfo.imageView = imageView;
    imageInfo.sampler = sampler;
    m_imageInfos.push_back(imageInfo);

    VkWriteDescriptorSet write{};
    write.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    write.dstSet = m_set;
    write.dstBinding = binding;
    write.dstArrayElement = 0;
    write.descriptorType = type;
    write.descriptorCount = 1;
    // pImageInfo will be set in update()
    write.pImageInfo = nullptr;

    m_writes.push_back(write);
    return *this;
}

DescriptorWriter& DescriptorWriter::writeSampler(
    u32 binding,
    VkSampler sampler) {

    VkDescriptorImageInfo imageInfo{};
    imageInfo.sampler = sampler;
    m_imageInfos.push_back(imageInfo);

    VkWriteDescriptorSet write{};
    write.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    write.dstSet = m_set;
    write.dstBinding = binding;
    write.dstArrayElement = 0;
    write.descriptorType = VK_DESCRIPTOR_TYPE_SAMPLER;
    write.descriptorCount = 1;
    write.pImageInfo = nullptr;

    m_writes.push_back(write);
    return *this;
}

void DescriptorWriter::update(VkDevice device) {
    // Now set the pointers to the info structs
    size_t bufferIndex = 0;
    size_t imageIndex = 0;

    for (auto& write : m_writes) {
        if (write.descriptorType == VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER ||
            write.descriptorType == VK_DESCRIPTOR_TYPE_STORAGE_BUFFER ||
            write.descriptorType == VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC ||
            write.descriptorType == VK_DESCRIPTOR_TYPE_STORAGE_BUFFER_DYNAMIC) {
            write.pBufferInfo = &m_bufferInfos[bufferIndex++];
        } else {
            write.pImageInfo = &m_imageInfos[imageIndex++];
        }
    }

    vkUpdateDescriptorSets(device, static_cast<u32>(m_writes.size()), m_writes.data(), 0, nullptr);
}

// ============================================================================
// DescriptorManager Implementation
// ============================================================================

DescriptorManager::DescriptorManager(VulkanContext& context)
    : m_context(context) {}

DescriptorManager::~DescriptorManager() {
    // Destroy all layouts
    for (auto& [name, layout] : m_layouts) {
        vkDestroyDescriptorSetLayout(m_context.getDevice(), layout, nullptr);
    }

    // Standard layouts are in m_layouts, so they're already destroyed
    m_globalLayout = VK_NULL_HANDLE;
    m_materialLayout = VK_NULL_HANDLE;
}

VkDescriptorSetLayout DescriptorManager::createLayout(
    const std::string& name,
    std::function<void(DescriptorSetLayoutBuilder&)> builder) {

    DescriptorSetLayoutBuilder layoutBuilder(m_context);
    builder(layoutBuilder);
    VkDescriptorSetLayout layout = layoutBuilder.build();

    m_layouts[name] = layout;
    return layout;
}

VkDescriptorSetLayout DescriptorManager::getLayout(const std::string& name) const {
    auto it = m_layouts.find(name);
    if (it != m_layouts.end()) {
        return it->second;
    }
    return VK_NULL_HANDLE;
}

void DescriptorManager::createPool(u32 maxSets, const DescriptorPool::PoolSizes& sizes) {
    m_pool = std::make_unique<DescriptorPool>(m_context, maxSets, sizes);
}

VkDescriptorSet DescriptorManager::allocateSet(VkDescriptorSetLayout layout) {
    if (!m_pool) {
        throw std::runtime_error("Descriptor pool not created");
    }
    return m_pool->allocate(layout);
}

std::vector<VkDescriptorSet> DescriptorManager::allocateSets(VkDescriptorSetLayout layout, u32 count) {
    if (!m_pool) {
        throw std::runtime_error("Descriptor pool not created");
    }
    return m_pool->allocate(layout, count);
}

void DescriptorManager::resetPool() {
    if (m_pool) {
        m_pool->reset();
    }
}

void DescriptorManager::createStandardLayouts() {
    // Global layout (Set 0):
    // - Binding 0: UBO (vertex + fragment stages)
    // - Binding 1: Shadow map sampler (fragment stage) - for Phase 4
    m_globalLayout = createLayout("global", [](DescriptorSetLayoutBuilder& builder) {
        builder
            .addUniformBuffer(0, VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT | VK_SHADER_STAGE_TESSELLATION_CONTROL_BIT | VK_SHADER_STAGE_TESSELLATION_EVALUATION_BIT)
            .addCombinedImageSampler(1, VK_SHADER_STAGE_FRAGMENT_BIT);
    });

    // Material layout (Set 1) - for future texture support
    // - Binding 0: Albedo texture
    // - Binding 1: Normal map
    // - Binding 2: Metallic/roughness
    m_materialLayout = createLayout("material", [](DescriptorSetLayoutBuilder& builder) {
        builder
            .addCombinedImageSampler(0, VK_SHADER_STAGE_FRAGMENT_BIT)
            .addCombinedImageSampler(1, VK_SHADER_STAGE_FRAGMENT_BIT)
            .addCombinedImageSampler(2, VK_SHADER_STAGE_FRAGMENT_BIT);
    });
}

} // namespace arch
