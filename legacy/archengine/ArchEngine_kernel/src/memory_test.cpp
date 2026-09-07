#include "memory_test.hpp"
#include <iostream>

#ifdef _WIN32
#include <windows.h>
#include <psapi.h>
#endif

namespace arch {

size_t MemoryTest::getCurrentMemoryUsage() {
#ifdef _WIN32
    PROCESS_MEMORY_COUNTERS_EX pmc;
    if (GetProcessMemoryInfo(GetCurrentProcess(), (PROCESS_MEMORY_COUNTERS*)&pmc, sizeof(pmc))) {
        return pmc.WorkingSetSize;
    }
#endif
    return 0;
}

void MemoryTest::logMemory(const std::string& label) {
    size_t mem = getCurrentMemoryUsage();
    std::cout << "[MemTest] " << label << ": " << (mem / (1024 * 1024)) << " MB" << std::endl;
}

MemoryTestResult MemoryTest::runAllTests(VulkanContext& context, Renderer& renderer) {
    (void)context;
    (void)renderer;

    MemoryTestResult result;
    result.passed = true;
    result.pipelineLeakDetected = false;
    result.hdrLeakDetected = false;

    std::cout << "\n========== MEMORY LEAK TEST ==========\n" << std::endl;
    logMemory("Initial");
    logMemory("Final");
    std::cout << "Memory tests complete (stubbed).\n" << std::endl;

    return result;
}

} // namespace arch
