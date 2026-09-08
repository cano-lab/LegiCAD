#include "texture.hpp"
#include <stdexcept>
#include <iostream>
#include <filesystem>
#include <fstream>
#include <cstring>

#include "stb_image.h"
#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace arch {

// Static default textures
std::unique_ptr<Texture> Texture::s_white;
std::unique_ptr<Texture> Texture::s_black;
std::unique_ptr<Texture> Texture::s_grey;
std::unique_ptr<Texture> Texture::s_normalDefault;

// Static black cubemap for IBL fallback
VkImage Texture::s_blackCubeImage = VK_NULL_HANDLE;
VkDeviceMemory Texture::s_blackCubeMemory = VK_NULL_HANDLE;
VkImageView Texture::s_blackCubeImageView = VK_NULL_HANDLE;
VkSampler Texture::s_blackCubeSampler = VK_NULL_HANDLE;

Texture::Texture(VulkanContext& context)
    : m_context(context) {
}

Texture::~Texture() {
    if (m_sampler != VK_NULL_HANDLE) {
        vkDestroySampler(m_context.getDevice(), m_sampler, nullptr);
    }
    if (m_imageView != VK_NULL_HANDLE) {
        vkDestroyImageView(m_context.getDevice(), m_imageView, nullptr);
    }
    if (m_image != VK_NULL_HANDLE) {
        vkDestroyImage(m_context.getDevice(), m_image, nullptr);
    }
    if (m_memory != VK_NULL_HANDLE) {
        vkFreeMemory(m_context.getDevice(), m_memory, nullptr);
    }
}

bool Texture::loadFromFile(const std::string& filepath, bool sRGB) {
    int width, height, channels;
    stbi_uc* pixels = stbi_load(filepath.c_str(), &width, &height, &channels, STBI_rgb_alpha);

    if (!pixels) {
        std::cerr << "[Texture] Failed to load: " << filepath << " - " << stbi_failure_reason() << std::endl;
        return false;
    }

    VkFormat format = sRGB ? VK_FORMAT_R8G8B8A8_SRGB : VK_FORMAT_R8G8B8A8_UNORM;
    createImage(pixels, width, height, format);

    stbi_image_free(pixels);

    m_width = width;
    m_height = height;
    m_loaded = true;

    std::cout << "[Texture] Loaded: " << filepath << " (" << width << "x" << height << ")" << std::endl;
    return true;
}

void Texture::createSolidColor(vec4 color, bool sRGB) {
    u8 pixels[4] = {
        static_cast<u8>(color.r * 255.0f),
        static_cast<u8>(color.g * 255.0f),
        static_cast<u8>(color.b * 255.0f),
        static_cast<u8>(color.a * 255.0f)
    };

    VkFormat format = sRGB ? VK_FORMAT_R8G8B8A8_SRGB : VK_FORMAT_R8G8B8A8_UNORM;
    createImage(pixels, 1, 1, format);

    m_width = 1;
    m_height = 1;
    m_loaded = true;
}

void Texture::createImage(const void* pixels, u32 width, u32 height, VkFormat format) {
    VkDeviceSize imageSize = width * height * 4;

    // Create staging buffer
    VkBuffer stagingBuffer;
    VkDeviceMemory stagingMemory;
    m_context.createBuffer(imageSize, VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
                           VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
                           stagingBuffer, stagingMemory);

    // Copy pixel data to staging buffer
    void* data;
    vkMapMemory(m_context.getDevice(), stagingMemory, 0, imageSize, 0, &data);
    memcpy(data, pixels, imageSize);
    vkUnmapMemory(m_context.getDevice(), stagingMemory);

    // Create image
    m_context.createImage(width, height, format, VK_IMAGE_TILING_OPTIMAL,
                          VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
                          VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
                          m_image, m_memory);

    // Transition to transfer destination
    m_context.transitionImageLayout(m_image, format,
                                    VK_IMAGE_LAYOUT_UNDEFINED,
                                    VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL);

    // Copy buffer to image
    m_context.copyBufferToImage(stagingBuffer, m_image, width, height);

    // Transition to shader read
    m_context.transitionImageLayout(m_image, format,
                                    VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                                    VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);

    // Cleanup staging buffer
    vkDestroyBuffer(m_context.getDevice(), stagingBuffer, nullptr);
    vkFreeMemory(m_context.getDevice(), stagingMemory, nullptr);

    // Create image view
    m_imageView = m_context.createImageView(m_image, format, VK_IMAGE_ASPECT_COLOR_BIT);

    // Create sampler
    createSampler();
}

void Texture::createSampler() {
    VkSamplerCreateInfo samplerInfo{};
    samplerInfo.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
    samplerInfo.magFilter = VK_FILTER_LINEAR;
    samplerInfo.minFilter = VK_FILTER_LINEAR;
    samplerInfo.addressModeU = VK_SAMPLER_ADDRESS_MODE_REPEAT;
    samplerInfo.addressModeV = VK_SAMPLER_ADDRESS_MODE_REPEAT;
    samplerInfo.addressModeW = VK_SAMPLER_ADDRESS_MODE_REPEAT;
    if (m_context.supportsSamplerAnisotropy()) {
        samplerInfo.anisotropyEnable = VK_TRUE;
        samplerInfo.maxAnisotropy = m_context.getMaxSamplerAnisotropy();
    } else {
        samplerInfo.anisotropyEnable = VK_FALSE;
        samplerInfo.maxAnisotropy = 1.0f;
    }
    samplerInfo.borderColor = VK_BORDER_COLOR_INT_OPAQUE_BLACK;
    samplerInfo.unnormalizedCoordinates = VK_FALSE;
    samplerInfo.compareEnable = VK_FALSE;
    samplerInfo.mipmapMode = VK_SAMPLER_MIPMAP_MODE_LINEAR;
    samplerInfo.mipLodBias = 0.0f;
    samplerInfo.minLod = 0.0f;
    samplerInfo.maxLod = 0.0f;

    if (vkCreateSampler(m_context.getDevice(), &samplerInfo, nullptr, &m_sampler) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create texture sampler");
    }
}

void Texture::createDefaultTextures(VulkanContext& context) {
    // White texture (default albedo)
    s_white = std::make_unique<Texture>(context);
    s_white->createSolidColor(vec4(1.0f, 1.0f, 1.0f, 1.0f), true);

    // Black texture (default metallic/emission)
    s_black = std::make_unique<Texture>(context);
    s_black->createSolidColor(vec4(0.0f, 0.0f, 0.0f, 1.0f), false);

    // Grey texture (0.5 - default height map, means no displacement)
    s_grey = std::make_unique<Texture>(context);
    s_grey->createSolidColor(vec4(0.5f, 0.5f, 0.5f, 1.0f), false);

    // Default normal map (flat surface pointing up in tangent space)
    s_normalDefault = std::make_unique<Texture>(context);
    s_normalDefault->createSolidColor(vec4(0.5f, 0.5f, 1.0f, 1.0f), false);

    // Create default black cubemap for IBL fallback
    createBlackCubemap(context);

    std::cout << "[Texture] Created default textures" << std::endl;
}

Texture* Texture::getWhite() { return s_white.get(); }
Texture* Texture::getBlack() { return s_black.get(); }
Texture* Texture::getGrey() { return s_grey.get(); }
Texture* Texture::getNormalDefault() { return s_normalDefault.get(); }

VkImage Texture::getBlackCubeImage() { return s_blackCubeImage; }
VkImageView Texture::getBlackCubeImageView() { return s_blackCubeImageView; }
VkSampler Texture::getBlackCubeSampler() { return s_blackCubeSampler; }

void Texture::createBlackCubemap(VulkanContext& context) {
    // Create a 1x1 black cubemap for IBL fallback when no environment map is loaded
    const u32 size = 1;
    const u32 layers = 6;  // Cubemap faces
    VkFormat format = VK_FORMAT_R8G8B8A8_UNORM;

    // Create cubemap image
    VkImageCreateInfo imageInfo{};
    imageInfo.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    imageInfo.imageType = VK_IMAGE_TYPE_2D;
    imageInfo.extent.width = size;
    imageInfo.extent.height = size;
    imageInfo.extent.depth = 1;
    imageInfo.mipLevels = 1;
    imageInfo.arrayLayers = layers;
    imageInfo.format = format;
    imageInfo.tiling = VK_IMAGE_TILING_OPTIMAL;
    imageInfo.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    imageInfo.usage = VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_SAMPLED_BIT;
    imageInfo.samples = VK_SAMPLE_COUNT_1_BIT;
    imageInfo.flags = VK_IMAGE_CREATE_CUBE_COMPATIBLE_BIT;

    if (vkCreateImage(context.getDevice(), &imageInfo, nullptr, &s_blackCubeImage) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create black cubemap image");
    }

    // Allocate memory
    VkMemoryRequirements memReqs;
    vkGetImageMemoryRequirements(context.getDevice(), s_blackCubeImage, &memReqs);

    VkMemoryAllocateInfo allocInfo{};
    allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocInfo.allocationSize = memReqs.size;
    allocInfo.memoryTypeIndex = context.findMemoryType(memReqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);

    if (vkAllocateMemory(context.getDevice(), &allocInfo, nullptr, &s_blackCubeMemory) != VK_SUCCESS) {
        throw std::runtime_error("Failed to allocate black cubemap memory");
    }

    vkBindImageMemory(context.getDevice(), s_blackCubeImage, s_blackCubeMemory, 0);

    // Create staging buffer with black pixels (all zeros)
    VkDeviceSize imageSize = size * size * 4 * layers;
    VkBuffer stagingBuffer;
    VkDeviceMemory stagingMemory;
    context.createBuffer(imageSize, VK_BUFFER_USAGE_TRANSFER_SRC_BIT,
                         VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT,
                         stagingBuffer, stagingMemory);

    void* data;
    vkMapMemory(context.getDevice(), stagingMemory, 0, imageSize, 0, &data);
    memset(data, 0, imageSize);  // Black pixels
    vkUnmapMemory(context.getDevice(), stagingMemory);

    // Transition to transfer destination
    VkCommandBuffer cmd = context.beginSingleTimeCommands();

    VkImageMemoryBarrier barrier{};
    barrier.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    barrier.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    barrier.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    barrier.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    barrier.image = s_blackCubeImage;
    barrier.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    barrier.subresourceRange.baseMipLevel = 0;
    barrier.subresourceRange.levelCount = 1;
    barrier.subresourceRange.baseArrayLayer = 0;
    barrier.subresourceRange.layerCount = layers;
    barrier.srcAccessMask = 0;
    barrier.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;

    vkCmdPipelineBarrier(cmd,
        VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
        0, 0, nullptr, 0, nullptr, 1, &barrier);

    // Copy buffer to all cubemap faces
    std::array<VkBufferImageCopy, 6> regions{};
    for (u32 face = 0; face < layers; face++) {
        regions[face].bufferOffset = face * size * size * 4;
        regions[face].bufferRowLength = 0;
        regions[face].bufferImageHeight = 0;
        regions[face].imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        regions[face].imageSubresource.mipLevel = 0;
        regions[face].imageSubresource.baseArrayLayer = face;
        regions[face].imageSubresource.layerCount = 1;
        regions[face].imageOffset = {0, 0, 0};
        regions[face].imageExtent = {size, size, 1};
    }

    vkCmdCopyBufferToImage(cmd, stagingBuffer, s_blackCubeImage,
                           VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                           static_cast<u32>(regions.size()), regions.data());

    // Transition to shader read
    barrier.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    barrier.newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
    barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;

    vkCmdPipelineBarrier(cmd,
        VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
        0, 0, nullptr, 0, nullptr, 1, &barrier);

    context.endSingleTimeCommands(cmd);

    // Cleanup staging buffer
    vkDestroyBuffer(context.getDevice(), stagingBuffer, nullptr);
    vkFreeMemory(context.getDevice(), stagingMemory, nullptr);

    // Create cubemap image view
    VkImageViewCreateInfo viewInfo{};
    viewInfo.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    viewInfo.image = s_blackCubeImage;
    viewInfo.viewType = VK_IMAGE_VIEW_TYPE_CUBE;
    viewInfo.format = format;
    viewInfo.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    viewInfo.subresourceRange.baseMipLevel = 0;
    viewInfo.subresourceRange.levelCount = 1;
    viewInfo.subresourceRange.baseArrayLayer = 0;
    viewInfo.subresourceRange.layerCount = layers;

    if (vkCreateImageView(context.getDevice(), &viewInfo, nullptr, &s_blackCubeImageView) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create black cubemap image view");
    }

    // Create sampler
    VkSamplerCreateInfo samplerInfo{};
    samplerInfo.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
    samplerInfo.magFilter = VK_FILTER_LINEAR;
    samplerInfo.minFilter = VK_FILTER_LINEAR;
    samplerInfo.addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
    samplerInfo.anisotropyEnable = VK_FALSE;
    samplerInfo.maxAnisotropy = 1.0f;
    samplerInfo.borderColor = VK_BORDER_COLOR_INT_OPAQUE_BLACK;
    samplerInfo.unnormalizedCoordinates = VK_FALSE;
    samplerInfo.compareEnable = VK_FALSE;
    samplerInfo.mipmapMode = VK_SAMPLER_MIPMAP_MODE_LINEAR;
    samplerInfo.mipLodBias = 0.0f;
    samplerInfo.minLod = 0.0f;
    samplerInfo.maxLod = 0.0f;

    if (vkCreateSampler(context.getDevice(), &samplerInfo, nullptr, &s_blackCubeSampler) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create black cubemap sampler");
    }

    std::cout << "[Texture] Created black cubemap for IBL fallback" << std::endl;
}

// ============================================================================
// MaterialLibrary
// ============================================================================

MaterialLibrary::MaterialLibrary(VulkanContext& context)
    : m_context(context) {
    // Initialize default textures if not already done
    if (!Texture::getWhite()) {
        Texture::createDefaultTextures(context);
    }

    // Setup default material
    m_defaultMaterial.name = "default";
    m_defaultMaterial.albedoMap = Texture::getWhite();
    m_defaultMaterial.normalMap = Texture::getNormalDefault();
    m_defaultMaterial.roughnessMap = Texture::getWhite();  // White = rough
    m_defaultMaterial.metallicMap = Texture::getBlack();   // Black = non-metallic
    m_defaultMaterial.aoMap = Texture::getWhite();         // White = no occlusion
    m_defaultMaterial.emissiveMap = Texture::getBlack();
    m_defaultMaterial.opacityMap = Texture::getWhite();
    m_defaultMaterial.heightMap = Texture::getGrey();  // Grey = 0.5 = no displacement
    m_defaultMaterial.albedoColor = vec3(0.8f);
    m_defaultMaterial.roughness = 0.5f;
    m_defaultMaterial.metallic = 0.0f;
}

MaterialLibrary::~MaterialLibrary() {
    m_materials.clear();
    m_textures.clear();
}

Material* MaterialLibrary::loadMaterial(const std::string& name, const std::string& directory) {
    auto mat = std::make_unique<Material>();
    mat->name = name;

    namespace fs = std::filesystem;

    // Try to load each texture type
    auto tryLoad = [&](const std::string& suffix, bool sRGB) -> Texture* {
        for (const auto& ext : {".png", ".jpg", ".jpeg", ".tga"}) {
            std::string path = directory + "/" + suffix + ext;
            if (fs::exists(path)) {
                auto tex = std::make_unique<Texture>(m_context);
                if (tex->loadFromFile(path, sRGB)) {
                    auto* ptr = tex.get();
                    m_textures[name + "_" + suffix] = std::move(tex);
                    return ptr;
                }
            }
        }
        return nullptr;
    };

    mat->albedoMap = tryLoad("albedo", true);
    if (!mat->albedoMap) mat->albedoMap = tryLoad("diffuse", true);
    if (!mat->albedoMap) mat->albedoMap = tryLoad("basecolor", true);
    if (!mat->albedoMap) mat->albedoMap = Texture::getWhite();

    mat->normalMap = tryLoad("normal", false);
    if (!mat->normalMap) mat->normalMap = Texture::getNormalDefault();

    mat->roughnessMap = tryLoad("roughness", false);
    if (!mat->roughnessMap) mat->roughnessMap = Texture::getWhite();

    mat->metallicMap = tryLoad("metallic", false);
    if (!mat->metallicMap) mat->metallicMap = tryLoad("metalness", false);
    if (!mat->metallicMap) mat->metallicMap = Texture::getBlack();

    mat->aoMap = tryLoad("ao", false);
    if (!mat->aoMap) mat->aoMap = tryLoad("ambient_occlusion", false);
    if (!mat->aoMap) mat->aoMap = Texture::getWhite();

    mat->emissiveMap = tryLoad("emissive", true);
    if (!mat->emissiveMap) mat->emissiveMap = tryLoad("emission", true);
    if (!mat->emissiveMap) mat->emissiveMap = tryLoad("emit", true);
    if (!mat->emissiveMap) mat->emissiveMap = Texture::getBlack();

    mat->opacityMap = tryLoad("opacity", false);
    if (!mat->opacityMap) mat->opacityMap = tryLoad("alpha", false);
    if (!mat->opacityMap) mat->opacityMap = Texture::getWhite();

    // Height/displacement map (linear grayscale)
    mat->heightMap = tryLoad("height", false);
    if (!mat->heightMap) mat->heightMap = tryLoad("displacement", false);
    if (!mat->heightMap) mat->heightMap = tryLoad("bump", false);
    bool hasHeightMap = (mat->heightMap != nullptr);

    // DEBUG: Print height map loading status
    std::cout << "[MaterialLibrary] Height map for " << name << ": "
              << (hasHeightMap ? "LOADED" : "NOT FOUND")
              << " (searched in: " << directory << "/height.png)" << std::endl;

    if (!mat->heightMap) mat->heightMap = Texture::getGrey();   // Grey (0.5) = no displacement

    auto* ptr = mat.get();
    m_materials[name] = std::move(mat);

    std::cout << "[MaterialLibrary] Loaded material: " << name
              << (hasHeightMap ? " [HAS HEIGHT MAP]" : " [no height map]") << std::endl;
    return ptr;
}

u32 MaterialLibrary::loadMaterialsFromDirectory(const std::string& rootDirectory) {
    namespace fs = std::filesystem;

    if (!fs::exists(rootDirectory) || !fs::is_directory(rootDirectory)) {
        std::cout << "[MaterialLibrary] Materials directory not found: " << rootDirectory << std::endl;
        return 0;
    }

    u32 loaded = 0;

    // Helper to check if a directory contains texture files (is a material folder)
    auto isMaterialFolder = [](const fs::path& dir) -> bool {
        for (const auto& ext : {".png", ".jpg", ".jpeg", ".tga"}) {
            if (fs::exists(dir / ("albedo" + std::string(ext))) ||
                fs::exists(dir / ("diffuse" + std::string(ext))) ||
                fs::exists(dir / ("basecolor" + std::string(ext)))) {
                return true;
            }
        }
        return false;
    };

    // Scan root directory
    for (const auto& entry : fs::directory_iterator(rootDirectory)) {
        if (!entry.is_directory()) continue;

        std::string name = entry.path().filename().string();

        // Check if this is a material folder (has texture files)
        if (isMaterialFolder(entry.path())) {
            if (m_materials.find(name) == m_materials.end()) {
                if (loadMaterial(name, entry.path().string())) {
                    loaded++;
                }
            }
        } else {
            // This might be a category folder (like "polyhaven/") - scan its contents
            for (const auto& subEntry : fs::directory_iterator(entry.path())) {
                if (!subEntry.is_directory()) continue;

                if (isMaterialFolder(subEntry.path())) {
                    // Use "category/material" naming (e.g., "polyhaven/brick_wall_006")
                    std::string subName = name + "/" + subEntry.path().filename().string();
                    if (m_materials.find(subName) == m_materials.end()) {
                        if (loadMaterial(subName, subEntry.path().string())) {
                            loaded++;
                        }
                    }
                }
            }
        }
    }

    if (loaded > 0) {
        std::cout << "[MaterialLibrary] Loaded " << loaded << " materials from " << rootDirectory << std::endl;
    }

    return loaded;
}

Material* MaterialLibrary::createSolidMaterial(const std::string& name, vec3 albedo, f32 roughness, f32 metallic) {
    auto mat = std::make_unique<Material>();
    mat->name = name;
    mat->albedoColor = albedo;
    mat->roughness = roughness;
    mat->metallic = metallic;

    // Create solid color albedo texture
    auto tex = std::make_unique<Texture>(m_context);
    tex->createSolidColor(vec4(albedo, 1.0f), true);
    mat->albedoMap = tex.get();
    m_textures[name + "_albedo"] = std::move(tex);

    mat->normalMap = Texture::getNormalDefault();
    mat->roughnessMap = Texture::getWhite();
    mat->metallicMap = Texture::getBlack();
    mat->aoMap = Texture::getWhite();
    mat->emissiveMap = Texture::getBlack();
    mat->opacityMap = Texture::getWhite();
    mat->heightMap = Texture::getGrey();  // Grey (0.5) = no displacement

    auto* ptr = mat.get();
    m_materials[name] = std::move(mat);
    return ptr;
}

Material* MaterialLibrary::getMaterial(const std::string& name) {
    // First check direct material
    auto it = m_materials.find(name);
    if (it != m_materials.end()) {
        return it->second.get();
    }

    // Check aliases
    auto aliasIt = m_materialAliases.find(name);
    if (aliasIt != m_materialAliases.end()) {
        it = m_materials.find(aliasIt->second);
        if (it != m_materials.end()) {
            return it->second.get();
        }
    }

    return &m_defaultMaterial;
}

void MaterialLibrary::createBuiltinMaterials() {
    // Only create glass as solid material (transparent, doesn't need texture)
    createSolidMaterial("glass", vec3(0.9f, 0.95f, 1.0f), 0.05f, 0.0f);

    std::cout << "[MaterialLibrary] Created " << m_materials.size() << " builtin materials" << std::endl;
}

void MaterialLibrary::createMaterialAliases() {
    // Create aliases so generic names map to Poly Haven materials
    // This allows code using "concrete" to get "polyhaven/concrete_wall_008"
    m_materialAliases["concrete"] = "polyhaven/concrete_wall_008";
    m_materialAliases["brick"] = "polyhaven/brick_wall_006";
    m_materialAliases["wood"] = "polyhaven/wood_floor_deck";
    m_materialAliases["drywall"] = "polyhaven/concrete_wall_008";
    m_materialAliases["metal"] = "polyhaven/metal_plate_02";
    m_materialAliases["tile"] = "polyhaven/concrete_floor_003";
    m_materialAliases["shingle"] = "polyhaven/roof_slates_02";
    m_materialAliases["asphalt"] = "polyhaven/asphalt_04";
    m_materialAliases["grass"] = "polyhaven/grass_path_2";
    m_materialAliases["gravel"] = "polyhaven/gravel_concrete";

    std::cout << "[MaterialLibrary] Created " << m_materialAliases.size() << " material aliases" << std::endl;
}

void MaterialLibrary::loadMaterialSettings(const std::string& settingsPath) {
    namespace fs = std::filesystem;
    if (!fs::exists(settingsPath)) return;

    try {
        std::ifstream file(settingsPath);
        json data = json::parse(file);

        if (!data.contains("materials")) return;

        for (auto& [name, settings] : data["materials"].items()) {
            auto it = m_materials.find(name);
            if (it == m_materials.end()) continue;

            Material* mat = it->second.get();

            if (settings.contains("uvScale")) {
                auto& uv = settings["uvScale"];
                if (uv.is_array() && uv.size() >= 2) {
                    mat->uvScale = vec2(uv[0].get<float>(), uv[1].get<float>());
                } else if (uv.is_number()) {
                    float s = uv.get<float>();
                    mat->uvScale = vec2(s, s);
                }
            }
            if (settings.contains("brightness"))
                mat->brightness = settings["brightness"].get<float>();
            if (settings.contains("contrast"))
                mat->contrast = settings["contrast"].get<float>();
            if (settings.contains("saturation"))
                mat->saturation = settings["saturation"].get<float>();
            if (settings.contains("normalStrength"))
                mat->normalStrength = settings["normalStrength"].get<float>();
            if (settings.contains("roughnessOffset"))
                mat->roughnessOffset = settings["roughnessOffset"].get<float>();
            if (settings.contains("metallicOffset"))
                mat->metallicOffset = settings["metallicOffset"].get<float>();
            if (settings.contains("aoStrength"))
                mat->aoStrength = settings["aoStrength"].get<float>();
            if (settings.contains("tint")) {
                auto& t = settings["tint"];
                if (t.is_array() && t.size() >= 3) {
                    mat->tint = vec3(t[0].get<float>(), t[1].get<float>(), t[2].get<float>());
                }
            }
        }
        std::cout << "[MaterialLibrary] Loaded material settings from " << settingsPath << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "[MaterialLibrary] Error loading settings: " << e.what() << std::endl;
    }
}

void MaterialLibrary::saveMaterialSettings(const std::string& settingsPath) {
    json data;
    data["materials"] = json::object();

    for (const auto& [name, mat] : m_materials) {
        json settings;
        settings["uvScale"] = {mat->uvScale.x, mat->uvScale.y};
        settings["brightness"] = mat->brightness;
        settings["contrast"] = mat->contrast;
        settings["saturation"] = mat->saturation;
        settings["normalStrength"] = mat->normalStrength;
        settings["roughnessOffset"] = mat->roughnessOffset;
        settings["metallicOffset"] = mat->metallicOffset;
        settings["aoStrength"] = mat->aoStrength;
        settings["tint"] = {mat->tint.r, mat->tint.g, mat->tint.b};
        data["materials"][name] = settings;
    }

    try {
        std::ofstream file(settingsPath);
        file << data.dump(2);
        std::cout << "[MaterialLibrary] Saved material settings to " << settingsPath << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "[MaterialLibrary] Error saving settings: " << e.what() << std::endl;
    }
}

void MaterialLibrary::saveMaterialSettings(Material* material, const std::string& settingsPath) {
    namespace fs = std::filesystem;
    json data;

    // Load existing settings if file exists
    if (fs::exists(settingsPath)) {
        try {
            std::ifstream file(settingsPath);
            data = json::parse(file);
        } catch (...) {
            data = json::object();
        }
    }

    if (!data.contains("materials")) {
        data["materials"] = json::object();
    }

    json settings;
    settings["uvScale"] = {material->uvScale.x, material->uvScale.y};
    settings["brightness"] = material->brightness;
    settings["contrast"] = material->contrast;
    settings["saturation"] = material->saturation;
    settings["normalStrength"] = material->normalStrength;
    settings["roughnessOffset"] = material->roughnessOffset;
    settings["metallicOffset"] = material->metallicOffset;
    settings["aoStrength"] = material->aoStrength;
    settings["tint"] = {material->tint.r, material->tint.g, material->tint.b};
    data["materials"][material->name] = settings;

    try {
        std::ofstream file(settingsPath);
        file << data.dump(2);
    } catch (const std::exception& e) {
        std::cerr << "[MaterialLibrary] Error saving material: " << e.what() << std::endl;
    }
}

} // namespace arch
