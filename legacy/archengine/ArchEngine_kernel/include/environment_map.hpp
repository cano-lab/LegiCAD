#pragma once

#include "types.hpp"
#include "vulkan_context.hpp"
#include <string>

namespace arch {

/**
 * @brief IBL (Image-Based Lighting) configuration
 */
struct IBLConfig {
    u32 irradianceSize = 64;       // Size of irradiance cubemap faces
    u32 prefilteredSize = 256;     // Size of prefiltered cubemap faces (mip 0)
    u32 prefilteredMipLevels = 6;  // Number of mip levels for roughness
    u32 brdfLutSize = 512;         // Size of BRDF LUT texture
    u32 sampleCount = 1024;        // Monte Carlo samples for convolution
};

class EnvironmentMap {
public:
    EnvironmentMap(VulkanContext& context);
    ~EnvironmentMap();

    // Non-copyable
    EnvironmentMap(const EnvironmentMap&) = delete;
    EnvironmentMap& operator=(const EnvironmentMap&) = delete;

    // Load HDR environment map from file (equirectangular format)
    bool loadFromFile(const std::string& filepath);

    // Load a default procedural sky (no file needed)
    void createProceduralSky();

    // Check if loaded
    bool isLoaded() const { return m_loaded; }

    // Getters for rendering
    VkImageView getCubemapView() const { return m_cubemapView; }
    VkSampler getSampler() const { return m_sampler; }
    VkDescriptorImageInfo getDescriptorInfo() const;

    // Get dimensions
    u32 getCubemapSize() const { return m_cubemapSize; }

    // ================= IBL Support =================

    /**
     * @brief Generate IBL textures (irradiance, prefiltered, BRDF LUT)
     *
     * Call this after loading an environment map to generate the textures
     * needed for proper image-based lighting.
     *
     * @param config Configuration for IBL generation
     * @return true if generation succeeded
     */
    bool generateIBLTextures(const IBLConfig& config = IBLConfig{});

    /**
     * @brief Check if IBL textures are ready
     */
    bool hasIBLTextures() const { return m_iblGenerated; }

    // IBL texture getters
    VkImageView getIrradianceView() const { return m_irradianceView; }
    VkImageView getPrefilteredView() const { return m_prefilteredView; }
    VkImageView getBRDFLutView() const { return m_brdfLutView; }
    VkSampler getIBLSampler() const { return m_iblSampler; }

    // Get descriptor infos for IBL textures
    VkDescriptorImageInfo getIrradianceDescriptorInfo() const;
    VkDescriptorImageInfo getPrefilteredDescriptorInfo() const;
    VkDescriptorImageInfo getBRDFLutDescriptorInfo() const;

    // Get prefiltered max mip level (for roughness LOD calculation)
    u32 getPrefilteredMipLevels() const { return m_prefilteredMipLevels; }

private:
    void createCubemapFromEquirectangular(const float* hdrData, int width, int height);
    void createSampler();
    void cleanup();
    void cleanupIBL();

    // Convert equirectangular to cubemap face
    vec3 getCubemapDirection(int face, float u, float v);

    // IBL generation helpers
    bool createIrradianceMap(const IBLConfig& config);
    bool createPrefilteredMap(const IBLConfig& config);
    bool createBRDFLut(const IBLConfig& config);
    void createIBLSampler();

    // Compute pipeline helpers
    void createComputePipelines();
    void cleanupComputePipelines();
    void runBRDFLutCompute(const IBLConfig& config);
    void runIrradianceCompute(const IBLConfig& config);
    void runPrefilterCompute(const IBLConfig& config);
    VkShaderModule loadShaderModule(const std::string& filename);

    VulkanContext& m_context;

    // Cubemap texture
    VkImage m_cubemapImage = VK_NULL_HANDLE;
    VkDeviceMemory m_cubemapMemory = VK_NULL_HANDLE;
    VkImageView m_cubemapView = VK_NULL_HANDLE;
    VkSampler m_sampler = VK_NULL_HANDLE;

    u32 m_cubemapSize = 512;  // Size of each cubemap face
    bool m_loaded = false;

    // ================= IBL Resources =================

    // Irradiance cubemap (diffuse IBL)
    VkImage m_irradianceImage = VK_NULL_HANDLE;
    VkDeviceMemory m_irradianceMemory = VK_NULL_HANDLE;
    VkImageView m_irradianceView = VK_NULL_HANDLE;

    // Pre-filtered environment map (specular IBL with mip chain)
    VkImage m_prefilteredImage = VK_NULL_HANDLE;
    VkDeviceMemory m_prefilteredMemory = VK_NULL_HANDLE;
    VkImageView m_prefilteredView = VK_NULL_HANDLE;
    u32 m_prefilteredMipLevels = 1;

    // BRDF LUT (2D texture for split-sum approximation)
    VkImage m_brdfLutImage = VK_NULL_HANDLE;
    VkDeviceMemory m_brdfLutMemory = VK_NULL_HANDLE;
    VkImageView m_brdfLutView = VK_NULL_HANDLE;

    // IBL sampler (with mip support)
    VkSampler m_iblSampler = VK_NULL_HANDLE;

    bool m_iblGenerated = false;

    // ================= Compute Pipelines =================

    // BRDF LUT compute pipeline
    VkDescriptorSetLayout m_brdfDescriptorSetLayout = VK_NULL_HANDLE;
    VkPipelineLayout m_brdfPipelineLayout = VK_NULL_HANDLE;
    VkPipeline m_brdfPipeline = VK_NULL_HANDLE;
    VkDescriptorPool m_computeDescriptorPool = VK_NULL_HANDLE;

    // Irradiance compute pipeline
    VkDescriptorSetLayout m_irradianceDescriptorSetLayout = VK_NULL_HANDLE;
    VkPipelineLayout m_irradiancePipelineLayout = VK_NULL_HANDLE;
    VkPipeline m_irradiancePipeline = VK_NULL_HANDLE;

    // Prefilter compute pipeline
    VkDescriptorSetLayout m_prefilterDescriptorSetLayout = VK_NULL_HANDLE;
    VkPipelineLayout m_prefilterPipelineLayout = VK_NULL_HANDLE;
    VkPipeline m_prefilterPipeline = VK_NULL_HANDLE;

    bool m_computePipelinesCreated = false;
};

} // namespace arch
