#pragma once

#include "types.hpp"
#include "vulkan_context.hpp"
#include <string>
#include <unordered_map>
#include <memory>

namespace arch {

// Single texture (albedo, normal, roughness, etc.)
class Texture {
public:
    Texture(VulkanContext& context);
    ~Texture();

    // Non-copyable
    Texture(const Texture&) = delete;
    Texture& operator=(const Texture&) = delete;

    // Load from file (supports PNG, JPG, HDR via stb_image)
    bool loadFromFile(const std::string& filepath, bool sRGB = true);

    // Create solid color texture (1x1 pixel)
    void createSolidColor(vec4 color, bool sRGB = true);

    // Create default textures (white, normal, black, grey)
    static void createDefaultTextures(VulkanContext& context);
    static Texture* getWhite();
    static Texture* getBlack();
    static Texture* getGrey();           // Mid-grey (0.5) for height maps - no displacement
    static Texture* getNormalDefault();  // Flat normal (0.5, 0.5, 1.0)

    // Default cubemap for IBL fallback (1x1 black cubemap)
    static VkImage getBlackCubeImage();
    static VkImageView getBlackCubeImageView();
    static VkSampler getBlackCubeSampler();

    VkImageView getImageView() const { return m_imageView; }
    VkSampler getSampler() const { return m_sampler; }

    u32 getWidth() const { return m_width; }
    u32 getHeight() const { return m_height; }
    bool isLoaded() const { return m_loaded; }

private:
    void createImage(const void* pixels, u32 width, u32 height, VkFormat format);
    void createSampler();

    VulkanContext& m_context;

    VkImage m_image = VK_NULL_HANDLE;
    VkDeviceMemory m_memory = VK_NULL_HANDLE;
    VkImageView m_imageView = VK_NULL_HANDLE;
    VkSampler m_sampler = VK_NULL_HANDLE;

    u32 m_width = 0;
    u32 m_height = 0;
    bool m_loaded = false;

    // Static default textures
    static std::unique_ptr<Texture> s_white;
    static std::unique_ptr<Texture> s_black;
    static std::unique_ptr<Texture> s_grey;
    static std::unique_ptr<Texture> s_normalDefault;

    // Static black cubemap for IBL fallback
    static VkImage s_blackCubeImage;
    static VkDeviceMemory s_blackCubeMemory;
    static VkImageView s_blackCubeImageView;
    static VkSampler s_blackCubeSampler;
    static void createBlackCubemap(VulkanContext& context);
};

// PBR Material definition
struct Material {
    std::string name;

    // Texture maps (nullptr means use default)
    Texture* albedoMap = nullptr;      // Base color (sRGB)
    Texture* normalMap = nullptr;      // Normal map (linear)
    Texture* roughnessMap = nullptr;   // Roughness (linear, grayscale)
    Texture* metallicMap = nullptr;    // Metallic (linear, grayscale)
    Texture* aoMap = nullptr;          // Ambient occlusion (linear, grayscale)
    Texture* emissiveMap = nullptr;    // Emissive (sRGB)
    Texture* opacityMap = nullptr;     // Opacity (linear, grayscale)
    Texture* heightMap = nullptr;      // Height/displacement map (linear, grayscale)

    // Fallback values when no texture
    vec3 albedoColor = vec3(0.8f);
    f32 roughness = 0.5f;
    f32 metallic = 0.0f;
    f32 ao = 1.0f;
    f32 opacity = 1.0f;

    // Texture tiling
    vec2 uvScale = vec2(1.0f);

    // Per-material adjustments (post-processing)
    f32 brightness = 0.0f;       // -1 to 1, added to albedo
    f32 contrast = 1.0f;         // 0 to 2, multiplied
    f32 saturation = 1.0f;       // 0 to 2, color saturation
    f32 normalStrength = 1.0f;   // 0 to 2, normal map intensity
    f32 roughnessOffset = 0.0f;  // -0.5 to 0.5, added to roughness
    f32 metallicOffset = 0.0f;   // -0.5 to 0.5, added to metallic
    f32 aoStrength = 1.0f;       // 0 to 2, AO multiplier
    vec3 tint = vec3(1.0f);      // Color tint multiplier
};

// Material library - manages loaded materials
class MaterialLibrary {
public:
    MaterialLibrary(VulkanContext& context);
    ~MaterialLibrary();

    // Load material from directory (expects albedo.png, normal.png, roughness.png, etc.)
    Material* loadMaterial(const std::string& name, const std::string& directory);

    // Load materials from subdirectories under a root directory.
    // Each subdirectory name becomes a material name.
    u32 loadMaterialsFromDirectory(const std::string& rootDirectory);

    const std::unordered_map<std::string, std::unique_ptr<Material>>& getMaterials() const {
        return m_materials;
    }
    bool hasMaterial(const std::string& name) const {
        if (m_materials.find(name) != m_materials.end()) return true;
        // Check aliases
        auto aliasIt = m_materialAliases.find(name);
        if (aliasIt != m_materialAliases.end()) {
            return m_materials.find(aliasIt->second) != m_materials.end();
        }
        return false;
    }

    // Create material with solid colors
    Material* createSolidMaterial(const std::string& name, vec3 albedo, f32 roughness, f32 metallic);

    // Get material by name
    Material* getMaterial(const std::string& name);

    // Get default material
    Material* getDefault() { return &m_defaultMaterial; }

    // Create built-in architectural materials
    void createBuiltinMaterials();

    // Create aliases mapping generic names to Poly Haven materials
    void createMaterialAliases();

    // Load/save per-material settings from/to JSON
    void loadMaterialSettings(const std::string& settingsPath);
    void saveMaterialSettings(const std::string& settingsPath);
    void saveMaterialSettings(Material* material, const std::string& settingsPath);

private:
    VulkanContext& m_context;
    std::unordered_map<std::string, std::unique_ptr<Material>> m_materials;
    std::unordered_map<std::string, std::unique_ptr<Texture>> m_textures;
    std::unordered_map<std::string, std::string> m_materialAliases;  // Maps generic names to Poly Haven
    Material m_defaultMaterial;
};

} // namespace arch
