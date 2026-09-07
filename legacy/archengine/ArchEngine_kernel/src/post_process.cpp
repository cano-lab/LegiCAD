#include "post_process.hpp"
#include <array>
#include <cstring>
#include <fstream>
#include <iostream>

namespace arch {

PostProcess::PostProcess(VulkanContext& context)
    : m_context(context) {
}

PostProcess::~PostProcess() {
    cleanup();
}

void PostProcess::initialize(u32 width, u32 height) {
    if (m_initialized) {
        cleanup();
    }

    m_width = width;
    m_height = height;

    createHDRResources();
    createSSAOKernel();
    createNoiseTexture();
    createSSAOResources();
    createSSAOPipeline();
    createBlurPipeline();
    createBloomResources();
    createBloomPipelines();
    createSSRResources();
    createSSRPipeline();
    createFullscreenQuad();

    m_initialized = true;
    std::cout << "[PostProcess] Initialized " << width << "x" << height << std::endl;
}

void PostProcess::cleanup() {
    if (!m_initialized) return;

    m_context.waitIdle();
    cleanupComposite();
    cleanupSSR();
    cleanupBloom();
    cleanupSSAO();
    cleanupHDR();

    // Cleanup fullscreen quad
    if (m_quadVertexBuffer) {
        vkDestroyBuffer(m_context.getDevice(), m_quadVertexBuffer, nullptr);
        vkFreeMemory(m_context.getDevice(), m_quadVertexMemory, nullptr);
    }
    if (m_quadIndexBuffer) {
        vkDestroyBuffer(m_context.getDevice(), m_quadIndexBuffer, nullptr);
        vkFreeMemory(m_context.getDevice(), m_quadIndexMemory, nullptr);
    }

    m_initialized = false;
}

void PostProcess::resize(u32 width, u32 height) {
    if (width == m_width && height == m_height) return;

    m_context.waitIdle();
    cleanupHDRTargets();
    cleanupSSAOSizeDependent();
    cleanupBloom();

    m_width = width;
    m_height = height;

    createHDRTargets();
    createSSAOResources();
    createBloomResources();
    std::cout << "[PostProcess] Resized to " << width << "x" << height << std::endl;
}

void PostProcess::createSSAOKernel() {
    std::uniform_real_distribution<float> randomFloats(0.0f, 1.0f);
    std::default_random_engine generator;

    m_ssaoKernel.resize(64);

    for (u32 i = 0; i < 64; i++) {
        // Generate random point in hemisphere
        vec3 sample(
            randomFloats(generator) * 2.0f - 1.0f,
            randomFloats(generator) * 2.0f - 1.0f,
            randomFloats(generator)  // Only positive z (hemisphere)
        );
        sample = glm::normalize(sample);
        sample *= randomFloats(generator);

        // Scale samples to be more aligned to center
        float scale = float(i) / 64.0f;
        scale = glm::mix(0.1f, 1.0f, scale * scale);  // Quadratic falloff
        sample *= scale;

        m_ssaoKernel[i] = vec4(sample, 0.0f);
    }
}

void PostProcess::createNoiseTexture() {
    std::uniform_real_distribution<float> randomFloats(0.0f, 1.0f);
    std::default_random_engine generator;

    // 4x4 noise texture with random rotation vectors
    std::vector<vec4> noise(16);
    for (u32 i = 0; i < 16; i++) {
        noise[i] = vec4(
            randomFloats(generator) * 2.0f - 1.0f,
            randomFloats(generator) * 2.0f - 1.0f,
            0.0f,
            0.0f
        );
        noise[i] = glm::normalize(noise[i]);
    }

    // Create staging buffer
    VkDeviceSize bufferSize = sizeof(vec4) * 16;
    VkBuffer stagingBuffer;
    VkDeviceMemory stagingMemory;

    m_context.createBuffer(bufferSize, VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
                          VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
                          stagingBuffer, stagingMemory);

    void* data;
    vkMapMemory(m_context.getDevice(), stagingMemory, 0, bufferSize, 0, &data);
    memcpy(data, noise.data(), bufferSize);
    vkUnmapMemory(m_context.getDevice(), stagingMemory);

    // Create image
    m_context.createImage(4, 4, VK_FORMAT_R32G32B32A32_SFLOAT, VK_IMAGE_TILING_OPTIMAL,
                         VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
                         VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
                         m_noiseImage, m_noiseMemory);

    // Transition and copy
    m_context.transitionImageLayout(m_noiseImage, VK_FORMAT_R32G32B32A32_SFLOAT,
                                   VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);

    VkCommandBuffer cmd = m_context.beginSingleTimeCommands();

    VkBufferImageCopy region{};
    region.bufferOffset = 0;
    region.bufferRowLength = 0;
    region.bufferImageHeight = 0;
    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    region.imageSubresource.mipLevel = 0;
    region.imageSubresource.baseArrayLayer = 0;
    region.imageSubresource.layerCount = 1;
    region.imageOffset = {0, 0, 0};
    region.imageExtent = {4, 4, 1};

    vkCmdCopyBufferToImage(cmd, stagingBuffer, m_noiseImage,
                          VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);

    m_context.endSingleTimeCommands(cmd);

    m_context.transitionImageLayout(m_noiseImage, VK_FORMAT_R32G32B32A32_SFLOAT,
                                   VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                                   VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);

    // Cleanup staging
    vkDestroyBuffer(m_context.getDevice(), stagingBuffer, nullptr);
    vkFreeMemory(m_context.getDevice(), stagingMemory, nullptr);

    // Create image view
    m_noiseView = m_context.createImageView(m_noiseImage, VK_FORMAT_R32G32B32A32_SFLOAT,
                                           VK_IMAGE_ASPECT_COLOR_BIT);

    // Create sampler (repeat for tiling)
    VkSamplerCreateInfo samplerInfo{};
    samplerInfo.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
    samplerInfo.magFilter = VK_FILTER_NEAREST;
    samplerInfo.minFilter = VK_FILTER_NEAREST;
    samplerInfo.addressModeU = VK_SAMPLER_ADDRESS_MODE_REPEAT;
    samplerInfo.addressModeV = VK_SAMPLER_ADDRESS_MODE_REPEAT;
    samplerInfo.addressModeW = VK_SAMPLER_ADDRESS_MODE_REPEAT;
    samplerInfo.anisotropyEnable = VK_FALSE;
    samplerInfo.maxAnisotropy = 1.0f;
    samplerInfo.borderColor = VK_BORDER_COLOR_INT_OPAQUE_BLACK;
    samplerInfo.unnormalizedCoordinates = VK_FALSE;
    samplerInfo.compareEnable = VK_FALSE;
    samplerInfo.mipmapMode = VK_SAMPLER_MIPMAP_MODE_NEAREST;

    if (vkCreateSampler(m_context.getDevice(), &samplerInfo, nullptr, &m_noiseSampler) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create noise sampler");
    }
}

void PostProcess::createSSAOResources() {
    auto device = m_context.getDevice();

    // Create SSAO output image (single channel float)
    m_context.createImage(m_width, m_height, VK_FORMAT_R8_UNORM, VK_IMAGE_TILING_OPTIMAL,
                         VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
                         VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
                         m_ssaoImage, m_ssaoMemory);

    m_ssaoView = m_context.createImageView(m_ssaoImage, VK_FORMAT_R8_UNORM, VK_IMAGE_ASPECT_COLOR_BIT);

    // Create blurred SSAO output
    m_context.createImage(m_width, m_height, VK_FORMAT_R8_UNORM, VK_IMAGE_TILING_OPTIMAL,
                         VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
                         VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
                         m_ssaoBlurredImage, m_ssaoBlurredMemory);

    m_ssaoBlurredView = m_context.createImageView(m_ssaoBlurredImage, VK_FORMAT_R8_UNORM, VK_IMAGE_ASPECT_COLOR_BIT);

    // Create SSAO sampler
    VkSamplerCreateInfo samplerInfo{};
    samplerInfo.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
    samplerInfo.magFilter = VK_FILTER_LINEAR;
    samplerInfo.minFilter = VK_FILTER_LINEAR;
    samplerInfo.addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.anisotropyEnable = VK_FALSE;
    samplerInfo.borderColor = VK_BORDER_COLOR_FLOAT_OPAQUE_WHITE;
    samplerInfo.unnormalizedCoordinates = VK_FALSE;
    samplerInfo.compareEnable = VK_FALSE;
    samplerInfo.mipmapMode = VK_SAMPLER_MIPMAP_MODE_LINEAR;

    if (vkCreateSampler(device, &samplerInfo, nullptr, &m_ssaoSampler) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSAO sampler");
    }

    // Create render pass for SSAO
    VkAttachmentDescription attachment{};
    attachment.format = VK_FORMAT_R8_UNORM;
    attachment.samples = VK_SAMPLE_COUNT_1_BIT;
    attachment.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    attachment.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    attachment.stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    attachment.stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    attachment.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    attachment.finalLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

    VkAttachmentReference colorRef{};
    colorRef.attachment = 0;
    colorRef.layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;

    VkSubpassDescription subpass{};
    subpass.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    subpass.colorAttachmentCount = 1;
    subpass.pColorAttachments = &colorRef;

    VkRenderPassCreateInfo renderPassInfo{};
    renderPassInfo.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO;
    renderPassInfo.attachmentCount = 1;
    renderPassInfo.pAttachments = &attachment;
    renderPassInfo.subpassCount = 1;
    renderPassInfo.pSubpasses = &subpass;

    if (vkCreateRenderPass(device, &renderPassInfo, nullptr, &m_ssaoRenderPass) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSAO render pass");
    }

    // Create framebuffers
    VkFramebufferCreateInfo fbInfo{};
    fbInfo.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO;
    fbInfo.renderPass = m_ssaoRenderPass;
    fbInfo.attachmentCount = 1;
    fbInfo.pAttachments = &m_ssaoView;
    fbInfo.width = m_width;
    fbInfo.height = m_height;
    fbInfo.layers = 1;

    if (vkCreateFramebuffer(device, &fbInfo, nullptr, &m_ssaoFramebuffer) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSAO framebuffer");
    }

    fbInfo.pAttachments = &m_ssaoBlurredView;
    if (vkCreateFramebuffer(device, &fbInfo, nullptr, &m_ssaoBlurFramebuffer) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSAO blur framebuffer");
    }

    // Create uniform buffer for SSAO params
    VkDeviceSize uniformSize = sizeof(mat4) * 2 + sizeof(vec4) * 64 + sizeof(vec4) * 2;
    m_context.createBuffer(uniformSize, VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT,
                          VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
                          m_ssaoUniformBuffer, m_ssaoUniformMemory);

    vkMapMemory(device, m_ssaoUniformMemory, 0, uniformSize, 0, &m_ssaoUniformMapped);

    // Create descriptor pool - enough for SSAO, bloom, SSR, and composite across frames
    u32 frameCount = m_context.getMaxFramesInFlight();
    std::array<VkDescriptorPoolSize, 2> poolSizes{};
    poolSizes[0].type = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    poolSizes[0].descriptorCount = frameCount * 20 + 10;  // SSAO (3), bloom (2), composite (5), SSR (4) per frame + extras
    poolSizes[1].type = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER;
    poolSizes[1].descriptorCount = frameCount + 4;

    VkDescriptorPoolCreateInfo poolInfo{};
    poolInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
    poolInfo.poolSizeCount = static_cast<u32>(poolSizes.size());
    poolInfo.pPoolSizes = poolSizes.data();
    poolInfo.maxSets = frameCount * 8 + 10;  // SSAO + bloom + composite + SSR per frame + extra
    // Allow descriptor sets to be updated while bound (for dynamic SSAO depth/normal binding)
    poolInfo.flags = VK_DESCRIPTOR_POOL_CREATE_UPDATE_AFTER_BIND_BIT;

    if (vkCreateDescriptorPool(device, &poolInfo, nullptr, &m_descriptorPool) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSAO descriptor pool");
    }

    // Create descriptor set layout for SSAO generation
    std::array<VkDescriptorSetLayoutBinding, 4> bindings{};

    // Depth texture
    bindings[0].binding = 0;
    bindings[0].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    bindings[0].descriptorCount = 1;
    bindings[0].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    // Normal texture (unused for now, will reconstruct from depth)
    bindings[1].binding = 1;
    bindings[1].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    bindings[1].descriptorCount = 1;
    bindings[1].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    // Noise texture
    bindings[2].binding = 2;
    bindings[2].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    bindings[2].descriptorCount = 1;
    bindings[2].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    // SSAO params uniform
    bindings[3].binding = 3;
    bindings[3].descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER;
    bindings[3].descriptorCount = 1;
    bindings[3].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    // Enable UPDATE_AFTER_BIND for all bindings (SSAO updates depth/normal views each frame)
    std::array<VkDescriptorBindingFlags, 4> bindingFlags{};
    bindingFlags[0] = VK_DESCRIPTOR_BINDING_UPDATE_AFTER_BIND_BIT;
    bindingFlags[1] = VK_DESCRIPTOR_BINDING_UPDATE_AFTER_BIND_BIT;
    bindingFlags[2] = VK_DESCRIPTOR_BINDING_UPDATE_AFTER_BIND_BIT;
    bindingFlags[3] = VK_DESCRIPTOR_BINDING_UPDATE_AFTER_BIND_BIT;

    VkDescriptorSetLayoutBindingFlagsCreateInfo bindingFlagsInfo{};
    bindingFlagsInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_BINDING_FLAGS_CREATE_INFO;
    bindingFlagsInfo.bindingCount = static_cast<u32>(bindingFlags.size());
    bindingFlagsInfo.pBindingFlags = bindingFlags.data();

    VkDescriptorSetLayoutCreateInfo layoutInfo{};
    layoutInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
    layoutInfo.bindingCount = static_cast<u32>(bindings.size());
    layoutInfo.pBindings = bindings.data();
    layoutInfo.pNext = &bindingFlagsInfo;
    layoutInfo.flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_UPDATE_AFTER_BIND_POOL_BIT;

    if (vkCreateDescriptorSetLayout(device, &layoutInfo, nullptr, &m_ssaoDescriptorLayout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSAO descriptor set layout");
    }

    // Create descriptor set layout for blur pass
    std::array<VkDescriptorSetLayoutBinding, 2> blurBindings{};
    blurBindings[0].binding = 0;
    blurBindings[0].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    blurBindings[0].descriptorCount = 1;
    blurBindings[0].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    blurBindings[1].binding = 1;
    blurBindings[1].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    blurBindings[1].descriptorCount = 1;
    blurBindings[1].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    // Reset layoutInfo for blur layout (no UPDATE_AFTER_BIND needed - static binding)
    VkDescriptorSetLayoutCreateInfo blurLayoutInfo{};
    blurLayoutInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
    blurLayoutInfo.bindingCount = static_cast<u32>(blurBindings.size());
    blurLayoutInfo.pBindings = blurBindings.data();

    if (vkCreateDescriptorSetLayout(device, &blurLayoutInfo, nullptr, &m_ssaoBlurDescLayout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSAO blur descriptor set layout");
    }

    // Create descriptor set layout for sampling SSAO in main shader
    VkDescriptorSetLayoutBinding sampleBinding{};
    sampleBinding.binding = 0;
    sampleBinding.descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    sampleBinding.descriptorCount = 1;
    sampleBinding.stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    // Enable UPDATE_AFTER_BIND for sample descriptor (updated during command recording)
    VkDescriptorBindingFlags sampleBindingFlag = VK_DESCRIPTOR_BINDING_UPDATE_AFTER_BIND_BIT;
    VkDescriptorSetLayoutBindingFlagsCreateInfo sampleBindingFlagsInfo{};
    sampleBindingFlagsInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_BINDING_FLAGS_CREATE_INFO;
    sampleBindingFlagsInfo.bindingCount = 1;
    sampleBindingFlagsInfo.pBindingFlags = &sampleBindingFlag;

    VkDescriptorSetLayoutCreateInfo sampleLayoutInfo{};
    sampleLayoutInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
    sampleLayoutInfo.bindingCount = 1;
    sampleLayoutInfo.pBindings = &sampleBinding;
    sampleLayoutInfo.pNext = &sampleBindingFlagsInfo;
    sampleLayoutInfo.flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_UPDATE_AFTER_BIND_POOL_BIT;

    if (vkCreateDescriptorSetLayout(device, &sampleLayoutInfo, nullptr, &m_ssaoSampleDescLayout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSAO sample descriptor set layout");
    }

    // Allocate descriptor sets
    VkDescriptorSetAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
    allocInfo.descriptorPool = m_descriptorPool;

    std::vector<VkDescriptorSetLayout> ssaoLayouts(frameCount, m_ssaoDescriptorLayout);
    allocInfo.descriptorSetCount = frameCount;
    allocInfo.pSetLayouts = ssaoLayouts.data();
    m_ssaoDescriptorSets.resize(frameCount, VK_NULL_HANDLE);

    if (vkAllocateDescriptorSets(device, &allocInfo, m_ssaoDescriptorSets.data()) != VK_SUCCESS) {
        throw std::runtime_error("Failed to allocate SSAO descriptor sets");
    }

    allocInfo.descriptorSetCount = 1;
    allocInfo.pSetLayouts = &m_ssaoBlurDescLayout;
    if (vkAllocateDescriptorSets(device, &allocInfo, &m_ssaoBlurDescSet) != VK_SUCCESS) {
        throw std::runtime_error("Failed to allocate SSAO blur descriptor set");
    }

    allocInfo.pSetLayouts = &m_ssaoSampleDescLayout;
    if (vkAllocateDescriptorSets(device, &allocInfo, &m_ssaoSampleDescSet) != VK_SUCCESS) {
        throw std::runtime_error("Failed to allocate SSAO sample descriptor set");
    }

    std::cout << "[PostProcess] SSAO resources created" << std::endl;
}

void PostProcess::createSSAOPipeline() {
    auto device = m_context.getDevice();

    // Load shaders
    auto loadShader = [&](const std::string& filename) -> VkShaderModule {
        std::ifstream file(filename, std::ios::ate | std::ios::binary);
        if (!file.is_open()) {
            throw std::runtime_error("Failed to open shader file: " + filename);
        }

        size_t fileSize = static_cast<size_t>(file.tellg());
        std::vector<char> buffer(fileSize);
        file.seekg(0);
        file.read(buffer.data(), fileSize);
        file.close();

        VkShaderModuleCreateInfo createInfo{};
        createInfo.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
        createInfo.codeSize = buffer.size();
        createInfo.pCode = reinterpret_cast<const u32*>(buffer.data());

        VkShaderModule shaderModule;
        if (vkCreateShaderModule(device, &createInfo, nullptr, &shaderModule) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create shader module");
        }
        return shaderModule;
    };

    VkShaderModule vertModule = loadShader("shaders/ssao.vert.spv");
    VkShaderModule fragModule = loadShader("shaders/ssao.frag.spv");

    VkPipelineShaderStageCreateInfo vertStage{};
    vertStage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    vertStage.stage = VK_SHADER_STAGE_VERTEX_BIT;
    vertStage.module = vertModule;
    vertStage.pName = "main";

    VkPipelineShaderStageCreateInfo fragStage{};
    fragStage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    fragStage.stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    fragStage.module = fragModule;
    fragStage.pName = "main";

    VkPipelineShaderStageCreateInfo stages[] = {vertStage, fragStage};

    // Vertex input - fullscreen triangle, no vertex buffer
    VkPipelineVertexInputStateCreateInfo vertexInput{};
    vertexInput.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;

    VkPipelineInputAssemblyStateCreateInfo inputAssembly{};
    inputAssembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    inputAssembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;

    VkViewport viewport{};
    viewport.x = 0.0f;
    viewport.y = 0.0f;
    viewport.width = static_cast<float>(m_width);
    viewport.height = static_cast<float>(m_height);
    viewport.minDepth = 0.0f;
    viewport.maxDepth = 1.0f;

    VkRect2D scissor{};
    scissor.offset = {0, 0};
    scissor.extent = {m_width, m_height};

    VkPipelineViewportStateCreateInfo viewportState{};
    viewportState.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    viewportState.viewportCount = 1;
    viewportState.pViewports = &viewport;
    viewportState.scissorCount = 1;
    viewportState.pScissors = &scissor;

    VkPipelineRasterizationStateCreateInfo rasterizer{};
    rasterizer.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    rasterizer.polygonMode = VK_POLYGON_MODE_FILL;
    rasterizer.lineWidth = 1.0f;
    rasterizer.cullMode = VK_CULL_MODE_NONE;
    rasterizer.frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE;

    VkPipelineMultisampleStateCreateInfo multisampling{};
    multisampling.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    multisampling.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;

    VkPipelineColorBlendAttachmentState colorBlendAttachment{};
    colorBlendAttachment.colorWriteMask = VK_COLOR_COMPONENT_R_BIT;

    VkPipelineColorBlendStateCreateInfo colorBlending{};
    colorBlending.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    colorBlending.attachmentCount = 1;
    colorBlending.pAttachments = &colorBlendAttachment;

    // Dynamic states for viewport/scissor
    std::array<VkDynamicState, 2> dynamicStates = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo dynamicState{};
    dynamicState.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO;
    dynamicState.dynamicStateCount = static_cast<u32>(dynamicStates.size());
    dynamicState.pDynamicStates = dynamicStates.data();

    // Pipeline layout
    VkPipelineLayoutCreateInfo layoutInfo{};
    layoutInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    layoutInfo.setLayoutCount = 1;
    layoutInfo.pSetLayouts = &m_ssaoDescriptorLayout;

    if (vkCreatePipelineLayout(device, &layoutInfo, nullptr, &m_ssaoPipelineLayout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSAO pipeline layout");
    }

    VkGraphicsPipelineCreateInfo pipelineInfo{};
    pipelineInfo.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    pipelineInfo.stageCount = 2;
    pipelineInfo.pStages = stages;
    pipelineInfo.pVertexInputState = &vertexInput;
    pipelineInfo.pInputAssemblyState = &inputAssembly;
    pipelineInfo.pViewportState = &viewportState;
    pipelineInfo.pRasterizationState = &rasterizer;
    pipelineInfo.pMultisampleState = &multisampling;
    pipelineInfo.pColorBlendState = &colorBlending;
    pipelineInfo.pDynamicState = &dynamicState;
    pipelineInfo.layout = m_ssaoPipelineLayout;
    pipelineInfo.renderPass = m_ssaoRenderPass;
    pipelineInfo.subpass = 0;

    if (vkCreateGraphicsPipelines(device, m_context.getPipelineCache(), 1, &pipelineInfo,
                                   nullptr, &m_ssaoPipeline) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSAO pipeline");
    }

    vkDestroyShaderModule(device, vertModule, nullptr);
    vkDestroyShaderModule(device, fragModule, nullptr);

    std::cout << "[PostProcess] SSAO pipeline created" << std::endl;
}

void PostProcess::createBlurPipeline() {
    auto device = m_context.getDevice();

    // Load shaders
    auto loadShader = [&](const std::string& filename) -> VkShaderModule {
        std::ifstream file(filename, std::ios::ate | std::ios::binary);
        if (!file.is_open()) {
            throw std::runtime_error("Failed to open shader file: " + filename);
        }

        size_t fileSize = static_cast<size_t>(file.tellg());
        std::vector<char> buffer(fileSize);
        file.seekg(0);
        file.read(buffer.data(), fileSize);
        file.close();

        VkShaderModuleCreateInfo createInfo{};
        createInfo.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
        createInfo.codeSize = buffer.size();
        createInfo.pCode = reinterpret_cast<const u32*>(buffer.data());

        VkShaderModule shaderModule;
        if (vkCreateShaderModule(device, &createInfo, nullptr, &shaderModule) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create shader module");
        }
        return shaderModule;
    };

    VkShaderModule vertModule = loadShader("shaders/ssao.vert.spv");  // Reuse fullscreen vert
    VkShaderModule fragModule = loadShader("shaders/ssao_blur.frag.spv");

    VkPipelineShaderStageCreateInfo vertStage{};
    vertStage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    vertStage.stage = VK_SHADER_STAGE_VERTEX_BIT;
    vertStage.module = vertModule;
    vertStage.pName = "main";

    VkPipelineShaderStageCreateInfo fragStage{};
    fragStage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    fragStage.stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    fragStage.module = fragModule;
    fragStage.pName = "main";

    VkPipelineShaderStageCreateInfo stages[] = {vertStage, fragStage};

    VkPipelineVertexInputStateCreateInfo vertexInput{};
    vertexInput.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;

    VkPipelineInputAssemblyStateCreateInfo inputAssembly{};
    inputAssembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    inputAssembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;

    VkPipelineViewportStateCreateInfo viewportState{};
    viewportState.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    viewportState.viewportCount = 1;
    viewportState.scissorCount = 1;

    VkPipelineRasterizationStateCreateInfo rasterizer{};
    rasterizer.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    rasterizer.polygonMode = VK_POLYGON_MODE_FILL;
    rasterizer.lineWidth = 1.0f;
    rasterizer.cullMode = VK_CULL_MODE_NONE;

    VkPipelineMultisampleStateCreateInfo multisampling{};
    multisampling.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    multisampling.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;

    VkPipelineColorBlendAttachmentState colorBlendAttachment{};
    colorBlendAttachment.colorWriteMask = VK_COLOR_COMPONENT_R_BIT;

    VkPipelineColorBlendStateCreateInfo colorBlending{};
    colorBlending.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    colorBlending.attachmentCount = 1;
    colorBlending.pAttachments = &colorBlendAttachment;

    std::array<VkDynamicState, 2> dynamicStates = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo dynamicState{};
    dynamicState.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO;
    dynamicState.dynamicStateCount = static_cast<u32>(dynamicStates.size());
    dynamicState.pDynamicStates = dynamicStates.data();

    // Push constant for blur direction
    VkPushConstantRange pushConstant{};
    pushConstant.stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
    pushConstant.offset = 0;
    pushConstant.size = sizeof(vec4);  // direction + depthThreshold

    VkPipelineLayoutCreateInfo layoutInfo{};
    layoutInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    layoutInfo.setLayoutCount = 1;
    layoutInfo.pSetLayouts = &m_ssaoBlurDescLayout;
    layoutInfo.pushConstantRangeCount = 1;
    layoutInfo.pPushConstantRanges = &pushConstant;

    if (vkCreatePipelineLayout(device, &layoutInfo, nullptr, &m_ssaoBlurPipelineLayout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create blur pipeline layout");
    }

    VkGraphicsPipelineCreateInfo pipelineInfo{};
    pipelineInfo.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    pipelineInfo.stageCount = 2;
    pipelineInfo.pStages = stages;
    pipelineInfo.pVertexInputState = &vertexInput;
    pipelineInfo.pInputAssemblyState = &inputAssembly;
    pipelineInfo.pViewportState = &viewportState;
    pipelineInfo.pRasterizationState = &rasterizer;
    pipelineInfo.pMultisampleState = &multisampling;
    pipelineInfo.pColorBlendState = &colorBlending;
    pipelineInfo.pDynamicState = &dynamicState;
    pipelineInfo.layout = m_ssaoBlurPipelineLayout;
    pipelineInfo.renderPass = m_ssaoRenderPass;
    pipelineInfo.subpass = 0;

    if (vkCreateGraphicsPipelines(device, m_context.getPipelineCache(), 1, &pipelineInfo,
                                   nullptr, &m_ssaoBlurPipeline) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSAO blur pipeline");
    }

    vkDestroyShaderModule(device, vertModule, nullptr);
    vkDestroyShaderModule(device, fragModule, nullptr);

    std::cout << "[PostProcess] Blur pipeline created" << std::endl;
}

void PostProcess::createFullscreenQuad() {
    // Actually not needed since we use a fullscreen triangle generated in the vertex shader
    // Keep this function for potential future use with actual geometry
}

void PostProcess::generateSSAO(VkCommandBuffer cmd, VkImageView depthView, VkImageView normalView,
                                const mat4& projection, const mat4& view, u32 frameIndex) {
    if (!m_ssaoConfig.enabled) return;
    if (frameIndex >= m_ssaoDescriptorSets.size()) return;

    // Update uniform buffer
    struct SSAOUniforms {
        mat4 projection;
        mat4 view;
        vec4 samples[64];
        vec4 params;  // radius, bias, intensity, power
        vec2 noiseScale;
        i32 kernelSize;
        f32 padding;
    } uniforms;

    uniforms.projection = projection;
    uniforms.view = view;
    memcpy(uniforms.samples, m_ssaoKernel.data(), sizeof(vec4) * 64);
    uniforms.params = vec4(m_ssaoConfig.radius, m_ssaoConfig.bias,
                          m_ssaoConfig.intensity, m_ssaoConfig.power);
    uniforms.noiseScale = vec2(float(m_width) / 4.0f, float(m_height) / 4.0f);
    uniforms.kernelSize = m_ssaoConfig.kernelSize;

    memcpy(m_ssaoUniformMapped, &uniforms, sizeof(uniforms));

    // Update descriptor set with current depth view
    VkDescriptorImageInfo depthInfo{};
    depthInfo.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    depthInfo.imageView = depthView;
    depthInfo.sampler = m_ssaoSampler;

    VkDescriptorImageInfo normalInfo{};
    normalInfo.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    normalInfo.imageView = normalView ? normalView : depthView;  // Fallback to depth if no normals
    normalInfo.sampler = m_ssaoSampler;

    VkDescriptorImageInfo noiseInfo{};
    noiseInfo.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    noiseInfo.imageView = m_noiseView;
    noiseInfo.sampler = m_noiseSampler;

    VkDescriptorBufferInfo uniformInfo{};
    uniformInfo.buffer = m_ssaoUniformBuffer;
    uniformInfo.offset = 0;
    uniformInfo.range = sizeof(uniforms);

    std::array<VkWriteDescriptorSet, 4> writes{};

    writes[0].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    writes[0].dstSet = m_ssaoDescriptorSets[frameIndex];
    writes[0].dstBinding = 0;
    writes[0].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    writes[0].descriptorCount = 1;
    writes[0].pImageInfo = &depthInfo;

    writes[1].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    writes[1].dstSet = m_ssaoDescriptorSets[frameIndex];
    writes[1].dstBinding = 1;
    writes[1].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    writes[1].descriptorCount = 1;
    writes[1].pImageInfo = &normalInfo;

    writes[2].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    writes[2].dstSet = m_ssaoDescriptorSets[frameIndex];
    writes[2].dstBinding = 2;
    writes[2].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    writes[2].descriptorCount = 1;
    writes[2].pImageInfo = &noiseInfo;

    writes[3].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    writes[3].dstSet = m_ssaoDescriptorSets[frameIndex];
    writes[3].dstBinding = 3;
    writes[3].descriptorType = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER;
    writes[3].descriptorCount = 1;
    writes[3].pBufferInfo = &uniformInfo;

    vkUpdateDescriptorSets(m_context.getDevice(), static_cast<u32>(writes.size()),
                          writes.data(), 0, nullptr);

    // Begin SSAO render pass
    VkRenderPassBeginInfo renderPassInfo{};
    renderPassInfo.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;
    renderPassInfo.renderPass = m_ssaoRenderPass;
    renderPassInfo.framebuffer = m_ssaoFramebuffer;
    renderPassInfo.renderArea.offset = {0, 0};
    renderPassInfo.renderArea.extent = {m_width, m_height};

    VkClearValue clearValue{};
    clearValue.color = {{1.0f, 1.0f, 1.0f, 1.0f}};
    renderPassInfo.clearValueCount = 1;
    renderPassInfo.pClearValues = &clearValue;

    vkCmdBeginRenderPass(cmd, &renderPassInfo, VK_SUBPASS_CONTENTS_INLINE);

    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_ssaoPipeline);
    vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_ssaoPipelineLayout,
                           0, 1, &m_ssaoDescriptorSets[frameIndex], 0, nullptr);

    // Set dynamic viewport/scissor
    VkViewport viewport{};
    viewport.x = 0.0f;
    viewport.y = 0.0f;
    viewport.width = static_cast<float>(m_width);
    viewport.height = static_cast<float>(m_height);
    viewport.minDepth = 0.0f;
    viewport.maxDepth = 1.0f;
    vkCmdSetViewport(cmd, 0, 1, &viewport);

    VkRect2D scissor{};
    scissor.offset = {0, 0};
    scissor.extent = {m_width, m_height};
    vkCmdSetScissor(cmd, 0, 1, &scissor);

    // Draw fullscreen triangle
    vkCmdDraw(cmd, 3, 1, 0, 0);

    vkCmdEndRenderPass(cmd);

    // Update sample descriptor set for main shader
    VkDescriptorImageInfo ssaoSampleInfo{};
    ssaoSampleInfo.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    ssaoSampleInfo.imageView = m_ssaoView;  // Use raw SSAO for now (blur TODO)
    ssaoSampleInfo.sampler = m_ssaoSampler;

    VkWriteDescriptorSet sampleWrite{};
    sampleWrite.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    sampleWrite.dstSet = m_ssaoSampleDescSet;
    sampleWrite.dstBinding = 0;
    sampleWrite.descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    sampleWrite.descriptorCount = 1;
    sampleWrite.pImageInfo = &ssaoSampleInfo;

    vkUpdateDescriptorSets(m_context.getDevice(), 1, &sampleWrite, 0, nullptr);
}

void PostProcess::createHDRResources() {
    auto device = m_context.getDevice();

    // Create sampler
    VkSamplerCreateInfo samplerInfo{};
    samplerInfo.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
    samplerInfo.magFilter = VK_FILTER_LINEAR;
    samplerInfo.minFilter = VK_FILTER_LINEAR;
    samplerInfo.addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.borderColor = VK_BORDER_COLOR_FLOAT_OPAQUE_BLACK;

    if (vkCreateSampler(device, &samplerInfo, nullptr, &m_hdrSampler) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create HDR sampler");
    }

    // Create HDR render pass with 3 attachments: color, normal (for SSR), depth
    std::array<VkAttachmentDescription, 3> attachments{};

    // Color attachment (location 0)
    attachments[0].format = VK_FORMAT_R16G16B16A16_SFLOAT;
    attachments[0].samples = VK_SAMPLE_COUNT_1_BIT;
    attachments[0].loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    attachments[0].storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    attachments[0].stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    attachments[0].stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    attachments[0].initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    attachments[0].finalLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

    // Normal + roughness attachment for SSR (location 1)
    // xyz = world normal (packed as *0.5+0.5), w = roughness
    attachments[1].format = VK_FORMAT_R16G16B16A16_SFLOAT;
    attachments[1].samples = VK_SAMPLE_COUNT_1_BIT;
    attachments[1].loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    attachments[1].storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    attachments[1].stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    attachments[1].stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    attachments[1].initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    attachments[1].finalLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

    // Depth attachment
    attachments[2].format = VK_FORMAT_D32_SFLOAT;
    attachments[2].samples = VK_SAMPLE_COUNT_1_BIT;
    attachments[2].loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    attachments[2].storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    attachments[2].stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    attachments[2].stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    attachments[2].initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    attachments[2].finalLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

    // Color attachments (HDR color + normal)
    std::array<VkAttachmentReference, 2> colorRefs{};
    colorRefs[0].attachment = 0;
    colorRefs[0].layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;
    colorRefs[1].attachment = 1;
    colorRefs[1].layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;

    VkAttachmentReference depthRef{};
    depthRef.attachment = 2;
    depthRef.layout = VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL;

    VkSubpassDescription subpass{};
    subpass.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    subpass.colorAttachmentCount = static_cast<u32>(colorRefs.size());
    subpass.pColorAttachments = colorRefs.data();
    subpass.pDepthStencilAttachment = &depthRef;

    VkRenderPassCreateInfo renderPassInfo{};
    renderPassInfo.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO;
    renderPassInfo.attachmentCount = static_cast<u32>(attachments.size());
    renderPassInfo.pAttachments = attachments.data();
    renderPassInfo.subpassCount = 1;
    renderPassInfo.pSubpasses = &subpass;

    if (vkCreateRenderPass(device, &renderPassInfo, nullptr, &m_hdrRenderPass) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create HDR render pass");
    }

    createHDRTargets();

    std::cout << "[PostProcess] HDR resources created" << std::endl;
}

void PostProcess::createHDRTargets() {
    auto device = m_context.getDevice();

    // Create HDR color buffer (RGBA16F for high dynamic range)
    m_context.createImage(m_width, m_height, VK_FORMAT_R16G16B16A16_SFLOAT, VK_IMAGE_TILING_OPTIMAL,
                         VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
                         VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
                         m_hdrColorImage, m_hdrColorMemory);

    m_hdrColorView = m_context.createImageView(m_hdrColorImage, VK_FORMAT_R16G16B16A16_SFLOAT,
                                               VK_IMAGE_ASPECT_COLOR_BIT);

    // Create normal + roughness buffer for SSR (xyz = normal, w = roughness)
    m_context.createImage(m_width, m_height, VK_FORMAT_R16G16B16A16_SFLOAT, VK_IMAGE_TILING_OPTIMAL,
                         VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
                         VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
                         m_hdrNormalImage, m_hdrNormalMemory);

    m_hdrNormalView = m_context.createImageView(m_hdrNormalImage, VK_FORMAT_R16G16B16A16_SFLOAT,
                                                VK_IMAGE_ASPECT_COLOR_BIT);

    // Create HDR depth buffer
    m_context.createImage(m_width, m_height, VK_FORMAT_D32_SFLOAT, VK_IMAGE_TILING_OPTIMAL,
                         VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
                         VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
                         m_hdrDepthImage, m_hdrDepthMemory);

    m_hdrDepthView = m_context.createImageView(m_hdrDepthImage, VK_FORMAT_D32_SFLOAT,
                                               VK_IMAGE_ASPECT_DEPTH_BIT);

    // Create framebuffer with 3 attachments: color, normal, depth
    std::array<VkImageView, 3> fbAttachments = {m_hdrColorView, m_hdrNormalView, m_hdrDepthView};

    VkFramebufferCreateInfo fbInfo{};
    fbInfo.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO;
    fbInfo.renderPass = m_hdrRenderPass;
    fbInfo.attachmentCount = static_cast<u32>(fbAttachments.size());
    fbInfo.pAttachments = fbAttachments.data();
    fbInfo.width = m_width;
    fbInfo.height = m_height;
    fbInfo.layers = 1;

    if (vkCreateFramebuffer(device, &fbInfo, nullptr, &m_hdrFramebuffer) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create HDR framebuffer");
    }
}

void PostProcess::createBloomResources() {
    auto device = m_context.getDevice();

    // Create bloom images (half resolution for efficiency)
    u32 bloomWidth = m_width / 2;
    u32 bloomHeight = m_height / 2;

    for (int i = 0; i < 2; i++) {
        m_context.createImage(bloomWidth, bloomHeight, VK_FORMAT_R16G16B16A16_SFLOAT, VK_IMAGE_TILING_OPTIMAL,
                             VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
                             VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
                             m_bloomImages[i], m_bloomMemory[i]);

        m_bloomViews[i] = m_context.createImageView(m_bloomImages[i], VK_FORMAT_R16G16B16A16_SFLOAT,
                                                   VK_IMAGE_ASPECT_COLOR_BIT);
    }
    m_bloomResultView = m_bloomViews[0];  // Final result in first buffer

    // Create bloom sampler
    VkSamplerCreateInfo samplerInfo{};
    samplerInfo.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
    samplerInfo.magFilter = VK_FILTER_LINEAR;
    samplerInfo.minFilter = VK_FILTER_LINEAR;
    samplerInfo.addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;

    if (vkCreateSampler(device, &samplerInfo, nullptr, &m_bloomSampler) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create bloom sampler");
    }

    // Create bloom render pass
    VkAttachmentDescription attachment{};
    attachment.format = VK_FORMAT_R16G16B16A16_SFLOAT;
    attachment.samples = VK_SAMPLE_COUNT_1_BIT;
    attachment.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    attachment.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    attachment.initialLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    attachment.finalLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

    VkAttachmentReference colorRef{};
    colorRef.attachment = 0;
    colorRef.layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;

    VkSubpassDescription subpass{};
    subpass.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    subpass.colorAttachmentCount = 1;
    subpass.pColorAttachments = &colorRef;

    VkRenderPassCreateInfo renderPassInfo{};
    renderPassInfo.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO;
    renderPassInfo.attachmentCount = 1;
    renderPassInfo.pAttachments = &attachment;
    renderPassInfo.subpassCount = 1;
    renderPassInfo.pSubpasses = &subpass;

    if (vkCreateRenderPass(device, &renderPassInfo, nullptr, &m_bloomRenderPass) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create bloom render pass");
    }

    // Create framebuffers
    for (int i = 0; i < 2; i++) {
        VkFramebufferCreateInfo fbInfo{};
        fbInfo.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO;
        fbInfo.renderPass = m_bloomRenderPass;
        fbInfo.attachmentCount = 1;
        fbInfo.pAttachments = &m_bloomViews[i];
        fbInfo.width = bloomWidth;
        fbInfo.height = bloomHeight;
        fbInfo.layers = 1;

        if (vkCreateFramebuffer(device, &fbInfo, nullptr, &m_bloomFramebuffers[i]) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create bloom framebuffer");
        }
    }

    // Ensure bloom images start in shader-read layout (for disabled bloom path).
    for (int i = 0; i < 2; i++) {
        m_context.transitionImageLayout(m_bloomImages[i], VK_FORMAT_R16G16B16A16_SFLOAT,
                                        VK_IMAGE_LAYOUT_UNDEFINED,
                                        VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
    }

    std::cout << "[PostProcess] Bloom resources created" << std::endl;
}

void PostProcess::createBloomPipelines() {
    auto device = m_context.getDevice();

    // Load shader helper
    auto loadShader = [&](const std::string& filename) -> VkShaderModule {
        std::ifstream file(filename, std::ios::ate | std::ios::binary);
        if (!file.is_open()) {
            throw std::runtime_error("Failed to open shader file: " + filename);
        }
        size_t fileSize = static_cast<size_t>(file.tellg());
        std::vector<char> buffer(fileSize);
        file.seekg(0);
        file.read(buffer.data(), fileSize);
        file.close();

        VkShaderModuleCreateInfo createInfo{};
        createInfo.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
        createInfo.codeSize = buffer.size();
        createInfo.pCode = reinterpret_cast<const u32*>(buffer.data());

        VkShaderModule shaderModule;
        if (vkCreateShaderModule(device, &createInfo, nullptr, &shaderModule) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create shader module");
        }
        return shaderModule;
    };

    // Create descriptor set layout for bloom (single texture)
    VkDescriptorSetLayoutBinding binding{};
    binding.binding = 0;
    binding.descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    binding.descriptorCount = 1;
    binding.stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    VkDescriptorSetLayoutCreateInfo layoutInfo{};
    layoutInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
    layoutInfo.bindingCount = 1;
    layoutInfo.pBindings = &binding;

    if (vkCreateDescriptorSetLayout(device, &layoutInfo, nullptr, &m_bloomDescLayout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create bloom descriptor set layout");
    }

    // Push constant for bloom parameters
    VkPushConstantRange pushConstant{};
    pushConstant.stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
    pushConstant.offset = 0;
    pushConstant.size = sizeof(vec4);  // threshold, softThreshold, exposure, padding OR direction, texelSize

    VkPipelineLayoutCreateInfo pipelineLayoutInfo{};
    pipelineLayoutInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    pipelineLayoutInfo.setLayoutCount = 1;
    pipelineLayoutInfo.pSetLayouts = &m_bloomDescLayout;
    pipelineLayoutInfo.pushConstantRangeCount = 1;
    pipelineLayoutInfo.pPushConstantRanges = &pushConstant;

    if (vkCreatePipelineLayout(device, &pipelineLayoutInfo, nullptr, &m_bloomPipelineLayout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create bloom pipeline layout");
    }

    // Allocate descriptor sets for ping-pong blur (per frame)
    u32 frameCount = m_context.getMaxFramesInFlight();
    m_bloomDescSets.resize(frameCount);

    VkDescriptorSetAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
    allocInfo.descriptorPool = m_descriptorPool;
    allocInfo.descriptorSetCount = 1;

    for (u32 frame = 0; frame < frameCount; ++frame) {
        for (int i = 0; i < 2; i++) {
            allocInfo.pSetLayouts = &m_bloomDescLayout;
            if (vkAllocateDescriptorSets(device, &allocInfo, &m_bloomDescSets[frame][i]) != VK_SUCCESS) {
                throw std::runtime_error("Failed to allocate bloom descriptor set");
            }
        }
    }

    // Common pipeline state
    VkShaderModule vertModule = loadShader("shaders/ssao.vert.spv");  // Reuse fullscreen vertex
    VkShaderModule brightFragModule = loadShader("shaders/bloom_bright.frag.spv");
    VkShaderModule blurFragModule = loadShader("shaders/bloom_blur.frag.spv");

    VkPipelineShaderStageCreateInfo vertStage{};
    vertStage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    vertStage.stage = VK_SHADER_STAGE_VERTEX_BIT;
    vertStage.module = vertModule;
    vertStage.pName = "main";

    VkPipelineVertexInputStateCreateInfo vertexInput{};
    vertexInput.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;

    VkPipelineInputAssemblyStateCreateInfo inputAssembly{};
    inputAssembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    inputAssembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;

    VkPipelineViewportStateCreateInfo viewportState{};
    viewportState.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    viewportState.viewportCount = 1;
    viewportState.scissorCount = 1;

    VkPipelineRasterizationStateCreateInfo rasterizer{};
    rasterizer.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    rasterizer.polygonMode = VK_POLYGON_MODE_FILL;
    rasterizer.lineWidth = 1.0f;
    rasterizer.cullMode = VK_CULL_MODE_NONE;

    VkPipelineMultisampleStateCreateInfo multisampling{};
    multisampling.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    multisampling.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;

    VkPipelineColorBlendAttachmentState colorBlendAttachment{};
    colorBlendAttachment.colorWriteMask = VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT |
                                          VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;

    VkPipelineColorBlendStateCreateInfo colorBlending{};
    colorBlending.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    colorBlending.attachmentCount = 1;
    colorBlending.pAttachments = &colorBlendAttachment;

    std::array<VkDynamicState, 2> dynamicStates = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo dynamicState{};
    dynamicState.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO;
    dynamicState.dynamicStateCount = static_cast<u32>(dynamicStates.size());
    dynamicState.pDynamicStates = dynamicStates.data();

    VkGraphicsPipelineCreateInfo pipelineInfo{};
    pipelineInfo.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    pipelineInfo.stageCount = 2;
    pipelineInfo.pVertexInputState = &vertexInput;
    pipelineInfo.pInputAssemblyState = &inputAssembly;
    pipelineInfo.pViewportState = &viewportState;
    pipelineInfo.pRasterizationState = &rasterizer;
    pipelineInfo.pMultisampleState = &multisampling;
    pipelineInfo.pColorBlendState = &colorBlending;
    pipelineInfo.pDynamicState = &dynamicState;
    pipelineInfo.layout = m_bloomPipelineLayout;
    pipelineInfo.renderPass = m_bloomRenderPass;
    pipelineInfo.subpass = 0;

    // Create bright pass pipeline
    VkPipelineShaderStageCreateInfo brightFragStage{};
    brightFragStage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    brightFragStage.stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    brightFragStage.module = brightFragModule;
    brightFragStage.pName = "main";

    VkPipelineShaderStageCreateInfo brightStages[] = {vertStage, brightFragStage};
    pipelineInfo.pStages = brightStages;

    if (vkCreateGraphicsPipelines(device, m_context.getPipelineCache(), 1, &pipelineInfo,
                                   nullptr, &m_bloomBrightPipeline) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create bloom bright pipeline");
    }

    // Create blur pipeline
    VkPipelineShaderStageCreateInfo blurFragStage{};
    blurFragStage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    blurFragStage.stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    blurFragStage.module = blurFragModule;
    blurFragStage.pName = "main";

    VkPipelineShaderStageCreateInfo blurStages[] = {vertStage, blurFragStage};
    pipelineInfo.pStages = blurStages;

    if (vkCreateGraphicsPipelines(device, m_context.getPipelineCache(), 1, &pipelineInfo,
                                   nullptr, &m_bloomBlurPipeline) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create bloom blur pipeline");
    }

    vkDestroyShaderModule(device, vertModule, nullptr);
    vkDestroyShaderModule(device, brightFragModule, nullptr);
    vkDestroyShaderModule(device, blurFragModule, nullptr);

    std::cout << "[PostProcess] Bloom pipelines created" << std::endl;
}

void PostProcess::createCompositePipeline(VkRenderPass renderPass, VkSampleCountFlagBits samples) {
    auto device = m_context.getDevice();

    if (m_compositePipeline || m_compositePipelineLayout || m_compositeDescLayout) {
        cleanupComposite();
    }

    // Load shader helper
    auto loadShader = [&](const std::string& filename) -> VkShaderModule {
        std::ifstream file(filename, std::ios::ate | std::ios::binary);
        if (!file.is_open()) {
            throw std::runtime_error("Failed to open shader file: " + filename);
        }
        size_t fileSize = static_cast<size_t>(file.tellg());
        std::vector<char> buffer(fileSize);
        file.seekg(0);
        file.read(buffer.data(), fileSize);
        file.close();

        VkShaderModuleCreateInfo createInfo{};
        createInfo.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
        createInfo.codeSize = buffer.size();
        createInfo.pCode = reinterpret_cast<const u32*>(buffer.data());

        VkShaderModule shaderModule;
        if (vkCreateShaderModule(device, &createInfo, nullptr, &shaderModule) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create shader module");
        }
        return shaderModule;
    };

    // Create descriptor set layout for composite (5 textures: HDR, SSAO, bloom, SSR, normalRoughness)
    std::array<VkDescriptorSetLayoutBinding, 5> bindings{};

    bindings[0].binding = 0;  // HDR scene
    bindings[0].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    bindings[0].descriptorCount = 1;
    bindings[0].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    bindings[1].binding = 1;  // SSAO
    bindings[1].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    bindings[1].descriptorCount = 1;
    bindings[1].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    bindings[2].binding = 2;  // Bloom
    bindings[2].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    bindings[2].descriptorCount = 1;
    bindings[2].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    bindings[3].binding = 3;  // SSR
    bindings[3].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    bindings[3].descriptorCount = 1;
    bindings[3].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    bindings[4].binding = 4;  // Normal + Roughness (for SSR blend)
    bindings[4].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    bindings[4].descriptorCount = 1;
    bindings[4].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    VkDescriptorSetLayoutCreateInfo layoutInfo{};
    layoutInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
    layoutInfo.bindingCount = static_cast<u32>(bindings.size());
    layoutInfo.pBindings = bindings.data();

    if (vkCreateDescriptorSetLayout(device, &layoutInfo, nullptr, &m_compositeDescLayout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create composite descriptor set layout");
    }

    // Push constant for composite parameters (12 floats to match shader)
    VkPushConstantRange pushConstant{};
    pushConstant.stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
    pushConstant.offset = 0;
    pushConstant.size = sizeof(f32) * 12;  // bloomIntensity, exposure, ssaoIntensity, enableSSAO, enableBloom, tonemapMode, debugMode, nearPlane, farPlane, enableSSR, ssrIntensity, padding

    VkPipelineLayoutCreateInfo pipelineLayoutInfo{};
    pipelineLayoutInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    pipelineLayoutInfo.setLayoutCount = 1;
    pipelineLayoutInfo.pSetLayouts = &m_compositeDescLayout;
    pipelineLayoutInfo.pushConstantRangeCount = 1;
    pipelineLayoutInfo.pPushConstantRanges = &pushConstant;

    if (vkCreatePipelineLayout(device, &pipelineLayoutInfo, nullptr, &m_compositePipelineLayout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create composite pipeline layout");
    }

    // Allocate descriptor sets (one per frame in flight)
    u32 frameCount = m_context.getMaxFramesInFlight();
    std::vector<VkDescriptorSetLayout> layouts(frameCount, m_compositeDescLayout);

    VkDescriptorSetAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
    allocInfo.descriptorPool = m_descriptorPool;
    allocInfo.descriptorSetCount = frameCount;
    allocInfo.pSetLayouts = layouts.data();

    m_compositeDescSets.resize(frameCount, VK_NULL_HANDLE);
    if (vkAllocateDescriptorSets(device, &allocInfo, m_compositeDescSets.data()) != VK_SUCCESS) {
        throw std::runtime_error("Failed to allocate composite descriptor sets");
    }

    // Load shaders
    VkShaderModule vertModule = loadShader("shaders/ssao.vert.spv");
    VkShaderModule fragModule = loadShader("shaders/composite.frag.spv");

    VkPipelineShaderStageCreateInfo vertStage{};
    vertStage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    vertStage.stage = VK_SHADER_STAGE_VERTEX_BIT;
    vertStage.module = vertModule;
    vertStage.pName = "main";

    VkPipelineShaderStageCreateInfo fragStage{};
    fragStage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    fragStage.stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    fragStage.module = fragModule;
    fragStage.pName = "main";

    VkPipelineShaderStageCreateInfo stages[] = {vertStage, fragStage};

    VkPipelineVertexInputStateCreateInfo vertexInput{};
    vertexInput.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;

    VkPipelineInputAssemblyStateCreateInfo inputAssembly{};
    inputAssembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    inputAssembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;

    VkPipelineViewportStateCreateInfo viewportState{};
    viewportState.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    viewportState.viewportCount = 1;
    viewportState.scissorCount = 1;

    VkPipelineRasterizationStateCreateInfo rasterizer{};
    rasterizer.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    rasterizer.polygonMode = VK_POLYGON_MODE_FILL;
    rasterizer.lineWidth = 1.0f;
    rasterizer.cullMode = VK_CULL_MODE_NONE;

    VkPipelineMultisampleStateCreateInfo multisampling{};
    multisampling.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    multisampling.rasterizationSamples = samples;

    VkPipelineColorBlendAttachmentState colorBlendAttachment{};
    colorBlendAttachment.colorWriteMask = VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT |
                                          VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;

    VkPipelineColorBlendStateCreateInfo colorBlending{};
    colorBlending.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    colorBlending.attachmentCount = 1;
    colorBlending.pAttachments = &colorBlendAttachment;

    VkPipelineDepthStencilStateCreateInfo depthStencil{};
    depthStencil.sType = VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO;
    depthStencil.depthTestEnable = VK_FALSE;
    depthStencil.depthWriteEnable = VK_FALSE;
    depthStencil.depthCompareOp = VK_COMPARE_OP_ALWAYS;
    depthStencil.stencilTestEnable = VK_FALSE;

    std::array<VkDynamicState, 2> dynamicStates = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo dynamicState{};
    dynamicState.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO;
    dynamicState.dynamicStateCount = static_cast<u32>(dynamicStates.size());
    dynamicState.pDynamicStates = dynamicStates.data();

    VkGraphicsPipelineCreateInfo pipelineInfo{};
    pipelineInfo.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    pipelineInfo.stageCount = 2;
    pipelineInfo.pStages = stages;
    pipelineInfo.pVertexInputState = &vertexInput;
    pipelineInfo.pInputAssemblyState = &inputAssembly;
    pipelineInfo.pViewportState = &viewportState;
    pipelineInfo.pRasterizationState = &rasterizer;
    pipelineInfo.pMultisampleState = &multisampling;
    pipelineInfo.pDepthStencilState = &depthStencil;
    pipelineInfo.pColorBlendState = &colorBlending;
    pipelineInfo.pDynamicState = &dynamicState;
    pipelineInfo.layout = m_compositePipelineLayout;
    pipelineInfo.renderPass = renderPass;
    pipelineInfo.subpass = 0;

    if (vkCreateGraphicsPipelines(device, m_context.getPipelineCache(), 1, &pipelineInfo,
                                   nullptr, &m_compositePipeline) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create composite pipeline");
    }

    vkDestroyShaderModule(device, vertModule, nullptr);
    vkDestroyShaderModule(device, fragModule, nullptr);

    std::cout << "[PostProcess] Composite pipeline created" << std::endl;
}

void PostProcess::generateBloom(VkCommandBuffer cmd, u32 frameIndex) {
    if (!m_bloomConfig.enabled) return;
    if (frameIndex >= m_bloomDescSets.size()) return;

    u32 bloomWidth = m_width / 2;
    u32 bloomHeight = m_height / 2;

    auto& bloomSets = m_bloomDescSets[frameIndex];

    // Update descriptor set 0 to read from HDR scene
    VkDescriptorImageInfo hdrInfo{};
    hdrInfo.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    hdrInfo.imageView = m_hdrColorView;
    hdrInfo.sampler = m_hdrSampler;

    VkWriteDescriptorSet write{};
    write.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    write.dstSet = bloomSets[0];
    write.dstBinding = 0;
    write.descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    write.descriptorCount = 1;
    write.pImageInfo = &hdrInfo;

    vkUpdateDescriptorSets(m_context.getDevice(), 1, &write, 0, nullptr);

    // Bright pass - extract bright pixels from HDR scene into bloom buffer 0
    VkRenderPassBeginInfo renderPassInfo{};
    renderPassInfo.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;
    renderPassInfo.renderPass = m_bloomRenderPass;
    renderPassInfo.framebuffer = m_bloomFramebuffers[0];
    renderPassInfo.renderArea.offset = {0, 0};
    renderPassInfo.renderArea.extent = {bloomWidth, bloomHeight};

    VkClearValue clearValue{};
    clearValue.color = {{0.0f, 0.0f, 0.0f, 0.0f}};
    renderPassInfo.clearValueCount = 1;
    renderPassInfo.pClearValues = &clearValue;

    vkCmdBeginRenderPass(cmd, &renderPassInfo, VK_SUBPASS_CONTENTS_INLINE);

    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_bloomBrightPipeline);
    vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_bloomPipelineLayout,
                           0, 1, &bloomSets[0], 0, nullptr);

    // Push bloom bright params: threshold, softThreshold, intensity, padding
    vec4 brightParams(m_bloomConfig.threshold, m_bloomConfig.softThreshold, m_compositeConfig.exposure, 0.0f);
    vkCmdPushConstants(cmd, m_bloomPipelineLayout, VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof(vec4), &brightParams);

    VkViewport viewport{};
    viewport.x = 0.0f;
    viewport.y = 0.0f;
    viewport.width = static_cast<float>(bloomWidth);
    viewport.height = static_cast<float>(bloomHeight);
    viewport.minDepth = 0.0f;
    viewport.maxDepth = 1.0f;
    vkCmdSetViewport(cmd, 0, 1, &viewport);

    VkRect2D scissor{};
    scissor.offset = {0, 0};
    scissor.extent = {bloomWidth, bloomHeight};
    vkCmdSetScissor(cmd, 0, 1, &scissor);

    vkCmdDraw(cmd, 3, 1, 0, 0);
    vkCmdEndRenderPass(cmd);

    // Ping-pong blur passes
    vec2 texelSize(1.0f / float(bloomWidth), 1.0f / float(bloomHeight));

    for (u32 i = 0; i < m_bloomConfig.iterations; i++) {
        // Horizontal blur: buffer 0 -> buffer 1
        VkDescriptorImageInfo inputInfo{};
        inputInfo.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
        inputInfo.imageView = m_bloomViews[0];
        inputInfo.sampler = m_bloomSampler;

        write.dstSet = bloomSets[1];
        write.pImageInfo = &inputInfo;
        vkUpdateDescriptorSets(m_context.getDevice(), 1, &write, 0, nullptr);

        renderPassInfo.framebuffer = m_bloomFramebuffers[1];
        vkCmdBeginRenderPass(cmd, &renderPassInfo, VK_SUBPASS_CONTENTS_INLINE);

        vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_bloomBlurPipeline);
        vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_bloomPipelineLayout,
                               0, 1, &bloomSets[1], 0, nullptr);

        // Horizontal blur: direction = (1, 0)
        vec4 blurParams(1.0f, 0.0f, texelSize.x, texelSize.y);
        vkCmdPushConstants(cmd, m_bloomPipelineLayout, VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof(vec4), &blurParams);

        vkCmdSetViewport(cmd, 0, 1, &viewport);
        vkCmdSetScissor(cmd, 0, 1, &scissor);
        vkCmdDraw(cmd, 3, 1, 0, 0);
        vkCmdEndRenderPass(cmd);

        // Vertical blur: buffer 1 -> buffer 0
        inputInfo.imageView = m_bloomViews[1];
        write.dstSet = bloomSets[0];
        write.pImageInfo = &inputInfo;
        vkUpdateDescriptorSets(m_context.getDevice(), 1, &write, 0, nullptr);

        renderPassInfo.framebuffer = m_bloomFramebuffers[0];
        vkCmdBeginRenderPass(cmd, &renderPassInfo, VK_SUBPASS_CONTENTS_INLINE);

        vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_bloomBlurPipeline);
        vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_bloomPipelineLayout,
                               0, 1, &bloomSets[0], 0, nullptr);

        // Vertical blur: direction = (0, 1)
        blurParams = vec4(0.0f, 1.0f, texelSize.x, texelSize.y);
        vkCmdPushConstants(cmd, m_bloomPipelineLayout, VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof(vec4), &blurParams);

        vkCmdSetViewport(cmd, 0, 1, &viewport);
        vkCmdSetScissor(cmd, 0, 1, &scissor);
        vkCmdDraw(cmd, 3, 1, 0, 0);
        vkCmdEndRenderPass(cmd);
    }

    // Final result is in m_bloomViews[0]
    m_bloomResultView = m_bloomViews[0];
}

void PostProcess::composite(VkCommandBuffer cmd, VkRenderPass renderPass, VkFramebuffer framebuffer,
                            VkExtent2D extent, u32 frameIndex, bool beginRenderPass, bool endRenderPass) {
    // Update composite descriptor set
    if (frameIndex >= m_compositeDescSets.size()) {
        return;
    }

    VkDescriptorSet compositeSet = m_compositeDescSets[frameIndex];

    std::array<VkDescriptorImageInfo, 5> imageInfos{};

    // HDR scene
    imageInfos[0].imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    imageInfos[0].imageView = m_hdrColorView;
    imageInfos[0].sampler = m_hdrSampler;

    // SSAO (use blurred if available, otherwise raw)
    imageInfos[1].imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    imageInfos[1].imageView = m_ssaoBlurredView ? m_ssaoBlurredView : m_ssaoView;
    imageInfos[1].sampler = m_ssaoSampler;

    // Bloom (use HDR view as fallback if bloom not ready)
    imageInfos[2].imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    imageInfos[2].imageView = m_bloomResultView ? m_bloomResultView : m_hdrColorView;
    imageInfos[2].sampler = m_bloomSampler ? m_bloomSampler : m_hdrSampler;

    // SSR (use HDR view as fallback if SSR not ready)
    imageInfos[3].imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    imageInfos[3].imageView = m_ssrView ? m_ssrView : m_hdrColorView;
    imageInfos[3].sampler = m_ssrSampler ? m_ssrSampler : m_hdrSampler;

    // Normal + Roughness buffer (use HDR view as fallback)
    imageInfos[4].imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    imageInfos[4].imageView = m_hdrNormalView ? m_hdrNormalView : m_hdrColorView;
    imageInfos[4].sampler = m_hdrSampler;

    std::array<VkWriteDescriptorSet, 5> writes{};
    for (u32 i = 0; i < 5; i++) {
        writes[i].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        writes[i].dstSet = compositeSet;
        writes[i].dstBinding = i;
        writes[i].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        writes[i].descriptorCount = 1;
        writes[i].pImageInfo = &imageInfos[i];
    }

    vkUpdateDescriptorSets(m_context.getDevice(), static_cast<u32>(writes.size()), writes.data(), 0, nullptr);

    if (beginRenderPass) {
        // Begin render pass (swapchain)
        VkRenderPassBeginInfo renderPassInfo{};
        renderPassInfo.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;
        renderPassInfo.renderPass = renderPass;
        renderPassInfo.framebuffer = framebuffer;
        renderPassInfo.renderArea.offset = {0, 0};
        renderPassInfo.renderArea.extent = extent;

        bool useMsaa = m_context.getMsaaSamples() != VK_SAMPLE_COUNT_1_BIT;
        std::array<VkClearValue, 3> clearValues{};
        clearValues[0].color = {{0.0f, 0.0f, 0.0f, 1.0f}};

        if (useMsaa) {
            clearValues[1].color = {{0.0f, 0.0f, 0.0f, 1.0f}};
            clearValues[2].depthStencil = {1.0f, 0};
            renderPassInfo.clearValueCount = 3u;
        } else {
            clearValues[1].depthStencil = {1.0f, 0};
            renderPassInfo.clearValueCount = 2u;
        }

        renderPassInfo.pClearValues = clearValues.data();

        vkCmdBeginRenderPass(cmd, &renderPassInfo, VK_SUBPASS_CONTENTS_INLINE);
    }

    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_compositePipeline);
    vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_compositePipelineLayout,
                           0, 1, &compositeSet, 0, nullptr);

    // Push composite params (must match shader layout exactly)
    struct CompositeParams {
        f32 bloomIntensity;
        f32 exposure;
        f32 ssaoIntensity;
        u32 enableSSAO;
        u32 enableBloom;
        u32 tonemapMode;
        u32 debugMode;
        f32 nearPlane;
        f32 farPlane;
        u32 enableSSR;
        f32 ssrIntensity;
        f32 padding;
    } params;

    params.bloomIntensity = m_bloomConfig.intensity;
    params.exposure = m_compositeConfig.exposure;
    params.ssaoIntensity = m_ssaoConfig.intensity;
    params.enableSSAO = m_ssaoConfig.enabled ? 1u : 0u;
    params.enableBloom = m_bloomConfig.enabled ? 1u : 0u;
    params.tonemapMode = m_compositeConfig.tonemapMode;
    params.debugMode = static_cast<u32>(m_debugMode);
    params.nearPlane = 0.1f;
    params.farPlane = 1000.0f;
    params.enableSSR = m_ssrConfig.enabled ? 1u : 0u;
    params.ssrIntensity = 1.0f;  // SSR intensity from config (default 1.0)
    params.padding = 0.0f;

    vkCmdPushConstants(cmd, m_compositePipelineLayout, VK_SHADER_STAGE_FRAGMENT_BIT,
                       0, sizeof(CompositeParams), &params);

    VkViewport viewport{};
    viewport.x = 0.0f;
    viewport.y = 0.0f;
    viewport.width = static_cast<float>(extent.width);
    viewport.height = static_cast<float>(extent.height);
    viewport.minDepth = 0.0f;
    viewport.maxDepth = 1.0f;
    vkCmdSetViewport(cmd, 0, 1, &viewport);

    VkRect2D scissor{};
    scissor.offset = {0, 0};
    scissor.extent = extent;
    vkCmdSetScissor(cmd, 0, 1, &scissor);

    vkCmdDraw(cmd, 3, 1, 0, 0);

    if (endRenderPass) {
        vkCmdEndRenderPass(cmd);
    }
}

void PostProcess::drawFullscreenQuad(VkCommandBuffer cmd) {
    vkCmdDraw(cmd, 3, 1, 0, 0);
}

void PostProcess::cleanupHDR() {
    auto device = m_context.getDevice();

    cleanupHDRTargets();
    if (m_hdrRenderPass) vkDestroyRenderPass(device, m_hdrRenderPass, nullptr);
    if (m_hdrSampler) vkDestroySampler(device, m_hdrSampler, nullptr);

    m_hdrFramebuffer = VK_NULL_HANDLE;
    m_hdrRenderPass = VK_NULL_HANDLE;
    m_hdrColorView = VK_NULL_HANDLE;
    m_hdrColorImage = VK_NULL_HANDLE;
    m_hdrColorMemory = VK_NULL_HANDLE;
    m_hdrNormalView = VK_NULL_HANDLE;
    m_hdrNormalImage = VK_NULL_HANDLE;
    m_hdrNormalMemory = VK_NULL_HANDLE;
    m_hdrDepthView = VK_NULL_HANDLE;
    m_hdrDepthImage = VK_NULL_HANDLE;
    m_hdrDepthMemory = VK_NULL_HANDLE;
    m_hdrSampler = VK_NULL_HANDLE;
}

void PostProcess::cleanupHDRTargets() {
    auto device = m_context.getDevice();

    if (m_hdrFramebuffer) vkDestroyFramebuffer(device, m_hdrFramebuffer, nullptr);
    if (m_hdrColorView) vkDestroyImageView(device, m_hdrColorView, nullptr);
    if (m_hdrColorImage) vkDestroyImage(device, m_hdrColorImage, nullptr);
    if (m_hdrColorMemory) vkFreeMemory(device, m_hdrColorMemory, nullptr);
    if (m_hdrNormalView) vkDestroyImageView(device, m_hdrNormalView, nullptr);
    if (m_hdrNormalImage) vkDestroyImage(device, m_hdrNormalImage, nullptr);
    if (m_hdrNormalMemory) vkFreeMemory(device, m_hdrNormalMemory, nullptr);
    if (m_hdrDepthView) vkDestroyImageView(device, m_hdrDepthView, nullptr);
    if (m_hdrDepthImage) vkDestroyImage(device, m_hdrDepthImage, nullptr);
    if (m_hdrDepthMemory) vkFreeMemory(device, m_hdrDepthMemory, nullptr);

    m_hdrFramebuffer = VK_NULL_HANDLE;
    m_hdrColorView = VK_NULL_HANDLE;
    m_hdrColorImage = VK_NULL_HANDLE;
    m_hdrColorMemory = VK_NULL_HANDLE;
    m_hdrNormalView = VK_NULL_HANDLE;
    m_hdrNormalImage = VK_NULL_HANDLE;
    m_hdrNormalMemory = VK_NULL_HANDLE;
    m_hdrDepthView = VK_NULL_HANDLE;
    m_hdrDepthImage = VK_NULL_HANDLE;
    m_hdrDepthMemory = VK_NULL_HANDLE;
}

void PostProcess::cleanupComposite() {
    auto device = m_context.getDevice();

    if (m_compositePipeline) vkDestroyPipeline(device, m_compositePipeline, nullptr);
    if (m_compositePipelineLayout) vkDestroyPipelineLayout(device, m_compositePipelineLayout, nullptr);
    if (m_compositeDescLayout) vkDestroyDescriptorSetLayout(device, m_compositeDescLayout, nullptr);

    m_compositePipeline = VK_NULL_HANDLE;
    m_compositePipelineLayout = VK_NULL_HANDLE;
    m_compositeDescLayout = VK_NULL_HANDLE;
    m_compositeDescSets.clear();  // Freed with pool
}

void PostProcess::cleanupSSAOSizeDependent() {
    // Cleanup only size-dependent SSAO resources (for resize)
    // Keeps noise texture, pipelines, and layouts intact
    auto device = m_context.getDevice();

    if (m_ssaoFramebuffer) vkDestroyFramebuffer(device, m_ssaoFramebuffer, nullptr);
    if (m_ssaoBlurFramebuffer) vkDestroyFramebuffer(device, m_ssaoBlurFramebuffer, nullptr);

    if (m_ssaoView) vkDestroyImageView(device, m_ssaoView, nullptr);
    if (m_ssaoImage) vkDestroyImage(device, m_ssaoImage, nullptr);
    if (m_ssaoMemory) vkFreeMemory(device, m_ssaoMemory, nullptr);

    if (m_ssaoBlurredView) vkDestroyImageView(device, m_ssaoBlurredView, nullptr);
    if (m_ssaoBlurredImage) vkDestroyImage(device, m_ssaoBlurredImage, nullptr);
    if (m_ssaoBlurredMemory) vkFreeMemory(device, m_ssaoBlurredMemory, nullptr);

    m_ssaoFramebuffer = VK_NULL_HANDLE;
    m_ssaoBlurFramebuffer = VK_NULL_HANDLE;
    m_ssaoView = VK_NULL_HANDLE;
    m_ssaoImage = VK_NULL_HANDLE;
    m_ssaoMemory = VK_NULL_HANDLE;
    m_ssaoBlurredView = VK_NULL_HANDLE;
    m_ssaoBlurredImage = VK_NULL_HANDLE;
    m_ssaoBlurredMemory = VK_NULL_HANDLE;
}

void PostProcess::cleanupSSAO() {
    auto device = m_context.getDevice();

    if (m_ssaoPipeline) vkDestroyPipeline(device, m_ssaoPipeline, nullptr);
    if (m_ssaoBlurPipeline) vkDestroyPipeline(device, m_ssaoBlurPipeline, nullptr);
    if (m_ssaoPipelineLayout) vkDestroyPipelineLayout(device, m_ssaoPipelineLayout, nullptr);
    if (m_ssaoBlurPipelineLayout) vkDestroyPipelineLayout(device, m_ssaoBlurPipelineLayout, nullptr);

    if (m_ssaoFramebuffer) vkDestroyFramebuffer(device, m_ssaoFramebuffer, nullptr);
    if (m_ssaoBlurFramebuffer) vkDestroyFramebuffer(device, m_ssaoBlurFramebuffer, nullptr);
    if (m_ssaoRenderPass) vkDestroyRenderPass(device, m_ssaoRenderPass, nullptr);

    if (m_ssaoView) vkDestroyImageView(device, m_ssaoView, nullptr);
    if (m_ssaoImage) vkDestroyImage(device, m_ssaoImage, nullptr);
    if (m_ssaoMemory) vkFreeMemory(device, m_ssaoMemory, nullptr);

    if (m_ssaoBlurredView) vkDestroyImageView(device, m_ssaoBlurredView, nullptr);
    if (m_ssaoBlurredImage) vkDestroyImage(device, m_ssaoBlurredImage, nullptr);
    if (m_ssaoBlurredMemory) vkFreeMemory(device, m_ssaoBlurredMemory, nullptr);

    if (m_ssaoSampler) vkDestroySampler(device, m_ssaoSampler, nullptr);

    if (m_noiseView) vkDestroyImageView(device, m_noiseView, nullptr);
    if (m_noiseImage) vkDestroyImage(device, m_noiseImage, nullptr);
    if (m_noiseMemory) vkFreeMemory(device, m_noiseMemory, nullptr);
    if (m_noiseSampler) vkDestroySampler(device, m_noiseSampler, nullptr);

    if (m_ssaoUniformBuffer) vkDestroyBuffer(device, m_ssaoUniformBuffer, nullptr);
    if (m_ssaoUniformMemory) vkFreeMemory(device, m_ssaoUniformMemory, nullptr);

    if (m_descriptorPool) vkDestroyDescriptorPool(device, m_descriptorPool, nullptr);
    if (m_ssaoDescriptorLayout) vkDestroyDescriptorSetLayout(device, m_ssaoDescriptorLayout, nullptr);
    if (m_ssaoBlurDescLayout) vkDestroyDescriptorSetLayout(device, m_ssaoBlurDescLayout, nullptr);
    if (m_ssaoSampleDescLayout) vkDestroyDescriptorSetLayout(device, m_ssaoSampleDescLayout, nullptr);

    m_ssaoPipeline = VK_NULL_HANDLE;
    m_ssaoBlurPipeline = VK_NULL_HANDLE;
    m_ssaoPipelineLayout = VK_NULL_HANDLE;
    m_ssaoBlurPipelineLayout = VK_NULL_HANDLE;
    m_ssaoFramebuffer = VK_NULL_HANDLE;
    m_ssaoBlurFramebuffer = VK_NULL_HANDLE;
    m_ssaoRenderPass = VK_NULL_HANDLE;
    m_ssaoView = VK_NULL_HANDLE;
    m_ssaoImage = VK_NULL_HANDLE;
    m_ssaoMemory = VK_NULL_HANDLE;
    m_ssaoBlurredView = VK_NULL_HANDLE;
    m_ssaoBlurredImage = VK_NULL_HANDLE;
    m_ssaoBlurredMemory = VK_NULL_HANDLE;
    m_ssaoSampler = VK_NULL_HANDLE;
    m_noiseView = VK_NULL_HANDLE;
    m_noiseImage = VK_NULL_HANDLE;
    m_noiseMemory = VK_NULL_HANDLE;
    m_noiseSampler = VK_NULL_HANDLE;
    m_ssaoUniformBuffer = VK_NULL_HANDLE;
    m_ssaoUniformMemory = VK_NULL_HANDLE;
    m_descriptorPool = VK_NULL_HANDLE;
    m_ssaoDescriptorLayout = VK_NULL_HANDLE;
    m_ssaoBlurDescLayout = VK_NULL_HANDLE;
    m_ssaoSampleDescLayout = VK_NULL_HANDLE;
    m_ssaoDescriptorSets.clear();
}

void PostProcess::cleanupBloom() {
    auto device = m_context.getDevice();

    for (int i = 0; i < 2; i++) {
        if (m_bloomViews[i]) vkDestroyImageView(device, m_bloomViews[i], nullptr);
        if (m_bloomImages[i]) vkDestroyImage(device, m_bloomImages[i], nullptr);
        if (m_bloomMemory[i]) vkFreeMemory(device, m_bloomMemory[i], nullptr);
        if (m_bloomFramebuffers[i]) vkDestroyFramebuffer(device, m_bloomFramebuffers[i], nullptr);
        m_bloomViews[i] = VK_NULL_HANDLE;
        m_bloomImages[i] = VK_NULL_HANDLE;
        m_bloomMemory[i] = VK_NULL_HANDLE;
        m_bloomFramebuffers[i] = VK_NULL_HANDLE;
    }
    m_bloomDescSets.clear();

    if (m_bloomSampler) vkDestroySampler(device, m_bloomSampler, nullptr);
    if (m_bloomRenderPass) vkDestroyRenderPass(device, m_bloomRenderPass, nullptr);
    if (m_bloomBrightPipeline) vkDestroyPipeline(device, m_bloomBrightPipeline, nullptr);
    if (m_bloomBlurPipeline) vkDestroyPipeline(device, m_bloomBlurPipeline, nullptr);
    if (m_bloomPipelineLayout) vkDestroyPipelineLayout(device, m_bloomPipelineLayout, nullptr);
    if (m_bloomDescLayout) vkDestroyDescriptorSetLayout(device, m_bloomDescLayout, nullptr);

    m_bloomSampler = VK_NULL_HANDLE;
    m_bloomRenderPass = VK_NULL_HANDLE;
    m_bloomBrightPipeline = VK_NULL_HANDLE;
    m_bloomBlurPipeline = VK_NULL_HANDLE;
    m_bloomPipelineLayout = VK_NULL_HANDLE;
    m_bloomDescLayout = VK_NULL_HANDLE;
    m_bloomResultView = VK_NULL_HANDLE;
}

// ============================================================================
// SSR (Screen Space Reflections) Implementation
// ============================================================================

void PostProcess::createSSRResources() {
    auto device = m_context.getDevice();

    // Create SSR output image (RGBA16F for HDR reflections with confidence)
    m_context.createImage(m_width, m_height, VK_FORMAT_R16G16B16A16_SFLOAT, VK_IMAGE_TILING_OPTIMAL,
                         VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
                         VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
                         m_ssrImage, m_ssrMemory);

    m_ssrView = m_context.createImageView(m_ssrImage, VK_FORMAT_R16G16B16A16_SFLOAT, VK_IMAGE_ASPECT_COLOR_BIT);

    // Create sampler
    VkSamplerCreateInfo samplerInfo{};
    samplerInfo.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
    samplerInfo.magFilter = VK_FILTER_LINEAR;
    samplerInfo.minFilter = VK_FILTER_LINEAR;
    samplerInfo.mipmapMode = VK_SAMPLER_MIPMAP_MODE_LINEAR;
    samplerInfo.addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.anisotropyEnable = VK_FALSE;
    samplerInfo.maxAnisotropy = 1.0f;
    samplerInfo.borderColor = VK_BORDER_COLOR_INT_OPAQUE_BLACK;
    samplerInfo.unnormalizedCoordinates = VK_FALSE;

    if (vkCreateSampler(device, &samplerInfo, nullptr, &m_ssrSampler) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSR sampler");
    }

    // Create render pass for SSR
    VkAttachmentDescription colorAttachment{};
    colorAttachment.format = VK_FORMAT_R16G16B16A16_SFLOAT;
    colorAttachment.samples = VK_SAMPLE_COUNT_1_BIT;
    colorAttachment.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    colorAttachment.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    colorAttachment.stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    colorAttachment.stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    colorAttachment.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    colorAttachment.finalLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

    VkAttachmentReference colorRef{};
    colorRef.attachment = 0;
    colorRef.layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;

    VkSubpassDescription subpass{};
    subpass.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    subpass.colorAttachmentCount = 1;
    subpass.pColorAttachments = &colorRef;

    VkSubpassDependency dependency{};
    dependency.srcSubpass = VK_SUBPASS_EXTERNAL;
    dependency.dstSubpass = 0;
    dependency.srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    dependency.srcAccessMask = 0;
    dependency.dstStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    dependency.dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;

    VkRenderPassCreateInfo renderPassInfo{};
    renderPassInfo.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO;
    renderPassInfo.attachmentCount = 1;
    renderPassInfo.pAttachments = &colorAttachment;
    renderPassInfo.subpassCount = 1;
    renderPassInfo.pSubpasses = &subpass;
    renderPassInfo.dependencyCount = 1;
    renderPassInfo.pDependencies = &dependency;

    if (vkCreateRenderPass(device, &renderPassInfo, nullptr, &m_ssrRenderPass) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSR render pass");
    }

    // Create framebuffer
    VkFramebufferCreateInfo fbInfo{};
    fbInfo.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO;
    fbInfo.renderPass = m_ssrRenderPass;
    fbInfo.attachmentCount = 1;
    fbInfo.pAttachments = &m_ssrView;
    fbInfo.width = m_width;
    fbInfo.height = m_height;
    fbInfo.layers = 1;

    if (vkCreateFramebuffer(device, &fbInfo, nullptr, &m_ssrFramebuffer) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSR framebuffer");
    }

    std::cout << "[PostProcess] SSR resources created (" << m_width << "x" << m_height << ")" << std::endl;
}

void PostProcess::createSSRPipeline() {
    auto device = m_context.getDevice();

    // Load shaders
    auto loadShader = [&](const std::string& filename) -> VkShaderModule {
        std::ifstream file(filename, std::ios::ate | std::ios::binary);
        if (!file.is_open()) {
            throw std::runtime_error("Failed to open shader file: " + filename);
        }
        size_t fileSize = static_cast<size_t>(file.tellg());
        std::vector<char> buffer(fileSize);
        file.seekg(0);
        file.read(buffer.data(), fileSize);
        file.close();

        VkShaderModuleCreateInfo createInfo{};
        createInfo.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
        createInfo.codeSize = buffer.size();
        createInfo.pCode = reinterpret_cast<const u32*>(buffer.data());

        VkShaderModule shaderModule;
        if (vkCreateShaderModule(device, &createInfo, nullptr, &shaderModule) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create shader module");
        }
        return shaderModule;
    };

    VkShaderModule vertModule = loadShader("shaders/ssr.vert.spv");
    VkShaderModule fragModule = loadShader("shaders/ssr.frag.spv");

    // Create descriptor set layout (3 textures: HDR scene, normal+roughness, depth)
    std::array<VkDescriptorSetLayoutBinding, 3> bindings{};

    bindings[0].binding = 0;  // HDR scene
    bindings[0].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    bindings[0].descriptorCount = 1;
    bindings[0].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    bindings[1].binding = 1;  // Normal + roughness
    bindings[1].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    bindings[1].descriptorCount = 1;
    bindings[1].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    bindings[2].binding = 2;  // Depth
    bindings[2].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    bindings[2].descriptorCount = 1;
    bindings[2].stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;

    VkDescriptorSetLayoutCreateInfo layoutInfo{};
    layoutInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
    layoutInfo.bindingCount = static_cast<u32>(bindings.size());
    layoutInfo.pBindings = bindings.data();

    if (vkCreateDescriptorSetLayout(device, &layoutInfo, nullptr, &m_ssrDescLayout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSR descriptor set layout");
    }

    // Push constant for SSR parameters (matrices + params)
    VkPushConstantRange pushConstant{};
    pushConstant.stageFlags = VK_SHADER_STAGE_FRAGMENT_BIT;
    pushConstant.offset = 0;
    pushConstant.size = sizeof(mat4) * 3 + sizeof(vec4) * 2;  // projection, invProjection, view, params, params2

    VkPipelineLayoutCreateInfo pipelineLayoutInfo{};
    pipelineLayoutInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    pipelineLayoutInfo.setLayoutCount = 1;
    pipelineLayoutInfo.pSetLayouts = &m_ssrDescLayout;
    pipelineLayoutInfo.pushConstantRangeCount = 1;
    pipelineLayoutInfo.pPushConstantRanges = &pushConstant;

    if (vkCreatePipelineLayout(device, &pipelineLayoutInfo, nullptr, &m_ssrPipelineLayout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSR pipeline layout");
    }

    // Create graphics pipeline
    VkPipelineShaderStageCreateInfo vertStage{};
    vertStage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    vertStage.stage = VK_SHADER_STAGE_VERTEX_BIT;
    vertStage.module = vertModule;
    vertStage.pName = "main";

    VkPipelineShaderStageCreateInfo fragStage{};
    fragStage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    fragStage.stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    fragStage.module = fragModule;
    fragStage.pName = "main";

    VkPipelineShaderStageCreateInfo stages[] = {vertStage, fragStage};

    // Vertex input (fullscreen quad)
    VkVertexInputBindingDescription vertexBinding{};
    vertexBinding.binding = 0;
    vertexBinding.stride = sizeof(f32) * 4;  // pos.xy, uv.xy
    vertexBinding.inputRate = VK_VERTEX_INPUT_RATE_VERTEX;

    std::array<VkVertexInputAttributeDescription, 2> vertexAttribs{};
    vertexAttribs[0].binding = 0;
    vertexAttribs[0].location = 0;
    vertexAttribs[0].format = VK_FORMAT_R32G32_SFLOAT;
    vertexAttribs[0].offset = 0;
    vertexAttribs[1].binding = 0;
    vertexAttribs[1].location = 1;
    vertexAttribs[1].format = VK_FORMAT_R32G32_SFLOAT;
    vertexAttribs[1].offset = sizeof(f32) * 2;

    VkPipelineVertexInputStateCreateInfo vertexInput{};
    vertexInput.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;
    vertexInput.vertexBindingDescriptionCount = 1;
    vertexInput.pVertexBindingDescriptions = &vertexBinding;
    vertexInput.vertexAttributeDescriptionCount = static_cast<u32>(vertexAttribs.size());
    vertexInput.pVertexAttributeDescriptions = vertexAttribs.data();

    VkPipelineInputAssemblyStateCreateInfo inputAssembly{};
    inputAssembly.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    inputAssembly.topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST;
    inputAssembly.primitiveRestartEnable = VK_FALSE;

    VkViewport viewport{};
    viewport.x = 0.0f;
    viewport.y = 0.0f;
    viewport.width = static_cast<f32>(m_width);
    viewport.height = static_cast<f32>(m_height);
    viewport.minDepth = 0.0f;
    viewport.maxDepth = 1.0f;

    VkRect2D scissor{};
    scissor.offset = {0, 0};
    scissor.extent = {m_width, m_height};

    VkPipelineViewportStateCreateInfo viewportState{};
    viewportState.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    viewportState.viewportCount = 1;
    viewportState.pViewports = &viewport;
    viewportState.scissorCount = 1;
    viewportState.pScissors = &scissor;

    VkPipelineRasterizationStateCreateInfo rasterizer{};
    rasterizer.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    rasterizer.depthClampEnable = VK_FALSE;
    rasterizer.rasterizerDiscardEnable = VK_FALSE;
    rasterizer.polygonMode = VK_POLYGON_MODE_FILL;
    rasterizer.lineWidth = 1.0f;
    rasterizer.cullMode = VK_CULL_MODE_NONE;
    rasterizer.frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE;
    rasterizer.depthBiasEnable = VK_FALSE;

    VkPipelineMultisampleStateCreateInfo multisampling{};
    multisampling.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    multisampling.sampleShadingEnable = VK_FALSE;
    multisampling.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;

    VkPipelineColorBlendAttachmentState colorBlendAttachment{};
    colorBlendAttachment.colorWriteMask = VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT |
                                          VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;
    colorBlendAttachment.blendEnable = VK_FALSE;

    VkPipelineColorBlendStateCreateInfo colorBlending{};
    colorBlending.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    colorBlending.logicOpEnable = VK_FALSE;
    colorBlending.attachmentCount = 1;
    colorBlending.pAttachments = &colorBlendAttachment;

    VkPipelineDepthStencilStateCreateInfo depthStencil{};
    depthStencil.sType = VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO;
    depthStencil.depthTestEnable = VK_FALSE;
    depthStencil.depthWriteEnable = VK_FALSE;

    VkDynamicState dynamicStates[] = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo dynamicState{};
    dynamicState.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO;
    dynamicState.dynamicStateCount = 2;
    dynamicState.pDynamicStates = dynamicStates;

    VkGraphicsPipelineCreateInfo pipelineInfo{};
    pipelineInfo.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    pipelineInfo.stageCount = 2;
    pipelineInfo.pStages = stages;
    pipelineInfo.pVertexInputState = &vertexInput;
    pipelineInfo.pInputAssemblyState = &inputAssembly;
    pipelineInfo.pViewportState = &viewportState;
    pipelineInfo.pRasterizationState = &rasterizer;
    pipelineInfo.pMultisampleState = &multisampling;
    pipelineInfo.pDepthStencilState = &depthStencil;
    pipelineInfo.pColorBlendState = &colorBlending;
    pipelineInfo.pDynamicState = &dynamicState;
    pipelineInfo.layout = m_ssrPipelineLayout;
    pipelineInfo.renderPass = m_ssrRenderPass;
    pipelineInfo.subpass = 0;

    if (vkCreateGraphicsPipelines(device, m_context.getPipelineCache(), 1, &pipelineInfo,
                                   nullptr, &m_ssrPipeline) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create SSR pipeline");
    }

    vkDestroyShaderModule(device, vertModule, nullptr);
    vkDestroyShaderModule(device, fragModule, nullptr);

    // Allocate descriptor sets
    u32 frameCount = static_cast<u32>(m_context.getSwapchainImageCount());
    m_ssrDescSets.resize(frameCount);

    std::vector<VkDescriptorSetLayout> layouts(frameCount, m_ssrDescLayout);

    VkDescriptorSetAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
    allocInfo.descriptorPool = m_descriptorPool;
    allocInfo.descriptorSetCount = frameCount;
    allocInfo.pSetLayouts = layouts.data();

    if (vkAllocateDescriptorSets(device, &allocInfo, m_ssrDescSets.data()) != VK_SUCCESS) {
        throw std::runtime_error("Failed to allocate SSR descriptor sets");
    }

    // Update descriptor sets
    for (u32 i = 0; i < frameCount; i++) {
        VkDescriptorImageInfo hdrInfo{};
        hdrInfo.sampler = m_hdrSampler;
        hdrInfo.imageView = m_hdrColorView;
        hdrInfo.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

        VkDescriptorImageInfo normalInfo{};
        normalInfo.sampler = m_hdrSampler;
        normalInfo.imageView = m_hdrNormalView;
        normalInfo.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

        VkDescriptorImageInfo depthInfo{};
        depthInfo.sampler = m_hdrSampler;
        depthInfo.imageView = m_hdrDepthView;
        depthInfo.imageLayout = VK_IMAGE_LAYOUT_DEPTH_STENCIL_READ_ONLY_OPTIMAL;

        std::array<VkWriteDescriptorSet, 3> writes{};

        writes[0].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        writes[0].dstSet = m_ssrDescSets[i];
        writes[0].dstBinding = 0;
        writes[0].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        writes[0].descriptorCount = 1;
        writes[0].pImageInfo = &hdrInfo;

        writes[1].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        writes[1].dstSet = m_ssrDescSets[i];
        writes[1].dstBinding = 1;
        writes[1].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        writes[1].descriptorCount = 1;
        writes[1].pImageInfo = &normalInfo;

        writes[2].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        writes[2].dstSet = m_ssrDescSets[i];
        writes[2].dstBinding = 2;
        writes[2].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        writes[2].descriptorCount = 1;
        writes[2].pImageInfo = &depthInfo;

        vkUpdateDescriptorSets(device, static_cast<u32>(writes.size()), writes.data(), 0, nullptr);
    }

    std::cout << "[PostProcess] SSR pipeline created" << std::endl;
}

void PostProcess::generateSSR(VkCommandBuffer cmd, const mat4& projection, const mat4& invProjection,
                               const mat4& view, u32 frameIndex) {
    if (!m_ssrConfig.enabled || !m_ssrPipeline) {
        return;
    }

    // Begin SSR render pass
    VkRenderPassBeginInfo renderPassInfo{};
    renderPassInfo.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;
    renderPassInfo.renderPass = m_ssrRenderPass;
    renderPassInfo.framebuffer = m_ssrFramebuffer;
    renderPassInfo.renderArea.offset = {0, 0};
    renderPassInfo.renderArea.extent = {m_width, m_height};

    VkClearValue clearValue = {};
    clearValue.color = {{0.0f, 0.0f, 0.0f, 0.0f}};
    renderPassInfo.clearValueCount = 1;
    renderPassInfo.pClearValues = &clearValue;

    vkCmdBeginRenderPass(cmd, &renderPassInfo, VK_SUBPASS_CONTENTS_INLINE);

    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_ssrPipeline);
    vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_ssrPipelineLayout, 0, 1,
                            &m_ssrDescSets[frameIndex], 0, nullptr);

    // Set viewport and scissor
    VkViewport viewport{};
    viewport.x = 0.0f;
    viewport.y = 0.0f;
    viewport.width = static_cast<f32>(m_width);
    viewport.height = static_cast<f32>(m_height);
    viewport.minDepth = 0.0f;
    viewport.maxDepth = 1.0f;
    vkCmdSetViewport(cmd, 0, 1, &viewport);

    VkRect2D scissor{};
    scissor.offset = {0, 0};
    scissor.extent = {m_width, m_height};
    vkCmdSetScissor(cmd, 0, 1, &scissor);

    // Push constants (matches shader layout)
    struct SSRPushConstants {
        mat4 projection;
        mat4 invProjection;
        mat4 view;
        vec4 params;    // maxDistance, thickness, stride, iterations
        vec4 params2;   // fadeStart, fadeEnd, jitter, unused
    } pushConstants;

    pushConstants.projection = projection;
    pushConstants.invProjection = invProjection;
    pushConstants.view = view;
    pushConstants.params = vec4(m_ssrConfig.maxDistance, m_ssrConfig.thickness,
                                m_ssrConfig.stride, static_cast<f32>(m_ssrConfig.iterations));
    pushConstants.params2 = vec4(m_ssrConfig.fadeStart, m_ssrConfig.fadeEnd, 0.0f, 0.0f);

    vkCmdPushConstants(cmd, m_ssrPipelineLayout, VK_SHADER_STAGE_FRAGMENT_BIT, 0,
                       sizeof(pushConstants), &pushConstants);

    // Draw fullscreen quad
    drawFullscreenQuad(cmd);

    vkCmdEndRenderPass(cmd);
}

void PostProcess::cleanupSSR() {
    auto device = m_context.getDevice();

    if (m_ssrView) vkDestroyImageView(device, m_ssrView, nullptr);
    if (m_ssrImage) vkDestroyImage(device, m_ssrImage, nullptr);
    if (m_ssrMemory) vkFreeMemory(device, m_ssrMemory, nullptr);
    if (m_ssrSampler) vkDestroySampler(device, m_ssrSampler, nullptr);
    if (m_ssrFramebuffer) vkDestroyFramebuffer(device, m_ssrFramebuffer, nullptr);
    if (m_ssrRenderPass) vkDestroyRenderPass(device, m_ssrRenderPass, nullptr);
    if (m_ssrPipeline) vkDestroyPipeline(device, m_ssrPipeline, nullptr);
    if (m_ssrPipelineLayout) vkDestroyPipelineLayout(device, m_ssrPipelineLayout, nullptr);
    if (m_ssrDescLayout) vkDestroyDescriptorSetLayout(device, m_ssrDescLayout, nullptr);

    m_ssrView = VK_NULL_HANDLE;
    m_ssrImage = VK_NULL_HANDLE;
    m_ssrMemory = VK_NULL_HANDLE;
    m_ssrSampler = VK_NULL_HANDLE;
    m_ssrFramebuffer = VK_NULL_HANDLE;
    m_ssrRenderPass = VK_NULL_HANDLE;
    m_ssrPipeline = VK_NULL_HANDLE;
    m_ssrPipelineLayout = VK_NULL_HANDLE;
    m_ssrDescLayout = VK_NULL_HANDLE;
    m_ssrDescSets.clear();
}

} // namespace arch
