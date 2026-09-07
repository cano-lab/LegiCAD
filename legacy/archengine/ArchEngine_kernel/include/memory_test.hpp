#pragma once
/**
 * @file memory_test.hpp
 * @brief Memory leak and stress testing utilities
 */

#include <cstddef>
#include <string>
#include <memory>
#include <vector>

namespace arch {

// Forward declarations
class VulkanContext;
class Renderer;

/**
 * @brief Result of memory stress tests
 */
struct MemoryTestResult {
    bool passed = false;
    size_t startMemory = 0;
    size_t endMemory = 0;
    size_t peakMemory = 0;
    std::vector<std::string> testNames;
    std::vector<bool> testResults;
    bool pipelineLeakDetected = false;
    bool hdrLeakDetected = false;
};

/**
 * @brief Memory leak detection and stress testing
 */
class MemoryTest {
public:
    static size_t getCurrentMemoryUsage();
    static void logMemory(const std::string& label);
    static MemoryTestResult runAllTests(VulkanContext& context, Renderer& renderer);
};

} // namespace arch
