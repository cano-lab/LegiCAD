# inpainting.py
# Environment inpainting for architectural renders
# Replaces background/environment while preserving building

import torch
import numpy as np
from PIL import Image
from typing import Optional
import gc

print("=== INPAINTING MODULE LOADED ===")


class EnvironmentInpainter:
    """
    Inpaint environment around buildings using Stable Diffusion.

    Uses depth map to create mask that preserves the building
    while allowing creative generation of sky, ground, trees, etc.
    """

    def __init__(self, model_type: str = "sd15"):
        """
        Args:
            model_type: "sd15" (faster, ~2GB) or "sdxl" (higher quality, ~6GB)
        """
        self.model_type = model_type
        self.pipe = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Inpainter initialized (model={model_type}, device={self.device})")

    def _load_model(self):
        """Lazy load the inpainting pipeline."""
        if self.pipe is not None:
            return

        from diffusers import (
            StableDiffusionInpaintPipeline,
            AutoPipelineForInpainting
        )

        if self.model_type == "sdxl":
            print("Loading SDXL Inpainting pipeline (this may download ~6GB on first run)...")
            self.pipe = AutoPipelineForInpainting.from_pretrained(
                "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
                torch_dtype=torch.float16,
                variant="fp16"
            )
        else:
            print("Loading SD 1.5 Inpainting pipeline...")
            self.pipe = StableDiffusionInpaintPipeline.from_pretrained(
                "runwayml/stable-diffusion-inpainting",
                torch_dtype=torch.float16,
                safety_checker=None
            )

        self.pipe.to(self.device)
        self.pipe.enable_attention_slicing(1)

        # Enable memory optimizations
        if hasattr(self.pipe, 'enable_vae_slicing'):
            self.pipe.enable_vae_slicing()
        if hasattr(self.pipe, 'enable_vae_tiling'):
            self.pipe.enable_vae_tiling()

        print(f"{self.model_type.upper()} Inpainting pipeline ready!")

    def create_environment_mask(
        self,
        depth_image: Image.Image,
        threshold: float = 0.3,
        expand_pixels: int = 10,
        feather: int = 15
    ) -> Image.Image:
        """
        Create mask from depth map where building is preserved (black)
        and environment is inpainted (white).

        Args:
            depth_image: Grayscale depth map (closer = brighter typically)
            threshold: Depth threshold (0-1). Pixels below threshold = building
            expand_pixels: Dilate building mask by this many pixels (safety margin)
            feather: Gaussian blur radius for soft edges

        Returns:
            Mask image (white = inpaint, black = keep)
        """
        from PIL import ImageFilter

        # Convert to numpy
        depth_np = np.array(depth_image.convert('L')).astype(np.float32) / 255.0

        # Create building mask (depth above threshold = building)
        # This assumes closer objects have higher depth values (white = close)
        # which matches Warp/3D renderer output where building is bright
        building_mask = depth_np > threshold

        # Expand building mask (dilate) to create safety margin
        if expand_pixels > 0:
            from scipy import ndimage
            building_mask = ndimage.binary_dilation(
                building_mask,
                iterations=expand_pixels
            )

        # Invert: white = inpaint (environment), black = keep (building)
        inpaint_mask = (~building_mask).astype(np.uint8) * 255
        mask = Image.fromarray(inpaint_mask, mode='L')

        # Feather edges for smooth blending
        if feather > 0:
            mask = mask.filter(ImageFilter.GaussianBlur(radius=feather))

        return mask

    def inpaint(
        self,
        image: Image.Image,
        mask: Image.Image,
        prompt: str,
        negative_prompt: str = "ugly, blurry, low quality, distorted",
        num_inference_steps: int = 30,
        guidance_scale: float = 7.5,
        seed: Optional[int] = None,
        progress_callback=None
    ) -> Image.Image:
        """
        Inpaint masked regions of image.

        Args:
            image: Input image
            mask: Mask (white = inpaint, black = keep)
            prompt: What to generate in masked area
            negative_prompt: What to avoid
            num_inference_steps: Diffusion steps (more = better quality, slower)
            guidance_scale: Prompt adherence (7-12 typical)
            seed: Random seed for reproducibility

        Returns:
            Inpainted image
        """
        self._load_model()

        # Resize to model-compatible size
        w, h = image.size

        if self.model_type == "sdxl":
            # SDXL works best at 1024x1024
            target_size = 1024
        else:
            # SD 1.5 at 512x512
            target_size = 512

        # Maintain aspect ratio
        aspect = w / h
        if aspect > 1:
            new_w = target_size
            new_h = int(target_size / aspect)
        else:
            new_h = target_size
            new_w = int(target_size * aspect)

        # Round to 8
        new_w = (new_w // 8) * 8
        new_h = (new_h // 8) * 8
        new_w = max(new_w, 64)
        new_h = max(new_h, 64)

        image_resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        mask_resized = mask.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # Set seed
        generator = None
        if seed is not None:
            generator = torch.Generator(device=self.device).manual_seed(seed)

        print(f"Inpainting at {new_w}x{new_h}, {num_inference_steps} steps...")

        # Create step callback for progress reporting
        def step_callback(pipe, step_index, timestep, callback_kwargs):
            if progress_callback:
                progress_callback(step_index + 1, num_inference_steps, "Inpainting")
            return callback_kwargs

        # Run inpainting
        result = self.pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            image=image_resized,
            mask_image=mask_resized,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            generator=generator,
            callback_on_step_end=step_callback
        ).images[0]

        # Resize back to original
        if result.size != (w, h):
            result = result.resize((w, h), Image.Resampling.LANCZOS)

        # Clear cache
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()

        return result

    def inpaint_environment(
        self,
        image: Image.Image,
        depth: Image.Image,
        prompt: str = "beautiful blue sky with clouds, green grass lawn, trees, professional photography",
        negative_prompt: str = "ugly, blurry, low quality, distorted, cartoon",
        threshold: float = 0.3,
        expand_pixels: int = 10,
        feather: int = 15,
        num_inference_steps: int = 30,
        guidance_scale: float = 7.5,
        seed: Optional[int] = None
    ) -> tuple:
        """
        Complete environment inpainting workflow.

        Args:
            image: Base render image
            depth: Depth map from render
            prompt: Environment description
            negative_prompt: What to avoid
            threshold: Depth threshold for building detection
            expand_pixels: Safety margin around building
            feather: Mask edge blur
            num_inference_steps: Diffusion steps
            guidance_scale: Prompt strength
            seed: Random seed

        Returns:
            Tuple of (result_image, mask_image)
        """
        # Create mask from depth
        mask = self.create_environment_mask(
            depth,
            threshold=threshold,
            expand_pixels=expand_pixels,
            feather=feather
        )

        # Inpaint environment
        result = self.inpaint(
            image=image,
            mask=mask,
            prompt=prompt,
            negative_prompt=negative_prompt,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            seed=seed
        )

        return result, mask

    def unload(self):
        """Unload model to free memory."""
        if self.pipe is not None:
            del self.pipe
            self.pipe = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()
            print("Inpainting model unloaded")


# Singleton instance
_inpainter = None


def get_inpainter(model_type: str = "sd15") -> EnvironmentInpainter:
    """Get or create inpainter instance."""
    global _inpainter

    if _inpainter is None or _inpainter.model_type != model_type:
        # Unload existing if switching models
        if _inpainter is not None:
            _inpainter.unload()
        _inpainter = EnvironmentInpainter(model_type=model_type)

    return _inpainter


# Quick test
if __name__ == "__main__":
    from pathlib import Path

    # Test mask creation
    print("Testing mask creation...")

    # Create fake depth (gradient)
    depth = Image.new('L', (512, 512))
    depth_np = np.zeros((512, 512), dtype=np.uint8)
    # Building in center (low depth = close)
    depth_np[100:400, 150:350] = 50  # Building
    depth_np[:100, :] = 200  # Sky (far)
    depth_np[400:, :] = 180  # Ground (medium)
    depth = Image.fromarray(depth_np)

    inpainter = get_inpainter("sd15")
    mask = inpainter.create_environment_mask(depth, threshold=0.3, expand_pixels=10)

    print(f"Mask size: {mask.size}")
    print("Test complete - mask created successfully")
