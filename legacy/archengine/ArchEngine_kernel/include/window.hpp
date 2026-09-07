#pragma once

#include "types.hpp"

#define GLFW_INCLUDE_VULKAN
#include <GLFW/glfw3.h>

namespace arch {

struct WindowConfig {
    u32 width = 1920;
    u32 height = 1080;
    std::string title = "Arch Engine";
    bool fullscreen = false;
    bool vsync = true;
    bool resizable = true;
};

class Window {
public:
    Window(const WindowConfig& config);
    ~Window();

    // Non-copyable
    Window(const Window&) = delete;
    Window& operator=(const Window&) = delete;

    // Accessors
    GLFWwindow* getHandle() const { return m_window; }
    u32 getWidth() const { return m_width; }
    u32 getHeight() const { return m_height; }
    f32 getAspectRatio() const { return static_cast<f32>(m_width) / static_cast<f32>(m_height); }
    bool wasResized() const { return m_framebufferResized; }
    void resetResizedFlag() { m_framebufferResized = false; }

    // Window state
    bool shouldClose() const;
    void close();

    // Size queries
    std::pair<u32, u32> getFramebufferSize() const;
    std::pair<u32, u32> getWindowSize() const;

    // Input state
    bool isKeyPressed(i32 key) const;
    bool isMouseButtonPressed(i32 button) const;
    void getCursorPos(f64& x, f64& y) const;
    void setCursorMode(int mode) { glfwSetInputMode(m_window, GLFW_CURSOR, mode); }

    // Vulkan
    VkSurfaceKHR createSurface(VkInstance instance) const;
    std::vector<const char*> getRequiredExtensions() const;

    // Events
    void pollEvents();
    void waitEvents();

    // Callbacks
    using ResizeCallback = std::function<void(int, int)>;
    using KeyCallback = std::function<void(int, int, int, int)>;
    using MouseButtonCallback = std::function<void(int, int, int)>;
    using CursorPosCallback = std::function<void(double, double)>;
    using ScrollCallback = std::function<void(double, double)>;

    void setResizeCallback(ResizeCallback cb) { m_resizeCallback = cb; }
    void setKeyCallback(KeyCallback cb) { m_keyCallback = cb; }
    void setMouseButtonCallback(MouseButtonCallback cb) { m_mouseButtonCallback = cb; }
    void setCursorPosCallback(CursorPosCallback cb) { m_cursorPosCallback = cb; }
    void setScrollCallback(ScrollCallback cb) { m_scrollCallback = cb; }

private:
    static void framebufferResizeCallback(GLFWwindow* window, int width, int height);
    static void keyCallback(GLFWwindow* window, int key, int scancode, int action, int mods);
    static void mouseButtonCallback(GLFWwindow* window, int button, int action, int mods);
    static void cursorPosCallback(GLFWwindow* window, double xpos, double ypos);
    static void scrollCallback(GLFWwindow* window, double xoffset, double yoffset);

    GLFWwindow* m_window = nullptr;
    WindowConfig m_config;
    u32 m_width = 0;
    u32 m_height = 0;
    bool m_framebufferResized = false;

    ResizeCallback m_resizeCallback;
    KeyCallback m_keyCallback;
    MouseButtonCallback m_mouseButtonCallback;
    CursorPosCallback m_cursorPosCallback;
    ScrollCallback m_scrollCallback;
};

} // namespace arch
