# height_generator.py
"""
Generate height/displacement maps from PBR materials using hybrid approach:
1. If normal map exists: integrate normals to reconstruct height
2. Fall back to Depth Anything v2 on diffuse texture
3. Optional ControlNet refinement for enhanced detail
"""

import numpy as np
from PIL import Image
from pathlib import Path
from scipy.ndimage import gaussian_filter
from scipy.fft import fft2, ifft2, fftfreq
import torch

print("=== HEIGHT GENERATOR MODULE LOADED ===")


def integrate_normals_to_height(normal_map: np.ndarray, iterations: int = 500) -> np.ndarray:
    """
    Reconstruct height field from normal map using Frankot-Chellappa algorithm.

    This method solves for the height field that best matches the given gradients
    in a least-squares sense using Fourier transforms.

    Args:
        normal_map: RGB normal map (H, W, 3) with values 0-255
                   Convention: R=X, G=Y, B=Z (tangent space)
        iterations: Not used for FFT method, kept for API compatibility

    Returns:
        Height map as float array (0-1 range)
    """
    # Convert from 0-255 to -1,1 range
    # Normal maps: 128 = 0, 0 = -1, 255 = 1
    normals = normal_map.astype(np.float32) / 255.0 * 2.0 - 1.0

    nx = normals[:, :, 0]  # X component (dh/dx direction)
    ny = normals[:, :, 1]  # Y component (dh/dy direction)
    nz = normals[:, :, 2]  # Z component (up)

    # Avoid division by zero
    nz = np.maximum(nz, 0.001)

    # Compute gradients: for a surface z=h(x,y), normal = (-dh/dx, -dh/dy, 1) normalized
    # So: dh/dx = -nx/nz, dh/dy = -ny/nz
    p = -nx / nz  # dh/dx
    q = -ny / nz  # dh/dy

    # Frankot-Chellappa integration in frequency domain
    h, w = p.shape

    # Create frequency coordinates
    fy = fftfreq(h).reshape(-1, 1)
    fx = fftfreq(w).reshape(1, -1)

    # FFT of gradients
    P = fft2(p)
    Q = fft2(q)

    # Frequency domain integration
    # H = (i*fx*P + i*fy*Q) / (fx^2 + fy^2)
    # Avoid division by zero at DC component
    denom = (fx ** 2 + fy ** 2)
    denom[0, 0] = 1.0  # Avoid div by zero

    # Combine gradients in frequency domain
    H = (1j * fx * P + 1j * fy * Q) / denom
    H[0, 0] = 0  # Set DC component to zero (mean height)

    # Inverse FFT to get height
    height = np.real(ifft2(H))

    # Normalize to 0-1 range
    height = height - height.min()
    if height.max() > 0:
        height = height / height.max()

    return height.astype(np.float32)


def height_from_diffuse(diffuse_path: str, device: str = "cuda") -> np.ndarray:
    """
    Estimate height from diffuse/albedo texture using Depth Anything v2.

    The AI model estimates depth from visual cues (shadows, texture patterns).
    We invert this to get height (raised areas appear lighter/closer).

    Args:
        diffuse_path: Path to diffuse/albedo texture
        device: "cuda" or "cpu"

    Returns:
        Height map as float array (0-1 range)
    """
    from image_channels import get_image_extractor

    extractor = get_image_extractor()

    # Load diffuse image
    diffuse = Image.open(diffuse_path).convert("RGB")

    # Estimate depth
    depth = extractor.estimate_depth(diffuse)

    # Invert: depth map has near=1, far=0
    # For height maps we typically want: high=1, low=0
    # For materials, the "raised" areas appear closer (higher depth value)
    # So height = depth (no inversion needed for typical materials)
    height = depth

    return height


def height_from_normal_map(normal_path: str) -> np.ndarray:
    """
    Reconstruct height from a normal map file.

    Args:
        normal_path: Path to normal map image

    Returns:
        Height map as float array (0-1 range)
    """
    normal_img = Image.open(normal_path).convert("RGB")
    normal_array = np.array(normal_img)

    return integrate_normals_to_height(normal_array)


def generate_height_map(
    material_path: str,
    output_path: str = None,
    method: str = "hybrid",
    blur_radius: float = 1.0,
    contrast: float = 1.0,
    invert: bool = False
) -> str:
    """
    Generate a height map for a material using the hybrid approach.

    Args:
        material_path: Path to material directory containing textures
        output_path: Where to save the height map (default: material_path/height.png)
        method: "hybrid" (auto-detect), "normal" (from normal map), "diffuse" (AI depth)
        blur_radius: Gaussian blur to smooth the result
        contrast: Multiply height values to increase/decrease contrast
        invert: Flip height values (swap peaks and valleys)

    Returns:
        Path to generated height map
    """
    material_dir = Path(material_path)

    if output_path is None:
        output_path = material_dir / "height.png"
    else:
        output_path = Path(output_path)

    # Find available textures
    normal_path = None
    diffuse_path = None

    # Check for normal map (various naming conventions)
    for pattern in ["*normal*", "*Normal*", "*_n.*", "*_N.*", "*_norm.*"]:
        matches = list(material_dir.glob(pattern))
        if matches:
            normal_path = matches[0]
            break

    # Check for diffuse/albedo (various naming conventions)
    for pattern in ["*diffuse*", "*Diffuse*", "*albedo*", "*Albedo*", "*_d.*", "*_D.*", "*color*", "*Color*", "*basecolor*"]:
        matches = list(material_dir.glob(pattern))
        if matches:
            diffuse_path = matches[0]
            break

    print(f"[HeightGen] Material: {material_dir.name}")
    print(f"[HeightGen] Normal map: {normal_path}")
    print(f"[HeightGen] Diffuse map: {diffuse_path}")
    print(f"[HeightGen] Method: {method}")

    height = None

    # Hybrid approach: prefer normal map if available
    if method == "hybrid":
        if normal_path and normal_path.exists():
            print("[HeightGen] Using normal map integration...")
            height = height_from_normal_map(str(normal_path))
        elif diffuse_path and diffuse_path.exists():
            print("[HeightGen] Using Depth Anything on diffuse...")
            height = height_from_diffuse(str(diffuse_path))
        else:
            raise ValueError(f"No normal or diffuse map found in {material_dir}")

    elif method == "normal":
        if not normal_path or not normal_path.exists():
            raise ValueError(f"No normal map found in {material_dir}")
        height = height_from_normal_map(str(normal_path))

    elif method == "diffuse":
        if not diffuse_path or not diffuse_path.exists():
            raise ValueError(f"No diffuse map found in {material_dir}")
        height = height_from_diffuse(str(diffuse_path))

    else:
        raise ValueError(f"Unknown method: {method}")

    # Post-processing
    if blur_radius > 0:
        height = gaussian_filter(height, sigma=blur_radius)

    # Apply contrast
    if contrast != 1.0:
        mean = height.mean()
        height = (height - mean) * contrast + mean
        height = np.clip(height, 0, 1)

    # Invert if requested
    if invert:
        height = 1.0 - height

    # Normalize to full range
    height = height - height.min()
    if height.max() > 0:
        height = height / height.max()

    # Save as 16-bit PNG for maximum precision
    height_16bit = (height * 65535).astype(np.uint16)
    height_img = Image.fromarray(height_16bit, mode='I;16')

    output_path.parent.mkdir(parents=True, exist_ok=True)
    height_img.save(str(output_path))

    print(f"[HeightGen] Saved: {output_path}")

    return str(output_path)


def generate_height_map_from_image(
    image: Image.Image,
    normal_image: Image.Image = None,
    method: str = "hybrid",
    blur_radius: float = 1.0,
    contrast: float = 1.0,
    invert: bool = False
) -> Image.Image:
    """
    Generate height map from PIL images directly (for API use).

    Args:
        image: Diffuse/albedo image
        normal_image: Optional normal map image
        method: "hybrid", "normal", or "diffuse"
        blur_radius: Gaussian blur radius
        contrast: Height contrast multiplier
        invert: Invert height values

    Returns:
        Height map as PIL Image (16-bit grayscale)
    """
    height = None

    if method == "hybrid":
        if normal_image is not None:
            print("[HeightGen] Using normal map integration...")
            normal_array = np.array(normal_image.convert("RGB"))
            height = integrate_normals_to_height(normal_array)
        else:
            print("[HeightGen] Using Depth Anything on diffuse...")
            from image_channels import get_image_extractor
            extractor = get_image_extractor()
            height = extractor.estimate_depth(image)

    elif method == "normal":
        if normal_image is None:
            raise ValueError("Normal image required for 'normal' method")
        normal_array = np.array(normal_image.convert("RGB"))
        height = integrate_normals_to_height(normal_array)

    elif method == "diffuse":
        from image_channels import get_image_extractor
        extractor = get_image_extractor()
        height = extractor.estimate_depth(image)

    # Post-processing
    if blur_radius > 0:
        height = gaussian_filter(height, sigma=blur_radius)

    if contrast != 1.0:
        mean = height.mean()
        height = (height - mean) * contrast + mean
        height = np.clip(height, 0, 1)

    if invert:
        height = 1.0 - height

    # Normalize
    height = height - height.min()
    if height.max() > 0:
        height = height / height.max()

    # Return as 16-bit image
    height_16bit = (height * 65535).astype(np.uint16)
    return Image.fromarray(height_16bit, mode='I;16')
