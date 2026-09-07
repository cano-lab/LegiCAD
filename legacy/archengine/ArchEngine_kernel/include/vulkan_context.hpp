/**
 * @file vulkan_context.hpp
 * @brief Vulkan device and resource management
 *
 * This file contains the VulkanContext class which handles all low-level Vulkan
 * initialization and resource management. It provides:
 * - Instance, device, and queue creation
 * - Swapchain management
 * - Buffer and image creation helpers
 * - Command buffer utilities
 * - Debug marker support for profiling tools
 *
 * @see Renderer for high-level rendering operations
 * @see Pipeline for graphics pipeline creation
 */

#pragma once

#include "types.hpp"
#include "window.hpp"
#include <optional>
#include <set>
#include <fstream>

namespace arch {

/**
 * @brief Queue family indices for graphics and present operations
 *
 * Stores the queue family indices discovered during device selection.
 * Both graphics and present families must be available for rendering.
 */
struct QueueFamilyIndices {
    std::optional<u32> graphicsFamily;  ///< Graphics queue family index
    std::optional<u32> presentFamily;   ///< Presentation queue family index

    /**
     * @brief Check if all required queue families are found
     * @return true if both graphics and present families are available
     */
    bool isComplete() const {
        return graphicsFamily.has_value() && presentFamily.has_value();
    }
};

/**
 * @brief Swapchain capabilities and supported modes
 *
 * Contains the surface capabilities, supported formats, and present modes
 * used to configure the swapchain.
 */
struct SwapchainSupportDetails {
    VkSurfaceCapabilitiesKHR capabilities;         ///< Surface capabilities (min/max images, extents)
    std::vector<VkSurfaceFormatKHR> formats;       ///< Supported surface formats
    std::vector<VkPresentModeKHR> presentModes;    ///< Supported presentation modes
};

/**
 * @brief Configuration options for VulkanContext
 *
 * Allows customization of Vulkan initialization including validation,
 * MSAA, shadows, and pipeline caching.
 */
struct VulkanConfig {
    bool enableValidation = true;       ///< Enable Vulkan validation layers
    bool enableDebugMarkers = true;     ///< Enable debug markers for RenderDoc/NSight
    u32 maxFramesInFlight = 2;          ///< Number of frames that can be in-flight
    bool headless = false;              ///< Headless mode (no surface/swapchain)

    /// @name MSAA Settings
    /// @{
    VkSampleCountFlagBits msaaSamples = VK_SAMPLE_COUNT_4_BIT;  ///< MSAA sample count
    bool enableMsaa = true;             ///< Enable multi-sample anti-aliasing
    /// @}

    /// @name Shadow Settings
    /// @{
    u32 shadowMapResolution = 2048;     ///< Shadow map resolution (pixels)
    bool enableShadows = true;          ///< Enable shadow mapping
    /// @}

    std::string pipelineCachePath = "pipeline_cache.bin";  ///< Path for pipeline cache file
};

/**
 * @brief Vulkan device and resource management
 *
 * VulkanContext handles all low-level Vulkan operations including:
 * - Instance and device creation with validation layers
 * - Physical device selection
 * - Swapchain creation and management
 * - Buffer and image allocation
 * - Command buffer management
 * - Pipeline caching
 *
 * Two construction modes are supported:
 * 1. Standard mode: Creates its own VkInstance and VkSurfaceKHR from a Window
 * 2. Embedded mode: Uses externally provided instance and surface (for CAD integration)
 *
 * @note This class is non-copyable. Only one VulkanContext should exist per application.
 *
 * Example usage:
 * @code
 * Window window(1280, 720, "ArchEngine");
 * VulkanConfig config;
 * config.msaaSamples = VK_SAMPLE_COUNT_4_BIT;
 * config.enableValidation = true;
 *
 * VulkanContext context(window, config);
 *
 * // Create a buffer
 * VkBuffer vertexBuffer;
 * VkDeviceMemory vertexMemory;
 * context.createBuffer(size, VK_BUFFER_USAGE_VERTEX_BUFFER_BIT,
 *                      VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT,
 *                      vertexBuffer, vertexMemory);
 * @endcode
 */
class VulkanContext {
public:
    /**
     * @brief Construct VulkanContext with a GLFW window
     * @param window Reference to the Window object
     * @param config Configuration options
     *
     * Creates VkInstance, VkSurfaceKHR, and all other Vulkan resources.
     */
    VulkanContext(Window& window, const VulkanConfig& config = {});

    /**
     * @brief Construct VulkanContext with external instance and surface
     * @param instance Pre-created VkInstance (ownership not transferred)
     * @param surface Pre-created VkSurfaceKHR (ownership not transferred)
     * @param width Initial swapchain width
     * @param height Initial swapchain height
     * @param config Configuration options
     *
     * Use this constructor when embedding ArchEngine in another application
     * that already has a Vulkan instance and surface.
     */
    VulkanContext(VkInstance instance, VkSurfaceKHR surface, u32 width, u32 height, const VulkanConfig& config = {});

    /**
     * @brief Create a headless VulkanContext for compute-only operations
     * @param config Configuration options (headless flag will be set)
     * @return Unique pointer to headless VulkanContext
     *
     * Use this for offline rendering (path tracing) without a display.
     * Does not create a surface or swapchain.
     */
    static std::unique_ptr<VulkanContext> createHeadless(const VulkanConfig& config = {});

    /**
     * @brief Destructor - cleans up all Vulkan resources
     */
    ~VulkanContext();

    /// @name Non-copyable
    /// @{
    VulkanContext(const VulkanContext&) = delete;
    VulkanContext& operator=(const VulkanContext&) = delete;
    /// @}

    /// @name Core Vulkan Accessors
    /// @{

    /** @brief Get the Vulkan instance handle */
    VkInstance getInstance() const { return m_instance; }

    /** @brief Get the logical device handle */
    VkDevice getDevice() const { return m_device; }

    /** @brief Get the physical device handle */
    VkPhysicalDevice getPhysicalDevice() const { return m_physicalDevice; }

    /** @brief Get the graphics queue */
    VkQueue getGraphicsQueue() const { return m_graphicsQueue; }

    /** @brief Get the presentation queue */
    VkQueue getPresentQueue() const { return m_presentQueue; }

    /** @brief Get the command pool for allocating command buffers */
    VkCommandPool getCommandPool() const { return m_commandPool; }

    /** @brief Get the window surface */
    VkSurfaceKHR getSurface() const { return m_surface; }

    /** @brief Get queue family indices */
    const QueueFamilyIndices& getQueueFamilies() const { return m_queueFamilies; }

    /** @brief Get graphics queue family index */
    u32 getGraphicsQueueFamily() const { return m_queueFamilies.graphicsFamily.value(); }

    /** @brief Get maximum frames that can be in-flight */
    u32 getMaxFramesInFlight() const { return m_config.maxFramesInFlight; }
    /// @}

    /// @name Pipeline Cache
    /// @{

    /** @brief Get the pipeline cache for faster pipeline creation */
    VkPipelineCache getPipelineCache() const { return m_pipelineCache; }
    /// @}

    /// @name MSAA Support
    /// @{

    /** @brief Get the configured MSAA sample count */
    VkSampleCountFlagBits getMsaaSamples() const { return m_msaaSamples; }

    /**
     * @brief Get the maximum supported MSAA sample count
     * @return Highest sample count supported by the device
     */
    VkSampleCountFlagBits getMaxUsableSampleCount() const;

    /** @brief Get the MSAA color image view for rendering */
    VkImageView getMsaaColorImageView() const { return m_msaaColorImageView; }

    /** @brief Check if anisotropic filtering is supported */
    bool supportsSamplerAnisotropy() const { return m_deviceFeatures.samplerAnisotropy == VK_TRUE; }

    /** @brief Get maximum anisotropy level supported */
    float getMaxSamplerAnisotropy() const { return m_maxSamplerAnisotropy; }

    /** @brief Check if tessellation shaders are supported */
    bool supportsTessellation() const { return m_deviceFeatures.tessellationShader == VK_TRUE; }

    /** @brief Check if wide lines are supported (often not on AMD) */
    bool supportsWideLines() const { return m_deviceFeatures.wideLines == VK_TRUE; }

    /** @brief Check if non-solid fill mode (wireframe) is supported */
    bool supportsFillModeNonSolid() const { return m_deviceFeatures.fillModeNonSolid == VK_TRUE; }

    /** @brief Check if shader clip distance is supported */
    bool supportsShaderClipDistance() const { return m_deviceFeatures.shaderClipDistance == VK_TRUE; }

    /** @brief Check if running in headless mode */
    bool isHeadless() const { return m_config.headless; }
    /// @}

    /// @name Configuration
    /// @{

    /** @brief Get the current configuration */
    const VulkanConfig& getConfig() const { return m_config; }
    /// @}

    /// @name Swapchain Access
    /// @{

    /** @brief Get the swapchain handle */
    VkSwapchainKHR getSwapchain() const { return m_swapchain; }

    /** @brief Get the swapchain image format */
    VkFormat getSwapchainFormat() const { return m_swapchainFormat; }

    /** @brief Get the swapchain extent (width/height) */
    VkExtent2D getSwapchainExtent() const { return m_swapchainExtent; }

    /** @brief Get all swapchain image views */
    const std::vector<VkImageView>& getSwapchainImageViews() const { return m_swapchainImageViews; }

    /** @brief Get the number of swapchain images */
    u32 getSwapchainImageCount() const { return static_cast<u32>(m_swapchainImages.size()); }
    /// @}

    /// @name Depth Buffer
    /// @{

    /** @brief Get the depth buffer image view */
    VkImageView getDepthImageView() const { return m_depthImageView; }

    /** @brief Get the depth buffer format (D32_SFLOAT) */
    VkFormat getDepthFormat() const { return VK_FORMAT_D32_SFLOAT; }
    /// @}

    /// @name Swapchain Management
    /// @{

    /**
     * @brief Recreate the swapchain after window resize
     *
     * Call when the window size changes. Destroys and recreates all
     * swapchain-dependent resources.
     */
    void recreateSwapchain();

    /**
     * @brief Wait for all device operations to complete
     *
     * Blocks until the GPU is idle. Use before cleanup or resize operations.
     */
    void waitIdle() { vkDeviceWaitIdle(m_device); }
    /// @}

    /// @name Command Buffer Helpers
    /// @{

    /**
     * @brief Begin a single-use command buffer
     * @return Command buffer ready for recording
     *
     * Use for one-time operations like buffer copies or image transitions.
     * Must be paired with endSingleTimeCommands().
     */
    VkCommandBuffer beginSingleTimeCommands();

    /**
     * @brief End and submit a single-use command buffer
     * @param commandBuffer The command buffer from beginSingleTimeCommands()
     *
     * Submits the command buffer and waits for completion.
     */
    void endSingleTimeCommands(VkCommandBuffer commandBuffer);
    /// @}

    /// @name Buffer Creation
    /// @{

    /**
     * @brief Create a Vulkan buffer with memory
     * @param size Buffer size in bytes
     * @param usage Buffer usage flags (e.g., VK_BUFFER_USAGE_VERTEX_BUFFER_BIT)
     * @param properties Memory property flags (e.g., VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)
     * @param buffer Output buffer handle
     * @param bufferMemory Output memory handle
     */
    void createBuffer(VkDeviceSize size, VkBufferUsageFlags usage,
                     VkMemoryPropertyFlags properties, VkBuffer& buffer,
                     VkDeviceMemory& bufferMemory);

    /**
     * @brief Copy data between buffers
     * @param srcBuffer Source buffer
     * @param dstBuffer Destination buffer
     * @param size Number of bytes to copy
     */
    void copyBuffer(VkBuffer srcBuffer, VkBuffer dstBuffer, VkDeviceSize size);

    /**
     * @brief Copy buffer data to an image
     * @param buffer Source buffer containing pixel data
     * @param image Destination image
     * @param width Image width
     * @param height Image height
     */
    void copyBufferToImage(VkBuffer buffer, VkImage image, u32 width, u32 height);

    /**
     * @brief Find a suitable memory type for allocation
     * @param typeFilter Bitmask of acceptable memory types
     * @param properties Required memory properties
     * @return Memory type index
     * @throws std::runtime_error if no suitable memory type found
     */
    u32 findMemoryType(u32 typeFilter, VkMemoryPropertyFlags properties);
    /// @}

    /// @name Image Creation
    /// @{

    /**
     * @brief Create a Vulkan image with memory
     * @param width Image width
     * @param height Image height
     * @param format Image format (e.g., VK_FORMAT_R8G8B8A8_SRGB)
     * @param tiling Image tiling mode
     * @param usage Image usage flags
     * @param properties Memory property flags
     * @param image Output image handle
     * @param imageMemory Output memory handle
     * @param samples MSAA sample count (default: 1)
     */
    void createImage(u32 width, u32 height, VkFormat format, VkImageTiling tiling,
                    VkImageUsageFlags usage, VkMemoryPropertyFlags properties,
                    VkImage& image, VkDeviceMemory& imageMemory,
                    VkSampleCountFlagBits samples = VK_SAMPLE_COUNT_1_BIT);

    /**
     * @brief Create an image view for an image
     * @param image The image to create a view for
     * @param format View format
     * @param aspectFlags Aspect flags (e.g., VK_IMAGE_ASPECT_COLOR_BIT)
     * @return Created image view handle
     */
    VkImageView createImageView(VkImage image, VkFormat format, VkImageAspectFlags aspectFlags);

    /**
     * @brief Transition an image between layouts
     * @param image The image to transition
     * @param format Image format
     * @param oldLayout Current layout
     * @param newLayout Target layout
     *
     * Inserts appropriate pipeline barriers for the layout transition.
     */
    void transitionImageLayout(VkImage image, VkFormat format,
                              VkImageLayout oldLayout, VkImageLayout newLayout);

    /**
     * @brief Transition image layout for multiple mip levels and array layers
     * @param image Image to transition
     * @param format Image format
     * @param oldLayout Current layout
     * @param newLayout Target layout
     * @param mipLevels Number of mip levels to transition
     * @param layerCount Number of array layers to transition
     */
    void transitionImageLayout(VkImage image, VkFormat format,
                              VkImageLayout oldLayout, VkImageLayout newLayout,
                              u32 mipLevels, u32 layerCount);
    /// @}

    /// @name Debug Markers
    /// @{

    /**
     * @brief Begin a labeled debug region (for RenderDoc/NSight)
     * @param cmd Command buffer to label
     * @param name Region name
     * @param color Debug color (RGBA)
     */
    void beginDebugLabel(VkCommandBuffer cmd, const char* name, vec4 color = {1,1,1,1});

    /**
     * @brief End a labeled debug region
     * @param cmd Command buffer
     */
    void endDebugLabel(VkCommandBuffer cmd);

    /**
     * @brief Insert a debug marker at current position
     * @param cmd Command buffer
     * @param name Marker name
     * @param color Debug color (RGBA)
     */
    void insertDebugLabel(VkCommandBuffer cmd, const char* name, vec4 color = {1,1,1,1});
    /// @}

private:
    // Private constructor for headless mode
    VulkanContext(const VulkanConfig& config, bool headless);

    void createInstance();
    void createInstanceHeadless();
    void setupDebugMessenger();
    void createSurface();
    void pickPhysicalDevice();
    void createLogicalDevice();
    void createSwapchain();
    void createImageViews();
    void createCommandPool();
    void createDepthResources();
    void createPipelineCache();
    void savePipelineCache();
    void createMsaaResources();

    void cleanupSwapchain();

    QueueFamilyIndices findQueueFamilies(VkPhysicalDevice device);
    SwapchainSupportDetails querySwapchainSupport(VkPhysicalDevice device);
    bool isDeviceSuitable(VkPhysicalDevice device);
    bool checkDeviceExtensionSupport(VkPhysicalDevice device);

    VkSurfaceFormatKHR chooseSwapSurfaceFormat(const std::vector<VkSurfaceFormatKHR>& formats);
    VkPresentModeKHR chooseSwapPresentMode(const std::vector<VkPresentModeKHR>& modes);
    VkExtent2D chooseSwapExtent(const VkSurfaceCapabilitiesKHR& capabilities);

    static VKAPI_ATTR VkBool32 VKAPI_CALL debugCallback(
        VkDebugUtilsMessageSeverityFlagBitsEXT severity,
        VkDebugUtilsMessageTypeFlagsEXT type,
        const VkDebugUtilsMessengerCallbackDataEXT* callbackData,
        void* userData);

    // Configuration
    VulkanConfig m_config;
    Window* m_window = nullptr;  // nullptr in embedded mode
    bool m_ownsInstance = true;  // false if using external instance
    bool m_ownsSurface = true;   // false if using external surface
    u32 m_embeddedWidth = 0;     // Used in embedded mode
    u32 m_embeddedHeight = 0;    // Used in embedded mode

    // Core Vulkan objects
    VkInstance m_instance = VK_NULL_HANDLE;
    VkDebugUtilsMessengerEXT m_debugMessenger = VK_NULL_HANDLE;
    VkSurfaceKHR m_surface = VK_NULL_HANDLE;
    VkPhysicalDevice m_physicalDevice = VK_NULL_HANDLE;
    VkDevice m_device = VK_NULL_HANDLE;
    VkPhysicalDeviceFeatures m_deviceFeatures{};
    float m_maxSamplerAnisotropy = 1.0f;

    // Pipeline cache (Phase 0)
    VkPipelineCache m_pipelineCache = VK_NULL_HANDLE;

    // MSAA resources (Phase 2)
    VkSampleCountFlagBits m_msaaSamples = VK_SAMPLE_COUNT_1_BIT;
    VkImage m_msaaColorImage = VK_NULL_HANDLE;
    VkDeviceMemory m_msaaColorMemory = VK_NULL_HANDLE;
    VkImageView m_msaaColorImageView = VK_NULL_HANDLE;

    // Queues
    VkQueue m_graphicsQueue = VK_NULL_HANDLE;
    VkQueue m_presentQueue = VK_NULL_HANDLE;
    QueueFamilyIndices m_queueFamilies;

    // Swapchain
    VkSwapchainKHR m_swapchain = VK_NULL_HANDLE;
    std::vector<VkImage> m_swapchainImages;
    std::vector<VkImageView> m_swapchainImageViews;
    VkFormat m_swapchainFormat;
    VkExtent2D m_swapchainExtent;

    // Depth buffer
    VkImage m_depthImage = VK_NULL_HANDLE;
    VkDeviceMemory m_depthImageMemory = VK_NULL_HANDLE;
    VkImageView m_depthImageView = VK_NULL_HANDLE;

    // Command pool
    VkCommandPool m_commandPool = VK_NULL_HANDLE;

    // Device extensions
    const std::vector<const char*> m_deviceExtensions = {
        VK_KHR_SWAPCHAIN_EXTENSION_NAME
    };

    // Validation layers
    const std::vector<const char*> m_validationLayers = {
        "VK_LAYER_KHRONOS_validation"
    };

    // Debug function pointers
    PFN_vkCmdBeginDebugUtilsLabelEXT m_vkCmdBeginDebugUtilsLabelEXT = nullptr;
    PFN_vkCmdEndDebugUtilsLabelEXT m_vkCmdEndDebugUtilsLabelEXT = nullptr;
    PFN_vkCmdInsertDebugUtilsLabelEXT m_vkCmdInsertDebugUtilsLabelEXT = nullptr;
};

} // namespace arch
