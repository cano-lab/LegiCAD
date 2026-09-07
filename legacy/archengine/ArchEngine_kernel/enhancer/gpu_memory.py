# gpu_memory.py
# GPU memory management utilities for limited VRAM systems
# Handles cleanup between operations and automatic resolution scaling

import gc
from typing import Optional, Tuple
from PIL import Image

# Track what's currently loaded
_loaded_models = set()

def get_vram_info() -> dict:
    """Get GPU VRAM information."""
    try:
        import torch
        if not torch.cuda.is_available():
            return {"available": False, "total_gb": 0, "free_gb": 0, "used_gb": 0}

        total = torch.cuda.get_device_properties(0).total_memory
        reserved = torch.cuda.memory_reserved(0)
        allocated = torch.cuda.memory_allocated(0)
        free = total - reserved

        return {
            "available": True,
            "total_gb": total / (1024**3),
            "free_gb": free / (1024**3),
            "used_gb": allocated / (1024**3),
            "reserved_gb": reserved / (1024**3),
            "device_name": torch.cuda.get_device_name(0)
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


def cleanup_gpu(force: bool = False) -> dict:
    """
    Aggressive GPU memory cleanup.

    Args:
        force: If True, also unloads cached models

    Returns:
        Dict with before/after memory stats
    """
    before = get_vram_info()

    # Python garbage collection
    gc.collect()

    try:
        import torch
        if torch.cuda.is_available():
            # Clear PyTorch cache
            torch.cuda.empty_cache()
            torch.cuda.synchronize()

            # Additional cleanup
            if hasattr(torch.cuda, 'reset_peak_memory_stats'):
                torch.cuda.reset_peak_memory_stats()
    except ImportError:
        pass

    if force:
        # Unload segmentation models
        try:
            from ai_segmentation import unload_models
            unload_models()
            _loaded_models.discard("segmentation")
        except:
            pass

        # Unload SD pipeline if exists
        try:
            from ai_enhancer import unload_pipeline
            unload_pipeline()
            _loaded_models.discard("sd_pipeline")
        except:
            pass

    # Final cleanup
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except:
        pass

    after = get_vram_info()

    freed = before.get("used_gb", 0) - after.get("used_gb", 0)
    print(f"GPU Cleanup: freed {freed:.2f}GB, now {after.get('free_gb', 0):.2f}GB free")

    return {
        "before": before,
        "after": after,
        "freed_gb": freed
    }


def register_model(name: str):
    """Register that a model is loaded."""
    _loaded_models.add(name)


def unregister_model(name: str):
    """Register that a model is unloaded."""
    _loaded_models.discard(name)


def get_loaded_models() -> set:
    """Get set of currently loaded model names."""
    return _loaded_models.copy()


def estimate_vram_needed(task: str, resolution: Tuple[int, int] = (1024, 1024)) -> float:
    """
    Estimate VRAM needed for a task.

    Returns estimated GB needed.
    """
    w, h = resolution
    pixels = w * h
    base_pixels = 1024 * 1024  # 1MP baseline
    scale = pixels / base_pixels

    estimates = {
        "oneformer": 2.5 * scale,      # ~2.5GB at 1MP
        "sam": 1.5 * scale,             # ~1.5GB at 1MP
        "sd15_inpaint": 4.0 * scale,    # ~4GB at 1MP
        "sdxl_inpaint": 10.0 * scale,   # ~10GB at 1MP (won't fit on 8GB)
        "depth_anything": 1.0 * scale,  # ~1GB at 1MP
        "controlnet": 1.5,              # Additional ~1.5GB per controlnet
    }

    return estimates.get(task, 2.0)


def get_safe_resolution(task: str, original_size: Tuple[int, int], max_vram_gb: float = None) -> Tuple[int, int]:
    """
    Calculate safe resolution for a task given VRAM constraints.

    Args:
        task: Task name (oneformer, sam, sd15_inpaint, etc.)
        original_size: Original (width, height)
        max_vram_gb: Override VRAM limit (auto-detects if None)

    Returns:
        Safe (width, height) that should fit in VRAM
    """
    if max_vram_gb is None:
        info = get_vram_info()
        max_vram_gb = info.get("free_gb", 4.0)

    # Leave headroom
    usable_vram = max_vram_gb * 0.8

    # Max resolutions per task for 8GB GPU (with headroom)
    max_res_8gb = {
        "oneformer": (1280, 1280),    # Reduce from original
        "sam": (1536, 1536),
        "sd15_inpaint": (1024, 1024),
        "sdxl_inpaint": (768, 768),   # Very tight on 8GB
        "depth_anything": (1536, 1536),
    }

    # Scale based on available VRAM relative to 8GB
    vram_scale = min(1.0, usable_vram / 6.0)  # 6GB as "comfortable" baseline

    max_size = max_res_8gb.get(task, (1024, 1024))
    scaled_max = (int(max_size[0] * vram_scale), int(max_size[1] * vram_scale))

    # Ensure minimum usable size
    scaled_max = (max(512, scaled_max[0]), max(512, scaled_max[1]))

    # Calculate output size maintaining aspect ratio
    w, h = original_size
    max_w, max_h = scaled_max

    if w <= max_w and h <= max_h:
        return original_size  # No resize needed

    # Scale down to fit
    scale = min(max_w / w, max_h / h)
    new_w = int(w * scale)
    new_h = int(h * scale)

    # Round to multiple of 8 (required by many models)
    new_w = (new_w // 8) * 8
    new_h = (new_h // 8) * 8

    print(f"VRAM limit: Scaling {task} from {w}x{h} to {new_w}x{new_h}")
    return (new_w, new_h)


def resize_for_task(image: Image.Image, task: str) -> Tuple[Image.Image, Tuple[int, int]]:
    """
    Resize image to safe resolution for task.

    Args:
        image: Input PIL image
        task: Task name

    Returns:
        (resized_image, original_size) - original_size for restoring later
    """
    original_size = image.size
    safe_size = get_safe_resolution(task, original_size)

    if safe_size == original_size:
        return image, original_size

    resized = image.resize(safe_size, Image.Resampling.LANCZOS)
    return resized, original_size


def restore_size(image: Image.Image, original_size: Tuple[int, int]) -> Image.Image:
    """Restore image to original size."""
    if image.size == original_size:
        return image
    return image.resize(original_size, Image.Resampling.LANCZOS)


# Auto-cleanup context manager
class GPUTask:
    """
    Context manager for GPU tasks with automatic cleanup.

    Usage:
        with GPUTask("oneformer"):
            # do segmentation
        # GPU automatically cleaned up
    """

    def __init__(self, task_name: str, cleanup_before: bool = True, cleanup_after: bool = True):
        self.task_name = task_name
        self.cleanup_before = cleanup_before
        self.cleanup_after = cleanup_after

    def __enter__(self):
        if self.cleanup_before:
            cleanup_gpu(force=False)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cleanup_after:
            cleanup_gpu(force=False)
        return False


print("GPU Memory Manager loaded")
vram = get_vram_info()
if vram.get("available"):
    print(f"  GPU: {vram.get('device_name', 'Unknown')}")
    print(f"  VRAM: {vram.get('total_gb', 0):.1f}GB total, {vram.get('free_gb', 0):.1f}GB free")
else:
    print("  No CUDA GPU available")
