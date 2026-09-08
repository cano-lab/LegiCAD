#pragma once

#include "types.hpp"
#include "obc_engine.hpp"
#include "slicer_2d.hpp"
#include <string>
#include <vector>
#include <unordered_map>
#include <optional>
#include <memory>

// Forward declare archgeometry types for optional integration
namespace archgeometry {
    class SchemaDocument;
    class QueryAPI;
}

namespace arch {
namespace qbd {

// ============================================================================
// QBD JSON FORMAT DOCUMENTATION (for translators/interpreters)
// ============================================================================
//
// The QBD interface expects JSON with the following structure. All dimensions
// are in millimeters (mm). Coordinate system: X = width, Y = height, Z = depth.
//
// Required fields:
//   - success: boolean
//   - width: number (building width in mm)
//   - depth: number (building depth in mm)
//
// Optional arrays:
//
// walls_batch: Array of wall objects
//   {
//     "start": [x, y, z],        // Wall start point in mm
//     "end": [x, y, z],          // Wall end point in mm
//     "height": 2700,            // Wall height in mm (default 2700)
//     "wall_type": "ext_2x6",    // Wall type identifier
//     "level_name": "Level 1",
//     "category": "exterior",    // "exterior", "interior", or "wet_wall"
//     "rooms": ["room1", "room2"] // Rooms on each side (can be null)
//   }
//
// floors_batch: Array of floor objects (NEW)
//   {
//     "start": [x, y, z],        // Bottom-left corner in mm (y = floor elevation)
//     "end": [x, y, z],          // Top-right corner in mm (y = same elevation)
//     "thickness": 300,          // Floor slab thickness in mm (default 300)
//     "level_name": "Level 1",
//     "room": "living_room"      // Optional: room this floor belongs to
//   }
//
// doors: Array of door objects
//   {
//     "wall_index": 0,           // Index into walls_batch array
//     "offset": 1500,            // Distance from wall start to door center (mm)
//     "width": 900,              // Door width in mm (default 900)
//     "height": 2100,            // Door height in mm (default 2100)
//     "type": "swing",           // "swing", "entry", "pocket", "sliding", "bifold", "french", "barn"
//     "swing": "left_in",        // "left_in", "right_in", "left_out", "right_out", "left", "right"
//     "room1": "living",         // Room on one side
//     "room2": "kitchen"         // Room on other side
//   }
//
// windows: Array of window objects
//   {
//     "wall_index": 0,           // Index into walls_batch array
//     "offset": 2000,            // Distance from wall start to window center (mm)
//     "width": 1200,             // Window width in mm (default 1200)
//     "height": 1200,            // Window height in mm (default 1200)
//     "sill_height": 900,        // Height from floor to bottom of window (mm)
//     "type": "double_hung",     // "fixed", "casement", "double_hung", "sliding", "awning"
//     "room": "bedroom"
//   }
//
// roofs: Array of roof objects
//   {
//     "id": "roof_1",
//     "type": "gable",           // "flat", "gable", "hip", "shed", "mansard", "gambrel"
//     "pitch": 6.0,              // Rise per 12" run (e.g., 6:12)
//     "overhang": 600,           // Eave overhang in mm
//     "ridge_height": 3000,      // Height of ridge above wall top in mm
//     "surfaces": [              // Array of roof surface polygons
//       {
//         "id": "surface_1",
//         "name": "west",
//         "pitch": 26.57,        // Slope in degrees
//         "vertices": [[x,y,z], [x,y,z], ...]  // Polygon vertices in mm
//       }
//     ],
//     "ridges": [...],           // Optional ridge lines
//     "dormers": [...],          // Optional dormers
//     "skylights": [...]         // Optional skylights
//   }
//
// rooms: Object with room_id as key
//   {
//     "living_room": {
//       "name": "Living Room",
//       "room_type": "living",
//       "area": 25000000,        // Area in mm² (25 m²)
//       "bounds": {"x": 0, "y": 0, "width": 5000, "height": 5000},
//       "center": {"x": 2500, "y": 2500}
//     }
//   }
//
// summary: Statistics object
//   {
//     "total_walls": 12,
//     "exterior_walls": 4,
//     "interior_walls": 6,
//     "wet_walls": 2,
//     "doors": 5,
//     "windows": 8,
//     "floors": 1,               // NEW
//     "rooms_placed": 6,
//     "rooms_requested": 6
//   }
//
// ============================================================================

// ============================================================================
// QBD INPUT TYPES (from Python QBD system)
// ============================================================================

// Wall category from QBD
enum class WallCategory : u32 {
    Exterior,
    Interior,
    WetWall      // Plumbing walls (kitchen, bath)
};

// Door type from QBD
enum class DoorType : u32 {
    Swing,
    Entry,
    Pocket,
    Sliding,
    Bifold,
    French,
    Barn
};

// Door swing direction
enum class DoorSwing : u32 {
    LeftIn,
    RightIn,
    LeftOut,
    RightOut,
    Left,   // For pocket/sliding
    Right
};

// Window type from QBD
enum class WindowType : u32 {
    Fixed,
    Casement,
    DoubleHung,
    Sliding,
    Awning
};

// Room zone
enum class RoomZone : u32 {
    Public,      // Living, dining, entry
    Private,     // Bedrooms
    Service,     // Kitchen, laundry, garage
    Circulation  // Hallways, stairs
};

// Wall from QBD output
struct QBDWall {
    vec3 start;
    vec3 end;
    f32 height = 10.0f;
    std::string wallType;       // Wall type name or variable
    std::string levelName;
    WallCategory category = WallCategory::Interior;
    std::string room1;          // Room on one side
    std::string room2;          // Room on other side
    std::string materialOverride;  // Optional material override (e.g., "polyhaven/brick_wall_006")

    f32 length() const {
        return glm::length(vec2(end.x - start.x, end.y - start.y));
    }
};

// Floor from QBD output
// JSON format in floors_batch:
// {
//   "start": [x, y, z],     // Bottom-left corner in mm (y = floor elevation)
//   "end": [x, y, z],       // Top-right corner in mm (y = floor elevation)
//   "thickness": 300,       // Floor thickness in mm (default 300)
//   "level_name": "Level 1",
//   "room": "living_room"   // Optional: room this floor belongs to
// }
struct QBDFloor {
    vec3 start;                 // Bottom-left corner (X, Y elevation, Z)
    vec3 end;                   // Top-right corner (X, Y elevation, Z)
    f32 thickness = 300.0f;     // Floor thickness in mm (default 300mm = ~12")
    std::string levelName;
    std::string room;           // Room this floor belongs to (optional)
    std::string material;       // Optional material override (e.g., "polyhaven/wood_floor_deck")

    f32 area() const {
        return std::abs((end.x - start.x) * (end.z - start.z));
    }

    vec2 dimensions() const {
        return vec2(std::abs(end.x - start.x), std::abs(end.z - start.z));
    }
};

// Door from QBD output (positioned by wall index and offset)
struct QBDDoor {
    i32 wallIndex = 0;          // Index into walls_batch array
    f32 offset = 0.0f;          // Distance from wall start to door center (mm)
    f32 width = 900.0f;         // Door width (mm) - 900mm standard
    f32 height = 2100.0f;       // Door height (mm) - 2100mm standard
    DoorType type = DoorType::Swing;
    DoorSwing swing = DoorSwing::LeftIn;
    std::string room1;
    std::string room2;
};

// Window from QBD output
struct QBDWindow {
    i32 wallIndex = 0;          // Index into walls_batch array
    f32 offset = 0.0f;          // Distance from wall start to window center (mm)
    f32 width = 1200.0f;        // Window width (mm)
    f32 height = 1200.0f;       // Window height (mm)
    f32 sillHeight = 900.0f;    // Height from floor to bottom of window (mm)
    WindowType type = WindowType::DoubleHung;
    std::string room;
};

// Roof type
enum class RoofType : u32 {
    Flat,
    Gable,
    Hip,
    Shed,
    Mansard,
    Gambrel
};

// Roof surface (a single face of the roof)
struct QBDRoofSurface {
    std::string id;
    std::string name;           // e.g., "west", "east", "south", "north"
    std::vector<vec3> vertices; // Polygon vertices in mm [X, Y, Z]
    f32 pitch = 0.0f;           // Slope in degrees
};

// Roof ridge line
struct QBDRoofRidge {
    std::string id;
    vec3 startPoint;            // Start of ridge in mm
    vec3 endPoint;              // End of ridge in mm
    f32 height = 0.0f;          // Ridge height above wall top
};

// Dormer
struct QBDDormer {
    std::string id;
    std::string type;           // "gable", "shed", "hip"
    vec3 position;              // Center position in mm
    f32 width = 1200.0f;        // mm
    f32 height = 1500.0f;       // mm
    f32 depth = 900.0f;         // mm
};

// Skylight
struct QBDSkylight {
    std::string id;
    std::string surfaceId;      // Which roof surface it's on
    vec3 position;              // Center position in mm
    f32 width = 600.0f;         // mm
    f32 height = 900.0f;        // mm
};

// Complete roof structure
struct QBDRoof {
    std::string id;
    RoofType type = RoofType::Gable;
    f32 pitch = 6.0f;           // Rise per 12" run (e.g., 6:12)
    f32 overhang = 600.0f;      // Eave overhang in mm
    f32 ridgeHeight = 0.0f;     // Height of ridge above wall top in mm
    std::vector<QBDRoofSurface> surfaces;
    std::vector<QBDRoofRidge> ridges;
    std::vector<QBDDormer> dormers;
    std::vector<QBDSkylight> skylights;
    std::string material;       // Optional material override (e.g., "polyhaven/roof_slates_02")
};

// Room bounds
struct RoomBounds {
    f32 x, y;
    f32 width, height;

    f32 area() const { return width * height; }
    vec2 center() const { return {x + width/2, y + height/2}; }
};

// Room from QBD output
struct QBDRoom {
    std::string id;
    std::string name;
    std::string roomType;       // kitchen, bedroom, etc.
    RoomBounds bounds;
    f32 area;
    vec2 center;
    RoomZone zone = RoomZone::Public;
};

// QBD answers (original user input)
struct QBDAnswers {
    std::string buildingType;   // residential, commercial, mixed
    std::string residenceType;  // single_family, apartment, etc.
    int bedrooms = 2;
    float bathrooms = 1.0f;
    int sqft = 1200;
    std::string garage;         // none, 1car, 2car, 3car
    std::vector<std::string> specialRooms;
    std::string style;          // modern, traditional, etc.
};

// Summary statistics
struct QBDSummary {
    int totalWalls = 0;
    int exteriorWalls = 0;
    int interiorWalls = 0;
    int wetWalls = 0;
    int doors = 0;
    int windows = 0;
    int floors = 0;
    int roomsPlaced = 0;
    int roomsRequested = 0;
};

// ============================================================================
// QBD LAYOUT (complete output from Python)
// ============================================================================

struct QBDLayout {
    bool success = false;
    f32 width = 0.0f;
    f32 depth = 0.0f;
    f32 sqft = 0.0f;
    bool isComplete = false;
    f32 score = 0.0f;

    std::vector<QBDWall> walls;
    std::vector<QBDFloor> floors;
    std::vector<QBDDoor> doors;
    std::vector<QBDWindow> windows;
    std::vector<QBDRoof> roofs;
    std::unordered_map<std::string, QBDRoom> rooms;
    std::vector<std::string> unplacedRooms;
    std::vector<WallType> wallTypes;

    // Terrain mesh (from elevation API)
    TerrainMesh terrain;

    // Building placement (center position on terrain in mm, from SW corner of property)
    vec3 buildingCenter = vec3(0.0f);  // x, 0, z position of building center
    f32 buildingRotation = 0.0f;       // Rotation in radians (0 = north-aligned)

    QBDSummary summary;
    QBDAnswers answers;

    // Helper methods
    bool hasRoom(const std::string& roomId) const {
        return rooms.find(roomId) != rooms.end();
    }

    std::vector<QBDWall> getWallsByCategory(WallCategory cat) const {
        std::vector<QBDWall> result;
        for (const auto& w : walls) {
            if (w.category == cat) result.push_back(w);
        }
        return result;
    }

    std::vector<QBDRoom> getRoomsByZone(RoomZone zone) const {
        std::vector<QBDRoom> result;
        for (const auto& [id, room] : rooms) {
            if (room.zone == zone) result.push_back(room);
        }
        return result;
    }
};

// ============================================================================
// VALIDATION RESULT
// ============================================================================

struct QBDValidationResult {
    bool overallPass = false;
    std::vector<obc::ComplianceReport> wallReports;
    std::vector<obc::ComplianceReport> roomReports;

    // Thermal summary
    f32 totalExteriorWallArea = 0.0f;
    f32 averageRValue = 0.0f;
    bool thermalCompliance = false;

    // Structural summary
    int wallsChecked = 0;
    int wallsPassed = 0;
    int wallsFailed = 0;

    std::string getSummary() const;
};

// ============================================================================
// DOCUMENTATION OUTPUT
// ============================================================================

struct QBDDocumentation {
    // Floor plan
    slicer::SliceResult floorPlan;
    std::string floorPlanSVG;
    std::string floorPlanDXF;

    // Building sections
    std::vector<slicer::SliceResult> sections;

    // Wall details
    std::vector<slicer::WallSectionDetail> wallDetails;

    // Metadata
    std::string projectName;
    std::string generatedDate;
};

// ============================================================================
// QBD INTERFACE CLASS
// ============================================================================

class QBDInterface {
public:
    QBDInterface();
    ~QBDInterface();

    // ========================================================================
    // LOADING
    // ========================================================================

    // Load QBD output from JSON string
    std::optional<QBDLayout> loadFromJSON(const std::string& jsonString);

    // Load QBD output from file
    std::optional<QBDLayout> loadFromFile(const std::string& filepath);

    // ========================================================================
    // CONVERSION TO KERNEL TYPES
    // ========================================================================

    // Convert QBD layout to kernel Building
    Building toBuilding(const QBDLayout& layout);

    // Convert QBD walls to parametric walls with wall types
    std::vector<ParametricWall> toParametricWalls(const QBDLayout& layout);

    // Get appropriate wall type for category
    WallType getWallTypeForCategory(WallCategory category);

    // ========================================================================
    // VALIDATION (uses OBC engine)
    // ========================================================================

    // Validate entire layout against OBC
    QBDValidationResult validateLayout(const QBDLayout& layout,
                                        const std::string& climateZone = "Zone 6");

    // Validate a single wall
    obc::ComplianceReport validateWall(const QBDWall& wall, f32 wallHeight = 9.0f);

    // ========================================================================
    // DOCUMENTATION (uses Slicer)
    // ========================================================================

    // Generate complete documentation package
    QBDDocumentation generateDocumentation(const QBDLayout& layout,
                                            const std::string& projectName = "QBD Project");

    // Generate floor plan only
    slicer::SliceResult generateFloorPlan(const QBDLayout& layout, f32 cutHeight = 4.0f);

    // Generate wall section details
    std::vector<slicer::WallSectionDetail> generateWallDetails(const QBDLayout& layout);

    // Export documentation to files
    bool exportDocumentation(const QBDDocumentation& docs,
                             const std::string& outputDir);

    // ========================================================================
    // ASSEMBLY ASSIGNMENT
    // ========================================================================

    // Assign wall assemblies based on category and requirements
    void assignWallAssemblies(QBDLayout& layout);

    // Set default wall types
    void setExteriorWallType(const WallType& type);
    void setInteriorWallType(const WallType& type);
    void setWetWallType(const WallType& type);

    // ========================================================================
    // CONFIGURATION
    // ========================================================================

    // Set OBC library path for validation
    void setOBCLibraryPath(const std::string& path);

    // Set climate zone for thermal calculations
    void setClimateZone(const std::string& zone);

    // ========================================================================
    // ARCHGEOMETRY INTEGRATION (shared geometry library)
    // ========================================================================

    // Get archgeometry QueryAPI for unified geometry queries
    // Returns nullptr if archgeometry parsing failed or was not used
    archgeometry::QueryAPI* getArchGeometryQuery();

    // Parse JSON using archgeometry library (alternative to loadFromJSON)
    // Stores result internally for later QueryAPI access
    bool parseWithArchGeometry(const std::string& jsonString);

    // Check if archgeometry parsing is available
    bool hasArchGeometryDoc() const { return m_archDoc != nullptr; }

private:
    std::string m_obcLibraryPath;
    std::string m_climateZone = "Zone 6";

    // Default wall types
    WallType m_exteriorWallType;
    WallType m_interiorWallType;
    WallType m_wetWallType;

    bool m_initialized = false;

    // ArchGeometry integration (shared library for unified schema interpretation)
    std::unique_ptr<archgeometry::SchemaDocument> m_archDoc;
    std::unique_ptr<archgeometry::QueryAPI> m_archQuery;

    // Initialize default wall types
    void initDefaultWallTypes();

    // Parsing helpers
    WallCategory parseWallCategory(const std::string& cat);
    DoorType parseDoorType(const std::string& type);
    DoorSwing parseDoorSwing(const std::string& swing);
    WindowType parseWindowType(const std::string& type);
    RoomZone inferRoomZone(const std::string& roomType);
};

// ============================================================================
// GLOBAL INTERFACE
// ============================================================================

QBDInterface& getQBDInterface();

} // namespace qbd
} // namespace arch
