#include "slicer_2d.hpp"
#include <fstream>
#include <sstream>
#include <iomanip>
#define _USE_MATH_DEFINES
#include <cmath>
#include <algorithm>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

namespace arch {
namespace slicer {

// ============================================================================
// CONSTRUCTOR / DESTRUCTOR
// ============================================================================

Slicer2D::Slicer2D() {
    initDefaults();
}

Slicer2D::~Slicer2D() = default;

void Slicer2D::initDefaults() {
    // Default layer configurations
    m_layerConfigs["wall"] = {"A-WALL", {0, 0, 0}, "continuous", 0.35f};
    m_layerConfigs["wall_hidden"] = {"A-WALL-HIDN", {0.5f, 0.5f, 0.5f}, "dashed", 0.18f};
    m_layerConfigs["column"] = {"S-COLS", {0, 0, 0}, "continuous", 0.50f};
    m_layerConfigs["beam"] = {"S-BEAM", {0, 0, 0}, "continuous", 0.35f};
    m_layerConfigs["floor"] = {"A-FLOR", {0.3f, 0.3f, 0.3f}, "continuous", 0.25f};
    m_layerConfigs["door"] = {"A-DOOR", {0, 0, 0}, "continuous", 0.25f};
    m_layerConfigs["window"] = {"A-GLAZ", {0, 0, 0}, "continuous", 0.25f};
    m_layerConfigs["dimension"] = {"A-DIMS", {0, 0, 0}, "continuous", 0.18f};
    m_layerConfigs["text"] = {"A-NOTE", {0, 0, 0}, "continuous", 0.18f};
    m_layerConfigs["hatch"] = {"A-PATT", {0.7f, 0.7f, 0.7f}, "continuous", 0.13f};

    // Default material hatch patterns
    m_materialHatches["wood"] = {"ANSI31", 1.0f};
    m_materialHatches["concrete"] = {"AR-CONC", 1.0f};
    m_materialHatches["steel"] = {"STEEL", 1.0f};
    m_materialHatches["insulation"] = {"INSUL", 1.0f};
    m_materialHatches["fiberglass"] = {"INSUL", 0.5f};
    m_materialHatches["gypsum"] = {"SOLID", 1.0f};
    m_materialHatches["drywall"] = {"SOLID", 1.0f};
    m_materialHatches["osb"] = {"PLYWOOD", 1.0f};
    m_materialHatches["plywood"] = {"PLYWOOD", 1.0f};
    m_materialHatches["brick"] = {"AR-BRSTD", 1.0f};
    m_materialHatches["air"] = {"", 0.0f};  // No hatch for air gaps
}

// ============================================================================
// GEOMETRY HELPERS
// ============================================================================

Point2D Slicer2D::projectTo2D(const vec3& point3D, const SlicePlane& plane) {
    switch (plane.type) {
        case SlicePlaneType::Horizontal:
            // Plan view: X, Z -> X, Y in 2D
            return Point2D(point3D.x, point3D.z);

        case SlicePlaneType::VerticalNS:
            // Section N-S: X, Y -> X, Y in 2D
            return Point2D(point3D.x, point3D.y);

        case SlicePlaneType::VerticalEW:
            // Section E-W: Z, Y -> X, Y in 2D
            return Point2D(point3D.z, point3D.y);

        case SlicePlaneType::Custom:
        default:
            // Project onto arbitrary plane
            // For now, just use XY
            return Point2D(point3D.x, point3D.y);
    }
}

std::optional<Point2D> Slicer2D::intersectLineWithPlane(
    const vec3& p1, const vec3& p2, const SlicePlane& plane
) {
    f32 d1, d2;

    switch (plane.type) {
        case SlicePlaneType::Horizontal:
            d1 = p1.y - plane.position;
            d2 = p2.y - plane.position;
            break;
        case SlicePlaneType::VerticalNS:
            d1 = p1.z - plane.position;
            d2 = p2.z - plane.position;
            break;
        case SlicePlaneType::VerticalEW:
            d1 = p1.x - plane.position;
            d2 = p2.x - plane.position;
            break;
        default:
            d1 = glm::dot(p1 - plane.origin, plane.normal);
            d2 = glm::dot(p2 - plane.origin, plane.normal);
            break;
    }

    // Check if line crosses plane
    if (d1 * d2 > 0) return std::nullopt;  // Both on same side

    // Calculate intersection point
    f32 t = d1 / (d1 - d2);
    vec3 intersection = p1 + t * (p2 - p1);

    return projectTo2D(intersection, plane);
}

std::vector<Line2D> Slicer2D::sliceBox(
    const vec3& center, const vec3& extents,
    const mat4& transform, const SlicePlane& plane
) {
    std::vector<Line2D> result;

    // 8 corners of the box
    vec3 corners[8] = {
        center + vec3(-extents.x, -extents.y, -extents.z),
        center + vec3(+extents.x, -extents.y, -extents.z),
        center + vec3(+extents.x, +extents.y, -extents.z),
        center + vec3(-extents.x, +extents.y, -extents.z),
        center + vec3(-extents.x, -extents.y, +extents.z),
        center + vec3(+extents.x, -extents.y, +extents.z),
        center + vec3(+extents.x, +extents.y, +extents.z),
        center + vec3(-extents.x, +extents.y, +extents.z)
    };

    // Transform corners
    for (int i = 0; i < 8; i++) {
        vec4 transformed = transform * vec4(corners[i], 1.0f);
        corners[i] = vec3(transformed);
    }

    // 12 edges of the box
    int edges[12][2] = {
        {0, 1}, {1, 2}, {2, 3}, {3, 0},  // Bottom face
        {4, 5}, {5, 6}, {6, 7}, {7, 4},  // Top face
        {0, 4}, {1, 5}, {2, 6}, {3, 7}   // Vertical edges
    };

    // Find all intersection points
    std::vector<Point2D> intersectionPoints;
    for (const auto& edge : edges) {
        auto pt = intersectLineWithPlane(corners[edge[0]], corners[edge[1]], plane);
        if (pt.has_value()) {
            intersectionPoints.push_back(pt.value());
        }
    }

    // Connect intersection points to form outline
    if (intersectionPoints.size() >= 2) {
        // Sort points by angle around centroid for proper polygon
        Point2D centroid = {0, 0};
        for (const auto& p : intersectionPoints) {
            centroid += p;
        }
        centroid /= static_cast<f32>(intersectionPoints.size());

        std::sort(intersectionPoints.begin(), intersectionPoints.end(),
            [&centroid](const Point2D& a, const Point2D& b) {
                return std::atan2(a.y - centroid.y, a.x - centroid.x) <
                       std::atan2(b.y - centroid.y, b.x - centroid.x);
            });

        // Create lines connecting consecutive points
        for (size_t i = 0; i < intersectionPoints.size(); i++) {
            Line2D line;
            line.start = intersectionPoints[i];
            line.end = intersectionPoints[(i + 1) % intersectionPoints.size()];
            line.layer = "0";
            line.lineType = "continuous";
            line.lineWeight = 0.35f;
            result.push_back(line);
        }
    }

    return result;
}

// ============================================================================
// SLICE OPERATIONS
// ============================================================================

SliceResult Slicer2D::sliceElement(const StructuralElement& element, const SlicePlane& plane) {
    SliceResult result;
    result.elementType = "element";

    // Calculate element center and extents
    vec3 center = (element.start + element.end) * 0.5f;
    vec3 dir = glm::normalize(element.end - element.start);
    f32 length = glm::length(element.end - element.start);

    vec3 extents;
    mat4 transform = mat4(1.0f);

    switch (element.type) {
        case ElementType::Column:
            extents = vec3(element.width * 0.5f, length * 0.5f, element.depth * 0.5f);
            break;

        case ElementType::Beam:
            extents = vec3(length * 0.5f, element.depth * 0.5f, element.width * 0.5f);
            // Rotate to align with beam direction
            if (glm::abs(dir.x) > 0.001f || glm::abs(dir.z) > 0.001f) {
                f32 angle = std::atan2(dir.z, dir.x);
                transform = glm::rotate(mat4(1.0f), angle, vec3(0, 1, 0));
            }
            break;

        case ElementType::Wall:
            extents = vec3(length * 0.5f, (element.end.y - element.start.y) * 0.5f, element.depth * 0.5f);
            break;

        case ElementType::Floor:
        case ElementType::Roof:
            extents = vec3(
                std::abs(element.end.x - element.start.x) * 0.5f,
                element.depth * 0.5f,
                std::abs(element.end.z - element.start.z) * 0.5f
            );
            break;

        default:
            extents = vec3(element.width * 0.5f, element.depth * 0.5f, element.width * 0.5f);
            break;
    }

    // Get layer config
    std::string layerKey;
    switch (element.type) {
        case ElementType::Column: layerKey = "column"; break;
        case ElementType::Beam: layerKey = "beam"; break;
        case ElementType::Wall: layerKey = "wall"; break;
        case ElementType::Floor: layerKey = "floor"; break;
        default: layerKey = "wall"; break;
    }

    auto& config = m_layerConfigs[layerKey];

    // Slice the box
    auto lines = sliceBox(center, extents, transform, plane);
    for (auto& line : lines) {
        line.layer = config.name;
        line.color = config.color;
        line.lineWeight = config.lineWeight;
        line.lineType = config.lineType;
    }

    result.lines = lines;
    return result;
}

SliceResult Slicer2D::sliceWall(
    const ParametricWall& wall, const WallType& wallType, const SlicePlane& plane
) {
    SliceResult result;
    result.elementId = wall.id;
    result.elementType = "wall";

    auto& config = m_layerConfigs["wall"];
    f32 totalThickness = wallType.getTotalThickness();

    // Wall direction and normal
    vec2 wallDir = wall.getDirection();
    vec2 wallNormal = wall.getNormal();

    // For plan views (horizontal slice)
    if (plane.type == SlicePlaneType::Horizontal) {
        // Check if slice plane intersects wall height
        if (plane.position < wall.baseHeight || plane.position > wall.topHeight) {
            return result;  // Wall not at this level
        }

        // Create wall outline in plan
        f32 halfThick = totalThickness * 0.5f;
        Point2D p1 = wall.startPoint + wallNormal * halfThick;
        Point2D p2 = wall.endPoint + wallNormal * halfThick;
        Point2D p3 = wall.endPoint - wallNormal * halfThick;
        Point2D p4 = wall.startPoint - wallNormal * halfThick;

        Polyline2D outline;
        outline.points = {p1, p2, p3, p4};
        outline.closed = true;
        outline.layer = config.name;
        outline.color = config.color;
        outline.lineWeight = config.lineWeight;
        result.polylines.push_back(outline);

        // Add hatch for wall
        Hatch2D hatch;
        hatch.boundaries.push_back(outline);
        hatch.pattern = "ANSI31";
        hatch.layer = m_layerConfigs["hatch"].name;
        hatch.color = m_layerConfigs["hatch"].color;
        result.hatches.push_back(hatch);
    }
    // For section views
    else {
        // Check if slice plane intersects wall
        f32 wallStart, wallEnd;
        if (plane.type == SlicePlaneType::VerticalNS) {
            wallStart = std::min(wall.startPoint.y, wall.endPoint.y);
            wallEnd = std::max(wall.startPoint.y, wall.endPoint.y);
        } else {
            wallStart = std::min(wall.startPoint.x, wall.endPoint.x);
            wallEnd = std::max(wall.startPoint.x, wall.endPoint.x);
        }

        // Generate section cut through wall layers
        f32 currentOffset = -totalThickness * 0.5f;

        for (const auto& layer : wallType.layers) {
            // Layer rectangle in section
            Polyline2D layerOutline;
            f32 x1 = currentOffset;
            f32 x2 = currentOffset + layer.thickness;
            f32 y1 = wall.baseHeight;
            f32 y2 = wall.topHeight;

            layerOutline.points = {
                {x1, y1}, {x2, y1}, {x2, y2}, {x1, y2}
            };
            layerOutline.closed = true;
            layerOutline.layer = config.name;
            layerOutline.lineWeight = 0.25f;
            result.polylines.push_back(layerOutline);

            // Add material hatch
            auto hatch = createMaterialHatch(layerOutline, layer.material);
            if (!hatch.pattern.empty()) {
                result.hatches.push_back(hatch);
            }

            currentOffset += layer.thickness;
        }
    }

    return result;
}

SliceResult Slicer2D::generateFloorPlan(const Building& building, f32 cutHeight) {
    SliceResult result;
    SlicePlane plane = SlicePlane::horizontal(cutHeight, "Floor Plan");

    // For floor plans, prefer ParametricWalls (correct 2D representation)
    // Only fall back to StructuralElements if no parametric walls exist
    if (!building.parametricWalls.empty()) {
        for (const auto& wall : building.parametricWalls) {
            if (wall.wallTypeIndex < building.wallTypes.size()) {
                auto wallResult = sliceWall(wall, building.wallTypes[wall.wallTypeIndex], plane);
                result.merge(wallResult);
            }
        }
    } else {
        // Fallback: slice structural elements (less accurate for walls)
        for (const auto& element : building.elements) {
            auto elemResult = sliceElement(element, plane);
            result.merge(elemResult);
        }
    }

    return result;
}

SliceResult Slicer2D::generateSection(const Building& building, const SlicePlane& plane) {
    SliceResult result;

    for (const auto& element : building.elements) {
        auto elemResult = sliceElement(element, plane);
        result.merge(elemResult);
    }

    for (const auto& wall : building.parametricWalls) {
        if (wall.wallTypeIndex < building.wallTypes.size()) {
            auto wallResult = sliceWall(wall, building.wallTypes[wall.wallTypeIndex], plane);
            result.merge(wallResult);
        }
    }

    return result;
}

SliceResult Slicer2D::sliceBuilding(const Building& building, const SlicePlane& plane) {
    if (plane.type == SlicePlaneType::Horizontal) {
        return generateFloorPlan(building, plane.position);
    } else {
        return generateSection(building, plane);
    }
}

// ============================================================================
// DETAIL GENERATION
// ============================================================================

WallSectionDetail Slicer2D::generateWallDetail(const WallType& wallType, f32 wallHeight) {
    WallSectionDetail detail;
    detail.wallTypeId = wallType.id;
    detail.wallTypeName = wallType.name;
    detail.totalThickness = wallType.getTotalThickness();
    detail.detailScale = 1.5f;  // 1-1/2" = 1'-0"

    f32 currentX = 0.0f;

    for (const auto& layer : wallType.layers) {
        WallSectionDetail::LayerDetail layerDetail;
        layerDetail.name = layer.name;
        layerDetail.material = layer.material;
        layerDetail.thickness = layer.thickness;

        // Create layer outline
        layerDetail.outline.points = {
            {currentX, 0},
            {currentX + layer.thickness, 0},
            {currentX + layer.thickness, wallHeight},
            {currentX, wallHeight}
        };
        layerDetail.outline.closed = true;
        layerDetail.outline.layer = "A-DETL";
        layerDetail.outline.lineWeight = 0.25f;

        // Create hatch for layer
        layerDetail.hatch = createMaterialHatch(layerDetail.outline, layer.material);

        // Add layer label
        Text2D label;
        label.position = {currentX + layer.thickness * 0.5f, wallHeight + 0.5f};
        label.text = layer.name;
        label.height = 0.1f;
        label.justification = "center";
        label.layer = "A-NOTE";
        layerDetail.labels.push_back(label);

        // Add thickness dimension
        Text2D thicknessNote;
        thicknessNote.position = {currentX + layer.thickness * 0.5f, -0.3f};
        std::stringstream ss;
        ss << std::fixed << std::setprecision(2) << (layer.thickness * 12.0f) << "\"";
        thicknessNote.text = ss.str();
        thicknessNote.height = 0.08f;
        thicknessNote.justification = "center";
        thicknessNote.layer = "A-DIMS";
        layerDetail.labels.push_back(thicknessNote);

        detail.layers.push_back(layerDetail);
        currentX += layer.thickness;
    }

    // Add overall dimension
    Dimension2D overallDim;
    overallDim.point1 = {0, -0.5f};
    overallDim.point2 = {detail.totalThickness, -0.5f};
    overallDim.textPosition = {detail.totalThickness * 0.5f, -0.7f};
    std::stringstream ss;
    ss << std::fixed << std::setprecision(2) << (detail.totalThickness * 12.0f) << "\" TOTAL";
    overallDim.text = ss.str();
    overallDim.layer = "A-DIMS";
    detail.dimensions.push_back(overallDim);

    return detail;
}

Hatch2D Slicer2D::createMaterialHatch(const Polyline2D& boundary, const std::string& material) {
    Hatch2D hatch;
    hatch.boundaries.push_back(boundary);
    hatch.layer = m_layerConfigs["hatch"].name;
    hatch.color = m_layerConfigs["hatch"].color;

    auto it = m_materialHatches.find(material);
    if (it != m_materialHatches.end()) {
        hatch.pattern = it->second.first;
        hatch.scale = it->second.second;
    } else {
        hatch.pattern = "ANSI31";  // Default
        hatch.scale = 1.0f;
    }

    return hatch;
}

// ============================================================================
// SVG EXPORT
// ============================================================================

std::string Slicer2D::colorToSVG(const vec3& color) {
    std::stringstream ss;
    ss << "rgb(" << static_cast<int>(color.r * 255) << ","
                 << static_cast<int>(color.g * 255) << ","
                 << static_cast<int>(color.b * 255) << ")";
    return ss.str();
}

std::string Slicer2D::svgLine(const Line2D& line, f32 scale) {
    std::stringstream ss;
    ss << "<line x1=\"" << line.start.x * scale << "\" y1=\"" << -line.start.y * scale
       << "\" x2=\"" << line.end.x * scale << "\" y2=\"" << -line.end.y * scale
       << "\" stroke=\"" << colorToSVG(line.color)
       << "\" stroke-width=\"" << line.lineWeight * scale;

    if (line.lineType == "dashed") {
        ss << "\" stroke-dasharray=\"" << 4 * scale << "," << 2 * scale;
    } else if (line.lineType == "hidden") {
        ss << "\" stroke-dasharray=\"" << 2 * scale << "," << 2 * scale;
    }

    ss << "\"/>\n";
    return ss.str();
}

std::string Slicer2D::svgPolyline(const Polyline2D& poly, f32 scale) {
    if (poly.points.size() < 2) return "";

    std::stringstream ss;
    ss << "<" << (poly.closed ? "polygon" : "polyline") << " points=\"";
    for (const auto& p : poly.points) {
        ss << p.x * scale << "," << -p.y * scale << " ";
    }
    ss << "\" fill=\"" << (poly.closed ? "none" : "none")
       << "\" stroke=\"" << colorToSVG(poly.color)
       << "\" stroke-width=\"" << poly.lineWeight * scale << "\"/>\n";
    return ss.str();
}

std::string Slicer2D::svgCircle(const Circle2D& circle, f32 scale) {
    std::stringstream ss;
    ss << "<circle cx=\"" << circle.center.x * scale
       << "\" cy=\"" << -circle.center.y * scale
       << "\" r=\"" << circle.radius * scale
       << "\" fill=\"none\" stroke=\"" << colorToSVG(circle.color)
       << "\" stroke-width=\"" << circle.lineWeight * scale << "\"/>\n";
    return ss.str();
}

std::string Slicer2D::svgArc(const Arc2D& arc, f32 scale) {
    // SVG arc uses path with A command
    // Calculate start and end points
    f32 startX = arc.center.x + arc.radius * std::cos(arc.startAngle);
    f32 startY = arc.center.y + arc.radius * std::sin(arc.startAngle);
    f32 endX = arc.center.x + arc.radius * std::cos(arc.endAngle);
    f32 endY = arc.center.y + arc.radius * std::sin(arc.endAngle);

    // Determine if we need large arc flag
    f32 angleDiff = arc.endAngle - arc.startAngle;
    while (angleDiff < 0) angleDiff += 2 * M_PI;
    int largeArcFlag = (angleDiff > M_PI) ? 1 : 0;
    int sweepFlag = 1;  // Clockwise in SVG (which is flipped Y)

    std::stringstream ss;
    ss << "<path d=\"M " << startX * scale << " " << -startY * scale
       << " A " << arc.radius * scale << " " << arc.radius * scale
       << " 0 " << largeArcFlag << " " << sweepFlag
       << " " << endX * scale << " " << -endY * scale
       << "\" fill=\"none\" stroke=\"" << colorToSVG(arc.color)
       << "\" stroke-width=\"" << arc.lineWeight * scale << "\"/>\n";
    return ss.str();
}

std::string Slicer2D::svgText(const Text2D& text, f32 scale) {
    std::stringstream ss;
    ss << "<text x=\"" << text.position.x * scale
       << "\" y=\"" << -text.position.y * scale
       << "\" font-size=\"" << text.height * scale
       << "\" fill=\"" << colorToSVG(text.color) << "\"";

    if (text.justification == "center") {
        ss << " text-anchor=\"middle\"";
    } else if (text.justification == "right") {
        ss << " text-anchor=\"end\"";
    }

    if (text.rotation != 0.0f) {
        ss << " transform=\"rotate(" << glm::degrees(text.rotation)
           << " " << text.position.x * scale << " " << -text.position.y * scale << ")\"";
    }

    ss << ">" << text.text << "</text>\n";
    return ss.str();
}

std::string Slicer2D::svgHatch(const Hatch2D& hatch, f32 scale) {
    if (hatch.boundaries.empty()) return "";

    std::stringstream ss;

    // Simplified hatch - just fill with semi-transparent color
    for (const auto& boundary : hatch.boundaries) {
        if (boundary.points.size() < 3) continue;

        ss << "<polygon points=\"";
        for (const auto& p : boundary.points) {
            ss << p.x * scale << "," << -p.y * scale << " ";
        }
        ss << "\" fill=\"" << colorToSVG(hatch.color)
           << "\" fill-opacity=\"0.3\" stroke=\"none\"/>\n";
    }

    return ss.str();
}

std::string Slicer2D::exportToSVG(const SliceResult& result, f32 scale) {
    // Calculate bounding box
    f32 minX = 1e9f, minY = 1e9f, maxX = -1e9f, maxY = -1e9f;

    for (const auto& line : result.lines) {
        minX = std::min({minX, line.start.x, line.end.x});
        minY = std::min({minY, line.start.y, line.end.y});
        maxX = std::max({maxX, line.start.x, line.end.x});
        maxY = std::max({maxY, line.start.y, line.end.y});
    }
    for (const auto& poly : result.polylines) {
        for (const auto& p : poly.points) {
            minX = std::min(minX, p.x);
            minY = std::min(minY, p.y);
            maxX = std::max(maxX, p.x);
            maxY = std::max(maxY, p.y);
        }
    }

    f32 margin = 10.0f;
    f32 width = (maxX - minX) * scale + 2 * margin;
    f32 height = (maxY - minY) * scale + 2 * margin;

    std::stringstream svg;
    svg << "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n";
    svg << "<svg xmlns=\"http://www.w3.org/2000/svg\" "
        << "width=\"" << width << "\" height=\"" << height << "\" "
        << "viewBox=\"" << (minX * scale - margin) << " " << (-maxY * scale - margin)
        << " " << width << " " << height << "\">\n";

    svg << "<rect width=\"100%\" height=\"100%\" fill=\"white\"/>\n";

    // Hatches first (background)
    for (const auto& hatch : result.hatches) {
        svg << svgHatch(hatch, scale);
    }

    // Lines
    for (const auto& line : result.lines) {
        svg << svgLine(line, scale);
    }

    // Polylines
    for (const auto& poly : result.polylines) {
        svg << svgPolyline(poly, scale);
    }

    // Circles
    for (const auto& circle : result.circles) {
        svg << svgCircle(circle, scale);
    }

    // Arcs
    for (const auto& arc : result.arcs) {
        svg << svgArc(arc, scale);
    }

    // Text annotations
    for (const auto& text : result.annotations) {
        svg << svgText(text, scale);
    }

    svg << "</svg>\n";
    return svg.str();
}

bool Slicer2D::exportToSVGFile(const SliceResult& result, const std::string& filepath, f32 scale) {
    std::ofstream file(filepath);
    if (!file.is_open()) return false;

    file << exportToSVG(result, scale);
    return true;
}

// ============================================================================
// DXF EXPORT
// ============================================================================

std::string Slicer2D::dxfHeader() {
    return
        "0\nSECTION\n2\nHEADER\n"
        "9\n$ACADVER\n1\nAC1015\n"
        "9\n$INSUNITS\n70\n4\n"
        "0\nENDSEC\n";
}

std::string Slicer2D::dxfTables() {
    std::stringstream ss;
    ss << "0\nSECTION\n2\nTABLES\n";

    // Layer table
    ss << "0\nTABLE\n2\nLAYER\n";
    for (const auto& [name, config] : m_layerConfigs) {
        ss << "0\nLAYER\n2\n" << config.name << "\n70\n0\n62\n7\n6\nCONTINUOUS\n";
    }
    ss << "0\nENDTAB\n";

    ss << "0\nENDSEC\n";
    return ss.str();
}

std::string Slicer2D::dxfLine(const Line2D& line) {
    std::stringstream ss;
    ss << "0\nLINE\n8\n" << line.layer << "\n"
       << "10\n" << line.start.x << "\n20\n" << line.start.y << "\n30\n0.0\n"
       << "11\n" << line.end.x << "\n21\n" << line.end.y << "\n31\n0.0\n";
    return ss.str();
}

std::string Slicer2D::dxfPolyline(const Polyline2D& poly) {
    if (poly.points.size() < 2) return "";

    std::stringstream ss;
    ss << "0\nLWPOLYLINE\n8\n" << poly.layer << "\n"
       << "90\n" << poly.points.size() << "\n"
       << "70\n" << (poly.closed ? 1 : 0) << "\n";

    for (const auto& p : poly.points) {
        ss << "10\n" << p.x << "\n20\n" << p.y << "\n";
    }
    return ss.str();
}

std::string Slicer2D::dxfText(const Text2D& text) {
    std::stringstream ss;
    ss << "0\nTEXT\n8\n" << text.layer << "\n"
       << "10\n" << text.position.x << "\n20\n" << text.position.y << "\n30\n0.0\n"
       << "40\n" << text.height << "\n"
       << "1\n" << text.text << "\n";

    if (text.rotation != 0.0f) {
        ss << "50\n" << glm::degrees(text.rotation) << "\n";
    }
    return ss.str();
}

std::string Slicer2D::dxfArc(const Arc2D& arc) {
    std::stringstream ss;
    ss << "0\nARC\n8\n" << arc.layer << "\n"
       << "10\n" << arc.center.x << "\n20\n" << arc.center.y << "\n30\n0.0\n"
       << "40\n" << arc.radius << "\n"
       << "50\n" << glm::degrees(arc.startAngle) << "\n"
       << "51\n" << glm::degrees(arc.endAngle) << "\n";
    return ss.str();
}

std::string Slicer2D::dxfHatch(const Hatch2D& hatch) {
    // Simplified - just output boundary as polyline with hatch pattern reference
    std::stringstream ss;
    for (const auto& boundary : hatch.boundaries) {
        ss << dxfPolyline(boundary);
    }
    return ss.str();
}

std::string Slicer2D::dxfEntities(const SliceResult& result) {
    std::stringstream ss;
    ss << "0\nSECTION\n2\nENTITIES\n";

    for (const auto& line : result.lines) {
        ss << dxfLine(line);
    }
    for (const auto& poly : result.polylines) {
        ss << dxfPolyline(poly);
    }
    for (const auto& arc : result.arcs) {
        ss << dxfArc(arc);
    }
    for (const auto& hatch : result.hatches) {
        ss << dxfHatch(hatch);
    }
    for (const auto& text : result.annotations) {
        ss << dxfText(text);
    }

    ss << "0\nENDSEC\n";
    return ss.str();
}

std::string Slicer2D::dxfFooter() {
    return "0\nEOF\n";
}

std::string Slicer2D::exportToDXF(const SliceResult& result) {
    std::stringstream dxf;
    dxf << dxfHeader();
    dxf << dxfTables();
    dxf << dxfEntities(result);
    dxf << dxfFooter();
    return dxf.str();
}

bool Slicer2D::exportToDXFFile(const SliceResult& result, const std::string& filepath) {
    std::ofstream file(filepath);
    if (!file.is_open()) return false;

    file << exportToDXF(result);
    return true;
}

std::string Slicer2D::wallDetailToSVG(const WallSectionDetail& detail, f32 scale) {
    SliceResult result;

    // Convert detail layers to slice result format
    for (const auto& layer : detail.layers) {
        result.polylines.push_back(layer.outline);
        if (!layer.hatch.pattern.empty()) {
            result.hatches.push_back(layer.hatch);
        }
        for (const auto& label : layer.labels) {
            result.annotations.push_back(label);
        }
    }

    return exportToSVG(result, scale * detail.detailScale * 12.0f);  // Scale up for detail
}

// ============================================================================
// CONFIGURATION
// ============================================================================

void Slicer2D::setLayerConfig(const std::string& elementType, const LayerConfig& config) {
    m_layerConfigs[elementType] = config;
}

void Slicer2D::setMaterialHatch(const std::string& material, const std::string& pattern, f32 scale) {
    m_materialHatches[material] = {pattern, scale};
}

// ============================================================================
// GLOBAL INSTANCE
// ============================================================================

Slicer2D& getSlicer() {
    static Slicer2D instance;
    return instance;
}

} // namespace slicer
} // namespace arch
