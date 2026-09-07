#!/usr/bin/env python3
"""
Simple memory monitor for ArchEngine process.
Monitors the ArchEngine.exe process memory usage over time.
Usage: python scripts/monitor_memory.py
"""

import psutil
import time
import sys

def find_archengine_process():
    """Find the ArchEngine.exe process"""
    for proc in psutil.process_iter(['name', 'pid', 'memory_info']):
        try:
            if proc.info['name'] and 'ArchEngine' in proc.info['name']:
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None

def format_memory(mb):
    """Format memory for display"""
    if mb < 1024:
        return f"{mb:.1f}MB"
    else:
        return f"{mb/1024:.2f}GB"

def monitor_memory(duration_seconds=300, interval_seconds=5):
    """
    Monitor ArchEngine memory usage

    Args:
        duration_seconds: How long to monitor (default 5 minutes)
        interval_seconds: How often to check (default 5 seconds)
    """
    print("=" * 60)
    print("ArchEngine Memory Monitor")
    print("=" * 60)

    proc = find_archengine_process()
    if not proc:
        print("ERROR: ArchEngine.exe not running!")
        print("Please launch ArchEngine first.")
        return False

    print(f"\nFound ArchEngine.exe (PID: {proc.pid})")
    print(f"Monitoring for {duration_seconds} seconds, checking every {interval_seconds} seconds...")
    print("Use the engine normally - the monitor will track memory usage.\n")

    readings = []
    start_time = time.time()
    iteration = 0

    try:
        while time.time() - start_time < duration_seconds:
            iteration += 1

            try:
                mem_info = proc.memory_info()
                mem_mb = mem_info.rss / 1024 / 1024

                readings.append({
                    'time': time.time() - start_time,
                    'memory_mb': mem_mb
                })

                elapsed = time.time() - start_time
                remaining = duration_seconds - elapsed

                # Calculate trend
                if len(readings) > 1:
                    first = readings[0]['memory_mb']
                    current = readings[-1]['memory_mb']
                    change = current - first
                    trend = "UP" if change > 1 else ("DOWN" if change < -1 else "STABLE")
                    trend_str = f" (Delta {change:+.1f}MB {trend})"
                else:
                    trend_str = ""

                print(f"[{elapsed:5.0f}s] Memory: {format_memory(mem_mb):>10s}{trend_str}  "
                      f"({iteration * interval_seconds}/{duration_seconds}s checked)")

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                print("\n! Process ended unexpectedly")
                break

            time.sleep(interval_seconds)

    except KeyboardInterrupt:
        print("\n\nMonitoring stopped by user.")

    # Analysis
    print("\n" + "=" * 60)
    print("MEMORY ANALYSIS")
    print("=" * 60)

    if len(readings) < 2:
        print("Not enough data for analysis")
        return True

    first_mem = readings[0]['memory_mb']
    last_mem = readings[-1]['memory_mb']
    max_mem = max(r['memory_mb'] for r in readings)
    min_mem = min(r['memory_mb'] for r in readings)
    avg_mem = sum(r['memory_mb'] for r in readings) / len(readings)

    total_change = last_mem - first_mem
    duration_minutes = (readings[-1]['time'] - readings[0]['time']) / 60

    print(f"\nDuration monitored: {duration_minutes:.1f} minutes")
    print(f"Initial memory:   {format_memory(first_mem)}")
    print(f"Final memory:     {format_memory(last_mem)}")
    print(f"Peak memory:      {format_memory(max_mem)}")
    print(f"Lowest memory:    {format_memory(min_mem)}")
    print(f"Average memory:   {format_memory(avg_mem)}")
    print(f"Total change:     {total_change:+.1f}MB")

    if duration_minutes > 0:
        leak_rate = total_change / duration_minutes
        print(f"Leak rate:        {leak_rate:+.1f}MB/minute")

    print("\nAssessment:")
    if total_change > 500:
        print("!  WARNING: Severe memory leak detected!")
        print(f"   {total_change:.0f}MB leaked - investigate immediately.")
        return False
    elif total_change > 200:
        print("!  CAUTION: Significant memory growth.")
        print(f"   {total_change:.0f}MB increase - may indicate a leak.")
        return False
    elif total_change > 50:
        print("!  NOTICE: Moderate memory growth.")
        print(f"   {total_change:.0f}MB increase - monitor during extended use.")
        return True
    else:
        print("OK Memory usage appears stable.")
        print("   No significant leaks detected.")
        return True

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Monitor ArchEngine memory usage')
    parser.add_argument('-d', '--duration', type=int, default=300,
                        help='Monitor duration in seconds (default: 300 = 5 min)')
    parser.add_argument('-i', '--interval', type=int, default=5,
                        help='Check interval in seconds (default: 5)')

    args = parser.parse_args()

    try:
        success = monitor_memory(args.duration, args.interval)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nX ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
