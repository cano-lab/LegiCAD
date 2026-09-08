# image_channels.py
"""
Extract channels (depth, normals, edges, AO) from a 2D image using AI.
No 3D mesh required - just a rendered image or screenshot.
"""

import torch
import numpy as np
from PIL import Image, ImageFilter
from pathlib import Path
import cv2

print("=== IMAGE CHANNELS MODULE LOADED ===")


class ImageChannelExtractor:
    """Extract depth, normals, edges, AO from a single 2D image using AI."""

    def __init__(self):
        self.depth_model = None
        self.depth_processor = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"ImageChannelExtractor initialized (device={self.device})")

    def _load_depth_model(self):
        """Lazy load Depth Anything v2 model."""
        if self.depth_model is not None:
            return

        print("Loading Depth Anything v2 model...")
        try:
            from transformers import AutoImageProcessor, AutoModelForDepthEstimation

            # Depth Anything v2 - excellent quality
            model_id = "depth-anything/Depth-Anything-V2-Small-hf"

            self.depth_processor = AutoImageProcessor.from_pretrained(model_id)
            self.depth_model = AutoModelForDepthEstimation.from_pretrained(model_id)
            self.depth_model.to(self.device)
            self.depth_model.eval()

            print("Depth Anything v2 loaded!")

        except Exception as e:
            print(f"Failed to load Depth Anything: {e}")
            print("Trying MiDaS fallback...")

            try:
                # Fallback to MiDaS
                self.depth_model = torch.hub.load("intel-isl/MiDaS", "MiDaS_small")
                self.depth_model.to(self.device)
                self.depth_model.eval()

                midas_transforms = torch.hub.load("intel-isl/MiDaS", "transforms")
                self.depth_processor = midas_transforms.small_transform
                print("MiDaS loaded as fallback!")

            except Exception as e2:
                print(f"MiDaS also failed: {e2}")
                raise RuntimeError("Could not load any depth estimation model")

    def estimate_depth(self, image: Image.Image) -> np.ndarray:
        """
        Estimate depth from a single image.

        Returns:
            Depth map as numpy array (0-1 range, 0=far, 1=near)
        """
        self._load_depth_model()

        image_rgb = image.convert("RGB")
        w, h = image_rgb.size

        with torch.no_grad():
            if hasattr(self.depth_processor, 'preprocess'):
                # Transformers-style (Depth Anything)
                inputs = self.depth_processor(images=image_rgb, return_tensors="pt")
                inputs = {k: v.to(self.device) for k, v in inputs.items()}

                outputs = self.depth_model(**inputs)
                depth = outputs.predicted_depth

                # Interpolate to original size
                depth = torch.nn.functional.interpolate(
                    depth.unsqueeze(1),
                    size=(h, w),
                    mode="bicubic",
                    align_corners=False
                ).squeeze()

            else:
                # MiDaS-style
                input_tensor = self.depth_processor(np.array(image_rgb)).to(self.device)
                depth = self.depth_model(input_tensor)

                depth = torch.nn.functional.interpolate(
                    depth.unsqueeze(1),
                    size=(h, w),
                    mode="bicubic",
                    align_corners=False
                ).squeeze()

            depth_np = depth.cpu().numpy()

        # Normalize to 0-1 range
        depth_min = depth_np.min()
        depth_max = depth_np.max()
        if depth_max - depth_min > 0:
            depth_np = (depth_np - depth_min) / (depth_max - depth_min)
        else:
            depth_np = np.zeros_like(depth_np)

        return depth_np

    def depth_to_normals(self, depth: np.ndarray, strength: float = 10.0) -> np.ndarray:
        """
        Derive surface normals from depth map using gradients.

        Args:
            depth: Depth map (0-1 range)
            strength: Multiplier for gradients (higher = more pronounced normals)

        Returns:
            Normals as RGB numpy array (0-255)
        """
        from scipy.ndimage import sobel, gaussian_filter

        # Smooth depth slightly to reduce noise
        depth_smooth = gaussian_filter(depth, sigma=1.0)

        # Use Sobel filter for better gradient estimation
        zx = sobel(depth_smooth, axis=1, mode='reflect') * strength
        zy = sobel(depth_smooth, axis=0, mode='reflect') * strength

        # Create normal vectors (Z points toward camera)
        normal = np.dstack((-zx, -zy, np.ones_like(depth)))

        # Normalize to unit length
        n = np.linalg.norm(normal, axis=2, keepdims=True)
        n = np.where(n > 0, n, 1)
        normal = normal / n

        # Convert from [-1,1] to [0,255] for RGB
        # Standard normal map encoding: R=X, G=Y, B=Z
        normal_rgb = ((normal + 1) / 2 * 255).astype(np.uint8)

        return normal_rgb

    def extract_edges(self, image: Image.Image, depth: np.ndarray = None) -> np.ndarray:
        """
        Extract edges using Canny edge detection on both image and depth.

        Returns:
            Edge map as numpy array (0-255)
        """
        # Convert to grayscale
        gray = np.array(image.convert("L"))

        # Canny edge detection on image
        edges_img = cv2.Canny(gray, 50, 150)

        # If we have depth, also get edges from depth
        if depth is not None:
            depth_uint8 = (depth * 255).astype(np.uint8)
            edges_depth = cv2.Canny(depth_uint8, 30, 100)

            # Combine edges
            edges = np.maximum(edges_img, edges_depth)
        else:
            edges = edges_img

        # Invert so edges are dark (like architectural line drawings)
        edges = 255 - edges

        return edges

    def estimate_ao(self, depth: np.ndarray, strength: float = 1.0) -> np.ndarray:
        """
        Approximate ambient occlusion from depth map.
        Uses local depth variance to estimate occlusion.

        Returns:
            AO map as numpy array (0-255, 255=no occlusion)
        """
        from scipy.ndimage import uniform_filter, gaussian_filter

        # Compute local depth statistics
        depth_mean = uniform_filter(depth, size=15)
        depth_sq_mean = uniform_filter(depth ** 2, size=15)
        depth_var = np.maximum(depth_sq_mean - depth_mean ** 2, 0)

        # Higher variance = more occlusion (crevices, corners)
        ao = 1.0 - np.sqrt(depth_var) * 10 * strength
        ao = np.clip(ao, 0, 1)

        # Also darken areas where depth changes rapidly (edges/corners)
        zy, zx = np.gradient(depth)
        gradient_mag = np.sqrt(zx**2 + zy**2)
        edge_ao = 1.0 - gradient_mag * 5 * strength
        edge_ao = np.clip(edge_ao, 0, 1)

        # Combine
        ao = ao * edge_ao

        # Smooth
        ao = gaussian_filter(ao, sigma=2)

        return (ao * 255).astype(np.uint8)

    def estimate_shadow(self, depth: np.ndarray,
                        light_dir: tuple = (0.5, 0.5, 1.0)) -> np.ndarray:
        """
        Approximate shadows from depth using light direction.

        Returns:
            Shadow map as numpy array (0-255, 255=lit)
        """
        # Get normals
        zy, zx = np.gradient(depth)
        normal = np.dstack((-zx * 10, -zy * 10, np.ones_like(depth)))
        n = np.linalg.norm(normal, axis=2, keepdims=True)
        n = np.where(n > 0, n, 1)
        normal = normal / n

        # Normalize light direction
        light = np.array(light_dir)
        light = light / np.linalg.norm(light)

        # Lambertian shading
        ndotl = np.sum(normal * light, axis=2)
        ndotl = np.clip(ndotl, 0, 1)

        # Add ambient
        shadow = 0.3 + 0.7 * ndotl

        return (shadow * 255).astype(np.uint8)

    def extract_all(self, image: Image.Image, output_dir: str,
                    channels: list = None) -> dict:
        """
        Extract all channels from an image.

        Args:
            image: Input PIL Image
            output_dir: Directory to save channel images
            channels: List of channels to extract. Options:
                      'depth', 'normals', 'edges', 'ao', 'shadow'

        Returns:
            Dict of channel names to file paths
        """
        if channels is None:
            channels = ['depth', 'normals', 'edges', 'ao', 'shadow']

        output_dir = Path(output_dir)
        output_dir.mkdir(exist_ok=True)

        results = {}
        depth = None

        print(f"Extracting channels from image: {channels}")

        # Estimate depth first (needed for other channels)
        if any(ch in channels for ch in ['depth', 'normals', 'ao', 'shadow']):
            print("  Estimating depth...")
            depth = self.estimate_depth(image)

            if 'depth' in channels:
                # Save depth (inverted: white=near for ControlNet compatibility)
                depth_img = Image.fromarray((depth * 255).astype(np.uint8))
                depth_path = output_dir / "depth.png"
                depth_img.save(depth_path)
                results['depth'] = str(depth_path)
                print(f"    Saved: {depth_path}")

        # Normals from depth
        if 'normals' in channels and depth is not None:
            print("  Computing normals...")
            normals = self.depth_to_normals(depth)
            normals_img = Image.fromarray(normals)
            normals_path = output_dir / "normals.png"
            normals_img.save(normals_path)
            results['normals'] = str(normals_path)
            print(f"    Saved: {normals_path}")

        # Edges
        if 'edges' in channels:
            print("  Extracting edges...")
            edges = self.extract_edges(image, depth)
            edges_img = Image.fromarray(edges)
            edges_path = output_dir / "edges.png"
            edges_img.save(edges_path)
            results['edges'] = str(edges_path)
            print(f"    Saved: {edges_path}")

        # Ambient occlusion
        if 'ao' in channels and depth is not None:
            print("  Estimating AO...")
            ao = self.estimate_ao(depth)
            ao_img = Image.fromarray(ao)
            ao_path = output_dir / "ao.png"
            ao_img.save(ao_path)
            results['ao'] = str(ao_path)
            print(f"    Saved: {ao_path}")

        # Shadow
        if 'shadow' in channels and depth is not None:
            print("  Estimating shadows...")
            shadow = self.estimate_shadow(depth)
            shadow_img = Image.fromarray(shadow)
            shadow_path = output_dir / "shadow.png"
            shadow_img.save(shadow_path)
            results['shadow'] = str(shadow_path)
            print(f"    Saved: {shadow_path}")

        print("Channel extraction complete!")
        return results


# Singleton instance
_extractor = None


def get_image_extractor() -> ImageChannelExtractor:
    """Get or create the image channel extractor."""
    global _extractor
    if _extractor is None:
        _extractor = ImageChannelExtractor()
    return _extractor
