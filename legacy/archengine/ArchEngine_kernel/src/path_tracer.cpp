/**
 * @file path_tracer.cpp
 * @brief Compute shader-based path tracer implementation
 */

#include "path_tracer.hpp"
#include <fstream>
#include <iostream>
#include <cstring>
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <set>

// STB for PNG/HDR export (implementation is in renderer.cpp)
#include "../external/stb_image_write.h"

// STB for image loading (implementation is in texture.cpp or renderer.cpp)
#include "../external/stb_image.h"

// JSON parsing
#include <nlohmann/json.hpp>
using json = nlohmann::json;

namespace arch {

PathTracer::PathTracer(VulkanContext& context)
    : m_context(context)
{
    std::cout << "[PathTracer] Initialized\n";
}

PathTracer::~PathTracer() {
    cleanup();
}

void PathTracer::cleanupTextures() {
    if (m_textureSampler) {
        vkDestroySampler(m_context.getDevice(), m_textureSampler, nullptr);
        m_textureSampler = VK_NULL_HANDLE;
    }
    if (m_textureArrayView) {
        vkDestroyImageView(m_context.getDevice(), m_textureArrayView, nullptr);
        m_textureArrayView = VK_NULL_HANDLE;
    }
    if (m_textureArray) {
        vkDestroyImage(m_context.getDevice(), m_textureArray, nullptr);
        m_textureArray = VK_NULL_HANDLE;
    }
    if (m_textureArrayMemory) {
        vkFreeMemory(m_context.getDevice(), m_textureArrayMemory, nullptr);
        m_textureArrayMemory = VK_NULL_HANDLE;
    }
    m_texturesLoaded = false;
    m_textureArrayLayers = 0;
}

void PathTracer::cleanupRenderResources() {
    // Only clean up render-specific resources, NOT scene data
    m_context.waitIdle();

    // Destroy compute pipeline
    if (m_pipeline) {
        vkDestroyPipeline(m_context.getDevice(), m_pipeline, nullptr);
        m_pipeline = VK_NULL_HANDLE;
    }
    if (m_pipelineLayout) {
        vkDestroyPipelineLayout(m_context.getDevice(), m_pipelineLayout, nullptr);
        m_pipelineLayout = VK_NULL_HANDLE;
    }
    if (m_descriptorSetLayout) {
        vkDestroyDescriptorSetLayout(m_context.getDevice(), m_descriptorSetLayout, nullptr);
        m_descriptorSetLayout = VK_NULL_HANDLE;
    }
    if (m_descriptorPool) {
        vkDestroyDescriptorPool(m_context.getDevice(), m_descriptorPool, nullptr);
        m_descriptorPool = VK_NULL_HANDLE;
    }

    // Destroy UBO and staging buffers (but NOT scene buffers)
    auto destroyBuffer = [&](VkBuffer& buf, VkDeviceMemory& mem) {
        if (buf) {
            vkDestroyBuffer(m_context.getDevice(), buf, nullptr);
            buf = VK_NULL_HANDLE;
        }
        if (mem) {
            vkFreeMemory(m_context.getDevice(), mem, nullptr);
            mem = VK_NULL_HANDLE;
        }
    };

    if (m_uboMapped) {
        vkUnmapMemory(m_context.getDevice(), m_uboMemory);
        m_uboMapped = nullptr;
    }

    destroyBuffer(m_uboBuffer, m_uboMemory);
    destroyBuffer(m_stagingBuffer, m_stagingMemory);

    // Destroy accumulation image
    if (m_accumView) {
        vkDestroyImageView(m_context.getDevice(), m_accumView, nullptr);
        m_accumView = VK_NULL_HANDLE;
    }
    if (m_accumImage) {
        vkDestroyImage(m_context.getDevice(), m_accumImage, nullptr);
        m_accumImage = VK_NULL_HANDLE;
    }
    if (m_accumMemory) {
        vkFreeMemory(m_context.getDevice(), m_accumMemory, nullptr);
        m_accumMemory = VK_NULL_HANDLE;
    }
}

void PathTracer::cleanup() {
    m_context.waitIdle();

    // Clean up render resources
    cleanupRenderResources();

    // Destroy textures
    cleanupTextures();

    // Destroy scene buffers (triangles, BVH, materials)
    auto destroyBuffer = [&](VkBuffer& buf, VkDeviceMemory& mem) {
        if (buf) {
            vkDestroyBuffer(m_context.getDevice(), buf, nullptr);
            buf = VK_NULL_HANDLE;
        }
        if (mem) {
            vkFreeMemory(m_context.getDevice(), mem, nullptr);
            mem = VK_NULL_HANDLE;
        }
    };

    destroyBuffer(m_triangleBuffer, m_triangleMemory);
    destroyBuffer(m_bvhBuffer, m_bvhMemory);
    destroyBuffer(m_materialBuffer, m_materialMemory);

    m_sceneValid = false;
}

VkShaderModule PathTracer::loadShaderModule(const std::string& filename) {
    std::ifstream file(filename, std::ios::ate | std::ios::binary);

    if (!file.is_open()) {
        std::cerr << "[PathTracer] Failed to open shader: " << filename << "\n";
        return VK_NULL_HANDLE;
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

    VkShaderModule module;
    if (vkCreateShaderModule(m_context.getDevice(), &createInfo, nullptr, &module) != VK_SUCCESS) {
        std::cerr << "[PathTracer] Failed to create shader module\n";
        return VK_NULL_HANDLE;
    }

    return module;
}

bool PathTracer::setScene(const std::vector<StructuralElement>& elements) {
    // Forward to terrain-aware overload with no terrain
    return setScene(elements, nullptr, "");
}

bool PathTracer::setScene(const std::vector<StructuralElement>& elements,
                          const TerrainMesh* terrain,
                          const std::string& terrainMaterialName) {
    // Store terrain material name for later texture index update
    m_terrainMaterialName = terrainMaterialName;

    // Build BVH from scene (with optional terrain)
    if (!buildSceneBVH(elements, terrain, terrainMaterialName, m_triangles, m_bvhNodes, m_materials)) {
        std::cerr << "[PathTracer] Failed to build scene BVH\n";
        m_sceneValid = false;
        return false;
    }

    // Clean up old buffers
    auto destroyBuffer = [&](VkBuffer& buf, VkDeviceMemory& mem) {
        if (buf) {
            vkDestroyBuffer(m_context.getDevice(), buf, nullptr);
            buf = VK_NULL_HANDLE;
        }
        if (mem) {
            vkFreeMemory(m_context.getDevice(), mem, nullptr);
            mem = VK_NULL_HANDLE;
        }
    };

    destroyBuffer(m_triangleBuffer, m_triangleMemory);
    destroyBuffer(m_bvhBuffer, m_bvhMemory);
    destroyBuffer(m_materialBuffer, m_materialMemory);

    // Create and upload triangle buffer - using HOST_VISIBLE for debugging
    VkDeviceSize triangleSize = sizeof(GPUTriangle) * m_triangles.size();
    m_context.createBuffer(
        triangleSize,
        VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
        m_triangleBuffer, m_triangleMemory
    );

    // Direct upload (no staging)
    void* data;
    vkMapMemory(m_context.getDevice(), m_triangleMemory, 0, triangleSize, 0, &data);
    std::memcpy(data, m_triangles.data(), triangleSize);
    vkUnmapMemory(m_context.getDevice(), m_triangleMemory);

    std::cout << "[PathTracer] Triangle buffer: " << triangleSize << " bytes, first tri v0=("
              << m_triangles[0].v0.x << "," << m_triangles[0].v0.y << "," << m_triangles[0].v0.z << ")\n";

    // Create and upload BVH buffer
    VkBuffer stagingBuffer;
    VkDeviceMemory stagingMemory;
    VkDeviceSize bvhSize = sizeof(GPUBVHNode) * m_bvhNodes.size();
    m_context.createBuffer(
        bvhSize,
        VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
        m_bvhBuffer, m_bvhMemory
    );

    m_context.createBuffer(
        bvhSize,
        VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
        stagingBuffer, stagingMemory
    );

    vkMapMemory(m_context.getDevice(), stagingMemory, 0, bvhSize, 0, &data);
    std::memcpy(data, m_bvhNodes.data(), bvhSize);
    vkUnmapMemory(m_context.getDevice(), stagingMemory);

    m_context.copyBuffer(stagingBuffer, m_bvhBuffer, bvhSize);

    vkDestroyBuffer(m_context.getDevice(), stagingBuffer, nullptr);
    vkFreeMemory(m_context.getDevice(), stagingMemory, nullptr);

    // Create and upload material buffer - using HOST_VISIBLE for reliability
    VkDeviceSize materialSize = sizeof(GPUPTMaterial) * m_materials.size();
    m_context.createBuffer(
        materialSize,
        VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
        m_materialBuffer, m_materialMemory
    );

    vkMapMemory(m_context.getDevice(), m_materialMemory, 0, materialSize, 0, &data);
    std::memcpy(data, m_materials.data(), materialSize);
    vkUnmapMemory(m_context.getDevice(), m_materialMemory);

    // Debug: Print first few materials
    std::cout << "[PathTracer] Materials uploaded: " << m_materials.size() << " materials\n";
    for (size_t i = 0; i < std::min(m_materials.size(), size_t(3)); i++) {
        std::cout << "[PathTracer] Material[" << i << "] albedo=("
                  << m_materials[i].albedo.r << ", "
                  << m_materials[i].albedo.g << ", "
                  << m_materials[i].albedo.b << ")\n";
    }

    m_sceneValid = true;
    std::cout << "[PathTracer] Scene uploaded: " << m_triangles.size() << " triangles\n";

    // Debug: Compute triangle bounding box
    if (!m_triangles.empty()) {
        vec3 minB(1e9f), maxB(-1e9f);
        for (const auto& tri : m_triangles) {
            vec3 v0(tri.v0.x, tri.v0.y, tri.v0.z);
            vec3 v1(tri.v1.x, tri.v1.y, tri.v1.z);
            vec3 v2(tri.v2.x, tri.v2.y, tri.v2.z);
            minB = glm::min(minB, glm::min(v0, glm::min(v1, v2)));
            maxB = glm::max(maxB, glm::max(v0, glm::max(v1, v2)));
        }
        std::cout << "[PathTracer] Triangle bounds: (" << minB.x << ", " << minB.y << ", " << minB.z
                  << ") to (" << maxB.x << ", " << maxB.y << ", " << maxB.z << ")\n";
    }

    return true;
}

void PathTracer::setCamera(const Camera& camera) {
    m_camera = camera;
}

void PathTracer::setClipPlane(const vec4& plane, bool enabled) {
    m_clipPlane = plane;
    m_enableClipping = enabled;
}

void PathTracer::setConfig(const PathTracerConfig& config) {
    m_config = config;
}

void PathTracer::setEnvironmentMap(EnvironmentMap* envMap) {
    m_envMap = envMap;
}

void PathTracer::createComputePipeline() {
    // Descriptor set layout
    std::vector<VkDescriptorSetLayoutBinding> bindings = {
        {0, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr},  // Accumulation image
        {1, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}, // UBO
        {2, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}, // Triangles
        {3, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}, // BVH nodes
        {4, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}, // Materials
        {5, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}, // Environment map
        {6, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, nullptr}, // Texture array
    };

    VkDescriptorSetLayoutCreateInfo layoutInfo{};
    layoutInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
    layoutInfo.bindingCount = static_cast<u32>(bindings.size());
    layoutInfo.pBindings = bindings.data();

    if (vkCreateDescriptorSetLayout(m_context.getDevice(), &layoutInfo, nullptr, &m_descriptorSetLayout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create path tracer descriptor set layout");
    }

    // Pipeline layout
    VkPipelineLayoutCreateInfo pipelineLayoutInfo{};
    pipelineLayoutInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    pipelineLayoutInfo.setLayoutCount = 1;
    pipelineLayoutInfo.pSetLayouts = &m_descriptorSetLayout;

    if (vkCreatePipelineLayout(m_context.getDevice(), &pipelineLayoutInfo, nullptr, &m_pipelineLayout) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create path tracer pipeline layout");
    }

    // Load compute shader
    VkShaderModule shaderModule = loadShaderModule("shaders/path_trace.comp.spv");
    if (!shaderModule) {
        throw std::runtime_error("Failed to load path_trace.comp.spv");
    }

    VkPipelineShaderStageCreateInfo stageInfo{};
    stageInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stageInfo.stage = VK_SHADER_STAGE_COMPUTE_BIT;
    stageInfo.module = shaderModule;
    stageInfo.pName = "main";

    VkComputePipelineCreateInfo pipelineInfo{};
    pipelineInfo.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO;
    pipelineInfo.stage = stageInfo;
    pipelineInfo.layout = m_pipelineLayout;

    if (vkCreateComputePipelines(m_context.getDevice(), m_context.getPipelineCache(),
                                  1, &pipelineInfo, nullptr, &m_pipeline) != VK_SUCCESS) {
        vkDestroyShaderModule(m_context.getDevice(), shaderModule, nullptr);
        throw std::runtime_error("Failed to create path tracer compute pipeline");
    }

    vkDestroyShaderModule(m_context.getDevice(), shaderModule, nullptr);
}

void PathTracer::createDescriptorSets() {
    // Descriptor pool
    std::vector<VkDescriptorPoolSize> poolSizes = {
        {VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1},
        {VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1},
        {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 3},
        {VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 2},  // Env map + texture array
    };

    VkDescriptorPoolCreateInfo poolInfo{};
    poolInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
    poolInfo.poolSizeCount = static_cast<u32>(poolSizes.size());
    poolInfo.pPoolSizes = poolSizes.data();
    poolInfo.maxSets = 1;

    if (vkCreateDescriptorPool(m_context.getDevice(), &poolInfo, nullptr, &m_descriptorPool) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create path tracer descriptor pool");
    }

    // Allocate descriptor set
    VkDescriptorSetAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
    allocInfo.descriptorPool = m_descriptorPool;
    allocInfo.descriptorSetCount = 1;
    allocInfo.pSetLayouts = &m_descriptorSetLayout;

    if (vkAllocateDescriptorSets(m_context.getDevice(), &allocInfo, &m_descriptorSet) != VK_SUCCESS) {
        throw std::runtime_error("Failed to allocate path tracer descriptor set");
    }

    // Update descriptor set
    VkDescriptorImageInfo accumImageInfo{};
    accumImageInfo.imageView = m_accumView;
    accumImageInfo.imageLayout = VK_IMAGE_LAYOUT_GENERAL;

    VkDescriptorBufferInfo uboInfo{};
    uboInfo.buffer = m_uboBuffer;
    uboInfo.offset = 0;
    uboInfo.range = sizeof(PathTraceUBO);

    VkDescriptorBufferInfo triangleInfo{};
    triangleInfo.buffer = m_triangleBuffer;
    triangleInfo.offset = 0;
    triangleInfo.range = VK_WHOLE_SIZE;

    VkDescriptorBufferInfo bvhInfo{};
    bvhInfo.buffer = m_bvhBuffer;
    bvhInfo.offset = 0;
    bvhInfo.range = VK_WHOLE_SIZE;

    VkDescriptorBufferInfo materialInfo{};
    materialInfo.buffer = m_materialBuffer;
    materialInfo.offset = 0;
    materialInfo.range = VK_WHOLE_SIZE;

    VkDescriptorImageInfo envMapInfo{};
    if (m_envMap && m_envMap->isLoaded()) {
        envMapInfo = m_envMap->getDescriptorInfo();
    } else {
        // Use a placeholder - we'll check in shader
        envMapInfo.imageView = m_accumView;  // Placeholder
        envMapInfo.imageLayout = VK_IMAGE_LAYOUT_GENERAL;
        envMapInfo.sampler = VK_NULL_HANDLE;
    }

    std::vector<VkWriteDescriptorSet> writes = {
        {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, nullptr, m_descriptorSet, 0, 0, 1,
         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, &accumImageInfo, nullptr, nullptr},
        {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, nullptr, m_descriptorSet, 1, 0, 1,
         VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, nullptr, &uboInfo, nullptr},
        {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, nullptr, m_descriptorSet, 2, 0, 1,
         VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, nullptr, &triangleInfo, nullptr},
        {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, nullptr, m_descriptorSet, 3, 0, 1,
         VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, nullptr, &bvhInfo, nullptr},
        {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, nullptr, m_descriptorSet, 4, 0, 1,
         VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, nullptr, &materialInfo, nullptr},
    };

    // Only add env map if we have a valid sampler
    if (m_envMap && m_envMap->isLoaded()) {
        writes.push_back({VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, nullptr, m_descriptorSet, 5, 0, 1,
                          VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, &envMapInfo, nullptr, nullptr});
    }

    // Add texture array if loaded
    VkDescriptorImageInfo textureArrayInfo{};
    if (m_texturesLoaded && m_textureArrayView && m_textureSampler) {
        textureArrayInfo.sampler = m_textureSampler;
        textureArrayInfo.imageView = m_textureArrayView;
        textureArrayInfo.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
        writes.push_back({VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, nullptr, m_descriptorSet, 6, 0, 1,
                          VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, &textureArrayInfo, nullptr, nullptr});
    }

    vkUpdateDescriptorSets(m_context.getDevice(), static_cast<u32>(writes.size()),
                           writes.data(), 0, nullptr);
}

void PathTracer::createBuffers() {
    // UBO buffer
    m_context.createBuffer(
        sizeof(PathTraceUBO),
        VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
        m_uboBuffer, m_uboMemory
    );

    vkMapMemory(m_context.getDevice(), m_uboMemory, 0, sizeof(PathTraceUBO), 0, &m_uboMapped);

    // Staging buffer for result download
    VkDeviceSize stagingSize = m_config.width * m_config.height * 4 * sizeof(f32);
    m_context.createBuffer(
        stagingSize,
        VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
        m_stagingBuffer, m_stagingMemory
    );
}

void PathTracer::createAccumulationImage() {
    // Clean up old image
    if (m_accumView) {
        vkDestroyImageView(m_context.getDevice(), m_accumView, nullptr);
        m_accumView = VK_NULL_HANDLE;
    }
    if (m_accumImage) {
        vkDestroyImage(m_context.getDevice(), m_accumImage, nullptr);
        m_accumImage = VK_NULL_HANDLE;
    }
    if (m_accumMemory) {
        vkFreeMemory(m_context.getDevice(), m_accumMemory, nullptr);
        m_accumMemory = VK_NULL_HANDLE;
    }

    // Create RGBA32F image for accumulation
    VkImageCreateInfo imageInfo{};
    imageInfo.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    imageInfo.imageType = VK_IMAGE_TYPE_2D;
    imageInfo.format = VK_FORMAT_R32G32B32A32_SFLOAT;
    imageInfo.extent = {m_config.width, m_config.height, 1};
    imageInfo.mipLevels = 1;
    imageInfo.arrayLayers = 1;
    imageInfo.samples = VK_SAMPLE_COUNT_1_BIT;
    imageInfo.tiling = VK_IMAGE_TILING_OPTIMAL;
    imageInfo.usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
    imageInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    imageInfo.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;

    if (vkCreateImage(m_context.getDevice(), &imageInfo, nullptr, &m_accumImage) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create accumulation image");
    }

    VkMemoryRequirements memReqs;
    vkGetImageMemoryRequirements(m_context.getDevice(), m_accumImage, &memReqs);

    VkMemoryAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocInfo.allocationSize = memReqs.size;
    allocInfo.memoryTypeIndex = m_context.findMemoryType(
        memReqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);

    if (vkAllocateMemory(m_context.getDevice(), &allocInfo, nullptr, &m_accumMemory) != VK_SUCCESS) {
        throw std::runtime_error("Failed to allocate accumulation image memory");
    }

    vkBindImageMemory(m_context.getDevice(), m_accumImage, m_accumMemory, 0);

    // Create image view
    VkImageViewCreateInfo viewInfo{};
    viewInfo.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    viewInfo.image = m_accumImage;
    viewInfo.viewType = VK_IMAGE_VIEW_TYPE_2D;
    viewInfo.format = VK_FORMAT_R32G32B32A32_SFLOAT;
    viewInfo.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    viewInfo.subresourceRange.baseMipLevel = 0;
    viewInfo.subresourceRange.levelCount = 1;
    viewInfo.subresourceRange.baseArrayLayer = 0;
    viewInfo.subresourceRange.layerCount = 1;

    if (vkCreateImageView(m_context.getDevice(), &viewInfo, nullptr, &m_accumView) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create accumulation image view");
    }

    // Transition to GENERAL layout
    VkCommandBuffer cmd = m_context.beginSingleTimeCommands();

    VkImageMemoryBarrier barrier{};
    barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    barrier.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    barrier.newLayout = VK_IMAGE_LAYOUT_GENERAL;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.image = m_accumImage;
    barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    barrier.subresourceRange.baseMipLevel = 0;
    barrier.subresourceRange.levelCount = 1;
    barrier.subresourceRange.baseArrayLayer = 0;
    barrier.subresourceRange.layerCount = 1;
    barrier.srcAccessMask = 0;
    barrier.dstAccessMask = VK_ACCESS_SHADER_WRITE_BIT;

    vkCmdPipelineBarrier(cmd,
                         VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
                         VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &barrier);

    m_context.endSingleTimeCommands(cmd);
}

void PathTracer::updateUBO() {
    PathTraceUBO ubo{};

    // Camera matrices
    f32 aspect = static_cast<f32>(m_config.width) / static_cast<f32>(m_config.height);
    mat4 view = m_camera.getViewMatrix();
    mat4 proj = m_camera.getProjectionMatrix(aspect);

    ubo.cameraInvView = glm::inverse(view);
    ubo.cameraInvProj = glm::inverse(proj);
    ubo.cameraPosition = vec4(m_camera.position, 1.0f);

    // Light
    ubo.lightDirection = vec4(glm::normalize(vec3(-0.5f, -1.0f, -0.3f)), 1.0f);
    ubo.lightColor = vec4(1.0f, 0.98f, 0.95f, 1.0f);

    // Environment map
    if (m_envMap && m_envMap->isLoaded()) {
        ubo.envMapInfo = vec4(1.0f, 1.0f, 0.0f, 0.0f);
    } else {
        ubo.envMapInfo = vec4(0.0f, 1.0f, 0.0f, 0.0f);
    }

    // Section clipping
    ubo.clipPlane = m_clipPlane;
    ubo.enableClipping = m_enableClipping ? 1 : 0;

    // Render state
    ubo.frameIndex = m_frameIndex;
    ubo.sampleCount = m_currentSample;
    ubo.maxBounces = m_config.maxBounces;
    ubo.triangleCount = static_cast<u32>(m_triangles.size());
    ubo.nodeCount = static_cast<u32>(m_bvhNodes.size());
    ubo.materialCount = static_cast<u32>(m_materials.size());
    ubo.enableNEE = m_config.enableNEE ? 1 : 0;
    ubo.enableRR = m_config.enableRR ? 1 : 0;
    ubo.rrStartDepth = m_config.rrStartDepth;
    ubo.exposure = m_config.exposure;
    ubo.tonemapMode = m_config.tonemapMode;
    ubo.width = m_config.width;
    ubo.height = m_config.height;
    ubo.uvScale = m_uvScale;

    std::memcpy(m_uboMapped, &ubo, sizeof(ubo));
}

void PathTracer::startRender() {
    if (!m_sceneValid) {
        std::cerr << "[PathTracer] Cannot start render - no valid scene\n";
        m_state = PathTracerState::Error;
        return;
    }

    // Clean up render resources only (keep scene data)
    cleanupRenderResources();

    // Create resources
    createAccumulationImage();
    createBuffers();
    createComputePipeline();
    createDescriptorSets();

    // Reset state
    m_currentSample = 0;
    m_frameIndex = 0;
    m_stopRequested = false;
    m_state = PathTracerState::Rendering;

    // Clear accumulation buffer
    VkCommandBuffer cmd = m_context.beginSingleTimeCommands();

    VkClearColorValue clearColor = {{0.0f, 0.0f, 0.0f, 0.0f}};
    VkImageSubresourceRange range{};
    range.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    range.baseMipLevel = 0;
    range.levelCount = 1;
    range.baseArrayLayer = 0;
    range.layerCount = 1;

    vkCmdClearColorImage(cmd, m_accumImage, VK_IMAGE_LAYOUT_GENERAL, &clearColor, 1, &range);

    m_context.endSingleTimeCommands(cmd);

    std::cout << "[PathTracer] Started render: " << m_config.width << "x" << m_config.height
              << ", " << m_config.samplesPerPixel << " spp\n";
}

bool PathTracer::renderFrame() {
    if (m_state != PathTracerState::Rendering) {
        return false;
    }

    if (m_stopRequested) {
        m_state = PathTracerState::Idle;
        return false;
    }

    // Check if complete
    if (m_currentSample >= m_config.samplesPerPixel) {
        downloadResult();
        if (m_config.enableDenoising) {
            applyDenoising();
        }
        tonemapResult();
        m_state = PathTracerState::Complete;

        if (m_progressCallback) {
            m_progressCallback(1.0f);
        }

        return false;
    }

    // Update UBO
    updateUBO();

    // Dispatch compute shader
    VkCommandBuffer cmd = m_context.beginSingleTimeCommands();

    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, m_pipeline);
    vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, m_pipelineLayout,
                            0, 1, &m_descriptorSet, 0, nullptr);

    // Dispatch: 16x16 workgroups
    u32 groupCountX = (m_config.width + 15) / 16;
    u32 groupCountY = (m_config.height + 15) / 16;
    vkCmdDispatch(cmd, groupCountX, groupCountY, 1);

    m_context.endSingleTimeCommands(cmd);

    // Update state
    m_currentSample += m_config.samplesPerFrame;
    m_frameIndex++;

    if (m_progressCallback) {
        m_progressCallback(getProgress());
    }

    return true;
}

void PathTracer::stopRender() {
    m_stopRequested = true;
}

f32 PathTracer::getProgress() const {
    if (m_config.samplesPerPixel == 0) return 0.0f;
    return static_cast<f32>(m_currentSample) / static_cast<f32>(m_config.samplesPerPixel);
}

void PathTracer::downloadResult() {
    // Copy image to staging buffer
    VkCommandBuffer cmd = m_context.beginSingleTimeCommands();

    // Transition to TRANSFER_SRC
    VkImageMemoryBarrier barrier{};
    barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    barrier.oldLayout = VK_IMAGE_LAYOUT_GENERAL;
    barrier.newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.image = m_accumImage;
    barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    barrier.subresourceRange.baseMipLevel = 0;
    barrier.subresourceRange.levelCount = 1;
    barrier.subresourceRange.baseArrayLayer = 0;
    barrier.subresourceRange.layerCount = 1;
    barrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;

    vkCmdPipelineBarrier(cmd,
                         VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                         VK_PIPELINE_STAGE_TRANSFER_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &barrier);

    // Copy
    VkBufferImageCopy region{};
    region.bufferOffset = 0;
    region.bufferRowLength = 0;
    region.bufferImageHeight = 0;
    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    region.imageSubresource.mipLevel = 0;
    region.imageSubresource.baseArrayLayer = 0;
    region.imageSubresource.layerCount = 1;
    region.imageOffset = {0, 0, 0};
    region.imageExtent = {m_config.width, m_config.height, 1};

    vkCmdCopyImageToBuffer(cmd, m_accumImage, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                           m_stagingBuffer, 1, &region);

    // Transition back to GENERAL
    barrier.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    barrier.newLayout = VK_IMAGE_LAYOUT_GENERAL;
    barrier.srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    barrier.dstAccessMask = VK_ACCESS_SHADER_WRITE_BIT;

    vkCmdPipelineBarrier(cmd,
                         VK_PIPELINE_STAGE_TRANSFER_BIT,
                         VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &barrier);

    m_context.endSingleTimeCommands(cmd);

    // Read staging buffer
    size_t pixelCount = m_config.width * m_config.height;
    m_hdrPixels.resize(pixelCount * 4);

    void* data;
    vkMapMemory(m_context.getDevice(), m_stagingMemory, 0, VK_WHOLE_SIZE, 0, &data);
    std::memcpy(m_hdrPixels.data(), data, pixelCount * 4 * sizeof(f32));
    vkUnmapMemory(m_context.getDevice(), m_stagingMemory);

    // Normalize by sample count
    f32 invSamples = 1.0f / static_cast<f32>(m_currentSample);
    for (size_t i = 0; i < pixelCount * 4; ++i) {
        m_hdrPixels[i] *= invSamples;
    }
}

void PathTracer::applyDenoising() {
    // Simple temporal variance-based denoising
    // For production quality, integrate Intel Open Image Denoise (OIDN)

    size_t pixelCount = m_config.width * m_config.height;

    // 3x3 edge-aware filter
    std::vector<f32> filtered(pixelCount * 4);

    for (u32 y = 0; y < m_config.height; ++y) {
        for (u32 x = 0; x < m_config.width; ++x) {
            size_t idx = (y * m_config.width + x) * 4;

            vec3 centerColor(m_hdrPixels[idx], m_hdrPixels[idx + 1], m_hdrPixels[idx + 2]);
            f32 centerLum = 0.2126f * centerColor.r + 0.7152f * centerColor.g + 0.0722f * centerColor.b;

            vec3 sum(0.0f);
            f32 totalWeight = 0.0f;

            for (int dy = -1; dy <= 1; ++dy) {
                for (int dx = -1; dx <= 1; ++dx) {
                    int nx = std::clamp(static_cast<int>(x) + dx, 0, static_cast<int>(m_config.width) - 1);
                    int ny = std::clamp(static_cast<int>(y) + dy, 0, static_cast<int>(m_config.height) - 1);
                    size_t nidx = (ny * m_config.width + nx) * 4;

                    vec3 neighborColor(m_hdrPixels[nidx], m_hdrPixels[nidx + 1], m_hdrPixels[nidx + 2]);
                    f32 neighborLum = 0.2126f * neighborColor.r + 0.7152f * neighborColor.g + 0.0722f * neighborColor.b;

                    f32 lumDiff = std::abs(centerLum - neighborLum);
                    f32 weight = std::exp(-lumDiff * 10.0f);

                    f32 dist = std::sqrt(static_cast<f32>(dx * dx + dy * dy));
                    weight *= std::exp(-dist * 0.5f);

                    sum += neighborColor * weight;
                    totalWeight += weight;
                }
            }

            vec3 result = sum / std::max(totalWeight, 0.0001f);
            filtered[idx] = result.r;
            filtered[idx + 1] = result.g;
            filtered[idx + 2] = result.b;
            filtered[idx + 3] = m_hdrPixels[idx + 3];
        }
    }

    m_hdrPixels = std::move(filtered);
}

void PathTracer::tonemapResult() {
    size_t pixelCount = m_config.width * m_config.height;
    m_ldrPixels.resize(pixelCount * 4);

    f32 exposure = m_config.exposure;

    for (size_t i = 0; i < pixelCount; ++i) {
        vec3 hdr(m_hdrPixels[i * 4], m_hdrPixels[i * 4 + 1], m_hdrPixels[i * 4 + 2]);

        // Apply exposure
        hdr *= exposure;

        // Tonemapping
        vec3 ldr;
        switch (m_config.tonemapMode) {
            case 0: // Reinhard
                ldr = hdr / (hdr + vec3(1.0f));
                break;
            case 1: // ACES
            default: {
                const f32 a = 2.51f;
                const f32 b = 0.03f;
                const f32 c = 2.43f;
                const f32 d = 0.59f;
                const f32 e = 0.14f;
                ldr = (hdr * (a * hdr + vec3(b))) / (hdr * (c * hdr + vec3(d)) + vec3(e));
                ldr = glm::clamp(ldr, vec3(0.0f), vec3(1.0f));
                break;
            }
            case 2: { // Uncharted2
                auto tonemap = [](vec3 x) {
                    const f32 A = 0.15f, B = 0.50f, C = 0.10f, D = 0.20f, E = 0.02f, F = 0.30f;
                    return ((x * (A * x + vec3(C * B)) + vec3(D * E)) / (x * (A * x + vec3(B)) + vec3(D * F))) - vec3(E / F);
                };
                const f32 W = 11.2f;
                ldr = tonemap(hdr * 2.0f) / tonemap(vec3(W));
                break;
            }
        }

        // Gamma correction
        ldr = glm::pow(ldr, vec3(1.0f / 2.2f));

        // Convert to 8-bit
        m_ldrPixels[i * 4 + 0] = static_cast<u8>(glm::clamp(ldr.r * 255.0f, 0.0f, 255.0f));
        m_ldrPixels[i * 4 + 1] = static_cast<u8>(glm::clamp(ldr.g * 255.0f, 0.0f, 255.0f));
        m_ldrPixels[i * 4 + 2] = static_cast<u8>(glm::clamp(ldr.b * 255.0f, 0.0f, 255.0f));
        m_ldrPixels[i * 4 + 3] = 255;
    }
}

bool PathTracer::savePNG(const std::string& filepath, f32 exposure) {
    if (m_ldrPixels.empty()) {
        std::cerr << "[PathTracer] No result to save\n";
        return false;
    }

    // If exposure is different, re-tonemap
    if (std::abs(exposure - m_config.exposure) > 0.01f) {
        f32 oldExposure = m_config.exposure;
        m_config.exposure = exposure;
        tonemapResult();
        m_config.exposure = oldExposure;
    }

    // Write directly - shader already handles Y flip for Vulkan coordinates
    if (stbi_write_png(filepath.c_str(), m_config.width, m_config.height, 4,
                       m_ldrPixels.data(), m_config.width * 4) == 0) {
        std::cerr << "[PathTracer] Failed to write PNG: " << filepath << "\n";
        return false;
    }

    std::cout << "[PathTracer] Saved PNG: " << filepath << "\n";
    return true;
}

bool PathTracer::saveEXR(const std::string& filepath) {
    if (m_hdrPixels.empty()) {
        std::cerr << "[PathTracer] No HDR result to save\n";
        return false;
    }

    // For proper EXR export, use tinyexr or OpenEXR library
    // For now, save as HDR format (simpler)
    std::string hdrPath = filepath;
    if (hdrPath.ends_with(".exr")) {
        hdrPath = hdrPath.substr(0, hdrPath.length() - 4) + ".hdr";
    }

    // Convert to RGB float (drop alpha) - no flip needed, shader handles it
    std::vector<f32> rgb(m_config.width * m_config.height * 3);
    for (size_t i = 0; i < m_config.width * m_config.height; ++i) {
        rgb[i * 3 + 0] = m_hdrPixels[i * 4 + 0];
        rgb[i * 3 + 1] = m_hdrPixels[i * 4 + 1];
        rgb[i * 3 + 2] = m_hdrPixels[i * 4 + 2];
    }

    if (stbi_write_hdr(hdrPath.c_str(), m_config.width, m_config.height, 3, rgb.data()) == 0) {
        std::cerr << "[PathTracer] Failed to write HDR: " << hdrPath << "\n";
        return false;
    }

    std::cout << "[PathTracer] Saved HDR: " << hdrPath << "\n";
    return true;
}

// ============================================================================
// Texture Loading
// ============================================================================

int PathTracer::getTextureIndex(const std::string& materialName) const {
    auto it = m_materialTextureIndices.find(materialName);
    if (it != m_materialTextureIndices.end()) {
        return it->second;
    }
    return -1;
}

bool PathTracer::loadMaterialTextures(const std::string& materialsDir) {
    namespace fs = std::filesystem;

    // Clean up existing textures
    cleanupTextures();
    m_materialTextureIndices.clear();
    m_loadedMaterials.clear();

    // Try multiple paths to find material_map.json
    std::vector<std::string> searchPaths = {
        materialsDir + "/material_map.json",
        "materials/material_map.json",
        "../materials/material_map.json",
        "../../materials/material_map.json",
        "../../../ArchEngine_kernel/materials/material_map.json"
    };

    std::string mapPath;
    std::string basePath;
    for (const auto& path : searchPaths) {
        if (fs::exists(path)) {
            mapPath = path;
            // Extract base directory for texture loading
            basePath = fs::path(path).parent_path().string();
            std::cout << "[PathTracer] Found material_map.json at: " << path << "\n";
            break;
        }
    }

    if (mapPath.empty()) {
        std::cerr << "[PathTracer] Could not find material_map.json in any search path\n";
        return false;
    }

    // Store base path for texture loading
    m_materialsBasePath = basePath;

    std::ifstream mapFile(mapPath);
    if (!mapFile.is_open()) {
        std::cerr << "[PathTracer] Could not open " << mapPath << "\n";
        return false;
    }

    json materialMap;
    try {
        mapFile >> materialMap;
    } catch (const std::exception& e) {
        std::cerr << "[PathTracer] Failed to parse material_map.json: " << e.what() << "\n";
        return false;
    }

    // Collect polyhaven materials to load
    struct TextureToLoad {
        std::string materialName;
        std::string albedoPath;
        std::string normalPath;
        std::string roughnessPath;
        std::string aoPath;
    };
    std::vector<TextureToLoad> texturesToLoad;

    if (materialMap.contains("materials")) {
        for (auto& [key, value] : materialMap["materials"].items()) {
            // Only load polyhaven materials (they have actual texture files)
            if (key.find("polyhaven/") == 0 && value.contains("folder")) {
                std::string folder = m_materialsBasePath + "/" + value["folder"].get<std::string>();
                if (fs::exists(folder)) {
                    TextureToLoad tex;
                    tex.materialName = key;

                    auto& textures = value["textures"];
                    tex.albedoPath = folder + "/" + textures.value("albedo", "albedo.jpg");
                    tex.normalPath = folder + "/" + textures.value("normal", "normal.jpg");
                    tex.roughnessPath = folder + "/" + textures.value("roughness", "roughness.jpg");
                    tex.aoPath = folder + "/" + textures.value("ao", "ao.jpg");

                    // Check if files exist
                    if (fs::exists(tex.albedoPath)) {
                        texturesToLoad.push_back(tex);
                    }
                }
            }
        }
    }

    // Also scan polyhaven folder for any materials not in material_map.json
    std::string polyhavenDir = m_materialsBasePath + "/polyhaven";
    if (fs::exists(polyhavenDir) && fs::is_directory(polyhavenDir)) {
        std::set<std::string> existingMaterials;
        for (const auto& tex : texturesToLoad) {
            existingMaterials.insert(tex.materialName);
        }

        for (const auto& entry : fs::directory_iterator(polyhavenDir)) {
            if (entry.is_directory()) {
                std::string matName = "polyhaven/" + entry.path().filename().string();
                // Skip if already in the list
                if (existingMaterials.count(matName) > 0) continue;

                std::string folder = entry.path().string();
                // Check for albedo texture (try common extensions)
                std::string albedoPath;
                for (const auto& ext : {".jpg", ".png", ".jpeg"}) {
                    std::string testPath = folder + "/albedo" + ext;
                    if (fs::exists(testPath)) {
                        albedoPath = testPath;
                        break;
                    }
                }

                if (!albedoPath.empty()) {
                    TextureToLoad tex;
                    tex.materialName = matName;
                    tex.albedoPath = albedoPath;

                    // Find other textures with same extension
                    std::string ext = fs::path(albedoPath).extension().string();
                    tex.normalPath = folder + "/normal" + ext;
                    tex.roughnessPath = folder + "/roughness" + ext;
                    tex.aoPath = folder + "/ao" + ext;

                    // Use fallbacks if files don't exist
                    if (!fs::exists(tex.normalPath)) tex.normalPath = folder + "/normal.jpg";
                    if (!fs::exists(tex.roughnessPath)) tex.roughnessPath = folder + "/roughness.jpg";
                    if (!fs::exists(tex.aoPath)) tex.aoPath = folder + "/ao.jpg";

                    texturesToLoad.push_back(tex);
                    std::cout << "[PathTracer] Found additional material: " << matName << "\n";
                }
            }
        }
    }

    if (texturesToLoad.empty()) {
        std::cout << "[PathTracer] No Poly Haven textures found to load\n";
        std::cout << "[PathTracer] Checked base path: " << m_materialsBasePath << "\n";
        return true;  // Not an error, just no textures
    }

    std::cout << "[PathTracer] Found textures to load:\n";
    for (const auto& tex : texturesToLoad) {
        std::cout << "  - " << tex.materialName << " from " << tex.albedoPath << "\n";
    }

    // Each material uses 4 layers: albedo, normal, roughness, ao
    u32 layersPerMaterial = 4;
    u32 totalLayers = static_cast<u32>(texturesToLoad.size()) * layersPerMaterial;

    std::cout << "[PathTracer] Loading " << texturesToLoad.size() << " Poly Haven materials ("
              << totalLayers << " texture layers)\n";

    // Load all textures into CPU memory first
    struct LoadedTexture {
        std::vector<u8> data;
        int width, height, channels;
    };
    std::vector<LoadedTexture> loadedTextures(totalLayers);

    u32 maxWidth = 0, maxHeight = 0;

    // Ensure consistent texture loading - don't flip for Vulkan coordinate system
    // (Environment map loading sets this to true, so we must reset it)
    stbi_set_flip_vertically_on_load(false);

    for (size_t i = 0; i < texturesToLoad.size(); ++i) {
        const auto& tex = texturesToLoad[i];
        u32 baseLayer = static_cast<u32>(i) * layersPerMaterial;

        // Load each texture type
        std::array<std::string, 4> paths = {tex.albedoPath, tex.normalPath, tex.roughnessPath, tex.aoPath};
        for (u32 j = 0; j < 4; ++j) {
            int w, h, c;
            stbi_uc* data = stbi_load(paths[j].c_str(), &w, &h, &c, 4);  // Force RGBA
            if (data) {
                loadedTextures[baseLayer + j].width = w;
                loadedTextures[baseLayer + j].height = h;
                loadedTextures[baseLayer + j].channels = 4;
                loadedTextures[baseLayer + j].data.assign(data, data + w * h * 4);
                stbi_image_free(data);

                maxWidth = std::max(maxWidth, static_cast<u32>(w));
                maxHeight = std::max(maxHeight, static_cast<u32>(h));
            } else {
                // Create a default texture (gray)
                loadedTextures[baseLayer + j].width = 64;
                loadedTextures[baseLayer + j].height = 64;
                loadedTextures[baseLayer + j].channels = 4;
                loadedTextures[baseLayer + j].data.resize(64 * 64 * 4);
                u8 defaultVal = (j == 0) ? 128 : ((j == 1) ? 127 : ((j == 2) ? 128 : 255));
                for (size_t p = 0; p < 64 * 64; ++p) {
                    loadedTextures[baseLayer + j].data[p * 4 + 0] = defaultVal;
                    loadedTextures[baseLayer + j].data[p * 4 + 1] = (j == 1) ? 127 : defaultVal;  // Normal Y
                    loadedTextures[baseLayer + j].data[p * 4 + 2] = (j == 1) ? 255 : defaultVal;  // Normal Z
                    loadedTextures[baseLayer + j].data[p * 4 + 3] = 255;
                }
            }
        }
    }

    // Use the max resolution found (capped at 2048)
    m_textureResolution = std::min(std::max(maxWidth, maxHeight), 2048u);
    m_textureArrayLayers = totalLayers;

    // Create texture array
    VkImageCreateInfo imageInfo{};
    imageInfo.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    imageInfo.imageType = VK_IMAGE_TYPE_2D;
    imageInfo.format = VK_FORMAT_R8G8B8A8_UNORM;
    imageInfo.extent = {m_textureResolution, m_textureResolution, 1};
    imageInfo.mipLevels = 1;
    imageInfo.arrayLayers = m_textureArrayLayers;
    imageInfo.samples = VK_SAMPLE_COUNT_1_BIT;
    imageInfo.tiling = VK_IMAGE_TILING_OPTIMAL;
    imageInfo.usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    imageInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    imageInfo.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;

    if (vkCreateImage(m_context.getDevice(), &imageInfo, nullptr, &m_textureArray) != VK_SUCCESS) {
        std::cerr << "[PathTracer] Failed to create texture array image\n";
        return false;
    }

    // Allocate memory
    VkMemoryRequirements memReqs;
    vkGetImageMemoryRequirements(m_context.getDevice(), m_textureArray, &memReqs);

    VkMemoryAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocInfo.allocationSize = memReqs.size;
    allocInfo.memoryTypeIndex = m_context.findMemoryType(memReqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);

    if (vkAllocateMemory(m_context.getDevice(), &allocInfo, nullptr, &m_textureArrayMemory) != VK_SUCCESS) {
        std::cerr << "[PathTracer] Failed to allocate texture array memory\n";
        return false;
    }

    vkBindImageMemory(m_context.getDevice(), m_textureArray, m_textureArrayMemory, 0);

    // Create staging buffer for texture upload
    VkDeviceSize layerSize = m_textureResolution * m_textureResolution * 4;
    VkBuffer stagingBuffer;
    VkDeviceMemory stagingMemory;
    m_context.createBuffer(
        layerSize,
        VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
        stagingBuffer, stagingMemory
    );

    // Transition image to transfer destination
    VkCommandBuffer cmd = m_context.beginSingleTimeCommands();

    VkImageMemoryBarrier barrier{};
    barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    barrier.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    barrier.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.image = m_textureArray;
    barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    barrier.subresourceRange.baseMipLevel = 0;
    barrier.subresourceRange.levelCount = 1;
    barrier.subresourceRange.baseArrayLayer = 0;
    barrier.subresourceRange.layerCount = m_textureArrayLayers;
    barrier.srcAccessMask = 0;
    barrier.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;

    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &barrier);

    m_context.endSingleTimeCommands(cmd);

    // Upload each layer
    for (u32 layer = 0; layer < totalLayers; ++layer) {
        const auto& tex = loadedTextures[layer];

        // Resize texture to target resolution if needed
        std::vector<u8> resizedData;
        if (tex.width == static_cast<int>(m_textureResolution) && tex.height == static_cast<int>(m_textureResolution)) {
            resizedData = tex.data;
        } else {
            // Simple nearest-neighbor resize
            resizedData.resize(m_textureResolution * m_textureResolution * 4);
            for (u32 y = 0; y < m_textureResolution; ++y) {
                for (u32 x = 0; x < m_textureResolution; ++x) {
                    u32 srcX = x * tex.width / m_textureResolution;
                    u32 srcY = y * tex.height / m_textureResolution;
                    u32 srcIdx = (srcY * tex.width + srcX) * 4;
                    u32 dstIdx = (y * m_textureResolution + x) * 4;
                    resizedData[dstIdx + 0] = tex.data[srcIdx + 0];
                    resizedData[dstIdx + 1] = tex.data[srcIdx + 1];
                    resizedData[dstIdx + 2] = tex.data[srcIdx + 2];
                    resizedData[dstIdx + 3] = tex.data[srcIdx + 3];
                }
            }
        }

        // Copy to staging buffer
        void* data;
        vkMapMemory(m_context.getDevice(), stagingMemory, 0, layerSize, 0, &data);
        std::memcpy(data, resizedData.data(), layerSize);
        vkUnmapMemory(m_context.getDevice(), stagingMemory);

        // Copy from staging buffer to image layer
        cmd = m_context.beginSingleTimeCommands();

        VkBufferImageCopy region{};
        region.bufferOffset = 0;
        region.bufferRowLength = 0;
        region.bufferImageHeight = 0;
        region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.imageSubresource.mipLevel = 0;
        region.imageSubresource.baseArrayLayer = layer;
        region.imageSubresource.layerCount = 1;
        region.imageOffset = {0, 0, 0};
        region.imageExtent = {m_textureResolution, m_textureResolution, 1};

        vkCmdCopyBufferToImage(cmd, stagingBuffer, m_textureArray,
                               VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);

        m_context.endSingleTimeCommands(cmd);
    }

    // Clean up staging buffer
    vkDestroyBuffer(m_context.getDevice(), stagingBuffer, nullptr);
    vkFreeMemory(m_context.getDevice(), stagingMemory, nullptr);

    // Transition to shader read optimal
    cmd = m_context.beginSingleTimeCommands();

    barrier.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    barrier.newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;

    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &barrier);

    m_context.endSingleTimeCommands(cmd);

    // Create image view for 2D array
    VkImageViewCreateInfo viewInfo{};
    viewInfo.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    viewInfo.image = m_textureArray;
    viewInfo.viewType = VK_IMAGE_VIEW_TYPE_2D_ARRAY;
    viewInfo.format = VK_FORMAT_R8G8B8A8_UNORM;
    viewInfo.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    viewInfo.subresourceRange.baseMipLevel = 0;
    viewInfo.subresourceRange.levelCount = 1;
    viewInfo.subresourceRange.baseArrayLayer = 0;
    viewInfo.subresourceRange.layerCount = m_textureArrayLayers;

    if (vkCreateImageView(m_context.getDevice(), &viewInfo, nullptr, &m_textureArrayView) != VK_SUCCESS) {
        std::cerr << "[PathTracer] Failed to create texture array view\n";
        return false;
    }

    // Create sampler
    VkSamplerCreateInfo samplerInfo{};
    samplerInfo.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
    samplerInfo.magFilter = VK_FILTER_LINEAR;
    samplerInfo.minFilter = VK_FILTER_LINEAR;
    samplerInfo.addressModeU = VK_SAMPLER_ADDRESS_MODE_REPEAT;
    samplerInfo.addressModeV = VK_SAMPLER_ADDRESS_MODE_REPEAT;
    samplerInfo.addressModeW = VK_SAMPLER_ADDRESS_MODE_REPEAT;
    samplerInfo.anisotropyEnable = VK_TRUE;
    samplerInfo.maxAnisotropy = 8.0f;
    samplerInfo.borderColor = VK_BORDER_COLOR_FLOAT_OPAQUE_WHITE;
    samplerInfo.unnormalizedCoordinates = VK_FALSE;
    samplerInfo.compareEnable = VK_FALSE;
    samplerInfo.mipmapMode = VK_SAMPLER_MIPMAP_MODE_LINEAR;

    if (vkCreateSampler(m_context.getDevice(), &samplerInfo, nullptr, &m_textureSampler) != VK_SUCCESS) {
        std::cerr << "[PathTracer] Failed to create texture sampler\n";
        return false;
    }

    // Store material to texture index mapping
    for (size_t i = 0; i < texturesToLoad.size(); ++i) {
        m_materialTextureIndices[texturesToLoad[i].materialName] = static_cast<int>(i * layersPerMaterial);
        m_loadedMaterials.push_back(texturesToLoad[i].materialName);
    }

    m_texturesLoaded = true;
    std::cout << "[PathTracer] Loaded " << texturesToLoad.size() << " materials at "
              << m_textureResolution << "x" << m_textureResolution << " resolution\n";

    return true;
}

void PathTracer::updateMaterialTextureIndices(const std::vector<StructuralElement>& elements) {
    if (!m_texturesLoaded) {
        std::cout << "[PathTracer] updateMaterialTextureIndices: textures not loaded\n";
        return;
    }
    if (m_materials.empty()) {
        std::cout << "[PathTracer] updateMaterialTextureIndices: no materials\n";
        return;
    }

    std::cout << "[PathTracer] Updating texture indices for " << elements.size()
              << " elements, " << m_materials.size() << " materials\n";
    std::cout << "[PathTracer] Available textures:\n";
    for (const auto& [name, idx] : m_materialTextureIndices) {
        std::cout << "  " << name << " -> " << idx << "\n";
    }

    // Resolve material name for each element (same logic as bvh.cpp and renderer.cpp)
    auto resolveMaterialName = [](const StructuralElement& elem) -> std::string {
        const std::string& matName = elem.material;

        // If material is already specified and non-empty, use it
        if (!matName.empty() && matName != "default") {
            // Check for polyhaven prefix
            if (matName.find("polyhaven/") == 0) {
                return matName;
            }

            // Convert to lowercase for matching
            std::string lower = matName;
            std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

            // Keyword-based mapping (same as renderer and bvh.cpp)
            if (lower.find("brick") != std::string::npos) {
                return "polyhaven/brick_wall_006";
            }
            if (lower.find("concrete") != std::string::npos || lower.find("cement") != std::string::npos ||
                lower.find("stone") != std::string::npos) {
                return "polyhaven/concrete_wall_008";
            }
            if (lower.find("drywall") != std::string::npos || lower.find("plaster") != std::string::npos ||
                lower.find("gypsum") != std::string::npos || lower.find("paint") != std::string::npos ||
                lower.find("stucco") != std::string::npos || lower.find("interior") != std::string::npos ||
                lower.find("tyvek") != std::string::npos || lower.find("membrane") != std::string::npos ||
                lower.find("poly") != std::string::npos || lower.find("vapor") != std::string::npos) {
                return "polyhaven/concrete_wall_008";
            }
            if (lower.find("tile") != std::string::npos || lower.find("ceramic") != std::string::npos) {
                return "polyhaven/concrete_floor_003";
            }
            if (lower.find("wood") != std::string::npos || lower.find("timber") != std::string::npos ||
                lower.find("osb") != std::string::npos || lower.find("plywood") != std::string::npos) {
                return "polyhaven/wood_floor_deck";
            }
            if (lower.find("vinyl") != std::string::npos || lower.find("siding") != std::string::npos) {
                return "polyhaven/concrete_wall_008";
            }
            if (lower.find("glass") != std::string::npos || lower.find("glazing") != std::string::npos ||
                lower.find("window") != std::string::npos) {
                return "glass";
            }
            if (lower.find("metal") != std::string::npos || lower.find("steel") != std::string::npos ||
                lower.find("aluminum") != std::string::npos) {
                return "polyhaven/metal_plate_02";
            }
            if (lower.find("shingle") != std::string::npos || lower.find("asphalt") != std::string::npos ||
                lower.find("roof") != std::string::npos || lower.find("slate") != std::string::npos) {
                return "polyhaven/roof_slates_02";
            }
            if (lower.find("grass") != std::string::npos || lower.find("lawn") != std::string::npos) {
                return "polyhaven/grass_path_2";
            }
            if (lower.find("gravel") != std::string::npos || lower.find("patio") != std::string::npos) {
                return "polyhaven/gravel_concrete";
            }
            if (lower.find("door") != std::string::npos) {
                return "polyhaven/wood_floor_deck";
            }
            // Generic "wall" without specific material
            if (lower == "wall" || lower == "partition") {
                return "polyhaven/concrete_wall_008";
            }
        }

        // Default based on element type
        switch (elem.type) {
            case ElementType::Wall: return "polyhaven/brick_wall_006";
            case ElementType::Floor: return "polyhaven/concrete_floor_003";
            case ElementType::Roof: return "polyhaven/roof_slates_02";
            case ElementType::Door:
            case ElementType::Beam:
            case ElementType::Column: return "polyhaven/wood_floor_deck";
            case ElementType::Window: return "glass";
            default: return "polyhaven/concrete_wall_008";
        }
    };

    // Material color lookup (approximate Poly Haven colors)
    auto getPolyHavenColor = [](const std::string& matName) -> vec4 {
        if (matName.find("glass") != std::string::npos) {
            return vec4(0.95f, 0.97f, 1.0f, 0.15f);  // Clear glass with low alpha
        } else if (matName.find("brick") != std::string::npos) {
            return vec4(0.45f, 0.28f, 0.22f, 1.0f);  // Reddish brown brick
        } else if (matName.find("concrete") != std::string::npos) {
            return vec4(0.5f, 0.48f, 0.45f, 1.0f);   // Grey concrete
        } else if (matName.find("wood") != std::string::npos) {
            return vec4(0.4f, 0.28f, 0.18f, 1.0f);   // Warm wood
        } else if (matName.find("roof") != std::string::npos) {
            return vec4(0.25f, 0.24f, 0.23f, 1.0f);  // Dark slate
        } else if (matName.find("asphalt") != std::string::npos) {
            return vec4(0.15f, 0.15f, 0.15f, 1.0f);  // Dark grey
        } else if (matName.find("grass") != std::string::npos) {
            return vec4(0.25f, 0.35f, 0.15f, 1.0f);  // Green
        } else if (matName.find("gravel") != std::string::npos) {
            return vec4(0.45f, 0.42f, 0.4f, 1.0f);   // Grey gravel
        } else if (matName.find("metal") != std::string::npos) {
            return vec4(0.55f, 0.55f, 0.55f, 1.0f);  // Metal grey
        }
        return vec4(0.5f, 0.5f, 0.5f, 1.0f);  // Default grey
    };

    // Update material texture indices AND albedo colors
    size_t numUpdated = 0;
    std::cout << "[PathTracer] Updating materials for " << std::min(elements.size(), m_materials.size()) << " elements\n";
    for (size_t i = 0; i < elements.size() && i < m_materials.size(); ++i) {
        std::string matName = resolveMaterialName(elements[i]);
        int texIndex = getTextureIndex(matName);

        // Debug first few materials
        if (i < 5) {
            std::cout << "[PathTracer] Element " << i << " type=" << static_cast<int>(elements[i].type)
                      << " input='" << elements[i].material << "'"
                      << " -> resolved=" << matName << " texIndex=" << texIndex << "\n";
        }

        // Always update albedo color to match resolved material
        m_materials[i].albedo = getPolyHavenColor(matName);

        // Set glass material properties
        if (matName.find("glass") != std::string::npos) {
            m_materials[i].properties.x = 0.02f;  // Very smooth
            m_materials[i].properties.y = 0.0f;   // Non-metallic
            m_materials[i].properties.z = 1.5f;   // IOR
            m_materials[i].properties.w = 0.95f;  // High transmission
        }

        if (texIndex >= 0) {
            m_materials[i].texIndices.x = static_cast<f32>(texIndex);
            numUpdated++;
        }
    }

    // Update terrain material if it exists (it's the material after all elements)
    if (m_materials.size() > elements.size() && !m_terrainMaterialName.empty()) {
        size_t terrainMatIndex = elements.size();
        int texIndex = getTextureIndex(m_terrainMaterialName);
        if (texIndex >= 0) {
            m_materials[terrainMatIndex].texIndices.x = static_cast<f32>(texIndex);
            std::cout << "[PathTracer] Updated terrain material '" << m_terrainMaterialName
                      << "' with texture index " << texIndex << "\n";
            numUpdated++;
        } else {
            std::cout << "[PathTracer] Warning: terrain texture '" << m_terrainMaterialName
                      << "' not found in loaded textures\n";
        }
    }

    std::cout << "[PathTracer] Updated " << numUpdated << " material texture indices\n";

    // Re-upload material buffer
    if (numUpdated > 0 && m_materialBuffer && m_materialMemory) {
        void* data;
        VkDeviceSize materialSize = sizeof(GPUPTMaterial) * m_materials.size();
        vkMapMemory(m_context.getDevice(), m_materialMemory, 0, materialSize, 0, &data);
        std::memcpy(data, m_materials.data(), materialSize);
        vkUnmapMemory(m_context.getDevice(), m_materialMemory);
    }
}

} // namespace arch
