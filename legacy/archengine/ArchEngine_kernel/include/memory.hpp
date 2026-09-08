#pragma once

#include "types.hpp"
#include <mutex>
#include <atomic>
#include <unordered_map>
#include <source_location>

namespace arch {

// ============================================================================
// MEMORY SYSTEM
// ============================================================================
// Custom memory management with tracking, pooling, and leak detection.
// Foundation for novel memory strategies.
//
// Design principles:
// 1. Every allocation is tracked (debug builds)
// 2. Pooled allocators for hot paths
// 3. Arena allocators for frame-local data
// 4. Explicit ownership semantics (no hidden copies)
// ============================================================================

// Forward declarations
class MemoryArena;
// Template PoolAllocator defined below

// Allocation info for tracking
struct AllocationInfo {
    void* ptr;
    size_t size;
    const char* file;
    u32 line;
    const char* tag;
    u64 frameAllocated;
    std::chrono::steady_clock::time_point timestamp;
};

// Memory statistics
struct MemoryStats {
    std::atomic<u64> totalAllocated{0};
    std::atomic<u64> totalFreed{0};
    std::atomic<u64> currentUsage{0};
    std::atomic<u64> peakUsage{0};
    std::atomic<u64> allocationCount{0};
    std::atomic<u64> freeCount{0};
    std::atomic<u64> arenaAllocations{0};
    std::atomic<u64> poolAllocations{0};

    void recordAllocation(size_t size) {
        totalAllocated += size;
        currentUsage += size;
        allocationCount++;
        u64 current = currentUsage.load();
        u64 peak = peakUsage.load();
        while (current > peak && !peakUsage.compare_exchange_weak(peak, current));
    }

    void recordFree(size_t size) {
        totalFreed += size;
        currentUsage -= size;
        freeCount++;
    }

    void print() const;
};

// Global memory stats
extern MemoryStats g_memoryStats;

// ============================================================================
// ARENA ALLOCATOR
// ============================================================================
// Fast bump allocator for temporary/frame-local allocations.
// All memory freed at once when arena is reset.
// Zero fragmentation, cache-friendly.

class MemoryArena {
public:
    explicit MemoryArena(size_t size);
    ~MemoryArena();

    // Non-copyable, movable
    MemoryArena(const MemoryArena&) = delete;
    MemoryArena& operator=(const MemoryArena&) = delete;
    MemoryArena(MemoryArena&& other) noexcept;
    MemoryArena& operator=(MemoryArena&& other) noexcept;

    // Allocate memory (bump pointer)
    void* alloc(size_t size, size_t alignment = 16);

    // Typed allocation
    template<typename T, typename... Args>
    T* create(Args&&... args) {
        void* ptr = alloc(sizeof(T), alignof(T));
        return new(ptr) T(std::forward<Args>(args)...);
    }

    // Allocate array
    template<typename T>
    T* allocArray(size_t count) {
        return static_cast<T*>(alloc(sizeof(T) * count, alignof(T)));
    }

    // Reset arena (free all memory at once)
    void reset();

    // Get stats
    size_t getUsed() const { return m_offset; }
    size_t getCapacity() const { return m_size; }
    size_t getRemaining() const { return m_size - m_offset; }

private:
    u8* m_memory = nullptr;
    size_t m_size = 0;
    size_t m_offset = 0;
};

// ============================================================================
// POOL ALLOCATOR
// ============================================================================
// Fixed-size block allocator for objects of the same size.
// O(1) allocation and deallocation.
// Excellent cache locality.

template<typename T, size_t BlockCount = 1024>
class PoolAllocator {
public:
    PoolAllocator() {
        // Allocate pool memory
        m_memory = static_cast<u8*>(_aligned_malloc(sizeof(T) * BlockCount, alignof(T)));
        if (!m_memory) {
            throw std::bad_alloc();
        }

        // Initialize free list
        m_freeList = reinterpret_cast<FreeNode*>(m_memory);
        FreeNode* current = m_freeList;
        for (size_t i = 0; i < BlockCount - 1; ++i) {
            current->next = reinterpret_cast<FreeNode*>(m_memory + (i + 1) * sizeof(T));
            current = current->next;
        }
        current->next = nullptr;

        g_memoryStats.poolAllocations++;
    }

    ~PoolAllocator() {
        _aligned_free(m_memory);
    }

    // Non-copyable
    PoolAllocator(const PoolAllocator&) = delete;
    PoolAllocator& operator=(const PoolAllocator&) = delete;

    // Allocate single object
    template<typename... Args>
    T* create(Args&&... args) {
        if (!m_freeList) {
            throw std::bad_alloc();
        }

        // Pop from free list
        void* ptr = m_freeList;
        m_freeList = m_freeList->next;
        m_allocatedCount++;

        // Construct object
        return new(ptr) T(std::forward<Args>(args)...);
    }

    // Deallocate single object
    void destroy(T* obj) {
        if (!obj) return;

        // Destruct
        obj->~T();

        // Push to free list
        FreeNode* node = reinterpret_cast<FreeNode*>(obj);
        node->next = m_freeList;
        m_freeList = node;
        m_allocatedCount--;
    }

    size_t getAllocatedCount() const { return m_allocatedCount; }
    size_t getCapacity() const { return BlockCount; }

private:
    struct FreeNode {
        FreeNode* next;
    };

    u8* m_memory = nullptr;
    FreeNode* m_freeList = nullptr;
    size_t m_allocatedCount = 0;
};

// ============================================================================
// TRACKED ALLOCATIONS (Debug)
// ============================================================================
// Wrap standard allocations with tracking for leak detection.

#ifdef ARCH_DEBUG

void* trackedAlloc(size_t size, const char* file, u32 line, const char* tag = nullptr);
void trackedFree(void* ptr);
void reportLeaks();

#define ARCH_ALLOC(size) arch::trackedAlloc(size, __FILE__, __LINE__)
#define ARCH_ALLOC_TAG(size, tag) arch::trackedAlloc(size, __FILE__, __LINE__, tag)
#define ARCH_FREE(ptr) arch::trackedFree(ptr)

#else

#define ARCH_ALLOC(size) std::malloc(size)
#define ARCH_ALLOC_TAG(size, tag) std::malloc(size)
#define ARCH_FREE(ptr) std::free(ptr)

#endif

// ============================================================================
// SMART POINTERS WITH CUSTOM DELETERS
// ============================================================================

// Unique pointer that tracks memory
template<typename T>
struct TrackedDeleter {
    void operator()(T* ptr) {
        if (ptr) {
            ptr->~T();
            ARCH_FREE(ptr);
        }
    }
};

template<typename T>
using UniquePtr = std::unique_ptr<T, TrackedDeleter<T>>;

template<typename T, typename... Args>
UniquePtr<T> makeUnique(Args&&... args) {
    void* mem = ARCH_ALLOC(sizeof(T));
    T* obj = new(mem) T(std::forward<Args>(args)...);
    return UniquePtr<T>(obj);
}

// ============================================================================
// FRAME ALLOCATOR
// ============================================================================
// Per-frame temporary allocations that auto-reset each frame.
// Global access for convenience.

class FrameAllocator {
public:
    static void init(size_t size = 16 * 1024 * 1024);  // 16MB default
    static void shutdown();
    static void beginFrame();
    static void endFrame();

    static void* alloc(size_t size, size_t alignment = 16);

    template<typename T, typename... Args>
    static T* create(Args&&... args) {
        void* ptr = alloc(sizeof(T), alignof(T));
        return new(ptr) T(std::forward<Args>(args)...);
    }

    template<typename T>
    static T* allocArray(size_t count) {
        return static_cast<T*>(alloc(sizeof(T) * count, alignof(T)));
    }

private:
    static MemoryArena* s_arena;
    static u64 s_frameNumber;
};

} // namespace arch
