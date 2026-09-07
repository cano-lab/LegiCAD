#pragma once

#include "types.hpp"
#include <nlohmann/json.hpp>

namespace arch {

using json = nlohmann::json;

// Analysis result from Python physics engine
struct BeamAnalysis {
    bool passes;
    f32 maxStressPsi;
    f32 allowableStressPsi;
    f32 maxDeflectionIn;
    f32 allowableDeflectionIn;
    f32 utilizationRatio;
    std::vector<std::string> warnings;
};

struct ColumnAnalysis {
    bool passes;
    f32 appliedLoadLbs;
    f32 allowableLoadLbs;
    f32 slendernessRatio;
    f32 utilizationRatio;
    std::string bucklingMode;
    std::vector<std::string> warnings;
};

struct FrameAnalysis {
    std::vector<BeamAnalysis> beams;
    std::vector<ColumnAnalysis> columns;
    bool allPass;
    f32 maxBeamUtilization;
    f32 maxColumnUtilization;
};

// Physics bridge to Python analysis engine
class PhysicsBridge {
public:
    PhysicsBridge();
    ~PhysicsBridge();

    // Check if Python backend is available
    bool isAvailable() const { return m_available; }

    // Analyze a beam
    BeamAnalysis analyzeBeam(f32 spanFt, f32 widthIn, f32 depthIn,
                             const std::string& material, f32 uniformLoadPlf);

    // Analyze a column
    ColumnAnalysis analyzeColumn(f32 heightFt, f32 widthIn, f32 depthIn,
                                 const std::string& material, f32 axialLoadLbs);

    // Analyze an entire frame
    FrameAnalysis analyzeFrame(const std::vector<StructuralElement>& elements);

    // Load analysis results from JSON file
    FrameAnalysis loadFromFile(const std::string& filepath);

    // Save current model to JSON for Python analysis
    void saveModelToFile(const std::string& filepath,
                        const std::vector<StructuralElement>& elements);

    // Run Python analysis script
    bool runPythonAnalysis(const std::string& inputFile, const std::string& outputFile);

    // Convert analysis results to render data
    std::vector<StructuralElement> convertToRenderElements(const FrameAnalysis& analysis,
                                                           const std::vector<StructuralElement>& geometry);

private:
    bool initPythonBridge();
    json callPythonFunction(const std::string& function, const json& args);

    bool m_available = false;
    std::string m_pythonPath;
    std::string m_physicsModulePath;
};

// JSON serialization for structural elements
void to_json(json& j, const StructuralElement& e);
void from_json(const json& j, StructuralElement& e);

void to_json(json& j, const BeamAnalysis& a);
void from_json(const json& j, BeamAnalysis& a);

void to_json(json& j, const ColumnAnalysis& a);
void from_json(const json& j, ColumnAnalysis& a);

void to_json(json& j, const FrameAnalysis& a);
void from_json(const json& j, FrameAnalysis& a);

} // namespace arch
