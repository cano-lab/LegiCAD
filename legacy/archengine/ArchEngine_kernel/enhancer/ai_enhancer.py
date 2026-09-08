# ai_enhancer.py
import torch
import gc
from diffusers import (
    StableDiffusionControlNetImg2ImgPipeline,
    ControlNetModel,
    UniPCMultistepScheduler,
    AutoencoderKL
)
from PIL import Image
import numpy as np
from pathlib import Path

print("=== AI_ENHANCER MODULE LOADED ===")

# Check for xformers
XFORMERS_AVAILABLE = False
try:
    import xformers
    XFORMERS_AVAILABLE = True
    print("  [OK] xformers available - memory efficient attention enabled")
except ImportError:
    print("  [WARN] xformers not installed - using standard attention")


def optimize_pipeline(pipe, device="cuda"):
    """Apply all memory optimizations for 8GB VRAM."""
    pipe.to(device)

    # Enable xformers if available (20-40% speedup, less VRAM)
    if XFORMERS_AVAILABLE:
        try:
            pipe.enable_xformers_memory_efficient_attention()
            print("    [OK] xformers memory efficient attention enabled")
        except Exception as e:
            print(f"    [WARN] xformers failed: {e}")

    # Attention slicing (reduces VRAM by processing in chunks)
    pipe.enable_attention_slicing(1)

    # VAE optimizations
    if hasattr(pipe, 'vae'):
        pipe.vae.enable_slicing()
        pipe.vae.enable_tiling()

    # Clear CUDA cache
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        gc.collect()

    return pipe


def clear_vram():
    """Aggressively clear VRAM between operations."""
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    gc.collect()

class ChannelEnhancer:
    """AI enhancement that preserves structure, only enhances materials and lighting."""
    
    def __init__(self, model_id: str = "SG161222/Realistic_Vision_V5.1_noVAE"):
        print("Loading AI Enhancer (structure-preserving mode)...")
        
        # Load ControlNet for depth
        print("  Loading ControlNet-Depth...")
        self.controlnet = ControlNetModel.from_pretrained(
            "lllyasviel/control_v11f1p_sd15_depth",
            torch_dtype=torch.float16
        )
        
        # Use ControlNet + Img2Img pipeline for maximum control
        print("  Loading Stable Diffusion pipeline...")
        self.pipe = StableDiffusionControlNetImg2ImgPipeline.from_pretrained(
            model_id,
            controlnet=self.controlnet,
            torch_dtype=torch.float16,
            safety_checker=None
        )
        
        # Better scheduler for quality
        self.pipe.scheduler = UniPCMultistepScheduler.from_config(self.pipe.scheduler.config)

        # Apply all memory optimizations for 8GB VRAM
        self.pipe = optimize_pipeline(self.pipe, device="cuda")

        print("Enhancer ready!")
    
    def enhance(
        self,
        base_path: str,
        depth_path: str = None,
        normals_path: str = None,
        edges_path: str = None,
        segmentation_path: str = None,
        prompt: str = "architectural visualization",
        negative_prompt: str = "blurry, low quality, distorted",
        num_inference_steps: int = 30,
        guidance_scale: float = 7.5,
        controlnet_conditioning_scale: float = 1.0,  # High = preserve structure
        strength: float = 0.35,  # Low = minimal changes to base
        seed: int = None,
        width: int = 512,
        height: int = 512,
        progress_callback=None
    ) -> Image.Image:
        """
        Enhance base image while preserving structure.
        
        - controlnet_conditioning_scale: Higher (0.9-1.0) = more structure preservation
        - strength: Lower (0.2-0.4) = less deviation from base image
        """
        
        # Load base image
        base_img = Image.open(base_path).convert("RGB")
        base_img = base_img.resize((width, height), Image.Resampling.LANCZOS)
        
        # Load depth for ControlNet (or use base as fallback)
        if depth_path and Path(depth_path).exists():
            control_img = Image.open(depth_path).convert("RGB")
        else:
            # Convert base to grayscale as pseudo-depth
            control_img = base_img.convert("L").convert("RGB")
        control_img = control_img.resize((width, height), Image.Resampling.LANCZOS)
        
        # Blend edges into control for sharper architectural lines
        if edges_path and Path(edges_path).exists():
            edges = Image.open(edges_path).convert("L").resize((width, height))
            edges_array = np.array(edges).astype(float) / 255.0
            control_array = np.array(control_img).astype(float) / 255.0
            
            # Strengthen edges in control image
            edge_boost = 0.4
            control_array = control_array * (1 - edges_array[:,:,None] * edge_boost)
            control_img = Image.fromarray((control_array * 255).astype(np.uint8))
        
        # Set seed
        generator = None
        if seed is not None:
            generator = torch.Generator("cuda").manual_seed(seed)
        
        clear_vram()

        # Create step callback for progress reporting
        step_callback = None
        if progress_callback:
            def step_callback(pipe, step_index, timestep, callback_kwargs):
                progress_callback(step_index + 1, num_inference_steps, "Diffusion")
                return callback_kwargs

        # Generate with both ControlNet (structure) and Img2Img (base preservation)
        result = self.pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            image=base_img,  # Start from base image
            control_image=control_img,  # Guide with depth
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            controlnet_conditioning_scale=controlnet_conditioning_scale,
            strength=strength,  # How much to change (lower = less change)
            generator=generator,
            callback_on_step_end=step_callback
        ).images[0]

        return result

    def enhance_selective(
        self,
        base_path: str,
        depth_path: str,
        prompt_building: str = "architectural photography, photorealistic building, detailed materials, sharp",
        prompt_environment: str = "beautiful sky, lush landscaping, professional photography",
        negative_prompt: str = "blurry, low quality, distorted, cartoon",
        building_strength: float = 0.25,  # Low = preserve building
        environment_strength: float = 0.6,  # Higher = creative freedom
        building_controlnet: float = 1.0,  # Strict structure
        environment_controlnet: float = 0.3,  # Loose structure
        depth_threshold: float = 0.7,  # 0-1, higher = more counts as "building"
        mask_blur: int = 15,  # Feather the mask edge
        num_inference_steps: int = 25,
        guidance_scale: float = 7.5,
        seed: int = None,
        width: int = 512,
        height: int = 512
    ) -> Image.Image:
        """
        Selective enhancement: strict on building, creative on environment.

        Uses depth to auto-mask building (foreground) vs environment (background).
        Runs two passes with different settings and blends them.
        """
        from scipy.ndimage import gaussian_filter

        # Load images
        base_img = Image.open(base_path).convert("RGB")
        base_img = base_img.resize((width, height), Image.Resampling.LANCZOS)

        depth_img = Image.open(depth_path).convert("L")
        depth_img = depth_img.resize((width, height), Image.Resampling.LANCZOS)
        depth_array = np.array(depth_img).astype(float) / 255.0

        # Create mask: white (1.0) = building, black (0.0) = environment
        # Depth is inverted: white = near (building), black = far (sky)
        building_mask = (depth_array > depth_threshold).astype(float)

        # Feather the mask edges for smooth blending
        building_mask = gaussian_filter(building_mask, sigma=mask_blur)
        building_mask = np.clip(building_mask, 0, 1)

        # Control image from depth
        control_img = depth_img.convert("RGB")

        # Set seed for reproducibility
        generator = None
        if seed is not None:
            generator = torch.Generator("cuda").manual_seed(seed)

        clear_vram()

        print("  Pass 1: Building (strict)...")
        # Pass 1: Building-focused (strict preservation)
        result_building = self.pipe(
            prompt=prompt_building,
            negative_prompt=negative_prompt,
            image=base_img,
            control_image=control_img,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            controlnet_conditioning_scale=building_controlnet,
            strength=building_strength,
            generator=generator
        ).images[0]

        clear_vram()

        print("  Pass 2: Environment (creative)...")
        # Pass 2: Environment-focused (creative freedom)
        # Reset generator for different result
        if seed is not None:
            generator = torch.Generator("cuda").manual_seed(seed + 1000)

        result_environment = self.pipe(
            prompt=prompt_environment,
            negative_prompt=negative_prompt,
            image=base_img,
            control_image=control_img,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            controlnet_conditioning_scale=environment_controlnet,
            strength=environment_strength,
            generator=generator
        ).images[0]

        # Blend: building from pass 1, environment from pass 2
        print("  Blending...")
        result_building_array = np.array(result_building).astype(float)
        result_env_array = np.array(result_environment).astype(float)

        # Expand mask to 3 channels
        mask_3ch = building_mask[:, :, np.newaxis]

        # Blend: mask=1 uses building result, mask=0 uses environment result
        blended = result_building_array * mask_3ch + result_env_array * (1 - mask_3ch)
        blended = np.clip(blended, 0, 255).astype(np.uint8)

        return Image.fromarray(blended)