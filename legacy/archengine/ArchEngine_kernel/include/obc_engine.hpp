#pragma once

#include "types.hpp"
#include <string>
#include <vector>
#include <unordered_map>
#include <optional>

namespace arch {
namespace obc {

// ============================================================================
// OBC CODE RESULT TYPES
// ============================================================================

// Result status for compliance checks
enum class ComplianceStatus : u32 {
    Pass,           // Meets code requirements
    Fail,           // Does not meet code requirements
    Warning,        // Marginal or needs review
    NotApplicable,  // Rule doesn't apply to this element
    DataMissing     // Insufficient data to evaluate
};

// Single compliance check result
struct ComplianceCheck {
    std::string ruleName;           // e.g., "Maximum Joist Span"
    std::string codeSection;        // e.g., "OBC 9.23.9.2"
    ComplianceStatus status;
    std::string requirement;        // What the code requires
    std::string actual;             // What the design has
    std::string message;            // Human-readable explanation
};

// Full compliance report for an assembly or element
struct ComplianceReport {
    std::string elementId;
    std::string elementType;        // "joist", "stud", "header", "rafter", "wall_assembly"
    std::vector<ComplianceCheck> checks;
    ComplianceStatus overallStatus;

    bool passes() const { return overallStatus == ComplianceStatus::Pass; }

    // Count by status
    int countByStatus(ComplianceStatus status) const {
        int count = 0;
        for (const auto& c : checks) {
            if (c.status == status) count++;
        }
        return count;
    }
};

// ============================================================================
// SPAN TABLE LOOKUP TYPES
// ============================================================================

// Joist/rafter span entry
struct SpanEntry {
    std::string size;           // "2x6", "2x8", etc.
    f32 depthInches;
    f32 span12;                 // Max span at 12" o.c. (in feet)
    f32 span16;                 // Max span at 16" o.c.
    f32 span24;                 // Max span at 24" o.c.

    f32 getSpanForSpacing(int spacingInches) const {
        if (spacingInches <= 12) return span12;
        if (spacingInches <= 16) return span16;
        return span24;
    }
};

// Stud sizing entry
struct StudEntry {
    std::string size;           // "2x4", "2x6", etc.
    f32 depthInches;
    f32 maxHeight12;            // Max height at 12" o.c. (in feet)
    f32 maxHeight16;            // Max height at 16" o.c.
    f32 maxHeight24;            // Max height at 24" o.c.
    int maxStoriesSupported;
    std::string notes;

    f32 getMaxHeightForSpacing(int spacingInches) const {
        if (spacingInches <= 12) return maxHeight12;
        if (spacingInches <= 16) return maxHeight16;
        return maxHeight24;
    }
};

// Header sizing entry
struct HeaderEntry {
    std::string size;           // "2-2x6", "2-2x8", etc.
    f32 depthInches;
    f32 maxSpan1Story;          // Max opening span supporting 1 story
    f32 maxSpan2Story;          // Max opening span supporting 2 stories
    std::string supportType;    // "roof_only", "floor_and_roof", etc.
};

// Rafter entry (similar to joist but with slope considerations)
struct RafterEntry {
    std::string size;
    f32 depthInches;
    f32 span12;
    f32 span16;
    f32 span24;
    f32 slopeMin;               // Minimum roof slope (rise/run)
    f32 slopeMax;               // Maximum roof slope
    f32 snowLoad;               // Design snow load (psf)
};

// ============================================================================
// SPAN TABLE CONTAINERS
// ============================================================================

struct SpanTable {
    std::string species;        // "SPF", "Doug Fir", etc.
    std::string grade;          // "No.1", "No.2", "Select Structural"
    f32 liveLoadPsf;            // Design live load
    std::vector<SpanEntry> entries;

    // Find entry by size
    std::optional<SpanEntry> findBySize(const std::string& size) const {
        for (const auto& e : entries) {
            if (e.size == size) return e;
        }
        return std::nullopt;
    }

    // Find smallest size that works for given span and spacing
    std::optional<SpanEntry> findForSpan(f32 requiredSpanFt, int spacingInches) const {
        for (const auto& e : entries) {
            if (e.getSpanForSpacing(spacingInches) >= requiredSpanFt) {
                return e;
            }
        }
        return std::nullopt;
    }
};

struct StudTable {
    std::string category;       // "load_bearing_exterior", "non_load_bearing"
    std::vector<StudEntry> entries;

    std::optional<StudEntry> findBySize(const std::string& size) const {
        for (const auto& e : entries) {
            if (e.size == size) return e;
        }
        return std::nullopt;
    }

    std::optional<StudEntry> findForHeight(f32 heightFt, int spacingInches, int storiesSupported) const {
        for (const auto& e : entries) {
            if (e.getMaxHeightForSpacing(spacingInches) >= heightFt &&
                e.maxStoriesSupported >= storiesSupported) {
                return e;
            }
        }
        return std::nullopt;
    }
};

// ============================================================================
// OBC ENGINE CLASS
// ============================================================================

class OBCEngine {
public:
    OBCEngine();
    ~OBCEngine();

    // Initialize - load all OBC tables from directory
    bool initialize(const std::string& obcLibraryPath);

    // Check if tables are loaded
    bool isInitialized() const { return m_initialized; }

    // ========================================================================
    // SPAN LOOKUPS
    // ========================================================================

    // Get maximum joist span for given parameters
    std::optional<f32> getJoistMaxSpan(
        const std::string& species,
        const std::string& grade,
        const std::string& size,
        int spacingInches,
        f32 liveLoadPsf = 40.0f
    ) const;

    // Get required joist size for span
    std::optional<std::string> getRequiredJoistSize(
        const std::string& species,
        const std::string& grade,
        f32 spanFt,
        int spacingInches,
        f32 liveLoadPsf = 40.0f
    ) const;

    // Get maximum stud height for given parameters
    std::optional<f32> getStudMaxHeight(
        const std::string& size,
        int spacingInches,
        bool isLoadBearing,
        int storiesSupported = 1
    ) const;

    // Get required stud size for height
    std::optional<std::string> getRequiredStudSize(
        f32 heightFt,
        int spacingInches,
        bool isLoadBearing,
        int storiesSupported = 1
    ) const;

    // Get maximum header span
    std::optional<f32> getHeaderMaxSpan(
        const std::string& size,
        int storiesSupported
    ) const;

    // Get required header size for opening
    std::optional<std::string> getRequiredHeaderSize(
        f32 openingWidthFt,
        int storiesSupported
    ) const;

    // Get maximum rafter span
    std::optional<f32> getRafterMaxSpan(
        const std::string& species,
        const std::string& grade,
        const std::string& size,
        int spacingInches,
        f32 snowLoadPsf = 40.0f
    ) const;

    // ========================================================================
    // COMPLIANCE VALIDATION
    // ========================================================================

    // Validate a floor joist
    ComplianceReport validateJoist(
        const std::string& species,
        const std::string& grade,
        const std::string& size,
        f32 spanFt,
        int spacingInches,
        f32 liveLoadPsf = 40.0f
    ) const;

    // Validate wall studs
    ComplianceReport validateStuds(
        const std::string& size,
        f32 heightFt,
        int spacingInches,
        bool isLoadBearing,
        int storiesSupported = 1
    ) const;

    // Validate a header
    ComplianceReport validateHeader(
        const std::string& size,
        f32 openingWidthFt,
        int storiesSupported
    ) const;

    // Validate a wall assembly (thermal + structural)
    ComplianceReport validateWallAssembly(
        const WallType& wallType,
        f32 wallHeightFt,
        bool isExterior,
        const std::string& climateZone = "Zone 6"
    ) const;

    // Validate entire building
    std::vector<ComplianceReport> validateBuilding(const Building& building) const;

    // ========================================================================
    // THERMAL COMPLIANCE
    // ========================================================================

    // Get minimum R-value for climate zone
    f32 getMinimumRValue(const std::string& climateZone, const std::string& assemblyType) const;

    // Check thermal compliance
    ComplianceCheck checkThermalCompliance(
        f32 assemblyRValue,
        const std::string& climateZone,
        const std::string& assemblyType
    ) const;

private:
    bool m_initialized = false;
    std::string m_libraryPath;

    // Loaded tables
    std::unordered_map<std::string, SpanTable> m_joistTables;
    std::unordered_map<std::string, SpanTable> m_rafterTables;
    std::unordered_map<std::string, StudTable> m_studTables;
    std::vector<HeaderEntry> m_headerTable;

    // Thermal requirements by climate zone
    std::unordered_map<std::string, std::unordered_map<std::string, f32>> m_thermalRequirements;

    // Helper to parse span string like "10-6" to feet
    static f32 parseSpanString(const std::string& span);

    // Load individual table files
    bool loadJoistTables(const std::string& filepath);
    bool loadStudTables(const std::string& filepath);
    bool loadHeaderTables(const std::string& filepath);
    bool loadRafterTables(const std::string& filepath);
    bool loadThermalRequirements();

    // Table key generation
    std::string makeTableKey(const std::string& species, const std::string& grade, f32 load) const;
};

// Global engine instance (optional singleton pattern)
OBCEngine& getOBCEngine();

} // namespace obc
} // namespace arch
