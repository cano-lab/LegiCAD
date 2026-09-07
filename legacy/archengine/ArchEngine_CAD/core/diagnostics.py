"""
Diagnostics Module - Tools for monitoring and debugging the application.

Provides:
- Memory tracking and leak detection
- Frame rate monitoring
- Resource usage logging
- Signal/slot connection tracking
- Performance profiling
- Crash/error logging
"""
import gc
import sys
import time
import traceback
import threading
import weakref
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
from collections import defaultdict
from dataclasses import dataclass, field

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("[Diagnostics] psutil not available - memory tracking limited")


@dataclass
class FrameStats:
    """Statistics for frame timing."""
    frame_count: int = 0
    total_time: float = 0.0
    min_time: float = float('inf')
    max_time: float = 0.0
    last_fps: float = 0.0
    fps_samples: List[float] = field(default_factory=list)


@dataclass
class MemorySnapshot:
    """Memory usage snapshot."""
    timestamp: datetime
    rss_mb: float  # Resident Set Size
    vms_mb: float  # Virtual Memory Size
    gc_objects: int  # Number of tracked objects
    label: str = ""


class DiagnosticsManager:
    """
    Central manager for application diagnostics.

    Usage:
        diag = DiagnosticsManager.instance()
        diag.start_monitoring()

        # Track a function
        @diag.profile
        def my_function():
            ...

        # Log memory
        diag.log_memory("after_load")

        # Check for leaks
        diag.check_memory_growth()
    """

    _instance = None

    @classmethod
    def instance(cls) -> 'DiagnosticsManager':
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._enabled = True
        self._log_file: Optional[Path] = None
        self._memory_snapshots: List[MemorySnapshot] = []
        self._frame_stats = FrameStats()
        self._profile_data: Dict[str, List[float]] = defaultdict(list)
        self._signal_connections: Dict[str, int] = defaultdict(int)
        self._tracked_objects: Dict[str, weakref.ref] = {}
        self._warnings: List[str] = []
        self._last_frame_time = time.perf_counter()
        self._frame_times: List[float] = []
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Thresholds for warnings
        self.memory_growth_threshold_mb = 50  # Warn if memory grows by this much
        self.frame_time_threshold_ms = 50  # Warn if frame takes longer than this
        self.max_signal_connections = 100  # Warn if too many connections

        # Initialize log file
        self._init_log_file()

    def _init_log_file(self):
        """Initialize diagnostic log file."""
        # Use user's home directory to avoid permission issues in Program Files
        log_dir = Path.home() / ".legiblestudio" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_file = log_dir / f"diagnostics_{timestamp}.log"

        self._write_log(f"=== ArchEngine CAD Diagnostics ===")
        self._write_log(f"Started: {datetime.now().isoformat()}")
        self._write_log(f"Python: {sys.version}")
        self._write_log(f"psutil available: {HAS_PSUTIL}")
        self._write_log("")

    def _write_log(self, message: str):
        """Write message to log file."""
        if self._log_file:
            try:
                with open(self._log_file, 'a', encoding='utf-8') as f:
                    f.write(f"{message}\n")
            except Exception:
                pass

    def log(self, message: str, level: str = "INFO"):
        """Log a diagnostic message."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = f"[{timestamp}] [{level}] {message}"
        print(f"[Diag] {formatted}")
        self._write_log(formatted)

    def warn(self, message: str):
        """Log a warning."""
        self._warnings.append(message)
        self.log(message, "WARN")

    def error(self, message: str, exc: Optional[Exception] = None):
        """Log an error with optional exception."""
        self.log(message, "ERROR")
        if exc:
            tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
            for line in tb:
                self._write_log(line.rstrip())

    # =========================================================================
    # Memory Tracking
    # =========================================================================

    def log_memory(self, label: str = ""):
        """Take a memory snapshot."""
        snapshot = self._get_memory_snapshot(label)
        self._memory_snapshots.append(snapshot)

        self.log(f"Memory [{label}]: RSS={snapshot.rss_mb:.1f}MB, "
                f"VMS={snapshot.vms_mb:.1f}MB, GC_Objects={snapshot.gc_objects}")

        return snapshot

    def _get_memory_snapshot(self, label: str = "") -> MemorySnapshot:
        """Get current memory usage."""
        gc_objects = len(gc.get_objects())

        if HAS_PSUTIL:
            process = psutil.Process()
            mem = process.memory_info()
            rss_mb = mem.rss / (1024 * 1024)
            vms_mb = mem.vms / (1024 * 1024)
        else:
            rss_mb = 0.0
            vms_mb = 0.0

        return MemorySnapshot(
            timestamp=datetime.now(),
            rss_mb=rss_mb,
            vms_mb=vms_mb,
            gc_objects=gc_objects,
            label=label
        )

    def check_memory_growth(self, threshold_mb: Optional[float] = None) -> bool:
        """
        Check if memory has grown significantly since first snapshot.
        Returns True if growth exceeds threshold.
        """
        if len(self._memory_snapshots) < 2:
            return False

        threshold = threshold_mb or self.memory_growth_threshold_mb
        first = self._memory_snapshots[0]
        last = self._memory_snapshots[-1]

        growth = last.rss_mb - first.rss_mb

        if growth > threshold:
            self.warn(f"Memory growth detected: {growth:.1f}MB "
                     f"(from {first.rss_mb:.1f}MB to {last.rss_mb:.1f}MB)")
            return True

        return False

    def gc_collect(self, generation: int = 2) -> int:
        """Force garbage collection and return count of freed objects."""
        before = len(gc.get_objects())
        gc.collect(generation)
        after = len(gc.get_objects())
        freed = before - after

        if freed > 100:
            self.log(f"GC collected {freed} objects")

        return freed

    def find_leaks(self, type_filter: Optional[str] = None) -> Dict[str, int]:
        """
        Analyze objects in memory by type.
        Useful for finding what's accumulating.
        """
        gc.collect()

        type_counts: Dict[str, int] = defaultdict(int)
        for obj in gc.get_objects():
            type_name = type(obj).__name__
            if type_filter is None or type_filter.lower() in type_name.lower():
                type_counts[type_name] += 1

        # Sort by count
        sorted_counts = dict(sorted(type_counts.items(), key=lambda x: -x[1])[:20])

        self.log(f"Top object types: {sorted_counts}")
        return sorted_counts

    # =========================================================================
    # Frame Rate Monitoring
    # =========================================================================

    def frame_start(self):
        """Call at the start of each frame."""
        self._last_frame_time = time.perf_counter()

    def frame_end(self):
        """Call at the end of each frame. Returns frame time in ms."""
        now = time.perf_counter()
        frame_time = (now - self._last_frame_time) * 1000  # ms

        with self._lock:
            self._frame_stats.frame_count += 1
            self._frame_stats.total_time += frame_time
            self._frame_stats.min_time = min(self._frame_stats.min_time, frame_time)
            self._frame_stats.max_time = max(self._frame_stats.max_time, frame_time)

            self._frame_times.append(frame_time)
            if len(self._frame_times) > 60:
                self._frame_times.pop(0)

            # Calculate FPS
            if self._frame_times:
                avg_time = sum(self._frame_times) / len(self._frame_times)
                self._frame_stats.last_fps = 1000.0 / avg_time if avg_time > 0 else 0

        # Warn on slow frames
        if frame_time > self.frame_time_threshold_ms:
            self.warn(f"Slow frame: {frame_time:.1f}ms")

        return frame_time

    def get_fps(self) -> float:
        """Get current FPS estimate."""
        return self._frame_stats.last_fps

    def get_frame_stats(self) -> dict:
        """Get frame timing statistics."""
        stats = self._frame_stats
        avg_time = stats.total_time / max(1, stats.frame_count)

        return {
            'frame_count': stats.frame_count,
            'avg_ms': avg_time,
            'min_ms': stats.min_time if stats.min_time != float('inf') else 0,
            'max_ms': stats.max_time,
            'fps': stats.last_fps,
        }

    def reset_frame_stats(self):
        """Reset frame statistics."""
        self._frame_stats = FrameStats()
        self._frame_times.clear()

    # =========================================================================
    # Performance Profiling
    # =========================================================================

    def profile(self, func: Callable) -> Callable:
        """Decorator to profile a function's execution time."""
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = (time.perf_counter() - start) * 1000
                self._profile_data[func.__name__].append(elapsed)

                # Keep last 100 samples
                if len(self._profile_data[func.__name__]) > 100:
                    self._profile_data[func.__name__].pop(0)

        return wrapper

    def time_block(self, name: str):
        """Context manager for timing a code block."""
        return _TimingContext(self, name)

    def get_profile_stats(self, func_name: str) -> Optional[dict]:
        """Get profiling stats for a function."""
        if func_name not in self._profile_data:
            return None

        times = self._profile_data[func_name]
        if not times:
            return None

        return {
            'calls': len(times),
            'avg_ms': sum(times) / len(times),
            'min_ms': min(times),
            'max_ms': max(times),
            'total_ms': sum(times),
        }

    def get_all_profile_stats(self) -> Dict[str, dict]:
        """Get profiling stats for all tracked functions."""
        return {name: self.get_profile_stats(name)
                for name in self._profile_data
                if self.get_profile_stats(name)}

    # =========================================================================
    # Signal/Slot Connection Tracking
    # =========================================================================

    def track_connection(self, signal_name: str):
        """Track a signal connection."""
        self._signal_connections[signal_name] += 1

        total = sum(self._signal_connections.values())
        if total > self.max_signal_connections:
            self.warn(f"High signal connection count: {total}")

    def track_disconnection(self, signal_name: str):
        """Track a signal disconnection."""
        if self._signal_connections[signal_name] > 0:
            self._signal_connections[signal_name] -= 1

    def get_connection_counts(self) -> Dict[str, int]:
        """Get signal connection counts."""
        return dict(self._signal_connections)

    # =========================================================================
    # Object Tracking
    # =========================================================================

    def track_object(self, obj: Any, name: str):
        """Track an object with a weak reference for leak detection."""
        self._tracked_objects[name] = weakref.ref(obj)

    def check_tracked_objects(self) -> List[str]:
        """Check which tracked objects are still alive."""
        alive = []
        dead = []

        for name, ref in self._tracked_objects.items():
            if ref() is not None:
                alive.append(name)
            else:
                dead.append(name)

        # Clean up dead references
        for name in dead:
            del self._tracked_objects[name]

        return alive

    # =========================================================================
    # Background Monitoring
    # =========================================================================

    def start_monitoring(self, interval_seconds: float = 30.0):
        """Start background monitoring thread."""
        if self._monitoring:
            return

        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval_seconds,),
            daemon=True
        )
        self._monitor_thread.start()
        self.log("Background monitoring started")

    def stop_monitoring(self):
        """Stop background monitoring."""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        self.log("Background monitoring stopped")

    def _monitor_loop(self, interval: float):
        """Background monitoring loop."""
        while self._monitoring:
            try:
                self.log_memory("periodic")
                self.check_memory_growth()

                # Log frame stats periodically
                stats = self.get_frame_stats()
                if stats['frame_count'] > 0:
                    self.log(f"Frame stats: {stats['fps']:.1f} FPS, "
                            f"avg={stats['avg_ms']:.1f}ms, "
                            f"max={stats['max_ms']:.1f}ms")

            except Exception as e:
                self.error("Monitor error", e)

            time.sleep(interval)

    # =========================================================================
    # Reports
    # =========================================================================

    def generate_report(self) -> str:
        """Generate a diagnostic report."""
        lines = [
            "=" * 60,
            "DIAGNOSTIC REPORT",
            f"Generated: {datetime.now().isoformat()}",
            "=" * 60,
            "",
            "--- Memory ---",
        ]

        if self._memory_snapshots:
            first = self._memory_snapshots[0]
            last = self._memory_snapshots[-1]
            lines.append(f"Initial: RSS={first.rss_mb:.1f}MB, GC={first.gc_objects}")
            lines.append(f"Current: RSS={last.rss_mb:.1f}MB, GC={last.gc_objects}")
            lines.append(f"Growth: {last.rss_mb - first.rss_mb:.1f}MB")

        lines.extend([
            "",
            "--- Frame Performance ---",
        ])
        stats = self.get_frame_stats()
        lines.append(f"Frames: {stats['frame_count']}")
        lines.append(f"FPS: {stats['fps']:.1f}")
        lines.append(f"Frame time: avg={stats['avg_ms']:.1f}ms, "
                    f"min={stats['min_ms']:.1f}ms, max={stats['max_ms']:.1f}ms")

        lines.extend([
            "",
            "--- Profiled Functions ---",
        ])
        for name, pstats in self.get_all_profile_stats().items():
            lines.append(f"  {name}: {pstats['calls']} calls, "
                        f"avg={pstats['avg_ms']:.2f}ms, total={pstats['total_ms']:.1f}ms")

        lines.extend([
            "",
            "--- Signal Connections ---",
            f"Total: {sum(self._signal_connections.values())}",
        ])
        for name, count in sorted(self._signal_connections.items(), key=lambda x: -x[1])[:10]:
            lines.append(f"  {name}: {count}")

        if self._warnings:
            lines.extend([
                "",
                "--- Warnings ---",
            ])
            for warn in self._warnings[-20:]:
                lines.append(f"  {warn}")

        lines.append("")
        lines.append("=" * 60)

        report = "\n".join(lines)
        self._write_log(report)
        return report

    def save_report(self, path: Optional[Path] = None):
        """Save diagnostic report to file."""
        if path is None:
            log_dir = Path.home() / ".legiblestudio" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = log_dir / f"report_{timestamp}.txt"

        report = self.generate_report()
        path.write_text(report)
        self.log(f"Report saved to {path}")
        return path


class _TimingContext:
    """Context manager for timing code blocks."""

    def __init__(self, diag: DiagnosticsManager, name: str):
        self.diag = diag
        self.name = name
        self.start = 0.0

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        elapsed = (time.perf_counter() - self.start) * 1000
        self.diag._profile_data[self.name].append(elapsed)
        if len(self.diag._profile_data[self.name]) > 100:
            self.diag._profile_data[self.name].pop(0)


# Convenience functions
def get_diagnostics() -> DiagnosticsManager:
    """Get the diagnostics manager instance."""
    return DiagnosticsManager.instance()


def log_memory(label: str = ""):
    """Quick memory logging."""
    return get_diagnostics().log_memory(label)


def diag_log(message: str):
    """Quick diagnostic log."""
    get_diagnostics().log(message)
