# style_harmonizer.py
# Post-processing for matching generated environment to architectural render style

import numpy as np
from PIL import Image, ImageFilter, ImageEnhance
from typing import Optional, Tuple
import colorsys

print("=== STYLE HARMONIZER MODULE LOADED ===")


def extract_color_palette(image: Image.Image, mask: Image.Image = None, n_colors: int = 8) -> list:
    """
    Extract dominant colors from an image region.

    Args:
        image: Source image
        mask: Optional mask (black = sample from here)
        n_colors: Number of colors to extract

    Returns:
        List of (R, G, B) tuples
    """
    img_np = np.array(image.convert('RGB'))

    if mask is not None:
        mask_np = np.array(mask.convert('L'))
        # Sample from masked area (black = building)
        building_pixels = img_np[mask_np < 128]
    else:
        building_pixels = img_np.reshape(-1, 3)

    if len(building_pixels) == 0:
        return [(128, 128, 128)]

    # Simple k-means-like clustering using numpy
    # Use random sampling for speed
    n_samples = min(10000, len(building_pixels))
    indices = np.random.choice(len(building_pixels), n_samples, replace=False)
    samples = building_pixels[indices]

    # Quantize to reduce colors
    quantized = (samples // 32) * 32
    unique, counts = np.unique(quantized, axis=0, return_counts=True)

    # Sort by frequency
    sorted_indices = np.argsort(-counts)
    top_colors = unique[sorted_indices[:n_colors]]

    return [tuple(c) for c in top_colors]


def get_color_statistics(image: Image.Image, mask: Image.Image = None) -> dict:
    """
    Get color statistics from an image region.

    Returns:
        Dict with mean, std, histogram for RGB and HSV
    """
    img_np = np.array(image.convert('RGB')).astype(np.float32)

    if mask is not None:
        mask_np = np.array(mask.convert('L'))
        # Sample from masked area
        mask_bool = mask_np < 128
        pixels = img_np[mask_bool]
    else:
        pixels = img_np.reshape(-1, 3)

    if len(pixels) == 0:
        return {
            'mean_rgb': (128, 128, 128),
            'std_rgb': (50, 50, 50),
            'mean_hsv': (0.5, 0.5, 0.5),
            'brightness': 128
        }

    # RGB stats
    mean_rgb = tuple(pixels.mean(axis=0).astype(int))
    std_rgb = tuple(pixels.std(axis=0).astype(int))

    # Brightness
    brightness = pixels.mean()

    # Convert mean to HSV
    r, g, b = [x / 255.0 for x in mean_rgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)

    return {
        'mean_rgb': mean_rgb,
        'std_rgb': std_rgb,
        'mean_hsv': (h, s, v),
        'brightness': brightness
    }


def harmonize_colors(
    result: Image.Image,
    base: Image.Image,
    mask: Image.Image,
    strength: float = 0.6
) -> Image.Image:
    """
    Match colors of generated area to the building's color palette.

    This reduces the "photorealistic vs rendered" disconnect by
    pulling the generated environment colors toward the building's palette.

    Args:
        result: Inpainted result image
        base: Original base image (with building)
        mask: Inpainting mask (white = generated area)
        strength: How much to harmonize (0-1)

    Returns:
        Color-harmonized image
    """
    result_np = np.array(result.convert('RGB')).astype(np.float32)
    base_np = np.array(base.convert('RGB')).astype(np.float32)
    mask_np = np.array(mask.convert('L')).astype(np.float32) / 255.0

    # Get building stats (from non-masked area)
    inverted_mask = Image.fromarray(((1 - mask_np) * 255).astype(np.uint8))
    building_stats = get_color_statistics(base, inverted_mask)

    # Get generated area stats
    generated_stats = get_color_statistics(result, mask)

    # Calculate adjustment factors
    target_brightness = building_stats['brightness']
    current_brightness = generated_stats['brightness']

    # Only process masked (generated) area
    mask_3d = mask_np[:, :, np.newaxis]

    # 1. Brightness adjustment - match the render's overall brightness
    if current_brightness > 0:
        brightness_factor = target_brightness / current_brightness
        brightness_factor = np.clip(brightness_factor, 0.7, 1.4)  # Limit adjustment
        adjusted = result_np * (1 + (brightness_factor - 1) * strength * mask_3d)
    else:
        adjusted = result_np

    # 2. Saturation reduction - renders are often less saturated than photos
    target_sat = building_stats['mean_hsv'][1]
    if target_sat < 0.5:  # If building is desaturated
        # Desaturate generated area slightly
        gray = adjusted.mean(axis=2, keepdims=True)
        desat_factor = 0.15 * strength  # Subtle desaturation
        adjusted = adjusted * (1 - desat_factor * mask_3d) + gray * (desat_factor * mask_3d)

    # 3. Color temperature matching
    building_warmth = (building_stats['mean_rgb'][0] - building_stats['mean_rgb'][2]) / 255.0
    generated_warmth = (generated_stats['mean_rgb'][0] - generated_stats['mean_rgb'][2]) / 255.0
    warmth_diff = building_warmth - generated_warmth

    # Apply subtle warmth adjustment
    warmth_adjust = warmth_diff * strength * 20  # Scale factor
    adjusted[:, :, 0] += warmth_adjust * mask_np  # Add red
    adjusted[:, :, 2] -= warmth_adjust * mask_np  # Reduce blue

    # Clip to valid range
    adjusted = np.clip(adjusted, 0, 255).astype(np.uint8)

    return Image.fromarray(adjusted)


def extract_render_essence(base: Image.Image, mask: Image.Image) -> dict:
    """
    Extract the lighting/color ESSENCE from the building render.

    This captures the aesthetic qualities without the content:
    - Color temperature (warm/cool)
    - Shadow character (lifted or deep)
    - Saturation level
    - Overall brightness/exposure

    Returns:
        Dict with essence properties
    """
    base_np = np.array(base.convert('RGB')).astype(np.float32)
    mask_np = np.array(mask.convert('L'))

    # Sample from building area (non-masked)
    building_pixels = base_np[mask_np < 128]

    if len(building_pixels) == 0:
        return {
            'warmth': 0,
            'shadow_floor': 20,
            'highlight_ceiling': 245,
            'saturation': 0.5
        }

    # Color temperature (R-B difference normalized)
    warmth = (building_pixels[:, 0].mean() - building_pixels[:, 2].mean()) / 255.0

    # Shadow floor (5th percentile - how lifted are the darks)
    luminance = 0.299 * building_pixels[:, 0] + 0.587 * building_pixels[:, 1] + 0.114 * building_pixels[:, 2]
    shadow_floor = np.percentile(luminance, 5)

    # Highlight ceiling (95th percentile - how compressed are highlights)
    highlight_ceiling = np.percentile(luminance, 95)

    # Saturation estimate
    max_rgb = building_pixels.max(axis=1)
    min_rgb = building_pixels.min(axis=1)
    sat = np.where(max_rgb > 0, (max_rgb - min_rgb) / max_rgb, 0)
    saturation = sat.mean()

    return {
        'warmth': float(warmth),
        'shadow_floor': float(shadow_floor),
        'highlight_ceiling': float(highlight_ceiling),
        'saturation': float(saturation)
    }


def apply_render_style(
    result: Image.Image,
    base: Image.Image,
    mask: Image.Image,
    style_strength: float = 0.4
) -> Image.Image:
    """
    Apply architectural rendering ESSENCE to generated area.

    This transfers the lighting/color character of the render without
    copying its content. Focuses on:
    - Matching shadow lift (renders don't have pure blacks)
    - Matching highlight softness
    - Matching color temperature (warm/cool tint)
    - Matching saturation level

    Does NOT:
    - Blur or reduce contrast
    - Copy textures or patterns
    - Change the actual content

    Args:
        result: Inpainted result image
        base: Original base image (with building)
        mask: Inpainting mask (white = generated area)
        style_strength: How much to apply (0-1)

    Returns:
        Stylized image with matched lighting character
    """
    result_np = np.array(result.convert('RGB')).astype(np.float32)
    mask_np = np.array(mask.convert('L')).astype(np.float32) / 255.0
    mask_3d = mask_np[:, :, np.newaxis]

    # Extract the render's lighting essence
    essence = extract_render_essence(base, mask)

    # Get generated area stats for comparison
    gen_pixels = result_np[mask_np > 0.5]
    if len(gen_pixels) == 0:
        return result

    gen_luminance = 0.299 * gen_pixels[:, 0] + 0.587 * gen_pixels[:, 1] + 0.114 * gen_pixels[:, 2]
    gen_shadow = np.percentile(gen_luminance, 5)
    gen_highlight = np.percentile(gen_luminance, 95)
    gen_warmth = (gen_pixels[:, 0].mean() - gen_pixels[:, 2].mean()) / 255.0

    styled = result_np.copy()

    # 1. Shadow lift - match the render's lifted blacks
    if gen_shadow < essence['shadow_floor']:
        lift_amount = (essence['shadow_floor'] - gen_shadow) * style_strength
        # Apply lift more to darker pixels
        darkness = 1.0 - (styled / 255.0)
        styled = styled + lift_amount * darkness * mask_3d

    # 2. Highlight softening - match the render's compressed highlights
    if gen_highlight > essence['highlight_ceiling']:
        compress_amount = (gen_highlight - essence['highlight_ceiling']) * style_strength * 0.5
        # Apply compression more to brighter pixels
        brightness = styled / 255.0
        highlight_factor = np.clip((brightness - 0.7) / 0.3, 0, 1)
        styled = styled - compress_amount * highlight_factor * mask_3d

    # 3. Color temperature match - subtle warm/cool shift
    warmth_diff = essence['warmth'] - gen_warmth
    temp_adjust = warmth_diff * style_strength * 15  # Subtle adjustment
    styled[:, :, 0] += temp_adjust * mask_np  # Red channel
    styled[:, :, 2] -= temp_adjust * mask_np  # Blue channel

    # 4. Saturation matching (very subtle)
    if essence['saturation'] < 0.4:  # If render is desaturated
        gray = styled.mean(axis=2, keepdims=True)
        desat = style_strength * 0.1  # Very subtle
        styled = styled * (1 - desat * mask_3d) + gray * (desat * mask_3d)

    styled = np.clip(styled, 0, 255).astype(np.uint8)
    return Image.fromarray(styled)


def blend_edges(
    result: Image.Image,
    base: Image.Image,
    mask: Image.Image,
    blend_width: int = 30,
    iterations: int = 2
) -> Image.Image:
    """
    Additional edge blending at mask boundary for seamless transitions.

    Uses multi-scale blending and color matching at the boundary.

    Args:
        result: Inpainted result
        base: Original image
        mask: Inpainting mask
        blend_width: Pixels to blend at edge
        iterations: Number of blending passes

    Returns:
        Edge-blended image
    """
    from scipy import ndimage

    result_np = np.array(result.convert('RGB')).astype(np.float32)
    base_np = np.array(base.convert('RGB')).astype(np.float32)
    mask_np = np.array(mask.convert('L')).astype(np.float32) / 255.0

    # Find edge region
    dilated = ndimage.binary_dilation(mask_np > 0.5, iterations=blend_width)
    eroded = ndimage.binary_erosion(mask_np > 0.5, iterations=blend_width)
    edge_region = dilated.astype(float) - eroded.astype(float)
    edge_region = np.clip(edge_region, 0, 1)

    # Create smooth gradient in edge region
    edge_gradient = ndimage.gaussian_filter(edge_region, sigma=blend_width / 3)
    edge_gradient = edge_gradient[:, :, np.newaxis]

    # Multi-scale blending
    blended = result_np.copy()

    for i in range(iterations):
        # Sample colors from both sides of boundary
        scale = blend_width // (i + 1)

        # Blur both images at this scale
        result_blur = ndimage.gaussian_filter(blended, sigma=(scale, scale, 0))
        base_blur = ndimage.gaussian_filter(base_np, sigma=(scale, scale, 0))

        # Blend in edge region
        blend_factor = edge_gradient * (0.5 / (i + 1))
        blended = blended * (1 - blend_factor) + (
            result_blur * 0.5 + base_blur * 0.5
        ) * blend_factor

    # Final edge color matching
    # Sample colors just inside and outside the mask at the boundary
    boundary = (edge_region > 0.3) & (edge_region < 0.7)
    if boundary.any():
        # Match colors at boundary
        inside_mask = (mask_np > 0.5) & boundary
        outside_mask = (mask_np <= 0.5) & boundary

        if inside_mask.any() and outside_mask.any():
            inside_color = blended[inside_mask].mean(axis=0)
            outside_color = base_np[outside_mask].mean(axis=0)

            # Subtle shift toward outside color at boundary
            color_diff = outside_color - inside_color
            adjustment = color_diff * 0.3  # Subtle

            # Apply adjustment at boundary (fade out toward center of generated area)
            boundary_weight = (1 - np.abs(mask_np - 0.5) * 2) * (edge_region > 0)
            boundary_weight = boundary_weight[:, :, np.newaxis]
            blended = blended + adjustment * boundary_weight

    blended = np.clip(blended, 0, 255).astype(np.uint8)

    return Image.fromarray(blended)


def full_harmonization(
    result: Image.Image,
    base: Image.Image,
    mask: Image.Image,
    color_strength: float = 0.5,
    style_strength: float = 0.3,
    edge_blend_width: int = 25
) -> Image.Image:
    """
    Complete harmonization pipeline.

    Applies color matching, render style, and edge blending.

    Args:
        result: Inpainted image
        base: Original base image
        mask: Inpainting mask
        color_strength: Color harmonization strength (0-1)
        style_strength: Render style strength (0-1)
        edge_blend_width: Edge blend width in pixels

    Returns:
        Fully harmonized image
    """
    print(f"Harmonizing: color={color_strength}, style={style_strength}, edge={edge_blend_width}px")

    # Step 1: Color harmonization
    harmonized = harmonize_colors(result, base, mask, strength=color_strength)

    # Step 2: Apply render style
    styled = apply_render_style(harmonized, base, mask, style_strength=style_strength)

    # Step 3: Edge blending
    final = blend_edges(styled, base, mask, blend_width=edge_blend_width)

    print("Harmonization complete")
    return final


# Architectural rendering prompt templates
# IMPORTANT: Negative prompts must explicitly exclude buildings/architecture
# to prevent model from generating more structures when it sees the existing building

# Core negative terms to ALWAYS include - prevents generating buildings
ARCH_NEGATIVE_CORE = (
    "buildings, architecture, concrete walls, glass facade, windows, doors, "
    "structure, urban buildings, skyscrapers, houses, construction, man-made structures, "
    "apartment buildings, office buildings, modern architecture, building exterior"
)

# Photorealism negatives - keeps output in render style
PHOTO_NEGATIVE = (
    "photorealistic, photograph, camera shot, lens flare, film grain, "
    "HDR photography, DSLR, realistic photo, stock photo"
)

ARCH_RENDER_PROMPTS = {
    'default': {
        'prompt': 'natural landscape environment, trees and vegetation, blue sky with soft clouds, green grass lawn, 3D render lighting style, soft diffuse shadows, ambient occlusion, clean professional visualization',
        'negative': f'{ARCH_NEGATIVE_CORE}, {PHOTO_NEGATIVE}, harsh shadows, oversaturated colors'
    },
    'sunny': {
        'prompt': 'sunny natural landscape, warm daylight, blue sky gradient, white clouds, green trees and shrubs, manicured lawn, soft shadows, 3D render style lighting',
        'negative': f'{ARCH_NEGATIVE_CORE}, {PHOTO_NEGATIVE}, harsh contrast, dark shadows'
    },
    'overcast': {
        'prompt': 'overcast sky environment, soft diffuse natural light, even illumination, green landscape, trees in soft light, 3D render style, no harsh shadows',
        'negative': f'{ARCH_NEGATIVE_CORE}, {PHOTO_NEGATIVE}, sun glare, dramatic lighting, strong shadows'
    },
    'dusk': {
        'prompt': 'evening dusk landscape, warm golden hour light, gradient sky orange to purple, tree silhouettes, soft ambient glow, 3D visualization style',
        'negative': f'{ARCH_NEGATIVE_CORE}, {PHOTO_NEGATIVE}, harsh contrast, noise, grain'
    },
    'minimal': {
        'prompt': 'minimal clean environment, simple sky gradient, subtle ground plane, sparse vegetation, clean professional 3D render style',
        'negative': f'{ARCH_NEGATIVE_CORE}, {PHOTO_NEGATIVE}, busy background, complex details, cluttered'
    },
    'forest': {
        'prompt': 'forest environment, tall trees, natural woodland, dappled light through leaves, forest floor, 3D render style soft lighting, lush vegetation',
        'negative': f'{ARCH_NEGATIVE_CORE}, {PHOTO_NEGATIVE}, dead trees, harsh shadows'
    },
    'mountain': {
        'prompt': 'mountain landscape background, distant peaks, alpine meadow, pine trees, clear sky, natural environment, 3D visualization lighting',
        'negative': f'{ARCH_NEGATIVE_CORE}, {PHOTO_NEGATIVE}, snow, harsh weather'
    }
}


def get_arch_prompt(style: str = 'default') -> Tuple[str, str]:
    """Get architectural rendering prompt and negative prompt."""
    preset = ARCH_RENDER_PROMPTS.get(style, ARCH_RENDER_PROMPTS['default'])
    return preset['prompt'], preset['negative']
