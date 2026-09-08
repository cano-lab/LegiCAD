#pragma once

#include "types.hpp"
#include "vulkan_context.hpp"
#include "pipeline.hpp"

namespace arch {

// Push constants for tessellated shadow pass
struct ShadowTessPushConstants {
    mat4 lightViewProj;
    mat4 model;
    f32 tessLevel;
    f32 dispScale;
    f32 uvScale;
    f32 padding;
};

// ============================================================================
// ShadowMap - Multi-layer shadow mapping with PCF (supports up to MAX_SHADOW_MAPS lights)
// ============================================================================
class ShadowMap {
public:
    ShadowMap(VulkanContext& context, u32 resolution = 2048);
    ~ShadowMap();

    // Non-copyable
    ShadowMap(const ShadowMap&) = delete;
    ShadowMap& operator=(const ShadowMap&) = delete;

    // Begin shadow pass rendering for a specific layer
    void beginShadowPass(VkCommandBuffer cmd, u32 layerIndex = 0);

    // End shadow pass rendering
    void endShadowPass(VkCommandBuffer cmd);

    // Update light matrices for a specific shadow map layer
    void updateLightMatrix(u32 layerIndex, const vec3& lightDir, const vec3& sceneCenter, f32 sceneRadius);

    // Legacy: Update first layer (for backward compatibility)
    void updateLightMatrix(const vec3& lightDir, const vec3& sceneCenter, f32 sceneRadius) {
        updateLightMatrix(0, lightDir, sceneCenter, sceneRadius);
    }

    // Get the light view-projection matrix for a specific layer
    const mat4& getLightViewProj(u32 layerIndex = 0) const {
        return m_lightViewProj[layerIndex < MAX_SHADOW_MAPS ? layerIndex : 0];
    }

    // Get shadow map array image view for binding to descriptor (samples all layers)
    VkImageView getArrayImageView() const { return m_depthArrayImageView; }

    // Get shadow map image view for first layer (2D view for single shadow map sampling)
    VkImageView getImageView() const { return m_depthLayerImageViews[0]; }

    // Get shadow map sampler
    VkSampler getSampler() const { return m_sampler; }

    // Get the shadow pipeline layout
    VkPipelineLayout getPipelineLayout() const { return m_pipelineLayout; }

    // Get the shadow pipeline
    VkPipeline getPipeline() const { return m_pipeline; }

    // Get resolution
    u32 getResolution() const { return m_resolution; }

    // Get number of layers
    u32 getLayerCount() const { return MAX_SHADOW_MAPS; }

    // Get descriptor set layout for shadow pass
    VkDescriptorSetLayout getDescriptorSetLayout() const { return m_descriptorSetLayout; }

    // Tessellated shadow pass (for displacement mapping)
    VkPipeline getTessPipeline() const { return m_tessPipeline; }
    VkPipelineLayout getTessPipelineLayout() const { return m_tessPipelineLayout; }
    VkDescriptorSetLayout getHeightMapDescriptorSetLayout() const { return m_heightMapDescriptorSetLayout; }

private:
    void createDepthResources();
    void createRenderPass();
    void createFramebuffers();
    void createSampler();
    void createPipeline();
    void createTessPipeline();
    void createDescriptorSetLayout();

    VulkanContext& m_context;
    u32 m_resolution;

    // Depth texture array (MAX_SHADOW_MAPS layers)
    VkImage m_depthImage = VK_NULL_HANDLE;
    VkDeviceMemory m_depthImageMemory = VK_NULL_HANDLE;
    VkImageView m_depthArrayImageView = VK_NULL_HANDLE;  // View for entire array (shader sampling)
    VkImageView m_depthLayerImageViews[MAX_SHADOW_MAPS] = {};  // Per-layer views (framebuffer attachment)

    // Render pass and per-layer framebuffers
    VkRenderPass m_renderPass = VK_NULL_HANDLE;
    VkFramebuffer m_framebuffers[MAX_SHADOW_MAPS] = {};  // One per layer

    // Sampler with comparison for hardware PCF
    VkSampler m_sampler = VK_NULL_HANDLE;

    // Shadow pass pipeline (non-tessellated)
    VkPipelineLayout m_pipelineLayout = VK_NULL_HANDLE;
    VkPipeline m_pipeline = VK_NULL_HANDLE;
    VkDescriptorSetLayout m_descriptorSetLayout = VK_NULL_HANDLE;

    // Tessellated shadow pass pipeline
    VkPipelineLayout m_tessPipelineLayout = VK_NULL_HANDLE;
    VkPipeline m_tessPipeline = VK_NULL_HANDLE;
    VkDescriptorSetLayout m_heightMapDescriptorSetLayout = VK_NULL_HANDLE;

    // Per-layer light matrices
    mat4 m_lightView[MAX_SHADOW_MAPS] = {};
    mat4 m_lightProj[MAX_SHADOW_MAPS] = {};
    mat4 m_lightViewProj[MAX_SHADOW_MAPS] = {};

    // Current layer being rendered
    u32 m_currentLayer = 0;
};

} // namespace arch
