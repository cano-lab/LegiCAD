#include "environment_map.hpp"
#include <stdexcept>
#include <cstring>
#include <cmath>
#include <vector>
#include <iostream>
#include <fstream>

#define STB_IMAGE_IMPLEMENTATION
#include "../external/stb_image.h"

// Debug logging to file (for crash diagnosis)
static void logToFile(const std::string& msg) {
    std::ofstream f("hdri_debug.log", std::ios::app);
    if (f.is_open()) {
        f << msg << std::endl;
        f.flush();
    }
}

namespace arch {

EnvironmentMap::EnvironmentMap(VulkanContext& context) : m_context(context) {
    createSampler();
}

EnvironmentMap::~EnvironmentMap() {
    cleanupComputePipelines();
    cleanupIBL();
    cleanup();
}

void EnvironmentMap::cleanup() {
    if (m_sampler != VK_NULL_HANDLE) {
        vkDestroySampler(m_context.getDevice(), m_sampler, nullptr);
        m_sampler = VK_NULL_HANDLE;
    }
    if (m_cubemapView != VK_NULL_HANDLE) {
        vkDestroyImageView(m_context.getDevice(), m_cubemapView, nullptr);
        m_cubemapView = VK_NULL_HANDLE;
    }
    if (m_cubemapImage != VK_NULL_HANDLE) {
        vkDestroyImage(m_context.getDevice(), m_cubemapImage, nullptr);
        m_cubemapImage = VK_NULL_HANDLE;
    }
    if (m_cubemapMemory != VK_NULL_HANDLE) {
        vkFreeMemory(m_context.getDevice(), m_cubemapMemory, nullptr);
        m_cubemapMemory = VK_NULL_HANDLE;
    }
    m_loaded = false;
}

void EnvironmentMap::createSampler() {
    VkSamplerCreateInfo samplerInfo{};
    samplerInfo.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
    samplerInfo.magFilter = VK_FILTER_LINEAR;
    samplerInfo.minFilter = VK_FILTER_LINEAR;
    samplerInfo.mipmapMode = VK_SAMPLER_MIPMAP_MODE_LINEAR;
    samplerInfo.addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    if (m_context.supportsSamplerAnisotropy()) {
        samplerInfo.anisotropyEnable = VK_TRUE;
        samplerInfo.maxAnisotropy = m_context.getMaxSamplerAnisotropy();
    } else {
        samplerInfo.anisotropyEnable = VK_FALSE;
        samplerInfo.maxAnisotropy = 1.0f;
    }
    samplerInfo.borderColor = VK_BORDER_COLOR_FLOAT_OPAQUE_BLACK;
    samplerInfo.compareEnable = VK_FALSE;
    samplerInfo.minLod = 0.0f;
    samplerInfo.maxLod = 1.0f;

    if (vkCreateSampler(m_context.getDevice(), &samplerInfo, nullptr, &m_sampler) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create environment map sampler");
    }
}

bool EnvironmentMap::loadFromFile(const std::string& filepath) {
    logToFile("=== loadFromFile START: " + filepath);

    // Don't flip - equirectangular HDRIs use standard orientation
    stbi_set_flip_vertically_on_load(false);

    logToFile("Loading HDR file...");
    int width, height, channels;
    float* hdrData = stbi_loadf(filepath.c_str(), &width, &height, &channels, 3);

    if (!hdrData) {
        logToFile("ERROR: Failed to load HDR file");
        return false;
    }
    logToFile("HDR loaded: " + std::to_string(width) + "x" + std::to_string(height));

    logToFile("Creating cubemap from equirectangular...");
    createCubemapFromEquirectangular(hdrData, width, height);
    logToFile("Cubemap created");

    stbi_image_free(hdrData);

    m_loaded = true;
    logToFile("=== loadFromFile SUCCESS");
    return true;
}

void EnvironmentMap::createProceduralSky() {
    // Create a simple procedural sky cubemap
    const u32 size = m_cubemapSize;
    std::vector<float> faceData(size * size * 4);  // RGBA float

    // Cleanup existing if any
    if (m_cubemapImage != VK_NULL_HANDLE) {
        m_context.waitIdle();
        vkDestroyImageView(m_context.getDevice(), m_cubemapView, nullptr);
        vkDestroyImage(m_context.getDevice(), m_cubemapImage, nullptr);
        vkFreeMemory(m_context.getDevice(), m_cubemapMemory, nullptr);
    }

    // Create cubemap image
    VkImageCreateInfo imageInfo{};
    imageInfo.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    imageInfo.imageType = VK_IMAGE_TYPE_2D;
    imageInfo.format = VK_FORMAT_R16G16B16A16_SFLOAT;  // HDR format
    imageInfo.extent = {size, size, 1};
    imageInfo.mipLevels = 1;
    imageInfo.arrayLayers = 6;  // 6 faces
    imageInfo.samples = VK_SAMPLE_COUNT_1_BIT;
    imageInfo.tiling = VK_IMAGE_TILING_OPTIMAL;
    imageInfo.usage = VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_SAMPLED_BIT;
    imageInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    imageInfo.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    imageInfo.flags = VK_IMAGE_CREATE_CUBE_COMPATIBLE_BIT;

    if (vkCreateImage(m_context.getDevice(), &imageInfo, nullptr, &m_cubemapImage) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create cubemap image");
    }

    // Allocate memory
    VkMemoryRequirements memReqs;
    vkGetImageMemoryRequirements(m_context.getDevice(), m_cubemapImage, &memReqs);

    VkMemoryAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocInfo.allocationSize = memReqs.size;
    allocInfo.memoryTypeIndex = m_context.findMemoryType(memReqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);

    if (vkAllocateMemory(m_context.getDevice(), &allocInfo, nullptr, &m_cubemapMemory) != VK_SUCCESS) {
        throw std::runtime_error("Failed to allocate cubemap memory");
    }
    vkBindImageMemory(m_context.getDevice(), m_cubemapImage, m_cubemapMemory, 0);

    // Create staging buffer for all 6 faces
    VkDeviceSize faceSize = size * size * 4 * sizeof(uint16_t);  // RGBA16F per face
    VkDeviceSize totalSize = faceSize * 6;

    VkBuffer stagingBuffer;
    VkDeviceMemory stagingMemory;
    m_context.createBuffer(totalSize, VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
                           VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
                           stagingBuffer, stagingMemory);

    // Map staging buffer
    void* data;
    vkMapMemory(m_context.getDevice(), stagingMemory, 0, totalSize, 0, &data);
    uint16_t* halfData = static_cast<uint16_t*>(data);

    // Helper to convert float to half
    auto floatToHalf = [](float f) -> uint16_t {
        uint32_t x = *reinterpret_cast<uint32_t*>(&f);
        uint32_t sign = (x >> 16) & 0x8000;
        int32_t exp = ((x >> 23) & 0xFF) - 127 + 15;
        uint32_t mant = x & 0x007FFFFF;

        if (exp <= 0) {
            return static_cast<uint16_t>(sign);
        } else if (exp >= 31) {
            return static_cast<uint16_t>(sign | 0x7C00);
        }
        return static_cast<uint16_t>(sign | (exp << 10) | (mant >> 13));
    };

    // Generate each face
    for (int face = 0; face < 6; ++face) {
        uint16_t* facePtr = halfData + (face * size * size * 4);

        for (u32 y = 0; y < size; ++y) {
            for (u32 x = 0; x < size; ++x) {
                float u = (static_cast<float>(x) + 0.5f) / size * 2.0f - 1.0f;
                float v = (static_cast<float>(y) + 0.5f) / size * 2.0f - 1.0f;

                vec3 dir = getCubemapDirection(face, u, v);
                dir = glm::normalize(dir);

                // Procedural sky color based on direction
                vec3 color;
                if (dir.y > 0.0f) {
                    // Sky
                    vec3 zenith = vec3(0.4f, 0.6f, 0.9f);
                    vec3 horizon = vec3(0.7f, 0.8f, 0.95f);
                    float t = std::pow(dir.y, 0.8f);
                    color = glm::mix(horizon, zenith, t);
                } else {
                    // Ground
                    vec3 ground = vec3(0.35f, 0.45f, 0.3f);
                    vec3 groundFar = vec3(0.4f, 0.5f, 0.45f);
                    float t = std::pow(-dir.y, 0.5f);
                    color = glm::mix(groundFar, ground, t);
                }

                u32 idx = (y * size + x) * 4;
                facePtr[idx + 0] = floatToHalf(color.r);
                facePtr[idx + 1] = floatToHalf(color.g);
                facePtr[idx + 2] = floatToHalf(color.b);
                facePtr[idx + 3] = floatToHalf(1.0f);
            }
        }
    }

    vkUnmapMemory(m_context.getDevice(), stagingMemory);

    // Transition image and copy data
    VkCommandBuffer cmd = m_context.beginSingleTimeCommands();

    // Transition to transfer dst
    VkImageMemoryBarrier barrier{};
    barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    barrier.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    barrier.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.image = m_cubemapImage;
    barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    barrier.subresourceRange.baseMipLevel = 0;
    barrier.subresourceRange.levelCount = 1;
    barrier.subresourceRange.baseArrayLayer = 0;
    barrier.subresourceRange.layerCount = 6;
    barrier.srcAccessMask = 0;
    barrier.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;

    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &barrier);

    // Copy each face
    std::vector<VkBufferImageCopy> copyRegions(6);
    for (int face = 0; face < 6; ++face) {
        copyRegions[face].bufferOffset = face * faceSize;
        copyRegions[face].bufferRowLength = 0;
        copyRegions[face].bufferImageHeight = 0;
        copyRegions[face].imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        copyRegions[face].imageSubresource.mipLevel = 0;
        copyRegions[face].imageSubresource.baseArrayLayer = face;
        copyRegions[face].imageSubresource.layerCount = 1;
        copyRegions[face].imageOffset = {0, 0, 0};
        copyRegions[face].imageExtent = {size, size, 1};
    }

    vkCmdCopyBufferToImage(cmd, stagingBuffer, m_cubemapImage, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                           static_cast<u32>(copyRegions.size()), copyRegions.data());

    // Transition to shader read
    barrier.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    barrier.newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;

    // Make visible to both fragment and compute shaders (for IBL generation)
    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TRANSFER_BIT,
                         VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT | VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &barrier);

    m_context.endSingleTimeCommands(cmd);

    // Cleanup staging
    vkDestroyBuffer(m_context.getDevice(), stagingBuffer, nullptr);
    vkFreeMemory(m_context.getDevice(), stagingMemory, nullptr);

    // Create image view
    VkImageViewCreateInfo viewInfo{};
    viewInfo.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    viewInfo.image = m_cubemapImage;
    viewInfo.viewType = VK_IMAGE_VIEW_TYPE_CUBE;
    viewInfo.format = VK_FORMAT_R16G16B16A16_SFLOAT;
    viewInfo.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    viewInfo.subresourceRange.baseMipLevel = 0;
    viewInfo.subresourceRange.levelCount = 1;
    viewInfo.subresourceRange.baseArrayLayer = 0;
    viewInfo.subresourceRange.layerCount = 6;

    if (vkCreateImageView(m_context.getDevice(), &viewInfo, nullptr, &m_cubemapView) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create cubemap image view");
    }

    m_loaded = true;
}

void EnvironmentMap::createCubemapFromEquirectangular(const float* hdrData, int width, int height) {
    const u32 size = m_cubemapSize;

    // Cleanup existing if any
    if (m_cubemapImage != VK_NULL_HANDLE) {
        m_context.waitIdle();
        vkDestroyImageView(m_context.getDevice(), m_cubemapView, nullptr);
        vkDestroyImage(m_context.getDevice(), m_cubemapImage, nullptr);
        vkFreeMemory(m_context.getDevice(), m_cubemapMemory, nullptr);
    }

    // Create cubemap image
    VkImageCreateInfo imageInfo{};
    imageInfo.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    imageInfo.imageType = VK_IMAGE_TYPE_2D;
    imageInfo.format = VK_FORMAT_R16G16B16A16_SFLOAT;
    imageInfo.extent = {size, size, 1};
    imageInfo.mipLevels = 1;
    imageInfo.arrayLayers = 6;
    imageInfo.samples = VK_SAMPLE_COUNT_1_BIT;
    imageInfo.tiling = VK_IMAGE_TILING_OPTIMAL;
    imageInfo.usage = VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_SAMPLED_BIT;
    imageInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    imageInfo.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    imageInfo.flags = VK_IMAGE_CREATE_CUBE_COMPATIBLE_BIT;

    if (vkCreateImage(m_context.getDevice(), &imageInfo, nullptr, &m_cubemapImage) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create cubemap image");
    }

    VkMemoryRequirements memReqs;
    vkGetImageMemoryRequirements(m_context.getDevice(), m_cubemapImage, &memReqs);

    VkMemoryAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocInfo.allocationSize = memReqs.size;
    allocInfo.memoryTypeIndex = m_context.findMemoryType(memReqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);

    if (vkAllocateMemory(m_context.getDevice(), &allocInfo, nullptr, &m_cubemapMemory) != VK_SUCCESS) {
        throw std::runtime_error("Failed to allocate cubemap memory");
    }
    vkBindImageMemory(m_context.getDevice(), m_cubemapImage, m_cubemapMemory, 0);

    // Create staging buffer
    VkDeviceSize faceSize = size * size * 4 * sizeof(uint16_t);
    VkDeviceSize totalSize = faceSize * 6;

    VkBuffer stagingBuffer;
    VkDeviceMemory stagingMemory;
    m_context.createBuffer(totalSize, VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
                           VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
                           stagingBuffer, stagingMemory);

    void* data;
    vkMapMemory(m_context.getDevice(), stagingMemory, 0, totalSize, 0, &data);
    uint16_t* halfData = static_cast<uint16_t*>(data);

    auto floatToHalf = [](float f) -> uint16_t {
        uint32_t x = *reinterpret_cast<uint32_t*>(&f);
        uint32_t sign = (x >> 16) & 0x8000;
        int32_t exp = ((x >> 23) & 0xFF) - 127 + 15;
        uint32_t mant = x & 0x007FFFFF;
        if (exp <= 0) return static_cast<uint16_t>(sign);
        if (exp >= 31) return static_cast<uint16_t>(sign | 0x7C00);
        return static_cast<uint16_t>(sign | (exp << 10) | (mant >> 13));
    };

    // Sample equirectangular for each face
    for (int face = 0; face < 6; ++face) {
        uint16_t* facePtr = halfData + (face * size * size * 4);

        for (u32 y = 0; y < size; ++y) {
            for (u32 x = 0; x < size; ++x) {
                float u = (static_cast<float>(x) + 0.5f) / size * 2.0f - 1.0f;
                float v = (static_cast<float>(y) + 0.5f) / size * 2.0f - 1.0f;

                vec3 dir = glm::normalize(getCubemapDirection(face, u, v));

                // Convert direction to equirectangular UV
                float phi = std::atan2(dir.z, dir.x);
                float theta = std::asin(glm::clamp(dir.y, -1.0f, 1.0f));

                float eqU = (phi + glm::pi<float>()) / (2.0f * glm::pi<float>());
                float eqV = (theta + glm::pi<float>() * 0.5f) / glm::pi<float>();

                // Sample HDR data (bilinear)
                int px = static_cast<int>(eqU * width) % width;
                int py = static_cast<int>((1.0f - eqV) * height) % height;
                if (py < 0) py = 0;
                if (py >= height) py = height - 1;

                int srcIdx = (py * width + px) * 3;
                float r = hdrData[srcIdx + 0];
                float g = hdrData[srcIdx + 1];
                float b = hdrData[srcIdx + 2];

                u32 idx = (y * size + x) * 4;
                facePtr[idx + 0] = floatToHalf(r);
                facePtr[idx + 1] = floatToHalf(g);
                facePtr[idx + 2] = floatToHalf(b);
                facePtr[idx + 3] = floatToHalf(1.0f);
            }
        }
    }

    vkUnmapMemory(m_context.getDevice(), stagingMemory);

    // Transfer to GPU
    VkCommandBuffer cmd = m_context.beginSingleTimeCommands();

    VkImageMemoryBarrier barrier{};
    barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    barrier.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    barrier.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.image = m_cubemapImage;
    barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    barrier.subresourceRange.baseMipLevel = 0;
    barrier.subresourceRange.levelCount = 1;
    barrier.subresourceRange.baseArrayLayer = 0;
    barrier.subresourceRange.layerCount = 6;
    barrier.srcAccessMask = 0;
    barrier.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;

    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &barrier);

    std::vector<VkBufferImageCopy> copyRegions(6);
    for (int face = 0; face < 6; ++face) {
        copyRegions[face].bufferOffset = face * faceSize;
        copyRegions[face].bufferRowLength = 0;
        copyRegions[face].bufferImageHeight = 0;
        copyRegions[face].imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        copyRegions[face].imageSubresource.mipLevel = 0;
        copyRegions[face].imageSubresource.baseArrayLayer = face;
        copyRegions[face].imageSubresource.layerCount = 1;
        copyRegions[face].imageOffset = {0, 0, 0};
        copyRegions[face].imageExtent = {size, size, 1};
    }

    vkCmdCopyBufferToImage(cmd, stagingBuffer, m_cubemapImage, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                           static_cast<u32>(copyRegions.size()), copyRegions.data());

    barrier.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    barrier.newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;

    // Make visible to both fragment and compute shaders (for IBL generation)
    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TRANSFER_BIT,
                         VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT | VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &barrier);

    m_context.endSingleTimeCommands(cmd);

    vkDestroyBuffer(m_context.getDevice(), stagingBuffer, nullptr);
    vkFreeMemory(m_context.getDevice(), stagingMemory, nullptr);

    // Create image view
    VkImageViewCreateInfo viewInfo{};
    viewInfo.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    viewInfo.image = m_cubemapImage;
    viewInfo.viewType = VK_IMAGE_VIEW_TYPE_CUBE;
    viewInfo.format = VK_FORMAT_R16G16B16A16_SFLOAT;
    viewInfo.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    viewInfo.subresourceRange.baseMipLevel = 0;
    viewInfo.subresourceRange.levelCount = 1;
    viewInfo.subresourceRange.baseArrayLayer = 0;
    viewInfo.subresourceRange.layerCount = 6;

    if (vkCreateImageView(m_context.getDevice(), &viewInfo, nullptr, &m_cubemapView) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create cubemap image view");
    }
}

vec3 EnvironmentMap::getCubemapDirection(int face, float u, float v) {
    // Standard cubemap face directions
    switch (face) {
        case 0: return vec3( 1.0f, -v,    -u);     // +X
        case 1: return vec3(-1.0f, -v,     u);     // -X
        case 2: return vec3( u,     1.0f,  v);     // +Y
        case 3: return vec3( u,    -1.0f, -v);     // -Y
        case 4: return vec3( u,    -v,     1.0f);  // +Z
        case 5: return vec3(-u,    -v,    -1.0f);  // -Z
        default: return vec3(0.0f, 1.0f, 0.0f);
    }
}

VkDescriptorImageInfo EnvironmentMap::getDescriptorInfo() const {
    VkDescriptorImageInfo info{};
    info.sampler = m_sampler;
    info.imageView = m_cubemapView;
    info.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    return info;
}

// ============================================================================
// IBL (Image-Based Lighting) Implementation
// ============================================================================

void EnvironmentMap::cleanupIBL() {
    auto device = m_context.getDevice();

    // Reset descriptor pool to free all allocated descriptor sets
    if (m_computeDescriptorPool != VK_NULL_HANDLE) {
        vkResetDescriptorPool(device, m_computeDescriptorPool, 0);
    }

    if (m_iblSampler) {
        vkDestroySampler(device, m_iblSampler, nullptr);
        m_iblSampler = VK_NULL_HANDLE;
    }

    if (m_irradianceView) {
        vkDestroyImageView(device, m_irradianceView, nullptr);
        m_irradianceView = VK_NULL_HANDLE;
    }
    if (m_irradianceImage) {
        vkDestroyImage(device, m_irradianceImage, nullptr);
        m_irradianceImage = VK_NULL_HANDLE;
    }
    if (m_irradianceMemory) {
        vkFreeMemory(device, m_irradianceMemory, nullptr);
        m_irradianceMemory = VK_NULL_HANDLE;
    }

    if (m_prefilteredView) {
        vkDestroyImageView(device, m_prefilteredView, nullptr);
        m_prefilteredView = VK_NULL_HANDLE;
    }
    if (m_prefilteredImage) {
        vkDestroyImage(device, m_prefilteredImage, nullptr);
        m_prefilteredImage = VK_NULL_HANDLE;
    }
    if (m_prefilteredMemory) {
        vkFreeMemory(device, m_prefilteredMemory, nullptr);
        m_prefilteredMemory = VK_NULL_HANDLE;
    }

    if (m_brdfLutView) {
        vkDestroyImageView(device, m_brdfLutView, nullptr);
        m_brdfLutView = VK_NULL_HANDLE;
    }
    if (m_brdfLutImage) {
        vkDestroyImage(device, m_brdfLutImage, nullptr);
        m_brdfLutImage = VK_NULL_HANDLE;
    }
    if (m_brdfLutMemory) {
        vkFreeMemory(device, m_brdfLutMemory, nullptr);
        m_brdfLutMemory = VK_NULL_HANDLE;
    }

    m_iblGenerated = false;
}

void EnvironmentMap::createIBLSampler() {
    VkSamplerCreateInfo samplerInfo{};
    samplerInfo.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
    samplerInfo.magFilter = VK_FILTER_LINEAR;
    samplerInfo.minFilter = VK_FILTER_LINEAR;
    samplerInfo.mipmapMode = VK_SAMPLER_MIPMAP_MODE_LINEAR;
    samplerInfo.addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.minLod = 0.0f;
    samplerInfo.maxLod = static_cast<float>(m_prefilteredMipLevels);
    if (m_context.supportsSamplerAnisotropy()) {
        samplerInfo.anisotropyEnable = VK_TRUE;
        samplerInfo.maxAnisotropy = m_context.getMaxSamplerAnisotropy();
    }

    if (vkCreateSampler(m_context.getDevice(), &samplerInfo, nullptr, &m_iblSampler) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create IBL sampler");
    }
}

bool EnvironmentMap::generateIBLTextures(const IBLConfig& config) {
    logToFile("=== generateIBLTextures START");

    if (!m_loaded) {
        logToFile("ERROR: No environment map loaded");
        std::cerr << "[EnvironmentMap] Cannot generate IBL: no environment map loaded" << std::endl;
        return false;
    }

    std::cout << "[EnvironmentMap] Generating IBL textures..." << std::endl;

    // Clean up any existing IBL resources
    logToFile("Cleaning up IBL...");
    cleanupIBL();

    m_prefilteredMipLevels = config.prefilteredMipLevels;

    // Create IBL sampler first
    logToFile("Creating IBL sampler...");
    createIBLSampler();

    // Create compute pipelines if not already created
    logToFile("Creating compute pipelines...");
    try {
        createComputePipelines();
        logToFile("Compute pipelines created");
    } catch (const std::exception& e) {
        logToFile("ERROR creating compute pipelines: " + std::string(e.what()));
        std::cerr << "[EnvironmentMap] Failed to create compute pipelines: " << e.what() << std::endl;
        cleanupIBL();
        return false;
    }

    // Create texture resources
    logToFile("Creating irradiance map...");
    if (!createIrradianceMap(config)) {
        logToFile("ERROR: Failed to create irradiance map");
        std::cerr << "[EnvironmentMap] Failed to create irradiance map" << std::endl;
        cleanupIBL();
        return false;
    }

    logToFile("Creating prefiltered map...");
    if (!createPrefilteredMap(config)) {
        logToFile("ERROR: Failed to create prefiltered map");
        std::cerr << "[EnvironmentMap] Failed to create prefiltered map" << std::endl;
        cleanupIBL();
        return false;
    }

    logToFile("Creating BRDF LUT...");
    if (!createBRDFLut(config)) {
        logToFile("ERROR: Failed to create BRDF LUT");
        std::cerr << "[EnvironmentMap] Failed to create BRDF LUT" << std::endl;
        cleanupIBL();
        return false;
    }

    // Run compute shaders to generate IBL textures
    logToFile("Running BRDF LUT compute...");
    try {
        runBRDFLutCompute(config);
        logToFile("Running irradiance compute...");
        runIrradianceCompute(config);
        logToFile("Running prefilter compute...");
        runPrefilterCompute(config);
        logToFile("All compute shaders completed");
    } catch (const std::exception& e) {
        logToFile("ERROR in IBL compute: " + std::string(e.what()));
        std::cerr << "[EnvironmentMap] Failed to run IBL compute: " << e.what() << std::endl;
        cleanupIBL();
        return false;
    }

    m_iblGenerated = true;
    logToFile("=== generateIBLTextures SUCCESS");
    std::cout << "[EnvironmentMap] IBL textures generated successfully" << std::endl;
    return true;
}

bool EnvironmentMap::createIrradianceMap(const IBLConfig& config) {
    auto device = m_context.getDevice();
    u32 size = config.irradianceSize;

    // Create irradiance cubemap image
    VkImageCreateInfo imageInfo{};
    imageInfo.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    imageInfo.imageType = VK_IMAGE_TYPE_2D;
    imageInfo.format = VK_FORMAT_R16G16B16A16_SFLOAT;
    imageInfo.extent = {size, size, 1};
    imageInfo.mipLevels = 1;
    imageInfo.arrayLayers = 6;
    imageInfo.samples = VK_SAMPLE_COUNT_1_BIT;
    imageInfo.tiling = VK_IMAGE_TILING_OPTIMAL;
    imageInfo.usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    imageInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    imageInfo.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    imageInfo.flags = VK_IMAGE_CREATE_CUBE_COMPATIBLE_BIT;

    if (vkCreateImage(device, &imageInfo, nullptr, &m_irradianceImage) != VK_SUCCESS) {
        return false;
    }

    VkMemoryRequirements memReqs;
    vkGetImageMemoryRequirements(device, m_irradianceImage, &memReqs);

    VkMemoryAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocInfo.allocationSize = memReqs.size;
    allocInfo.memoryTypeIndex = m_context.findMemoryType(memReqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);

    if (vkAllocateMemory(device, &allocInfo, nullptr, &m_irradianceMemory) != VK_SUCCESS) {
        return false;
    }
    vkBindImageMemory(device, m_irradianceImage, m_irradianceMemory, 0);

    // Create image view
    VkImageViewCreateInfo viewInfo{};
    viewInfo.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    viewInfo.image = m_irradianceImage;
    viewInfo.viewType = VK_IMAGE_VIEW_TYPE_CUBE;
    viewInfo.format = VK_FORMAT_R16G16B16A16_SFLOAT;
    viewInfo.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    viewInfo.subresourceRange.baseMipLevel = 0;
    viewInfo.subresourceRange.levelCount = 1;
    viewInfo.subresourceRange.baseArrayLayer = 0;
    viewInfo.subresourceRange.layerCount = 6;

    if (vkCreateImageView(device, &viewInfo, nullptr, &m_irradianceView) != VK_SUCCESS) {
        return false;
    }

    // Transition all array layers (6 for cubemap) to shader read layout
    m_context.transitionImageLayout(m_irradianceImage, VK_FORMAT_R16G16B16A16_SFLOAT,
                                    VK_IMAGE_LAYOUT_UNDEFINED,
                                    VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
                                    1, 6);  // 1 mip level, 6 array layers

    return true;
}

bool EnvironmentMap::createPrefilteredMap(const IBLConfig& config) {
    auto device = m_context.getDevice();
    u32 size = config.prefilteredSize;
    u32 mipLevels = config.prefilteredMipLevels;

    // Create prefiltered cubemap with mip chain
    VkImageCreateInfo imageInfo{};
    imageInfo.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    imageInfo.imageType = VK_IMAGE_TYPE_2D;
    imageInfo.format = VK_FORMAT_R16G16B16A16_SFLOAT;
    imageInfo.extent = {size, size, 1};
    imageInfo.mipLevels = mipLevels;
    imageInfo.arrayLayers = 6;
    imageInfo.samples = VK_SAMPLE_COUNT_1_BIT;
    imageInfo.tiling = VK_IMAGE_TILING_OPTIMAL;
    imageInfo.usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    imageInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    imageInfo.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    imageInfo.flags = VK_IMAGE_CREATE_CUBE_COMPATIBLE_BIT;

    if (vkCreateImage(device, &imageInfo, nullptr, &m_prefilteredImage) != VK_SUCCESS) {
        return false;
    }

    VkMemoryRequirements memReqs;
    vkGetImageMemoryRequirements(device, m_prefilteredImage, &memReqs);

    VkMemoryAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocInfo.allocationSize = memReqs.size;
    allocInfo.memoryTypeIndex = m_context.findMemoryType(memReqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);

    if (vkAllocateMemory(device, &allocInfo, nullptr, &m_prefilteredMemory) != VK_SUCCESS) {
        return false;
    }
    vkBindImageMemory(device, m_prefilteredImage, m_prefilteredMemory, 0);

    // Create image view (all mip levels)
    VkImageViewCreateInfo viewInfo{};
    viewInfo.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    viewInfo.image = m_prefilteredImage;
    viewInfo.viewType = VK_IMAGE_VIEW_TYPE_CUBE;
    viewInfo.format = VK_FORMAT_R16G16B16A16_SFLOAT;
    viewInfo.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    viewInfo.subresourceRange.baseMipLevel = 0;
    viewInfo.subresourceRange.levelCount = mipLevels;
    viewInfo.subresourceRange.baseArrayLayer = 0;
    viewInfo.subresourceRange.layerCount = 6;

    if (vkCreateImageView(device, &viewInfo, nullptr, &m_prefilteredView) != VK_SUCCESS) {
        return false;
    }

    // Transition ALL mip levels and array layers to shader read layout
    // (6 array layers for cubemap, mipLevels for prefiltered mip chain)
    m_context.transitionImageLayout(m_prefilteredImage, VK_FORMAT_R16G16B16A16_SFLOAT,
                                    VK_IMAGE_LAYOUT_UNDEFINED,
                                    VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
                                    mipLevels, 6);

    return true;
}

bool EnvironmentMap::createBRDFLut(const IBLConfig& config) {
    auto device = m_context.getDevice();
    u32 size = config.brdfLutSize;

    // Create BRDF LUT image (2D, RG16F)
    VkImageCreateInfo imageInfo{};
    imageInfo.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    imageInfo.imageType = VK_IMAGE_TYPE_2D;
    imageInfo.format = VK_FORMAT_R16G16_SFLOAT;
    imageInfo.extent = {size, size, 1};
    imageInfo.mipLevels = 1;
    imageInfo.arrayLayers = 1;
    imageInfo.samples = VK_SAMPLE_COUNT_1_BIT;
    imageInfo.tiling = VK_IMAGE_TILING_OPTIMAL;
    imageInfo.usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    imageInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    imageInfo.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;

    if (vkCreateImage(device, &imageInfo, nullptr, &m_brdfLutImage) != VK_SUCCESS) {
        return false;
    }

    VkMemoryRequirements memReqs;
    vkGetImageMemoryRequirements(device, m_brdfLutImage, &memReqs);

    VkMemoryAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocInfo.allocationSize = memReqs.size;
    allocInfo.memoryTypeIndex = m_context.findMemoryType(memReqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);

    if (vkAllocateMemory(device, &allocInfo, nullptr, &m_brdfLutMemory) != VK_SUCCESS) {
        return false;
    }
    vkBindImageMemory(device, m_brdfLutImage, m_brdfLutMemory, 0);

    // Create image view
    VkImageViewCreateInfo viewInfo{};
    viewInfo.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    viewInfo.image = m_brdfLutImage;
    viewInfo.viewType = VK_IMAGE_VIEW_TYPE_2D;
    viewInfo.format = VK_FORMAT_R16G16_SFLOAT;
    viewInfo.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    viewInfo.subresourceRange.baseMipLevel = 0;
    viewInfo.subresourceRange.levelCount = 1;
    viewInfo.subresourceRange.baseArrayLayer = 0;
    viewInfo.subresourceRange.layerCount = 1;

    if (vkCreateImageView(device, &viewInfo, nullptr, &m_brdfLutView) != VK_SUCCESS) {
        return false;
    }

    // Transition to shader read layout
    m_context.transitionImageLayout(m_brdfLutImage, VK_FORMAT_R16G16_SFLOAT,
                                    VK_IMAGE_LAYOUT_UNDEFINED,
                                    VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);

    return true;
}

VkDescriptorImageInfo EnvironmentMap::getIrradianceDescriptorInfo() const {
    VkDescriptorImageInfo info{};
    info.sampler = m_iblSampler;
    info.imageView = m_irradianceView;
    info.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    return info;
}

VkDescriptorImageInfo EnvironmentMap::getPrefilteredDescriptorInfo() const {
    VkDescriptorImageInfo info{};
    info.sampler = m_iblSampler;
    info.imageView = m_prefilteredView;
    info.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    return info;
}

VkDescriptorImageInfo EnvironmentMap::getBRDFLutDescriptorInfo() const {
    VkDescriptorImageInfo info{};
    info.sampler = m_iblSampler;
    info.imageView = m_brdfLutView;
    info.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    return info;
}

// ============================================================================
// Compute Pipeline Implementation
// ============================================================================

VkShaderModule EnvironmentMap::loadShaderModule(const std::string& filename) {
    logToFile("Loading shader: " + filename);
    std::ifstream file(filename, std::ios::ate | std::ios::binary);
    if (!file.is_open()) {
        logToFile("ERROR: Failed to open shader file: " + filename);
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
    createInfo.pCode = reinterpret_cast<const uint32_t*>(buffer.data());

    VkShaderModule shaderModule;
    if (vkCreateShaderModule(m_context.getDevice(), &createInfo, nullptr, &shaderModule) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create shader module: " + filename);
    }

    return shaderModule;
}

void EnvironmentMap::createComputePipelines() {
    if (m_computePipelinesCreated) return;

    auto device = m_context.getDevice();

    // Create descriptor pool for compute shaders
    std::array<VkDescriptorPoolSize, 2> poolSizes{};
    poolSizes[0].type = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    poolSizes[0].descriptorCount = 10;
    poolSizes[1].type = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE;
    poolSizes[1].descriptorCount = 10;

    VkDescriptorPoolCreateInfo poolInfo{};
    poolInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
    poolInfo.poolSizeCount = static_cast<u32>(poolSizes.size());
    poolInfo.pPoolSizes = poolSizes.data();
    poolInfo.maxSets = 10;

    if (vkCreateDescriptorPool(device, &poolInfo, nullptr, &m_computeDescriptorPool) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create compute descriptor pool");
    }

    // ==================== BRDF LUT Pipeline ====================
    {
        // Descriptor set layout: binding 0 = storage image (output)
        VkDescriptorSetLayoutBinding binding{};
        binding.binding = 0;
        binding.descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE;
        binding.descriptorCount = 1;
        binding.stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;

        VkDescriptorSetLayoutCreateInfo layoutInfo{};
        layoutInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
        layoutInfo.bindingCount = 1;
        layoutInfo.pBindings = &binding;

        if (vkCreateDescriptorSetLayout(device, &layoutInfo, nullptr, &m_brdfDescriptorSetLayout) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create BRDF descriptor set layout");
        }

        // Push constant range
        VkPushConstantRange pushConstant{};
        pushConstant.stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
        pushConstant.offset = 0;
        pushConstant.size = sizeof(u32) * 4;  // size, sampleCount, pad, pad

        VkPipelineLayoutCreateInfo pipelineLayoutInfo{};
        pipelineLayoutInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
        pipelineLayoutInfo.setLayoutCount = 1;
        pipelineLayoutInfo.pSetLayouts = &m_brdfDescriptorSetLayout;
        pipelineLayoutInfo.pushConstantRangeCount = 1;
        pipelineLayoutInfo.pPushConstantRanges = &pushConstant;

        if (vkCreatePipelineLayout(device, &pipelineLayoutInfo, nullptr, &m_brdfPipelineLayout) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create BRDF pipeline layout");
        }

        // Create compute pipeline
        VkShaderModule shaderModule = loadShaderModule("shaders/brdf_lut.comp.spv");

        VkPipelineShaderStageCreateInfo stageInfo{};
        stageInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
        stageInfo.stage = VK_SHADER_STAGE_COMPUTE_BIT;
        stageInfo.module = shaderModule;
        stageInfo.pName = "main";

        VkComputePipelineCreateInfo pipelineInfo{};
        pipelineInfo.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO;
        pipelineInfo.stage = stageInfo;
        pipelineInfo.layout = m_brdfPipelineLayout;

        if (vkCreateComputePipelines(device, VK_NULL_HANDLE, 1, &pipelineInfo, nullptr, &m_brdfPipeline) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create BRDF compute pipeline");
        }

        vkDestroyShaderModule(device, shaderModule, nullptr);
    }

    // ==================== Irradiance Pipeline ====================
    {
        // Descriptor set layout: binding 0 = cubemap sampler, binding 1 = storage image
        std::array<VkDescriptorSetLayoutBinding, 2> bindings{};
        bindings[0].binding = 0;
        bindings[0].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        bindings[0].descriptorCount = 1;
        bindings[0].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
        bindings[1].binding = 1;
        bindings[1].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE;
        bindings[1].descriptorCount = 1;
        bindings[1].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;

        VkDescriptorSetLayoutCreateInfo layoutInfo{};
        layoutInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
        layoutInfo.bindingCount = static_cast<u32>(bindings.size());
        layoutInfo.pBindings = bindings.data();

        if (vkCreateDescriptorSetLayout(device, &layoutInfo, nullptr, &m_irradianceDescriptorSetLayout) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create irradiance descriptor set layout");
        }

        VkPushConstantRange pushConstant{};
        pushConstant.stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
        pushConstant.offset = 0;
        pushConstant.size = sizeof(u32) * 4;  // faceSize, sampleCount, pad, pad

        VkPipelineLayoutCreateInfo pipelineLayoutInfo{};
        pipelineLayoutInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
        pipelineLayoutInfo.setLayoutCount = 1;
        pipelineLayoutInfo.pSetLayouts = &m_irradianceDescriptorSetLayout;
        pipelineLayoutInfo.pushConstantRangeCount = 1;
        pipelineLayoutInfo.pPushConstantRanges = &pushConstant;

        if (vkCreatePipelineLayout(device, &pipelineLayoutInfo, nullptr, &m_irradiancePipelineLayout) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create irradiance pipeline layout");
        }

        VkShaderModule shaderModule = loadShaderModule("shaders/irradiance_convolve.comp.spv");

        VkPipelineShaderStageCreateInfo stageInfo{};
        stageInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
        stageInfo.stage = VK_SHADER_STAGE_COMPUTE_BIT;
        stageInfo.module = shaderModule;
        stageInfo.pName = "main";

        VkComputePipelineCreateInfo pipelineInfo{};
        pipelineInfo.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO;
        pipelineInfo.stage = stageInfo;
        pipelineInfo.layout = m_irradiancePipelineLayout;

        if (vkCreateComputePipelines(device, VK_NULL_HANDLE, 1, &pipelineInfo, nullptr, &m_irradiancePipeline) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create irradiance compute pipeline");
        }

        vkDestroyShaderModule(device, shaderModule, nullptr);
    }

    // ==================== Prefilter Pipeline ====================
    {
        // Same layout as irradiance
        std::array<VkDescriptorSetLayoutBinding, 2> bindings{};
        bindings[0].binding = 0;
        bindings[0].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        bindings[0].descriptorCount = 1;
        bindings[0].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
        bindings[1].binding = 1;
        bindings[1].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE;
        bindings[1].descriptorCount = 1;
        bindings[1].stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;

        VkDescriptorSetLayoutCreateInfo layoutInfo{};
        layoutInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO;
        layoutInfo.bindingCount = static_cast<u32>(bindings.size());
        layoutInfo.pBindings = bindings.data();

        if (vkCreateDescriptorSetLayout(device, &layoutInfo, nullptr, &m_prefilterDescriptorSetLayout) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create prefilter descriptor set layout");
        }

        VkPushConstantRange pushConstant{};
        pushConstant.stageFlags = VK_SHADER_STAGE_COMPUTE_BIT;
        pushConstant.offset = 0;
        pushConstant.size = sizeof(float) * 8;  // faceSize, sampleCount, roughness, mipLevel, envMapSize, pad x3

        VkPipelineLayoutCreateInfo pipelineLayoutInfo{};
        pipelineLayoutInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
        pipelineLayoutInfo.setLayoutCount = 1;
        pipelineLayoutInfo.pSetLayouts = &m_prefilterDescriptorSetLayout;
        pipelineLayoutInfo.pushConstantRangeCount = 1;
        pipelineLayoutInfo.pPushConstantRanges = &pushConstant;

        if (vkCreatePipelineLayout(device, &pipelineLayoutInfo, nullptr, &m_prefilterPipelineLayout) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create prefilter pipeline layout");
        }

        VkShaderModule shaderModule = loadShaderModule("shaders/prefilter_envmap.comp.spv");

        VkPipelineShaderStageCreateInfo stageInfo{};
        stageInfo.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
        stageInfo.stage = VK_SHADER_STAGE_COMPUTE_BIT;
        stageInfo.module = shaderModule;
        stageInfo.pName = "main";

        VkComputePipelineCreateInfo pipelineInfo{};
        pipelineInfo.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO;
        pipelineInfo.stage = stageInfo;
        pipelineInfo.layout = m_prefilterPipelineLayout;

        if (vkCreateComputePipelines(device, VK_NULL_HANDLE, 1, &pipelineInfo, nullptr, &m_prefilterPipeline) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create prefilter compute pipeline");
        }

        vkDestroyShaderModule(device, shaderModule, nullptr);
    }

    m_computePipelinesCreated = true;
    std::cout << "[EnvironmentMap] Compute pipelines created" << std::endl;
}

void EnvironmentMap::cleanupComputePipelines() {
    auto device = m_context.getDevice();

    if (m_brdfPipeline) vkDestroyPipeline(device, m_brdfPipeline, nullptr);
    if (m_brdfPipelineLayout) vkDestroyPipelineLayout(device, m_brdfPipelineLayout, nullptr);
    if (m_brdfDescriptorSetLayout) vkDestroyDescriptorSetLayout(device, m_brdfDescriptorSetLayout, nullptr);

    if (m_irradiancePipeline) vkDestroyPipeline(device, m_irradiancePipeline, nullptr);
    if (m_irradiancePipelineLayout) vkDestroyPipelineLayout(device, m_irradiancePipelineLayout, nullptr);
    if (m_irradianceDescriptorSetLayout) vkDestroyDescriptorSetLayout(device, m_irradianceDescriptorSetLayout, nullptr);

    if (m_prefilterPipeline) vkDestroyPipeline(device, m_prefilterPipeline, nullptr);
    if (m_prefilterPipelineLayout) vkDestroyPipelineLayout(device, m_prefilterPipelineLayout, nullptr);
    if (m_prefilterDescriptorSetLayout) vkDestroyDescriptorSetLayout(device, m_prefilterDescriptorSetLayout, nullptr);

    if (m_computeDescriptorPool) vkDestroyDescriptorPool(device, m_computeDescriptorPool, nullptr);

    m_brdfPipeline = VK_NULL_HANDLE;
    m_brdfPipelineLayout = VK_NULL_HANDLE;
    m_brdfDescriptorSetLayout = VK_NULL_HANDLE;
    m_irradiancePipeline = VK_NULL_HANDLE;
    m_irradiancePipelineLayout = VK_NULL_HANDLE;
    m_irradianceDescriptorSetLayout = VK_NULL_HANDLE;
    m_prefilterPipeline = VK_NULL_HANDLE;
    m_prefilterPipelineLayout = VK_NULL_HANDLE;
    m_prefilterDescriptorSetLayout = VK_NULL_HANDLE;
    m_computeDescriptorPool = VK_NULL_HANDLE;

    m_computePipelinesCreated = false;
}

void EnvironmentMap::runBRDFLutCompute(const IBLConfig& config) {
    auto device = m_context.getDevice();

    // Allocate descriptor set
    VkDescriptorSet descriptorSet;
    VkDescriptorSetAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
    allocInfo.descriptorPool = m_computeDescriptorPool;
    allocInfo.descriptorSetCount = 1;
    allocInfo.pSetLayouts = &m_brdfDescriptorSetLayout;

    if (vkAllocateDescriptorSets(device, &allocInfo, &descriptorSet) != VK_SUCCESS) {
        throw std::runtime_error("Failed to allocate BRDF descriptor set");
    }

    // Create storage image view for BRDF LUT
    VkImageView storageView;
    VkImageViewCreateInfo viewInfo{};
    viewInfo.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    viewInfo.image = m_brdfLutImage;
    viewInfo.viewType = VK_IMAGE_VIEW_TYPE_2D;
    viewInfo.format = VK_FORMAT_R16G16_SFLOAT;
    viewInfo.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    viewInfo.subresourceRange.baseMipLevel = 0;
    viewInfo.subresourceRange.levelCount = 1;
    viewInfo.subresourceRange.baseArrayLayer = 0;
    viewInfo.subresourceRange.layerCount = 1;

    if (vkCreateImageView(device, &viewInfo, nullptr, &storageView) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create BRDF storage view");
    }

    // Update descriptor set
    VkDescriptorImageInfo imageInfo{};
    imageInfo.imageView = storageView;
    imageInfo.imageLayout = VK_IMAGE_LAYOUT_GENERAL;

    VkWriteDescriptorSet write{};
    write.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    write.dstSet = descriptorSet;
    write.dstBinding = 0;
    write.dstArrayElement = 0;
    write.descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE;
    write.descriptorCount = 1;
    write.pImageInfo = &imageInfo;

    vkUpdateDescriptorSets(device, 1, &write, 0, nullptr);

    // Record and submit compute commands
    VkCommandBuffer cmd = m_context.beginSingleTimeCommands();

    // Transition image to general layout for compute
    VkImageMemoryBarrier barrier{};
    barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    barrier.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    barrier.newLayout = VK_IMAGE_LAYOUT_GENERAL;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.image = m_brdfLutImage;
    barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    barrier.subresourceRange.baseMipLevel = 0;
    barrier.subresourceRange.levelCount = 1;
    barrier.subresourceRange.baseArrayLayer = 0;
    barrier.subresourceRange.layerCount = 1;
    barrier.srcAccessMask = 0;
    barrier.dstAccessMask = VK_ACCESS_SHADER_WRITE_BIT;

    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &barrier);

    // Bind pipeline and dispatch
    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, m_brdfPipeline);
    vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, m_brdfPipelineLayout, 0, 1, &descriptorSet, 0, nullptr);

    struct {
        u32 size;
        u32 sampleCount;
        float pad1, pad2;
    } pushConstants = { config.brdfLutSize, config.sampleCount, 0, 0 };

    vkCmdPushConstants(cmd, m_brdfPipelineLayout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(pushConstants), &pushConstants);

    u32 groupCount = (config.brdfLutSize + 15) / 16;
    vkCmdDispatch(cmd, groupCount, groupCount, 1);

    // Transition to shader read
    barrier.oldLayout = VK_IMAGE_LAYOUT_GENERAL;
    barrier.newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    barrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;

    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &barrier);

    m_context.endSingleTimeCommands(cmd);

    vkDestroyImageView(device, storageView, nullptr);
    std::cout << "[EnvironmentMap] BRDF LUT generated (" << config.brdfLutSize << "x" << config.brdfLutSize << ")" << std::endl;
}

void EnvironmentMap::runIrradianceCompute(const IBLConfig& config) {
    auto device = m_context.getDevice();

    // Allocate descriptor set
    VkDescriptorSet descriptorSet;
    VkDescriptorSetAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
    allocInfo.descriptorPool = m_computeDescriptorPool;
    allocInfo.descriptorSetCount = 1;
    allocInfo.pSetLayouts = &m_irradianceDescriptorSetLayout;

    if (vkAllocateDescriptorSets(device, &allocInfo, &descriptorSet) != VK_SUCCESS) {
        throw std::runtime_error("Failed to allocate irradiance descriptor set");
    }

    // Create storage image view for irradiance cubemap
    VkImageView storageView;
    VkImageViewCreateInfo viewInfo{};
    viewInfo.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    viewInfo.image = m_irradianceImage;
    viewInfo.viewType = VK_IMAGE_VIEW_TYPE_CUBE;
    viewInfo.format = VK_FORMAT_R16G16B16A16_SFLOAT;
    viewInfo.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    viewInfo.subresourceRange.baseMipLevel = 0;
    viewInfo.subresourceRange.levelCount = 1;
    viewInfo.subresourceRange.baseArrayLayer = 0;
    viewInfo.subresourceRange.layerCount = 6;

    if (vkCreateImageView(device, &viewInfo, nullptr, &storageView) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create irradiance storage view");
    }

    // Update descriptor set
    VkDescriptorImageInfo envMapInfo{};
    envMapInfo.sampler = m_sampler;
    envMapInfo.imageView = m_cubemapView;
    envMapInfo.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

    VkDescriptorImageInfo irradianceInfo{};
    irradianceInfo.imageView = storageView;
    irradianceInfo.imageLayout = VK_IMAGE_LAYOUT_GENERAL;

    std::array<VkWriteDescriptorSet, 2> writes{};
    writes[0].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    writes[0].dstSet = descriptorSet;
    writes[0].dstBinding = 0;
    writes[0].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    writes[0].descriptorCount = 1;
    writes[0].pImageInfo = &envMapInfo;

    writes[1].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    writes[1].dstSet = descriptorSet;
    writes[1].dstBinding = 1;
    writes[1].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE;
    writes[1].descriptorCount = 1;
    writes[1].pImageInfo = &irradianceInfo;

    vkUpdateDescriptorSets(device, static_cast<u32>(writes.size()), writes.data(), 0, nullptr);

    // Record and submit
    VkCommandBuffer cmd = m_context.beginSingleTimeCommands();

    // Transition irradiance to general
    VkImageMemoryBarrier barrier{};
    barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    barrier.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    barrier.newLayout = VK_IMAGE_LAYOUT_GENERAL;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.image = m_irradianceImage;
    barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    barrier.subresourceRange.baseMipLevel = 0;
    barrier.subresourceRange.levelCount = 1;
    barrier.subresourceRange.baseArrayLayer = 0;
    barrier.subresourceRange.layerCount = 6;
    barrier.srcAccessMask = 0;
    barrier.dstAccessMask = VK_ACCESS_SHADER_WRITE_BIT;

    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &barrier);

    vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, m_irradiancePipeline);
    vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, m_irradiancePipelineLayout, 0, 1, &descriptorSet, 0, nullptr);

    struct {
        u32 faceSize;
        u32 sampleCount;
        float pad1, pad2;
    } pushConstants = { config.irradianceSize, config.sampleCount, 0, 0 };

    vkCmdPushConstants(cmd, m_irradiancePipelineLayout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(pushConstants), &pushConstants);

    u32 groupCount = (config.irradianceSize + 15) / 16;
    vkCmdDispatch(cmd, groupCount, groupCount, 1);

    // Transition to shader read
    barrier.oldLayout = VK_IMAGE_LAYOUT_GENERAL;
    barrier.newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    barrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;

    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &barrier);

    m_context.endSingleTimeCommands(cmd);

    vkDestroyImageView(device, storageView, nullptr);
    std::cout << "[EnvironmentMap] Irradiance map generated (" << config.irradianceSize << "x" << config.irradianceSize << " x6)" << std::endl;
}

void EnvironmentMap::runPrefilterCompute(const IBLConfig& config) {
    auto device = m_context.getDevice();

    // Generate each mip level
    for (u32 mip = 0; mip < config.prefilteredMipLevels; mip++) {
        u32 mipSize = config.prefilteredSize >> mip;
        float roughness = static_cast<float>(mip) / static_cast<float>(config.prefilteredMipLevels - 1);

        // Allocate descriptor set
        VkDescriptorSet descriptorSet;
        VkDescriptorSetAllocateInfo allocInfo{};
        allocInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO;
        allocInfo.descriptorPool = m_computeDescriptorPool;
        allocInfo.descriptorSetCount = 1;
        allocInfo.pSetLayouts = &m_prefilterDescriptorSetLayout;

        if (vkAllocateDescriptorSets(device, &allocInfo, &descriptorSet) != VK_SUCCESS) {
            throw std::runtime_error("Failed to allocate prefilter descriptor set");
        }

        // Create storage image view for this mip level
        VkImageView storageView;
        VkImageViewCreateInfo viewInfo{};
        viewInfo.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
        viewInfo.image = m_prefilteredImage;
        viewInfo.viewType = VK_IMAGE_VIEW_TYPE_CUBE;
        viewInfo.format = VK_FORMAT_R16G16B16A16_SFLOAT;
        viewInfo.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        viewInfo.subresourceRange.baseMipLevel = mip;
        viewInfo.subresourceRange.levelCount = 1;
        viewInfo.subresourceRange.baseArrayLayer = 0;
        viewInfo.subresourceRange.layerCount = 6;

        if (vkCreateImageView(device, &viewInfo, nullptr, &storageView) != VK_SUCCESS) {
            throw std::runtime_error("Failed to create prefilter storage view");
        }

        // Update descriptor set
        VkDescriptorImageInfo envMapInfo{};
        envMapInfo.sampler = m_sampler;
        envMapInfo.imageView = m_cubemapView;
        envMapInfo.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

        VkDescriptorImageInfo prefilteredInfo{};
        prefilteredInfo.imageView = storageView;
        prefilteredInfo.imageLayout = VK_IMAGE_LAYOUT_GENERAL;

        std::array<VkWriteDescriptorSet, 2> writes{};
        writes[0].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        writes[0].dstSet = descriptorSet;
        writes[0].dstBinding = 0;
        writes[0].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
        writes[0].descriptorCount = 1;
        writes[0].pImageInfo = &envMapInfo;

        writes[1].sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
        writes[1].dstSet = descriptorSet;
        writes[1].dstBinding = 1;
        writes[1].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE;
        writes[1].descriptorCount = 1;
        writes[1].pImageInfo = &prefilteredInfo;

        vkUpdateDescriptorSets(device, static_cast<u32>(writes.size()), writes.data(), 0, nullptr);

        // Record and submit
        VkCommandBuffer cmd = m_context.beginSingleTimeCommands();

        // Transition this mip to general
        VkImageMemoryBarrier barrier{};
        barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
        barrier.oldLayout = mip == 0 ? VK_IMAGE_LAYOUT_UNDEFINED : VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
        barrier.newLayout = VK_IMAGE_LAYOUT_GENERAL;
        barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        barrier.image = m_prefilteredImage;
        barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        barrier.subresourceRange.baseMipLevel = mip;
        barrier.subresourceRange.levelCount = 1;
        barrier.subresourceRange.baseArrayLayer = 0;
        barrier.subresourceRange.layerCount = 6;
        barrier.srcAccessMask = 0;
        barrier.dstAccessMask = VK_ACCESS_SHADER_WRITE_BIT;

        vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
                             0, 0, nullptr, 0, nullptr, 1, &barrier);

        vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, m_prefilterPipeline);
        vkCmdBindDescriptorSets(cmd, VK_PIPELINE_BIND_POINT_COMPUTE, m_prefilterPipelineLayout, 0, 1, &descriptorSet, 0, nullptr);

        struct {
            u32 faceSize;
            u32 sampleCount;
            float roughness;
            u32 mipLevel;
            float envMapSize;
            float pad1, pad2, pad3;
        } pushConstants = {
            mipSize, config.sampleCount, roughness, mip,
            static_cast<float>(m_cubemapSize), 0, 0, 0
        };

        vkCmdPushConstants(cmd, m_prefilterPipelineLayout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(pushConstants), &pushConstants);

        u32 groupCount = (mipSize + 15) / 16;
        vkCmdDispatch(cmd, groupCount, groupCount, 1);

        // Transition to shader read
        barrier.oldLayout = VK_IMAGE_LAYOUT_GENERAL;
        barrier.newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
        barrier.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
        barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;

        vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
                             0, 0, nullptr, 0, nullptr, 1, &barrier);

        m_context.endSingleTimeCommands(cmd);

        vkDestroyImageView(device, storageView, nullptr);
    }

    std::cout << "[EnvironmentMap] Prefiltered map generated (" << config.prefilteredSize << "x" << config.prefilteredSize
              << " x6, " << config.prefilteredMipLevels << " mips)" << std::endl;
}

} // namespace arch
