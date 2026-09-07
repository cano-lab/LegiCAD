# ai_segmentation.py
# AI-powered semantic segmentation for architectural images
# Uses SAM (Segment Anything Model) for accurate masks

import numpy as np
from PIL import Image
from typing import Optional, List, Tuple, Dict
import gc

# Import GPU memory management
try:
    from gpu_memory import cleanup_gpu, resize_for_task, restore_size, GPUTask, get_vram_info
    HAS_GPU_MANAGER = True
except ImportError:
    HAS_GPU_MANAGER = False
    def cleanup_gpu(force=False): pass
    def resize_for_task(img, task): return img, img.size
    def restore_size(img, size): return img if img.size == size else img.resize(size, Image.Resampling.LANCZOS)
    class GPUTask:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False

print("=== AI SEGMENTATION MODULE ===")

# Global model instances
_sam_model = None
_sam_processor = None
_oneformer_model = None
_oneformer_processor = None


def get_sam_model():
    """Lazy load SAM model from transformers."""
    global _sam_model, _sam_processor

    if _sam_model is not None:
        return _sam_model, _sam_processor

    try:
        import torch
        from transformers import SamModel, SamProcessor

        print("Loading SAM model (first time downloads ~375MB)...")

        # Use the base SAM model - good balance of speed and quality
        model_id = "facebook/sam-vit-base"

        _sam_processor = SamProcessor.from_pretrained(model_id)
        _sam_model = SamModel.from_pretrained(model_id)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        _sam_model.to(device)
        _sam_model.eval()

        print(f"SAM model loaded on {device}")
        return _sam_model, _sam_processor

    except ImportError as e:
        print(f"SAM not available: {e}")
        print("Install with: pip install transformers")
        return None, None
    except Exception as e:
        print(f"Error loading SAM: {e}")
        return None, None


def get_oneformer_model():
    """Lazy load OneFormer for semantic segmentation."""
    global _oneformer_model, _oneformer_processor

    if _oneformer_model is not None:
        return _oneformer_model, _oneformer_processor

    try:
        import torch
        from transformers import OneFormerProcessor, OneFormerForUniversalSegmentation

        # Cleanup GPU before loading large model
        print("Cleaning GPU memory before loading OneFormer...")
        cleanup_gpu(force=True)

        print("Loading OneFormer model (first time downloads ~1GB)...")

        # ADE20k model has good outdoor/architectural classes
        model_id = "shi-labs/oneformer_ade20k_swin_large"

        _oneformer_processor = OneFormerProcessor.from_pretrained(model_id)
        _oneformer_model = OneFormerForUniversalSegmentation.from_pretrained(model_id)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        _oneformer_model.to(device)
        _oneformer_model.eval()

        print(f"OneFormer model loaded on {device}")
        return _oneformer_model, _oneformer_processor

    except ImportError as e:
        print(f"OneFormer not available: {e}")
        return None, None
    except Exception as e:
        print(f"Error loading OneFormer: {e}")
        import traceback
        traceback.print_exc()
        return None, None


# ADE20k class IDs for architectural segmentation
ADE20K_CLASSES = {
    'sky': [2],  # sky
    'building': [1, 25, 48, 79],  # building, house, skyscraper, tower
    'ground': [3, 9, 11, 13, 29, 52, 53, 54],  # floor, grass, ground, earth, field, path, road, sidewalk
    'vegetation': [4, 17, 66, 72],  # tree, plant, flower, palm
    'wall': [0],  # wall
    'window': [8],  # window
    'door': [14],  # door
    'roof': [43],  # roof (if available)
    'water': [21, 26, 60],  # water, sea, river
}


def segment_with_oneformer(
    image: Image.Image,
    target: str = "sky"
) -> Optional[np.ndarray]:
    """
    Segment image using OneFormer semantic segmentation.

    Args:
        image: Input PIL image
        target: What to segment - "sky", "building", "ground", "vegetation", "exterior"

    Returns:
        Binary mask as numpy array (0-255) or None if failed
    """
    import torch

    model, processor = get_oneformer_model()
    if model is None:
        return None

    device = next(model.parameters()).device
    original_size = image.size

    # Resize image if too large for VRAM (prevents OOM errors)
    work_image, _ = resize_for_task(image, "oneformer")
    work_size = work_image.size

    if work_size != original_size:
        print(f"OneFormer: Processing at {work_size[0]}x{work_size[1]} (original: {original_size[0]}x{original_size[1]})")

    try:
        # Prepare input
        inputs = processor(images=work_image, task_inputs=["semantic"], return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model(**inputs)

        # Get semantic segmentation at working size
        predicted_map = processor.post_process_semantic_segmentation(
            outputs, target_sizes=[work_size[::-1]]
        )[0]

        seg_map = predicted_map.cpu().numpy()

        # Clear intermediate tensors
        del outputs, inputs
        torch.cuda.empty_cache() if torch.cuda.is_available() else None

    except RuntimeError as e:
        if "out of memory" in str(e).lower():
            print(f"CUDA OOM in OneFormer - trying CPU fallback")
            cleanup_gpu(force=True)
            # Fall back to heuristic
            return None
        raise

    # Create mask based on target
    if target == "exterior":
        # Exterior = sky + ground + vegetation (everything except building)
        target_classes = ADE20K_CLASSES['sky'] + ADE20K_CLASSES['ground'] + ADE20K_CLASSES['vegetation']
    elif target in ADE20K_CLASSES:
        target_classes = ADE20K_CLASSES[target]
    else:
        print(f"Unknown target: {target}")
        return None

    # Create binary mask
    mask = np.zeros_like(seg_map, dtype=np.uint8)
    for class_id in target_classes:
        mask[seg_map == class_id] = 255

    # Resize mask back to original size if needed
    if work_size != original_size:
        mask_img = Image.fromarray(mask)
        mask_img = mask_img.resize(original_size, Image.Resampling.NEAREST)
        mask = np.array(mask_img)

    return mask


def segment_with_sam_auto(
    image: Image.Image,
    target: str = "building",
    min_area_ratio: float = 0.01,
    max_area_ratio: float = 0.9
) -> Optional[np.ndarray]:
    """
    Automatic segmentation using SAM.
    Generates all masks and filters by position/size for target.

    Args:
        image: Input PIL image
        target: "sky" (top), "ground" (bottom), "building" (center/large), "exterior" (not center)
        min_area_ratio: Minimum mask area as ratio of image
        max_area_ratio: Maximum mask area as ratio of image

    Returns:
        Binary mask as numpy array (0-255)
    """
    import torch

    model, processor = get_sam_model()
    if model is None:
        return None

    device = next(model.parameters()).device
    w, h = image.size
    total_pixels = w * h

    # Generate automatic masks using a grid of points
    # SAM works best with point prompts - we'll use a grid
    grid_size = 32
    points = []
    for y in range(grid_size // 2, h, h // grid_size):
        for x in range(grid_size // 2, w, w // grid_size):
            points.append([x, y])

    # Process in batches to avoid OOM
    all_masks = []
    batch_size = 64

    for i in range(0, len(points), batch_size):
        batch_points = points[i:i + batch_size]

        inputs = processor(
            image,
            input_points=[batch_points],
            return_tensors="pt"
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model(**inputs)

        masks = processor.image_processor.post_process_masks(
            outputs.pred_masks.cpu(),
            inputs["original_sizes"].cpu(),
            inputs["reshaped_input_sizes"].cpu()
        )[0]

        # Get best mask for each point (highest IoU score)
        scores = outputs.iou_scores.cpu().numpy()[0]
        for j, (mask_set, score_set) in enumerate(zip(masks, scores)):
            best_idx = np.argmax(score_set)
            mask = mask_set[best_idx].numpy()
            score = score_set[best_idx]
            if score > 0.7:  # Only keep confident masks
                all_masks.append({
                    'mask': mask,
                    'score': score,
                    'area': mask.sum(),
                    'point': batch_points[j]
                })

    if not all_masks:
        print("No masks generated")
        return None

    # Filter and combine masks based on target
    result_mask = np.zeros((h, w), dtype=np.uint8)

    if target == "sky":
        # Sky: masks in upper third of image
        for m in all_masks:
            mask = m['mask']
            # Check if mask center is in upper third
            ys, xs = np.where(mask)
            if len(ys) > 0:
                center_y = ys.mean() / h
                area_ratio = m['area'] / total_pixels
                if center_y < 0.4 and min_area_ratio < area_ratio < max_area_ratio:
                    result_mask[mask] = 255

    elif target == "ground":
        # Ground: masks in lower third
        for m in all_masks:
            mask = m['mask']
            ys, xs = np.where(mask)
            if len(ys) > 0:
                center_y = ys.mean() / h
                area_ratio = m['area'] / total_pixels
                if center_y > 0.6 and min_area_ratio < area_ratio < max_area_ratio:
                    result_mask[mask] = 255

    elif target == "building":
        # Building: largest mask(s) near center
        # Sort by area and take largest that's centered
        sorted_masks = sorted(all_masks, key=lambda x: x['area'], reverse=True)
        for m in sorted_masks[:5]:  # Check top 5 largest
            mask = m['mask']
            ys, xs = np.where(mask)
            if len(ys) > 0:
                center_x = xs.mean() / w
                center_y = ys.mean() / h
                # Is it roughly centered?
                if 0.2 < center_x < 0.8 and 0.2 < center_y < 0.8:
                    area_ratio = m['area'] / total_pixels
                    if area_ratio > 0.05:  # At least 5% of image
                        result_mask[mask] = 255

    elif target == "exterior":
        # Exterior: everything except building
        # First get building mask, then invert
        building_mask = segment_with_sam_auto(image, "building")
        if building_mask is not None:
            result_mask = 255 - building_mask
        else:
            # Fallback: sky + ground
            sky = segment_with_sam_auto(image, "sky")
            ground = segment_with_sam_auto(image, "ground")
            if sky is not None:
                result_mask = np.maximum(result_mask, sky)
            if ground is not None:
                result_mask = np.maximum(result_mask, ground)

    return result_mask


def segment_with_sam_points(
    image: Image.Image,
    points: List[Tuple[int, int]],
    labels: List[int] = None
) -> Optional[np.ndarray]:
    """
    Segment using SAM with specific point prompts.

    Args:
        image: Input PIL image
        points: List of (x, y) coordinates to segment
        labels: List of labels (1 = foreground, 0 = background). Default all foreground.

    Returns:
        Binary mask as numpy array (0-255)
    """
    import torch

    model, processor = get_sam_model()
    if model is None:
        return None

    device = next(model.parameters()).device

    if labels is None:
        labels = [1] * len(points)

    inputs = processor(
        image,
        input_points=[points],
        input_labels=[labels],
        return_tensors="pt"
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)

    masks = processor.image_processor.post_process_masks(
        outputs.pred_masks.cpu(),
        inputs["original_sizes"].cpu(),
        inputs["reshaped_input_sizes"].cpu()
    )[0]

    # Get the best mask (highest IoU score)
    scores = outputs.iou_scores.cpu().numpy()[0]
    best_idx = np.argmax(scores[0])
    mask = masks[0][best_idx].numpy()

    return (mask * 255).astype(np.uint8)


def sharpen_mask_edges(mask: np.ndarray, strength: float = 0.5) -> np.ndarray:
    """
    Sharpen mask edges by increasing contrast at boundaries.

    Args:
        mask: Input mask (0-255)
        strength: 0 = no sharpening, 1 = maximum sharpening (binary edges)

    Returns:
        Sharpened mask (0-255)
    """
    if strength <= 0:
        return mask

    # Normalize to 0-1
    normalized = mask.astype(np.float32) / 255.0

    # Apply sigmoid-like curve to sharpen transitions
    # Higher strength = steeper curve = sharper edges
    # We use a contrast enhancement centered at 0.5
    if strength >= 1.0:
        # Maximum sharpening - threshold to binary
        return ((normalized > 0.5) * 255).astype(np.uint8)

    # Sigmoid steepness based on strength (2-10 range)
    steepness = 2 + strength * 8

    # Apply sigmoid: transforms gradual edges to sharper ones
    sharpened = 1 / (1 + np.exp(-steepness * (normalized - 0.5)))

    # Scale back to 0-255
    return (sharpened * 255).astype(np.uint8)


def segment_image(
    image: Image.Image,
    target: str = "sky",
    method: str = "auto",
    feather: int = 10,
    sharpen: float = 0.0,
    points: List[Tuple[int, int]] = None
) -> Tuple[Optional[np.ndarray], str]:
    """
    Main segmentation function - tries different methods.

    Args:
        image: Input PIL image
        target: "sky", "building", "ground", "vegetation", "exterior"
        method: "auto" (pick best), "sam", "oneformer", "heuristic"
        feather: Gaussian blur radius for mask edges
        sharpen: Edge sharpening strength (0 = none, 1 = binary edges)
        points: Optional click points for SAM point-based segmentation

    Returns:
        Tuple of (mask array 0-255, method used)
    """
    from scipy.ndimage import gaussian_filter

    mask = None
    method_used = method

    # If points provided, use SAM point-based
    if points and len(points) > 0:
        print(f"Using SAM with {len(points)} point(s)")
        mask = segment_with_sam_points(image, points)
        method_used = "sam_points"

    # Try OneFormer first (best semantic understanding)
    elif method in ["auto", "oneformer"]:
        print(f"Trying OneFormer for {target}...")
        mask = segment_with_oneformer(image, target)
        if mask is not None:
            method_used = "oneformer"
        elif method == "oneformer":
            return None, "oneformer_failed"

    # Try SAM automatic
    if mask is None and method in ["auto", "sam"]:
        print(f"Trying SAM automatic for {target}...")
        mask = segment_with_sam_auto(image, target)
        if mask is not None:
            method_used = "sam_auto"
        elif method == "sam":
            return None, "sam_failed"

    # Fallback to heuristic
    if mask is None:
        print(f"Using heuristic segmentation for {target}...")
        mask = segment_heuristic(image, target)
        method_used = "heuristic"

    # Apply feathering first (soft edges)
    if mask is not None and feather > 0:
        mask = gaussian_filter(mask.astype(float), sigma=feather)
        mask = (mask * 255 / mask.max()).astype(np.uint8) if mask.max() > 0 else mask.astype(np.uint8)

    # Then apply edge sharpening if requested
    if mask is not None and sharpen > 0:
        mask = sharpen_mask_edges(mask, sharpen)

    return mask, method_used


def segment_heuristic(
    image: Image.Image,
    target: str = "sky"
) -> np.ndarray:
    """
    Fallback heuristic segmentation (original method).
    Uses depth estimation + color/position analysis.
    """
    import numpy as np

    w, h = image.size
    img_arr = np.array(image).astype(np.float32) / 255.0

    # Position arrays
    y_pos = np.linspace(0, 1, h)[:, np.newaxis]
    y_pos = np.tile(y_pos, (1, w))

    x_pos = np.linspace(0, 1, w)[np.newaxis, :]
    x_pos = np.tile(x_pos, (h, 1))

    # Color features
    brightness = np.mean(img_arr, axis=2)
    r, g, b = img_arr[:, :, 0], img_arr[:, :, 1], img_arr[:, :, 2]

    max_c = np.max(img_arr, axis=2)
    min_c = np.min(img_arr, axis=2)
    saturation = (max_c - min_c) / (max_c + 1e-6)

    if target == "sky":
        # Sky: upper, bright, low saturation, blue-ish
        upper_weight = 1.0 - y_pos
        bright_weight = brightness ** 0.5
        low_sat_weight = 1.0 - saturation
        blue_tint = (b > r * 0.85) & (b > g * 0.75)

        score = (
            upper_weight * 0.4 +
            bright_weight * 0.3 +
            low_sat_weight * 0.2 +
            blue_tint.astype(float) * 0.1
        )
        mask = (score > 0.5).astype(np.uint8) * 255

    elif target == "building":
        # Building: center, mid-brightness, has color/texture
        center_x = 1.0 - np.abs(x_pos - 0.5) * 2
        center_y = 1.0 - np.abs(y_pos - 0.5) * 2
        center_weight = center_x * center_y

        mid_bright = 1.0 - np.abs(brightness - 0.5) * 2
        has_color = saturation * 0.5 + 0.5

        score = (
            center_weight * 0.4 +
            mid_bright * 0.3 +
            has_color * 0.3
        )
        mask = (score > 0.45).astype(np.uint8) * 255

        # Keep largest connected component
        from scipy.ndimage import label, binary_fill_holes
        labeled, num = label(mask)
        if num > 0:
            sizes = np.bincount(labeled.ravel())
            sizes[0] = 0
            largest = sizes.argmax()
            mask = ((labeled == largest) * 255).astype(np.uint8)
            mask = (binary_fill_holes(mask > 0) * 255).astype(np.uint8)

    elif target == "ground":
        # Ground: lower, darker, green/brown
        lower_weight = y_pos
        darker = 1.0 - brightness
        green_brown = ((g > r * 0.8) | ((r > b) & (g > b * 0.7)))

        score = (
            lower_weight * 0.5 +
            darker * 0.2 +
            green_brown.astype(float) * 0.3
        )
        mask = (score > 0.55).astype(np.uint8) * 255

    elif target in ["exterior", "environment"]:
        # Exterior = inverse of building
        building = segment_heuristic(image, "building")
        from scipy.ndimage import binary_dilation
        building_dilated = binary_dilation(building > 0, iterations=10)
        mask = ((~building_dilated) * 255).astype(np.uint8)

    else:
        mask = np.zeros((h, w), dtype=np.uint8)

    return mask


def unload_models():
    """Unload all models to free memory."""
    global _sam_model, _sam_processor, _oneformer_model, _oneformer_processor

    _sam_model = None
    _sam_processor = None
    _oneformer_model = None
    _oneformer_processor = None

    gc.collect()

    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except:
        pass

    print("Segmentation models unloaded")


# Quick test
if __name__ == "__main__":
    from pathlib import Path

    test_image = Path(r"C:\Users\jerro\Desktop\channel_test\base.png")
    if test_image.exists():
        img = Image.open(test_image)

        print("\nTesting segmentation...")
        for target in ["sky", "building", "ground"]:
            mask, method = segment_image(img, target, method="auto", feather=5)
            if mask is not None:
                print(f"  {target}: {method}, coverage={mask.mean()/255*100:.1f}%")
            else:
                print(f"  {target}: FAILED")
    else:
        print("No test image found")
