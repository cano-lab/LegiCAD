#pragma once

#include "types.hpp"
#include <nlohmann/json.hpp>
#include <fstream>
#include <sstream>
#include <cmath>

namespace arch {

using json = nlohmann::json;

// Plan types
enum class PlanType : u32 {
    FloorPlan,
    RoofPlan,
    ReflectedCeilingPlan,
    SitePlan,
    FoundationPlan,
    FramingPlan,
    Elevation,
    Section
};

// Symbol types for annotations
enum class SymbolType : u32 {
    NorthArrow,
    SectionMarker,
    DetailMarker,
    ElevationMarker,
    DoorTag,
    WindowTag,
    RoomTag,
    ColumnGrid,
    LevelMarker
};

// Roof annotation types
enum class RoofAnnotationType : u32 {
    PitchIndicator,
    DrainageArrow,
    RidgeLine,
    ValleyLine,
    HipLine,
    EaveLine,
    RakeLine,
    SlopeArrow
};

// Text label annotation
struct TextLabel {
    std::string id;
    std::string text;
    vec2 position;
    f32 rotation = 0.0f;
    f32 textHeight = 100.0f;
    std::string fontStyle = "regular";
    std::string justification = "center";
    bool showBorder = false;
    bool showBackground = false;
};

// Dimension annotation
struct Dimension {
    std::string id;
    vec2 startPoint;
    vec2 endPoint;
    f32 offsetDistance = 200.0f;
    f32 textHeight = 80.0f;
    std::string unit = "mm";
    i32 precision = 0;
    bool showValue = true;
};

// Leader annotation
struct Leader {
    std::string id;
    vec2 arrowPoint;
    vec2 textPosition;
    std::vector<vec2> bendPoints;
    std::string text;
    f32 textHeight = 80.0f;
    std::string arrowStyle = "closed";
};

// Symbol annotation
struct Symbol {
    std::string id;
    SymbolType type;
    vec2 position;
    f32 rotation = 0.0f;
    f32 scale = 1.0f;
    std::string label;
    std::string sheetReference;
    vec2 direction = {0.0f, 1.0f};
};

// Roof annotation
struct RoofAnnotation {
    std::string id;
    RoofAnnotationType type;
    vec2 position;
    vec2 endPosition;
    f32 rotation = 0.0f;
    f32 pitch = 4.0f;       // Rise per 12 run
    f32 slopePercent = 0.0f;
    std::string label;
    std::string roofSurfaceId;
};

// Grid line
struct GridLine {
    std::string id;
    std::string label;
    vec2 startPoint;
    vec2 endPoint;
    bool isPrimary = true;
    bool showBubble = true;
};

// Annotation set for a plan view
struct AnnotationSet {
    std::string id;
    std::string name;
    PlanType planType;
    std::string level;
    f32 scale = 48.0f;      // 1/4" = 1'-0"

    std::vector<Dimension> dimensions;
    std::vector<TextLabel> labels;
    std::vector<Leader> leaders;
    std::vector<Symbol> symbols;
    std::vector<RoofAnnotation> roofAnnotations;
    std::vector<GridLine> gridLines;

    vec2 viewportCenter = {0.0f, 0.0f};
    f32 viewportWidth = 10000.0f;
    f32 viewportHeight = 8000.0f;
};

// Plan generator for creating 2D drawings with annotations
class PlanGenerator {
public:
    // Generate floor plan from building
    static AnnotationSet generateFloorPlan(const Building& building, const std::string& levelName = "Level 1");

    // Generate roof plan from building
    static AnnotationSet generateRoofPlan(const Building& building);

    // Auto-generate dimensions for walls
    static std::vector<Dimension> generateWallDimensions(const Building& building, f32 offset = 300.0f);

    // Auto-generate room labels from building data
    static std::vector<TextLabel> generateRoomLabels(const Building& building, const json& rooms);

    // Auto-generate roof annotations (pitch, drainage)
    static std::vector<RoofAnnotation> generateRoofAnnotations(const Building& building, const json& roofs);

    // Generate structural grid from building extents
    static std::vector<GridLine> generateStructuralGrid(const Building& building, f32 gridSpacing = 3048.0f);  // 10' in mm

    // Export plan to SVG
    static std::string exportToSVG(const Building& building, const AnnotationSet& annotations);

    // Export plan to DXF
    static std::string exportToDXF(const Building& building, const AnnotationSet& annotations);

    // Convert annotation set to JSON
    static json annotationSetToJson(const AnnotationSet& set);

    // Parse annotation set from JSON
    static AnnotationSet annotationSetFromJson(const json& j);

private:
    // SVG helpers
    static std::string svgHeader(f32 width, f32 height, f32 minX, f32 minY);
    static std::string svgFooter();
    static std::string svgLine(f32 x1, f32 y1, f32 x2, f32 y2, const std::string& stroke = "black", f32 strokeWidth = 1.0f);
    static std::string svgRect(f32 x, f32 y, f32 width, f32 height, const std::string& fill = "none", const std::string& stroke = "black");
    static std::string svgText(f32 x, f32 y, const std::string& text, f32 fontSize = 12.0f, const std::string& anchor = "middle");
    static std::string svgPolygon(const std::vector<vec2>& points, const std::string& fill = "none", const std::string& stroke = "black");
    static std::string svgArc(f32 x1, f32 y1, f32 x2, f32 y2, f32 radius, bool largeArc = false);
    static std::string svgArrow(f32 x1, f32 y1, f32 x2, f32 y2, f32 headSize = 10.0f);
    static std::string svgDimension(const Dimension& dim, f32 scale);
    static std::string svgPitchIndicator(f32 x, f32 y, f32 pitch, f32 rotation);
    static std::string svgDrainageArrow(f32 x, f32 y, f32 rotation);
    static std::string svgNorthArrow(f32 x, f32 y, f32 scale = 1.0f);
    static std::string svgSectionMarker(f32 x, f32 y, const std::string& label, f32 rotation);
    static std::string svgGridBubble(f32 x, f32 y, const std::string& label);

    // DXF helpers
    static std::string dxfHeader();
    static std::string dxfFooter();
    static std::string dxfLine(f32 x1, f32 y1, f32 x2, f32 y2, const std::string& layer = "0");
    static std::string dxfText(f32 x, f32 y, const std::string& text, f32 height = 100.0f, const std::string& layer = "0");
    static std::string dxfDimension(const Dimension& dim);

    // Calculate building bounds
    static void getBuildingBounds(const Building& building, f32& minX, f32& minY, f32& maxX, f32& maxY);

    // Format dimension value
    static std::string formatDimensionValue(f32 value, const std::string& unit, i32 precision);
};

// Implementation inline for header-only usage
inline AnnotationSet PlanGenerator::generateFloorPlan(const Building& building, const std::string& levelName) {
    AnnotationSet set;
    set.id = "floor_plan_" + levelName;
    set.name = "Floor Plan - " + levelName;
    set.planType = PlanType::FloorPlan;
    set.level = levelName;
    set.scale = 48.0f;  // 1/4" = 1'-0"

    // Generate dimensions
    set.dimensions = generateWallDimensions(building, 300.0f);

    // Generate grid
    set.gridLines = generateStructuralGrid(building);

    // Add north arrow
    f32 minX, minY, maxX, maxY;
    getBuildingBounds(building, minX, minY, maxX, maxY);

    Symbol northArrow;
    northArrow.id = "north_arrow";
    northArrow.type = SymbolType::NorthArrow;
    northArrow.position = {maxX + 1000.0f, maxY - 500.0f};
    northArrow.scale = 1.0f;
    set.symbols.push_back(northArrow);

    // Set viewport
    set.viewportCenter = {(minX + maxX) / 2.0f, (minY + maxY) / 2.0f};
    set.viewportWidth = (maxX - minX) + 2000.0f;
    set.viewportHeight = (maxY - minY) + 2000.0f;

    return set;
}

inline AnnotationSet PlanGenerator::generateRoofPlan(const Building& building) {
    AnnotationSet set;
    set.id = "roof_plan";
    set.name = "Roof Plan";
    set.planType = PlanType::RoofPlan;
    set.level = "Roof";
    set.scale = 48.0f;

    // Generate grid
    set.gridLines = generateStructuralGrid(building);

    // Add north arrow
    f32 minX, minY, maxX, maxY;
    getBuildingBounds(building, minX, minY, maxX, maxY);

    Symbol northArrow;
    northArrow.id = "north_arrow";
    northArrow.type = SymbolType::NorthArrow;
    northArrow.position = {maxX + 1000.0f, maxY - 500.0f};
    northArrow.scale = 1.0f;
    set.symbols.push_back(northArrow);

    // Set viewport
    set.viewportCenter = {(minX + maxX) / 2.0f, (minY + maxY) / 2.0f};
    set.viewportWidth = (maxX - minX) + 2000.0f;
    set.viewportHeight = (maxY - minY) + 2000.0f;

    return set;
}

inline std::vector<Dimension> PlanGenerator::generateWallDimensions(const Building& building, f32 offset) {
    std::vector<Dimension> dims;
    u32 dimCount = 0;

    for (const auto& wall : building.parametricWalls) {
        Dimension dim;
        dim.id = "dim_" + std::to_string(dimCount++);
        dim.startPoint = wall.startPoint;
        dim.endPoint = wall.endPoint;
        dim.offsetDistance = offset;
        dim.textHeight = 80.0f;
        dim.unit = "mm";
        dim.precision = 0;
        dim.showValue = true;
        dims.push_back(dim);
    }

    return dims;
}

inline std::vector<GridLine> PlanGenerator::generateStructuralGrid(const Building& building, f32 gridSpacing) {
    std::vector<GridLine> grids;

    f32 minX, minY, maxX, maxY;
    getBuildingBounds(building, minX, minY, maxX, maxY);

    // Add margin
    minX -= 500.0f;
    minY -= 500.0f;
    maxX += 500.0f;
    maxY += 500.0f;

    // Generate horizontal grids (numbered)
    i32 gridNum = 1;
    for (f32 y = minY; y <= maxY; y += gridSpacing) {
        GridLine grid;
        grid.id = "grid_h_" + std::to_string(gridNum);
        grid.label = std::to_string(gridNum);
        grid.startPoint = {minX - 300.0f, y};
        grid.endPoint = {maxX + 300.0f, y};
        grid.isPrimary = true;
        grid.showBubble = true;
        grids.push_back(grid);
        gridNum++;
    }

    // Generate vertical grids (lettered)
    char gridLetter = 'A';
    for (f32 x = minX; x <= maxX; x += gridSpacing) {
        GridLine grid;
        grid.id = "grid_v_";
        grid.id += gridLetter;
        grid.label = std::string(1, gridLetter);
        grid.startPoint = {x, minY - 300.0f};
        grid.endPoint = {x, maxY + 300.0f};
        grid.isPrimary = true;
        grid.showBubble = true;
        grids.push_back(grid);
        gridLetter++;
    }

    return grids;
}

inline void PlanGenerator::getBuildingBounds(const Building& building, f32& minX, f32& minY, f32& maxX, f32& maxY) {
    minX = minY = std::numeric_limits<f32>::max();
    maxX = maxY = std::numeric_limits<f32>::lowest();

    for (const auto& elem : building.elements) {
        minX = std::min({minX, elem.start.x, elem.end.x});
        minY = std::min({minY, elem.start.z, elem.end.z});
        maxX = std::max({maxX, elem.start.x, elem.end.x});
        maxY = std::max({maxY, elem.start.z, elem.end.z});
    }

    for (const auto& wall : building.parametricWalls) {
        minX = std::min({minX, wall.startPoint.x, wall.endPoint.x});
        minY = std::min({minY, wall.startPoint.y, wall.endPoint.y});
        maxX = std::max({maxX, wall.startPoint.x, wall.endPoint.x});
        maxY = std::max({maxY, wall.startPoint.y, wall.endPoint.y});
    }

    if (minX == std::numeric_limits<f32>::max()) {
        minX = minY = 0.0f;
        maxX = maxY = 10000.0f;
    }
}

inline std::string PlanGenerator::exportToSVG(const Building& building, const AnnotationSet& annotations) {
    std::stringstream ss;

    f32 minX, minY, maxX, maxY;
    getBuildingBounds(building, minX, minY, maxX, maxY);

    // Add margin for annotations
    f32 margin = 1000.0f;
    minX -= margin;
    minY -= margin;
    maxX += margin;
    maxY += margin;

    f32 width = maxX - minX;
    f32 height = maxY - minY;

    // SVG header
    ss << "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n";
    ss << "<svg xmlns=\"http://www.w3.org/2000/svg\" ";
    ss << "width=\"" << width << "\" height=\"" << height << "\" ";
    ss << "viewBox=\"" << minX << " " << -maxY << " " << width << " " << height << "\">\n";
    ss << "<rect width=\"100%\" height=\"100%\" fill=\"white\"/>\n";
    ss << "<g transform=\"scale(1,-1)\">\n";  // Flip Y for SVG

    // Draw walls
    for (const auto& elem : building.elements) {
        if (elem.type == ElementType::Wall) {
            ss << svgLine(elem.start.x, elem.start.z, elem.end.x, elem.end.z, "rgb(100,100,100)", 2.0f);
        }
    }

    for (const auto& wall : building.parametricWalls) {
        ss << svgLine(wall.startPoint.x, wall.startPoint.y, wall.endPoint.x, wall.endPoint.y, "rgb(50,50,50)", 3.0f);
    }

    // Draw grid lines
    for (const auto& grid : annotations.gridLines) {
        ss << svgLine(grid.startPoint.x, grid.startPoint.y, grid.endPoint.x, grid.endPoint.y, "rgb(200,200,200)", 0.5f);
        if (grid.showBubble) {
            // Grid bubble at start
            ss << "<circle cx=\"" << grid.startPoint.x << "\" cy=\"" << grid.startPoint.y
               << "\" r=\"150\" fill=\"white\" stroke=\"black\" stroke-width=\"1\"/>\n";
            ss << "<text x=\"" << grid.startPoint.x << "\" y=\"" << grid.startPoint.y
               << "\" text-anchor=\"middle\" dominant-baseline=\"central\" font-size=\"100\">"
               << grid.label << "</text>\n";
        }
    }

    // Draw dimensions
    for (const auto& dim : annotations.dimensions) {
        f32 dx = dim.endPoint.x - dim.startPoint.x;
        f32 dy = dim.endPoint.y - dim.startPoint.y;
        f32 len = std::sqrt(dx*dx + dy*dy);
        f32 nx = -dy / len * dim.offsetDistance;
        f32 ny = dx / len * dim.offsetDistance;

        // Dimension line
        ss << svgLine(dim.startPoint.x + nx, dim.startPoint.y + ny,
                      dim.endPoint.x + nx, dim.endPoint.y + ny, "black", 0.5f);

        // Extension lines
        ss << svgLine(dim.startPoint.x, dim.startPoint.y,
                      dim.startPoint.x + nx, dim.startPoint.y + ny, "black", 0.3f);
        ss << svgLine(dim.endPoint.x, dim.endPoint.y,
                      dim.endPoint.x + nx, dim.endPoint.y + ny, "black", 0.3f);

        // Dimension text
        f32 midX = (dim.startPoint.x + dim.endPoint.x) / 2.0f + nx;
        f32 midY = (dim.startPoint.y + dim.endPoint.y) / 2.0f + ny;
        std::string valueStr = formatDimensionValue(len, dim.unit, dim.precision);
        ss << "<text x=\"" << midX << "\" y=\"" << midY
           << "\" text-anchor=\"middle\" dominant-baseline=\"central\" font-size=\""
           << dim.textHeight << "\" transform=\"scale(1,-1) translate(0," << -2*midY << ")\">"
           << valueStr << "</text>\n";
    }

    // Draw labels
    for (const auto& label : annotations.labels) {
        ss << "<text x=\"" << label.position.x << "\" y=\"" << label.position.y
           << "\" text-anchor=\"middle\" dominant-baseline=\"central\" font-size=\""
           << label.textHeight << "\" transform=\"scale(1,-1) translate(0," << -2*label.position.y << ")\">"
           << label.text << "</text>\n";
    }

    // Draw roof annotations
    for (const auto& anno : annotations.roofAnnotations) {
        if (anno.type == RoofAnnotationType::PitchIndicator) {
            // Draw pitch triangle
            f32 x = anno.position.x;
            f32 y = anno.position.y;
            f32 rise = anno.pitch;
            f32 run = 12.0f;
            f32 scale = 50.0f;

            ss << "<path d=\"M " << x << " " << y << " L " << (x + run * scale) << " " << y
               << " L " << (x + run * scale) << " " << (y + rise * scale) << " Z\" "
               << "fill=\"none\" stroke=\"black\" stroke-width=\"1\"/>\n";
            ss << "<text x=\"" << (x + run * scale / 2) << "\" y=\"" << (y - 50)
               << "\" text-anchor=\"middle\" font-size=\"80\" transform=\"scale(1,-1) translate(0,"
               << -2*(y - 50) << ")\">" << static_cast<int>(rise) << ":12</text>\n";
        }
        else if (anno.type == RoofAnnotationType::DrainageArrow || anno.type == RoofAnnotationType::SlopeArrow) {
            // Draw arrow
            f32 angle = anno.rotation * 3.14159f / 180.0f;
            f32 len = 200.0f;
            f32 endX = anno.position.x + len * std::cos(angle);
            f32 endY = anno.position.y + len * std::sin(angle);
            ss << svgArrow(anno.position.x, anno.position.y, endX, endY, 30.0f);
        }
        else if (anno.type == RoofAnnotationType::RidgeLine ||
                 anno.type == RoofAnnotationType::ValleyLine ||
                 anno.type == RoofAnnotationType::HipLine) {
            std::string dashArray = (anno.type == RoofAnnotationType::RidgeLine) ? "" : "10,5";
            ss << "<line x1=\"" << anno.position.x << "\" y1=\"" << anno.position.y
               << "\" x2=\"" << anno.endPosition.x << "\" y2=\"" << anno.endPosition.y
               << "\" stroke=\"black\" stroke-width=\"2\"";
            if (!dashArray.empty()) {
                ss << " stroke-dasharray=\"" << dashArray << "\"";
            }
            ss << "/>\n";
        }
    }

    // Draw symbols
    for (const auto& sym : annotations.symbols) {
        if (sym.type == SymbolType::NorthArrow) {
            f32 x = sym.position.x;
            f32 y = sym.position.y;
            f32 s = 100.0f * sym.scale;
            ss << "<path d=\"M " << x << " " << (y - s) << " L " << (x - s/3) << " " << (y + s)
               << " L " << x << " " << (y + s/2) << " L " << (x + s/3) << " " << (y + s) << " Z\" "
               << "fill=\"black\" stroke=\"none\"/>\n";
            ss << "<text x=\"" << x << "\" y=\"" << (y - s - 30)
               << "\" text-anchor=\"middle\" font-size=\"80\" font-weight=\"bold\" "
               << "transform=\"scale(1,-1) translate(0," << -2*(y - s - 30) << ")\">N</text>\n";
        }
        else if (sym.type == SymbolType::SectionMarker) {
            f32 x = sym.position.x;
            f32 y = sym.position.y;
            f32 r = 100.0f * sym.scale;
            ss << "<circle cx=\"" << x << "\" cy=\"" << y << "\" r=\"" << r
               << "\" fill=\"white\" stroke=\"black\" stroke-width=\"2\"/>\n";
            ss << "<text x=\"" << x << "\" y=\"" << y
               << "\" text-anchor=\"middle\" dominant-baseline=\"central\" font-size=\"80\" font-weight=\"bold\" "
               << "transform=\"scale(1,-1) translate(0," << -2*y << ")\">" << sym.label << "</text>\n";
            // Direction arrow
            f32 angle = sym.rotation * 3.14159f / 180.0f;
            f32 ax = x + r * 1.5f * std::cos(angle);
            f32 ay = y + r * 1.5f * std::sin(angle);
            ss << svgArrow(x + r * std::cos(angle), y + r * std::sin(angle), ax, ay, 20.0f);
        }
    }

    ss << "</g>\n";
    ss << "</svg>\n";

    return ss.str();
}

inline std::string PlanGenerator::svgLine(f32 x1, f32 y1, f32 x2, f32 y2, const std::string& stroke, f32 strokeWidth) {
    std::stringstream ss;
    ss << "<line x1=\"" << x1 << "\" y1=\"" << y1 << "\" x2=\"" << x2 << "\" y2=\"" << y2
       << "\" stroke=\"" << stroke << "\" stroke-width=\"" << strokeWidth << "\"/>\n";
    return ss.str();
}

inline std::string PlanGenerator::svgArrow(f32 x1, f32 y1, f32 x2, f32 y2, f32 headSize) {
    std::stringstream ss;
    f32 angle = std::atan2(y2 - y1, x2 - x1);
    f32 a1 = angle + 2.5f;  // ~150 degrees
    f32 a2 = angle - 2.5f;

    ss << "<line x1=\"" << x1 << "\" y1=\"" << y1 << "\" x2=\"" << x2 << "\" y2=\"" << y2
       << "\" stroke=\"black\" stroke-width=\"2\"/>\n";
    ss << "<polygon points=\"" << x2 << "," << y2 << " "
       << (x2 - headSize * std::cos(a1)) << "," << (y2 - headSize * std::sin(a1)) << " "
       << (x2 - headSize * std::cos(a2)) << "," << (y2 - headSize * std::sin(a2))
       << "\" fill=\"black\"/>\n";

    return ss.str();
}

inline std::string PlanGenerator::formatDimensionValue(f32 value, const std::string& unit, i32 precision) {
    std::stringstream ss;

    if (unit == "feet" || unit == "ft") {
        // Convert to feet-inches
        f32 feet = std::floor(value);
        f32 inches = (value - feet) * 12.0f;
        if (precision == 0) {
            ss << static_cast<int>(feet) << "'-" << static_cast<int>(std::round(inches)) << "\"";
        } else {
            ss << static_cast<int>(feet) << "'-" << std::fixed << std::setprecision(precision) << inches << "\"";
        }
    } else {
        // Metric (mm)
        if (precision == 0) {
            ss << static_cast<int>(std::round(value));
        } else {
            ss << std::fixed << std::setprecision(precision) << value;
        }
    }

    return ss.str();
}

inline json PlanGenerator::annotationSetToJson(const AnnotationSet& set) {
    json j;
    j["id"] = set.id;
    j["name"] = set.name;

    // Plan type to string
    const char* planTypes[] = {"floor_plan", "roof_plan", "reflected_ceiling_plan", "site_plan",
                                "foundation_plan", "framing_plan", "elevation", "section"};
    j["plan_type"] = planTypes[static_cast<u32>(set.planType)];

    j["level"] = set.level;
    j["scale"] = set.scale;

    // Dimensions
    json dimsJson = json::array();
    for (const auto& dim : set.dimensions) {
        json dj;
        dj["id"] = dim.id;
        dj["start_point"] = {dim.startPoint.x, dim.startPoint.y};
        dj["end_point"] = {dim.endPoint.x, dim.endPoint.y};
        dj["offset_distance"] = dim.offsetDistance;
        dj["text_height"] = dim.textHeight;
        dj["unit"] = dim.unit;
        dj["precision"] = dim.precision;
        dj["show_value"] = dim.showValue;
        dimsJson.push_back(dj);
    }
    j["dimensions"] = dimsJson;

    // Labels
    json labelsJson = json::array();
    for (const auto& label : set.labels) {
        json lj;
        lj["id"] = label.id;
        lj["text"] = label.text;
        lj["position"] = {label.position.x, label.position.y};
        lj["rotation"] = label.rotation;
        lj["text_height"] = label.textHeight;
        lj["font_style"] = label.fontStyle;
        lj["justification"] = label.justification;
        lj["show_border"] = label.showBorder;
        lj["show_background"] = label.showBackground;
        labelsJson.push_back(lj);
    }
    j["labels"] = labelsJson;

    // Roof annotations
    json roofAnnoJson = json::array();
    for (const auto& anno : set.roofAnnotations) {
        json aj;
        aj["id"] = anno.id;
        const char* roofTypes[] = {"pitch_indicator", "drainage_arrow", "ridge_line", "valley_line",
                                    "hip_line", "eave_line", "rake_line", "slope_arrow"};
        aj["type"] = roofTypes[static_cast<u32>(anno.type)];
        aj["position"] = {anno.position.x, anno.position.y};
        aj["end_position"] = {anno.endPosition.x, anno.endPosition.y};
        aj["rotation"] = anno.rotation;
        aj["pitch"] = anno.pitch;
        aj["slope_percent"] = anno.slopePercent;
        aj["label"] = anno.label;
        aj["roof_surface_id"] = anno.roofSurfaceId;
        roofAnnoJson.push_back(aj);
    }
    j["roof_annotations"] = roofAnnoJson;

    // Grid lines
    json gridJson = json::array();
    for (const auto& grid : set.gridLines) {
        json gj;
        gj["id"] = grid.id;
        gj["label"] = grid.label;
        gj["start_point"] = {grid.startPoint.x, grid.startPoint.y};
        gj["end_point"] = {grid.endPoint.x, grid.endPoint.y};
        gj["is_primary"] = grid.isPrimary;
        gj["show_bubble"] = grid.showBubble;
        gridJson.push_back(gj);
    }
    j["grid_lines"] = gridJson;

    // Viewport
    j["viewport_center"] = {set.viewportCenter.x, set.viewportCenter.y};
    j["viewport_width"] = set.viewportWidth;
    j["viewport_height"] = set.viewportHeight;

    return j;
}

} // namespace arch
