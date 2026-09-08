#pragma once

#include "types.hpp"
#include <string>
#include <vector>
#include <optional>
#include <functional>

namespace arch {
namespace slicer {

// ============================================================================
// 2D PRIMITIVE TYPES
// ============================================================================

// 2D point (uses glm::vec2 from types.hpp)
using Point2D = vec2;

// 2D line segment
struct Line2D {
    Point2D start;
    Point2D end;
    std::string layer;          // CAD layer name
    std::string lineType;       // "continuous", "dashed", "center", "hidden"
    f32 lineWeight = 0.25f;     // Line weight in mm
    vec3 color = {0, 0, 0};     // RGB color

    f32 length() const {
        return glm::length(end - start);
    }

    Point2D midpoint() const {
        return (start + end) * 0.5f;
    }
};

// 2D polyline (connected line segments)
struct Polyline2D {
    std::vector<Point2D> points;
    bool closed = false;
    std::string layer;
    std::string lineType = "continuous";
    f32 lineWeight = 0.25f;
    vec3 color = {0, 0, 0};

    void addPoint(const Point2D& p) { points.push_back(p); }
    bool empty() const { return points.size() < 2; }
};

// 2D arc
struct Arc2D {
    Point2D center;
    f32 radius;
    f32 startAngle;     // Radians
    f32 endAngle;       // Radians
    std::string layer;
    f32 lineWeight = 0.25f;
    vec3 color = {0, 0, 0};
};

// 2D circle
struct Circle2D {
    Point2D center;
    f32 radius;
    std::string layer;
    f32 lineWeight = 0.25f;
    vec3 color = {0, 0, 0};
};

// Text annotation
struct Text2D {
    Point2D position;
    std::string text;
    f32 height = 2.5f;          // Text height in mm
    f32 rotation = 0.0f;        // Rotation in radians
    std::string layer;
    std::string style = "Standard";
    std::string justification = "left";  // "left", "center", "right"
    vec3 color = {0, 0, 0};
};

// Linear dimension
struct Dimension2D {
    Point2D point1;
    Point2D point2;
    Point2D textPosition;
    std::string text;           // Override text (empty = auto calculate)
    f32 textHeight = 2.5f;
    std::string layer = "DIMS";
    std::string style = "Standard";
};

// Hatch/fill pattern
struct Hatch2D {
    std::vector<Polyline2D> boundaries;
    std::string pattern;        // "SOLID", "ANSI31", "INSULATION", "CONCRETE", etc.
    f32 scale = 1.0f;
    f32 angle = 0.0f;
    std::string layer;
    vec3 color = {0.8f, 0.8f, 0.8f};
};

// ============================================================================
// SLICE PLANE DEFINITION
// ============================================================================

enum class SlicePlaneType : u32 {
    Horizontal,     // Plan view (XY plane at height Z)
    VerticalNS,     // Section looking North-South (XZ plane at Y)
    VerticalEW,     // Section looking East-West (YZ plane at X)
    Custom          // Arbitrary plane defined by normal and point
};

struct SlicePlane {
    SlicePlaneType type = SlicePlaneType::Horizontal;
    f32 position = 0.0f;        // Height for horizontal, offset for vertical
    vec3 normal = {0, 0, 1};    // For custom planes
    vec3 origin = {0, 0, 0};    // For custom planes
    std::string name;           // e.g., "Level 1 Plan", "Section A-A"

    // Create horizontal plane at given height
    static SlicePlane horizontal(f32 height, const std::string& name = "") {
        SlicePlane p;
        p.type = SlicePlaneType::Horizontal;
        p.position = height;
        p.normal = {0, 1, 0};   // Y-up in kernel coords
        p.origin = {0, height, 0};
        p.name = name;
        return p;
    }

    // Create vertical section plane (North-South cut)
    static SlicePlane sectionNS(f32 yPosition, const std::string& name = "") {
        SlicePlane p;
        p.type = SlicePlaneType::VerticalNS;
        p.position = yPosition;
        p.normal = {0, 0, 1};
        p.origin = {0, 0, yPosition};
        p.name = name;
        return p;
    }

    // Create vertical section plane (East-West cut)
    static SlicePlane sectionEW(f32 xPosition, const std::string& name = "") {
        SlicePlane p;
        p.type = SlicePlaneType::VerticalEW;
        p.position = xPosition;
        p.normal = {1, 0, 0};
        p.origin = {xPosition, 0, 0};
        p.name = name;
        return p;
    }
};

// ============================================================================
// DRAWING SHEET
// ============================================================================

// Standard paper sizes (in mm)
struct PaperSize {
    std::string name;
    f32 width;
    f32 height;

    static PaperSize ARCH_D() { return {"ARCH D", 914.4f, 609.6f}; }
    static PaperSize ARCH_E() { return {"ARCH E", 1219.2f, 914.4f}; }
    static PaperSize ANSI_D() { return {"ANSI D", 863.6f, 558.8f}; }
    static PaperSize A1() { return {"A1", 841.0f, 594.0f}; }
    static PaperSize A2() { return {"A2", 594.0f, 420.0f}; }
    static PaperSize A3() { return {"A3", 420.0f, 297.0f}; }
};

// Viewport on a sheet
struct Viewport {
    Point2D position;           // Position on sheet (mm)
    f32 width;                  // Width on sheet (mm)
    f32 height;                 // Height on sheet (mm)
    f32 scale = 1.0f;           // Drawing scale (e.g., 0.25 = 1/4" = 1'-0")
    Point2D centerPoint;        // Center of view in model space
    std::string name;           // Viewport label
};

// Complete drawing sheet
struct DrawingSheet {
    std::string name;
    std::string number;         // Sheet number (e.g., "A-101")
    PaperSize paper = PaperSize::ARCH_D();
    std::vector<Viewport> viewports;

    // Title block info
    std::string projectName;
    std::string projectAddress;
    std::string drawnBy;
    std::string checkedBy;
    std::string date;
    std::string revision;
};

// ============================================================================
// SLICE RESULT
// ============================================================================

// Result of slicing an element
struct SliceResult {
    std::string elementId;
    std::string elementType;        // "wall", "floor", "beam", etc.
    std::vector<Line2D> lines;
    std::vector<Polyline2D> polylines;
    std::vector<Arc2D> arcs;
    std::vector<Circle2D> circles;
    std::vector<Hatch2D> hatches;
    std::vector<Text2D> annotations;
    std::vector<Dimension2D> dimensions;

    bool empty() const {
        return lines.empty() && polylines.empty() && arcs.empty() &&
               circles.empty() && hatches.empty();
    }

    void merge(const SliceResult& other) {
        lines.insert(lines.end(), other.lines.begin(), other.lines.end());
        polylines.insert(polylines.end(), other.polylines.begin(), other.polylines.end());
        arcs.insert(arcs.end(), other.arcs.begin(), other.arcs.end());
        circles.insert(circles.end(), other.circles.begin(), other.circles.end());
        hatches.insert(hatches.end(), other.hatches.begin(), other.hatches.end());
        annotations.insert(annotations.end(), other.annotations.begin(), other.annotations.end());
        dimensions.insert(dimensions.end(), other.dimensions.begin(), other.dimensions.end());
    }
};

// ============================================================================
// WALL SECTION DETAIL
// ============================================================================

// Detail view of a wall assembly section
struct WallSectionDetail {
    std::string wallTypeId;
    std::string wallTypeName;
    f32 totalThickness;
    f32 detailScale = 1.0f;     // Typically 1.5" = 1'-0" or similar

    // Layer representations
    struct LayerDetail {
        std::string name;
        std::string material;
        f32 thickness;
        Polyline2D outline;
        Hatch2D hatch;
        std::vector<Text2D> labels;
    };
    std::vector<LayerDetail> layers;

    // Fastener callouts
    std::vector<Text2D> fastenerNotes;

    // Overall dimensions
    std::vector<Dimension2D> dimensions;
};

// ============================================================================
// SLICER ENGINE CLASS
// ============================================================================

class Slicer2D {
public:
    Slicer2D();
    ~Slicer2D();

    // ========================================================================
    // SLICE OPERATIONS
    // ========================================================================

    // Slice a building with a plane
    SliceResult sliceBuilding(const Building& building, const SlicePlane& plane);

    // Slice a single structural element
    SliceResult sliceElement(const StructuralElement& element, const SlicePlane& plane);

    // Slice a parametric wall
    SliceResult sliceWall(const ParametricWall& wall, const WallType& wallType,
                          const SlicePlane& plane);

    // Generate floor plan at height
    SliceResult generateFloorPlan(const Building& building, f32 cutHeight = 4.0f);

    // Generate building section
    SliceResult generateSection(const Building& building, const SlicePlane& plane);

    // ========================================================================
    // DETAIL GENERATION
    // ========================================================================

    // Generate wall section detail
    WallSectionDetail generateWallDetail(const WallType& wallType, f32 wallHeight = 9.0f);

    // Generate typical wall section at location
    SliceResult generateWallSection(const ParametricWall& wall, const WallType& wallType,
                                     f32 cutPosition = 0.5f);  // 0-1 along wall length

    // ========================================================================
    // ANNOTATION
    // ========================================================================

    // Add dimensions to slice result
    void addOverallDimensions(SliceResult& result);

    // Add room labels
    void addRoomLabels(SliceResult& result, const std::vector<std::pair<Point2D, std::string>>& rooms);

    // Add grid lines
    void addGridLines(SliceResult& result, const std::vector<f32>& xGrids,
                      const std::vector<f32>& yGrids);

    // ========================================================================
    // EXPORT
    // ========================================================================

    // Export to SVG string
    std::string exportToSVG(const SliceResult& result, f32 scale = 1.0f);

    // Export to SVG file
    bool exportToSVGFile(const SliceResult& result, const std::string& filepath, f32 scale = 1.0f);

    // Export to DXF string
    std::string exportToDXF(const SliceResult& result);

    // Export to DXF file
    bool exportToDXFFile(const SliceResult& result, const std::string& filepath);

    // Export wall detail to SVG
    std::string wallDetailToSVG(const WallSectionDetail& detail, f32 scale = 1.0f);

    // ========================================================================
    // CONFIGURATION
    // ========================================================================

    // Layer configuration
    struct LayerConfig {
        std::string name;
        vec3 color;
        std::string lineType;
        f32 lineWeight;
    };

    void setLayerConfig(const std::string& elementType, const LayerConfig& config);

    // Hatch patterns for materials
    void setMaterialHatch(const std::string& material, const std::string& pattern, f32 scale = 1.0f);

private:
    // Layer configurations by element type
    std::unordered_map<std::string, LayerConfig> m_layerConfigs;

    // Material to hatch pattern mapping
    std::unordered_map<std::string, std::pair<std::string, f32>> m_materialHatches;

    // Initialize default configurations
    void initDefaults();

    // Geometry helpers
    std::optional<Point2D> intersectLineWithPlane(const vec3& p1, const vec3& p2,
                                                   const SlicePlane& plane);

    std::vector<Line2D> sliceBox(const vec3& center, const vec3& extents,
                                  const mat4& transform, const SlicePlane& plane);

    Polyline2D sliceMesh(const MeshData& mesh, const SlicePlane& plane);

    // Project 3D point to 2D based on slice plane
    Point2D projectTo2D(const vec3& point3D, const SlicePlane& plane);

    // Material hatch generation
    Hatch2D createMaterialHatch(const Polyline2D& boundary, const std::string& material);

    // DXF helpers
    std::string dxfHeader();
    std::string dxfTables();
    std::string dxfEntities(const SliceResult& result);
    std::string dxfLine(const Line2D& line);
    std::string dxfPolyline(const Polyline2D& poly);
    std::string dxfText(const Text2D& text);
    std::string dxfHatch(const Hatch2D& hatch);
    std::string dxfFooter();

    // SVG helpers
    std::string svgLine(const Line2D& line, f32 scale);
    std::string svgPolyline(const Polyline2D& poly, f32 scale);
    std::string svgCircle(const Circle2D& circle, f32 scale);
    std::string svgArc(const Arc2D& arc, f32 scale);
    std::string svgText(const Text2D& text, f32 scale);
    std::string svgHatch(const Hatch2D& hatch, f32 scale);
    std::string colorToSVG(const vec3& color);

    // DXF arc helper
    std::string dxfArc(const Arc2D& arc);
};

// Global slicer instance
Slicer2D& getSlicer();

} // namespace slicer
} // namespace arch
