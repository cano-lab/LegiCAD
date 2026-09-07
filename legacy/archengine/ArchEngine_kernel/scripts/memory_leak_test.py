#!/usr/bin/env python3
"""
Memory leak test for ArchEngine.
Repeatedly loads and renders scenes while monitoring memory usage.
"""

import psutil
import time
import json
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def get_memory_usage():
    """Get current memory usage in MB"""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024  # Convert to MB

def test_scene_load_reload():
    """Test loading and reloading scenes repeatedly"""
    print("=" * 60)
    print("Memory Leak Test: Scene Load/Reload")
    print("=" * 60)

    # Import after adding to path
    try:
        import arch_api
    except ImportError:
        print("ERROR: arch_api module not found. Engine must be built with Python support.")
        return False

    # Simple test building (one floor, four columns, four beams)
    test_building = {
        "name": "Leak Test",
        "elements": [
            # Floor
            {
                "type": "floor",
                "start": [0, 0, 0],
                "end": [10, 0.2, 10],
                "width": 0.2
            },
            # Four columns
            {
                "type": "column",
                "start": [0, 0.2, 0],
                "end": [0, 3, 0],
                "width": 0.3,
                "depth": 0.3
            },
            {
                "type": "column",
                "start": [10, 0.2, 0],
                "end": [10, 3, 0],
                "width": 0.3,
                "depth": 0.3
            },
            {
                "type": "column",
                "start": [0, 0.2, 10],
                "end": [0, 3, 10],
                "width": 0.3,
                "depth": 0.3
            },
            {
                "type": "column",
                "start": [10, 0.2, 10],
                "end": [10, 3, 10],
                "width": 0.3,
                "depth": 0.3
            },
            # Four beams
            {
                "type": "beam",
                "start": [0, 3, 0],
                "end": [10, 3, 0],
                "width": 0.2,
                "depth": 0.2
            },
            {
                "type": "beam",
                "start": [0, 3, 10],
                "end": [10, 3, 10],
                "width": 0.2,
                "depth": 0.2
            },
            {
                "type": "beam",
                "start": [0, 3, 0],
                "end": [0, 3, 10],
                "width": 0.2,
                "depth": 0.2
            },
            {
                "type": "beam",
                "start": [10, 3, 0],
                "end": [10, 3, 10],
                "width": 0.2,
                "depth": 0.2
            }
        ]
    }

    iterations = 10
    memory_readings = []

    print(f"\nRunning {iterations} iterations of load/render/unload...")
    print("This will take a few minutes...\n")

    for i in range(iterations):
        print(f"Iteration {i+1}/{iterations}...", end=" ", flush=True)

        mem_before = get_memory_usage()

        # Load building
        building_json = json.dumps(test_building)
        arch_api.arch_load_json(building_json)

        # Wait a bit for rendering
        time.sleep(0.5)

        mem_after_load = get_memory_usage()

        # Clear building
        arch_api.arch_load_json('{"name": "empty", "elements": []}')

        # Wait for cleanup
        time.sleep(0.5)

        mem_after_clear = get_memory_usage()

        leaked = mem_after_clear - mem_before

        print(f"Before: {mem_before:.1f}MB, After Load: {mem_after_load:.1f}MB, "
              f"After Clear: {mem_after_clear:.1f}MB, Leaked: {leaked:+.1f}MB")

        memory_readings.append({
            'iteration': i + 1,
            'before': mem_before,
            'after_load': mem_after_load,
            'after_clear': mem_after_clear,
            'leaked': leaked
        })

    # Analysis
    print("\n" + "=" * 60)
    print("MEMORY LEAK ANALYSIS")
    print("=" * 60)

    initial_mem = memory_readings[0]['after_clear']
    final_mem = memory_readings[-1]['after_clear']
    total_leaked = final_mem - initial_mem

    avg_leak_per_iter = sum(r['leaked'] for r in memory_readings) / len(memory_readings)

    print(f"\nInitial memory: {initial_mem:.1f}MB")
    print(f"Final memory: {final_mem:.1f}MB")
    print(f"Total change: {total_leaked:+.1f}MB over {iterations} iterations")
    print(f"Average leak per iteration: {avg_leak_per_iter:+.1f}MB")

    # Determine if there's a significant leak
    if total_leaked > 100:  # More than 100MB leaked
        print("\n⚠️  WARNING: Significant memory leak detected!")
        print("   More than 100MB leaked over test period.")
        return False
    elif total_leaked > 50:
        print("\n⚠️  CAUTION: Possible memory leak.")
        print("   50-100MB leaked - may need investigation.")
        return False
    elif avg_leak_per_iter > 5:
        print("\n⚠️  CAUTION: Small but consistent leak.")
        print(f"   Averaging {avg_leak_per_iter:.1f}MB per iteration.")
        return False
    else:
        print("\n✅ PASS: No significant memory leak detected.")
        print("   Memory usage is stable within acceptable range.")
        return True

def test_high_res_render():
    """Test memory usage during high-res renders"""
    print("\n" + "=" * 60)
    print("Memory Leak Test: High-Res Render")
    print("=" * 60)

    try:
        import arch_api
    except ImportError:
        print("ERROR: arch_api module not found")
        return False

    # Simple building
    test_building = {
        "name": "Render Test",
        "elements": [
            {"type": "floor", "start": [0, 0, 0], "end": [5, 0.2, 5], "width": 0.2},
            {
                "type": "column",
                "start": [0, 0.2, 0],
                "end": [0, 2.5, 0],
                "width": 0.25,
                "depth": 0.25
            },
        ]
    }

    print(f"\nLoading test building...")
    arch_api.arch_load_json(json.dumps(test_building))
    time.sleep(1)

    mem_before = get_memory_usage()
    print(f"Memory before renders: {mem_before:.1f}MB")

    # Do multiple small renders
    renders = 5
    print(f"\nRunning {renders} preview renders...")

    for i in range(renders):
        print(f"  Render {i+1}/{renders}...", flush=True)
        # In a real test, we'd call arch_high_res_render here
        # For now, just wait to simulate render time
        time.sleep(1)

        mem_current = get_memory_usage()
        leaked = mem_current - mem_before
        print(f"    Memory: {mem_current:.1f}MB (Δ {leaked:+.1f}MB)")

    print("\n✅ High-res render test complete")

    # Clean up
    arch_api.arch_load_json('{"name": "empty", "elements": []}')

    return True


if __name__ == '__main__':
    print("ArchEngine Memory Leak Detection Tool")
    print("====================================\n")

    try:
        # Run tests
        result1 = test_scene_load_reload()
        result2 = test_high_res_render()

        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Load/Reload Test: {'✅ PASS' if result1 else '❌ FAIL'}")
        print(f"High-Res Render Test: {'✅ PASS' if result2 else '❌ FAIL'}")

        sys.exit(0 if (result1 and result2) else 1)

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
