#include "imgui_layer.hpp"
#include "physics_bridge.hpp"
#include "renderer.hpp"
#include "memory_test.hpp"
#include <GLFW/glfw3.h>
#include <algorithm>
#include <chrono>
#include <ctime>
#include <filesystem>
#include <iostream>
#include <map>
#include <stdexcept>

namespace arch {

ImGuiLayer::ImGuiLayer(VulkanContext& context, GLFWwindow* window, VkRenderPass renderPass) : m_context(context) {
    // Create descriptor pool for ImGui
    createDescriptorPool();

    // Setup ImGui context
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;

    // Setup style
    ImGui::StyleColorsDark();
    ImGuiStyle& style = ImGui::GetStyle();
    style.WindowRounding = 5.0f;
    style.FrameRounding = 3.0f;
    style.ScrollbarRounding = 3.0f;
    style.GrabRounding = 3.0f;

    // Initialize GLFW backend
    ImGui_ImplGlfw_InitForVulkan(window, true);

    // Initialize Vulkan backend
    ImGui_ImplVulkan_InitInfo initInfo{};
    initInfo.Instance = context.getInstance();
    initInfo.PhysicalDevice = context.getPhysicalDevice();
    initInfo.Device = context.getDevice();
    initInfo.QueueFamily = context.getGraphicsQueueFamily();
    initInfo.Queue = context.getGraphicsQueue();
    initInfo.DescriptorPool = m_imguiPool;
    initInfo.MinImageCount = 2;
    initInfo.ImageCount = static_cast<u32>(context.getSwapchainImageViews().size());
    initInfo.MSAASamples = context.getMsaaSamples();  // Match render pass MSAA

    ImGui_ImplVulkan_Init(&initInfo, renderPass);

    // Upload fonts
    uploadFonts();

    // Initialize render output path to absolute path
    namespace fs = std::filesystem;
    fs::path renderDir = fs::current_path() / "renders";
    fs::path defaultRenderPath = renderDir / "render.png";
    snprintf(m_renderOutputPath, sizeof(m_renderOutputPath), "%s", defaultRenderPath.string().c_str());

    m_initialized = true;
}

ImGuiLayer::~ImGuiLayer() {
    if (m_initialized) {
        m_context.waitIdle();
        ImGui_ImplVulkan_Shutdown();
        ImGui_ImplGlfw_Shutdown();
        ImGui::DestroyContext();
    }

    if (m_imguiPool != VK_NULL_HANDLE) {
        vkDestroyDescriptorPool(m_context.getDevice(), m_imguiPool, nullptr);
    }
}

void ImGuiLayer::createDescriptorPool() {
    VkDescriptorPoolSize poolSizes[] = {
        { VK_DESCRIPTOR_TYPE_SAMPLER, 1000 },
        { VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1000 },
        { VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE, 1000 },
        { VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1000 },
        { VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER, 1000 },
        { VK_DESCRIPTOR_TYPE_STORAGE_TEXEL_BUFFER, 1000 },
        { VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1000 },
        { VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1000 },
        { VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC, 1000 },
        { VK_DESCRIPTOR_TYPE_STORAGE_BUFFER_DYNAMIC, 1000 },
        { VK_DESCRIPTOR_TYPE_INPUT_ATTACHMENT, 1000 }
    };

    VkDescriptorPoolCreateInfo poolInfo{};
    poolInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
    poolInfo.flags = VK_DESCRIPTOR_POOL_CREATE_FREE_DESCRIPTOR_SET_BIT;
    poolInfo.maxSets = 1000;
    poolInfo.poolSizeCount = static_cast<u32>(std::size(poolSizes));
    poolInfo.pPoolSizes = poolSizes;

    if (vkCreateDescriptorPool(m_context.getDevice(), &poolInfo, nullptr, &m_imguiPool) != VK_SUCCESS) {
        throw std::runtime_error("Failed to create ImGui descriptor pool");
    }
}

void ImGuiLayer::uploadFonts() {
    // In ImGui 1.90+, font upload is handled automatically by ImGui_ImplVulkan_CreateFontsTexture
    ImGui_ImplVulkan_CreateFontsTexture();
}

void ImGuiLayer::beginFrame() {
    ImGui_ImplVulkan_NewFrame();
    ImGui_ImplGlfw_NewFrame();
    ImGui::NewFrame();
}

void ImGuiLayer::endFrame(VkCommandBuffer cmd) {
    ImGui::Render();
    ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(), cmd);
}

void ImGuiLayer::drawMainMenuBar(VisualizationMode& mode, bool& showDemo, bool& showMetrics) {
    if (ImGui::BeginMainMenuBar()) {
        if (ImGui::BeginMenu("View")) {
            if (ImGui::MenuItem("Structural", "1", mode == VisualizationMode::Structural))
                mode = VisualizationMode::Structural;
            if (ImGui::MenuItem("Thermal", "2", mode == VisualizationMode::Thermal))
                mode = VisualizationMode::Thermal;
            if (ImGui::MenuItem("Lighting", "3", mode == VisualizationMode::Lighting))
                mode = VisualizationMode::Lighting;
            if (ImGui::MenuItem("Acoustic", "4", mode == VisualizationMode::Acoustic))
                mode = VisualizationMode::Acoustic;
            if (ImGui::MenuItem("Material", "5", mode == VisualizationMode::Material))
                mode = VisualizationMode::Material;
            ImGui::EndMenu();
        }
        if (ImGui::BeginMenu("Tools")) {
            ImGui::MenuItem("Show Demo", nullptr, &showDemo);
            ImGui::MenuItem("Show Metrics", nullptr, &showMetrics);
            ImGui::MenuItem("Material Library", nullptr, &m_showMaterialLibrary);
            ImGui::MenuItem("Material Inspector", nullptr, &m_showMaterialInspector);
            ImGui::MenuItem("Material Test (PBR)", nullptr, &m_showMaterialTestWindow);
            ImGui::MenuItem("Render Preview", nullptr, &m_showRenderPreviewPanel);
            ImGui::Separator();
            if (ImGui::MenuItem("Run Memory Test")) {
                m_runMemoryTest = true;
            }
            ImGui::EndMenu();
        }
        ImGui::EndMainMenuBar();
    }
}

void ImGuiLayer::drawBuildingPanel(const Building& building, size_t currentIndex, size_t totalBuildings) {
    ImGui::SetNextWindowPos(ImVec2(10, 30), ImGuiCond_FirstUseEver);
    ImGui::SetNextWindowSize(ImVec2(280, 200), ImGuiCond_FirstUseEver);

    if (ImGui::Begin("Building Info")) {
        ImGui::Text("Building: %s", building.name.c_str());
        ImGui::Text("Index: %zu / %zu", currentIndex + 1, totalBuildings);
        ImGui::Separator();

        ImGui::Text("Elements: %zu", building.elements.size());

        // Count element types
        size_t beams = 0, columns = 0, floors = 0;
        for (const auto& elem : building.elements) {
            switch (elem.type) {
                case ElementType::Beam: beams++; break;
                case ElementType::Column: columns++; break;
                case ElementType::Floor: floors++; break;
                default: break;
            }
        }

        ImGui::BulletText("Beams: %zu", beams);
        ImGui::BulletText("Columns: %zu", columns);
        ImGui::BulletText("Floors: %zu", floors);

        ImGui::Separator();
        ImGui::TextWrapped("Use [ ] to switch buildings");
    }
    ImGui::End();
}

void ImGuiLayer::drawPhysicsPanel(const FrameAnalysis& analysis, bool physicsAvailable) {
    ImGui::SetNextWindowPos(ImVec2(10, 240), ImGuiCond_FirstUseEver);
    ImGui::SetNextWindowSize(ImVec2(280, 180), ImGuiCond_FirstUseEver);

    if (ImGui::Begin("Physics Analysis")) {
        if (!physicsAvailable) {
            ImGui::TextColored(ImVec4(1.0f, 0.5f, 0.0f, 1.0f), "Physics engine not available");
            ImGui::TextWrapped("Python physics module not found.");
        } else {
            // Status indicator
            if (analysis.allPass) {
                ImGui::TextColored(ImVec4(0.2f, 0.8f, 0.2f, 1.0f), "Status: PASS");
            } else {
                ImGui::TextColored(ImVec4(0.9f, 0.3f, 0.3f, 1.0f), "Status: FAIL");
            }

            ImGui::Separator();

            // Utilization bars
            ImGui::Text("Beam Utilization:");
            f32 beamUtil = analysis.maxBeamUtilization;
            ImVec4 beamColor = beamUtil > 1.0f ? ImVec4(0.9f, 0.3f, 0.3f, 1.0f) :
                              beamUtil > 0.9f ? ImVec4(0.9f, 0.7f, 0.0f, 1.0f) :
                              ImVec4(0.2f, 0.8f, 0.2f, 1.0f);
            ImGui::PushStyleColor(ImGuiCol_PlotHistogram, beamColor);
            ImGui::ProgressBar(beamUtil, ImVec2(-1, 0),
                std::to_string(static_cast<int>(beamUtil * 100)).append("%").c_str());
            ImGui::PopStyleColor();

            ImGui::Text("Column Utilization:");
            f32 colUtil = analysis.maxColumnUtilization;
            ImVec4 colColor = colUtil > 1.0f ? ImVec4(0.9f, 0.3f, 0.3f, 1.0f) :
                             colUtil > 0.9f ? ImVec4(0.9f, 0.7f, 0.0f, 1.0f) :
                             ImVec4(0.2f, 0.8f, 0.2f, 1.0f);
            ImGui::PushStyleColor(ImGuiCol_PlotHistogram, colColor);
            ImGui::ProgressBar(colUtil, ImVec2(-1, 0),
                std::to_string(static_cast<int>(colUtil * 100)).append("%").c_str());
            ImGui::PopStyleColor();

            ImGui::Separator();
            if (ImGui::Button("Run Analysis (P)")) {
                m_analysisRequested = true;
            }
        }
    }
    ImGui::End();
}

void ImGuiLayer::drawVisualizationPanel(VisualizationMode& mode, Renderer& renderer) {
    ImGui::SetNextWindowPos(ImVec2(10, 430), ImGuiCond_FirstUseEver);
    ImGui::SetNextWindowSize(ImVec2(280, 280), ImGuiCond_FirstUseEver);

    if (ImGui::Begin("Visualization Mode")) {
        // Camera view buttons
        ImGui::Text("Camera View:");
        if (ImGui::Button("Perspective")) {
            m_cameraViewRequested = true;
            m_requestedCameraView = CameraView::Perspective;
        }
        ImGui::SameLine();
        if (ImGui::Button("Top")) {
            m_cameraViewRequested = true;
            m_requestedCameraView = CameraView::Top;
        }
        ImGui::SameLine();
        if (ImGui::Button("Front")) {
            m_cameraViewRequested = true;
            m_requestedCameraView = CameraView::Front;
        }
        ImGui::SameLine();
        if (ImGui::Button("Right")) {
            m_cameraViewRequested = true;
            m_requestedCameraView = CameraView::Right;
        }

        ImGui::Separator();

        const char* modeNames[] = { "Structural", "Thermal", "Lighting", "Acoustic", "Material", "Wireframe" };
        int currentMode = static_cast<int>(mode);

        if (ImGui::Combo("Mode", &currentMode, modeNames, IM_ARRAYSIZE(modeNames))) {
            mode = static_cast<VisualizationMode>(currentMode);
        }

        // Material style selector
        const char* styleNames[] = { "Realistic", "Clean", "Schematic", "Blueprint" };
        int currentStyle = static_cast<int>(renderer.getMaterialStyle());

        if (ImGui::Combo("Style", &currentStyle, styleNames, IM_ARRAYSIZE(styleNames))) {
            renderer.setMaterialStyle(static_cast<MaterialStyle>(currentStyle));
        }

        ImGui::Separator();

        // Mode-specific legend
        switch (mode) {
            case VisualizationMode::Structural:
                ImGui::TextColored(ImVec4(0.13f, 0.77f, 0.37f, 1.0f), "Green: Safe (<70%%)");
                ImGui::TextColored(ImVec4(0.92f, 0.70f, 0.03f, 1.0f), "Yellow: Warning (70-90%%)");
                ImGui::TextColored(ImVec4(0.98f, 0.45f, 0.09f, 1.0f), "Orange: Critical (90-100%%)");
                ImGui::TextColored(ImVec4(0.94f, 0.27f, 0.27f, 1.0f), "Red: Failure (>100%%)");
                break;
            case VisualizationMode::Thermal:
                ImGui::TextColored(ImVec4(0.12f, 0.56f, 1.0f, 1.0f), "Blue: Cold");
                ImGui::TextColored(ImVec4(1.0f, 0.27f, 0.0f, 1.0f), "Red: Hot");
                break;
            case VisualizationMode::Lighting:
                ImGui::TextColored(ImVec4(1.0f, 0.96f, 0.61f, 1.0f), "Yellow: High lux");
                ImGui::TextColored(ImVec4(0.25f, 0.41f, 0.88f, 1.0f), "Blue: Low lux");
                break;
            case VisualizationMode::Acoustic:
                ImGui::TextColored(ImVec4(0.13f, 0.77f, 0.37f, 1.0f), "Green: Good RT60");
                ImGui::TextColored(ImVec4(0.92f, 0.70f, 0.03f, 1.0f), "Yellow: Moderate");
                ImGui::TextColored(ImVec4(0.94f, 0.27f, 0.27f, 1.0f), "Red: Poor");
                break;
            case VisualizationMode::Material:
                ImGui::Text("Colors by material type");
                break;
            default:
                break;
        }
    }
    ImGui::End();
}

void ImGuiLayer::drawHelpPanel(bool& show) {
    if (!show) return;

    ImGui::SetNextWindowPos(ImVec2(300, 100), ImGuiCond_FirstUseEver);
    ImGui::SetNextWindowSize(ImVec2(350, 300), ImGuiCond_FirstUseEver);

    if (ImGui::Begin("Help", &show)) {
        ImGui::Text("Keyboard Shortcuts:");
        ImGui::Separator();

        ImGui::BulletText("1-5: Switch visualization mode");
        ImGui::BulletText("[ ]: Previous/Next building");
        ImGui::BulletText("P: Run physics analysis");
        ImGui::BulletText("H: Toggle help");
        ImGui::BulletText("ESC: Exit");

        ImGui::Separator();
        ImGui::Text("Mouse Controls:");
        ImGui::BulletText("Left drag: Orbit camera");
        ImGui::BulletText("Right drag: Pan camera");
        ImGui::BulletText("Scroll: Zoom");
    }
    ImGui::End();
}

void ImGuiLayer::drawPerformancePanel(f32 fps, u32 drawCalls, u32 triangles, u32 culledElements) {
    ImGui::SetNextWindowPos(ImVec2(ImGui::GetIO().DisplaySize.x - 170, 30), ImGuiCond_FirstUseEver);
    ImGui::SetNextWindowSize(ImVec2(160, 115), ImGuiCond_FirstUseEver);

    if (ImGui::Begin("Performance", nullptr, ImGuiWindowFlags_NoResize)) {
        ImGui::Text("FPS: %.1f", fps);
        ImGui::Text("Draw Calls: %u", drawCalls);
        ImGui::Text("Triangles: %u", triangles);
        if (culledElements > 0) {
            ImGui::Text("Culled: %u", culledElements);
        }
    }
    ImGui::End();
}

void ImGuiLayer::drawCompassOverlay(float cameraYaw) {
    if (!m_showCompass) return;

    // Compass in bottom-left corner
    const float compassSize = 80.0f;
    const float margin = 20.0f;
    const ImVec2 displaySize = ImGui::GetIO().DisplaySize;
    const ImVec2 center(margin + compassSize / 2, displaySize.y - margin - compassSize / 2);

    ImDrawList* drawList = ImGui::GetBackgroundDrawList();

    // Background circle
    drawList->AddCircleFilled(center, compassSize / 2, IM_COL32(30, 30, 30, 200), 32);
    drawList->AddCircle(center, compassSize / 2, IM_COL32(100, 100, 100, 255), 32, 2.0f);

    // Cardinal direction labels and arrows
    // Camera yaw: 0 = looking north (+Z), PI/2 = looking east (+X)
    // We rotate the compass so N always points to where north actually is in view
    const float arrowLength = compassSize * 0.35f;
    const float labelRadius = compassSize * 0.42f;

    // Directions: N=+Z, E=+X, S=-Z, W=-X
    // In our coordinate system: +Z is north, +X is east
    // Camera yaw 0 = looking along +Z (north)
    struct Direction {
        const char* label;
        float angle;  // Angle from north (0 = N, PI/2 = E, PI = S, 3*PI/2 = W)
        ImU32 color;
    };

    Direction dirs[] = {
        {"N", 0.0f, IM_COL32(220, 50, 50, 255)},             // North - Red
        {"E", 3.14159f / 2.0f, IM_COL32(200, 200, 200, 255)}, // East
        {"S", 3.14159f, IM_COL32(200, 200, 200, 255)},        // South
        {"W", 3.0f * 3.14159f / 2.0f, IM_COL32(200, 200, 200, 255)}  // West
    };

    for (const auto& dir : dirs) {
        // Rotate by negative camera yaw so compass shows world directions
        float displayAngle = dir.angle - cameraYaw;

        // Arrow endpoint (pointing outward from center)
        // In screen space: up is -Y, so we need to flip
        float dx = std::sin(displayAngle) * arrowLength;
        float dy = -std::cos(displayAngle) * arrowLength;  // Negative because screen Y is down

        ImVec2 arrowEnd(center.x + dx, center.y + dy);

        // Draw arrow line
        float lineWidth = (dir.label[0] == 'N') ? 3.0f : 1.5f;
        drawList->AddLine(center, arrowEnd, dir.color, lineWidth);

        // Draw arrowhead for North
        if (dir.label[0] == 'N') {
            float headSize = 8.0f;
            float headAngle = 0.4f;  // Arrowhead spread
            ImVec2 head1(arrowEnd.x - headSize * std::sin(displayAngle - headAngle),
                         arrowEnd.y + headSize * std::cos(displayAngle - headAngle));
            ImVec2 head2(arrowEnd.x - headSize * std::sin(displayAngle + headAngle),
                         arrowEnd.y + headSize * std::cos(displayAngle + headAngle));
            drawList->AddTriangleFilled(arrowEnd, head1, head2, dir.color);
        }

        // Label position (beyond arrow)
        float labelDx = std::sin(displayAngle) * labelRadius;
        float labelDy = -std::cos(displayAngle) * labelRadius;
        ImVec2 labelPos(center.x + labelDx - 4, center.y + labelDy - 7);  // Offset for text centering

        drawList->AddText(labelPos, dir.color, dir.label);
    }

    // Center dot
    drawList->AddCircleFilled(center, 3.0f, IM_COL32(150, 150, 150, 255));
}

bool ImGuiLayer::wantCaptureMouse() const {
    return ImGui::GetIO().WantCaptureMouse;
}

bool ImGuiLayer::wantCaptureKeyboard() const {
    return ImGui::GetIO().WantCaptureKeyboard;
}


void ImGuiLayer::drawGeometryEditor(bool& show) {
    if (!show) return;

    ImGui::SetNextWindowPos(ImVec2(300, 30), ImGuiCond_FirstUseEver);
    ImGui::SetNextWindowSize(ImVec2(350, 550), ImGuiCond_FirstUseEver);

    if (ImGui::Begin("Geometry Editor", &show)) {
        // File Operations
        if (ImGui::CollapsingHeader("File Operations", ImGuiTreeNodeFlags_DefaultOpen)) {
            static char filepath[256] = "C:/Users/jerro/Desktop/channel_test/test.ifc";
            ImGui::InputText("Path", filepath, sizeof(filepath));
            m_filePath = filepath;

            // Quick load buttons
            if (ImGui::Button("Load")) {
                m_loadRequested = true;
            }
            ImGui::SameLine();
            if (ImGui::Button("Save")) {
                m_saveRequested = true;
            }
            
            ImGui::Separator();
            ImGui::Text("Quick Paths:");
            if (ImGui::Button("Desktop IFC")) {
                strcpy(filepath, "C:/Users/jerro/Desktop/channel_test/test.ifc");
                m_filePath = filepath;
                m_loadRequested = true;
            }
            ImGui::SameLine();
            if (ImGui::Button("Test JSON")) {
                strcpy(filepath, "X:/tmp/test_import.json");
                m_filePath = filepath;
                m_loadRequested = true;
            }
        }

        ImGui::Separator();

        // Add New Element
        if (ImGui::CollapsingHeader("Add Element", ImGuiTreeNodeFlags_DefaultOpen)) {
            const char* elementTypes[] = { "Beam", "Column", "Floor", "Wall", "Door", "Window", "Roof" };
            ImGui::Combo("Type", &m_newElement.type, elementTypes, IM_ARRAYSIZE(elementTypes));

            const char* materials[] = { "Steel", "Concrete", "Wood", "Aluminum" };
            ImGui::Combo("Material", &m_newElement.materialIndex, materials, IM_ARRAYSIZE(materials));

            ImGui::Separator();

            if (m_newElement.type == 0) {  // Beam
                ImGui::Text("Beam (horizontal member)");
                ImGui::DragFloat3("Start Point", m_newElement.start, 0.5f, -500.0f, 500.0f);
                ImGui::DragFloat3("End Point", m_newElement.end, 0.5f, -500.0f, 500.0f);
                ImGui::DragFloat("Width (ft)", &m_newElement.width, 0.05f, 0.1f, 5.0f);
                ImGui::DragFloat("Depth (ft)", &m_newElement.depth, 0.05f, 0.1f, 5.0f);
            }
            else if (m_newElement.type == 1) {  // Column
                ImGui::Text("Column (vertical member)");
                ImGui::DragFloat3("Base Position", m_newElement.start, 0.5f, -500.0f, 500.0f);
                float height = m_newElement.end[1] - m_newElement.start[1];
                if (height < 1.0f) height = 12.0f;
                if (ImGui::DragFloat("Height (ft)", &height, 0.5f, 1.0f, 100.0f)) {
                    m_newElement.end[0] = m_newElement.start[0];
                    m_newElement.end[1] = m_newElement.start[1] + height;
                    m_newElement.end[2] = m_newElement.start[2];
                }
                ImGui::DragFloat("Width (ft)", &m_newElement.width, 0.05f, 0.1f, 5.0f);
                ImGui::DragFloat("Depth (ft)", &m_newElement.depth, 0.05f, 0.1f, 5.0f);
            }
            else if (m_newElement.type == 2) {  // Floor
                ImGui::Text("Floor slab");
                ImGui::DragFloat3("Corner Position", m_newElement.start, 0.5f, -500.0f, 500.0f);
                float floorWidth = m_newElement.end[0] - m_newElement.start[0];
                float floorDepthZ = m_newElement.end[2] - m_newElement.start[2];
                if (floorWidth < 1.0f) floorWidth = 20.0f;
                if (floorDepthZ < 1.0f) floorDepthZ = 20.0f;
                if (ImGui::DragFloat("Width X (ft)", &floorWidth, 0.5f, 1.0f, 200.0f)) {
                    m_newElement.end[0] = m_newElement.start[0] + floorWidth;
                }
                if (ImGui::DragFloat("Depth Z (ft)", &floorDepthZ, 0.5f, 1.0f, 200.0f)) {
                    m_newElement.end[2] = m_newElement.start[2] + floorDepthZ;
                }
                m_newElement.end[1] = m_newElement.start[1];
                ImGui::DragFloat("Thickness (ft)", &m_newElement.depth, 0.05f, 0.1f, 2.0f);
            }
            else if (m_newElement.type == 3) {  // Wall
                ImGui::Text("Parametric Wall");

                // Wall type selection
                const char* wallTypes[] = { "2x6 Exterior", "2x4 Exterior", "2x4 Interior" };
                ImGui::Combo("Wall Type", &m_newElement.wallTypeIndex, wallTypes, IM_ARRAYSIZE(wallTypes));

                // Wall height
                ImGui::DragFloat("Height (ft)", &m_newElement.wallHeight, 0.5f, 4.0f, 20.0f);

                ImGui::Separator();

                // Drawing mode toggle
                if (m_drawMode == DrawMode::DrawWall) {
                    ImGui::TextColored(ImVec4(0.2f, 1.0f, 0.2f, 1.0f), "DRAWING MODE ACTIVE");
                    if (m_drawPoints.empty()) {
                        ImGui::Text("Click to place START point");
                    } else {
                        ImGui::Text("Click to place END point");
                        ImGui::Text("Start: (%.1f, %.1f, %.1f)",
                            m_drawPoints[0].x, m_drawPoints[0].y, m_drawPoints[0].z);
                    }
                    if (ImGui::Button("Cancel Drawing", ImVec2(-1, 25))) {
                        m_drawMode = DrawMode::None;
                        m_drawPoints.clear();
                    }
                } else {
                    if (ImGui::Button("Draw Wall (Click-to-Place)", ImVec2(-1, 30))) {
                        m_drawMode = DrawMode::DrawWall;
                        m_drawPoints.clear();
                    }
                    ImGui::TextColored(ImVec4(0.7f, 0.7f, 0.7f, 1.0f),
                        "Or enter coordinates manually:");
                    ImGui::DragFloat3("Start Position", m_newElement.start, 0.5f, -500.0f, 500.0f);
                    ImGui::DragFloat3("End Position", m_newElement.end, 0.5f, -500.0f, 500.0f);
                }
            }
            else if (m_newElement.type == 4) {  // Door
                ImGui::Text("Door opening");
                ImGui::DragFloat3("Position", m_newElement.start, 0.5f, -500.0f, 500.0f);
                float doorHeight = m_newElement.end[1] - m_newElement.start[1];
                if (doorHeight < 1.0f) doorHeight = 7.0f;  // Default door height ~7ft
                if (ImGui::DragFloat("Height (ft)", &doorHeight, 0.1f, 4.0f, 12.0f)) {
                    m_newElement.end[1] = m_newElement.start[1] + doorHeight;
                }
                ImGui::DragFloat("Width (ft)", &m_newElement.width, 0.1f, 2.0f, 10.0f);
                ImGui::DragFloat("Depth (ft)", &m_newElement.depth, 0.05f, 0.1f, 1.0f);
            }
            else if (m_newElement.type == 5) {  // Window
                ImGui::Text("Window");
                ImGui::DragFloat3("Position", m_newElement.start, 0.5f, -500.0f, 500.0f);
                float windowHeight = m_newElement.end[1] - m_newElement.start[1];
                if (windowHeight < 0.5f) windowHeight = 4.0f;  // Default window height
                if (ImGui::DragFloat("Height (ft)", &windowHeight, 0.1f, 1.0f, 10.0f)) {
                    m_newElement.end[1] = m_newElement.start[1] + windowHeight;
                }
                ImGui::DragFloat("Width (ft)", &m_newElement.width, 0.1f, 1.0f, 15.0f);
                ImGui::DragFloat("Depth (ft)", &m_newElement.depth, 0.05f, 0.1f, 0.5f);
            }
            else if (m_newElement.type == 6) {  // Roof
                ImGui::Text("Roof slab");
                ImGui::DragFloat3("Corner Position", m_newElement.start, 0.5f, -500.0f, 500.0f);
                float roofWidth = m_newElement.end[0] - m_newElement.start[0];
                float roofDepthZ = m_newElement.end[2] - m_newElement.start[2];
                if (roofWidth < 1.0f) roofWidth = 30.0f;
                if (roofDepthZ < 1.0f) roofDepthZ = 30.0f;
                if (ImGui::DragFloat("Width X (ft)", &roofWidth, 0.5f, 1.0f, 200.0f)) {
                    m_newElement.end[0] = m_newElement.start[0] + roofWidth;
                }
                if (ImGui::DragFloat("Depth Z (ft)", &roofDepthZ, 0.5f, 1.0f, 200.0f)) {
                    m_newElement.end[2] = m_newElement.start[2] + roofDepthZ;
                }
                ImGui::DragFloat("Thickness (ft)", &m_newElement.depth, 0.05f, 0.1f, 2.0f);
            }

            ImGui::Separator();

if (ImGui::Button("Add Element", ImVec2(-1, 30))) {
                m_addElementRequested = true;
            }
        }

        ImGui::Separator();

        // Boolean Operations (CSG)
        if (ImGui::CollapsingHeader("Boolean Operations")) {
            ImGui::Text("Selected: %d elements", (int)m_selectedElements.size());
            ImGui::TextWrapped("Ctrl+Click to select multiple elements");

            ImGui::Separator();

            // Union button - enabled only when 2+ elements selected
            bool canUnion = m_selectedElements.size() >= 2;
            if (!canUnion) {
                ImGui::BeginDisabled();
            }
            if (ImGui::Button("Union Selected", ImVec2(-1, 30))) {
                m_unionRequested = true;
            }
            if (!canUnion) {
                ImGui::EndDisabled();
                ImGui::TextColored(ImVec4(0.7f, 0.7f, 0.7f, 1.0f), "Select 2+ elements to union");
            }

        }
    }
    ImGui::End();
}


void ImGuiLayer::drawWallEditor(Building& building, bool show) {
    if (!show) return;
    
    ImGui::SetNextWindowPos(ImVec2(660, 30), ImGuiCond_FirstUseEver);
    ImGui::SetNextWindowSize(ImVec2(300, 400), ImGuiCond_FirstUseEver);
    
    if (ImGui::Begin("Wall Editor")) {
        // Get walls and roofs
        std::vector<int> wallIndices;
        std::vector<int> roofIndices;
        for (size_t i = 0; i < building.elements.size(); i++) {
            if (building.elements[i].type == ElementType::Wall) {
                wallIndices.push_back(static_cast<int>(i));
            }
            if (building.elements[i].type == ElementType::Roof) {
                roofIndices.push_back(static_cast<int>(i));
            }
        }

        ImGui::Text("Walls: %d, Roofs: %d", (int)wallIndices.size(), (int)roofIndices.size());

        // Wall selection - auto-select if element was clicked
        static int selectedIdx = 0;
        // Check if any selected element is a wall
        for (int selElem : m_selectedElements) {
            for (int i = 0; i < (int)wallIndices.size(); i++) {
                if (wallIndices[i] == selElem) {
                    selectedIdx = i;
                    break;
                }
            }
        }
        if (!wallIndices.empty()) {
            // Create wall labels
            std::vector<std::string> wallLabels;
            for (int idx : wallIndices) {
                auto& w = building.elements[idx];
                float height = w.end.y - w.start.y;
                char label[64];
                snprintf(label, sizeof(label), "Wall %d (%.1fft)", idx, height);
                wallLabels.push_back(label);
            }

            // Combo for wall selection
            if (ImGui::BeginCombo("Select Wall", wallLabels[selectedIdx].c_str())) {
                for (int i = 0; i < (int)wallLabels.size(); i++) {
                    bool isSelected = (selectedIdx == i);
                    if (ImGui::Selectable(wallLabels[i].c_str(), isSelected)) {
                        selectedIdx = i;
                    }
                    if (isSelected) ImGui::SetItemDefaultFocus();
                }
                ImGui::EndCombo();
            }

            // Show selected wall info
            int wallIdx = wallIndices[selectedIdx];
            auto& wall = building.elements[wallIdx];
            ImGui::Text("Current Height: %.1f ft", wall.end.y - wall.start.y);
            ImGui::Text("Position: (%.1f, %.1f) to (%.1f, %.1f)",
                       wall.start.x, wall.start.z, wall.end.x, wall.end.z);

            // Find roof peak above this wall
            float roofPeak = wall.end.y;
            for (int roofIdx : roofIndices) {
                auto& roof = building.elements[roofIdx];
                // Check if wall is under this roof (simple bounds check)
                float wallCenterX = (wall.start.x + wall.end.x) / 2;
                float wallCenterZ = (wall.start.z + wall.end.z) / 2;

                if (roof.mesh.hasData()) {
                    // Check mesh vertices for peak
                    for (const auto& v : roof.mesh.vertices) {
                        // If vertex is roughly above the wall
                        float dx = std::abs(v.x - wallCenterX);
                        float dz = std::abs(v.z - wallCenterZ);
                        float wallExtentX = std::abs(wall.end.x - wall.start.x) / 2 + 5.0f;
                        float wallExtentZ = std::abs(wall.end.z - wall.start.z) / 2 + 5.0f;
                        if (dx < wallExtentX && dz < wallExtentZ) {
                            roofPeak = std::max(roofPeak, v.y);
                        }
                    }
                } else {
                    // Use bounding box
                    if (wallCenterX >= roof.start.x - 5 && wallCenterX <= roof.end.x + 5 &&
                        wallCenterZ >= roof.start.z - 5 && wallCenterZ <= roof.end.z + 5) {
                        roofPeak = std::max(roofPeak, roof.end.y);
                    }
                }
            }

            ImGui::Text("Roof Peak Above: %.1f ft", roofPeak);

            // Height adjustment slider
            static float newHeight = 10.0f;
            newHeight = wall.end.y - wall.start.y;
            ImGui::SliderFloat("New Height (ft)", &newHeight, 1.0f, 30.0f);

            // Quick buttons
            if (ImGui::Button("Extend to Roof Peak")) {
                m_selectedWallIndex = wallIdx;
                // Subtract offset so wall fits under roof (accounts for roof thickness)
                m_wallExtendHeight = roofPeak - 0.5f;
                m_extendWallRequested = true;
            }
            ImGui::SameLine();
            if (ImGui::Button("Set Custom Height")) {
                m_selectedWallIndex = wallIdx;
                m_wallExtendHeight = wall.start.y + newHeight;
                m_extendWallRequested = true;
            }
        } else {
            ImGui::Text("No walls in model");
        }
    }
    ImGui::End();
}

void ImGuiLayer::drawRenderSettingsPanel(Renderer& renderer, bool& show) {
    if (!show) return;

    ImGui::SetNextWindowPos(ImVec2(10, 660), ImGuiCond_FirstUseEver);
    ImGui::SetNextWindowSize(ImVec2(320, 300), ImGuiCond_FirstUseEver);
    if (ImGui::Begin("Render Settings", &show)) {
        // Post-processing (HDR) master toggle
        bool postProcessingEnabled = renderer.isPostProcessingEnabled();
        if (ImGui::Checkbox("Enable Post Processing (HDR)", &postProcessingEnabled)) {
            renderer.setPostProcessingEnabled(postProcessingEnabled);
        }
        ImGui::SetItemTooltip("Enables HDR path for SSAO, bloom, and tonemapping.");

        ImGui::Separator();

        // Shadow Settings
        if (ImGui::CollapsingHeader("Shadow Settings", ImGuiTreeNodeFlags_DefaultOpen)) {
            bool shadowsEnabled = renderer.getShadowsEnabled();
            if (ImGui::Checkbox("Enable Shadows", &shadowsEnabled)) {
                renderer.setShadowsEnabled(shadowsEnabled);
            }

            if (shadowsEnabled) {
                vec3 lightDir = renderer.getLightDirection();
                float lightAngles[2] = {
                    glm::degrees(std::atan2(lightDir.x, lightDir.z)),  // Azimuth
                    glm::degrees(std::asin(-lightDir.y))               // Elevation
                };

                if (ImGui::SliderFloat("Sun Azimuth", &lightAngles[0], -180.0f, 180.0f, "%.0f deg")) {
                    float az = glm::radians(lightAngles[0]);
                    float el = glm::radians(lightAngles[1]);
                    vec3 newDir = vec3(
                        std::sin(az) * std::cos(el),
                        -std::sin(el),
                        std::cos(az) * std::cos(el)
                    );
                    renderer.setLightDirection(newDir);
                }

                if (ImGui::SliderFloat("Sun Elevation", &lightAngles[1], 10.0f, 80.0f, "%.0f deg")) {
                    float az = glm::radians(lightAngles[0]);
                    float el = glm::radians(lightAngles[1]);
                    vec3 newDir = vec3(
                        std::sin(az) * std::cos(el),
                        -std::sin(el),
                        std::cos(az) * std::cos(el)
                    );
                    renderer.setLightDirection(newDir);
                }

                float shadowBias = renderer.getShadowBias();
                if (ImGui::SliderFloat("Shadow Bias", &shadowBias, 0.001f, 0.1f, "%.4f")) {
                    renderer.setShadowBias(shadowBias);
                }
                ImGui::SetItemTooltip("Increase to reduce shadow acne, decrease to reduce peter-panning");

                // Quick presets
                ImGui::Text("Light Presets:");
                if (ImGui::Button("Morning")) {
                    renderer.setLightDirection(vec3(-0.7f, -0.5f, 0.5f));
                }
                ImGui::SameLine();
                if (ImGui::Button("Noon")) {
                    renderer.setLightDirection(vec3(0.0f, -1.0f, 0.1f));
                }
                ImGui::SameLine();
                if (ImGui::Button("Evening")) {
                    renderer.setLightDirection(vec3(0.7f, -0.3f, -0.5f));
                }

                ImGui::Separator();

                // Interactive light placement
                ImGui::Checkbox("Click to Position Light", &m_lightPlacementMode);
                if (m_lightPlacementMode) {
                    ImGui::TextColored(ImVec4(1.0f, 0.8f, 0.2f, 1.0f), "Click in scene to set sun position");
                }

                ImGui::Separator();

                // Sun animation
                static bool animateSun = false;
                static float animSpeed = 0.1f;  // Slower default
                static float sunAngle = 0.0f;

                ImGui::Checkbox("Animate Sun", &animateSun);
                if (animateSun) {
                    ImGui::SliderFloat("Speed", &animSpeed, 0.01f, 2.0f, "%.2fx");

                    // Update sun angle
                    sunAngle += animSpeed * 0.016f;  // ~60fps
                    if (sunAngle > 6.28318f) sunAngle -= 6.28318f;

                    // Calculate sun position (circular path)
                    float elevation = 0.5f + 0.3f * std::sin(sunAngle * 0.5f);  // Varies 0.2-0.8
                    vec3 newDir = vec3(
                        std::sin(sunAngle) * std::cos(elevation),
                        -std::sin(elevation),
                        std::cos(sunAngle) * std::cos(elevation)
                    );
                    renderer.setLightDirection(newDir);

                    // Show current time of day
                    float hours = (sunAngle / 6.28318f) * 24.0f;
                    int hour = static_cast<int>(hours) % 24;
                    int minute = static_cast<int>((hours - hour) * 60.0f) % 60;
                    ImGui::Text("Time: %02d:%02d", (hour + 6) % 24, minute);
                }
            }
        }

        ImGui::Separator();

        // Environment Settings (HDRI, Sky)
        if (ImGui::CollapsingHeader("Environment", ImGuiTreeNodeFlags_DefaultOpen)) {
            static std::vector<std::string> hdriFiles;
            static int selectedHdri = -1;
            static bool hdriScanned = false;
            static std::string hdriError;

            if (!hdriScanned) {
                // Scan for HDRI files
                std::string hdriDir = "hdri";
                if (!std::filesystem::exists(hdriDir)) {
                    hdriDir = "../../hdri";
                }
                if (std::filesystem::exists(hdriDir)) {
                    try {
                        for (const auto& entry : std::filesystem::directory_iterator(hdriDir)) {
                            if (entry.path().extension() == ".hdr") {
                                hdriFiles.push_back(entry.path().string());
                            }
                        }
                    } catch (...) {
                        // Ignore filesystem errors
                    }
                }
                hdriScanned = true;
            }

            ImGui::Text("Sky / Environment Map:");

            if (!hdriFiles.empty()) {
                const char* currentLabel = selectedHdri >= 0
                    ? std::filesystem::path(hdriFiles[selectedHdri]).filename().string().c_str()
                    : "Procedural Sky";

                if (ImGui::BeginCombo("##Environment", currentLabel)) {
                    // Procedural sky option
                    if (ImGui::Selectable("Procedural Sky", selectedHdri < 0)) {
                        selectedHdri = -1;
                        hdriError.clear();
                        try {
                            renderer.useProceduralSky();
                        } catch (const std::exception& e) {
                            hdriError = std::string("Error: ") + e.what();
                        } catch (...) {
                            hdriError = "Unknown error switching to procedural sky";
                        }
                    }
                    ImGui::Separator();
                    // HDRI files
                    for (int i = 0; i < static_cast<int>(hdriFiles.size()); i++) {
                        std::string filename = std::filesystem::path(hdriFiles[i]).filename().string();
                        if (ImGui::Selectable(filename.c_str(), selectedHdri == i)) {
                            selectedHdri = i;
                            hdriError.clear();
                            try {
                                if (!renderer.loadHdrEnvironment(hdriFiles[i])) {
                                    hdriError = "Failed to load HDRI";
                                }
                            } catch (const std::exception& e) {
                                hdriError = std::string("Error: ") + e.what();
                            } catch (...) {
                                hdriError = "Unknown error loading HDRI";
                            }
                        }
                    }
                    ImGui::EndCombo();
                }
                ImGui::SetItemTooltip("Select environment map for sky and lighting");
            } else {
                ImGui::TextDisabled("No HDRI files found in hdri/ folder");
                ImGui::TextDisabled("Place .hdr files there to enable");
            }

            if (!hdriError.empty()) {
                ImGui::TextColored(ImVec4(1.0f, 0.3f, 0.3f, 1.0f), "%s", hdriError.c_str());
            }

            // Rescan button
            if (ImGui::Button("Rescan HDRIs")) {
                hdriScanned = false;
                hdriFiles.clear();
                selectedHdri = -1;
            }
            ImGui::SetItemTooltip("Rescan hdri/ folder for new files");
        }

        ImGui::Separator();

        // Terrain Settings
        if (ImGui::CollapsingHeader("Terrain")) {
            static std::vector<std::string> terrainMaterials;
            static bool terrainMatsScanned = false;
            static int selectedTerrainMat = 0;  // 0 = Elevation Colors

            if (!terrainMatsScanned) {
                terrainMaterials.clear();
                terrainMaterials.push_back("");  // Empty = elevation colors

                // Scan for terrain-suitable materials in polyhaven folder
                std::string matDir = "materials/polyhaven";
                if (!std::filesystem::exists(matDir)) {
                    matDir = "../../materials/polyhaven";
                }
                if (std::filesystem::exists(matDir)) {
                    try {
                        for (const auto& entry : std::filesystem::directory_iterator(matDir)) {
                            if (entry.is_directory()) {
                                std::string name = entry.path().filename().string();
                                // Include terrain-like materials
                                if (name.find("grass") != std::string::npos ||
                                    name.find("ground") != std::string::npos ||
                                    name.find("mud") != std::string::npos ||
                                    name.find("sand") != std::string::npos ||
                                    name.find("rock") != std::string::npos ||
                                    name.find("snow") != std::string::npos ||
                                    name.find("gravel") != std::string::npos ||
                                    name.find("dirt") != std::string::npos ||
                                    name.find("forest") != std::string::npos ||
                                    name.find("path") != std::string::npos) {
                                    terrainMaterials.push_back("polyhaven/" + name);
                                }
                            }
                        }
                    } catch (...) {}
                }
                terrainMatsScanned = true;
            }

            ImGui::Text("Terrain Material:");
            const char* currentLabel = selectedTerrainMat == 0 ? "Elevation Colors" :
                terrainMaterials[selectedTerrainMat].c_str();

            if (ImGui::BeginCombo("##TerrainMat", currentLabel)) {
                // Elevation colors option
                if (ImGui::Selectable("Elevation Colors", selectedTerrainMat == 0)) {
                    selectedTerrainMat = 0;
                    renderer.setTerrainMaterial("");
                }

                if (terrainMaterials.size() > 1) {
                    ImGui::Separator();
                    for (int i = 1; i < static_cast<int>(terrainMaterials.size()); i++) {
                        std::string displayName = terrainMaterials[i];
                        size_t pos = displayName.find('/');
                        if (pos != std::string::npos) {
                            displayName = displayName.substr(pos + 1);
                        }
                        if (ImGui::Selectable(displayName.c_str(), selectedTerrainMat == i)) {
                            selectedTerrainMat = i;
                            renderer.setTerrainMaterial(terrainMaterials[i]);
                        }
                    }
                }
                ImGui::EndCombo();
            }
            ImGui::SetItemTooltip("Select material texture for terrain");

            if (terrainMaterials.size() <= 1) {
                ImGui::TextDisabled("No terrain materials found");
                ImGui::TextDisabled("Run: python scripts/download_polyhaven.py --preset terrain");
            }

            // Rescan button
            if (ImGui::Button("Rescan Materials")) {
                terrainMatsScanned = false;
                terrainMaterials.clear();
                selectedTerrainMat = 0;
            }
        }

        ImGui::Separator();

        // Multi-Light System
        if (ImGui::CollapsingHeader("Additional Lights")) {
            u32 lightCount = renderer.getLightCount();

            ImGui::Text("Lights: %u / %u", lightCount, MAX_LIGHTS);

            // Click to place lights
            ImGui::Text("Click to Place:");
            bool placingPoint = (m_placeLightType == PlaceLightType::Point);
            bool placingSpot = (m_placeLightType == PlaceLightType::Spot);

            if (ImGui::RadioButton("Off", !placingPoint && !placingSpot)) {
                m_placeLightType = PlaceLightType::None;
            }
            ImGui::SameLine();
            if (ImGui::RadioButton("Point", placingPoint)) {
                m_placeLightType = placingPoint ? PlaceLightType::None : PlaceLightType::Point;
            }
            ImGui::SameLine();
            if (ImGui::RadioButton("Spot", placingSpot)) {
                m_placeLightType = placingSpot ? PlaceLightType::None : PlaceLightType::Spot;
            }

            if (m_placeLightType != PlaceLightType::None) {
                ImGui::TextColored(ImVec4(0.2f, 1.0f, 0.4f, 1.0f), "Click in scene to place light");

                // Snap plane selection
                ImGui::Text("Snap Plane:");
                int snapIdx = static_cast<int>(m_snapPlane);
                const char* snapNames[] = { "Ground", "Floor 1 (8ft)", "Floor 2 (18ft)", "Floor 3 (28ft)", "Ceiling (10ft)", "Custom" };
                if (ImGui::Combo("##snapplane", &snapIdx, snapNames, 6)) {
                    m_snapPlane = static_cast<SnapPlane>(snapIdx);
                }

                if (m_snapPlane == SnapPlane::Custom) {
                    ImGui::SliderFloat("Custom Height (ft)", &m_customSnapHeight, 0.0f, 50.0f, "%.1f");
                }

                // Show current snap height
                float snapHeight = getSnapPlaneHeight();
                ImGui::Text("Placement Height: %.1f ft (%.1f m)", snapHeight, snapHeight * 0.3048f);

                // Show preview position if valid
                if (m_lightPreviewValid) {
                    ImGui::TextColored(ImVec4(1.0f, 1.0f, 0.0f, 1.0f),
                        "Preview: (%.1f, %.1f, %.1f)",
                        m_lightPreviewPos.x, m_lightPreviewPos.y, m_lightPreviewPos.z);
                }

                ImGui::Separator();
                ImGui::Text("Light Properties:");
                ImGui::SliderFloat("Intensity##place", &m_lightPlacementIntensity, 0.5f, 20.0f, "%.1f");
                ImGui::SliderFloat("Range##place", &m_lightPlacementRange, 5.0f, 50.0f, "%.1f");
                ImGui::ColorEdit3("Color##place", &m_lightPlacementColor.x);

                // Group selection for placement
                const char* groupNames[] = { "Interior", "Exterior", "Accent", "Custom" };
                ImGui::Combo("Group##place", &m_placementLightGroup, groupNames, 4);
            }

            ImGui::Separator();

            // Light Group Controls
            ImGui::Text("Light Groups:");
            const char* groupLabels[] = { "Interior", "Exterior", "Accent", "Custom" };
            for (int g = 0; g < 4; g++) {
                ImGui::PushID(g);
                bool enabled = m_lightGroupEnabled[g];
                if (ImGui::Checkbox(groupLabels[g], &enabled)) {
                    m_lightGroupEnabled[g] = enabled;
                }
                ImGui::SameLine();
                ImGui::SetNextItemWidth(80);
                ImGui::SliderFloat("##intensity", &m_lightGroupIntensity[g], 0.0f, 2.0f, "%.1fx");
                ImGui::PopID();
            }

            ImGui::Separator();

            // Add light at origin buttons
            if (lightCount < MAX_LIGHTS) {
                if (ImGui::Button("+ Point at Origin")) {
                    Light light = Light::createPoint(vec3(0.0f, 3.0f, 0.0f), vec3(1.0f), 5.0f, 15.0f);
                    renderer.addLight(light);
                }
                ImGui::SameLine();
                if (ImGui::Button("+ Spot at Origin")) {
                    Light light = Light::createSpot(vec3(0.0f, 5.0f, 0.0f), vec3(0.0f, -1.0f, 0.0f),
                                                     vec3(1.0f), 8.0f, 20.0f, 25.0f, 40.0f);
                    renderer.addLight(light);
                }
            }

            if (ImGui::Button("Clear All Lights")) {
                renderer.clearLights();
                m_selectedLightIndex = -1;
            }

            ImGui::Separator();

            // Light list
            ImGui::Text("Placed Lights:");
            for (u32 i = 0; i < lightCount; i++) {
                Light* light = renderer.getLight(i);
                if (!light) continue;

                const char* typeNames[] = {"Dir", "Pt", "Spot"};
                const char* groupNames[] = {"Int", "Ext", "Acc", "Cust"};
                LightType type = light->getType();
                int typeIdx = static_cast<int>(type);
                int groupIdx = static_cast<int>(light->getGroup());

                // Show enabled state with color
                bool lightEnabled = light->isEnabled() && m_lightGroupEnabled[groupIdx];
                if (!lightEnabled) {
                    ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.5f, 0.5f, 0.5f, 1.0f));
                }

                // Build label with shadow indicator
                char label[80];
                const char* shadowIndicator = light->isCastingShadow() ? " [S]" : "";
                snprintf(label, sizeof(label), "%u: %s [%s]%s%s", i, typeNames[typeIdx], groupNames[groupIdx],
                         shadowIndicator, lightEnabled ? "" : " (off)");

                bool isSelected = (m_selectedLightIndex == static_cast<int>(i));
                if (ImGui::Selectable(label, isSelected)) {
                    m_selectedLightIndex = isSelected ? -1 : static_cast<int>(i);
                }

                if (!lightEnabled) {
                    ImGui::PopStyleColor();
                }
            }

            // Edit selected light
            if (m_selectedLightIndex >= 0 && m_selectedLightIndex < static_cast<int>(lightCount)) {
                Light* light = renderer.getLight(static_cast<u32>(m_selectedLightIndex));
                if (light) {
                    ImGui::Separator();
                    ImGui::Text("Edit Light %d", m_selectedLightIndex);

                    // Position
                    vec3 pos = light->getPosition();
                    if (ImGui::DragFloat3("Position", &pos.x, 0.1f)) {
                        light->setPosition(pos);
                    }

                    // Color
                    vec3 color = light->getColor();
                    if (ImGui::ColorEdit3("Color", &color.x)) {
                        light->setColor(color);
                    }

                    // Intensity
                    float intensity = light->getIntensity();
                    if (ImGui::SliderFloat("Intensity", &intensity, 0.1f, 50.0f)) {
                        light->setIntensity(intensity);
                    }

                    // Light Group
                    const char* groupNames[] = { "Interior", "Exterior", "Accent", "Custom" };
                    int currentGroup = static_cast<int>(light->getGroup());
                    if (ImGui::Combo("Group", &currentGroup, groupNames, 4)) {
                        light->setGroup(static_cast<LightGroup>(currentGroup));
                    }

                    // Enabled checkbox
                    bool lightEnabled = light->isEnabled();
                    if (ImGui::Checkbox("Enabled", &lightEnabled)) {
                        light->setEnabled(lightEnabled);
                    }

                    // Shadow casting checkbox (directional/spot lights only)
                    LightType lightType = light->getType();
                    if (lightType == LightType::Directional || lightType == LightType::Spot) {
                        bool castsShadow = light->isCastingShadow();
                        if (ImGui::Checkbox("Cast Shadow", &castsShadow)) {
                            light->setCastShadow(castsShadow);
                        }
                        ImGui::SameLine();
                        ImGui::TextDisabled("(?)");
                        if (ImGui::IsItemHovered()) {
                            ImGui::SetTooltip("Only one light can cast shadows at a time.\nThe first shadow-casting light will be used.");
                        }
                    }

                    // Range (for point/spot)
                    LightType type = light->getType();
                    if (type == LightType::Point || type == LightType::Spot) {
                        float range = light->getRange();
                        if (ImGui::SliderFloat("Range", &range, 1.0f, 100.0f)) {
                            light->setRange(range);
                        }
                    }

                    // Direction and angles (for spot)
                    if (type == LightType::Spot) {
                        vec3 dir = light->getDirection();
                        if (ImGui::DragFloat3("Direction", &dir.x, 0.01f, -1.0f, 1.0f)) {
                            light->setDirection(dir);
                        }

                        float innerAngle = light->getInnerAngleDeg();
                        float outerAngle = light->getOuterAngleDeg();
                        bool anglesChanged = false;
                        if (ImGui::SliderFloat("Inner Angle", &innerAngle, 5.0f, 85.0f, "%.1f deg")) {
                            anglesChanged = true;
                        }
                        if (ImGui::SliderFloat("Outer Angle", &outerAngle, 10.0f, 90.0f, "%.1f deg")) {
                            anglesChanged = true;
                        }
                        if (anglesChanged) {
                            // Ensure outer >= inner
                            if (outerAngle < innerAngle) outerAngle = innerAngle + 5.0f;
                            light->setSpotAngles(innerAngle, outerAngle);
                        }
                    }

                    // Presets
                    ImGui::Separator();
                    ImGui::Text("Presets:");
                    if (ImGui::Button("Warm")) {
                        light->setColor(vec3(1.0f, 0.85f, 0.7f));
                        light->setIntensity(3.0f);
                    }
                    ImGui::SameLine();
                    if (ImGui::Button("Cool")) {
                        light->setColor(vec3(0.9f, 0.95f, 1.0f));
                        light->setIntensity(4.0f);
                    }
                    ImGui::SameLine();
                    if (ImGui::Button("Candle")) {
                        light->setColor(vec3(1.0f, 0.6f, 0.2f));
                        light->setIntensity(1.5f);
                    }

                    // Remove button
                    ImGui::Separator();
                    if (ImGui::Button("Remove This Light")) {
                        renderer.removeLight(static_cast<u32>(m_selectedLightIndex));
                        m_selectedLightIndex = -1;
                    }
                }
            }
        }

        ImGui::Separator();

        // SSAO Settings
        if (ImGui::CollapsingHeader("Ambient Occlusion (SSAO)", ImGuiTreeNodeFlags_DefaultOpen)) {
            bool ssaoEnabled = renderer.getSSAOEnabled();
            if (ImGui::Checkbox("Enable SSAO", &ssaoEnabled)) {
                renderer.setSSAOEnabled(ssaoEnabled);
            }

            if (ssaoEnabled) {
                float ssaoRadius = renderer.getSSAORadius();
                if (ImGui::SliderFloat("Radius", &ssaoRadius, 0.1f, 2.0f, "%.2f")) {
                    renderer.setSSAORadius(ssaoRadius);
                }

                float ssaoIntensity = renderer.getSSAOIntensity();
                if (ImGui::SliderFloat("Intensity", &ssaoIntensity, 0.5f, 4.0f, "%.1f")) {
                    renderer.setSSAOIntensity(ssaoIntensity);
                }

                float ssaoBias = renderer.getSSAOBias();
                if (ImGui::SliderFloat("Bias", &ssaoBias, 0.001f, 0.1f, "%.3f")) {
                    renderer.setSSAOBias(ssaoBias);
                }

                // Presets
                ImGui::Text("Presets:");
                if (ImGui::Button("Subtle")) {
                    renderer.setSSAORadius(0.3f);
                    renderer.setSSAOIntensity(1.0f);
                }
                ImGui::SameLine();
                if (ImGui::Button("Medium")) {
                    renderer.setSSAORadius(0.5f);
                    renderer.setSSAOIntensity(1.5f);
                }
                ImGui::SameLine();
                if (ImGui::Button("Strong")) {
                    renderer.setSSAORadius(0.8f);
                    renderer.setSSAOIntensity(2.5f);
                }
            }
        }

        ImGui::Separator();

        // Bloom Settings
        if (ImGui::CollapsingHeader("Bloom", ImGuiTreeNodeFlags_DefaultOpen)) {
            bool bloomEnabled = renderer.getBloomEnabled();
            if (ImGui::Checkbox("Enable Bloom", &bloomEnabled)) {
                renderer.setBloomEnabled(bloomEnabled);
            }

            if (bloomEnabled) {
                float bloomThreshold = renderer.getBloomThreshold();
                if (ImGui::SliderFloat("Threshold", &bloomThreshold, 0.1f, 3.0f, "%.2f")) {
                    renderer.setBloomThreshold(bloomThreshold);
                }

                float bloomIntensity = renderer.getBloomIntensity();
                if (ImGui::SliderFloat("Bloom Intensity", &bloomIntensity, 0.0f, 1.0f, "%.2f")) {
                    renderer.setBloomIntensity(bloomIntensity);
                }

                int bloomIterations = static_cast<int>(renderer.getBloomIterations());
                if (ImGui::SliderInt("Blur Iterations", &bloomIterations, 1, 10)) {
                    renderer.setBloomIterations(static_cast<u32>(bloomIterations));
                }

                // Presets
                ImGui::Text("Presets:");
                if (ImGui::Button("Subtle##bloom")) {
                    renderer.setBloomThreshold(1.5f);
                    renderer.setBloomIntensity(0.15f);
                    renderer.setBloomIterations(3);
                }
                ImGui::SameLine();
                if (ImGui::Button("Medium##bloom")) {
                    renderer.setBloomThreshold(1.0f);
                    renderer.setBloomIntensity(0.3f);
                    renderer.setBloomIterations(5);
                }
                ImGui::SameLine();
                if (ImGui::Button("Strong##bloom")) {
                    renderer.setBloomThreshold(0.5f);
                    renderer.setBloomIntensity(0.5f);
                    renderer.setBloomIterations(7);
                }
            }
        }

        ImGui::Separator();

        // Tonemapping Settings
        if (ImGui::CollapsingHeader("Tonemapping", ImGuiTreeNodeFlags_DefaultOpen)) {
            float exposure = renderer.getExposure();
            if (ImGui::SliderFloat("Exposure", &exposure, 0.1f, 5.0f, "%.2f")) {
                renderer.setExposure(exposure);
            }

            const char* tonemapModes[] = { "Reinhard", "ACES Filmic", "Uncharted 2" };
            int currentMode = static_cast<int>(renderer.getTonemapMode());
            if (ImGui::Combo("Tonemap Mode", &currentMode, tonemapModes, IM_ARRAYSIZE(tonemapModes))) {
                renderer.setTonemapMode(static_cast<u32>(currentMode));
            }

            // Exposure presets
            ImGui::Text("Exposure Presets:");
            if (ImGui::Button("Indoor")) {
                renderer.setExposure(1.5f);
            }
            ImGui::SameLine();
            if (ImGui::Button("Outdoor")) {
                renderer.setExposure(1.0f);
            }
            ImGui::SameLine();
            if (ImGui::Button("Bright")) {
                renderer.setExposure(0.7f);
            }
        }

        ImGui::Separator();

        // Tessellation (displacement mapping)
        if (ImGui::CollapsingHeader("Tessellation")) {
            bool tessEnabled = renderer.getTessellationEnabled();
            if (ImGui::Checkbox("Enable Tessellation", &tessEnabled)) {
                renderer.setTessellationEnabled(tessEnabled);
            }
            if (ImGui::IsItemHovered()) {
                ImGui::SetTooltip("Enable hardware tessellation for displacement mapping using height maps");
            }

            ImGui::BeginDisabled(!tessEnabled);

            float tessLevel = renderer.getTessellationLevel();
            if (ImGui::SliderFloat("Tessellation Level", &tessLevel, 1.0f, 128.0f, "%.1f")) {
                renderer.setTessellationLevel(tessLevel);
            }
            if (ImGui::IsItemHovered()) {
                ImGui::SetTooltip("Higher values create more detailed displacement but may impact performance");
            }

            float dispScale = renderer.getDisplacementScale();
            if (ImGui::SliderFloat("Displacement Scale", &dispScale, 0.0f, 2.0f, "%.4f", ImGuiSliderFlags_Logarithmic)) {
                renderer.setDisplacementScale(dispScale);
            }
            if (ImGui::IsItemHovered()) {
                ImGui::SetTooltip("Controls the strength of height map displacement");
            }

            ImGui::EndDisabled();

            // Tessellation presets (always enabled - they also enable tessellation)
            ImGui::Text("Presets:");
            if (ImGui::Button("Subtle")) {
                renderer.setTessellationEnabled(true);
                renderer.setTessellationLevel(16.0f);
                renderer.setDisplacementScale(0.05f);
            }
            ImGui::SameLine();
            if (ImGui::Button("Medium")) {
                renderer.setTessellationEnabled(true);
                renderer.setTessellationLevel(32.0f);
                renderer.setDisplacementScale(0.15f);
            }
            ImGui::SameLine();
            if (ImGui::Button("Strong")) {
                renderer.setTessellationEnabled(true);
                renderer.setTessellationLevel(64.0f);
                renderer.setDisplacementScale(0.3f);
            }
            ImGui::SameLine();
            if (ImGui::Button("Off")) {
                renderer.setTessellationEnabled(false);
            }
        }

        // Parallax Occlusion Mapping (alternative to tessellation)
        if (ImGui::CollapsingHeader("Parallax Occlusion Mapping (POM)")) {
            bool pomEnabled = renderer.getPOMEnabled();
            if (ImGui::Checkbox("Enable POM", &pomEnabled)) {
                renderer.setPOMEnabled(pomEnabled);
            }
            if (ImGui::IsItemHovered()) {
                ImGui::SetTooltip("Parallax Occlusion Mapping simulates depth using ray marching in fragment shader.\nLower performance cost than tessellation but view-dependent.");
            }

            if (pomEnabled) {
                float heightScale = renderer.getPOMHeightScale();
                if (ImGui::SliderFloat("Height Scale", &heightScale, 0.001f, 0.2f, "%.3f")) {
                    renderer.setPOMHeightScale(heightScale);
                }
                if (ImGui::IsItemHovered()) {
                    ImGui::SetTooltip("Controls apparent depth of parallax effect. Higher = deeper displacement.");
                }

                float minLayers = renderer.getPOMMinLayers();
                float maxLayers = renderer.getPOMMaxLayers();
                if (ImGui::SliderFloat("Min Layers", &minLayers, 4.0f, 32.0f, "%.0f")) {
                    renderer.setPOMLayers(minLayers, maxLayers);
                }
                if (ImGui::IsItemHovered()) {
                    ImGui::SetTooltip("Minimum ray marching steps (used when viewing straight-on).");
                }
                if (ImGui::SliderFloat("Max Layers", &maxLayers, 16.0f, 128.0f, "%.0f")) {
                    renderer.setPOMLayers(minLayers, maxLayers);
                }
                if (ImGui::IsItemHovered()) {
                    ImGui::SetTooltip("Maximum ray marching steps (used at grazing angles). Higher = better quality but slower.");
                }

                // POM presets
                ImGui::Text("Presets:");
                if (ImGui::Button("Subtle##pom")) {
                    renderer.setPOMEnabled(true);
                    renderer.setPOMHeightScale(0.02f);
                    renderer.setPOMLayers(8.0f, 32.0f);
                }
                ImGui::SameLine();
                if (ImGui::Button("Medium##pom")) {
                    renderer.setPOMEnabled(true);
                    renderer.setPOMHeightScale(0.05f);
                    renderer.setPOMLayers(8.0f, 48.0f);
                }
                ImGui::SameLine();
                if (ImGui::Button("Strong##pom")) {
                    renderer.setPOMEnabled(true);
                    renderer.setPOMHeightScale(0.1f);
                    renderer.setPOMLayers(12.0f, 64.0f);
                }
                ImGui::SameLine();
                if (ImGui::Button("Off##pom")) {
                    renderer.setPOMEnabled(false);
                }

                ImGui::TextColored(ImVec4(1.0f, 0.8f, 0.3f, 1.0f), "Note: POM works best with tessellation disabled.");
            }
        }

        ImGui::Separator();

        // Material Library
        if (ImGui::CollapsingHeader("Material Library", ImGuiTreeNodeFlags_DefaultOpen)) {
            if (!m_materialUiInitialized) {
                const std::string& root = renderer.getMaterialRoot();
                if (!root.empty()) {
                    std::snprintf(m_materialRoot, sizeof(m_materialRoot), "%s", root.c_str());
                    std::snprintf(m_materialOutputRoot, sizeof(m_materialOutputRoot), "%s", root.c_str());
                }
                m_materialUiInitialized = true;
            }

            ImGui::InputText("Filter", m_materialFilter, sizeof(m_materialFilter));

            auto materials = renderer.getMaterialNames();
            std::vector<std::string> filtered;
            filtered.reserve(materials.size());

            std::string filter = m_materialFilter;
            for (const auto& name : materials) {
                if (filter.empty() || name.find(filter) != std::string::npos) {
                    filtered.push_back(name);
                }
            }

            if (ImGui::BeginListBox("Materials", ImVec2(-1.0f, 180.0f))) {
                for (int i = 0; i < static_cast<int>(filtered.size()); ++i) {
                    const std::string& name = filtered[i];
                    bool isSelected = (m_materialListIndex == i);
                    if (ImGui::Selectable(name.c_str(), isSelected)) {
                        m_materialListIndex = i;
                        m_applyMaterialName = name;
                    }
                    if (ImGui::BeginDragDropSource()) {
                        ImGui::SetDragDropPayload("ARCH_MATERIAL", name.c_str(), name.size() + 1);
                        ImGui::Text("Apply %s", name.c_str());
                        m_materialDragActive = true;
                        m_materialDragName = name;
                        ImGui::EndDragDropSource();
                    }
                }
                ImGui::EndListBox();
            }

            if (!m_applyMaterialName.empty()) {
                ImGui::Text("Selected: %s", m_applyMaterialName.c_str());
            } else {
                ImGui::Text("Selected: -");
            }

            if (ImGui::Button("Apply to Selection")) {
                if (!m_applyMaterialName.empty()) {
                    m_applyMaterialRequested = true;
                }
            }
            ImGui::SameLine();
            if (ImGui::Button("Reload Library")) {
                renderer.reloadMaterialLibrary(m_materialRoot);
            }

            ImGui::InputText("Material Root", m_materialRoot, sizeof(m_materialRoot));
            if (ImGui::Button("Set Material Root")) {
                renderer.reloadMaterialLibrary(m_materialRoot);
            }

            // Quick preview controls
            float uvScale = renderer.getMaterialUVScale();
            if (ImGui::SliderFloat("UV Scale", &uvScale, 0.01f, 500.0f, "%.2f")) {
                renderer.setMaterialUVScale(uvScale);
            }

            float normalStrength = renderer.getNormalStrength();
            if (ImGui::SliderFloat("Normal Strength", &normalStrength, 0.0f, 2.0f, "%.2f")) {
                renderer.setNormalStrength(normalStrength);
            }

            ImGui::TextWrapped("Drag a material onto the viewport to apply it to the surface under the cursor.");

            // Render-server generation
            if (ImGui::TreeNode("Generate Material (Render Server)")) {
                if (ImGui::Button("Start Render Server")) {
                    m_startRenderServerRequested = true;
                }
                ImGui::SameLine();
                if (ImGui::Button("Stop Render Server")) {
                    m_stopRenderServerRequested = true;
                }
                ImGui::Text("Script: enhancer/start_render_server.ps1");
                ImGui::DragInt("Port", &m_renderServerPort, 1.0f, 1, 65535);

                ImGui::InputText("Name", m_materialName, sizeof(m_materialName));
                ImGui::InputText("Prompt", m_materialPrompt, sizeof(m_materialPrompt));
                ImGui::InputText("Negative", m_materialNegative, sizeof(m_materialNegative));
                ImGui::InputText("Server URL", m_materialServerUrl, sizeof(m_materialServerUrl));
                ImGui::InputText("Python EXE", m_materialPythonExe, sizeof(m_materialPythonExe));
                ImGui::InputText("Generator Script", m_materialScriptPath, sizeof(m_materialScriptPath));
                ImGui::InputText("Output Root", m_materialOutputRoot, sizeof(m_materialOutputRoot));

                ImGui::DragInt("Size", &m_materialSize, 32, 256, 4096);
                ImGui::DragInt("Steps", &m_materialSteps, 1, 5, 100);
                ImGui::DragFloat("Guidance", &m_materialGuidance, 0.1f, 1.0f, 20.0f, "%.1f");
                ImGui::Checkbox("Tileable", &m_materialTileable);

                if (ImGui::Button("Generate Material")) {
                    m_materialGenerateRequest.name = m_materialName;
                    m_materialGenerateRequest.prompt = m_materialPrompt;
                    m_materialGenerateRequest.negativePrompt = m_materialNegative;
                    m_materialGenerateRequest.serverUrl = m_materialServerUrl;
                    m_materialGenerateRequest.pythonExe = m_materialPythonExe;
                    m_materialGenerateRequest.scriptPath = m_materialScriptPath;
                    m_materialGenerateRequest.outputRoot = m_materialOutputRoot;
                    m_materialGenerateRequest.size = m_materialSize;
                    m_materialGenerateRequest.steps = m_materialSteps;
                    m_materialGenerateRequest.guidance = m_materialGuidance;
                    m_materialGenerateRequest.tileable = m_materialTileable;
                    m_materialGenerateRequested = true;
                }

                if (!m_materialGenerateStatus.empty()) {
                    ImGui::Text("Status: %s", m_materialGenerateStatus.c_str());
                }

                ImGui::TreePop();
            }

            // Material upscaling
            if (ImGui::TreeNode("Upscale Material")) {
                if (!m_applyMaterialName.empty()) {
                    ImGui::Text("Material: %s", m_applyMaterialName.c_str());

                    // Scale selector
                    const char* scaleItems[] = { "2x", "4x" };
                    int scaleIndex = (m_upscaleScale == 2) ? 0 : 1;
                    if (ImGui::Combo("Scale Factor", &scaleIndex, scaleItems, 2)) {
                        m_upscaleScale = (scaleIndex == 0) ? 2 : 4;
                    }

                    // Method selector
                    const char* methodItems[] = { "Real-ESRGAN (AI)", "Lanczos (Fast)" };
                    ImGui::Combo("Method", &m_upscaleMethod, methodItems, 2);

                    ImGui::TextDisabled("Upscales all textures in material folder");

                    // Upscale button
                    bool canUpscale = !m_materialUpscaleInFlight;
                    if (!canUpscale) {
                        ImGui::BeginDisabled();
                    }

                    if (ImGui::Button("Upscale Material", ImVec2(-1, 25))) {
                        m_materialUpscaleRequest.materialName = m_applyMaterialName;
                        m_materialUpscaleRequest.serverUrl = m_materialServerUrl;
                        m_materialUpscaleRequest.pythonExe = m_materialPythonExe;
                        m_materialUpscaleRequest.scriptPath = "scripts/material_preview.py";
                        m_materialUpscaleRequest.materialRoot = m_materialRoot;
                        m_materialUpscaleRequest.scale = m_upscaleScale;
                        m_materialUpscaleRequest.method = m_upscaleMethod;
                        m_materialUpscaleRequested = true;
                    }

                    if (!canUpscale) {
                        ImGui::EndDisabled();
                    }

                    if (!m_materialUpscaleStatus.empty()) {
                        ImGui::Text("Status: %s", m_materialUpscaleStatus.c_str());
                    }
                } else {
                    ImGui::TextDisabled("Select a material from the list above");
                }

                ImGui::TreePop();
            }

            // Height map generation
            if (ImGui::TreeNode("Generate Height Map")) {
                if (!m_applyMaterialName.empty()) {
                    ImGui::Text("Material: %s", m_applyMaterialName.c_str());

                    // Method selector
                    const char* heightMethods[] = { "Hybrid (Auto)", "From Normal Map", "From Diffuse (AI)" };
                    ImGui::Combo("Method", &m_heightGenMethod, heightMethods, 3);

                    ImGui::SliderFloat("Blur", &m_heightGenBlur, 0.0f, 5.0f, "%.1f");
                    ImGui::SetItemTooltip("Smoothing to reduce noise");

                    ImGui::SliderFloat("Contrast", &m_heightGenContrast, 0.5f, 2.0f, "%.2f");
                    ImGui::SetItemTooltip("Increase/decrease height variation");

                    ImGui::Checkbox("Invert", &m_heightGenInvert);
                    ImGui::SetItemTooltip("Swap peaks and valleys");

                    ImGui::TextDisabled("Generates height.png for tessellation/displacement");

                    bool canGenerate = !m_heightGenInFlight;
                    if (!canGenerate) {
                        ImGui::BeginDisabled();
                    }

                    if (ImGui::Button("Generate Height Map", ImVec2(-1, 25))) {
                        m_heightGenRequest.materialName = m_applyMaterialName;
                        m_heightGenRequest.materialPath = std::string(m_materialRoot) + "/" + m_applyMaterialName;
                        m_heightGenRequest.serverUrl = m_materialServerUrl;
                        m_heightGenRequest.method = m_heightGenMethod;
                        m_heightGenRequest.blur = m_heightGenBlur;
                        m_heightGenRequest.contrast = m_heightGenContrast;
                        m_heightGenRequest.invert = m_heightGenInvert;
                        m_heightGenRequested = true;
                    }

                    if (!canGenerate) {
                        ImGui::EndDisabled();
                    }

                    if (!m_heightGenStatus.empty()) {
                        ImGui::Text("Status: %s", m_heightGenStatus.c_str());
                    }
                } else {
                    ImGui::TextDisabled("Select a material from the list above");
                }

                ImGui::TreePop();
            }

            if (m_materialDragActive && !ImGui::IsMouseDown(ImGuiMouseButton_Left)) {
                if (!ImGui::IsWindowHovered(ImGuiHoveredFlags_AnyWindow)) {
                    m_materialDropRequested = true;
                    m_materialDropName = m_materialDragName;
                }
                m_materialDragActive = false;
            }
        }

        ImGui::Separator();

        // PBR Material Settings
        if (ImGui::CollapsingHeader("Material Properties", ImGuiTreeNodeFlags_DefaultOpen)) {
            if (ImGui::TreeNode("Texture Settings")) {
                float uvScale = renderer.getMaterialUVScale();
                if (ImGui::SliderFloat("UV Scale", &uvScale, 0.01f, 500.0f, "%.2f")) {
                    std::cout << "[ImGui] UV Scale slider changed to " << uvScale << std::endl;
                    renderer.setMaterialUVScale(uvScale);
                    std::cout << "[ImGui] Called setMaterialUVScale, new value = " << renderer.getMaterialUVScale() << std::endl;
                }

                float normalStrength = renderer.getNormalStrength();
                if (ImGui::SliderFloat("Normal Strength", &normalStrength, 0.0f, 2.0f, "%.2f")) {
                    renderer.setNormalStrength(normalStrength);
                }
                ImGui::TreePop();
            }

            if (ImGui::TreeNode("Material Adjustments")) {
                ImGui::TextDisabled("Color Adjustments");

                float brightness = renderer.getMaterialBrightness();
                if (ImGui::SliderFloat("Brightness", &brightness, -0.5f, 0.5f, "%.2f")) {
                    renderer.setMaterialBrightness(brightness);
                }

                float contrast = renderer.getMaterialContrast();
                if (ImGui::SliderFloat("Contrast", &contrast, 0.5f, 2.0f, "%.2f")) {
                    renderer.setMaterialContrast(contrast);
                }

                float saturation = renderer.getMaterialSaturation();
                if (ImGui::SliderFloat("Saturation", &saturation, 0.0f, 2.0f, "%.2f")) {
                    renderer.setMaterialSaturation(saturation);
                }

                vec3 tint = renderer.getMaterialTint();
                float tintArr[3] = {tint.r, tint.g, tint.b};
                if (ImGui::ColorEdit3("Tint", tintArr)) {
                    renderer.setMaterialTint(vec3(tintArr[0], tintArr[1], tintArr[2]));
                }

                ImGui::Separator();
                ImGui::TextDisabled("PBR Adjustments");

                float roughnessOffset = renderer.getMaterialRoughnessOffset();
                if (ImGui::SliderFloat("Roughness Offset", &roughnessOffset, -0.5f, 0.5f, "%.2f")) {
                    renderer.setMaterialRoughnessOffset(roughnessOffset);
                }

                float metallicOffset = renderer.getMaterialMetallicOffset();
                if (ImGui::SliderFloat("Metallic Offset", &metallicOffset, -0.5f, 0.5f, "%.2f")) {
                    renderer.setMaterialMetallicOffset(metallicOffset);
                }

                float aoStrength = renderer.getMaterialAOStrength();
                if (ImGui::SliderFloat("AO Strength", &aoStrength, 0.0f, 2.0f, "%.2f")) {
                    renderer.setMaterialAOStrength(aoStrength);
                }

                ImGui::Separator();
                if (ImGui::Button("Reset All")) {
                    renderer.setMaterialBrightness(0.0f);
                    renderer.setMaterialContrast(1.0f);
                    renderer.setMaterialSaturation(1.0f);
                    renderer.setMaterialTint(vec3(1.0f));
                    renderer.setMaterialRoughnessOffset(0.0f);
                    renderer.setMaterialMetallicOffset(0.0f);
                    renderer.setMaterialAOStrength(1.0f);
                }

                ImGui::TreePop();
            }

            // Wall Materials
            if (ImGui::TreeNode("Wall Material")) {
                float wallMetallic = renderer.getWallMetallic();
                if (ImGui::SliderFloat("Metallic##wall", &wallMetallic, 0.0f, 1.0f, "%.2f")) {
                    renderer.setWallMetallic(wallMetallic);
                }

                float wallRoughness = renderer.getWallRoughness();
                if (ImGui::SliderFloat("Roughness##wall", &wallRoughness, 0.04f, 1.0f, "%.2f")) {
                    renderer.setWallRoughness(wallRoughness);
                }

                // Wall presets
                if (ImGui::Button("Concrete##wall")) {
                    renderer.setWallMetallic(0.0f);
                    renderer.setWallRoughness(0.9f);
                }
                ImGui::SameLine();
                if (ImGui::Button("Stucco##wall")) {
                    renderer.setWallMetallic(0.0f);
                    renderer.setWallRoughness(0.8f);
                }
                ImGui::SameLine();
                if (ImGui::Button("Brick##wall")) {
                    renderer.setWallMetallic(0.0f);
                    renderer.setWallRoughness(0.85f);
                }
                ImGui::TreePop();
            }

            // Roof Materials
            if (ImGui::TreeNode("Roof Material")) {
                float roofMetallic = renderer.getRoofMetallic();
                if (ImGui::SliderFloat("Metallic##roof", &roofMetallic, 0.0f, 1.0f, "%.2f")) {
                    renderer.setRoofMetallic(roofMetallic);
                }

                float roofRoughness = renderer.getRoofRoughness();
                if (ImGui::SliderFloat("Roughness##roof", &roofRoughness, 0.04f, 1.0f, "%.2f")) {
                    renderer.setRoofRoughness(roofRoughness);
                }

                // Roof presets
                if (ImGui::Button("Shingle##roof")) {
                    renderer.setRoofMetallic(0.0f);
                    renderer.setRoofRoughness(0.8f);
                }
                ImGui::SameLine();
                if (ImGui::Button("Metal##roof")) {
                    renderer.setRoofMetallic(0.9f);
                    renderer.setRoofRoughness(0.3f);
                }
                ImGui::SameLine();
                if (ImGui::Button("Tile##roof")) {
                    renderer.setRoofMetallic(0.0f);
                    renderer.setRoofRoughness(0.6f);
                }
                ImGui::TreePop();
            }

            // Default/Other Materials
            if (ImGui::TreeNode("Other Elements")) {
                float metallic = renderer.getDefaultMetallic();
                if (ImGui::SliderFloat("Metallic##default", &metallic, 0.0f, 1.0f, "%.2f")) {
                    renderer.setDefaultMetallic(metallic);
                }

                float roughness = renderer.getDefaultRoughness();
                if (ImGui::SliderFloat("Roughness##default", &roughness, 0.04f, 1.0f, "%.2f")) {
                    renderer.setDefaultRoughness(roughness);
                }

                if (ImGui::Button("Steel##default")) {
                    renderer.setDefaultMetallic(0.95f);
                    renderer.setDefaultRoughness(0.4f);
                }
                ImGui::SameLine();
                if (ImGui::Button("Wood##default")) {
                    renderer.setDefaultMetallic(0.0f);
                    renderer.setDefaultRoughness(0.7f);
                }
                ImGui::SameLine();
                if (ImGui::Button("Concrete##default")) {
                    renderer.setDefaultMetallic(0.0f);
                    renderer.setDefaultRoughness(0.9f);
                }
                ImGui::TreePop();
            }
        }

        ImGui::Separator();

        // Section Clipping Settings
        if (ImGui::CollapsingHeader("Section Clipping", ImGuiTreeNodeFlags_DefaultOpen)) {
            bool clippingEnabled = renderer.getClippingEnabled();
            if (ImGui::Checkbox("Enable Section Cut", &clippingEnabled)) {
                renderer.setClippingEnabled(clippingEnabled);
            }

            if (clippingEnabled) {
                // Axis selection
                const char* axisNames[] = { "X (Left/Right)", "Y (Up/Down)", "Z (Front/Back)" };
                int clipAxis = renderer.getClipAxis();
                if (ImGui::Combo("Cut Axis", &clipAxis, axisNames, 3)) {
                    renderer.setClipAxis(clipAxis);
                }

                // Height/position slider
                float clipHeight = renderer.getClipHeight();
                const char* heightLabel = "Cut Position";
                float minVal = -100.0f;
                float maxVal = 100.0f;

                switch (clipAxis) {
                    case 0: heightLabel = "X Position (ft)"; break;
                    case 1: heightLabel = "Y Position (ft)"; minVal = 0.0f; maxVal = 50.0f; break;
                    case 2: heightLabel = "Z Position (ft)"; break;
                }

                if (ImGui::SliderFloat(heightLabel, &clipHeight, minVal, maxVal, "%.1f")) {
                    renderer.setClipHeight(clipHeight);
                }

                // Flip direction
                bool flipped = renderer.getClipFlipped();
                if (ImGui::Checkbox("Flip Cut Direction", &flipped)) {
                    renderer.setClipFlipped(flipped);
                }

                ImGui::Separator();

                // Quick section presets
                ImGui::Text("Quick Sections:");
                if (ImGui::Button("Floor Plan (Y=4ft)")) {
                    renderer.setClipAxis(1);
                    renderer.setClipHeight(4.0f);
                    renderer.setClipFlipped(false);
                }
                ImGui::SameLine();
                if (ImGui::Button("Roof Plan (Y=10ft)")) {
                    renderer.setClipAxis(1);
                    renderer.setClipHeight(10.0f);
                    renderer.setClipFlipped(false);
                }

                if (ImGui::Button("Section A-A (X=0)")) {
                    renderer.setClipAxis(0);
                    renderer.setClipHeight(0.0f);
                    renderer.setClipFlipped(false);
                }
                ImGui::SameLine();
                if (ImGui::Button("Section B-B (Z=0)")) {
                    renderer.setClipAxis(2);
                    renderer.setClipHeight(0.0f);
                    renderer.setClipFlipped(false);
                }

                ImGui::Separator();

                // Help text
                ImGui::TextWrapped("Section clipping cuts away geometry to show interior views. "
                                   "Use Y axis for floor plans, X/Z for building sections.");
            }
        }

        ImGui::Separator();

        // High-Resolution Render
        if (ImGui::CollapsingHeader("High-Resolution Render")) {
            ImGui::TextDisabled("Render high-quality images for presentations");

            // Render mode selector (Rasterizer vs Path Tracer)
            const char* renderModeItems[] = { "Rasterizer (Fast)", "Path Tracer (Quality)" };
            ImGui::Combo("Render Mode", &m_renderMode, renderModeItems, 2);
            ImGui::SetItemTooltip("Rasterizer: Fast real-time rendering\nPath Tracer: Physically accurate global illumination");

            ImGui::Separator();

            // Resolution selector
            const char* resolutionItems[] = { "4K (3840x2160)", "6K (6144x3456)", "8K (7680x4320)" };
            ImGui::Combo("Resolution", &m_renderResolution, resolutionItems, 3);

            // Path tracer specific settings
            if (m_renderMode == 1) {
                ImGui::SliderInt("PT Samples", &m_ptSamples, 16, 512);
                ImGui::SetItemTooltip("Samples per pixel. Higher = less noise, longer render time.\n64-128 for preview, 256-512 for final.");

                ImGui::SliderInt("PT Bounces", &m_ptBounces, 2, 12);
                ImGui::SetItemTooltip("Max light bounces. Higher = more accurate indirect lighting.\n4-6 for interiors, 6-8 for complex scenes.");
            }

            // Samples selector (for rasterizer accumulation/AA)
            if (m_renderMode == 0) {
                const char* sampleItems[] = { "1 (Fast)", "16 (Good)", "64 (High)", "256 (Best)" };
                ImGui::Combo("Samples", &m_renderSamples, sampleItems, 4);
                ImGui::SetItemTooltip("Higher samples = less noise, longer render time");
            }

            // Format selector
            const char* formatItems[] = { "PNG (8-bit)", "EXR (HDR 32-bit)" };
            ImGui::Combo("Format", &m_renderFormat, formatItems, 2);

            // Brightness adjustment (no bloom/SSAO in high-res - use <1.0 to avoid washing out)
            ImGui::SliderFloat("Brightness", &m_renderBrightness, 0.5f, 2.0f, "%.2fx");
            ImGui::SetItemTooltip("1.0 = use viewport exposure. Try 0.7-0.8 to match viewport with bloom.");

            // Post-processing preset
            const char* postProcessItems[] = { "None", "Subtle", "Vivid", "Warm", "Architectural", "Golden Hour", "Print Ready" };
            ImGui::Combo("Post-Process", &m_renderPostProcess, postProcessItems, 7);
            ImGui::SetItemTooltip("Apply color grading. Use 'Print Ready' for boosted saturation that survives printing.");

            // Advanced post-process controls
            ImGui::Checkbox("Advanced Post-Process", &m_showPostProcessAdvanced);
            ImGui::SetItemTooltip("Fine-tune post-processing parameters. Leave at default to use preset values.");

            if (m_showPostProcessAdvanced) {
                ImGui::Indent();
                ImGui::TextDisabled("Adjust post-processing parameters (default uses preset):");

                // Saturation
                ImGui::SliderFloat("Saturation", &m_postSaturation, -1.0f, 1.0f, "%.2f");
                ImGui::SetItemTooltip("-1 = preset default. Higher = more color vibrancy.");

                // Vibrance
                ImGui::SliderFloat("Vibrance", &m_postVibrance, -1.0f, 1.0f, "%.2f");
                ImGui::SetItemTooltip("-1 = preset default. Boosts less-saturated colors more.");

                // Contrast
                ImGui::SliderFloat("Contrast", &m_postContrast, -1.0f, 1.0f, "%.2f");
                ImGui::SetItemTooltip("-1 = preset default. Higher = more contrast.");

                // Sharpness
                ImGui::SliderFloat("Sharpness", &m_postSharpness, -1.0f, 1.0f, "%.2f");
                ImGui::SetItemTooltip("-1 = preset default. Higher = sharper edges.");

                // Exposure
                ImGui::SliderFloat("Post Exposure", &m_postExposure, -1.0f, 1.0f, "%.2f");
                ImGui::SetItemTooltip("-1 = preset default. Positive = brighter, negative = darker.");

                // Vignette
                ImGui::SliderFloat("Vignette", &m_postVignette, -1.0f, 1.0f, "%.2f");
                ImGui::SetItemTooltip("-1 = preset default. Higher = darker edges.");

                ImGui::Unindent();
            }

            ImGui::Separator();

            // Upscaling option
            ImGui::Checkbox("Upscale to target", &m_renderUpscale);
            ImGui::SetItemTooltip("Render at 4K and AI-upscale to 6K/8K (faster, nearly same quality)");

            if (m_renderUpscale && m_renderResolution > 0) {
                const char* upscaleMethodItems[] = { "Real-ESRGAN (AI)", "Lanczos (Fast)" };
                ImGui::Combo("Upscale Method", &m_renderUpscaleMethod, upscaleMethodItems, 2);

                if (m_renderResolution == 1) {
                    ImGui::TextDisabled("Will render 4K -> upscale 1.6x to 6K");
                } else if (m_renderResolution == 2) {
                    ImGui::TextDisabled("Will render 4K -> upscale 2x to 8K");
                }

                // Server controls for AI upscaling
                if (m_renderUpscaleMethod == 0) {
                    ImGui::Spacing();
                    if (ImGui::Button("Start Upscale Server")) {
                        m_startRenderServerRequested = true;
                    }
                    ImGui::SameLine();
                    if (ImGui::Button("Stop Server")) {
                        m_stopRenderServerRequested = true;
                    }
                    ImGui::SetItemTooltip("Real-ESRGAN requires the render server running on port 5000");
                }
            }

            ImGui::Separator();

            // Output path with auto-generate button
            ImGui::Text("Output:");
            ImGui::InputText("##OutputPath", m_renderOutputPath, sizeof(m_renderOutputPath));
            ImGui::SameLine();
            if (ImGui::Button("New")) {
                // Generate timestamped filename
                auto now = std::chrono::system_clock::now();
                auto time = std::chrono::system_clock::to_time_t(now);
                std::tm tm = *std::localtime(&time);

                const char* resNames[] = { "4K", "6K", "8K" };
                const int sampleCounts[] = { 1, 16, 64, 256 };

                char timestamp[64];
                std::strftime(timestamp, sizeof(timestamp), "%Y%m%d_%H%M%S", &tm);

                const char* ext = (m_renderFormat == 0) ? "png" : "exr";
                snprintf(m_renderOutputPath, sizeof(m_renderOutputPath),
                    "renders/render_%s_%s_%dspp.%s",
                    timestamp, resNames[m_renderResolution],
                    sampleCounts[m_renderSamples], ext);
            }
            ImGui::SetItemTooltip("Generate unique timestamped filename");

            // Show estimated file size
            const char* resNames[] = { "4K", "6K", "8K" };
            const int widths[] = { 3840, 6144, 7680 };
            const int heights[] = { 2160, 3456, 4320 };
            size_t pixels = static_cast<size_t>(widths[m_renderResolution]) * heights[m_renderResolution];
            size_t estimatedSize = (m_renderFormat == 0) ? pixels * 4 / 3 : pixels * 16; // PNG compressed, EXR HDR
            ImGui::TextDisabled("Est. size: %.1f MB (%s)", estimatedSize / (1024.0f * 1024.0f), resNames[m_renderResolution]);

            // Render button
            bool canRender = !m_highResRenderInFlight;
            if (!canRender) {
                ImGui::BeginDisabled();
            }

            if (ImGui::Button("Render Image", ImVec2(-1, 30))) {
                // Auto-generate unique filename if using default or file exists
                namespace fs = std::filesystem;
                fs::path currentPath(m_renderOutputPath);
                std::string filename = currentPath.filename().string();
                bool isDefault = (filename == "render.png" || filename == "render.exr");
                bool fileExists = fs::exists(currentPath);

                if (isDefault || fileExists) {
                    // Generate timestamped filename in the same directory
                    auto now = std::chrono::system_clock::now();
                    auto time = std::chrono::system_clock::to_time_t(now);
                    std::tm tm = *std::localtime(&time);

                    const char* resNamesAuto[] = { "4K", "6K", "8K" };
                    const int sampleCountsAuto[] = { 1, 16, 64, 256 };

                    char timestamp[64];
                    std::strftime(timestamp, sizeof(timestamp), "%Y%m%d_%H%M%S", &tm);

                    const char* ext = (m_renderFormat == 0) ? "png" : "exr";
                    char newFilename[128];
                    snprintf(newFilename, sizeof(newFilename),
                        "render_%s_%s_%dspp.%s",
                        timestamp, resNamesAuto[m_renderResolution],
                        sampleCountsAuto[m_renderSamples], ext);

                    fs::path newPath = currentPath.parent_path() / newFilename;
                    snprintf(m_renderOutputPath, sizeof(m_renderOutputPath), "%s", newPath.string().c_str());
                }

                // Build the request
                m_highResRenderRequest.outputPath = m_renderOutputPath;
                m_highResRenderRequest.resolution = m_renderResolution;

                // Convert sample index to actual sample count
                const int sampleCounts[] = { 1, 16, 64, 256 };
                m_highResRenderRequest.samples = sampleCounts[m_renderSamples];

                m_highResRenderRequest.format = m_renderFormat;
                m_highResRenderRequest.upscale = m_renderUpscale && m_renderResolution > 0;
                m_highResRenderRequest.upscaleMethod = m_renderUpscaleMethod;
                m_highResRenderRequest.brightness = m_renderBrightness;
                m_highResRenderRequest.postProcessPreset = m_renderPostProcess;
                m_highResRenderRequest.postExposure = m_postExposure;
                m_highResRenderRequest.postContrast = m_postContrast;
                m_highResRenderRequest.postSaturation = m_postSaturation;
                m_highResRenderRequest.postVibrance = m_postVibrance;
                m_highResRenderRequest.postSharpness = m_postSharpness;
                m_highResRenderRequest.postVignette = m_postVignette;

                // Path tracer settings
                m_highResRenderRequest.renderMode = m_renderMode;
                m_highResRenderRequest.ptSamples = m_ptSamples;
                m_highResRenderRequest.ptBounces = m_ptBounces;

                m_highResRenderRequested = true;
            }

            if (!canRender) {
                ImGui::EndDisabled();
            }

            // Quick preview button for post-process tuning
            if (ImGui::Button("Preview Post-Process (1080p Fast)", ImVec2(-1, 25))) {
                m_previewRequested = true;
                // Generate temp preview filename
                namespace fs = std::filesystem;
                fs::path renderPath(m_renderOutputPath);
                fs::path previewDir = renderPath.parent_path() / "previews";
                fs::create_directories(previewDir);
                m_previewImagePath = (previewDir / "preview.png").string();
            }
            ImGui::SetItemTooltip("Quick render at 1080p to test post-processing settings (much faster than full render)");

            // Progress and status
            if (m_highResRenderInFlight) {
                ImGui::ProgressBar(m_highResRenderProgress, ImVec2(-1, 0));
            }

            if (!m_highResRenderStatus.empty()) {
                ImGui::Text("Status: %s", m_highResRenderStatus.c_str());
            }

            // Resolution info
            ImGui::Separator();
            ImGui::TextDisabled("Resolution Details:");
            const char* resInfo[] = {
                "4K: 3840x2160 (8.3 MP) - Standard presentation",
                "6K: 6144x3456 (21 MP) - Large format print",
                "8K: 7680x4320 (33 MP) - Ultra high detail"
            };
            ImGui::TextWrapped("%s", resInfo[m_renderResolution]);
        }

        ImGui::Separator();

        // Debug Visualization modes
        if (ImGui::CollapsingHeader("Debug Visualization")) {
            ImGui::TextColored(ImVec4(1.0f, 0.8f, 0.3f, 1.0f), "Use these to verify effects are working");

            // Material Test Scene (PBR Validation) - Quick access
            ImGui::Spacing();
            if (ImGui::Button("Open Material Test Window")) {
                m_showMaterialTestWindow = true;
            }
            ImGui::SameLine();
            bool showTestScene = renderer.getShowMaterialTestScene();
            if (ImGui::Checkbox("Show Spheres", &showTestScene)) {
                renderer.setShowMaterialTestScene(showTestScene);
            }
            ImGui::SetItemTooltip("Tools > Material Test (PBR) for full controls");
            ImGui::Spacing();

            // Shader Effect Toggles
            ImGui::Text("Shader Effects:");
            ImGui::Indent();

            bool iblEnabled = renderer.getIBLEnabled();
            if (ImGui::Checkbox("IBL (Ambient Lighting)", &iblEnabled)) {
                renderer.setIBLEnabled(iblEnabled);
            }
            ImGui::SetItemTooltip("Image-Based Lighting: ambient light from environment map");

            bool directLightEnabled = renderer.getDirectLightEnabled();
            if (ImGui::Checkbox("Direct Light (Sun)", &directLightEnabled)) {
                renderer.setDirectLightEnabled(directLightEnabled);
            }
            ImGui::SetItemTooltip("Direct lighting from sun and additional lights");

            bool normalMappingEnabled = renderer.getNormalMappingEnabled();
            if (ImGui::Checkbox("Normal Mapping", &normalMappingEnabled)) {
                renderer.setNormalMappingEnabled(normalMappingEnabled);
            }
            ImGui::SetItemTooltip("Surface detail from normal maps");

            ImGui::Unindent();
            ImGui::Spacing();

            // IBL Intensity Settings (collapsible)
            if (ImGui::TreeNode("IBL Settings")) {
                float iblOverall = renderer.getIBLIntensity();
                if (ImGui::SliderFloat("Overall Intensity", &iblOverall, 0.0f, 3.0f, "%.2f")) {
                    renderer.setIBLIntensity(iblOverall);
                }
                ImGui::SetItemTooltip("Master intensity for all IBL (ambient lighting)");

                float iblDiffuse = renderer.getIBLDiffuseIntensity();
                if (ImGui::SliderFloat("Diffuse Intensity", &iblDiffuse, 0.0f, 3.0f, "%.2f")) {
                    renderer.setIBLDiffuseIntensity(iblDiffuse);
                }
                ImGui::SetItemTooltip("Diffuse ambient from environment (irradiance map)");

                float iblSpecular = renderer.getIBLSpecularIntensity();
                if (ImGui::SliderFloat("Specular Intensity", &iblSpecular, 0.0f, 3.0f, "%.2f")) {
                    renderer.setIBLSpecularIntensity(iblSpecular);
                }
                ImGui::SetItemTooltip("Specular reflections from environment (prefiltered map)\nReduce this to fix white film on glossy surfaces");

                float fresnel = renderer.getFresnelIntensity();
                if (ImGui::SliderFloat("Fresnel Intensity", &fresnel, 0.0f, 2.0f, "%.2f")) {
                    renderer.setFresnelIntensity(fresnel);
                }
                ImGui::SetItemTooltip("Fresnel effect strength (edge reflectivity)\nReducing this makes surfaces less reflective at grazing angles");

                if (ImGui::Button("Reset IBL")) {
                    renderer.setIBLIntensity(1.0f);
                    renderer.setIBLDiffuseIntensity(1.0f);
                    renderer.setIBLSpecularIntensity(0.4f);
                    renderer.setFresnelIntensity(0.6f);
                }

                ImGui::TreePop();
            }
            ImGui::Spacing();

            // Post-processing debug mode
            ImGui::Text("Post-Processing:");
            const char* ppDebugModes[] = { "None (Normal)", "SSAO Only", "Bloom Only", "HDR Scene (No FX)", "Depth Edges", "SSR Only", "Normals" };
            int currentPPDebug = static_cast<int>(renderer.getPostProcessDebugMode());
            if (ImGui::Combo("PP Debug Mode", &currentPPDebug, ppDebugModes, IM_ARRAYSIZE(ppDebugModes))) {
                renderer.setPostProcessDebugMode(static_cast<PostProcessDebugMode>(currentPPDebug));
            }
            if (ImGui::IsItemHovered()) {
                ImGui::SetTooltip(
                    "None: Normal rendering with all effects\n"
                    "SSAO Only: Show ambient occlusion buffer (dark = occluded)\n"
                    "Bloom Only: Show bloom contribution\n"
                    "HDR Scene: Scene without SSAO/bloom (tests tonemapping)\n"
                    "Depth Edges: Show depth-based edge detection\n"
                    "SSR Only: Show screen-space reflections\n"
                    "Normals: Show normal buffer"
                );
            }

            ImGui::Spacing();

            // Material/Displacement debug mode
            ImGui::Text("Material/Lighting Debug:");
            const char* matDebugModes[] = {
                "None (Normal)", "Displacement", "POM Depth", "Normals", "UVs", "AO Map",
                "Specular IBL", "Diffuse IBL", "Total Ambient", "BRDF LUT", "Direct Light", "Fresnel"
            };
            int currentMatDebug = static_cast<int>(renderer.getMaterialDebugMode());
            if (ImGui::Combo("Material Debug Mode", &currentMatDebug, matDebugModes, IM_ARRAYSIZE(matDebugModes))) {
                renderer.setMaterialDebugMode(static_cast<MaterialDebugMode>(currentMatDebug));
            }
            if (ImGui::IsItemHovered()) {
                ImGui::SetTooltip(
                    "None: Normal rendering\n"
                    "Displacement: Show tessellation displacement\n"
                    "POM Depth: Show parallax depth offset\n"
                    "Normals: Show surface normals\n"
                    "UVs: Show UV coordinates\n"
                    "AO Map: Show ambient occlusion texture\n"
                    "Specular IBL: Show specular reflection contribution\n"
                    "Diffuse IBL: Show diffuse ambient contribution\n"
                    "Total Ambient: Show combined ambient lighting\n"
                    "BRDF LUT: Show BRDF lookup (R=scale, G=bias)\n"
                    "Direct Light: Show sun/lights only (no ambient)\n"
                    "Fresnel: Show surface reflectivity"
                );
            }

            ImGui::Spacing();

            // Quick reset button
            if (ImGui::Button("Reset All Debug Modes")) {
                renderer.setPostProcessDebugMode(PostProcessDebugMode::None);
                renderer.setMaterialDebugMode(MaterialDebugMode::None);
                renderer.setIBLEnabled(true);
                renderer.setDirectLightEnabled(true);
                renderer.setNormalMappingEnabled(true);
            }
        }

        ImGui::Separator();

        // Visualization mode (moved from elsewhere for convenience)
        if (ImGui::CollapsingHeader("Visualization")) {
            VisualizationMode mode = renderer.getVisualizationMode();
            const char* modeNames[] = { "Structural", "Thermal", "Lighting", "Acoustic", "Material", "Wireframe" };
            int currentMode = static_cast<int>(mode);
            if (ImGui::Combo("Mode", &currentMode, modeNames, 6)) {
                renderer.setVisualizationMode(static_cast<VisualizationMode>(currentMode));
            }
        }
    }
    ImGui::End();
}

bool ImGuiLayer::takeMaterialDrop(std::string& outName) {
    if (!m_materialDropRequested) {
        return false;
    }

    outName = m_materialDropName;
    m_materialDropRequested = false;
    m_materialDropName.clear();
    return true;
}

ImGuiLayer::MaterialGenerateRequest ImGuiLayer::takeMaterialGenerateRequest() {
    m_materialGenerateRequested = false;
    return m_materialGenerateRequest;
}

void ImGuiLayer::setMaterialGenerationState(bool inFlight, const std::string& status) {
    m_materialGenerateInFlight = inFlight;
    m_materialGenerateStatus = status;
}

ImGuiLayer::MaterialUpscaleRequest ImGuiLayer::takeMaterialUpscaleRequest() {
    m_materialUpscaleRequested = false;
    return m_materialUpscaleRequest;
}

void ImGuiLayer::setMaterialUpscaleState(bool inFlight, const std::string& status) {
    m_materialUpscaleInFlight = inFlight;
    m_materialUpscaleStatus = status;
}

ImGuiLayer::HeightGenRequest ImGuiLayer::takeHeightGenRequest() {
    m_heightGenRequested = false;
    return m_heightGenRequest;
}

void ImGuiLayer::setHeightGenState(bool inFlight, const std::string& status) {
    m_heightGenInFlight = inFlight;
    m_heightGenStatus = status;
}

ImGuiLayer::HighResRenderRequest ImGuiLayer::takeHighResRenderRequest() {
    m_highResRenderRequested = false;
    return m_highResRenderRequest;
}

void ImGuiLayer::setHighResRenderState(bool inFlight, const std::string& status, float progress) {
    m_highResRenderInFlight = inFlight;
    m_highResRenderStatus = status;
    m_highResRenderProgress = progress;
}

float ImGuiLayer::getSnapPlaneHeight() const {
    switch (m_snapPlane) {
        case SnapPlane::Ground:  return 0.0f;       // Ground level
        case SnapPlane::Floor1:  return 8.0f;       // ~8ft ceiling for floor 1
        case SnapPlane::Floor2:  return 18.0f;      // ~18ft for floor 2 ceiling
        case SnapPlane::Floor3:  return 28.0f;      // ~28ft for floor 3 ceiling
        case SnapPlane::Ceiling: return 10.0f;      // Default ceiling height
        case SnapPlane::Custom:  return m_customSnapHeight;
        default: return 8.0f;
    }
}

void ImGuiLayer::drawPreviewWindow() {
    if (!m_showPreviewWindow) return;

    ImGui::SetNextWindowSize(ImVec2(500, 400), ImGuiCond_FirstUseEver);
    if (ImGui::Begin("Print Preview", &m_showPreviewWindow)) {
        ImGui::TextDisabled("Post-Process Preview (1080p Fast Render)");

        ImGui::Spacing();

        if (!m_previewImagePath.empty()) {
            ImGui::Text("Preview saved to:");
            ImGui::TextWrapped("%s", m_previewImagePath.c_str());

            ImGui::Spacing();
            ImGui::Separator();
            ImGui::Spacing();

            ImGui::Text("Instructions:");
            ImGui::BulletText("Open the preview image in an image viewer to see results");
            ImGui::BulletText("Adjust post-processing sliders above");
            ImGui::BulletText("Click 'Preview Post-Process' again to re-render with new settings");
            ImGui::BulletText("When satisfied, do a full high-res render");

            ImGui::Spacing();
            ImGui::Separator();
            ImGui::Spacing();

            // Current settings display
            ImGui::Text("Current Post-Process Settings:");
            const char* presetNames[] = { "None", "Subtle", "Vivid", "Warm", "Architectural", "Golden Hour", "Print Ready" };
            ImGui::Text("Preset: %s", presetNames[m_renderPostProcess]);

            if (m_showPostProcessAdvanced) {
                if (m_postSaturation >= 0.0f) ImGui::Text("Saturation: %.2f", m_postSaturation);
                if (m_postVibrance >= 0.0f) ImGui::Text("Vibrance: %.2f", m_postVibrance);
                if (m_postContrast >= 0.0f) ImGui::Text("Contrast: %.2f", m_postContrast);
                if (m_postSharpness >= 0.0f) ImGui::Text("Sharpness: %.2f", m_postSharpness);
                if (m_postExposure >= 0.0f) ImGui::Text("Exposure: %.2f", m_postExposure);
                if (m_postVignette >= 0.0f) ImGui::Text("Vignette: %.2f", m_postVignette);
            } else {
                ImGui::TextDisabled("(using preset defaults)");
            }

            ImGui::Spacing();

            // Quick actions
            if (ImGui::Button("Open in File Explorer")) {
                std::string cmd = "explorer /select,\"" + m_previewImagePath + "\"";
                std::system(cmd.c_str());
            }

            ImGui::SameLine();
            if (ImGui::Button("Close")) {
                m_showPreviewWindow = false;
            }
        } else {
            ImGui::Text("No preview available.");
            ImGui::Text("Click 'Preview Post-Process' in Render Settings to generate one.");
        }
    }
    ImGui::End();
}

// ============================================================================
// Live Render Preview Panel (GPU-Direct Inline Preview)
// ============================================================================

void ImGuiLayer::drawRenderPreviewPanel(Renderer& renderer) {
    if (!m_showRenderPreviewPanel) return;

    ImGui::SetNextWindowSize(ImVec2(680, 440), ImGuiCond_FirstUseEver);
    if (ImGui::Begin("Render Preview", &m_showRenderPreviewPanel)) {
        // Refresh button
        if (ImGui::Button("Refresh Preview")) {
            m_renderPreviewRefreshRequested = true;
        }

        ImGui::SameLine();
        ImGui::TextDisabled("(?)");
        if (ImGui::IsItemHovered()) {
            ImGui::BeginTooltip();
            ImGui::Text("Renders the current view at 640x360 directly to GPU.");
            ImGui::Text("Fast (~50ms) for quick iteration on materials and lighting.");
            ImGui::Text("Material overrides will appear in the preview.");
            ImGui::EndTooltip();
        }

        ImGui::Separator();

        // Display preview info
        ImGui::Text("Resolution: %u x %u", renderer.getPreviewWidth(), renderer.getPreviewHeight());
        ImGui::SameLine();
        ImGui::TextDisabled("| Single sample | GPU-direct");

        ImGui::Spacing();

        // Get the preview texture descriptor
        VkDescriptorSet tex = renderer.getPreviewDescriptor();

        if (tex != VK_NULL_HANDLE && renderer.hasPreviewResources()) {
            // Calculate display size maintaining 16:9 aspect ratio
            ImVec2 availSize = ImGui::GetContentRegionAvail();
            float previewAspect = static_cast<float>(renderer.getPreviewWidth()) /
                                  static_cast<float>(renderer.getPreviewHeight());

            ImVec2 displaySize;
            if (availSize.x / availSize.y > previewAspect) {
                // Window is wider than preview - fit to height
                displaySize.y = availSize.y - 10.0f;  // Small margin
                displaySize.x = displaySize.y * previewAspect;
            } else {
                // Window is taller than preview - fit to width
                displaySize.x = availSize.x - 10.0f;  // Small margin
                displaySize.y = displaySize.x / previewAspect;
            }

            // Ensure minimum size
            displaySize.x = std::max(displaySize.x, 320.0f);
            displaySize.y = std::max(displaySize.y, 180.0f);

            // Center the image
            float offsetX = (availSize.x - displaySize.x) * 0.5f;
            if (offsetX > 0) {
                ImGui::SetCursorPosX(ImGui::GetCursorPosX() + offsetX);
            }

            // Display the preview image
            ImGui::Image((ImTextureID)tex, displaySize);

            // Show status
            ImGui::Spacing();
            ImGui::TextColored(ImVec4(0.5f, 0.8f, 0.5f, 1.0f), "Preview ready");
        } else {
            // No preview yet
            ImVec2 placeholderSize(640.0f, 360.0f);
            ImVec2 availSize = ImGui::GetContentRegionAvail();

            // Scale down if needed
            if (placeholderSize.x > availSize.x - 10.0f) {
                float scale = (availSize.x - 10.0f) / placeholderSize.x;
                placeholderSize.x *= scale;
                placeholderSize.y *= scale;
            }

            // Draw placeholder box
            ImVec2 cursorPos = ImGui::GetCursorScreenPos();
            float offsetX = (availSize.x - placeholderSize.x) * 0.5f;
            if (offsetX > 0) {
                cursorPos.x += offsetX;
                ImGui::SetCursorPosX(ImGui::GetCursorPosX() + offsetX);
            }

            ImDrawList* drawList = ImGui::GetWindowDrawList();
            drawList->AddRectFilled(
                cursorPos,
                ImVec2(cursorPos.x + placeholderSize.x, cursorPos.y + placeholderSize.y),
                IM_COL32(40, 40, 50, 255)
            );
            drawList->AddRect(
                cursorPos,
                ImVec2(cursorPos.x + placeholderSize.x, cursorPos.y + placeholderSize.y),
                IM_COL32(80, 80, 100, 255)
            );

            // Center text in placeholder
            const char* text = "Click 'Refresh Preview' to render";
            ImVec2 textSize = ImGui::CalcTextSize(text);
            ImVec2 textPos(
                cursorPos.x + (placeholderSize.x - textSize.x) * 0.5f,
                cursorPos.y + (placeholderSize.y - textSize.y) * 0.5f
            );
            drawList->AddText(textPos, IM_COL32(150, 150, 150, 255), text);

            // Advance cursor past placeholder
            ImGui::Dummy(placeholderSize);

            ImGui::Spacing();
            ImGui::TextColored(ImVec4(0.6f, 0.6f, 0.6f, 1.0f), "No preview rendered yet");
        }
    }
    ImGui::End();
}

// ============================================================================
// Material Test Window (PBR Validation)
// ============================================================================

void ImGuiLayer::drawMaterialTestWindow(Renderer& renderer, Camera& camera) {
    if (!m_showMaterialTestWindow) return;

    ImGui::SetNextWindowSize(ImVec2(350, 400), ImGuiCond_FirstUseEver);
    if (ImGui::Begin("Material Test", &m_showMaterialTestWindow)) {
        ImGui::TextColored(ImVec4(0.8f, 0.6f, 0.2f, 1.0f), "PBR Validation Scene");
        ImGui::TextWrapped("Test spheres with varying roughness and metallic values to validate IBL and lighting.");
        ImGui::Separator();

        // Show/Hide toggle
        bool showTestScene = renderer.getShowMaterialTestScene();
        if (ImGui::Checkbox("Show Test Spheres", &showTestScene)) {
            renderer.setShowMaterialTestScene(showTestScene);
        }

        // Focus camera button
        if (ImGui::Button("Focus Camera on Test Scene")) {
            camera.position = renderer.getMaterialTestSceneCameraPosition();
            camera.target = renderer.getMaterialTestSceneCameraTarget();
        }
        ImGui::SetItemTooltip("Move camera to view the material test spheres");

        ImGui::Separator();

        // Preset selector
        ImGui::Text("Test Preset:");
        const char* presetNames[] = {
            "Full Grid (all spheres)",
            "Dielectrics Only (metallic=0)",
            "Metals Only (metallic=1)",
            "Roughness Row (mid metallic)",
            "Metallic Column (mid roughness)"
        };

        int currentPreset = renderer.getMaterialTestPreset();
        for (int i = 0; i < 5; ++i) {
            if (ImGui::RadioButton(presetNames[i], currentPreset == i)) {
                renderer.setMaterialTestPreset(i);
                m_materialTestPreset = i;
            }
        }

        ImGui::Separator();

        // Grid size
        int gridSize = renderer.getMaterialTestGridSize();
        if (ImGui::SliderInt("Grid Size", &gridSize, 3, 9, "%dx%d")) {
            renderer.setMaterialTestGridSize(gridSize);
        }

        ImGui::Separator();

        // Reference guide
        if (ImGui::CollapsingHeader("How to Read", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::BulletText("X-axis: Roughness 0 (left) to 1 (right)");
            ImGui::BulletText("Y-axis: Metallic 0 (bottom) to 1 (top)");
            ImGui::Spacing();
            ImGui::TextColored(ImVec4(0.5f, 0.8f, 0.5f, 1.0f), "Expected appearance:");
            ImGui::BulletText("Bottom-left: Glossy plastic");
            ImGui::BulletText("Bottom-right: Matte plastic/rubber");
            ImGui::BulletText("Top-left: Mirror-like metal");
            ImGui::BulletText("Top-right: Brushed/rough metal");
        }

        if (ImGui::CollapsingHeader("IBL Tuning Tips")) {
            ImGui::TextWrapped(
                "If metals look too bright or have white film:\n"
                "- Reduce Specular Intensity\n"
                "- Reduce Fresnel Intensity\n\n"
                "If dielectrics look too flat:\n"
                "- Increase Diffuse Intensity\n\n"
                "If everything looks washed out:\n"
                "- Reduce Overall Intensity"
            );
        }
    }
    ImGui::End();
}

// ============================================================================
// Material Library Panel (Improved with categories and grid view)
// ============================================================================

void ImGuiLayer::drawMaterialLibraryPanel(Renderer& renderer) {
    if (!m_showMaterialLibrary) return;

    // Auto-generate material previews on first open
    static bool previewsGenerated = false;
    if (!previewsGenerated) {
        renderer.generateMaterialPreviews();
        previewsGenerated = true;
    }

    ImGui::SetNextWindowSize(ImVec2(450, 600), ImGuiCond_FirstUseEver);
    if (ImGui::Begin("Material Library", &m_showMaterialLibrary)) {
        // Header with filter and view options
        ImGui::TextDisabled("Browse and Apply Materials");
        ImGui::Separator();

        // Filter input
        ImGui::PushItemWidth(-1);
        if (ImGui::InputText("##Filter", m_materialLibraryFilter, sizeof(m_materialLibraryFilter),
                            ImGuiInputTextFlags_EnterReturnsTrue)) {
            // Filter updated
        }
        ImGui::PopItemWidth();
        if (ImGui::IsItemHovered()) {
            ImGui::SetTooltip("Filter materials by name");
        }

        // View mode toggle and thumbnail size
        ImGui::Spacing();
        const char* viewModes[] = { "Grid", "List" };
        ImGui::SetNextItemWidth(100);
        ImGui::Combo("View", &m_materialLibraryViewMode, viewModes, 2);

        if (m_materialLibraryViewMode == 0) {  // Grid view
            ImGui::SameLine();
            ImGui::SetNextItemWidth(150);
            if (ImGui::SliderFloat("Size", &m_materialThumbnailSize, 80.0f, 250.0f, "%.0f")) {
                // Clamp to reasonable range
                m_materialThumbnailSize = std::max(80.0f, std::min(250.0f, m_materialThumbnailSize));
            }
        }

        ImGui::Spacing();
        ImGui::Separator();

        // Get materials from renderer using the C API
        auto materials = renderer.getMaterialNames();
        std::string filter = m_materialLibraryFilter;

        // Group materials by category based on name patterns
        std::map<std::string, std::vector<std::string>> categorizedMaterials;
        std::vector<std::string> uncategorizedMaterials;

        // Helper to determine category from material name
        auto getCategoryFromName = [](const std::string& name) -> std::string {
            std::string lowerName = name;
            std::transform(lowerName.begin(), lowerName.end(), lowerName.begin(), ::tolower);

            // Check for roof materials
            if (lowerName.find("roof") == 0 || lowerName.find("shingle") != std::string::npos ||
                lowerName.find("tile_") == 0) {
                return "Roofs";
            }

            // Check for floor materials
            if (lowerName.find("floor") == 0 || lowerName.find("wood_") == 0 ||
                lowerName.find("tile") != std::string::npos || lowerName.find("marble") != std::string::npos ||
                lowerName.find("stone_") == 0) {
                return "Floors";
            }

            // Check for wall materials
            if (lowerName.find("brick") == 0 || lowerName.find("siding") == 0 ||
                lowerName.find("paint") == 0 || lowerName.find("concrete") == 0 ||
                lowerName.find("stucco") == 0 || lowerName.find("drywall") != std::string::npos ||
                lowerName.find("plaster") != std::string::npos) {
                return "Walls";
            }

            // Check for metal materials
            if (lowerName.find("metal") == 0 || lowerName.find("steel") != std::string::npos ||
                lowerName.find("aluminum") != std::string::npos || lowerName.find("copper") != std::string::npos) {
                return "Metals";
            }

            // Check for glass
            if (lowerName.find("glass") != std::string::npos || lowerName.find("window") != std::string::npos) {
                return "Glass";
            }

            return "";
        };

        for (const auto& material : materials) {
            // Apply filter
            if (!filter.empty()) {
                std::string lowerMaterial = material;
                std::string lowerFilter = filter;
                std::transform(lowerMaterial.begin(), lowerMaterial.end(), lowerMaterial.begin(), ::tolower);
                std::transform(lowerFilter.begin(), lowerFilter.end(), lowerFilter.begin(), ::tolower);
                if (lowerMaterial.find(lowerFilter) == std::string::npos) {
                    continue;
                }
            }

            // Categorize based on name patterns
            std::string category = getCategoryFromName(material);
            if (!category.empty()) {
                categorizedMaterials[category].push_back(material);
            } else {
                uncategorizedMaterials.push_back(material);
            }
        }

        // Display materials by category
        float windowWidth = ImGui::GetContentRegionAvail().x;
        int itemsPerRow = std::max(1, static_cast<int>(windowWidth / (m_materialThumbnailSize + 10)));

        // Helper to draw material item
        auto drawMaterialItem = [&](const std::string& materialName) {
            // Extract just the name part (after last slash)
            std::string displayName = materialName;
            size_t lastSlash = materialName.find_last_of('/');
            if (lastSlash != std::string::npos) {
                displayName = materialName.substr(lastSlash + 1);
            }

            bool isSelected = (m_selectedMaterialName == materialName);

            if (m_materialLibraryViewMode == 0) {  // Grid view
                ImGui::PushID(materialName.c_str());

                // Thumbnail button
                ImVec2 thumbSize(m_materialThumbnailSize, m_materialThumbnailSize * 0.75f);

                // Try to get material preview texture
                VkDescriptorSet previewTex = renderer.getMaterialPreviewDescriptor(materialName);
                bool hasPreview = (previewTex != VK_NULL_HANDLE);

                if (hasPreview) {
                    // Render actual material preview
                    if (ImGui::ImageButton((ImTextureID)previewTex, thumbSize, ImVec2(0, 0),
                        ImVec2(1, 1), -1, ImVec4(0, 0, 0, 0),
                        isSelected ? ImVec4(1.0f, 0.8f, 0.3f, 1.0f) : ImVec4(0, 0, 0, 0))) {
                        m_selectedMaterialName = materialName;
                    }
                } else {
                    // Fallback: Generate a consistent color based on material name hash
                    size_t hash = std::hash<std::string>{}(materialName);
                    float hue = (hash % 360) / 360.0f;
                    float sat = 0.3f + ((hash / 360) % 100) / 200.0f;  // 0.3 - 0.8
                    float val = 0.6f + ((hash / 36000) % 100) / 250.0f;  // 0.6 - 1.0
                    float r, g, b;
                    ImGui::ColorConvertHSVtoRGB(hue, sat, val, r, g, b);
                    ImVec4 thumbColor(r, g, b, 1.0f);

                    // Draw colored rectangle as placeholder thumbnail
                    ImGui::PushStyleColor(ImGuiCol_Button, thumbColor);
                    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, thumbColor);
                    ImGui::PushStyleColor(ImGuiCol_ButtonActive, thumbColor);

                    if (ImGui::Button("", thumbSize)) {
                        m_selectedMaterialName = materialName;
                    }

                    ImGui::PopStyleColor(3);
                }

                // Drag and drop source
                if (ImGui::BeginDragDropSource(ImGuiDragDropFlags_SourceAllowNullID)) {
                    ImGui::SetDragDropPayload("ARCH_MATERIAL", materialName.c_str(), materialName.size() + 1);
                    ImGui::Text("Apply %s", displayName.c_str());
                    m_materialDragActive = true;
                    m_materialDragName = materialName;
                    ImGui::EndDragDropSource();
                }

                // Hover tooltip
                if (ImGui::IsItemHovered()) {
                    ImGui::BeginTooltip();
                    ImGui::Text("%s", displayName.c_str());
                    ImGui::TextDisabled("Click to select, drag to apply");
                    ImGui::EndTooltip();
                }

                // Selection indicator (only for fallback buttons, ImageButton has built-in border)
                if (isSelected && !hasPreview) {
                    ImDrawList* drawList = ImGui::GetWindowDrawList();
                    ImVec2 min = ImGui::GetItemRectMin();
                    ImVec2 max = ImGui::GetItemRectMax();
                    float thickness = 2.0f;
                    ImU32 color = ImGui::GetColorU32(ImVec4(1.0f, 0.8f, 0.3f, 1.0f));
                    drawList->AddRect(min, max, color, 0.0f, 0, thickness);
                }

                // Display name below thumbnail
                ImGui::PushTextWrapPos(ImGui::GetCursorPosX() + thumbSize.x);
                ImGui::Text("%s", displayName.c_str());
                ImGui::PopTextWrapPos();

                ImGui::PopID();

                // Move to next item in row
                ImGui::SameLine();
            } else {  // List view
                if (ImGui::Selectable(displayName.c_str(), isSelected)) {
                    m_selectedMaterialName = materialName;
                }

                // Drag and drop source
                if (ImGui::BeginDragDropSource(ImGuiDragDropFlags_SourceAllowNullID)) {
                    ImGui::SetDragDropPayload("ARCH_MATERIAL", materialName.c_str(), materialName.size() + 1);
                    ImGui::Text("Apply %s", displayName.c_str());
                    m_materialDragActive = true;
                    m_materialDragName = materialName;
                    ImGui::EndDragDropSource();
                }
            }
        };

        // Draw categorized materials
        for (const auto& [category, categoryMaterials] : categorizedMaterials) {
            if (ImGui::TreeNode(category.c_str())) {
                ImGui::Spacing();

                if (m_materialLibraryViewMode == 0) {  // Grid view
                    int col = 0;
                    for (const auto& material : categoryMaterials) {
                        drawMaterialItem(material);
                        col++;
                        if (col >= itemsPerRow) {
                            ImGui::NewLine();
                            col = 0;
                        }
                    }
                    if (col > 0) {
                        ImGui::NewLine();
                    }
                } else {  // List view
                    for (const auto& material : categoryMaterials) {
                        drawMaterialItem(material);
                    }
                }

                ImGui::TreePop();
            }
            ImGui::Separator();
        }

        // Draw uncategorized materials
        if (!uncategorizedMaterials.empty()) {
            if (ImGui::TreeNode("Other")) {
                ImGui::Spacing();

                if (m_materialLibraryViewMode == 0) {  // Grid view
                    int col = 0;
                    for (const auto& material : uncategorizedMaterials) {
                        drawMaterialItem(material);
                        col++;
                        if (col >= itemsPerRow) {
                            ImGui::NewLine();
                            col = 0;
                        }
                    }
                    if (col > 0) {
                        ImGui::NewLine();
                    }
                } else {  // List view
                    for (const auto& material : uncategorizedMaterials) {
                        drawMaterialItem(material);
                    }
                }

                ImGui::TreePop();
            }
        }

        ImGui::Separator();
        ImGui::Spacing();

        // Selected material info and actions
        if (!m_selectedMaterialName.empty()) {
            std::string displaySelected = m_selectedMaterialName;
            size_t lastSlash = displaySelected.find_last_of('/');
            if (lastSlash != std::string::npos) {
                displaySelected = displaySelected.substr(lastSlash + 1);
            }

            ImGui::Text("Selected: %s", displaySelected.c_str());

            if (ImGui::Button("Apply to Selection", ImVec2(-1, 0))) {
                m_applyMaterialName = m_selectedMaterialName;
                m_applyMaterialRequested = true;
            }

            ImGui::Spacing();
        } else {
            ImGui::TextDisabled("No material selected");
        }

        // Help text
        ImGui::Separator();
        ImGui::TextWrapped("Tip: Drag materials from this panel onto the 3D viewport to apply them to elements.");

        // Handle drag drop end
        if (m_materialDragActive && !ImGui::IsMouseDown(ImGuiMouseButton_Left)) {
            if (!ImGui::IsWindowHovered(ImGuiHoveredFlags_AnyWindow)) {
                m_materialDropRequested = true;
                m_materialDropName = m_materialDragName;
            }
            m_materialDragActive = false;
        }
    }

    ImGui::End();
}

// ============================================================================
// Material Inspector (Per-Element Material Overrides)
// ============================================================================

ImGuiLayer::MaterialOverrideRequest ImGuiLayer::takeMaterialOverrideRequest() {
    m_materialOverrideRequested = false;
    return m_materialOverrideRequest;
}

void ImGuiLayer::drawMaterialInspector(const Renderer& renderer) {
    if (!m_showMaterialInspector) return;

    ImGui::SetNextWindowSize(ImVec2(350, 500), ImGuiCond_FirstUseEver);
    if (ImGui::Begin("Material Inspector", &m_showMaterialInspector)) {
        ImGui::TextDisabled("Per-Element Material Overrides");
        ImGui::Separator();
        ImGui::Spacing();

        // Show selected element count
        const auto& selectedElements = getSelectedElements();
        size_t selectedCount = selectedElements.size();

        if (selectedCount == 0) {
            ImGui::TextWrapped("No elements selected. Select one or more elements in the viewport to edit their materials.");
            ImGui::TextDisabled("(Click on elements in the 3D view to select them)");
            ImGui::Spacing();
            if (ImGui::Button("Close")) {
                m_showMaterialInspector = false;
            }
            ImGui::End();
            return;
        }

        ImGui::Text("Selected Elements: %zu", selectedCount);
        ImGui::TextDisabled("Overrides add to global material values");
        ImGui::Spacing();
        ImGui::Separator();
        ImGui::Spacing();

        // Clear flags when selection changes (track previous selection count)
        static size_t previousSelectedCount = 0;
        static std::vector<int> previousSelectedIndices;
        if (selectedCount != previousSelectedCount) {
            // Selection changed - clear flags
            m_modifiedUVScale = m_modifiedUVRotation = m_modifiedNormalStrength = m_modifiedBrightness = false;
            m_modifiedContrast = m_modifiedSaturation = m_modifiedRoughness = false;
            m_modifiedMetallic = m_modifiedAOStrength = m_modifiedTint = false;

            // Initialize sliders to show current effective values for the first selected element
            if (selectedCount > 0) {
                int firstElementId = *selectedElements.begin();
                const auto* override = renderer.getElementOverride(firstElementId);

                if (override) {
                    // Element has override - show override values
                    m_inspectorUVScale = override->uvScale;
                    m_inspectorUVRotation = override->uvRotation;
                    m_inspectorNormalStrength = override->normalStrength;
                    m_inspectorBrightness = override->brightness;
                    m_inspectorContrast = override->contrast;
                    m_inspectorSaturation = override->saturation;
                    m_inspectorRoughness = override->roughness;
                    m_inspectorMetallic = override->metallic;
                    m_inspectorAOStrength = override->aoStrength;
                } else {
                    // Element has no override - show global values as reference
                    m_inspectorUVScale = renderer.getMaterialUVScale();
                    m_inspectorUVRotation = 0.0f;  // No global rotation
                    m_inspectorNormalStrength = renderer.getNormalStrength();
                    m_inspectorBrightness = renderer.getMaterialBrightness();
                    m_inspectorContrast = renderer.getMaterialContrast();
                    m_inspectorSaturation = renderer.getMaterialSaturation();
                    m_inspectorRoughness = renderer.getMaterialRoughnessOffset();
                    m_inspectorMetallic = renderer.getMaterialMetallicOffset();
                    m_inspectorAOStrength = renderer.getMaterialAOStrength();
                }
            }

            previousSelectedCount = selectedCount;
        }

        // Parameter sliders
        if (ImGui::CollapsingHeader("Properties", ImGuiTreeNodeFlags_DefaultOpen)) {
            ImGui::Indent();

            // UV Scale - shows current value (global or override), adjusts create override for this element
            ImGui::Text("UV Scale");
            if (ImGui::SliderFloat("##uvScale", &m_inspectorUVScale, 0.01f, 500.0f, "%.2f")) {
                m_modifiedUVScale = true;
            }
            ImGui::SetItemTooltip("Texture tiling density for selected element (overrides global value)");

            // UV Rotation (0 to 360 degrees)
            ImGui::Text("Pattern Rotation");
            if (ImGui::SliderFloat("##uvRotation", &m_inspectorUVRotation, 0.0f, 360.0f, "%.1f deg")) {
                m_modifiedUVRotation = true;
            }
            ImGui::SetItemTooltip("Rotate texture pattern (0-360 degrees)");

            // Normal Strength (0 to 5)
            ImGui::Text("Normal Strength");
            if (ImGui::SliderFloat("##normalStrength", &m_inspectorNormalStrength, 0.0f, 5.0f, "%.2f")) {
                m_modifiedNormalStrength = true;
            }
            ImGui::SetItemTooltip("Set normal map intensity (leave at 1.0 to use global value)");

            // Brightness (-1 to 1)
            ImGui::Text("Brightness");
            if (ImGui::SliderFloat("##brightness", &m_inspectorBrightness, -1.0f, 1.0f, "%.2f")) {
                m_modifiedBrightness = true;
            }
            ImGui::SetItemTooltip("Set brightness adjustment (leave at 0.0 to use global value)");

            // Contrast (0 to 2)
            ImGui::Text("Contrast");
            if (ImGui::SliderFloat("##contrast", &m_inspectorContrast, 0.0f, 2.0f, "%.2f")) {
                m_modifiedContrast = true;
            }
            ImGui::SetItemTooltip("Set contrast (leave at 1.0 to use global value)");

            // Saturation (0 to 2)
            ImGui::Text("Saturation");
            if (ImGui::SliderFloat("##saturation", &m_inspectorSaturation, 0.0f, 2.0f, "%.2f")) {
                m_modifiedSaturation = true;
            }
            ImGui::SetItemTooltip("Set color saturation (leave at 1.0 to use global value)");

            // Roughness (-0.5 to 0.5, additive offset)
            ImGui::Text("Roughness");
            if (ImGui::SliderFloat("##roughness", &m_inspectorRoughness, -0.5f, 0.5f, "%.2f")) {
                m_modifiedRoughness = true;
            }
            ImGui::SetItemTooltip("Adjust roughness offset (leave at 0.0 to use global value)");

            // Metallic (-0.5 to 0.5, additive offset)
            ImGui::Text("Metallic");
            if (ImGui::SliderFloat("##metallic", &m_inspectorMetallic, -0.5f, 0.5f, "%.2f")) {
                m_modifiedMetallic = true;
            }
            ImGui::SetItemTooltip("Adjust metallic offset (leave at 0.0 to use global value)");

            // AO Strength (0 to 2)
            ImGui::Text("AO Strength");
            if (ImGui::SliderFloat("##aoStrength", &m_inspectorAOStrength, 0.0f, 2.0f, "%.2f")) {
                m_modifiedAOStrength = true;
            }
            ImGui::SetItemTooltip("Set ambient occlusion intensity (leave at 1.0 to use global value)");

            // Tint (-1 to 1, additive color)
            ImGui::Text("Tint (RGB)");
            if (ImGui::SliderFloat3("##tint", m_inspectorTint, -0.5f, 0.5f, "%.2f")) {
                m_modifiedTint = true;
            }
            ImGui::SetItemTooltip("Add RGB color tint (leave at 0,0,0 to use global value)");

            ImGui::Unindent();
        }

        ImGui::Spacing();
        ImGui::Separator();
        ImGui::Spacing();

        // Action buttons
        // Apply to selected elements
        bool hasAnyModified = m_modifiedUVScale || m_modifiedUVRotation || m_modifiedNormalStrength || m_modifiedBrightness ||
                             m_modifiedContrast || m_modifiedSaturation || m_modifiedRoughness ||
                             m_modifiedMetallic || m_modifiedAOStrength || m_modifiedTint;

        if (!hasAnyModified) {
            ImGui::BeginDisabled();
        }

        if (ImGui::Button("Apply to Selected", ImVec2(-1, 0))) {
            if (hasAnyModified) {
                m_materialOverrideRequest.elementIndices.assign(selectedElements.begin(), selectedElements.end());

                // Set all values
                m_materialOverrideRequest.uvScale = m_inspectorUVScale;
                m_materialOverrideRequest.uvRotation = m_inspectorUVRotation;
                m_materialOverrideRequest.normalStrength = m_inspectorNormalStrength;
                m_materialOverrideRequest.brightness = m_inspectorBrightness;
                m_materialOverrideRequest.contrast = m_inspectorContrast;
                m_materialOverrideRequest.saturation = m_inspectorSaturation;
                m_materialOverrideRequest.roughness = m_inspectorRoughness;
                m_materialOverrideRequest.metallic = m_inspectorMetallic;
                m_materialOverrideRequest.aoStrength = m_inspectorAOStrength;
                m_materialOverrideRequest.tint[0] = m_inspectorTint[0];
                m_materialOverrideRequest.tint[1] = m_inspectorTint[1];
                m_materialOverrideRequest.tint[2] = m_inspectorTint[2];

                // Only set flags for parameters that user actually modified
                m_materialOverrideRequest.hasUVScale = m_modifiedUVScale;
                m_materialOverrideRequest.hasUVRotation = m_modifiedUVRotation;
                m_materialOverrideRequest.hasNormalStrength = m_modifiedNormalStrength;
                m_materialOverrideRequest.hasBrightness = m_modifiedBrightness;
                m_materialOverrideRequest.hasContrast = m_modifiedContrast;
                m_materialOverrideRequest.hasSaturation = m_modifiedSaturation;
                m_materialOverrideRequest.hasRoughness = m_modifiedRoughness;
                m_materialOverrideRequest.hasMetallic = m_modifiedMetallic;
                m_materialOverrideRequest.hasAOStrength = m_modifiedAOStrength;
                m_materialOverrideRequest.hasTint = m_modifiedTint;

                m_materialOverrideRequest.resetSelected = false;
                m_materialOverrideRequest.resetAll = false;
                m_materialOverrideRequested = true;

                // NOTE: Don't clear flags here! User might want to apply the same overrides to more elements
                // Flags are only cleared when user clicks Reset or selects new elements
            }
        }

        if (!hasAnyModified) {
            ImGui::EndDisabled();
            if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled)) {
                ImGui::SetTooltip("Adjust at least one parameter above to enable");
            }
        }

        // Reset selected elements
        ImGui::SameLine();
        if (ImGui::Button("Reset Selected", ImVec2(-1, 0))) {
            m_materialOverrideRequest.elementIndices.assign(selectedElements.begin(), selectedElements.end());
            m_materialOverrideRequest.resetSelected = true;
            m_materialOverrideRequest.resetAll = false;
            m_materialOverrideRequested = true;
            // Clear modified flags after reset
            m_modifiedUVScale = m_modifiedUVRotation = m_modifiedNormalStrength = m_modifiedBrightness = false;
            m_modifiedContrast = m_modifiedSaturation = m_modifiedRoughness = false;
            m_modifiedMetallic = m_modifiedAOStrength = m_modifiedTint = false;
        }

        // Reset all overrides
        if (ImGui::Button("Reset All Overrides", ImVec2(-1, 0))) {
            m_materialOverrideRequest.elementIndices.clear();
            m_materialOverrideRequest.resetSelected = false;
            m_materialOverrideRequest.resetAll = true;
            m_materialOverrideRequested = true;
            // Clear modified flags after reset
            m_modifiedUVScale = m_modifiedUVRotation = m_modifiedNormalStrength = m_modifiedBrightness = false;
            m_modifiedContrast = m_modifiedSaturation = m_modifiedRoughness = false;
            m_modifiedMetallic = m_modifiedAOStrength = m_modifiedTint = false;
            // Reset slider values to defaults
            m_inspectorUVScale = 1.0f;
            m_inspectorUVRotation = 0.0f;
            m_inspectorNormalStrength = 1.0f;
            m_inspectorBrightness = 0.0f;
            m_inspectorContrast = 1.0f;
            m_inspectorSaturation = 1.0f;
            m_inspectorRoughness = 0.0f;
            m_inspectorMetallic = 0.0f;
            m_inspectorAOStrength = 1.0f;
        }

        ImGui::Spacing();

        // Show override statistics
        size_t overrideCount = renderer.getOverrideCount();
        ImGui::TextDisabled("Total active overrides: %zu elements", overrideCount);
        if (overrideCount > 0 && ImGui::IsItemHovered()) {
            ImGui::SetTooltip("Elements with custom material adjustments");
        }

        ImGui::Spacing();
        if (ImGui::Button("Close Inspector")) {
            m_showMaterialInspector = false;
        }
    }
    ImGui::End();
}

} // namespace arch
