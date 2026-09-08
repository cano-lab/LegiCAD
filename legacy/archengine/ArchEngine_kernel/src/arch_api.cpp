/**
 * ArchEngine C API Implementation
 *
 * Wraps the Vulkan renderer for embedding in Qt/Python applications.
 */

#include "arch_api.h"

#include "types.hpp"
#include "vulkan_context.hpp"
#include "renderer.hpp"
#include "qbd_interface.hpp"
#include "path_tracer.hpp"

#include <memory>
#include <string>
#include <cstring>
#include <mutex>
#include <iostream>
#include <set>
#include <map>
#include <chrono>
#include <atomic>
#include <algorithm>
#include <limits>
#include <tuple>
#include <cmath>

#ifdef _WIN32
#define VK_USE_PLATFORM_WIN32_KHR
#include <windows.h>
#include <vulkan/vulkan.h>
#include <vulkan/vulkan_win32.h>
#endif

using namespace arch;

// Global state
namespace {
    std::unique_ptr<VulkanContext> g_context;
    std::unique_ptr<Renderer> g_renderer;
    std::unique_ptr<PathTracer> g_pathTracer;
    Building g_building;
    qbd::QBDLayout g_layout;  // Store layout for room access
    PathTracerConfig g_ptConfig;  // Path tracer configuration

    // Camera state
    float g_cameraYaw = 0.5f;
    float g_cameraPitch = 0.4f;
    float g_cameraDistance = 60.0f;
    vec3 g_cameraTarget = {20.0f, 10.0f, 15.0f};
    float g_cameraFOV = 45.0f;
    bool g_cameraOrthographic = false;

    // Free-look camera mode (for arch_set_camera_pose)
    bool g_freeLookMode = false;
    vec3 g_freeLookCameraPosition = {0.0f, 10.0f, 60.0f};

    // State
    bool g_initialized = false;
    int g_width = 800;
    int g_height = 600;
    int g_selectedElement = -1;
    VisualizationMode g_vizMode = VisualizationMode::Material;
    bool g_terrainEnabled = true;  // Terrain rendering enabled by default

    // Error handling
    std::string g_lastError;
    std::recursive_mutex g_mutex;

    // Vulkan handles for embedded mode
    VkInstance g_instance = VK_NULL_HANDLE;
    VkSurfaceKHR g_surface = VK_NULL_HANDLE;

    void setError(const std::string& error) {
        g_lastError = error;
        std::cerr << "[ArchAPI] Error: " << error << std::endl;
    }

    void updateCamera() {
        if (!g_renderer) return;

        Camera camera;
        if (g_freeLookMode) {
            // Free-look mode: use direct camera position
            camera.position = g_freeLookCameraPosition;
        } else {
            // Orbit mode: calculate position from yaw/pitch/distance
            camera.position.x = g_cameraTarget.x + g_cameraDistance * cos(g_cameraPitch) * sin(g_cameraYaw);
            camera.position.y = g_cameraTarget.y + g_cameraDistance * sin(g_cameraPitch);
            camera.position.z = g_cameraTarget.z + g_cameraDistance * cos(g_cameraPitch) * cos(g_cameraYaw);
        }
        camera.target = g_cameraTarget;
        camera.up = vec3(0, 1, 0);
        camera.fov = g_cameraFOV;
        camera.nearPlane = 0.1f;
        camera.farPlane = 100000.0f;  // Large value to handle mm units
        camera.isOrthographic = g_cameraOrthographic;
        camera.orthoSize = g_cameraDistance * 0.5f;  // Scale ortho based on distance

        g_renderer->setCamera(camera);
    }
}

extern "C" {

ARCH_API int arch_init(void* hwnd, int width, int height) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (g_initialized) {
        setError("Already initialized");
        return -1;
    }

    try {
        g_width = width;
        g_height = height;

#ifdef _WIN32
        HWND hWnd = static_cast<HWND>(hwnd);

        // Create Vulkan instance
        VkApplicationInfo appInfo{};
        appInfo.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
        appInfo.pApplicationName = "ArchEngine";
        appInfo.applicationVersion = VK_MAKE_VERSION(1, 0, 0);
        appInfo.pEngineName = "ArchEngine";
        appInfo.engineVersion = VK_MAKE_VERSION(1, 0, 0);
        appInfo.apiVersion = VK_API_VERSION_1_2;

        std::vector<const char*> extensions = {
            VK_KHR_SURFACE_EXTENSION_NAME,
            VK_KHR_WIN32_SURFACE_EXTENSION_NAME
        };

        std::vector<const char*> layers;
#ifdef _DEBUG
        layers.push_back("VK_LAYER_KHRONOS_validation");
        extensions.push_back(VK_EXT_DEBUG_UTILS_EXTENSION_NAME);
#endif

        VkInstanceCreateInfo createInfo{};
        createInfo.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
        createInfo.pApplicationInfo = &appInfo;
        createInfo.enabledExtensionCount = static_cast<uint32_t>(extensions.size());
        createInfo.ppEnabledExtensionNames = extensions.data();
        createInfo.enabledLayerCount = static_cast<uint32_t>(layers.size());
        createInfo.ppEnabledLayerNames = layers.data();

        if (vkCreateInstance(&createInfo, nullptr, &g_instance) != VK_SUCCESS) {
            setError("Failed to create Vulkan instance");
            return -2;
        }

        // Create Win32 surface
        VkWin32SurfaceCreateInfoKHR surfaceInfo{};
        surfaceInfo.sType = VK_STRUCTURE_TYPE_WIN32_SURFACE_CREATE_INFO_KHR;
        surfaceInfo.hwnd = hWnd;
        surfaceInfo.hinstance = GetModuleHandle(nullptr);

        if (vkCreateWin32SurfaceKHR(g_instance, &surfaceInfo, nullptr, &g_surface) != VK_SUCCESS) {
            setError("Failed to create window surface");
            vkDestroyInstance(g_instance, nullptr);
            g_instance = VK_NULL_HANDLE;
            return -3;
        }

        // Create Vulkan context with existing instance and surface
        VulkanConfig config{};
        config.enableValidation = false;  // Already set up
        config.maxFramesInFlight = 2;

        g_context = std::make_unique<VulkanContext>(g_instance, g_surface, width, height, config);
        g_renderer = std::make_unique<Renderer>(*g_context);

        // Initialize with empty building
        g_building.name = "Empty";

        g_initialized = true;
        std::cout << "[ArchAPI] Initialized " << width << "x" << height << std::endl;
        return 0;
#else
        setError("Only Windows is supported");
        return -4;
#endif
    }
    catch (const std::exception& e) {
        setError(std::string("Init failed: ") + e.what());
        return -5;
    }
}

ARCH_API int arch_init_headless(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (g_initialized) {
        setError("Already initialized");
        return -1;
    }

    try {
        // Create headless Vulkan context (no window/surface)
        VulkanConfig config{};
        config.enableValidation = false;
        config.headless = true;

        g_context = VulkanContext::createHeadless(config);
        // No renderer needed for headless path tracing
        // g_renderer is left null - only path tracer will be used

        // Initialize with empty building
        g_building.name = "Empty";

        g_initialized = true;
        std::cout << "[ArchAPI] Initialized in headless mode" << std::endl;
        return 0;
    }
    catch (const std::exception& e) {
        setError(std::string("Headless init failed: ") + e.what());
        return -1;
    }
}

ARCH_API void arch_shutdown(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_initialized) return;

    if (g_context) {
        g_context->waitIdle();
    }

    g_pathTracer.reset();
    g_renderer.reset();
    g_context.reset();

    if (g_surface != VK_NULL_HANDLE) {
        vkDestroySurfaceKHR(g_instance, g_surface, nullptr);
        g_surface = VK_NULL_HANDLE;
    }

    if (g_instance != VK_NULL_HANDLE) {
        vkDestroyInstance(g_instance, nullptr);
        g_instance = VK_NULL_HANDLE;
    }

    g_initialized = false;
    std::cout << "[ArchAPI] Shutdown complete" << std::endl;
}

ARCH_API int arch_is_initialized(void) {
    return g_initialized ? 1 : 0;
}

ARCH_API int arch_load_json(const char* json_str) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_initialized) {
        setError("Not initialized");
        return -1;
    }

    try {
        // Clear mesh cache before loading new scene to prevent memory leaks
        if (g_renderer) {
            g_renderer->clearMeshCache();
        }

        auto& qbd = qbd::getQBDInterface();
        auto layoutOpt = qbd.loadFromJSON(std::string(json_str));

        if (!layoutOpt.has_value()) {
            setError("Failed to parse JSON");
            return -2;
        }

        g_layout = *layoutOpt;  // Store layout for room access

        // Debug: check if terrain was parsed
        std::cout << "[ArchAPI] Layout terrain has data: " << (g_layout.terrain.hasData() ? "YES" : "NO") << std::endl;
        if (g_layout.terrain.hasData()) {
            std::cout << "[ArchAPI] Layout terrain: " << g_layout.terrain.vertices.size() << " vertices" << std::endl;
        }

        g_building = qbd.toBuilding(g_layout);
        g_building.name = "Loaded Building";

        // Scale from mm to feet
        const float mmToFeet = 1.0f / 304.8f;
        for (auto& elem : g_building.elements) {
            elem.start *= mmToFeet;
            elem.end *= mmToFeet;
            elem.width *= mmToFeet;
            elem.depth *= mmToFeet;
            for (auto& v : elem.mesh.vertices) {
                v *= mmToFeet;
            }
        }

        // Scale terrain vertices from mm to feet
        for (auto& vert : g_building.terrainMesh.vertices) {
            vert.position *= mmToFeet;
        }

        std::cout << "[ArchAPI] Loaded building with " << g_building.elements.size() << " elements" << std::endl;
        std::cout << "[ArchAPI] Terrain has data: " << (g_building.terrainMesh.hasData() ? "YES" : "NO")
                  << ", vertices: " << g_building.terrainMesh.vertices.size()
                  << ", indices: " << g_building.terrainMesh.indices.size() << std::endl;

        // Reset camera to fit
        arch_reset_camera();

        return 0;
    }
    catch (const std::exception& e) {
        setError(std::string("Load failed: ") + e.what());
        return -3;
    }
}

ARCH_API int arch_load_file(const char* file_path) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_initialized) {
        setError("Not initialized");
        return -1;
    }

    try {
        // Clear mesh cache before loading new scene to prevent memory leaks
        if (g_renderer) {
            g_renderer->clearMeshCache();
        }

        auto& qbd = qbd::getQBDInterface();
        auto layoutOpt = qbd.loadFromFile(std::string(file_path));

        if (!layoutOpt.has_value()) {
            setError("Failed to load file");
            return -2;
        }

        g_layout = *layoutOpt;  // Store layout for room access
        g_building = qbd.toBuilding(g_layout);
        g_building.name = file_path;

        // Scale from mm to feet
        const float mmToFeet = 1.0f / 304.8f;
        for (auto& elem : g_building.elements) {
            elem.start *= mmToFeet;
            elem.end *= mmToFeet;
            elem.width *= mmToFeet;
            elem.depth *= mmToFeet;
            for (auto& v : elem.mesh.vertices) {
                v *= mmToFeet;
            }
        }

        std::cout << "[ArchAPI] Loaded file: " << file_path << " (" << g_building.elements.size() << " elements)" << std::endl;

        arch_reset_camera();
        return 0;
    }
    catch (const std::exception& e) {
        setError(std::string("Load failed: ") + e.what());
        return -3;
    }
}

ARCH_API int arch_render_frame(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_initialized || !g_renderer) {
        return -1;
    }

    try {
        updateCamera();

        if (g_renderer->beginFrame()) {
            // Render shadow pass
            g_renderer->renderShadowPass(g_building.elements);

            // Main render pass
            vec4 clearColor = {0.05f, 0.05f, 0.08f, 1.0f};
            g_renderer->beginRenderPass(clearColor);

            g_renderer->drawSky();
            g_renderer->drawGrid(150.0f, 5.0f);

            // Draw terrain if enabled
            if (g_terrainEnabled && g_building.terrainMesh.hasData()) {
                g_renderer->drawTerrain(g_building.terrainMesh);
            }

            // Draw building with selection
            std::set<int> selected;
            if (g_selectedElement >= 0) {
                selected.insert(g_selectedElement);
            }
            g_renderer->drawStructuralFrame(g_building.elements, g_building, selected);

            g_renderer->endRenderPass();
            g_renderer->endFrame();
        }

        return 0;
    }
    catch (const std::exception& e) {
        setError(std::string("Render failed: ") + e.what());
        return -2;
    }
}

ARCH_API void arch_resize(int width, int height) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_initialized || width <= 0 || height <= 0) return;

    g_width = width;
    g_height = height;

    if (g_renderer) {
        g_renderer->onResize();
    }

    std::cout << "[ArchAPI] Resized to " << width << "x" << height << std::endl;
}

ARCH_API void arch_set_camera(float yaw, float pitch, float distance) {
    g_cameraYaw = yaw;
    g_cameraPitch = glm::clamp(pitch, -1.4f, 1.4f);
    g_cameraDistance = glm::clamp(distance, 10.0f, 500.0f);
}

ARCH_API void arch_set_camera_target(float x, float y, float z) {
    g_cameraTarget = vec3(x, y, z);
}

ARCH_API void arch_set_camera_pose(float cam_x, float cam_y, float cam_z,
                                   float target_x, float target_y, float target_z) {
    // Direct camera positioning for free-look mode
    g_freeLookMode = true;
    g_freeLookCameraPosition = vec3(cam_x, cam_y, cam_z);

    vec3 targetPos(target_x, target_y, target_z);
    g_cameraTarget = targetPos;

    // Calculate distance (for zoom consistency)
    vec3 offset = g_freeLookCameraPosition - targetPos;
    g_cameraDistance = glm::length(offset);

    // Calculate yaw and pitch from offset vector
    if (g_cameraDistance > 0.001f) {
        vec3 dir = offset / g_cameraDistance;
        g_cameraPitch = glm::asin(dir.y);  // Vertical angle
        g_cameraYaw = glm::atan(dir.z, dir.x);  // Horizontal angle
    }

    std::cout << "[FreeLook] Set camera pose: pos=(" << g_freeLookCameraPosition.x << ", "
              << g_freeLookCameraPosition.y << ", " << g_freeLookCameraPosition.z << ") target=("
              << g_cameraTarget.x << ", " << g_cameraTarget.y << ", " << g_cameraTarget.z << ")\n";
}

ARCH_API void arch_get_camera_state(float* out_target_x, float* out_target_y, float* out_target_z, float* out_distance) {
    if (out_target_x) *out_target_x = g_cameraTarget.x;
    if (out_target_y) *out_target_y = g_cameraTarget.y;
    if (out_target_z) *out_target_z = g_cameraTarget.z;
    if (out_distance) *out_distance = g_cameraDistance;
}

ARCH_API void arch_reset_camera(void) {
    if (g_building.elements.empty()) {
        g_cameraTarget = vec3(0, 0, 0);
        g_cameraDistance = 60.0f;
        return;
    }

    vec3 minBound(1e9f), maxBound(-1e9f);
    for (const auto& elem : g_building.elements) {
        minBound = glm::min(minBound, glm::min(elem.start, elem.end));
        maxBound = glm::max(maxBound, glm::max(elem.start, elem.end));
    }

    g_cameraTarget = (minBound + maxBound) * 0.5f;
    float size = glm::length(maxBound - minBound);
    g_cameraDistance = size * 1.5f;
    g_cameraYaw = 0.5f;
    g_cameraPitch = 0.4f;

    std::cout << "[Camera] Bounds: (" << minBound.x << ", " << minBound.y << ", " << minBound.z << ") to ("
              << maxBound.x << ", " << maxBound.y << ", " << maxBound.z << ")\n";
    std::cout << "[Camera] Target: (" << g_cameraTarget.x << ", " << g_cameraTarget.y << ", " << g_cameraTarget.z
              << "), Distance: " << g_cameraDistance << "\n";
}

ARCH_API void arch_set_camera_fov(float fov) {
    g_cameraFOV = glm::clamp(fov, 10.0f, 120.0f);
}

ARCH_API float arch_get_camera_fov(void) {
    return g_cameraFOV;
}

ARCH_API void arch_set_orthographic(int enabled) {
    g_cameraOrthographic = (enabled != 0);
}

ARCH_API int arch_get_orthographic(void) {
    return g_cameraOrthographic ? 1 : 0;
}

ARCH_API void arch_set_viz_mode(int mode) {
    if (mode >= 0 && mode <= 5) {
        g_vizMode = static_cast<VisualizationMode>(mode);
        if (g_renderer) {
            g_renderer->setVisualizationMode(g_vizMode);
        }
    }
}

ARCH_API void arch_select_element(int element_index) {
    g_selectedElement = element_index;
}

ARCH_API int arch_get_selected_element(void) {
    return g_selectedElement;
}

ARCH_API int arch_pick_element(int screen_x, int screen_y) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_initialized || g_building.elements.empty()) {
        return -1;
    }

    // Convert screen coordinates to normalized device coordinates (-1 to 1)
    float ndcX = (2.0f * screen_x / g_width) - 1.0f;
    float ndcY = 1.0f - (2.0f * screen_y / g_height);  // Flip Y

    // Get camera position
    vec3 camPos;
    camPos.x = g_cameraTarget.x + g_cameraDistance * cos(g_cameraPitch) * sin(g_cameraYaw);
    camPos.y = g_cameraTarget.y + g_cameraDistance * sin(g_cameraPitch);
    camPos.z = g_cameraTarget.z + g_cameraDistance * cos(g_cameraPitch) * cos(g_cameraYaw);

    // Build view and projection matrices
    mat4 view = glm::lookAt(camPos, g_cameraTarget, vec3(0, 1, 0));
    mat4 proj;
    float aspect = float(g_width) / float(g_height);

    if (g_cameraOrthographic) {
        float orthoSize = g_cameraDistance * 0.5f;
        proj = glm::ortho(-orthoSize * aspect, orthoSize * aspect, -orthoSize, orthoSize, 0.1f, 500.0f);
    } else {
        proj = glm::perspective(glm::radians(g_cameraFOV), aspect, 0.1f, 500.0f);
    }

    // Inverse view-projection to get ray
    mat4 invViewProj = glm::inverse(proj * view);

    // Ray in world space
    vec4 rayStart4 = invViewProj * vec4(ndcX, ndcY, -1.0f, 1.0f);
    vec4 rayEnd4 = invViewProj * vec4(ndcX, ndcY, 1.0f, 1.0f);
    vec3 rayStart = vec3(rayStart4) / rayStart4.w;
    vec3 rayEnd = vec3(rayEnd4) / rayEnd4.w;
    vec3 rayDir = glm::normalize(rayEnd - rayStart);

    // Test ray against each element's AABB
    int closestElement = -1;
    float closestDist = 1e9f;

    for (size_t i = 0; i < g_building.elements.size(); ++i) {
        const auto& elem = g_building.elements[i];

        // Compute element AABB
        vec3 minB = glm::min(elem.start, elem.end);
        vec3 maxB = glm::max(elem.start, elem.end);

        // Expand by element width/depth (approximate)
        float halfW = elem.width * 0.5f + 0.1f;
        float halfD = elem.depth * 0.5f + 0.1f;
        minB -= vec3(halfW, 0, halfD);
        maxB += vec3(halfW, elem.depth, halfD);

        // Ray-AABB intersection test (slab method)
        vec3 invDir = 1.0f / rayDir;
        vec3 t1 = (minB - rayStart) * invDir;
        vec3 t2 = (maxB - rayStart) * invDir;

        vec3 tMin = glm::min(t1, t2);
        vec3 tMax = glm::max(t1, t2);

        float tNear = glm::max(glm::max(tMin.x, tMin.y), tMin.z);
        float tFar = glm::min(glm::min(tMax.x, tMax.y), tMax.z);

        if (tNear <= tFar && tFar > 0) {
            float dist = tNear > 0 ? tNear : tFar;
            if (dist < closestDist) {
                closestDist = dist;
                closestElement = static_cast<int>(i);
            }
        }
    }

    return closestElement;
}

ARCH_API int arch_get_element_count(void) {
    return static_cast<int>(g_building.elements.size());
}

ARCH_API const char* arch_get_error(void) {
    return g_lastError.c_str();
}

// =============================================================================
// Section Clipping API
// =============================================================================

ARCH_API void arch_set_clipping_enabled(int enabled) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setClippingEnabled(enabled != 0);
    }
}

ARCH_API int arch_get_clipping_enabled(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return (g_renderer && g_renderer->getClippingEnabled()) ? 1 : 0;
}

ARCH_API void arch_set_clip_axis(int axis) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer && axis >= 0 && axis <= 2) {
        g_renderer->setClipAxis(axis);
    }
}

ARCH_API int arch_get_clip_axis(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_renderer ? g_renderer->getClipAxis() : 1;
}

ARCH_API void arch_set_clip_height(float height) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setClipHeight(height);
    }
}

ARCH_API float arch_get_clip_height(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_renderer ? g_renderer->getClipHeight() : 0.0f;
}

ARCH_API void arch_set_clip_flipped(int flipped) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setClipFlipped(flipped != 0);
    }
}

ARCH_API int arch_get_clip_flipped(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return (g_renderer && g_renderer->getClipFlipped()) ? 1 : 0;
}

ARCH_API void arch_set_section_floor_plan(float y_height) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setClipAxis(1);  // Y axis
        g_renderer->setClipHeight(y_height);
        g_renderer->setClipFlipped(false);
        g_renderer->setClippingEnabled(true);
    }
}

ARCH_API void arch_set_section_elevation(int axis, float position) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer && (axis == 0 || axis == 2)) {
        g_renderer->setClipAxis(axis);
        g_renderer->setClipHeight(position);
        g_renderer->setClipFlipped(false);
        g_renderer->setClippingEnabled(true);
    }
}

// =============================================================================
// Section Box API (Multi-Plane Clipping)
// =============================================================================

ARCH_API void arch_set_section_box(float min_x, float min_y, float min_z,
                                   float max_x, float max_y, float max_z) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setSectionBox(
            vec3(min_x, min_y, min_z),
            vec3(max_x, max_y, max_z)
        );
    }
}

ARCH_API void arch_clear_section_box(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->clearSectionBox();
    }
}

ARCH_API int arch_has_section_box(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return (g_renderer && g_renderer->hasSectionBox()) ? 1 : 0;
}

ARCH_API int arch_get_section_box(float* out_min_x, float* out_min_y, float* out_min_z,
                                  float* out_max_x, float* out_max_y, float* out_max_z) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (!g_renderer) return -1;

    vec3 minBounds, maxBounds;
    if (!g_renderer->getSectionBoxBounds(minBounds, maxBounds)) {
        return -1;  // No section box active
    }

    if (out_min_x) *out_min_x = minBounds.x;
    if (out_min_y) *out_min_y = minBounds.y;
    if (out_min_z) *out_min_z = minBounds.z;
    if (out_max_x) *out_max_x = maxBounds.x;
    if (out_max_y) *out_max_y = maxBounds.y;
    if (out_max_z) *out_max_z = maxBounds.z;
    return 0;
}

ARCH_API void arch_set_clip_plane_at(int index, float a, float b, float c, float d, int enabled) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer && index >= 0 && index < 6) {
        g_renderer->setClipPlaneAt(static_cast<u32>(index), vec4(a, b, c, d), enabled != 0);
    }
}

ARCH_API int arch_get_clip_plane_at(int index, float* out_a, float* out_b, float* out_c, float* out_d) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (!g_renderer || index < 0 || index >= 6) return 0;

    const vec4& plane = g_renderer->getClipPlaneAt(static_cast<u32>(index));
    if (out_a) *out_a = plane.x;
    if (out_b) *out_b = plane.y;
    if (out_c) *out_c = plane.z;
    if (out_d) *out_d = plane.w;

    return g_renderer->getClipPlaneEnabled(static_cast<u32>(index)) ? 1 : 0;
}

ARCH_API int arch_get_num_clip_planes(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_renderer ? static_cast<int>(g_renderer->getNumClipPlanes()) : 0;
}

// =============================================================================
// Material Style API
// =============================================================================

ARCH_API void arch_set_material_style(int style) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer && style >= 0 && style <= 3) {
        g_renderer->setMaterialStyle(static_cast<MaterialStyle>(style));
    }
}

ARCH_API int arch_get_material_style(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_renderer ? static_cast<int>(g_renderer->getMaterialStyle()) : 1; // Default: Clean
}

ARCH_API void arch_set_uv_scale(float scale_u, float scale_v) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        // Use average of U and V for now (renderer uses single scale)
        g_renderer->setMaterialUVScale((scale_u + scale_v) * 0.5f);
    }
}

ARCH_API void arch_get_uv_scale(float* out_u, float* out_v) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer && out_u && out_v) {
        float scale = g_renderer->getMaterialUVScale();
        *out_u = scale;
        *out_v = scale;
    }
}

ARCH_API void arch_set_roughness_multiplier(float multiplier) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        // Use offset: multiplier 1.0 = offset 0, multiplier 0.5 = offset -0.5, etc.
        g_renderer->setMaterialRoughnessOffset(multiplier - 1.0f);
    }
}

ARCH_API float arch_get_roughness_multiplier(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_renderer ? (g_renderer->getMaterialRoughnessOffset() + 1.0f) : 1.0f;
}

ARCH_API void arch_set_metallic_multiplier(float multiplier) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setMaterialMetallicOffset(multiplier - 1.0f);
    }
}

ARCH_API float arch_get_metallic_multiplier(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_renderer ? (g_renderer->getMaterialMetallicOffset() + 1.0f) : 1.0f;
}

ARCH_API void arch_set_ao_strength(float strength) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setMaterialAOStrength(strength);
    }
}

ARCH_API float arch_get_ao_strength(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_renderer ? g_renderer->getMaterialAOStrength() : 1.0f;
}

// =============================================================================
// Shadows & Lighting API
// =============================================================================

ARCH_API void arch_set_shadows_enabled(int enabled) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setShadowsEnabled(enabled != 0);
    }
}

ARCH_API int arch_get_shadows_enabled(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return (g_renderer && g_renderer->getShadowsEnabled()) ? 1 : 0;
}

ARCH_API void arch_set_light_direction(float x, float y, float z) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setLightDirection(vec3(x, y, z));
    }
}

ARCH_API void arch_get_light_direction(float* out_x, float* out_y, float* out_z) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer && out_x && out_y && out_z) {
        const vec3& dir = g_renderer->getLightDirection();
        *out_x = dir.x;
        *out_y = dir.y;
        *out_z = dir.z;
    }
}

// =============================================================================
// SSAO API
// =============================================================================

ARCH_API void arch_set_ssao_enabled(int enabled) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setSSAOEnabled(enabled != 0);
    }
}

ARCH_API int arch_get_ssao_enabled(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return (g_renderer && g_renderer->getSSAOEnabled()) ? 1 : 0;
}

ARCH_API void arch_set_ssao_radius(float radius) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setSSAORadius(radius);
    }
}

ARCH_API float arch_get_ssao_radius(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_renderer ? g_renderer->getSSAORadius() : 0.5f;
}

ARCH_API void arch_set_ssao_intensity(float intensity) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setSSAOIntensity(intensity);
    }
}

ARCH_API float arch_get_ssao_intensity(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_renderer ? g_renderer->getSSAOIntensity() : 1.0f;
}

// =============================================================================
// Bloom API
// =============================================================================

ARCH_API void arch_set_bloom_enabled(int enabled) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setBloomEnabled(enabled != 0);
    }
}

ARCH_API int arch_get_bloom_enabled(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return (g_renderer && g_renderer->getBloomEnabled()) ? 1 : 0;
}

ARCH_API void arch_set_bloom_threshold(float threshold) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setBloomThreshold(threshold);
    }
}

ARCH_API float arch_get_bloom_threshold(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_renderer ? g_renderer->getBloomThreshold() : 1.0f;
}

ARCH_API void arch_set_bloom_intensity(float intensity) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setBloomIntensity(intensity);
    }
}

ARCH_API float arch_get_bloom_intensity(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_renderer ? g_renderer->getBloomIntensity() : 0.5f;
}

// =============================================================================
// Tonemapping & Exposure API
// =============================================================================

ARCH_API void arch_set_exposure(float exposure) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setExposure(exposure);
    }
}

ARCH_API float arch_get_exposure(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_renderer ? g_renderer->getExposure() : 1.0f;
}

ARCH_API void arch_set_tonemap_mode(int mode) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer && mode >= 0 && mode <= 2) {
        g_renderer->setTonemapMode(static_cast<u32>(mode));
    }
}

ARCH_API int arch_get_tonemap_mode(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_renderer ? static_cast<int>(g_renderer->getTonemapMode()) : 1; // Default: ACES
}

// =============================================================================
// Room Data Export API
// =============================================================================

ARCH_API int arch_get_room_count(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return static_cast<int>(g_layout.rooms.size());
}

ARCH_API int arch_get_room_data(int index, ArchRoomData* out_room) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!out_room) return -1;
    if (index < 0 || index >= static_cast<int>(g_layout.rooms.size())) return -2;

    // Get room by index (iterate the map)
    auto it = g_layout.rooms.begin();
    std::advance(it, index);

    const auto& room = it->second;

    // Copy strings safely
    strncpy(out_room->id, room.id.c_str(), sizeof(out_room->id) - 1);
    out_room->id[sizeof(out_room->id) - 1] = '\0';

    strncpy(out_room->name, room.name.c_str(), sizeof(out_room->name) - 1);
    out_room->name[sizeof(out_room->name) - 1] = '\0';

    strncpy(out_room->room_type, room.roomType.c_str(), sizeof(out_room->room_type) - 1);
    out_room->room_type[sizeof(out_room->room_type) - 1] = '\0';

    // Copy bounds (in mm)
    out_room->bounds_x = room.bounds.x;
    out_room->bounds_y = room.bounds.y;
    out_room->bounds_width = room.bounds.width;
    out_room->bounds_height = room.bounds.height;

    // Copy center (in mm)
    out_room->center_x = room.center.x;
    out_room->center_y = room.center.y;

    out_room->area = room.area;
    out_room->zone = static_cast<int>(room.zone);

    return 0;
}

ARCH_API int arch_get_all_rooms(ArchRoomData* out_rooms, int max_rooms) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!out_rooms || max_rooms <= 0) return 0;

    int count = 0;
    for (const auto& [id, room] : g_layout.rooms) {
        if (count >= max_rooms) break;

        ArchRoomData& out = out_rooms[count];

        strncpy(out.id, room.id.c_str(), sizeof(out.id) - 1);
        out.id[sizeof(out.id) - 1] = '\0';

        strncpy(out.name, room.name.c_str(), sizeof(out.name) - 1);
        out.name[sizeof(out.name) - 1] = '\0';

        strncpy(out.room_type, room.roomType.c_str(), sizeof(out.room_type) - 1);
        out.room_type[sizeof(out.room_type) - 1] = '\0';

        out.bounds_x = room.bounds.x;
        out.bounds_y = room.bounds.y;
        out.bounds_width = room.bounds.width;
        out.bounds_height = room.bounds.height;
        out.center_x = room.center.x;
        out.center_y = room.center.y;
        out.area = room.area;
        out.zone = static_cast<int>(room.zone);

        count++;
    }

    return count;
}

// =============================================================================
// Per-Element Material Override Implementation
// =============================================================================

ARCH_API int arch_set_element_material(int element_index,
                                       float uv_scale,
                                       float normal_strength,
                                       float brightness,
                                       float contrast) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer) {
        setError("Renderer not initialized");
        return -1;
    }

    if (element_index < 0 || element_index >= static_cast<int>(g_building.elements.size())) {
        setError("Invalid element index");
        return -2;
    }

    // Build override mask
    u32 mask = 0;
    if (uv_scale != 1.0f) mask |= (1u << 0);  // OVERRIDE_UV_SCALE
    if (normal_strength != 1.0f) mask |= (1u << 1);  // OVERRIDE_NORMAL_STRENGTH
    if (brightness != 0.0f) mask |= (1u << 2);  // OVERRIDE_BRIGHTNESS
    if (contrast != 1.0f) mask |= (1u << 3);  // OVERRIDE_CONTRAST

    // Apply override via renderer
    g_renderer->setElementOverride(element_index, mask, uv_scale, normal_strength, brightness, contrast);

    return 0;
}

ARCH_API int arch_clear_element_material(int element_index) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer) {
        setError("Renderer not initialized");
        return -1;
    }

    if (element_index < 0 || element_index >= static_cast<int>(g_building.elements.size())) {
        setError("Invalid element index");
        return -2;
    }

    g_renderer->clearElementOverride(element_index);
    return 0;
}

ARCH_API void arch_clear_all_material_overrides(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->clearAllElementOverrides();
    }
}

ARCH_API int arch_has_material_override(int element_index) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer || element_index < 0 || element_index >= static_cast<int>(g_building.elements.size())) {
        return 0;
    }

    return g_renderer->hasElementOverride(element_index) ? 1 : 0;
}

ARCH_API int arch_get_element_material(int element_index,
                                      float* out_uv_scale,
                                      float* out_normal_strength,
                                      float* out_brightness,
                                      float* out_contrast) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer) {
        setError("Renderer not initialized");
        return -1;
    }

    if (element_index < 0 || element_index >= static_cast<int>(g_building.elements.size())) {
        setError("Invalid element index");
        return -2;
    }

    if (!g_renderer->hasElementOverride(element_index)) {
        return -3;  // No override
    }

    // Get override values
    const auto* override = g_renderer->getElementOverride(element_index);
    if (override) {
        if (out_uv_scale) *out_uv_scale = override->uvScale;
        if (out_normal_strength) *out_normal_strength = override->normalStrength;
        if (out_brightness) *out_brightness = override->brightness;
        if (out_contrast) *out_contrast = override->contrast;
    }

    return 0;
}

ARCH_API int arch_apply_material_batch(const int* indices, int count,
                                       float uv_scale,
                                       float normal_strength,
                                       float brightness,
                                       float contrast) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer) {
        setError("Renderer not initialized");
        return 0;
    }

    if (!indices || count <= 0) {
        setError("Invalid indices array");
        return 0;
    }

    // Build override mask
    u32 mask = 0;
    if (uv_scale != 1.0f) mask |= (1u << 0);
    if (normal_strength != 1.0f) mask |= (1u << 1);
    if (brightness != 0.0f) mask |= (1u << 2);
    if (contrast != 1.0f) mask |= (1u << 3);

    int updated = 0;
    for (int i = 0; i < count; i++) {
        int idx = indices[i];
        if (idx >= 0 && idx < static_cast<int>(g_building.elements.size())) {
            g_renderer->setElementOverride(idx, mask, uv_scale, normal_strength, brightness, contrast);
            updated++;
        }
    }

    return updated;
}

ARCH_API int arch_get_override_count(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer) {
        return 0;
    }

    return static_cast<int>(g_renderer->getOverrideCount());
}

ARCH_API int arch_get_override_indices(int* out_indices, int max_indices) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer) {
        return 0;
    }

    if (!out_indices || max_indices <= 0) {
        return 0;
    }

    return g_renderer->getElementOverrideIndices(out_indices, max_indices);
}

// =============================================================================
// Material Library API Implementation
// =============================================================================

ARCH_API int arch_get_material_count(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer) {
        return 0;
    }

    return static_cast<int>(g_renderer->getMaterialNames().size());
}

ARCH_API const char* arch_get_material_name(int index) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer) {
        setError("Renderer not initialized");
        return nullptr;
    }

    const auto& materials = g_renderer->getMaterialNames();
    if (index < 0 || index >= static_cast<int>(materials.size())) {
        setError("Invalid material index");
        return nullptr;
    }

    // Store in static buffer for next API call (valid until next call)
    static std::string g_materialNameBuffer;
    g_materialNameBuffer = materials[index];
    return g_materialNameBuffer.c_str();
}

ARCH_API const char* arch_get_material_category(int index) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer) {
        setError("Renderer not initialized");
        return nullptr;
    }

    const auto& materials = g_renderer->getMaterialNames();
    if (index < 0 || index >= static_cast<int>(materials.size())) {
        setError("Invalid material index");
        return nullptr;
    }

    // Extract category from material path (format: "category/material_name")
    const std::string& materialPath = materials[index];
    size_t slashPos = materialPath.find('/');
    std::string category = (slashPos != std::string::npos)
                          ? materialPath.substr(0, slashPos)
                          : "general";

    static std::string g_categoryBuffer;
    g_categoryBuffer = category;
    return g_categoryBuffer.c_str();
}

ARCH_API int arch_get_materials_by_category(const char* category,
                                            int* out_indices,
                                            int max_indices) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer) {
        setError("Renderer not initialized");
        return 0;
    }

    if (!category || !out_indices || max_indices <= 0) {
        setError("Invalid parameters");
        return 0;
    }

    const auto& materials = g_renderer->getMaterialNames();
    std::string catPrefix = std::string(category) + "/";
    int found = 0;

    for (size_t i = 0; i < materials.size() && found < max_indices; i++) {
        // Check if material starts with category prefix
        if (materials[i].compare(0, catPrefix.length(), catPrefix) == 0) {
            out_indices[found++] = static_cast<int>(i);
        }
    }

    return found;
}

ARCH_API int arch_find_material(const char* name) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer) {
        return -1;
    }

    if (!name) {
        return -1;
    }

    const auto& materials = g_renderer->getMaterialNames();
    for (size_t i = 0; i < materials.size(); i++) {
        if (materials[i] == name) {
            return static_cast<int>(i);
        }
    }

    return -1;  // Not found
}

ARCH_API int arch_apply_material_to_element(int element_index, const char* material_name) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer) {
        setError("Renderer not initialized");
        return -1;
    }

    if (element_index < 0 || element_index >= static_cast<int>(g_building.elements.size())) {
        setError("Invalid element index");
        return -2;
    }

    if (!material_name) {
        setError("Invalid material name");
        return -3;
    }

    // Find material index
    int matIndex = arch_find_material(material_name);
    if (matIndex < 0) {
        setError("Material not found");
        return -4;
    }

    // Get category from material path
    const std::string& materialPath = g_renderer->getMaterialNames()[matIndex];
    size_t slashPos = materialPath.find('/');
    std::string category = (slashPos != std::string::npos)
                          ? materialPath.substr(0, slashPos)
                          : "general";

    // Set override mask for material application
    u32 mask = (1u << 0);  // UV_SCALE

    // Different UV scales for different categories
    float uvScale = 1.0f;
    if (category == "walls") uvScale = 1.0f;
    else if (category == "floors") uvScale = 2.0f;
    else if (category == "roofs") uvScale = 1.5f;

    g_renderer->setElementOverride(element_index, mask, uvScale, 1.0f, 0.0f, 1.0f);

    return 0;
}

ARCH_API int arch_apply_material_to_batch(const int* indices, int count, const char* material_name) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer) {
        setError("Renderer not initialized");
        return 0;
    }

    if (!indices || count <= 0) {
        setError("Invalid indices array");
        return 0;
    }

    if (!material_name) {
        setError("Invalid material name");
        return 0;
    }

    // Find material index
    int matIndex = arch_find_material(material_name);
    if (matIndex < 0) {
        setError("Material not found");
        return 0;
    }

    int updated = 0;
    for (int i = 0; i < count; i++) {
        int idx = indices[i];
        if (idx >= 0 && idx < static_cast<int>(g_building.elements.size())) {
            if (arch_apply_material_to_element(idx, material_name) == 0) {
                updated++;
            }
        }
    }

    return updated;
}

ARCH_API int arch_get_element_material_name(int element_index, char* out_name, int max_length) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_renderer) {
        setError("Renderer not initialized");
        return -1;
    }

    if (element_index < 0 || element_index >= static_cast<int>(g_building.elements.size())) {
        setError("Invalid element index");
        return -2;
    }

    if (!out_name || max_length <= 0) {
        setError("Invalid output buffer");
        return -3;
    }

    // Check if element has an override
    if (!g_renderer->hasElementOverride(element_index)) {
        // No override - return empty string
        out_name[0] = '\0';
        return -4;
    }

    // For now, return "custom" since we don't track which material was applied
    // TODO: Track applied material names in element metadata
    std::strncpy(out_name, "custom", max_length - 1);
    out_name[max_length - 1] = '\0';

    return 0;
}

} // extern "C" (temporarily close for C++ terrain helpers)

// =============================================================================
// Terrain Mesh API Implementation
// =============================================================================

// Global terrain state (C++ namespace, not exported)
namespace {
    // g_terrainEnabled is defined at top of file with other globals
    vec3 g_terrainOffset = {0.0f, 0.0f, 0.0f};
    float g_terrainRoughness = 0.8f;
    float g_terrainMetallic = 0.0f;
    int g_terrainColorMode = 0;  // 0=elevation gradient, 1=textured
    std::string g_terrainTextureName = "";  // Empty = use vertex colors, otherwise use material texture

    // Elevation color gradient (same as geometry_loader.cpp)
    vec3 getTerrainElevationColor(float normalizedElevation) {
        float t = glm::clamp(normalizedElevation, 0.0f, 1.0f);

        // Four-stop gradient: green -> tan -> gray -> white
        const vec3 lowGreen = vec3(0.34f, 0.55f, 0.30f);   // Low elevation - grass/forest
        const vec3 midTan = vec3(0.72f, 0.60f, 0.40f);     // Mid elevation - dirt/rock
        const vec3 highGray = vec3(0.55f, 0.55f, 0.55f);   // High elevation - bare rock
        const vec3 peakWhite = vec3(0.95f, 0.95f, 0.95f);  // Peak - snow

        if (t < 0.33f) {
            return glm::mix(lowGreen, midTan, t / 0.33f);
        } else if (t < 0.66f) {
            return glm::mix(midTan, highGray, (t - 0.33f) / 0.33f);
        } else {
            return glm::mix(highGray, peakWhite, (t - 0.66f) / 0.34f);
        }
    }
}

extern "C" {  // Re-open for C API functions

ARCH_API int arch_set_terrain_data(const ArchTerrainVertex* vertices, int vertex_count,
                                   const unsigned int* indices, int index_count,
                                   float width_ft, float depth_ft,
                                   float min_elevation, float max_elevation) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!vertices || vertex_count <= 0) {
        setError("Invalid vertices array");
        return -1;
    }

    if (!indices || index_count <= 0 || index_count % 3 != 0) {
        setError("Invalid indices array (must be multiple of 3)");
        return -2;
    }

    // Clear existing terrain
    g_building.terrainMesh.vertices.clear();
    g_building.terrainMesh.indices.clear();

    // Store metadata
    g_building.terrainMesh.width_ft = width_ft;
    g_building.terrainMesh.depth_ft = depth_ft;
    g_building.terrainMesh.min_elevation = min_elevation;
    g_building.terrainMesh.max_elevation = max_elevation;

    // Compute elevation range for color mapping
    float elevRange = max_elevation - min_elevation;
    if (elevRange < 0.001f) elevRange = 1.0f;  // Avoid division by zero

    // Convert vertices (keep in feet, same units as building elements)
    g_building.terrainMesh.vertices.reserve(vertex_count);

    for (int i = 0; i < vertex_count; i++) {
        const ArchTerrainVertex& src = vertices[i];
        Vertex vert{};

        // Position: keep in feet (same units as building elements)
        // API: X=east, Y=up(elevation), Z=north
        // Engine: X=east, Y=up, Z=south (flip Z)
        vert.position = vec3(
            src.pos_x,
            src.pos_y,   // Y is elevation (up)
            -src.pos_z   // Flip Z for south
        );

        // Apply offset (in feet)
        vert.position += vec3(
            g_terrainOffset.x,
            g_terrainOffset.y,
            -g_terrainOffset.z
        );

        // Normal (swap Y/Z, flip Z)
        vert.normal = glm::normalize(vec3(src.normal_x, src.normal_y, -src.normal_z));

        // UV
        vert.texCoord = vec2(src.u, src.v);

        // Compute color from elevation
        float normalizedElev = (src.pos_y - min_elevation) / elevRange;
        if (g_terrainColorMode == 0) {
            vert.color = getTerrainElevationColor(normalizedElev);
        } else {
            // Uniform gray
            vert.color = vec3(0.5f, 0.5f, 0.5f);
        }

        g_building.terrainMesh.vertices.push_back(vert);
    }

    // Copy indices
    g_building.terrainMesh.indices.reserve(index_count);
    for (int i = 0; i < index_count; i++) {
        g_building.terrainMesh.indices.push_back(indices[i]);
    }

    // Reset renderer's terrain cache to force rebuild
    if (g_renderer) {
        g_renderer->invalidateTerrainCache();
    }

    std::cout << "[Terrain API] Set terrain: " << vertex_count << " vertices, "
              << (index_count / 3) << " triangles, elevation " << min_elevation
              << "-" << max_elevation << " ft\n";

    return 0;
}

ARCH_API void arch_clear_terrain(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    g_building.terrainMesh.vertices.clear();
    g_building.terrainMesh.indices.clear();
    g_building.terrainMesh.width_ft = 0.0f;
    g_building.terrainMesh.depth_ft = 0.0f;
    g_building.terrainMesh.min_elevation = 0.0f;
    g_building.terrainMesh.max_elevation = 0.0f;

    if (g_renderer) {
        g_renderer->invalidateTerrainCache();
    }

    std::cout << "[Terrain API] Cleared terrain data\n";
}

ARCH_API int arch_has_terrain(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_building.terrainMesh.hasData() ? 1 : 0;
}

ARCH_API int arch_get_terrain_info(float* out_width_ft, float* out_depth_ft,
                                   float* out_min_elev, float* out_max_elev,
                                   int* out_vertex_count, int* out_triangle_count) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_building.terrainMesh.hasData()) {
        return -1;
    }

    if (out_width_ft) *out_width_ft = g_building.terrainMesh.width_ft;
    if (out_depth_ft) *out_depth_ft = g_building.terrainMesh.depth_ft;
    if (out_min_elev) *out_min_elev = g_building.terrainMesh.min_elevation;
    if (out_max_elev) *out_max_elev = g_building.terrainMesh.max_elevation;
    if (out_vertex_count) *out_vertex_count = static_cast<int>(g_building.terrainMesh.vertices.size());
    if (out_triangle_count) *out_triangle_count = static_cast<int>(g_building.terrainMesh.indices.size() / 3);

    return 0;
}

ARCH_API void arch_set_terrain_enabled(int enabled) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    g_terrainEnabled = (enabled != 0);
}

ARCH_API int arch_get_terrain_enabled(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_terrainEnabled ? 1 : 0;
}

ARCH_API void arch_set_terrain_offset(float offset_x, float offset_y, float offset_z) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    g_terrainOffset = vec3(offset_x, offset_y, offset_z);

    // If terrain exists, we need to rebuild it with the new offset
    // For now, just store the offset - a full rebuild would require re-calling set_terrain_data
    std::cout << "[Terrain API] Set offset: (" << offset_x << ", " << offset_y << ", " << offset_z << ") ft\n";
}

ARCH_API void arch_get_terrain_offset(float* out_x, float* out_y, float* out_z) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (out_x) *out_x = g_terrainOffset.x;
    if (out_y) *out_y = g_terrainOffset.y;
    if (out_z) *out_z = g_terrainOffset.z;
}

ARCH_API void arch_set_terrain_material(float roughness, float metallic) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    g_terrainRoughness = glm::clamp(roughness, 0.0f, 1.0f);
    g_terrainMetallic = glm::clamp(metallic, 0.0f, 1.0f);
}

ARCH_API void arch_set_terrain_color_mode(int mode) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    g_terrainColorMode = mode;
}

ARCH_API void arch_set_terrain_texture(const char* material_name) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (material_name && strlen(material_name) > 0) {
        g_terrainTextureName = material_name;
        g_terrainColorMode = 1;  // Switch to textured mode
        if (g_renderer) {
            g_renderer->setTerrainMaterial(material_name);
        }
        std::cout << "[Terrain API] Set texture: " << material_name << std::endl;
    } else {
        g_terrainTextureName = "";
        g_terrainColorMode = 0;  // Switch back to vertex color mode
        if (g_renderer) {
            g_renderer->setTerrainMaterial("");
        }
        std::cout << "[Terrain API] Cleared texture, using elevation colors" << std::endl;
    }
}

ARCH_API const char* arch_get_terrain_texture(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_terrainTextureName.c_str();
}

// =============================================================================
// High-Performance Terrain Generation
// =============================================================================

namespace {
    // Progress tracking for terrain generation
    std::atomic<float> g_terrainGenProgress{0.0f};
    std::string g_terrainGenStatus = "";

    // Point-in-polygon test (ray casting)
    bool pointInPolygon(float px, float pz, const std::vector<std::pair<float, float>>& poly) {
        if (poly.empty()) return true;  // No boundary = always inside

        bool inside = false;
        size_t n = poly.size();
        for (size_t i = 0, j = n - 1; i < n; j = i++) {
            float xi = poly[i].first, zi = poly[i].second;
            float xj = poly[j].first, zj = poly[j].second;

            if (((zi > pz) != (zj > pz)) &&
                (px < (xj - xi) * (pz - zi) / (zj - zi) + xi)) {
                inside = !inside;
            }
        }
        return inside;
    }

    // KD-tree-like spatial index for fast nearest neighbor
    struct ElevationIndex {
        struct Point {
            float lat, lng, elev;
        };
        std::vector<Point> points;
        float latMin, latMax, lngMin, lngMax;

        void build(const ArchElevationPoint* pts, int count,
                   float latMin_, float latMax_, float lngMin_, float lngMax_) {
            latMin = latMin_; latMax = latMax_;
            lngMin = lngMin_; lngMax = lngMax_;
            points.resize(count);
            for (int i = 0; i < count; i++) {
                points[i] = {pts[i].lat, pts[i].lng, pts[i].elevation_m};
            }
        }

        // Find nearest elevation using simple grid search (fast enough for this use case)
        float findNearest(float lat, float lng) const {
            if (points.empty()) return 0.0f;

            float bestDist = std::numeric_limits<float>::max();
            float bestElev = points[0].elev;

            // For large point sets, we could use a spatial hash here
            // For now, linear search works for up to ~1M points
            for (const auto& p : points) {
                float dlat = p.lat - lat;
                float dlng = p.lng - lng;
                float dist = dlat * dlat + dlng * dlng;
                if (dist < bestDist) {
                    bestDist = dist;
                    bestElev = p.elev;
                }
            }
            return bestElev;
        }

        // Inverse distance weighted interpolation from K nearest
        float interpolate(float lat, float lng, int k = 4) const {
            if (points.empty()) return 0.0f;
            if (points.size() == 1) return points[0].elev;

            // Find k nearest points
            struct Neighbor { float dist; float elev; };
            std::vector<Neighbor> neighbors;
            neighbors.reserve(k);

            for (const auto& p : points) {
                float dlat = p.lat - lat;
                float dlng = p.lng - lng;
                float dist = std::sqrt(dlat * dlat + dlng * dlng);

                if (dist < 1e-9f) return p.elev;  // Exact match

                if (neighbors.size() < static_cast<size_t>(k)) {
                    neighbors.push_back({dist, p.elev});
                    std::push_heap(neighbors.begin(), neighbors.end(),
                        [](const Neighbor& a, const Neighbor& b) { return a.dist < b.dist; });
                } else if (dist < neighbors[0].dist) {
                    std::pop_heap(neighbors.begin(), neighbors.end(),
                        [](const Neighbor& a, const Neighbor& b) { return a.dist < b.dist; });
                    neighbors.back() = {dist, p.elev};
                    std::push_heap(neighbors.begin(), neighbors.end(),
                        [](const Neighbor& a, const Neighbor& b) { return a.dist < b.dist; });
                }
            }

            // Inverse distance weighting
            float sumWeights = 0.0f;
            float sumElev = 0.0f;
            for (const auto& n : neighbors) {
                float w = 1.0f / (n.dist * n.dist);  // IDW with power 2
                sumWeights += w;
                sumElev += w * n.elev;
            }
            return sumElev / sumWeights;
        }
    };
}

ARCH_API int arch_generate_terrain_from_points(
    const ArchElevationPoint* points,
    int point_count,
    const float* boundary_ft,
    int boundary_vertex_count,
    float bounds_lat_min, float bounds_lat_max,
    float bounds_lng_min, float bounds_lng_max,
    float width_ft, float depth_ft,
    int grid_resolution,
    float origin_x_ft, float origin_z_ft,
    float rotation_deg
) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!points || point_count <= 0) {
        setError("No elevation points provided");
        return -1;
    }

    if (grid_resolution < 10 || grid_resolution > 2000) {
        setError("Grid resolution must be between 10 and 2000");
        return -2;
    }

    std::cout << "[TerrainGen] Starting C++ terrain generation..." << std::endl;
    std::cout << "[TerrainGen] Input: " << point_count << " elevation points" << std::endl;
    std::cout << "[TerrainGen] Grid: " << grid_resolution << "x" << grid_resolution
              << " (~" << (2 * grid_resolution * grid_resolution) << " triangles)" << std::endl;
    std::cout << "[TerrainGen] Property: " << width_ft << "ft x " << depth_ft << "ft" << std::endl;
    std::cout << "[TerrainGen] Lat bounds: [" << bounds_lat_min << ", " << bounds_lat_max << "]" << std::endl;
    std::cout << "[TerrainGen] Lng bounds: [" << bounds_lng_min << ", " << bounds_lng_max << "]" << std::endl;
    std::cout << "[TerrainGen] Origin: (" << origin_x_ft << ", " << origin_z_ft << ") ft, rotation: " << rotation_deg << " deg" << std::endl;

    // Debug: verify first few elevation points
    std::cout << "[TerrainGen] First 5 elevation points received:" << std::endl;
    for (int i = 0; i < std::min(5, point_count); i++) {
        std::cout << "[TerrainGen]   [" << i << "] lat=" << points[i].lat
                  << ", lng=" << points[i].lng
                  << ", elev=" << points[i].elevation_m << "m" << std::endl;
    }

    g_terrainGenProgress = 0.0f;
    g_terrainGenStatus = "Building spatial index...";

    auto startTime = std::chrono::high_resolution_clock::now();

    // Build spatial index for fast elevation lookup
    ElevationIndex elevIndex;
    elevIndex.build(points, point_count, bounds_lat_min, bounds_lat_max,
                    bounds_lng_min, bounds_lng_max);

    // Check actual elevation point ranges
    float ptLatMin = points[0].lat, ptLatMax = points[0].lat;
    float ptLngMin = points[0].lng, ptLngMax = points[0].lng;
    for (int i = 0; i < point_count; i++) {
        ptLatMin = std::min(ptLatMin, points[i].lat);
        ptLatMax = std::max(ptLatMax, points[i].lat);
        ptLngMin = std::min(ptLngMin, points[i].lng);
        ptLngMax = std::max(ptLngMax, points[i].lng);
    }
    std::cout << "[TerrainGen] Actual elevation point ranges:" << std::endl;
    std::cout << "[TerrainGen]   Lat: [" << ptLatMin << ", " << ptLatMax << "]" << std::endl;
    std::cout << "[TerrainGen]   Lng: [" << ptLngMin << ", " << ptLngMax << "]" << std::endl;
    if (std::abs(ptLatMin - bounds_lat_min) > 0.0001f || std::abs(ptLatMax - bounds_lat_max) > 0.0001f ||
        std::abs(ptLngMin - bounds_lng_min) > 0.0001f || std::abs(ptLngMax - bounds_lng_max) > 0.0001f) {
        std::cout << "[TerrainGen] WARNING: Elevation point range differs from provided bounds!" << std::endl;
    }

    // Find elevation range
    float minElev = std::numeric_limits<float>::max();
    float maxElev = std::numeric_limits<float>::lowest();
    for (int i = 0; i < point_count; i++) {
        minElev = std::min(minElev, points[i].elevation_m);
        maxElev = std::max(maxElev, points[i].elevation_m);
    }
    float elevRange = maxElev - minElev;
    if (elevRange < 0.001f) elevRange = 1.0f;

    std::cout << "[TerrainGen] Elevation: " << minElev << "m to " << maxElev << "m (range: "
              << elevRange << "m / " << (elevRange * 3.28084f) << "ft)" << std::endl;

    g_terrainGenProgress = 0.1f;
    g_terrainGenStatus = "Generating grid vertices...";

    // Parse boundary polygon (convert from feet to mm)
    std::vector<std::pair<float, float>> boundary;
    if (boundary_ft && boundary_vertex_count >= 3) {
        std::cout << "[TerrainGen] Boundary polygon: " << boundary_vertex_count << " vertices" << std::endl;
        for (int i = 0; i < boundary_vertex_count; i++) {
            // Convert from feet to mm
            float x_mm = boundary_ft[i * 2] * 304.8f;
            float z_mm = boundary_ft[i * 2 + 1] * 304.8f;
            boundary.push_back({x_mm, z_mm});
        }
    }

    // All coordinates are in mm from here on
    // Grid spans the property size, centered at origin
    float widthMm = width_ft * 304.8f;
    float depthMm = depth_ft * 304.8f;
    float minX = 0.0f;
    float maxX = widthMm;
    float minZ = 0.0f;
    float maxZ = depthMm;

    // If boundary polygon is provided, use its bounding box instead
    if (!boundary.empty()) {
        minX = maxX = boundary[0].first;
        minZ = maxZ = boundary[0].second;
        for (const auto& v : boundary) {
            minX = std::min(minX, v.first);
            maxX = std::max(maxX, v.first);
            minZ = std::min(minZ, v.second);
            maxZ = std::max(maxZ, v.second);
        }
        widthMm = maxX - minX;
        depthMm = maxZ - minZ;
    }

    std::cout << "[TerrainGen] Grid extents (mm): [" << minX << ", " << maxX << "] x [" << minZ << ", " << maxZ << "]" << std::endl;
    std::cout << "[TerrainGen] Grid size: " << widthMm << " x " << depthMm << " mm" << std::endl;
    float stepX = widthMm / grid_resolution;
    float stepZ = depthMm / grid_resolution;

    // Lat/lng range for coordinate mapping
    float latRange = bounds_lat_max - bounds_lat_min;
    float lngRange = bounds_lng_max - bounds_lng_min;
    std::cout << "[TerrainGen] Lat range: " << latRange << " deg, Lng range: " << lngRange << " deg" << std::endl;

    // Debug: show corner mappings
    std::cout << "[TerrainGen] Corner coord mapping:" << std::endl;
    std::cout << "[TerrainGen]   Grid (0,0) -> lat=" << bounds_lat_min << ", lng=" << bounds_lng_min << std::endl;
    std::cout << "[TerrainGen]   Grid (1,0) -> lat=" << bounds_lat_min << ", lng=" << bounds_lng_max << std::endl;
    std::cout << "[TerrainGen]   Grid (0,1) -> lat=" << bounds_lat_max << ", lng=" << bounds_lng_min << std::endl;
    std::cout << "[TerrainGen]   Grid (1,1) -> lat=" << bounds_lat_max << ", lng=" << bounds_lng_max << std::endl;

    // NOTE: rotation_deg is not used for terrain (terrain doesn't rotate)
    // But origin_x/z_ft IS used to sample terrain elevation at building position
    (void)rotation_deg;
    float buildingOriginXmm = origin_x_ft * 304.8f;
    float buildingOriginZmm = origin_z_ft * 304.8f;

    // Elevation offset so lowest point is at Y=0
    float elevOffsetM = -minElev - 0.01f;  // Slight offset below ground

    // Generate grid vertices (using Vertex type from types.hpp)
    std::vector<Vertex> vertices;
    std::vector<u32> indices;
    std::vector<std::tuple<int, int, int>> gridPoints;  // (gridX, gridZ, vertexIndex)

    vertices.reserve((grid_resolution + 1) * (grid_resolution + 1));

    for (int iz = 0; iz <= grid_resolution; iz++) {
        if (iz % 50 == 0) {
            g_terrainGenProgress = 0.1f + 0.6f * (float(iz) / grid_resolution);
        }

        for (int ix = 0; ix <= grid_resolution; ix++) {
            float px = minX + ix * stepX;
            float pz = minZ + iz * stepZ;

            // Check if inside boundary polygon
            if (!boundary.empty() && !pointInPolygon(px, pz, boundary)) {
                continue;
            }

            // Map local coords to lat/lng
            float fracX = (widthMm > 0) ? (px - minX) / widthMm : 0;
            float fracZ = (depthMm > 0) ? (pz - minZ) / depthMm : 0;
            float lat = bounds_lat_min + fracZ * latRange;
            float lng = bounds_lng_min + fracX * lngRange;

            // Get interpolated elevation
            float elevM = elevIndex.interpolate(lat, lng, 4);
            float elevMm = (elevM + elevOffsetM) * 1000.0f;  // Convert m to mm

            // Terrain stays in world coordinates (0 to width, 0 to depth)
            // Building is rotated by QBD, but terrain (real-world ground) does NOT rotate
            float x = px;
            float z = pz;

            // NOTE: We intentionally do NOT rotate terrain - only the building rotates
            // The terrain represents the actual ground which stays fixed
            // The building is rotated by QBD to match user's placement orientation

            // UV coordinates
            float u = float(ix) / grid_resolution;
            float v = float(iz) / grid_resolution;

            int vertIdx = static_cast<int>(vertices.size());
            Vertex vert;
            vert.position = vec3(x, elevMm, z);
            vert.normal = vec3(0, 1, 0);  // Computed later
            vert.color = vec3(1, 1, 1);   // Computed later
            vert.texCoord = vec2(u, v);
            vert.stress = 0.0f;
            vertices.push_back(vert);
            gridPoints.push_back({ix, iz, vertIdx});
        }
    }

    if (vertices.size() < 3) {
        setError("Not enough vertices inside boundary");
        return -3;
    }

    // Debug: show vertex position range
    if (!vertices.empty()) {
        float vMinX = vertices[0].position.x, vMaxX = vertices[0].position.x;
        float vMinY = vertices[0].position.y, vMaxY = vertices[0].position.y;
        float vMinZ = vertices[0].position.z, vMaxZ = vertices[0].position.z;
        for (const auto& v : vertices) {
            vMinX = std::min(vMinX, v.position.x);
            vMaxX = std::max(vMaxX, v.position.x);
            vMinY = std::min(vMinY, v.position.y);
            vMaxY = std::max(vMaxY, v.position.y);
            vMinZ = std::min(vMinZ, v.position.z);
            vMaxZ = std::max(vMaxZ, v.position.z);
        }
        std::cout << "[TerrainGen] Vertex bounds (mm):" << std::endl;
        std::cout << "[TerrainGen]   X: [" << vMinX << ", " << vMaxX << "] (" << (vMaxX-vMinX)/304.8f << " ft)" << std::endl;
        std::cout << "[TerrainGen]   Y: [" << vMinY << ", " << vMaxY << "] (elev range: " << (vMaxY-vMinY)/1000.0f << " m)" << std::endl;
        std::cout << "[TerrainGen]   Z: [" << vMinZ << ", " << vMaxZ << "] (" << (vMaxZ-vMinZ)/304.8f << " ft)" << std::endl;
    }

    g_terrainGenProgress = 0.7f;
    g_terrainGenStatus = "Building triangles...";

    // Build lookup map for grid connectivity
    std::map<std::pair<int, int>, int> gridMap;
    for (const auto& gp : gridPoints) {
        gridMap[{std::get<0>(gp), std::get<1>(gp)}] = std::get<2>(gp);
    }

    // Generate triangles
    indices.reserve(grid_resolution * grid_resolution * 6);
    for (const auto& gp : gridPoints) {
        int ix = std::get<0>(gp);
        int iz = std::get<1>(gp);
        int idx = std::get<2>(gp);

        auto right = gridMap.find({ix + 1, iz});
        auto bottom = gridMap.find({ix, iz + 1});
        auto diag = gridMap.find({ix + 1, iz + 1});

        if (right != gridMap.end() && bottom != gridMap.end()) {
            if (diag != gridMap.end()) {
                // Two triangles for quad
                indices.push_back(idx);
                indices.push_back(bottom->second);
                indices.push_back(right->second);

                indices.push_back(right->second);
                indices.push_back(bottom->second);
                indices.push_back(diag->second);
            } else {
                // Single triangle
                indices.push_back(idx);
                indices.push_back(bottom->second);
                indices.push_back(right->second);
            }
        }
    }

    g_terrainGenProgress = 0.85f;
    g_terrainGenStatus = "Computing normals and colors...";

    // Compute normals using finite differences
    for (auto& gp : gridPoints) {
        int ix = std::get<0>(gp);
        int iz = std::get<1>(gp);
        int idx = std::get<2>(gp);

        Vertex& v = vertices[idx];

        // Get neighbor heights
        auto left = gridMap.find({ix - 1, iz});
        auto right = gridMap.find({ix + 1, iz});
        auto up = gridMap.find({ix, iz - 1});
        auto down = gridMap.find({ix, iz + 1});

        float hL = (left != gridMap.end()) ? vertices[left->second].position.y : v.position.y;
        float hR = (right != gridMap.end()) ? vertices[right->second].position.y : v.position.y;
        float hU = (up != gridMap.end()) ? vertices[up->second].position.y : v.position.y;
        float hD = (down != gridMap.end()) ? vertices[down->second].position.y : v.position.y;

        // Normal from height gradient
        float nx = (hL - hR) / (2.0f * stepX);
        float nz = (hU - hD) / (2.0f * stepZ);
        float ny = 1.0f;
        float len = std::sqrt(nx * nx + ny * ny + nz * nz);
        if (len > 0.0001f) {
            v.normal = vec3(nx / len, ny / len, nz / len);
        }

        // Elevation-based color (green to brown gradient)
        float t = (v.position.y - vertices[0].position.y) / (elevRange * 1000.0f + 1.0f);
        t = std::clamp(t, 0.0f, 1.0f);
        // Low = green (0.3, 0.5, 0.2), High = brown (0.6, 0.4, 0.25)
        v.color = vec3(
            0.3f + t * 0.3f,
            0.5f - t * 0.1f,
            0.2f + t * 0.05f
        );
    }

    g_terrainGenProgress = 0.95f;
    g_terrainGenStatus = "Storing terrain data...";

    // Store in global building terrain mesh
    // The renderer will auto-upload on next render when it detects changed data
    g_building.terrainMesh.vertices = std::move(vertices);
    g_building.terrainMesh.indices = std::move(indices);
    g_building.terrainMesh.width_ft = width_ft;
    g_building.terrainMesh.depth_ft = depth_ft;
    g_building.terrainMesh.min_elevation = minElev * 3.28084f;  // Convert to feet
    g_building.terrainMesh.max_elevation = maxElev * 3.28084f;

    auto endTime = std::chrono::high_resolution_clock::now();
    auto durationMs = std::chrono::duration_cast<std::chrono::milliseconds>(endTime - startTime).count();

    g_terrainGenProgress = 1.0f;
    g_terrainGenStatus = "Complete";

    std::cout << "[TerrainGen] Complete: " << g_building.terrainMesh.vertices.size()
              << " vertices, " << (g_building.terrainMesh.indices.size() / 3)
              << " triangles in " << durationMs << "ms" << std::endl;

    // Debug: Compare terrain bounds with building bounds to check alignment
    // NOTE: At this point terrain is in mm, building is already in feet (scaled by arch_load_json)
    {
        // Terrain bounds in mm (will convert to feet for comparison)
        float terrainMinXmm = 1e9f, terrainMaxXmm = -1e9f;
        float terrainMinZmm = 1e9f, terrainMaxZmm = -1e9f;
        for (const auto& v : g_building.terrainMesh.vertices) {
            terrainMinXmm = std::min(terrainMinXmm, v.position.x);
            terrainMaxXmm = std::max(terrainMaxXmm, v.position.x);
            terrainMinZmm = std::min(terrainMinZmm, v.position.z);
            terrainMaxZmm = std::max(terrainMaxZmm, v.position.z);
        }

        // Convert terrain bounds to feet for proper comparison
        float terrainMinXft = terrainMinXmm / 304.8f;
        float terrainMaxXft = terrainMaxXmm / 304.8f;
        float terrainMinZft = terrainMinZmm / 304.8f;
        float terrainMaxZft = terrainMaxZmm / 304.8f;

        // Building bounds are already in feet
        float buildingMinXft = 1e9f, buildingMaxXft = -1e9f;
        float buildingMinZft = 1e9f, buildingMaxZft = -1e9f;
        for (const auto& elem : g_building.elements) {
            for (const auto& v : elem.mesh.vertices) {
                buildingMinXft = std::min(buildingMinXft, v.x);
                buildingMaxXft = std::max(buildingMaxXft, v.x);
                buildingMinZft = std::min(buildingMinZft, v.z);
                buildingMaxZft = std::max(buildingMaxZft, v.z);
            }
        }

        // Building origin in feet (convert from mm)
        float buildingOriginXft = buildingOriginXmm / 304.8f;
        float buildingOriginZft = buildingOriginZmm / 304.8f;

        std::cout << "\n[ALIGNMENT CHECK] (all values in feet)" << std::endl;
        std::cout << "  Terrain X: [" << terrainMinXft << ", " << terrainMaxXft << "] ft" << std::endl;
        std::cout << "  Terrain Z: [" << terrainMinZft << ", " << terrainMaxZft << "] ft" << std::endl;
        std::cout << "  Building X: [" << buildingMinXft << ", " << buildingMaxXft << "] ft" << std::endl;
        std::cout << "  Building Z: [" << buildingMinZft << ", " << buildingMaxZft << "] ft" << std::endl;
        std::cout << "  Building Origin: (" << buildingOriginXft << ", " << buildingOriginZft << ") ft" << std::endl;

        // Check if building is inside terrain bounds (all in feet)
        bool originInsideTerrain = (buildingOriginXft >= terrainMinXft && buildingOriginXft <= terrainMaxXft &&
                                    buildingOriginZft >= terrainMinZft && buildingOriginZft <= terrainMaxZft);
        bool buildingOverlapsTerrain = (buildingMaxXft >= terrainMinXft && buildingMinXft <= terrainMaxXft &&
                                        buildingMaxZft >= terrainMinZft && buildingMinZft <= terrainMaxZft);

        std::cout << "  Building origin inside terrain: " << (originInsideTerrain ? "YES" : "NO") << std::endl;
        std::cout << "  Building overlaps terrain: " << (buildingOverlapsTerrain ? "YES" : "NO") << std::endl;

        if (!buildingOverlapsTerrain) {
            std::cout << "  [!] WARNING: Building and terrain DO NOT OVERLAP!" << std::endl;
            std::cout << "  [!] This explains why they appear far apart in the viewport." << std::endl;
        }
        std::cout << std::endl;
    }


    // Sample terrain elevation at building origin and lift building to sit on terrain
    // The building was loaded at Y=0, but the terrain at that XZ position may be higher
    float buildingElevMm = 0.0f;

    // Find the terrain elevation at the building origin position by interpolating nearby vertices
    float searchRadius = 5000.0f;  // 5m search radius
    float totalWeight = 0.0f;

    for (const auto& v : g_building.terrainMesh.vertices) {
        float dx = v.position.x - buildingOriginXmm;
        float dz = v.position.z - buildingOriginZmm;
        float dist = std::sqrt(dx * dx + dz * dz);

        if (dist < searchRadius) {
            float weight = 1.0f / (dist + 1.0f);  // Inverse distance weighting
            buildingElevMm += v.position.y * weight;
            totalWeight += weight;
        }
    }

    if (totalWeight > 0.0f) {
        buildingElevMm = buildingElevMm / totalWeight;
        std::cout << "[TerrainGen] Terrain elevation at building origin: " << buildingElevMm << " mm ("
                  << (buildingElevMm / 304.8f) << " ft)" << std::endl;

        // Convert elevation to feet (building elements are already in feet from arch_load_json)
        float buildingElevFt = buildingElevMm / 304.8f;

        // Offset building elements to sit on terrain (in feet)
        // Lift elements based on their current Y position:
        // - Y ≈ 0: Floors/walls at ground level, need full lift
        // - Y ≈ 9ft (wall height): Roofs at wall top, need full lift
        // - Y > 20ft: Already lifted elements, skip
        int liftedCount = 0;
        int skippedCount = 0;
        int roofCount = 0;
        float minRoofY = 1e9f, maxRoofY = -1e9f;
        for (auto& elem : g_building.elements) {
            // Track roof Y range for debugging
            if (elem.type == ElementType::Roof) {
                roofCount++;
                minRoofY = std::min(minRoofY, elem.start.y);
                maxRoofY = std::max(maxRoofY, elem.end.y);
            }

            // Determine if element needs lifting
            // Walls/roofs on first load: start.y is 0 or wall height (~9ft)
            // Elements after lift: start.y > 20ft (terrain lift + wall height)
            bool needsLift = false;
            if (elem.start.y <= 15.0f) {
                // Ground level elements (floors, walls at Y=0) or roofs at wall height (~9ft)
                needsLift = true;
            }
            // else: Already lifted (start.y > 15ft), skip

            if (!needsLift) {
                skippedCount++;
                continue;
            }

            elem.start.y += buildingElevFt;
            elem.end.y += buildingElevFt;
            for (auto& v : elem.mesh.vertices) {
                v.y += buildingElevFt;
            }
            liftedCount++;
        }

        // Offset parametric walls (in feet)
        for (auto& pw : g_building.parametricWalls) {
            // Only lift if not already lifted (baseHeight <= 15ft)
            if (pw.baseHeight <= 15.0f) {
                pw.baseHeight += buildingElevFt;
                pw.topHeight += buildingElevFt;
            }
        }

        std::cout << "[TerrainGen] Lifted " << liftedCount << " elements, skipped " << skippedCount << " already-lifted" << std::endl;
        if (roofCount > 0) {
            std::cout << "[TerrainGen] Roof Y range: [" << minRoofY << ", " << maxRoofY << "] ft" << std::endl;
        }

        std::cout << "[TerrainGen] Building lifted by " << buildingElevFt << " ft to sit on terrain" << std::endl;
    } else {
        std::cout << "[TerrainGen] WARNING: Could not sample terrain at building origin ("
                  << buildingOriginXmm << ", " << buildingOriginZmm << ")" << std::endl;
    }

    // Debug: Show terrain bounds BEFORE scaling
    {
        float minX = 1e9f, maxX = -1e9f, minZ = 1e9f, maxZ = -1e9f;
        for (const auto& v : g_building.terrainMesh.vertices) {
            minX = std::min(minX, v.position.x);
            maxX = std::max(maxX, v.position.x);
            minZ = std::min(minZ, v.position.z);
            maxZ = std::max(maxZ, v.position.z);
        }
        std::cout << "[TerrainGen] BEFORE scaling - Terrain bounds:" << std::endl;
        std::cout << "[TerrainGen]   X: [" << minX << ", " << maxX << "] (should be mm)" << std::endl;
        std::cout << "[TerrainGen]   Z: [" << minZ << ", " << maxZ << "] (should be mm)" << std::endl;
        std::cout << "[TerrainGen]   Width: " << (maxX - minX) << ", Depth: " << (maxZ - minZ) << std::endl;
    }

    // Scale terrain vertices from mm to feet (building elements are in feet)
    const float mmToFeet = 1.0f / 304.8f;
    for (auto& vert : g_building.terrainMesh.vertices) {
        vert.position *= mmToFeet;
    }

    // Debug: Show terrain bounds AFTER scaling
    {
        float minX = 1e9f, maxX = -1e9f, minZ = 1e9f, maxZ = -1e9f;
        for (const auto& v : g_building.terrainMesh.vertices) {
            minX = std::min(minX, v.position.x);
            maxX = std::max(maxX, v.position.x);
            minZ = std::min(minZ, v.position.z);
            maxZ = std::max(maxZ, v.position.z);
        }
        std::cout << "[TerrainGen] AFTER scaling - Terrain bounds:" << std::endl;
        std::cout << "[TerrainGen]   X: [" << minX << ", " << maxX << "] ft" << std::endl;
        std::cout << "[TerrainGen]   Z: [" << minZ << ", " << maxZ << "] ft" << std::endl;
        std::cout << "[TerrainGen]   Width: " << (maxX - minX) << " ft, Depth: " << (maxZ - minZ) << " ft" << std::endl;
    }

    // Also show building bounds for comparison
    {
        float minX = 1e9f, maxX = -1e9f, minZ = 1e9f, maxZ = -1e9f;
        for (const auto& elem : g_building.elements) {
            for (const auto& v : elem.mesh.vertices) {
                minX = std::min(minX, v.x);
                maxX = std::max(maxX, v.x);
                minZ = std::min(minZ, v.z);
                maxZ = std::max(maxZ, v.z);
            }
        }
        std::cout << "[TerrainGen] Building bounds (should be feet):" << std::endl;
        std::cout << "[TerrainGen]   X: [" << minX << ", " << maxX << "] ft" << std::endl;
        std::cout << "[TerrainGen]   Z: [" << minZ << ", " << maxZ << "] ft" << std::endl;
    }

    // Add 3D North Arrow to terrain mesh
    // Arrow positioned at SW corner, pointing north (+Z direction)
    {
        // Get terrain bounds (already in feet)
        float tMinX = 1e9f, tMaxX = -1e9f, tMinZ = 1e9f, tMaxZ = -1e9f;
        float avgY = 0.0f;
        for (const auto& v : g_building.terrainMesh.vertices) {
            tMinX = std::min(tMinX, v.position.x);
            tMaxX = std::max(tMaxX, v.position.x);
            tMinZ = std::min(tMinZ, v.position.z);
            tMaxZ = std::max(tMaxZ, v.position.z);
            avgY += v.position.y;
        }
        if (!g_building.terrainMesh.vertices.empty()) {
            avgY /= g_building.terrainMesh.vertices.size();
        }

        // Arrow dimensions (in feet)
        float arrowLength = std::min(tMaxX - tMinX, tMaxZ - tMinZ) * 0.15f;  // 15% of smaller dimension
        float arrowWidth = arrowLength * 0.1f;   // Stem width
        float arrowHeadWidth = arrowLength * 0.25f;  // Head width
        float arrowHeadLength = arrowLength * 0.3f;  // Head length
        float arrowHeight = 2.0f;  // 2 feet above terrain

        // Position at SW corner with some offset
        float baseX = tMinX + arrowLength * 0.5f;
        float baseZ = tMinZ + arrowLength * 0.5f;
        float baseY = avgY + arrowHeight;

        // North arrow color (red)
        vec3 arrowColor(0.9f, 0.1f, 0.1f);

        // Create arrow vertices
        u32 baseIdx = static_cast<u32>(g_building.terrainMesh.vertices.size());

        // Arrow stem (rectangle pointing +Z)
        float stemLength = arrowLength - arrowHeadLength;

        // Stem vertices (4 corners of rectangle)
        Vertex v0, v1, v2, v3;
        v0.position = vec3(baseX - arrowWidth/2, baseY, baseZ);
        v0.normal = vec3(0, 1, 0);
        v0.color = arrowColor;
        v0.texCoord = vec2(0, 0);

        v1.position = vec3(baseX + arrowWidth/2, baseY, baseZ);
        v1.normal = vec3(0, 1, 0);
        v1.color = arrowColor;
        v1.texCoord = vec2(1, 0);

        v2.position = vec3(baseX + arrowWidth/2, baseY, baseZ + stemLength);
        v2.normal = vec3(0, 1, 0);
        v2.color = arrowColor;
        v2.texCoord = vec2(1, 1);

        v3.position = vec3(baseX - arrowWidth/2, baseY, baseZ + stemLength);
        v3.normal = vec3(0, 1, 0);
        v3.color = arrowColor;
        v3.texCoord = vec2(0, 1);

        g_building.terrainMesh.vertices.push_back(v0);
        g_building.terrainMesh.vertices.push_back(v1);
        g_building.terrainMesh.vertices.push_back(v2);
        g_building.terrainMesh.vertices.push_back(v3);

        // Stem triangles
        g_building.terrainMesh.indices.push_back(baseIdx + 0);
        g_building.terrainMesh.indices.push_back(baseIdx + 1);
        g_building.terrainMesh.indices.push_back(baseIdx + 2);
        g_building.terrainMesh.indices.push_back(baseIdx + 0);
        g_building.terrainMesh.indices.push_back(baseIdx + 2);
        g_building.terrainMesh.indices.push_back(baseIdx + 3);

        // Arrow head (triangle)
        u32 headBaseIdx = static_cast<u32>(g_building.terrainMesh.vertices.size());

        Vertex h0, h1, h2;
        // Left corner of head base
        h0.position = vec3(baseX - arrowHeadWidth/2, baseY, baseZ + stemLength);
        h0.normal = vec3(0, 1, 0);
        h0.color = arrowColor;
        h0.texCoord = vec2(0, 0);

        // Right corner of head base
        h1.position = vec3(baseX + arrowHeadWidth/2, baseY, baseZ + stemLength);
        h1.normal = vec3(0, 1, 0);
        h1.color = arrowColor;
        h1.texCoord = vec2(1, 0);

        // Tip of arrow (north)
        h2.position = vec3(baseX, baseY, baseZ + arrowLength);
        h2.normal = vec3(0, 1, 0);
        h2.color = arrowColor;
        h2.texCoord = vec2(0.5f, 1);

        g_building.terrainMesh.vertices.push_back(h0);
        g_building.terrainMesh.vertices.push_back(h1);
        g_building.terrainMesh.vertices.push_back(h2);

        // Arrow head triangle
        g_building.terrainMesh.indices.push_back(headBaseIdx + 0);
        g_building.terrainMesh.indices.push_back(headBaseIdx + 1);
        g_building.terrainMesh.indices.push_back(headBaseIdx + 2);

        // Add "N" label vertices (simple N shape made of lines/quads)
        // Position N just beyond the arrow tip
        float nBaseZ = baseZ + arrowLength + arrowWidth;
        float nHeight = arrowHeadWidth * 0.8f;
        float nWidth = arrowHeadWidth * 0.6f;
        float nThickness = arrowWidth * 0.5f;

        u32 nBaseIdx = static_cast<u32>(g_building.terrainMesh.vertices.size());

        // N is made of 3 vertical strokes: left |, diagonal \, right |
        // Left vertical bar
        Vertex n0, n1, n2, n3;
        n0.position = vec3(baseX - nWidth/2, baseY, nBaseZ);
        n0.normal = vec3(0, 1, 0); n0.color = arrowColor; n0.texCoord = vec2(0, 0);

        n1.position = vec3(baseX - nWidth/2 + nThickness, baseY, nBaseZ);
        n1.normal = vec3(0, 1, 0); n1.color = arrowColor; n1.texCoord = vec2(1, 0);

        n2.position = vec3(baseX - nWidth/2 + nThickness, baseY, nBaseZ + nHeight);
        n2.normal = vec3(0, 1, 0); n2.color = arrowColor; n2.texCoord = vec2(1, 1);

        n3.position = vec3(baseX - nWidth/2, baseY, nBaseZ + nHeight);
        n3.normal = vec3(0, 1, 0); n3.color = arrowColor; n3.texCoord = vec2(0, 1);

        g_building.terrainMesh.vertices.push_back(n0);
        g_building.terrainMesh.vertices.push_back(n1);
        g_building.terrainMesh.vertices.push_back(n2);
        g_building.terrainMesh.vertices.push_back(n3);

        g_building.terrainMesh.indices.push_back(nBaseIdx + 0);
        g_building.terrainMesh.indices.push_back(nBaseIdx + 1);
        g_building.terrainMesh.indices.push_back(nBaseIdx + 2);
        g_building.terrainMesh.indices.push_back(nBaseIdx + 0);
        g_building.terrainMesh.indices.push_back(nBaseIdx + 2);
        g_building.terrainMesh.indices.push_back(nBaseIdx + 3);

        // Right vertical bar
        u32 n2BaseIdx = static_cast<u32>(g_building.terrainMesh.vertices.size());
        Vertex n4, n5, n6, n7;
        n4.position = vec3(baseX + nWidth/2 - nThickness, baseY, nBaseZ);
        n4.normal = vec3(0, 1, 0); n4.color = arrowColor; n4.texCoord = vec2(0, 0);

        n5.position = vec3(baseX + nWidth/2, baseY, nBaseZ);
        n5.normal = vec3(0, 1, 0); n5.color = arrowColor; n5.texCoord = vec2(1, 0);

        n6.position = vec3(baseX + nWidth/2, baseY, nBaseZ + nHeight);
        n6.normal = vec3(0, 1, 0); n6.color = arrowColor; n6.texCoord = vec2(1, 1);

        n7.position = vec3(baseX + nWidth/2 - nThickness, baseY, nBaseZ + nHeight);
        n7.normal = vec3(0, 1, 0); n7.color = arrowColor; n7.texCoord = vec2(0, 1);

        g_building.terrainMesh.vertices.push_back(n4);
        g_building.terrainMesh.vertices.push_back(n5);
        g_building.terrainMesh.vertices.push_back(n6);
        g_building.terrainMesh.vertices.push_back(n7);

        g_building.terrainMesh.indices.push_back(n2BaseIdx + 0);
        g_building.terrainMesh.indices.push_back(n2BaseIdx + 1);
        g_building.terrainMesh.indices.push_back(n2BaseIdx + 2);
        g_building.terrainMesh.indices.push_back(n2BaseIdx + 0);
        g_building.terrainMesh.indices.push_back(n2BaseIdx + 2);
        g_building.terrainMesh.indices.push_back(n2BaseIdx + 3);

        // Diagonal bar (connecting top-left to bottom-right)
        u32 n3BaseIdx = static_cast<u32>(g_building.terrainMesh.vertices.size());
        Vertex d0, d1, d2, d3;
        d0.position = vec3(baseX - nWidth/2, baseY, nBaseZ + nHeight - nThickness);
        d0.normal = vec3(0, 1, 0); d0.color = arrowColor; d0.texCoord = vec2(0, 0);

        d1.position = vec3(baseX - nWidth/2 + nThickness, baseY, nBaseZ + nHeight);
        d1.normal = vec3(0, 1, 0); d1.color = arrowColor; d1.texCoord = vec2(1, 0);

        d2.position = vec3(baseX + nWidth/2, baseY, nBaseZ + nThickness);
        d2.normal = vec3(0, 1, 0); d2.color = arrowColor; d2.texCoord = vec2(1, 1);

        d3.position = vec3(baseX + nWidth/2 - nThickness, baseY, nBaseZ);
        d3.normal = vec3(0, 1, 0); d3.color = arrowColor; d3.texCoord = vec2(0, 1);

        g_building.terrainMesh.vertices.push_back(d0);
        g_building.terrainMesh.vertices.push_back(d1);
        g_building.terrainMesh.vertices.push_back(d2);
        g_building.terrainMesh.vertices.push_back(d3);

        g_building.terrainMesh.indices.push_back(n3BaseIdx + 0);
        g_building.terrainMesh.indices.push_back(n3BaseIdx + 1);
        g_building.terrainMesh.indices.push_back(n3BaseIdx + 2);
        g_building.terrainMesh.indices.push_back(n3BaseIdx + 0);
        g_building.terrainMesh.indices.push_back(n3BaseIdx + 2);
        g_building.terrainMesh.indices.push_back(n3BaseIdx + 3);

        std::cout << "[TerrainGen] Added 3D north arrow at (" << baseX << ", " << baseZ << ") ft" << std::endl;
    }

    return 0;
}

ARCH_API int arch_get_terrain_generation_progress(float* out_progress, const char** out_status) {
    if (out_progress) *out_progress = g_terrainGenProgress.load();
    if (out_status) *out_status = g_terrainGenStatus.c_str();
    return (g_terrainGenProgress < 1.0f && g_terrainGenProgress > 0.0f) ? 1 : 0;
}

// =============================================================================
// Environment/HDRI API
// =============================================================================

ARCH_API int arch_load_hdri(const char* path) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_initialized || !g_renderer) {
        setError("Not initialized");
        return -1;
    }

    if (!path || strlen(path) == 0) {
        setError("Invalid HDRI path");
        return -2;
    }

    std::cout << "[ArchAPI] Loading HDRI: " << path << std::endl;

    if (g_renderer->loadHdrEnvironment(path)) {
        std::cout << "[ArchAPI] HDRI loaded successfully" << std::endl;
        return 0;
    } else {
        setError("Failed to load HDRI");
        return -3;
    }
}

ARCH_API const char* arch_list_hdris(void) {
    static std::string result;
    result.clear();

    std::string hdriDir = "hdri";
    if (!std::filesystem::exists(hdriDir)) {
        hdriDir = "../../hdri";
    }

    if (std::filesystem::exists(hdriDir)) {
        for (const auto& entry : std::filesystem::directory_iterator(hdriDir)) {
            if (entry.path().extension() == ".hdr") {
                if (!result.empty()) result += ";";
                result += entry.path().filename().string();
            }
        }
    }

    return result.c_str();
}

// =============================================================================
// Path Tracer API Implementation
// =============================================================================

ARCH_API int arch_pt_set_config(int width, int height, int samples, int bounces) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (width <= 0 || height <= 0 || samples <= 0 || bounces <= 0) {
        setError("Invalid path tracer configuration");
        return -1;
    }

    g_ptConfig.width = static_cast<u32>(width);
    g_ptConfig.height = static_cast<u32>(height);
    g_ptConfig.samplesPerPixel = static_cast<u32>(samples);
    g_ptConfig.maxBounces = static_cast<u32>(bounces);

    std::cout << "[PathTracer API] Config: " << width << "x" << height
              << ", " << samples << " spp, " << bounces << " bounces\n";

    return 0;
}

ARCH_API int arch_pt_start_render(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_initialized || !g_context) {
        setError("Not initialized");
        return -1;
    }

    if (g_building.elements.empty()) {
        setError("No scene loaded");
        return -2;
    }

    // Create path tracer if needed
    if (!g_pathTracer) {
        g_pathTracer = std::make_unique<PathTracer>(*g_context);
        // Load PBR textures from materials directory
        g_pathTracer->loadMaterialTextures("materials");
    }

    // Set scene with terrain (if enabled and available)
    const TerrainMesh* terrain = nullptr;
    std::string terrainMatName = "";
    std::cout << "[PathTracer] Terrain check: enabled=" << g_terrainEnabled
              << ", hasData=" << g_building.terrainMesh.hasData()
              << ", vertices=" << g_building.terrainMesh.vertices.size()
              << ", indices=" << g_building.terrainMesh.indices.size() << "\n";
    if (g_terrainEnabled && g_building.terrainMesh.hasData()) {
        terrain = &g_building.terrainMesh;
        terrainMatName = g_terrainTextureName;
        std::cout << "[PathTracer] Including terrain with " << g_building.terrainMesh.indices.size() / 3
                  << " triangles, material='" << terrainMatName << "'\n";
    } else {
        std::cout << "[PathTracer] Terrain NOT included\n";
    }

    if (!g_pathTracer->setScene(g_building.elements, terrain, terrainMatName)) {
        setError("Failed to upload scene to path tracer");
        return -3;
    }

    // Set camera
    Camera camera;
    camera.position.x = g_cameraTarget.x + g_cameraDistance * cos(g_cameraPitch) * sin(g_cameraYaw);
    camera.position.y = g_cameraTarget.y + g_cameraDistance * sin(g_cameraPitch);
    camera.position.z = g_cameraTarget.z + g_cameraDistance * cos(g_cameraPitch) * cos(g_cameraYaw);
    camera.target = g_cameraTarget;
    camera.up = vec3(0, 1, 0);
    camera.fov = g_cameraFOV;
    camera.nearPlane = 0.1f;
    camera.farPlane = 100000.0f;  // Large value to handle mm units
    camera.isOrthographic = g_cameraOrthographic;
    camera.orthoSize = g_cameraDistance * 0.5f;

    std::cout << "[PathTracer] Camera pos: (" << camera.position.x << ", " << camera.position.y << ", " << camera.position.z
              << "), target: (" << camera.target.x << ", " << camera.target.y << ", " << camera.target.z << ")\n";

    g_pathTracer->setCamera(camera);
    g_pathTracer->setConfig(g_ptConfig);

    // Pass section clipping from renderer to path tracer
    if (g_renderer) {
        g_pathTracer->setClipPlane(g_renderer->getClipPlane(), g_renderer->getClippingEnabled());
        std::cout << "[PathTracer] Clipping: enabled=" << g_renderer->getClippingEnabled()
                  << ", plane=(" << g_renderer->getClipPlane().x << ", " << g_renderer->getClipPlane().y
                  << ", " << g_renderer->getClipPlane().z << ", " << g_renderer->getClipPlane().w << ")\n";

        // Pass UV scale from renderer to path tracer for consistent texturing
        float uvScale = g_renderer->getMaterialUVScale();
        g_pathTracer->setUVScale(uvScale);
        std::cout << "[PathTracer] UV scale: " << uvScale << "\n";
    }

    // Start render
    g_pathTracer->startRender();

    return 0;
}

ARCH_API int arch_pt_render_frame(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_pathTracer) {
        return -1;
    }

    if (!g_pathTracer->isRendering()) {
        return g_pathTracer->isComplete() ? 0 : -1;
    }

    bool moreFrames = g_pathTracer->renderFrame();
    return moreFrames ? 1 : 0;
}

ARCH_API int arch_pt_get_progress(float* progress) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!progress) {
        return -1;
    }

    if (!g_pathTracer) {
        *progress = 0.0f;
        return 0;
    }

    *progress = g_pathTracer->getProgress();
    return 0;
}

ARCH_API void arch_pt_stop(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (g_pathTracer) {
        g_pathTracer->stopRender();
    }
}

ARCH_API int arch_pt_is_rendering(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return (g_pathTracer && g_pathTracer->isRendering()) ? 1 : 0;
}

ARCH_API int arch_pt_is_complete(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return (g_pathTracer && g_pathTracer->isComplete()) ? 1 : 0;
}

ARCH_API int arch_pt_get_sample_count(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_pathTracer) {
        return 0;
    }

    return static_cast<int>(g_pathTracer->getCurrentSample());
}

ARCH_API int arch_pt_save_png(const char* path, float exposure) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_pathTracer) {
        setError("Path tracer not initialized");
        return -1;
    }

    if (!path) {
        setError("Invalid path");
        return -2;
    }

    if (!g_pathTracer->savePNG(std::string(path), exposure)) {
        setError("Failed to save PNG");
        return -3;
    }

    return 0;
}

ARCH_API int arch_pt_save_hdr(const char* path) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_pathTracer) {
        setError("Path tracer not initialized");
        return -1;
    }

    if (!path) {
        setError("Invalid path");
        return -2;
    }

    if (!g_pathTracer->saveEXR(std::string(path))) {
        setError("Failed to save HDR");
        return -3;
    }

    return 0;
}

ARCH_API int arch_pt_apply_denoise(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (!g_pathTracer) {
        setError("Path tracer not initialized");
        return -1;
    }

    g_pathTracer->applyDenoising();
    return 0;
}

ARCH_API void arch_pt_set_exposure(float exposure) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    g_ptConfig.exposure = exposure;

    if (g_pathTracer) {
        g_pathTracer->setConfig(g_ptConfig);
    }
}

ARCH_API float arch_pt_get_exposure(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_ptConfig.exposure;
}

ARCH_API void arch_pt_set_tonemap_mode(int mode) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    if (mode >= 0 && mode <= 2) {
        g_ptConfig.tonemapMode = static_cast<u32>(mode);
        if (g_pathTracer) {
            g_pathTracer->setConfig(g_ptConfig);
        }
    }
}

ARCH_API int arch_pt_get_tonemap_mode(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return static_cast<int>(g_ptConfig.tonemapMode);
}

ARCH_API void arch_pt_set_nee_enabled(int enabled) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    g_ptConfig.enableNEE = (enabled != 0);

    if (g_pathTracer) {
        g_pathTracer->setConfig(g_ptConfig);
    }
}

ARCH_API void arch_pt_set_rr_enabled(int enabled) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    g_ptConfig.enableRR = (enabled != 0);

    if (g_pathTracer) {
        g_pathTracer->setConfig(g_ptConfig);
    }
}

// =============================================================================
// Tessellation API Implementation
// =============================================================================

ARCH_API void arch_set_tessellation_enabled(int enabled) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setTessellationEnabled(enabled != 0);
    }
}

ARCH_API int arch_get_tessellation_enabled(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        return g_renderer->getTessellationEnabled() ? 1 : 0;
    }
    return 0;
}

ARCH_API void arch_set_tessellation_level(float level) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setTessellationLevel(level);
    }
}

ARCH_API float arch_get_tessellation_level(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        return g_renderer->getTessellationLevel();
    }
    return 1.0f;
}

ARCH_API void arch_set_displacement_scale(float scale) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        g_renderer->setDisplacementScale(scale);
    }
}

ARCH_API float arch_get_displacement_scale(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (g_renderer) {
        return g_renderer->getDisplacementScale();
    }
    return 0.0f;
}

// =============================================================================
// LOD (Level of Detail) API
// =============================================================================

static int g_lod_level = 3;  // Default: Assembly (medium detail)

ARCH_API void arch_set_lod_level(int level) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);

    // Clamp to valid range and store
    level = std::max(1, std::min(5, level));
    g_lod_level = level;

    if (!g_renderer) return;

    // Adjust rendering parameters based on LOD level
    switch (level) {
        case 1:  // Topology - minimal detail, fastest
            g_renderer->setTessellationEnabled(false);
            g_renderer->setShadowsEnabled(false);
            g_renderer->setSSAOEnabled(false);
            g_renderer->setBloomEnabled(false);
            break;

        case 2:  // Spatial - low detail
            g_renderer->setTessellationEnabled(false);
            g_renderer->setShadowsEnabled(true);
            g_renderer->setSSAOEnabled(false);
            g_renderer->setBloomEnabled(false);
            break;

        case 3:  // Assembly - medium detail (default)
            g_renderer->setTessellationEnabled(false);
            g_renderer->setShadowsEnabled(true);
            g_renderer->setSSAOEnabled(true);
            g_renderer->setSSAORadius(0.3f);
            g_renderer->setSSAOIntensity(0.8f);
            g_renderer->setBloomEnabled(false);
            break;

        case 4:  // Construction - high detail
            g_renderer->setTessellationEnabled(true);
            g_renderer->setTessellationLevel(16.0f);
            g_renderer->setDisplacementScale(0.05f);
            g_renderer->setShadowsEnabled(true);
            g_renderer->setSSAOEnabled(true);
            g_renderer->setSSAORadius(0.5f);
            g_renderer->setSSAOIntensity(1.0f);
            g_renderer->setBloomEnabled(true);
            g_renderer->setBloomIntensity(0.3f);
            break;

        case 5:  // Fabrication - maximum detail
            g_renderer->setTessellationEnabled(true);
            g_renderer->setTessellationLevel(32.0f);
            g_renderer->setDisplacementScale(0.1f);
            g_renderer->setShadowsEnabled(true);
            g_renderer->setSSAOEnabled(true);
            g_renderer->setSSAORadius(0.7f);
            g_renderer->setSSAOIntensity(1.2f);
            g_renderer->setBloomEnabled(true);
            g_renderer->setBloomIntensity(0.5f);
            break;
    }
}

ARCH_API int arch_get_lod_level(void) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    return g_lod_level;
}

// =============================================================================
// Frame Capture API
// =============================================================================

ARCH_API int arch_capture_frame(const char* path) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (!g_renderer) {
        setError("Renderer not initialized");
        return 1;
    }

    try {
        // Get current viewport size
        u32 width = g_context ? g_context->getSwapchainExtent().width : 1920;
        u32 height = g_context ? g_context->getSwapchainExtent().height : 1080;

        // Render current frame and save
        // TODO: Implement proper high-res capture
        setError("Frame capture not yet implemented");
        return 1;
    } catch (const std::exception& e) {
        setError(e.what());
        return -1;
    }
}

ARCH_API int arch_capture_elevation(const char* path, int direction, int section_enabled, float section_depth) {
    std::lock_guard<std::recursive_mutex> lock(g_mutex);
    if (!g_renderer || !g_context) {
        setError("Renderer not initialized");
        return 1;
    }

    try {
        // Save current camera state
        float savedYaw = g_cameraYaw;
        float savedPitch = g_cameraPitch;
        float savedDistance = g_cameraDistance;
        vec3 savedTarget = g_cameraTarget;
        bool savedOrtho = g_cameraOrthographic;

        // Switch to orthographic mode
        g_cameraOrthographic = true;

        // Use default bounds if no geometry
        float distance = 100.0f;

        // Position camera based on direction
        // Direction: 0=South, 1=North, 2=East, 3=West
        switch (direction) {
            case 0: // South - looking from south
                g_cameraYaw = 0.0f;
                g_cameraPitch = 0.0f;
                break;
            case 1: // North - looking from north
                g_cameraYaw = 3.14159f;  // 180 degrees in radians
                g_cameraPitch = 0.0f;
                break;
            case 2: // East - looking from east
                g_cameraYaw = 1.5708f;   // 90 degrees in radians
                g_cameraPitch = 0.0f;
                break;
            case 3: // West - looking from west
                g_cameraYaw = -1.5708f;  // -90 degrees in radians
                g_cameraPitch = 0.0f;
                break;
            default:
                g_cameraYaw = 0.0f;
                g_cameraPitch = 0.0f;
                break;
        }

        g_cameraDistance = distance;

        // Update camera
        updateCamera();

        // Capture frame
        int result = arch_capture_frame(path);

        // Restore camera state
        g_cameraYaw = savedYaw;
        g_cameraPitch = savedPitch;
        g_cameraDistance = savedDistance;
        g_cameraTarget = savedTarget;
        g_cameraOrthographic = savedOrtho;
        updateCamera();

        return result;
    } catch (const std::exception& e) {
        setError(e.what());
        return -1;
    }
}

} // extern "C"
