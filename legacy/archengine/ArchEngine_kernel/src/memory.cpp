#include "memory.hpp"
#include <cstdlib>
#include <iostream>
#include <iomanip>

namespace arch {

// Global memory stats
MemoryStats g_memoryStats;

void MemoryStats::print() const {
    std::cout << "=== Memory Statistics ===\n"
              << "Total Allocated:  " << totalAllocated.load() / 1024 << " KB\n"
              << "Total Freed:      " << totalFreed.load() / 1024 << " KB\n"
              << "Current Usage:    " << currentUsage.load() / 1024 << " KB\n"
              << "Peak Usage:       " << peakUsage.load() / 1024 << " KB\n"
              << "Allocation Count: " << allocationCount.load() << "\n"
              << "Free Count:       " << freeCount.load() << "\n"
              << "Arena Allocations:" << arenaAllocations.load() << "\n"
              << "Pool Allocations: " << poolAllocations.load() << "\n"
              << "========================\n";
}

// ============================================================================
// MEMORY ARENA IMPLEMENTATION
// ============================================================================

MemoryArena::MemoryArena(size_t size) : m_size(size), m_offset(0) {
    m_memory = static_cast<u8*>(_aligned_malloc(size, 16));
    if (!m_memory) {
        throw std::bad_alloc();
    }
    g_memoryStats.arenaAllocations++;
    g_memoryStats.recordAllocation(size);
}

MemoryArena::~MemoryArena() {
    if (m_memory) {
        g_memoryStats.recordFree(m_size);
        _aligned_free(m_memory);
        m_memory = nullptr;
    }
}

MemoryArena::MemoryArena(MemoryArena&& other) noexcept
    : m_memory(other.m_memory), m_size(other.m_size), m_offset(other.m_offset) {
    other.m_memory = nullptr;
    other.m_size = 0;
    other.m_offset = 0;
}

MemoryArena& MemoryArena::operator=(MemoryArena&& other) noexcept {
    if (this != &other) {
        if (m_memory) {
            g_memoryStats.recordFree(m_size);
            _aligned_free(m_memory);
        }
        m_memory = other.m_memory;
        m_size = other.m_size;
        m_offset = other.m_offset;
        other.m_memory = nullptr;
        other.m_size = 0;
        other.m_offset = 0;
    }
    return *this;
}

void* MemoryArena::alloc(size_t size, size_t alignment) {
    // Align the offset
    size_t alignedOffset = (m_offset + alignment - 1) & ~(alignment - 1);
    
    if (alignedOffset + size > m_size) {
        return nullptr;  // Out of memory
    }
    
    void* ptr = m_memory + alignedOffset;
    m_offset = alignedOffset + size;
    return ptr;
}

void MemoryArena::reset() {
    m_offset = 0;
}

// ============================================================================
// FRAME ALLOCATOR IMPLEMENTATION
// ============================================================================

MemoryArena* FrameAllocator::s_arena = nullptr;
u64 FrameAllocator::s_frameNumber = 0;

void FrameAllocator::init(size_t size) {
    if (!s_arena) {
        s_arena = new MemoryArena(size);
    }
}

void FrameAllocator::shutdown() {
    delete s_arena;
    s_arena = nullptr;
}

void FrameAllocator::beginFrame() {
    if (s_arena) {
        s_arena->reset();
    }
    s_frameNumber++;
}

void FrameAllocator::endFrame() {
    // Nothing to do - memory will be reset at beginFrame
}

void* FrameAllocator::alloc(size_t size, size_t alignment) {
    if (!s_arena) {
        init();  // Lazy initialization
    }
    return s_arena->alloc(size, alignment);
}

// ============================================================================
// TRACKED ALLOCATIONS (Debug)
// ============================================================================

#ifdef ARCH_DEBUG

static std::mutex g_trackingMutex;
static std::unordered_map<void*, AllocationInfo> g_allocations;

void* trackedAlloc(size_t size, const char* file, u32 line, const char* tag) {
    void* ptr = std::malloc(size);
    if (ptr) {
        std::lock_guard<std::mutex> lock(g_trackingMutex);
        g_allocations[ptr] = {
            ptr,
            size,
            file,
            line,
            tag,
            FrameAllocator::s_frameNumber,
            std::chrono::steady_clock::now()
        };
        g_memoryStats.recordAllocation(size);
    }
    return ptr;
}

void trackedFree(void* ptr) {
    if (!ptr) return;
    
    std::lock_guard<std::mutex> lock(g_trackingMutex);
    auto it = g_allocations.find(ptr);
    if (it != g_allocations.end()) {
        g_memoryStats.recordFree(it->second.size);
        g_allocations.erase(it);
    }
    std::free(ptr);
}

void reportLeaks() {
    std::lock_guard<std::mutex> lock(g_trackingMutex);
    
    if (g_allocations.empty()) {
        std::cout << "No memory leaks detected.\n";
        return;
    }
    
    std::cout << "=== MEMORY LEAKS DETECTED ===\n";
    std::cout << "Total leaks: " << g_allocations.size() << "\n\n";
    
    for (const auto& [ptr, info] : g_allocations) {
        std::cout << "Leak: " << info.size << " bytes at " << ptr << "\n"
                  << "  File: " << info.file << ":" << info.line << "\n";
        if (info.tag) {
            std::cout << "  Tag: " << info.tag << "\n";
        }
        std::cout << "  Frame: " << info.frameAllocated << "\n\n";
    }
    
    std::cout << "=============================\n";
}

#endif // ARCH_DEBUG

} // namespace arch
