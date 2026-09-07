#include "physics_bridge.hpp"
#include <fstream>
#include <iostream>
#include <cstdlib>
#include <array>

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#else
#include <unistd.h>
#include <sys/wait.h>
#endif

namespace arch {

PhysicsBridge::PhysicsBridge() {
    m_available = initPythonBridge();
}

PhysicsBridge::~PhysicsBridge() = default;

bool PhysicsBridge::initPythonBridge() {
    // Try to find Python and physics module
#ifdef _WIN32
#define NOMINMAX
    // Check common Python locations on Windows
    const char* pythonPaths[] = {
        "python",
        "python3",
        "C:\\Python311\\python.exe",
        "C:\\Python310\\python.exe",
        "C:\\Users\\%USERNAME%\\AppData\\Local\\Programs\\Python\\Python311\\python.exe"
    };
#else
    const char* pythonPaths[] = {
        "python3",
        "python",
        "/usr/bin/python3",
        "/usr/local/bin/python3"
    };
#endif

    for (const auto& path : pythonPaths) {
        std::string cmd = std::string(path) + " --version";
#ifdef _WIN32
#define NOMINMAX
        int result = system(cmd.c_str());
#else
        int result = system((cmd + " > /dev/null 2>&1").c_str());
#endif
        if (result == 0) {
            m_pythonPath = path;
            break;
        }
    }

    if (m_pythonPath.empty()) {
        std::cerr << "Warning: Python not found. Physics analysis will be disabled.\n";
        return false;
    }

    // Look for physics module relative to working directory
    std::vector<std::string> modulePaths = {
        "../../scripts/physics_bridge.py",
        "X:/ARCH/Software/ArchEngine/scripts/physics_bridge.py",
        "./physics"
    };

    for (const auto& modulePath : modulePaths) {
        std::ifstream test(modulePath);
        if (test.good()) {
            m_physicsModulePath = modulePath;
            std::cout << "Physics module found at: " << modulePath << "\n";
            return true;
        }
    }

    std::cerr << "Warning: Physics module not found. Analysis will be disabled.\n";
    return false;
}

BeamAnalysis PhysicsBridge::analyzeBeam(f32 spanFt, f32 widthIn, f32 depthIn,
                                         const std::string& material, f32 uniformLoadPlf) {
    BeamAnalysis result{};

    if (!m_available) {
        result.passes = true;
        result.maxStressPsi = 0;
        result.warnings.push_back("Physics engine not available");
        return result;
    }

    json args;
    args["span_ft"] = spanFt;
    args["width_in"] = widthIn;
    args["depth_in"] = depthIn;
    args["material"] = material;
    args["uniform_load_plf"] = uniformLoadPlf;

    json response = callPythonFunction("analyze_beam", args);

    if (response.contains("error")) {
        result.passes = false;
        result.warnings.push_back(response["error"].get<std::string>());
        return result;
    }

    result.passes = response.value("passes", false);
    result.maxStressPsi = response.value("max_stress_psi", 0.0f);
    result.allowableStressPsi = response.value("allowable_stress_psi", 0.0f);
    result.maxDeflectionIn = response.value("max_deflection_in", 0.0f);
    result.allowableDeflectionIn = response.value("allowable_deflection_in", 0.0f);
    result.utilizationRatio = response.value("utilization_ratio", 0.0f);

    if (response.contains("warnings")) {
        for (const auto& w : response["warnings"]) {
            result.warnings.push_back(w.get<std::string>());
        }
    }

    return result;
}

ColumnAnalysis PhysicsBridge::analyzeColumn(f32 heightFt, f32 widthIn, f32 depthIn,
                                             const std::string& material, f32 axialLoadLbs) {
    ColumnAnalysis result{};

    if (!m_available) {
        result.passes = true;
        result.appliedLoadLbs = axialLoadLbs;
        result.warnings.push_back("Physics engine not available");
        return result;
    }

    json args;
    args["height_ft"] = heightFt;
    args["width_in"] = widthIn;
    args["depth_in"] = depthIn;
    args["material"] = material;
    args["axial_load_lbs"] = axialLoadLbs;

    json response = callPythonFunction("analyze_column", args);

    if (response.contains("error")) {
        result.passes = false;
        result.warnings.push_back(response["error"].get<std::string>());
        return result;
    }

    result.passes = response.value("passes", false);
    result.appliedLoadLbs = response.value("applied_load_lbs", axialLoadLbs);
    result.allowableLoadLbs = response.value("allowable_load_lbs", 0.0f);
    result.slendernessRatio = response.value("slenderness_ratio", 0.0f);
    result.utilizationRatio = response.value("utilization_ratio", 0.0f);
    result.bucklingMode = response.value("buckling_mode", "unknown");

    if (response.contains("warnings")) {
        for (const auto& w : response["warnings"]) {
            result.warnings.push_back(w.get<std::string>());
        }
    }

    return result;
}

FrameAnalysis PhysicsBridge::analyzeFrame(const std::vector<StructuralElement>& elements) {
    FrameAnalysis result{};
    result.allPass = true;
    result.maxBeamUtilization = 0.0f;
    result.maxColumnUtilization = 0.0f;

    if (!m_available) {
        return result;  // Return empty analysis when physics not available
    }

    // Build batch request - all elements in one JSON array
    json elementsJson = json::array();
    for (const auto& element : elements) {
        json e;
        if (element.type == ElementType::Beam) {
            f32 span = glm::length(element.end - element.start);
            e["type"] = "beam";
            e["span_ft"] = span;
            e["width_in"] = element.width * 12.0f;
            e["depth_in"] = element.depth * 12.0f;
            e["material"] = element.material;
            e["uniform_load_plf"] = 100.0f;
        } else if (element.type == ElementType::Column) {
            f32 height = element.end.y - element.start.y;
            e["type"] = "column";
            e["height_ft"] = height;
            e["width_in"] = element.width * 12.0f;
            e["depth_in"] = element.depth * 12.0f;
            e["material"] = element.material;
            e["axial_load_lbs"] = 10000.0f;
        } else {
            continue;
        }
        elementsJson.push_back(e);
    }

    // Call Python once with all elements
    json args;
    args["elements"] = elementsJson;
    json response = callPythonFunction("analyze_frame", args);

    if (response.contains("error")) {
        std::cerr << "Physics analysis error: " << response["error"].get<std::string>() << "\n";
        return result;
    }

    // Parse response
    result.allPass = response.value("all_pass", true);
    result.maxBeamUtilization = response.value("max_beam_utilization", 0.0f);
    result.maxColumnUtilization = response.value("max_column_utilization", 0.0f);

    // Parse beam results
    if (response.contains("beams")) {
        for (const auto& b : response["beams"]) {
            BeamAnalysis beam;
            beam.passes = b.value("passes", true);
            beam.maxStressPsi = b.value("max_stress_psi", 0.0f);
            beam.allowableStressPsi = b.value("allowable_stress_psi", 0.0f);
            beam.maxDeflectionIn = b.value("max_deflection_in", 0.0f);
            beam.allowableDeflectionIn = b.value("allowable_deflection_in", 0.0f);
            beam.utilizationRatio = b.value("utilization_ratio", 0.0f);
            if (b.contains("warnings")) {
                for (const auto& w : b["warnings"]) {
                    beam.warnings.push_back(w.get<std::string>());
                }
            }
            result.beams.push_back(beam);
        }
    }

    // Parse column results
    if (response.contains("columns")) {
        for (const auto& c : response["columns"]) {
            ColumnAnalysis col;
            col.passes = c.value("passes", true);
            col.appliedLoadLbs = c.value("applied_load_lbs", 0.0f);
            col.allowableLoadLbs = c.value("allowable_load_lbs", 0.0f);
            col.slendernessRatio = c.value("slenderness_ratio", 0.0f);
            col.utilizationRatio = c.value("utilization_ratio", 0.0f);
            col.bucklingMode = c.value("buckling_mode", "unknown");
            if (c.contains("warnings")) {
                for (const auto& w : c["warnings"]) {
                    col.warnings.push_back(w.get<std::string>());
                }
            }
            result.columns.push_back(col);
        }
    }

    return result;
}

FrameAnalysis PhysicsBridge::loadFromFile(const std::string& filepath) {
    FrameAnalysis result{};

    std::ifstream file(filepath);
    if (!file.is_open()) {
        std::cerr << "Failed to open analysis file: " << filepath << "\n";
        return result;
    }

    try {
        json data = json::parse(file);
        from_json(data, result);
    } catch (const std::exception& e) {
        std::cerr << "Failed to parse analysis file: " << e.what() << "\n";
    }

    return result;
}

void PhysicsBridge::saveModelToFile(const std::string& filepath,
                                    const std::vector<StructuralElement>& elements) {
    json data;
    data["elements"] = json::array();

    for (const auto& element : elements) {
        json e;
        to_json(e, element);
        data["elements"].push_back(e);
    }

    std::ofstream file(filepath);
    if (file.is_open()) {
        file << data.dump(2);
    } else {
        std::cerr << "Failed to save model to: " << filepath << "\n";
    }
}

bool PhysicsBridge::runPythonAnalysis(const std::string& inputFile, const std::string& outputFile) {
    if (!m_available) return false;

    std::string cmd = m_pythonPath + " -c \"import sys; sys.path.insert(0, '" + m_physicsModulePath +
                      "'); from structural import StructuralAnalyzer; import json; " +
                      "data = json.load(open('" + inputFile + "')); " +
                      "analyzer = StructuralAnalyzer(); " +
                      "# Run analysis and save results\" > " + outputFile;

    int result = system(cmd.c_str());
    return result == 0;
}

json PhysicsBridge::callPythonFunction(const std::string& function, const json& args) {
    if (!m_available) {
        return json{{"error", "Physics engine not available"}};
    }

    // Create temporary files for IPC
    std::string inputFile = "temp_physics_input.json";
    std::string outputFile = "temp_physics_output.json";

    // Write input
    std::ofstream input(inputFile);
    input << args.dump();
    input.close();

    // Call physics bridge script
    std::string cmd = m_pythonPath + " \"" + m_physicsModulePath + "\" " + 
                      function + " " + inputFile + " " + outputFile;
    int result = system(cmd.c_str());

    if (result != 0) {
        // Cleanup
        std::remove(inputFile.c_str());
        std::remove(outputFile.c_str());
        return json{{"error", "Python execution failed"}};
    }

    // Read output
    std::ifstream output(outputFile);
    json response;
    if (output.is_open()) {
        try {
            response = json::parse(output);
        } catch (...) {
            response = json{{"error", "Failed to parse Python output"}};
        }
    } else {
        response = json{{"error", "Failed to read Python output"}};
    }

    // Cleanup
    std::remove(inputFile.c_str());
    std::remove(outputFile.c_str());

    return response;
}

std::vector<StructuralElement> PhysicsBridge::convertToRenderElements(
    const FrameAnalysis& analysis, const std::vector<StructuralElement>& geometry) {

    std::vector<StructuralElement> result = geometry;

    // Apply analysis results to geometry
    size_t beamIdx = 0;
    size_t colIdx = 0;

    for (auto& element : result) {
        if (element.type == ElementType::Beam && beamIdx < analysis.beams.size()) {
            element.stress = analysis.beams[beamIdx].utilizationRatio;
            element.deflection = analysis.beams[beamIdx].maxDeflectionIn / 12.0f;  // Convert to feet
            beamIdx++;
        } else if (element.type == ElementType::Column && colIdx < analysis.columns.size()) {
            element.stress = analysis.columns[colIdx].utilizationRatio;
            colIdx++;
        }
    }

    return result;
}

// JSON serialization
void to_json(json& j, const StructuralElement& e) {
    j = json{
        {"type", static_cast<int>(e.type)},
        {"start", {e.start.x, e.start.y, e.start.z}},
        {"end", {e.end.x, e.end.y, e.end.z}},
        {"width", e.width},
        {"depth", e.depth},
        {"material", e.material},
        {"stress", e.stress},
        {"deflection", e.deflection}
    };
}

void from_json(const json& j, StructuralElement& e) {
    e.type = static_cast<ElementType>(j.value("type", 0));
    if (j.contains("start")) {
        e.start = {j["start"][0], j["start"][1], j["start"][2]};
    }
    if (j.contains("end")) {
        e.end = {j["end"][0], j["end"][1], j["end"][2]};
    }
    e.width = j.value("width", 0.0f);
    e.depth = j.value("depth", 0.0f);
    e.material = j.value("material", "steel");
    e.stress = j.value("stress", 0.0f);
    e.deflection = j.value("deflection", 0.0f);
}

void to_json(json& j, const BeamAnalysis& a) {
    j = json{
        {"passes", a.passes},
        {"max_stress_psi", a.maxStressPsi},
        {"allowable_stress_psi", a.allowableStressPsi},
        {"max_deflection_in", a.maxDeflectionIn},
        {"allowable_deflection_in", a.allowableDeflectionIn},
        {"utilization_ratio", a.utilizationRatio},
        {"warnings", a.warnings}
    };
}

void from_json(const json& j, BeamAnalysis& a) {
    a.passes = j.value("passes", false);
    a.maxStressPsi = j.value("max_stress_psi", 0.0f);
    a.allowableStressPsi = j.value("allowable_stress_psi", 0.0f);
    a.maxDeflectionIn = j.value("max_deflection_in", 0.0f);
    a.allowableDeflectionIn = j.value("allowable_deflection_in", 0.0f);
    a.utilizationRatio = j.value("utilization_ratio", 0.0f);
    if (j.contains("warnings")) {
        for (const auto& w : j["warnings"]) {
            a.warnings.push_back(w.get<std::string>());
        }
    }
}

void to_json(json& j, const ColumnAnalysis& a) {
    j = json{
        {"passes", a.passes},
        {"applied_load_lbs", a.appliedLoadLbs},
        {"allowable_load_lbs", a.allowableLoadLbs},
        {"slenderness_ratio", a.slendernessRatio},
        {"utilization_ratio", a.utilizationRatio},
        {"buckling_mode", a.bucklingMode},
        {"warnings", a.warnings}
    };
}

void from_json(const json& j, ColumnAnalysis& a) {
    a.passes = j.value("passes", false);
    a.appliedLoadLbs = j.value("applied_load_lbs", 0.0f);
    a.allowableLoadLbs = j.value("allowable_load_lbs", 0.0f);
    a.slendernessRatio = j.value("slenderness_ratio", 0.0f);
    a.utilizationRatio = j.value("utilization_ratio", 0.0f);
    a.bucklingMode = j.value("buckling_mode", "unknown");
    if (j.contains("warnings")) {
        for (const auto& w : j["warnings"]) {
            a.warnings.push_back(w.get<std::string>());
        }
    }
}

void to_json(json& j, const FrameAnalysis& a) {
    j = json{
        {"beams", json::array()},
        {"columns", json::array()},
        {"all_pass", a.allPass},
        {"max_beam_utilization", a.maxBeamUtilization},
        {"max_column_utilization", a.maxColumnUtilization}
    };

    for (const auto& beam : a.beams) {
        json b;
        to_json(b, beam);
        j["beams"].push_back(b);
    }

    for (const auto& col : a.columns) {
        json c;
        to_json(c, col);
        j["columns"].push_back(c);
    }
}

void from_json(const json& j, FrameAnalysis& a) {
    a.allPass = j.value("all_pass", false);
    a.maxBeamUtilization = j.value("max_beam_utilization", 0.0f);
    a.maxColumnUtilization = j.value("max_column_utilization", 0.0f);

    if (j.contains("beams")) {
        for (const auto& b : j["beams"]) {
            BeamAnalysis beam;
            from_json(b, beam);
            a.beams.push_back(beam);
        }
    }

    if (j.contains("columns")) {
        for (const auto& c : j["columns"]) {
            ColumnAnalysis col;
            from_json(c, col);
            a.columns.push_back(col);
        }
    }
}

} // namespace arch
