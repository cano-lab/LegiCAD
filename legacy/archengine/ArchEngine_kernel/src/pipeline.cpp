#include "pipeline.hpp"
#include <stdexcept>

namespace arch {

// PipelineConfig default
PipelineConfig PipelineConfig::defaultConfig() {
    PipelineConfig config;

    config.inputAssembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    config.inputAssembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    config.inputAssembly.primitiveRestartEnable = VK_FALSE;

    config.rasterization.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    config.rasterization.depthClampEnable = VK_FALSE;
    config.rasterization.rasterizerDiscardEnable = VK_FALSE;
    config.rasterization.polygonMode = VK_POLYGON_MODE_FILL;
    config.rasterization.lineWidth = 1.0f;
    config.rasterization.cullMode = VK_CULL_MODE_BACK_BIT;  // Enable back-face culling
    config.rasterization.frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE;
    config.rasterization.depthBiasEnable = VK_FALSE;

    config.multisample.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    config.multisample.sampleShadingEnable = VK_FALSE;
    config.multisample.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;

    config.colorBlendAttachment.colorWriteMask =
        VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT |
        VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;
    config.colorBlendAttachment.blendEnable = VK_FALSE;

    config.depthStencil.sType = VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO;
    config.depthStencil.depthTestEnable = VK_TRUE;
    config.depthStencil.depthWriteEnable = VK_TRUE;
    config.depthStencil.depthCompareOp = VK_COMPARE_OP_LESS;
    config.depthStencil.depthBoundsTestEnable = VK_FALSE;
    config.depthStencil.stencilTestEnable = VK_FALSE;

    config.dynamicStates = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR};

    return config;
}

// PipelineConfig for transparent/glass materials with alpha blending
PipelineConfig PipelineConfig::transparentConfig() {
    PipelineConfig config = defaultConfig();

    // Enable alpha blending: finalColor = srcAlpha * srcColor + (1 - srcAlpha) * dstColor
    config.colorBlendAttachment.blendEnable = VK_TRUE;
    config.colorBlendAttachment.srcColorBlendFactor = VK_BLEND_FACTOR_SRC_ALPHA;
    config.colorBlendAttachment.dstColorBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA;
    config.colorBlendAttachment.colorBlendOp = VK_BLEND_OP_ADD;
    config.colorBlendAttachment.srcAlphaBlendFactor = VK_BLEND_FACTOR_ONE;
    config.colorBlendAttachment.dstAlphaBlendFactor = VK_BLEND_FACTOR_ZERO;
    config.colorBlendAttachment.alphaBlendOp = VK_BLEND_OP_ADD;

    // Disable depth writing for transparent objects (but still test depth)
    config.depthStencil.depthWriteEnable = VK_FALSE;

    return config;
}

// PipelineConfig for tessellation with displacement mapping
PipelineConfig PipelineConfig::tessellationConfig() {
    PipelineConfig config = defaultConfig();

    // For tessellation, input assembly uses patch list topology
    config.inputAssembly.topology = VK_PRIMITIVE_TOPOLOGY_PATCH_LIST;

    // Enable tessellation
    config.enableTessellation = true;
    config.patchControlPoints = 3;  // Triangles

    // Initialize tessellation state
    config.tessellation.sType = VK_STRUCTURE_TYPE_PIPELINE_TESSELLATION_STATE_CREATE_INFO;
    config.tessellation.patchControlPoints = 3;

    return config;
}

// PipelineConfig for multiple render targets (MRT)
PipelineConfig PipelineConfig::mrtConfig(u32 colorAttachmentCount) {
    PipelineConfig config = defaultConfig();

    // Set up multiple color blend attachments (all with same settings as default)
    config.colorBlendAttachments.resize(colorAttachmentCount);
    for (u32 i = 0; i < colorAttachmentCount; i++) {
        config.colorBlendAttachments[i].colorWriteMask =
            VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT |
            VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;
        config.colorBlendAttachments[i].blendEnable = VK_FALSE;
    }

    return config;
}

// Pipeline implementation
Pipeline::Pipeline(VulkanContext& context, const std::string& vertPath,
                   const std::string& fragPath, const PipelineConfig& config)
    : m_context(context) {

    auto vertCode = readFile(vertPath);
    auto fragCode = readFile(fragPath);

    m_vertShaderModule = createShaderModule(vertCode);
    m_fragShaderModule = createShaderModule(fragCode);

    VkPipelineShaderStageCreateInfo vertStageInfo{};
    vertStageInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    vertStageInfo.stage = VK_SHADER_STAGE_VERTEX_BIT;
    vertStageInfo.module = m_vertShaderModule;
    vertStageInfo.pName = "main";

    VkPipelineShaderStageCreateInfo fragStageInfo{};
    fragStageInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    fragStageInfo.stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    fragStageInfo.module = m_fragShaderModule;
    fragStageInfo.pName = "main";

    VkPipelineShaderStageCreateInfo shaderStages[] = {vertStageInfo, fragStageInfo};

    // Vertex input
    auto bindingDesc = Vertex::getBindingDescriptions()[0];
    auto attributeDescs = Vertex::getAttributeDescriptions();

    VkPipelineVertexInputStateCreateInfo vertexInputInfo{};
    vertexInputInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;
    vertexInputInfo.vertexBindingDescriptionCount = 1;
    vertexInputInfo.pVertexBindingDescriptions = &bindingDesc;
    vertexInputInfo.vertexAttributeDescriptionCount = static_cast<u32>(attributeDescs.size());
    vertexInputInfo.pVertexAttributeDescriptions = attributeDescs.data();

    // Viewport (dynamic)
    VkPipelineViewportStateCreateInfo viewportState{};
    viewportState.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    viewportState.viewportCount = 1;
    viewportState.scissorCount = 1;

    // Color blending - support multiple attachments for MRT
    VkPipelineColorBlendStateCreateInfo colorBlending{};
    colorBlending.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    colorBlending.logicOpEnable = VK_FALSE;

    // Use colorBlendAttachments vector if provided, otherwise use single attachment
    if (!config.colorBlendAttachments.empty()) {
        colorBlending.attachmentCount = static_cast<u32>(config.colorBlendAttachments.size());
        colorBlending.pAttachments = config.colorBlendAttachments.data();
    } else {
        colorBlending.attachmentCount = 1;
        colorBlending.pAttachments = &config.colorBlendAttachment;
    }

    // Dynamic state
    VkPipelineDynamicStateCreateInfo dynamicState{};
    dynamicState.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO;
    dynamicState.dynamicStateCount = static_cast<u32>(config.dynamicStates.size());
    dynamicState.pDynamicStates = config.dynamicStates.data();

    // Store layout
    m_pipelineLayout = config.pipelineLayout;

    // Create pipeline
    VkGraphicsPipelineCreateInfo pipelineInfo{};
    pipelineInfo.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    pipelineInfo.stageCount = 2;
    pipelineInfo.pStages = shaderStages;
    pipelineInfo.pVertexInputState = &vertexInputInfo;
    pipelineInfo.pInputAssemblyState = &config.inputAssembly;
    pipelineInfo.pViewportState = &viewportState;
    pipelineInfo.pRasterizationState = &config.rasterization;
    pipelineInfo.pMultisampleState = &config.multisample;
    pipelineInfo.pDepthStencilState = &config.depthStencil;
    pipelineInfo.pColorBlendState = &colorBlending;
    pipelineInfo.pDynamicState = &dynamicState;
    pipelineInfo.layout = m_pipelineLayout;
    pipelineInfo.renderPass = config.renderPass;
    pipelineInfo.subpass = config.subpass;

    if (vkCreateGraphicsPipelines(m_context.getDevice(), m_context.getPipelineCache(), 1,
                                   &pipelineInfo, nullptr, &m_pipeline) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create graphics pipeline");
    }
}

// Tessellation pipeline constructor
Pipeline::Pipeline(VulkanContext& context, const std::string& vertPath,
                   const std::string& tescPath, const std::string& tesePath,
                   const std::string& fragPath, const PipelineConfig& config)
    : m_context(context) {

    auto vertCode = readFile(vertPath);
    auto tescCode = readFile(tescPath);
    auto teseCode = readFile(tesePath);
    auto fragCode = readFile(fragPath);

    m_vertShaderModule = createShaderModule(vertCode);
    m_tescShaderModule = createShaderModule(tescCode);
    m_teseShaderModule = createShaderModule(teseCode);
    m_fragShaderModule = createShaderModule(fragCode);

    // Create shader stage infos
    VkPipelineShaderStageCreateInfo vertStageInfo{};
    vertStageInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    vertStageInfo.stage = VK_SHADER_STAGE_VERTEX_BIT;
    vertStageInfo.module = m_vertShaderModule;
    vertStageInfo.pName = "main";

    VkPipelineShaderStageCreateInfo tescStageInfo{};
    tescStageInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    tescStageInfo.stage = VK_SHADER_STAGE_TESSELLATION_CONTROL_BIT;
    tescStageInfo.module = m_tescShaderModule;
    tescStageInfo.pName = "main";

    VkPipelineShaderStageCreateInfo teseStageInfo{};
    teseStageInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    teseStageInfo.stage = VK_SHADER_STAGE_TESSELLATION_EVALUATION_BIT;
    teseStageInfo.module = m_teseShaderModule;
    teseStageInfo.pName = "main";

    VkPipelineShaderStageCreateInfo fragStageInfo{};
    fragStageInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    fragStageInfo.stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    fragStageInfo.module = m_fragShaderModule;
    fragStageInfo.pName = "main";

    VkPipelineShaderStageCreateInfo shaderStages[] = {
        vertStageInfo, tescStageInfo, teseStageInfo, fragStageInfo
    };

    // Vertex input
    auto bindingDesc = Vertex::getBindingDescriptions()[0];
    auto attributeDescs = Vertex::getAttributeDescriptions();

    VkPipelineVertexInputStateCreateInfo vertexInputInfo{};
    vertexInputInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;
    vertexInputInfo.vertexBindingDescriptionCount = 1;
    vertexInputInfo.pVertexBindingDescriptions = &bindingDesc;
    vertexInputInfo.vertexAttributeDescriptionCount = static_cast<u32>(attributeDescs.size());
    vertexInputInfo.pVertexAttributeDescriptions = attributeDescs.data();

    // Input assembly - must use patch list for tessellation
    VkPipelineInputAssemblyStateCreateInfo inputAssembly{};
    inputAssembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    inputAssembly.topology = VK_PRIMITIVE_TOPOLOGY_PATCH_LIST;
    inputAssembly.primitiveRestartEnable = VK_FALSE;

    // Tessellation state
    VkPipelineTessellationStateCreateInfo tessellation{};
    tessellation.sType = VK_STRUCTURE_TYPE_PIPELINE_TESSELLATION_STATE_CREATE_INFO;
    tessellation.patchControlPoints = config.patchControlPoints;

    // Viewport (dynamic)
    VkPipelineViewportStateCreateInfo viewportState{};
    viewportState.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    viewportState.viewportCount = 1;
    viewportState.scissorCount = 1;

    // Color blending - support multiple attachments for MRT
    VkPipelineColorBlendStateCreateInfo colorBlending{};
    colorBlending.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    colorBlending.logicOpEnable = VK_FALSE;

    // Use colorBlendAttachments vector if provided, otherwise use single attachment
    if (!config.colorBlendAttachments.empty()) {
        colorBlending.attachmentCount = static_cast<u32>(config.colorBlendAttachments.size());
        colorBlending.pAttachments = config.colorBlendAttachments.data();
    } else {
        colorBlending.attachmentCount = 1;
        colorBlending.pAttachments = &config.colorBlendAttachment;
    }

    // Dynamic state
    VkPipelineDynamicStateCreateInfo dynamicState{};
    dynamicState.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO;
    dynamicState.dynamicStateCount = static_cast<u32>(config.dynamicStates.size());
    dynamicState.pDynamicStates = config.dynamicStates.data();

    // Store layout
    m_pipelineLayout = config.pipelineLayout;

    // Create pipeline with tessellation stages
    VkGraphicsPipelineCreateInfo pipelineInfo{};
    pipelineInfo.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    pipelineInfo.stageCount = 4;  // vert, tesc, tese, frag
    pipelineInfo.pStages = shaderStages;
    pipelineInfo.pVertexInputState = &vertexInputInfo;
    pipelineInfo.pInputAssemblyState = &inputAssembly;
    pipelineInfo.pTessellationState = &tessellation;  // Enable tessellation
    pipelineInfo.pViewportState = &viewportState;
    pipelineInfo.pRasterizationState = &config.rasterization;
    pipelineInfo.pMultisampleState = &config.multisample;
    pipelineInfo.pDepthStencilState = &config.depthStencil;
    pipelineInfo.pColorBlendState = &colorBlending;
    pipelineInfo.pDynamicState = &dynamicState;
    pipelineInfo.layout = m_pipelineLayout;
    pipelineInfo.renderPass = config.renderPass;
    pipelineInfo.subpass = config.subpass;

    if (vkCreateGraphicsPipelines(m_context.getDevice(), m_context.getPipelineCache(), 1,
                                   &pipelineInfo, nullptr, &m_pipeline) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create tessellation pipeline");
    }
}

Pipeline::~Pipeline() {
    if (m_fragShaderModule != VK_NULL_HANDLE) {
        vkDestroyShaderModule(m_context.getDevice(), m_fragShaderModule, nullptr);
    }
    if (m_teseShaderModule != VK_NULL_HANDLE) {
        vkDestroyShaderModule(m_context.getDevice(), m_teseShaderModule, nullptr);
    }
    if (m_tescShaderModule != VK_NULL_HANDLE) {
        vkDestroyShaderModule(m_context.getDevice(), m_tescShaderModule, nullptr);
    }
    if (m_vertShaderModule != VK_NULL_HANDLE) {
        vkDestroyShaderModule(m_context.getDevice(), m_vertShaderModule, nullptr);
    }
    vkDestroyPipeline(m_context.getDevice(), m_pipeline, nullptr);
    if (m_ownsLayout) {
        vkDestroyPipelineLayout(m_context.getDevice(), m_pipelineLayout, nullptr);
    }
}

void Pipeline::bind(VkCommandBuffer commandBuffer) {
    vkCmdBindPipeline(commandBuffer, VK_PIPELINE_BIND_POINT_GRAPHICS, m_pipeline);
}

std::vector<char> Pipeline::readFile(const std::string& filepath) {
    std::ifstream file(filepath, std::ios::ate | std::ios::binary);
    if (!file.is_open()) {
        throw std::runtime_error("Failed to open shader file: " + filepath);
    }

    size_t fileSize = static_cast<size_t>(file.tellg());
    std::vector<char> buffer(fileSize);

    file.seekg(0);
    file.read(buffer.data(), fileSize);
    file.close();

    return buffer;
}

VkShaderModule Pipeline::createShaderModule(const std::vector<char>& code) {
    VkShaderModuleCreateInfo createInfo{};
    createInfo.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
    createInfo.codeSize = code.size();
    createInfo.pCode = reinterpret_cast<const u32*>(code.data());

    VkShaderModule shaderModule;
    if (vkCreateShaderModule(m_context.getDevice(), &createInfo, nullptr, &shaderModule) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create shader module");
    }

    return shaderModule;
}

// RenderPassBuilder implementation
RenderPassBuilder::RenderPassBuilder(VulkanContext& context) : m_context(context) {}

RenderPassBuilder& RenderPassBuilder::addColorAttachment(VkFormat format,
                                                          VkAttachmentLoadOp loadOp,
                                                          VkAttachmentStoreOp storeOp) {
    VkAttachmentDescription attachment{};
    attachment.format = format;
    attachment.samples = VK_SAMPLE_COUNT_1_BIT;
    attachment.loadOp = loadOp;
    attachment.storeOp = storeOp;
    attachment.stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    attachment.stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    attachment.initialLayout = loadOp == VK_ATTACHMENT_LOAD_OP_CLEAR ?
                               VK_IMAGE_LAYOUT_UNDEFINED : VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    attachment.finalLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;

    VkAttachmentReference ref{};
    ref.attachment = static_cast<u32>(m_attachments.size());
    ref.layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;

    m_attachments.push_back(attachment);
    m_colorRefs.push_back(ref);

    return *this;
}

RenderPassBuilder& RenderPassBuilder::addDepthAttachment(VkFormat format) {
    VkAttachmentDescription attachment{};
    attachment.format = format;
    attachment.samples = VK_SAMPLE_COUNT_1_BIT;
    attachment.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    attachment.storeOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    attachment.stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    attachment.stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    attachment.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    attachment.finalLayout = VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL;

    m_depthRef.attachment = static_cast<u32>(m_attachments.size());
    m_depthRef.layout = VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL;

    m_attachments.push_back(attachment);
    m_hasDepth = true;

    return *this;
}

RenderPassBuilder& RenderPassBuilder::addSubpass(VkPipelineBindPoint bindPoint) {
    VkSubpassDescription subpass{};
    subpass.pipelineBindPoint = bindPoint;
    subpass.colorAttachmentCount = static_cast<u32>(m_colorRefs.size());
    subpass.pColorAttachments = m_colorRefs.data();
    if (m_hasDepth) {
        subpass.pDepthStencilAttachment = &m_depthRef;
    }

    m_subpasses.push_back(subpass);
    return *this;
}

VkRenderPass RenderPassBuilder::build() {
    VkSubpassDependency dependency{};
    dependency.srcSubpass = VK_SUBPASS_EXTERNAL;
    dependency.dstSubpass = 0;
    dependency.srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT |
                               VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT;
    dependency.srcAccessMask = 0;
    dependency.dstStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT |
                               VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT;
    dependency.dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT |
                                VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;

    VkRenderPassCreateInfo renderPassInfo{};
    renderPassInfo.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO;
    renderPassInfo.attachmentCount = static_cast<u32>(m_attachments.size());
    renderPassInfo.pAttachments = m_attachments.data();
    renderPassInfo.subpassCount = static_cast<u32>(m_subpasses.size());
    renderPassInfo.pSubpasses = m_subpasses.data();
    renderPassInfo.dependencyCount = 1;
    renderPassInfo.pDependencies = &dependency;

    VkRenderPass renderPass;
    if (vkCreateRenderPass(m_context.getDevice(), &renderPassInfo, nullptr, &renderPass) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create render pass");
    }

    return renderPass;
}

// PipelineLayoutBuilder implementation
PipelineLayoutBuilder::PipelineLayoutBuilder(VulkanContext& context) : m_context(context) {}

PipelineLayoutBuilder& PipelineLayoutBuilder::addPushConstantRange(VkShaderStageFlags stages,
                                                                     u32 offset, u32 size) {
    VkPushConstantRange range{};
    range.stageFlags = stages;
    range.offset = offset;
    range.size = size;
    m_pushConstantRanges.push_back(range);
    return *this;
}

PipelineLayoutBuilder& PipelineLayoutBuilder::addDescriptorSetLayout(VkDescriptorSetLayout layout) {
    m_descriptorSetLayouts.push_back(layout);
    return *this;
}

VkPipelineLayout PipelineLayoutBuilder::build() {
    VkPipelineLayoutCreateInfo layoutInfo{};
    layoutInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    layoutInfo.setLayoutCount = static_cast<u32>(m_descriptorSetLayouts.size());
    layoutInfo.pSetLayouts = m_descriptorSetLayouts.data();
    layoutInfo.pushConstantRangeCount = static_cast<u32>(m_pushConstantRanges.size());
    layoutInfo.pPushConstantRanges = m_pushConstantRanges.data();

    VkPipelineLayout layout;
    if (vkCreatePipelineLayout(m_context.getDevice(), &layoutInfo, nullptr, &layout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create pipeline layout");
    }

    return layout;
}

} // namespace arch
