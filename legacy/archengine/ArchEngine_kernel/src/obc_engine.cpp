#include "obc_engine.hpp"
#include <fstream>
#include <sstream>
#include <filesystem>
#include <iostream>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace arch {
namespace obc {

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

f32 OBCEngine::parseSpanString(const std::string& span) {
    // Parse "10-6" format (feet-inches) to decimal feet
    size_t dashPos = span.find('-');
    if (dashPos == std::string::npos) {
        // Just feet
        return std::stof(span);
    }

    int feet = std::stoi(span.substr(0, dashPos));
    int inches = std::stoi(span.substr(dashPos + 1));
    return static_cast<f32>(feet) + static_cast<f32>(inches) / 12.0f;
}

std::string OBCEngine::makeTableKey(const std::string& species, const std::string& grade, f32 load) const {
    std::stringstream ss;
    ss << species << "_" << grade << "_" << static_cast<int>(load);
    return ss.str();
}

// ============================================================================
// CONSTRUCTOR / DESTRUCTOR
// ============================================================================

OBCEngine::OBCEngine() {
    loadThermalRequirements();
}

OBCEngine::~OBCEngine() = default;

// ============================================================================
// INITIALIZATION
// ============================================================================

bool OBCEngine::initialize(const std::string& obcLibraryPath) {
    m_libraryPath = obcLibraryPath;
    std::filesystem::path basePath(obcLibraryPath);
    std::filesystem::path tablesPath = basePath / "tables";

    if (!std::filesystem::exists(tablesPath)) {
        std::cerr << "OBCEngine: Tables directory not found: " << tablesPath << std::endl;
        return false;
    }

    bool success = true;

    // Load each table file
    auto joistPath = tablesPath / "obc_9.23_joists.json";
    if (std::filesystem::exists(joistPath)) {
        success &= loadJoistTables(joistPath.string());
    }

    auto studPath = tablesPath / "obc_9.23_studs.json";
    if (std::filesystem::exists(studPath)) {
        success &= loadStudTables(studPath.string());
    }

    auto headerPath = tablesPath / "obc_9.23_headers.json";
    if (std::filesystem::exists(headerPath)) {
        success &= loadHeaderTables(headerPath.string());
    }

    auto rafterPath = tablesPath / "obc_9.23_rafters.json";
    if (std::filesystem::exists(rafterPath)) {
        success &= loadRafterTables(rafterPath.string());
    }

    m_initialized = success;

    if (m_initialized) {
        std::cout << "OBCEngine: Initialized with "
                  << m_joistTables.size() << " joist tables, "
                  << m_studTables.size() << " stud tables, "
                  << m_headerTable.size() << " header entries" << std::endl;
    }

    return m_initialized;
}

// ============================================================================
// TABLE LOADING
// ============================================================================

bool OBCEngine::loadJoistTables(const std::string& filepath) {
    try {
        std::ifstream file(filepath);
        if (!file.is_open()) return false;

        json j = json::parse(file);

        for (auto& [tableKey, tableData] : j["tables"].items()) {
            SpanTable table;
            table.species = tableData["species"];
            table.grade = tableData["grade"];
            table.liveLoadPsf = tableData["live_load_psf"];

            for (const auto& entry : tableData["entries"]) {
                SpanEntry e;
                e.size = entry["size"];
                e.depthInches = entry["depth_in"];
                e.span12 = parseSpanString(entry["spacing_12_span"]);
                e.span16 = parseSpanString(entry["spacing_16_span"]);
                e.span24 = parseSpanString(entry["spacing_24_span"]);
                table.entries.push_back(e);
            }

            std::string key = makeTableKey(table.species, table.grade, table.liveLoadPsf);
            m_joistTables[key] = table;
        }

        return true;
    } catch (const std::exception& e) {
        std::cerr << "OBCEngine: Error loading joist tables: " << e.what() << std::endl;
        return false;
    }
}

bool OBCEngine::loadStudTables(const std::string& filepath) {
    try {
        std::ifstream file(filepath);
        if (!file.is_open()) return false;

        json j = json::parse(file);

        for (auto& [tableKey, tableData] : j["tables"].items()) {
            StudTable table;
            table.category = tableKey;

            for (const auto& entry : tableData["entries"]) {
                StudEntry e;
                e.size = entry["size"];
                e.depthInches = entry["depth_in"];

                // Handle optional spacing fields
                e.maxHeight12 = entry.contains("spacing_12_max_height_ft") ?
                    static_cast<f32>(entry["spacing_12_max_height_ft"]) : 0.0f;
                e.maxHeight16 = entry.contains("spacing_16_max_height_ft") ?
                    static_cast<f32>(entry["spacing_16_max_height_ft"]) : 0.0f;
                e.maxHeight24 = entry.contains("spacing_24_max_height_ft") ?
                    static_cast<f32>(entry["spacing_24_max_height_ft"]) : 0.0f;

                e.maxStoriesSupported = entry.contains("max_stories_supported") ?
                    static_cast<int>(entry["max_stories_supported"]) : 1;
                e.notes = entry.contains("notes") ? entry["notes"] : "";

                table.entries.push_back(e);
            }

            m_studTables[tableKey] = table;
        }

        return true;
    } catch (const std::exception& e) {
        std::cerr << "OBCEngine: Error loading stud tables: " << e.what() << std::endl;
        return false;
    }
}

bool OBCEngine::loadHeaderTables(const std::string& filepath) {
    try {
        std::ifstream file(filepath);
        if (!file.is_open()) return false;

        json j = json::parse(file);

        // Load roof_ceiling_only table (1 story support)
        if (j.contains("tables") && j["tables"].contains("roof_ceiling_only")) {
            for (const auto& entry : j["tables"]["roof_ceiling_only"]["entries"]) {
                HeaderEntry e;
                e.size = "2-" + static_cast<std::string>(entry["size"]);  // Double ply default
                e.depthInches = entry["depth_in"];
                e.maxSpan1Story = entry["double_ply_span_ft"];  // 1 story = roof only
                e.supportType = "roof_ceiling_only";

                // Get 2 story span from one_floor_roof_ceiling table if exists
                e.maxSpan2Story = 0.0f;
                if (j["tables"].contains("one_floor_roof_ceiling")) {
                    for (const auto& e2 : j["tables"]["one_floor_roof_ceiling"]["entries"]) {
                        if (e2["size"] == entry["size"]) {
                            e.maxSpan2Story = e2["double_ply_span_ft"];
                            break;
                        }
                    }
                }

                m_headerTable.push_back(e);
            }
        }

        return true;
    } catch (const std::exception& e) {
        std::cerr << "OBCEngine: Error loading header tables: " << e.what() << std::endl;
        return false;
    }
}

bool OBCEngine::loadRafterTables(const std::string& filepath) {
    try {
        std::ifstream file(filepath);
        if (!file.is_open()) return false;

        json j = json::parse(file);

        for (auto& [tableKey, tableData] : j["tables"].items()) {
            SpanTable table;
            table.species = tableData["species"];
            table.grade = tableData["grade"];
            table.liveLoadPsf = tableData.contains("snow_load_psf") ?
                static_cast<f32>(tableData["snow_load_psf"]) : 40.0f;

            for (const auto& entry : tableData["entries"]) {
                SpanEntry e;
                e.size = entry["size"];
                e.depthInches = entry["depth_in"];
                e.span12 = parseSpanString(entry["spacing_12_span"]);
                e.span16 = parseSpanString(entry["spacing_16_span"]);
                e.span24 = parseSpanString(entry["spacing_24_span"]);
                table.entries.push_back(e);
            }

            std::string key = makeTableKey(table.species, table.grade, table.liveLoadPsf);
            m_rafterTables[key] = table;
        }

        return true;
    } catch (const std::exception& e) {
        std::cerr << "OBCEngine: Error loading rafter tables: " << e.what() << std::endl;
        return false;
    }
}

bool OBCEngine::loadThermalRequirements() {
    // OBC SB-12 thermal requirements by climate zone
    // Format: m_thermalRequirements[zone][assembly_type] = R-value

    // Zone 4 (Southern Ontario - milder)
    m_thermalRequirements["Zone 4"]["wall"] = 17.0f;
    m_thermalRequirements["Zone 4"]["ceiling"] = 38.0f;
    m_thermalRequirements["Zone 4"]["floor"] = 28.0f;
    m_thermalRequirements["Zone 4"]["basement_wall"] = 17.0f;

    // Zone 5 (Central Ontario)
    m_thermalRequirements["Zone 5"]["wall"] = 20.0f;
    m_thermalRequirements["Zone 5"]["ceiling"] = 44.0f;
    m_thermalRequirements["Zone 5"]["floor"] = 28.0f;
    m_thermalRequirements["Zone 5"]["basement_wall"] = 20.0f;

    // Zone 6 (Northern Ontario - coldest, most common)
    m_thermalRequirements["Zone 6"]["wall"] = 24.0f;
    m_thermalRequirements["Zone 6"]["ceiling"] = 50.0f;
    m_thermalRequirements["Zone 6"]["floor"] = 31.0f;
    m_thermalRequirements["Zone 6"]["basement_wall"] = 20.0f;

    // Zone 7A (Far North)
    m_thermalRequirements["Zone 7A"]["wall"] = 27.0f;
    m_thermalRequirements["Zone 7A"]["ceiling"] = 60.0f;
    m_thermalRequirements["Zone 7A"]["floor"] = 35.0f;
    m_thermalRequirements["Zone 7A"]["basement_wall"] = 24.0f;

    return true;
}

// ============================================================================
// SPAN LOOKUPS
// ============================================================================

std::optional<f32> OBCEngine::getJoistMaxSpan(
    const std::string& species,
    const std::string& grade,
    const std::string& size,
    int spacingInches,
    f32 liveLoadPsf
) const {
    std::string key = makeTableKey(species, grade, liveLoadPsf);

    auto it = m_joistTables.find(key);
    if (it == m_joistTables.end()) return std::nullopt;

    auto entry = it->second.findBySize(size);
    if (!entry.has_value()) return std::nullopt;

    return entry->getSpanForSpacing(spacingInches);
}

std::optional<std::string> OBCEngine::getRequiredJoistSize(
    const std::string& species,
    const std::string& grade,
    f32 spanFt,
    int spacingInches,
    f32 liveLoadPsf
) const {
    std::string key = makeTableKey(species, grade, liveLoadPsf);

    auto it = m_joistTables.find(key);
    if (it == m_joistTables.end()) return std::nullopt;

    auto entry = it->second.findForSpan(spanFt, spacingInches);
    if (!entry.has_value()) return std::nullopt;

    return entry->size;
}

std::optional<f32> OBCEngine::getStudMaxHeight(
    const std::string& size,
    int spacingInches,
    bool isLoadBearing,
    int storiesSupported
) const {
    std::string tableKey = isLoadBearing ? "load_bearing_exterior" : "non_load_bearing";

    auto it = m_studTables.find(tableKey);
    if (it == m_studTables.end()) return std::nullopt;

    auto entry = it->second.findBySize(size);
    if (!entry.has_value()) return std::nullopt;

    if (entry->maxStoriesSupported < storiesSupported) return std::nullopt;

    return entry->getMaxHeightForSpacing(spacingInches);
}

std::optional<std::string> OBCEngine::getRequiredStudSize(
    f32 heightFt,
    int spacingInches,
    bool isLoadBearing,
    int storiesSupported
) const {
    std::string tableKey = isLoadBearing ? "load_bearing_exterior" : "non_load_bearing";

    auto it = m_studTables.find(tableKey);
    if (it == m_studTables.end()) return std::nullopt;

    auto entry = it->second.findForHeight(heightFt, spacingInches, storiesSupported);
    if (!entry.has_value()) return std::nullopt;

    return entry->size;
}

std::optional<f32> OBCEngine::getHeaderMaxSpan(
    const std::string& size,
    int storiesSupported
) const {
    for (const auto& entry : m_headerTable) {
        if (entry.size == size) {
            return (storiesSupported <= 1) ? entry.maxSpan1Story : entry.maxSpan2Story;
        }
    }
    return std::nullopt;
}

std::optional<std::string> OBCEngine::getRequiredHeaderSize(
    f32 openingWidthFt,
    int storiesSupported
) const {
    for (const auto& entry : m_headerTable) {
        f32 maxSpan = (storiesSupported <= 1) ? entry.maxSpan1Story : entry.maxSpan2Story;
        if (maxSpan >= openingWidthFt) {
            return entry.size;
        }
    }
    return std::nullopt;
}

std::optional<f32> OBCEngine::getRafterMaxSpan(
    const std::string& species,
    const std::string& grade,
    const std::string& size,
    int spacingInches,
    f32 snowLoadPsf
) const {
    std::string key = makeTableKey(species, grade, snowLoadPsf);

    auto it = m_rafterTables.find(key);
    if (it == m_rafterTables.end()) return std::nullopt;

    auto entry = it->second.findBySize(size);
    if (!entry.has_value()) return std::nullopt;

    return entry->getSpanForSpacing(spacingInches);
}

// ============================================================================
// COMPLIANCE VALIDATION
// ============================================================================

ComplianceReport OBCEngine::validateJoist(
    const std::string& species,
    const std::string& grade,
    const std::string& size,
    f32 spanFt,
    int spacingInches,
    f32 liveLoadPsf
) const {
    ComplianceReport report;
    report.elementType = "joist";
    report.elementId = size + " @ " + std::to_string(spacingInches) + "\" o.c.";

    // Check span
    auto maxSpan = getJoistMaxSpan(species, grade, size, spacingInches, liveLoadPsf);

    ComplianceCheck spanCheck;
    spanCheck.ruleName = "Maximum Joist Span";
    spanCheck.codeSection = "OBC 9.23.9.2";

    if (!maxSpan.has_value()) {
        spanCheck.status = ComplianceStatus::DataMissing;
        spanCheck.message = "No span data found for " + species + " " + grade + " " + size;
        spanCheck.requirement = "N/A";
        spanCheck.actual = std::to_string(spanFt) + " ft";
    } else if (spanFt <= maxSpan.value()) {
        spanCheck.status = ComplianceStatus::Pass;
        spanCheck.requirement = "Max span: " + std::to_string(maxSpan.value()) + " ft";
        spanCheck.actual = std::to_string(spanFt) + " ft";
        spanCheck.message = "Joist span is within allowable limits";
    } else {
        spanCheck.status = ComplianceStatus::Fail;
        spanCheck.requirement = "Max span: " + std::to_string(maxSpan.value()) + " ft";
        spanCheck.actual = std::to_string(spanFt) + " ft";
        spanCheck.message = "Joist span exceeds maximum by " +
            std::to_string(spanFt - maxSpan.value()) + " ft. Consider larger size or closer spacing.";

        // Suggest fix
        auto requiredSize = getRequiredJoistSize(species, grade, spanFt, spacingInches, liveLoadPsf);
        if (requiredSize.has_value()) {
            spanCheck.message += " Recommended: " + requiredSize.value();
        }
    }

    report.checks.push_back(spanCheck);

    // Determine overall status
    report.overallStatus = ComplianceStatus::Pass;
    for (const auto& check : report.checks) {
        if (check.status == ComplianceStatus::Fail) {
            report.overallStatus = ComplianceStatus::Fail;
            break;
        } else if (check.status == ComplianceStatus::Warning &&
                   report.overallStatus != ComplianceStatus::Fail) {
            report.overallStatus = ComplianceStatus::Warning;
        }
    }

    return report;
}

ComplianceReport OBCEngine::validateStuds(
    const std::string& size,
    f32 heightFt,
    int spacingInches,
    bool isLoadBearing,
    int storiesSupported
) const {
    ComplianceReport report;
    report.elementType = "stud";
    report.elementId = size + (isLoadBearing ? " (load-bearing)" : " (non-load-bearing)");

    // Check height
    auto maxHeight = getStudMaxHeight(size, spacingInches, isLoadBearing, storiesSupported);

    ComplianceCheck heightCheck;
    heightCheck.ruleName = "Maximum Wall Height";
    heightCheck.codeSection = "OBC 9.23.10.1";

    if (!maxHeight.has_value()) {
        heightCheck.status = ComplianceStatus::DataMissing;
        heightCheck.message = "No height data found for " + size + " studs";
        heightCheck.requirement = "N/A";
        heightCheck.actual = std::to_string(heightFt) + " ft";
    } else if (heightFt <= maxHeight.value()) {
        heightCheck.status = ComplianceStatus::Pass;
        heightCheck.requirement = "Max height: " + std::to_string(maxHeight.value()) + " ft";
        heightCheck.actual = std::to_string(heightFt) + " ft";
        heightCheck.message = "Wall height is within allowable limits";
    } else {
        heightCheck.status = ComplianceStatus::Fail;
        heightCheck.requirement = "Max height: " + std::to_string(maxHeight.value()) + " ft";
        heightCheck.actual = std::to_string(heightFt) + " ft";
        heightCheck.message = "Wall height exceeds maximum. ";

        auto requiredSize = getRequiredStudSize(heightFt, spacingInches, isLoadBearing, storiesSupported);
        if (requiredSize.has_value()) {
            heightCheck.message += "Recommended: " + requiredSize.value();
        }
    }

    report.checks.push_back(heightCheck);

    // Check stories supported
    ComplianceCheck storiesCheck;
    storiesCheck.ruleName = "Stories Supported";
    storiesCheck.codeSection = "OBC 9.23.10.1";
    storiesCheck.requirement = std::to_string(storiesSupported) + " stor(ies)";
    storiesCheck.actual = size;

    std::string tableKey = isLoadBearing ? "load_bearing_exterior" : "non_load_bearing";
    auto it = m_studTables.find(tableKey);
    if (it != m_studTables.end()) {
        auto entry = it->second.findBySize(size);
        if (entry.has_value() && entry->maxStoriesSupported >= storiesSupported) {
            storiesCheck.status = ComplianceStatus::Pass;
            storiesCheck.message = size + " can support " + std::to_string(storiesSupported) + " stor(ies)";
        } else {
            storiesCheck.status = ComplianceStatus::Fail;
            storiesCheck.message = size + " cannot support " + std::to_string(storiesSupported) + " stor(ies)";
        }
    } else {
        storiesCheck.status = ComplianceStatus::DataMissing;
        storiesCheck.message = "No stud data available";
    }

    report.checks.push_back(storiesCheck);

    // Determine overall status
    report.overallStatus = ComplianceStatus::Pass;
    for (const auto& check : report.checks) {
        if (check.status == ComplianceStatus::Fail) {
            report.overallStatus = ComplianceStatus::Fail;
            break;
        }
    }

    return report;
}

ComplianceReport OBCEngine::validateHeader(
    const std::string& size,
    f32 openingWidthFt,
    int storiesSupported
) const {
    ComplianceReport report;
    report.elementType = "header";
    report.elementId = size;

    auto maxSpan = getHeaderMaxSpan(size, storiesSupported);

    ComplianceCheck spanCheck;
    spanCheck.ruleName = "Maximum Header Span";
    spanCheck.codeSection = "OBC 9.23.12.1";

    if (!maxSpan.has_value()) {
        spanCheck.status = ComplianceStatus::DataMissing;
        spanCheck.message = "No span data found for " + size + " header";
    } else if (openingWidthFt <= maxSpan.value()) {
        spanCheck.status = ComplianceStatus::Pass;
        spanCheck.requirement = "Max span: " + std::to_string(maxSpan.value()) + " ft";
        spanCheck.actual = std::to_string(openingWidthFt) + " ft";
        spanCheck.message = "Header span is within allowable limits";
    } else {
        spanCheck.status = ComplianceStatus::Fail;
        spanCheck.requirement = "Max span: " + std::to_string(maxSpan.value()) + " ft";
        spanCheck.actual = std::to_string(openingWidthFt) + " ft";

        auto requiredSize = getRequiredHeaderSize(openingWidthFt, storiesSupported);
        if (requiredSize.has_value()) {
            spanCheck.message = "Header undersized. Recommended: " + requiredSize.value();
        } else {
            spanCheck.message = "No standard header size available for this span. Engineering required.";
        }
    }

    report.checks.push_back(spanCheck);
    report.overallStatus = spanCheck.status;

    return report;
}

// ============================================================================
// THERMAL COMPLIANCE
// ============================================================================

f32 OBCEngine::getMinimumRValue(const std::string& climateZone, const std::string& assemblyType) const {
    auto zoneIt = m_thermalRequirements.find(climateZone);
    if (zoneIt == m_thermalRequirements.end()) {
        // Default to Zone 6 (most common in Ontario)
        zoneIt = m_thermalRequirements.find("Zone 6");
        if (zoneIt == m_thermalRequirements.end()) return 0.0f;
    }

    auto typeIt = zoneIt->second.find(assemblyType);
    if (typeIt == zoneIt->second.end()) return 0.0f;

    return typeIt->second;
}

ComplianceCheck OBCEngine::checkThermalCompliance(
    f32 assemblyRValue,
    const std::string& climateZone,
    const std::string& assemblyType
) const {
    ComplianceCheck check;
    check.ruleName = "Thermal Performance (R-value)";
    check.codeSection = "OBC SB-12";

    f32 requiredR = getMinimumRValue(climateZone, assemblyType);

    check.requirement = "R-" + std::to_string(static_cast<int>(requiredR));
    check.actual = "R-" + std::to_string(static_cast<int>(assemblyRValue));

    if (assemblyRValue >= requiredR) {
        check.status = ComplianceStatus::Pass;
        check.message = "Assembly meets thermal requirements for " + climateZone;
    } else if (assemblyRValue >= requiredR * 0.9f) {
        check.status = ComplianceStatus::Warning;
        check.message = "Assembly is marginally below thermal requirements. Consider additional insulation.";
    } else {
        check.status = ComplianceStatus::Fail;
        f32 deficit = requiredR - assemblyRValue;
        check.message = "Assembly is R-" + std::to_string(static_cast<int>(deficit)) +
                       " below minimum. Add insulation.";
    }

    return check;
}

ComplianceReport OBCEngine::validateWallAssembly(
    const WallType& wallType,
    f32 wallHeightFt,
    bool isExterior,
    const std::string& climateZone
) const {
    ComplianceReport report;
    report.elementType = "wall_assembly";
    report.elementId = wallType.name;

    // Check thermal compliance if exterior wall
    if (isExterior) {
        f32 totalR = wallType.getTotalRValue();
        auto thermalCheck = checkThermalCompliance(totalR, climateZone, "wall");
        report.checks.push_back(thermalCheck);
    }

    // Check structural layer (studs)
    for (const auto& layer : wallType.layers) {
        if (layer.function == LayerFunction::Structure) {
            // Extract stud size from layer name (e.g., "2x6 Stud @ 16\" o.c.")
            std::string layerName = layer.name;

            // Default assumptions if not specified
            std::string studSize = "2x6";
            int spacing = 16;

            if (layerName.find("2x4") != std::string::npos) studSize = "2x4";
            else if (layerName.find("2x6") != std::string::npos) studSize = "2x6";
            else if (layerName.find("2x8") != std::string::npos) studSize = "2x8";

            if (layerName.find("24\"") != std::string::npos) spacing = 24;
            else if (layerName.find("12\"") != std::string::npos) spacing = 12;

            bool isLoadBearing = wallType.intent.structuralRole == "load_bearing" ||
                                 wallType.intent.structuralRole == "shear";

            auto studReport = validateStuds(studSize, wallHeightFt, spacing, isLoadBearing, 1);
            for (const auto& check : studReport.checks) {
                report.checks.push_back(check);
            }
            break;
        }
    }

    // Check existing constraints
    for (const auto& constraint : wallType.constraints) {
        ComplianceCheck check;
        check.ruleName = constraint.name;
        check.codeSection = constraint.codeSection;
        check.requirement = constraint.value;
        check.status = constraint.isMet ? ComplianceStatus::Pass : ComplianceStatus::Fail;
        check.message = constraint.description;
        report.checks.push_back(check);
    }

    // Determine overall status
    report.overallStatus = ComplianceStatus::Pass;
    for (const auto& check : report.checks) {
        if (check.status == ComplianceStatus::Fail) {
            report.overallStatus = ComplianceStatus::Fail;
            break;
        } else if (check.status == ComplianceStatus::Warning &&
                   report.overallStatus != ComplianceStatus::Fail) {
            report.overallStatus = ComplianceStatus::Warning;
        }
    }

    return report;
}

std::vector<ComplianceReport> OBCEngine::validateBuilding(const Building& building) const {
    std::vector<ComplianceReport> reports;

    // Validate wall assemblies
    for (size_t i = 0; i < building.wallTypes.size(); ++i) {
        auto report = validateWallAssembly(building.wallTypes[i], 9.0f, true, "Zone 6");
        reports.push_back(report);
    }

    // Validate structural elements
    for (const auto& element : building.elements) {
        if (element.type == ElementType::Floor) {
            // Assume joist properties
            auto report = validateJoist("SPF", "No.2", "2x10",
                glm::length(element.end - element.start), 16, 40.0f);
            reports.push_back(report);
        }
    }

    return reports;
}

// ============================================================================
// GLOBAL INSTANCE
// ============================================================================

OBCEngine& getOBCEngine() {
    static OBCEngine instance;
    return instance;
}

} // namespace obc
} // namespace arch
