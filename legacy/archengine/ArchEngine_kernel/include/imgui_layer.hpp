#pragma once

#include "types.hpp"
#include "vulkan_context.hpp"
#include <imgui.h>
#include <string>
#include <set>
#include <vector>
#include <memory>
#include <imgui_impl_glfw.h>
#include <imgui_impl_vulkan.h>

struct GLFWwindow;

namespace arch {

// Forward declarations
struct Building;
struct FrameAnalysis;
class Renderer;

// Drawing modes for geometry creation
enum class DrawMode {
    None,           // Normal selection mode
    DrawWall,       // Click to place wall start/end
    DrawRoom,       // Click to place room corners
    DrawFloor       // Click to place floor corners
};

class ImGuiLayer {
public:
    struct MaterialGenerateRequest {
        std::string name;
        std::string prompt;
        std::string negativePrompt;
        std::string serverUrl;
        std::string pythonExe;
        std::string scriptPath;
        std::string outputRoot;
        int size = 1024;
        int steps = 30;
        float guidance = 7.5f;
        bool tileable = true;
    };

    struct MaterialUpscaleRequest {
        std::string materialName;
        std::string serverUrl;
        std::string pythonExe;
        std::string scriptPath;
        std::string materialRoot;
        int scale = 4;      // 2 or 4
        int method = 0;     // 0=realesrgan, 1=lanczos
    };

    struct HeightGenRequest {
        std::string materialName;
        std::string materialPath;
        std::string serverUrl;
        int method = 0;     // 0=hybrid, 1=normal, 2=diffuse
        float blur = 1.0f;
        float contrast = 1.0f;
        bool invert = false;
    };

    struct HighResRenderRequest {
        std::string outputPath;
        int resolution = 0;     // 0=4K, 1=6K, 2=8K
        int samples = 1;        // 1, 16, 64, 256
        int format = 0;         // 0=PNG, 1=EXR
        bool upscale = false;   // If true, render at 4K and upscale to target
        int upscaleMethod = 0;  // 0=realesrgan, 1=lanczos
        float brightness = 1.0f; // Brightness multiplier (1.0 = match viewport)
        int postProcessPreset = 0; // 0=none, 1=subtle, 2=vivid, 3=warm, 4=architectural, 5=golden_hour, 6=print_ready
        // Manual post-process overrides (negative = use preset values)
        float postExposure = -1.0f;
        float postContrast = -1.0f;
        float postSaturation = -1.0f;
        float postVibrance = -1.0f;
        float postSharpness = -1.0f;
        float postVignette = -1.0f;
        // Path tracer settings
        int renderMode = 0;     // 0=Rasterizer, 1=Path Tracer
        int ptSamples = 64;     // Path tracer samples per pixel
        int ptBounces = 6;      // Path tracer max bounces
    };

    struct MaterialOverrideRequest {
        std::vector<int> elementIndices;  // Elements to apply override to

        // Per-parameter flags (which parameters should be overridden)
        bool hasUVScale = false;
        bool hasUVRotation = false;
        bool hasNormalStrength = false;
        bool hasBrightness = false;
        bool hasContrast = false;
        bool hasSaturation = false;
        bool hasRoughness = false;
        bool hasMetallic = false;
        bool hasAOStrength = false;
        bool hasTint = false;

        // Direct replacement values (except roughness/metallic which are additive offsets)
        float uvScale = 1.0f;
        float uvRotation = 0.0f;      // Rotation in degrees
        float normalStrength = 1.0f;
        float brightness = 0.0f;
        float contrast = 1.0f;
        float saturation = 1.0f;
        float roughness = 0.0f;       // Additive offset
        float metallic = 0.0f;        // Additive offset
        float aoStrength = 1.0f;
        float tint[3] = {0, 0, 0};

        bool resetSelected = false;  // If true, clear overrides for selected elements
        bool resetAll = false;      // If true, clear all overrides
    };

    ImGuiLayer(VulkanContext& context, GLFWwindow* window, VkRenderPass renderPass);
    ~ImGuiLayer();

    // Non-copyable
    ImGuiLayer(const ImGuiLayer&) = delete;
    ImGuiLayer& operator=(const ImGuiLayer&) = delete;

    // Frame lifecycle
    void beginFrame();
    void endFrame(VkCommandBuffer cmd);

    // UI Panels
    void drawMainMenuBar(VisualizationMode& mode, bool& showDemo, bool& showMetrics);
    void drawBuildingPanel(const Building& building, size_t currentIndex, size_t totalBuildings);
    void drawPhysicsPanel(const FrameAnalysis& analysis, bool physicsAvailable);
    void drawVisualizationPanel(VisualizationMode& mode, Renderer& renderer);
    void drawHelpPanel(bool& show);
    void drawPerformancePanel(f32 fps, u32 drawCalls, u32 triangles, u32 culledElements = 0);
    void drawRenderSettingsPanel(Renderer& renderer, bool& show);
    void drawPreviewWindow();
    void drawRenderPreviewPanel(Renderer& renderer);
    void drawGeometryEditor(bool& show);
    void drawMaterialInspector(const Renderer& renderer);
    void drawMaterialLibraryPanel(Renderer& renderer);

    // Geometry editor state
    struct NewElement {
        int type = 0;  // 0=Beam, 1=Column, 2=Floor, 3=Wall, 4=Door, 5=Window, 6=Roof
        float start[3] = {0, 0, 0};
        float end[3] = {10, 0, 0};
        float width = 0.5f;
        float depth = 1.0f;
        int materialIndex = 0;
        int wallTypeIndex = 0;  // 0=2x6 Exterior, 1=2x4 Exterior, 2=Interior
        float wallHeight = 10.0f;
    };
    NewElement& getNewElement() { return m_newElement; }

    // File operations
    bool wasLoadRequested() const { return m_loadRequested; }
    bool wasSaveRequested() const { return m_saveRequested; }
    bool wasAddElementRequested() const { return m_addElementRequested; }
    void clearLoadRequest() { m_loadRequested = false; }
    void clearSaveRequest() { m_saveRequested = false; }
    void clearAddElementRequest() { m_addElementRequested = false; }
    const std::string& getFilePath() const { return m_filePath; }
    void setFilePath(const std::string& path) { m_filePath = path; }

    // Wall editing
    void drawWallEditor(Building& building, bool show);
    bool wasExtendWallRequested() const { return m_extendWallRequested; }
    void clearExtendWallRequest() { m_extendWallRequested = false; }
    int getSelectedWallIndex() const { return m_selectedWallIndex; }
    float getWallExtendHeight() const { return m_wallExtendHeight; }
    void setSelectedWallByElementIndex(int elemIdx) { m_selectedElements.clear(); m_selectedElements.insert(elemIdx); }
    const std::set<int>& getSelectedElements() const { return m_selectedElements; }
    void addToSelection(int idx) { m_selectedElements.insert(idx); }
    void removeFromSelection(int idx) { m_selectedElements.erase(idx); }
    void clearSelection() { m_selectedElements.clear(); }
    void setSelection(int idx) { m_selectedElements.clear(); m_selectedElements.insert(idx); }
    bool isSelected(int idx) const { return m_selectedElements.count(idx) > 0; }
    int getSelectedRoofIndex() const { return m_selectedRoofIdx; }
    void setSelectedRoofIndex(int idx) { m_selectedRoofIdx = idx; }
    void clearRoofSelection() { m_selectedRoofIdx = -1; }

    // Boolean operations (CSG)
    bool wasUnionRequested() const { return m_unionRequested; }
    void clearUnionRequest() { m_unionRequested = false; }

    // Drawing mode for interactive geometry creation
    DrawMode getDrawMode() const { return m_drawMode; }
    void setDrawMode(DrawMode mode) { m_drawMode = mode; m_drawPoints.clear(); }
    bool isDrawing() const { return m_drawMode != DrawMode::None; }

    // Drawing state - points clicked so far
    const std::vector<vec3>& getDrawPoints() const { return m_drawPoints; }
    void addDrawPoint(vec3 point) { m_drawPoints.push_back(point); }
    void clearDrawPoints() { m_drawPoints.clear(); }
    bool hasDrawPointStart() const { return !m_drawPoints.empty(); }

    // Check if wall creation is ready (2 points for wall)
    bool isWallDrawComplete() const { return m_drawMode == DrawMode::DrawWall && m_drawPoints.size() >= 2; }

    // Light placement mode - click to position sun light
    bool isLightPlacementMode() const { return m_lightPlacementMode; }
    void setLightPlacementMode(bool enabled) { m_lightPlacementMode = enabled; }

    // Light placement mode for adding point/spot lights
    enum class PlaceLightType { None, Point, Spot };
    bool isPlacingLight() const { return m_placeLightType != PlaceLightType::None; }
    PlaceLightType getPlaceLightType() const { return m_placeLightType; }
    void setPlaceLightType(PlaceLightType type) { m_placeLightType = type; }
    float getLightPlacementHeight() const { return m_lightPlacementHeight; }
    float getLightPlacementIntensity() const { return m_lightPlacementIntensity; }
    float getLightPlacementRange() const { return m_lightPlacementRange; }
    vec3 getLightPlacementColor() const { return m_lightPlacementColor; }

    // Light placement preview position (updated by main loop)
    void setLightPreviewPosition(vec3 pos, bool valid) { m_lightPreviewPos = pos; m_lightPreviewValid = valid; }
    vec3 getLightPreviewPosition() const { return m_lightPreviewPos; }
    bool hasValidLightPreview() const { return m_lightPreviewValid && isPlacingLight(); }

    // Snap planes for placement
    enum class SnapPlane { Ground, Floor1, Floor2, Floor3, Ceiling, Custom };
    SnapPlane getSnapPlane() const { return m_snapPlane; }
    void setSnapPlane(SnapPlane plane) { m_snapPlane = plane; }
    float getSnapPlaneHeight() const;  // Returns actual height based on selected plane
    float getCustomSnapHeight() const { return m_customSnapHeight; }
    void setCustomSnapHeight(float h) { m_customSnapHeight = h; }

    // Light selection (for clicking on indicators in scene)
    int getSelectedLightIndex() const { return m_selectedLightIndex; }
    void setSelectedLightIndex(int idx) { m_selectedLightIndex = idx; }

    // Light group controls
    bool isLightGroupEnabled(int group) const { return (group >= 0 && group < 4) ? m_lightGroupEnabled[group] : true; }
    void setLightGroupEnabled(int group, bool enabled) { if (group >= 0 && group < 4) m_lightGroupEnabled[group] = enabled; }
    float getLightGroupIntensity(int group) const { return (group >= 0 && group < 4) ? m_lightGroupIntensity[group] : 1.0f; }
    void setLightGroupIntensity(int group, float intensity) { if (group >= 0 && group < 4) m_lightGroupIntensity[group] = intensity; }
    int getPlacementLightGroup() const { return m_placementLightGroup; }
    void setPlacementLightGroup(int group) { m_placementLightGroup = group; }

    // Get parametric wall creation request
    bool wasParametricWallRequested() const { return m_parametricWallRequested; }
    void clearParametricWallRequest() { m_parametricWallRequested = false; }
    void requestParametricWall() { m_parametricWallRequested = true; }

    // State
    bool wantCaptureMouse() const;
    bool wantCaptureKeyboard() const;

    // UI action flags
    bool wasAnalysisRequested() const { return m_analysisRequested; }
    void clearAnalysisRequest() { m_analysisRequested = false; }

    // Camera view controls
    bool wasCameraViewRequested() const { return m_cameraViewRequested; }
    void clearCameraViewRequest() { m_cameraViewRequested = false; }
    CameraView getRequestedCameraView() const { return m_requestedCameraView; }

    // Material UI actions
    bool wasApplyMaterialRequested() const { return m_applyMaterialRequested; }
    const std::string& getApplyMaterialName() const { return m_applyMaterialName; }
    void clearApplyMaterialRequest() { m_applyMaterialRequested = false; }
    bool takeMaterialDrop(std::string& outName);

    bool wasMaterialGenerateRequested() const { return m_materialGenerateRequested; }
    MaterialGenerateRequest takeMaterialGenerateRequest();
    void setMaterialGenerationState(bool inFlight, const std::string& status);
    bool wasStartRenderServerRequested() const { return m_startRenderServerRequested; }
    void clearStartRenderServerRequest() { m_startRenderServerRequested = false; }
    bool wasStopRenderServerRequested() const { return m_stopRenderServerRequested; }
    void clearStopRenderServerRequest() { m_stopRenderServerRequested = false; }
    int getRenderServerPort() const { return m_renderServerPort; }

    // Material upscaling
    bool wasMaterialUpscaleRequested() const { return m_materialUpscaleRequested; }
    MaterialUpscaleRequest takeMaterialUpscaleRequest();
    void setMaterialUpscaleState(bool inFlight, const std::string& status);

    // Height map generation
    bool wasHeightGenRequested() const { return m_heightGenRequested; }
    HeightGenRequest takeHeightGenRequest();
    void setHeightGenState(bool inFlight, const std::string& status);

    // High-res rendering
    bool wasHighResRenderRequested() const { return m_highResRenderRequested; }
    HighResRenderRequest takeHighResRenderRequest();
    void setHighResRenderState(bool inFlight, const std::string& status, float progress = 0.0f);
    float getHighResRenderProgress() const { return m_highResRenderProgress; }

    // Material Inspector (per-element material overrides)
    bool wasMaterialOverrideRequested() const { return m_materialOverrideRequested; }
    MaterialOverrideRequest takeMaterialOverrideRequest();
    void setMaterialInspectorVisibility(bool show) { m_showMaterialInspector = show; }
    bool getMaterialInspectorVisibility() const { return m_showMaterialInspector; }

    // Live Render Preview Panel (GPU-direct inline preview)
    bool wasRenderPreviewRefreshRequested() const { return m_renderPreviewRefreshRequested; }
    void clearRenderPreviewRefreshRequest() { m_renderPreviewRefreshRequested = false; }
    void setRenderPreviewPanelVisibility(bool show) { m_showRenderPreviewPanel = show; }
    bool getRenderPreviewPanelVisibility() const { return m_showRenderPreviewPanel; }

    // Material Library Panel
    void setMaterialLibraryVisibility(bool show) { m_showMaterialLibrary = show; }
    bool getMaterialLibraryVisibility() const { return m_showMaterialLibrary; }

    // Material Test Window (PBR validation)
    void drawMaterialTestWindow(Renderer& renderer, Camera& camera);
    void setMaterialTestWindowVisibility(bool show) { m_showMaterialTestWindow = show; }
    bool getMaterialTestWindowVisibility() const { return m_showMaterialTestWindow; }

    // Compass overlay (shows N/S/E/W directions)
    void drawCompassOverlay(float cameraYaw);
    void setCompassVisibility(bool show) { m_showCompass = show; }
    bool getCompassVisibility() const { return m_showCompass; }

    // Memory test
    bool shouldRunMemoryTest() {
        bool run = m_runMemoryTest;
        m_runMemoryTest = false;
        return run;
    }

private:
    void createDescriptorPool();
    void uploadFonts();

    VulkanContext& m_context;
    bool m_analysisRequested = false;
    bool m_cameraViewRequested = false;
    CameraView m_requestedCameraView = CameraView::Perspective;
    bool m_loadRequested = false;
    bool m_saveRequested = false;
    bool m_addElementRequested = false;
    std::string m_filePath;
    NewElement m_newElement;
    VkDescriptorPool m_imguiPool = VK_NULL_HANDLE;
    bool m_initialized = false;

    // Wall editing state
    bool m_extendWallRequested = false;
    int m_selectedWallIndex = -1;
    float m_wallExtendHeight = 0.0f;
    std::set<int> m_selectedElements;
    int m_selectedRoofIdx = -1;

    // Boolean operations
    bool m_unionRequested = false;

    // Drawing mode state
    DrawMode m_drawMode = DrawMode::None;
    std::vector<vec3> m_drawPoints;
    bool m_parametricWallRequested = false;
    bool m_lightPlacementMode = false;

    // Light placement state
    PlaceLightType m_placeLightType = PlaceLightType::None;
    float m_lightPlacementHeight = 6.5f;      // ~2 meters in feet
    float m_lightPlacementIntensity = 5.0f;
    float m_lightPlacementRange = 15.0f;
    vec3 m_lightPlacementColor = vec3(1.0f, 0.95f, 0.9f);  // Warm white
    vec3 m_lightPreviewPos = vec3(0.0f);
    bool m_lightPreviewValid = false;
    SnapPlane m_snapPlane = SnapPlane::Ceiling;
    float m_customSnapHeight = 8.0f;
    int m_selectedLightIndex = -1;  // Currently selected light for editing (-1 = none)

    // Light group settings
    bool m_lightGroupEnabled[4] = {true, true, true, true};  // Interior, Exterior, Accent, Custom
    float m_lightGroupIntensity[4] = {1.0f, 1.0f, 1.0f, 1.0f};  // Per-group intensity multiplier
    int m_placementLightGroup = 0;  // Default group for newly placed lights (0=Interior)

    // Material UI state
    bool m_materialUiInitialized = false;
    int m_materialListIndex = -1;
    char m_materialFilter[96] = "";
    char m_materialRoot[260] = "materials";
    char m_materialOutputRoot[260] = "materials";
    char m_materialName[128] = "";
    char m_materialPrompt[512] = "";
    char m_materialNegative[256] = "blurry, low quality, distorted, watermark";
    char m_materialServerUrl[256] = "http://localhost:5000";
    char m_materialPythonExe[260] = "C:\\RevitMCP\\.venv-sd\\Scripts\\python.exe";
    char m_materialScriptPath[260] = "scripts/material_generate.py";
    int m_materialSize = 1024;
    int m_materialSteps = 30;
    float m_materialGuidance = 7.5f;
    bool m_materialTileable = true;
    int m_renderServerPort = 5000;
    bool m_applyMaterialRequested = false;
    std::string m_applyMaterialName;
    bool m_materialDropRequested = false;
    std::string m_materialDropName;
    bool m_materialDragActive = false;
    std::string m_materialDragName;
    bool m_materialGenerateRequested = false;
    MaterialGenerateRequest m_materialGenerateRequest;
    bool m_materialGenerateInFlight = false;
    std::string m_materialGenerateStatus;
    bool m_startRenderServerRequested = false;
    bool m_stopRenderServerRequested = false;

    // Material upscale state
    bool m_materialUpscaleRequested = false;
    MaterialUpscaleRequest m_materialUpscaleRequest;
    bool m_materialUpscaleInFlight = false;
    std::string m_materialUpscaleStatus;
    int m_upscaleScale = 4;
    int m_upscaleMethod = 0;

    // Height map generation state
    bool m_heightGenRequested = false;
    HeightGenRequest m_heightGenRequest;
    bool m_heightGenInFlight = false;
    std::string m_heightGenStatus;
    int m_heightGenMethod = 0;      // 0=hybrid, 1=normal, 2=diffuse
    float m_heightGenBlur = 1.0f;
    float m_heightGenContrast = 1.0f;
    bool m_heightGenInvert = false;

    // High-res render state
    bool m_highResRenderRequested = false;
    HighResRenderRequest m_highResRenderRequest;
    bool m_highResRenderInFlight = false;
    std::string m_highResRenderStatus;
    float m_highResRenderProgress = 0.0f;
    int m_renderResolution = 0;     // 0=4K, 1=6K, 2=8K
    int m_renderSamples = 0;        // 0=1, 1=16, 2=64, 3=256
    int m_renderFormat = 0;         // 0=PNG, 1=EXR
    bool m_renderUpscale = false;
    int m_renderUpscaleMethod = 0;
    float m_renderBrightness = 1.8f; // Brightness multiplier (1.8 default to compensate for no bloom/post-process)
    int m_renderPostProcess = 4;    // 0=none, 1=subtle, 2=vivid, 3=warm, 4=architectural, 5=golden_hour, 6=print_ready
    int m_renderMode = 0;           // 0=Rasterizer (fast), 1=Path Tracer (quality)
    int m_ptSamples = 64;           // Path tracer samples per pixel
    int m_ptBounces = 6;            // Path tracer max bounces
    char m_renderOutputPath[260] = "renders/render.png";

    // Post-process manual adjustments (negative = use preset)
    float m_postExposure = -1.0f;
    float m_postContrast = -1.0f;
    float m_postSaturation = -1.0f;
    float m_postVibrance = -1.0f;
    float m_postSharpness = -1.0f;
    float m_postVignette = -1.0f;
    bool m_showPostProcessAdvanced = false;

    // Print preview state
    bool m_previewRequested = false;
    bool m_showPreviewWindow = false;
    std::string m_previewImagePath;
    std::string mPreviewPostProcessedImage;

    // Material Inspector state
    bool m_showMaterialInspector = false;
    bool m_materialOverrideRequested = false;
    MaterialOverrideRequest m_materialOverrideRequest;
    // Override parameter values (defaults matching global values)
    float m_inspectorUVScale = 1.0f;
    float m_inspectorUVRotation = 0.0f;    // Rotation in degrees
    float m_inspectorNormalStrength = 1.0f;
    float m_inspectorBrightness = 0.0f;
    float m_inspectorContrast = 1.0f;
    float m_inspectorSaturation = 1.0f;
    float m_inspectorRoughness = 0.0f;     // Offset, not direct value
    float m_inspectorMetallic = 0.0f;      // Offset, not direct value
    float m_inspectorAOStrength = 1.0f;
    float m_inspectorTint[3] = {0, 0, 0};
    // Track which parameters have been modified by user (only override changed params)
    bool m_modifiedUVScale = false;
    bool m_modifiedUVRotation = false;
    bool m_modifiedNormalStrength = false;
    bool m_modifiedBrightness = false;
    bool m_modifiedContrast = false;
    bool m_modifiedSaturation = false;
    bool m_modifiedRoughness = false;
    bool m_modifiedMetallic = false;
    bool m_modifiedAOStrength = false;
    bool m_modifiedTint = false;

    // Live Render Preview Panel state (GPU-direct preview)
    bool m_showRenderPreviewPanel = false;
    bool m_renderPreviewRefreshRequested = false;

    // Material Test Window state (PBR validation)
    bool m_showMaterialTestWindow = false;
    int m_materialTestPreset = 0;  // 0=Full Grid, 1=Dielectrics, 2=Metals, 3=Roughness Row, 4=Metallic Column

    // Memory test flag
    bool m_runMemoryTest = false;

    // Compass overlay
    bool m_showCompass = true;  // Show by default

    // Improved Material Library state
    bool m_showMaterialLibrary = false;
    char m_materialLibraryFilter[128] = "";
    int m_materialLibraryViewMode = 0;  // 0=Grid, 1=List
    float m_materialThumbnailSize = 80.0f;
    std::string m_selectedMaterialName;
    std::string m_hoveredMaterialName;

public:
    float getRenderBrightness() const { return m_renderBrightness; }
    bool wasPreviewRequested() const { return m_previewRequested; }
    void clearPreviewRequest() { m_previewRequested = false; }
    const std::string& getPreviewImagePath() const { return m_previewImagePath; }
    void setPreviewImagePath(const std::string& path) { m_previewImagePath = path; }
    void showPreviewWindow(bool show) { m_showPreviewWindow = show; }
};

} // namespace arch
