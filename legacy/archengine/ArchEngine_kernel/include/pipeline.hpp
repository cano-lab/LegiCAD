#pragma once

#include "types.hpp"
#include "vulkan_context.hpp"
#include <fstream>

namespace arch {

struct PipelineConfig {
    VkPipelineInputAssemblyStateCreateInfo inputAssembly{};
    VkPipelineRasterizationStateCreateInfo rasterization{};
    VkPipelineMultisampleStateCreateInfo multisample{};
    VkPipelineColorBlendAttachmentState colorBlendAttachment{};  // Primary attachment (for backwards compat)
    std::vector<VkPipelineColorBlendAttachmentState> colorBlendAttachments;  // Multiple attachments for MRT
    VkPipelineDepthStencilStateCreateInfo depthStencil{};
    VkPipelineTessellationStateCreateInfo tessellation{};
    std::vector<VkDynamicState> dynamicStates;
    VkPipelineLayout pipelineLayout = VK_NULL_HANDLE;
    VkRenderPass renderPass = VK_NULL_HANDLE;
    u32 subpass = 0;
    bool enableTessellation = false;
    u32 patchControlPoints = 3;  // Triangles

    static PipelineConfig defaultConfig();
    static PipelineConfig transparentConfig();  // Alpha blending enabled
    static PipelineConfig tessellationConfig(); // Tessellation enabled
    static PipelineConfig mrtConfig(u32 colorAttachmentCount);  // Multiple render targets
};

class Pipeline {
public:
    // Standard pipeline (vertex + fragment)
    Pipeline(VulkanContext& context, const std::string& vertPath,
             const std::string& fragPath, const PipelineConfig& config);

    // Tessellation pipeline (vertex + tesc + tese + fragment)
    Pipeline(VulkanContext& context, const std::string& vertPath,
             const std::string& tescPath, const std::string& tesePath,
             const std::string& fragPath, const PipelineConfig& config);

    ~Pipeline();

    // Non-copyable
    Pipeline(const Pipeline&) = delete;
    Pipeline& operator=(const Pipeline&) = delete;

    void bind(VkCommandBuffer commandBuffer);

    VkPipeline getHandle() const { return m_pipeline; }
    VkPipelineLayout getLayout() const { return m_pipelineLayout; }

private:
    static std::vector<char> readFile(const std::string& filepath);
    VkShaderModule createShaderModule(const std::vector<char>& code);

    VulkanContext& m_context;
    VkPipeline m_pipeline = VK_NULL_HANDLE;
    VkPipelineLayout m_pipelineLayout = VK_NULL_HANDLE;
    VkShaderModule m_vertShaderModule = VK_NULL_HANDLE;
    VkShaderModule m_tescShaderModule = VK_NULL_HANDLE;
    VkShaderModule m_teseShaderModule = VK_NULL_HANDLE;
    VkShaderModule m_fragShaderModule = VK_NULL_HANDLE;
    bool m_ownsLayout = false;
};

// Render pass builder
class RenderPassBuilder {
public:
    explicit RenderPassBuilder(VulkanContext& context);

    RenderPassBuilder& addColorAttachment(VkFormat format,
                                          VkAttachmentLoadOp loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR,
                                          VkAttachmentStoreOp storeOp = VK_ATTACHMENT_STORE_OP_STORE);

    RenderPassBuilder& addDepthAttachment(VkFormat format);

    RenderPassBuilder& addSubpass(VkPipelineBindPoint bindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS);

    VkRenderPass build();

private:
    VulkanContext& m_context;
    std::vector<VkAttachmentDescription> m_attachments;
    std::vector<VkAttachmentReference> m_colorRefs;
    VkAttachmentReference m_depthRef{};
    bool m_hasDepth = false;
    std::vector<VkSubpassDescription> m_subpasses;
};

// Pipeline layout builder
class PipelineLayoutBuilder {
public:
    explicit PipelineLayoutBuilder(VulkanContext& context);

    PipelineLayoutBuilder& addPushConstantRange(VkShaderStageFlags stages, u32 offset, u32 size);
    PipelineLayoutBuilder& addDescriptorSetLayout(VkDescriptorSetLayout layout);

    VkPipelineLayout build();

private:
    VulkanContext& m_context;
    std::vector<VkPushConstantRange> m_pushConstantRanges;
    std::vector<VkDescriptorSetLayout> m_descriptorSetLayouts;
};

} // namespace arch
