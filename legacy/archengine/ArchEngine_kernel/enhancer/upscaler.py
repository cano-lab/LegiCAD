# upscaler.py
import torch
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance
from pathlib import Path
import sys
import gc

# Fix for newer torchvision versions that removed functional_tensor
# This must happen BEFORE importing basicsr/realesrgan
try:
    import torchvision.transforms.functional_tensor
except ImportError:
    # Create a shim module for compatibility with older basicsr/realesrgan
    import torchvision.transforms.functional as F
    import types

    # Create fake module with the functions that basicsr expects
    functional_tensor = types.ModuleType('torchvision.transforms.functional_tensor')
    functional_tensor.rgb_to_grayscale = F.rgb_to_grayscale
    sys.modules['torchvision.transforms.functional_tensor'] = functional_tensor

print("=== UPSCALER MODULE LOADED ===")


class TileUpscaler:
    """AI-powered upscaler using Real-ESRGAN for architectural renders."""

    def __init__(self, model_name: str = "realesrgan-x4plus"):
        """
        Initialize the upscaler.

        Args:
            model_name: Model to use. Options:
                - "realesrgan-x4plus" (default) - Best quality, 4x
                - "realesrgan-x4plus-anime" - For anime/illustration style
                - "realesrnet-x4plus" - Faster, slightly lower quality
                - "simple" - Lanczos fallback (no AI)
        """
        self.model_name = model_name
        self.model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Upscaler initialized (model={model_name}, device={self.device})")

    def _load_model(self):
        """Lazy load the Real-ESRGAN model."""
        if self.model is not None:
            return

        if self.model_name == "simple":
            print("Using simple Lanczos upscaler (no AI)")
            return

        # Try spandrel first (modern, well-maintained library)
        if self._try_load_spandrel():
            return

        # Fall back to basicsr/realesrgan
        if self._try_load_basicsr():
            return

        # Last resort: simple upscaler
        print("All AI upscalers failed, using simple Lanczos")
        self.model_name = "simple"

    def _try_load_spandrel(self) -> bool:
        """Try loading Real-ESRGAN via spandrel (modern approach)."""
        try:
            from pathlib import Path
            import spandrel

            print(f"Loading Real-ESRGAN via spandrel...", flush=True)

            models_dir = Path(__file__).parent / "models"
            models_dir.mkdir(exist_ok=True)
            model_path = models_dir / "RealESRGAN_x4plus.pth"

            # Download model if needed
            if not model_path.exists():
                print("Downloading RealESRGAN_x4plus model (~67MB)...", flush=True)
                try:
                    import urllib.request
                    import socket

                    url = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"
                    print(f"Downloading from: {url}", flush=True)

                    # Set timeout to avoid hanging
                    socket.setdefaulttimeout(30)  # 30 second timeout

                    # Download with progress
                    def show_progress(block_num, block_size, total_size):
                        if total_size > 0:
                            pct = min(100, block_num * block_size * 100 // total_size)
                            print(f"\r  Progress: {pct}%", end="", flush=True)

                    urllib.request.urlretrieve(url, str(model_path), reporthook=show_progress)
                    print()  # Newline after progress

                    # Reset timeout
                    socket.setdefaulttimeout(None)
                except socket.timeout:
                    print(f"\nDownload timed out - using simple upscaler")
                    return False
                except Exception as e:
                    print(f"\nDownload failed: {e}")
                    return False

            # Load with spandrel
            self.model = spandrel.ModelLoader().load_from_file(str(model_path))
            self.model = self.model.to(self.device)
            if self.device == "cuda":
                self.model = self.model.half()
            self.model.eval()
            self._use_spandrel = True

            print(f"Real-ESRGAN loaded via spandrel!", flush=True)
            return True

        except ImportError:
            print("spandrel not installed, trying basicsr...", flush=True)
            return False
        except Exception as e:
            print(f"spandrel loading failed: {e}", flush=True)
            return False

    def _try_load_basicsr(self) -> bool:
        """Try loading Real-ESRGAN via basicsr (older approach)."""
        try:
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer
            import os

            print(f"Loading Real-ESRGAN via basicsr: {self.model_name}...")

            models_dir = Path(__file__).parent / "models"
            models_dir.mkdir(exist_ok=True)

            model = RRDBNet(
                num_in_ch=3, num_out_ch=3, num_feat=64,
                num_block=23, num_grow_ch=32, scale=4
            )

            model_path = models_dir / "RealESRGAN_x4plus.pth"
            if not model_path.exists():
                import urllib.request
                import socket

                url = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"
                print(f"Downloading model from: {url}")

                # Set timeout to avoid hanging
                socket.setdefaulttimeout(30)
                try:
                    urllib.request.urlretrieve(url, str(model_path))
                finally:
                    socket.setdefaulttimeout(None)

            self.model = RealESRGANer(
                scale=4,
                model_path=str(model_path),
                dni_weight=None,
                model=model,
                tile=256,  # Reduced for memory efficiency
                tile_pad=16,
                pre_pad=0,
                half=True if self.device == "cuda" else False,
                device=self.device
            )
            self._use_spandrel = False

            print(f"Real-ESRGAN model loaded via basicsr!")
            return True

        except Exception as e:
            print(f"basicsr loading failed: {e}")
            return False

    def upscale(self, input_path: str, output_path: str,
                prompt: str = None, scale: int = 4,
                progress_callback=None, tile_size: int = 256, **kwargs) -> str:
        """
        Upscale image using Real-ESRGAN.

        Args:
            input_path: Path to input image
            output_path: Path to save upscaled image
            prompt: Not used for Real-ESRGAN (kept for API compatibility)
            scale: Upscale factor (2 or 4)
            progress_callback: Optional callback(current, total) for progress
            tile_size: Tile size for processing large images (default 512)

        Returns:
            Path to the upscaled image
        """
        img = Image.open(input_path).convert('RGB')
        w, h = img.size

        print(f"Upscaling {w}x{h} -> {w*scale}x{h*scale}...")

        # Load model if needed
        self._load_model()

        if self.model_name == "simple" or self.model is None:
            return self._upscale_simple(img, output_path, scale)

        try:
            if progress_callback:
                progress_callback(1, 3)

            # Use appropriate upscaling method
            if getattr(self, '_use_spandrel', False):
                result = self._upscale_spandrel(img, scale, tile_size)
            else:
                result = self._upscale_basicsr(img, scale)

            if progress_callback:
                progress_callback(2, 3)

            # Save
            result.save(output_path, 'PNG', quality=95)

            if progress_callback:
                progress_callback(3, 3)

            print(f"Upscaled: {w}x{h} -> {result.size[0]}x{result.size[1]}")
            return output_path

        except Exception as e:
            print(f"Real-ESRGAN failed: {e}, falling back to simple")
            import traceback
            traceback.print_exc()
            return self._upscale_simple(img, output_path, scale)

    def _upscale_spandrel(self, img: Image.Image, scale: int = 4, tile_size: int = 512) -> Image.Image:
        """Upscale using spandrel with tiling for memory efficiency."""
        w, h = img.size
        out_w, out_h = w * scale, h * scale

        # Convert to tensor
        img_np = np.array(img).astype(np.float32) / 255.0
        img_tensor = torch.from_numpy(img_np).permute(2, 0, 1).unsqueeze(0)
        img_tensor = img_tensor.to(self.device)
        if self.device == "cuda":
            img_tensor = img_tensor.half()

        # Process in tiles if image is large
        if w > tile_size or h > tile_size:
            result = self._tile_process_spandrel(img_tensor, scale, tile_size)
        else:
            with torch.no_grad():
                result = self.model(img_tensor)

        # Convert back to PIL
        result_np = result.squeeze(0).permute(1, 2, 0).float().cpu().numpy()
        result_np = np.clip(result_np * 255, 0, 255).astype(np.uint8)

        return Image.fromarray(result_np)

    def _tile_process_spandrel(self, img_tensor: torch.Tensor, scale: int, tile_size: int) -> torch.Tensor:
        """Process large image in tiles using spandrel."""
        _, c, h, w = img_tensor.shape
        out_h, out_w = h * scale, w * scale
        tile_pad = 16  # Reduced padding for memory

        # Output tensor (on CPU to save GPU memory)
        output = torch.zeros((1, c, out_h, out_w), dtype=torch.float32, device='cpu')
        weight = torch.zeros((1, c, out_h, out_w), dtype=torch.float32, device='cpu')

        # Calculate tiles
        tiles_x = (w + tile_size - 1) // tile_size
        tiles_y = (h + tile_size - 1) // tile_size

        total_tiles = tiles_x * tiles_y
        tile_num = 0

        for y in range(tiles_y):
            for x in range(tiles_x):
                tile_num += 1

                # Input tile bounds with padding
                x0 = max(0, x * tile_size - tile_pad)
                y0 = max(0, y * tile_size - tile_pad)
                x1 = min(w, (x + 1) * tile_size + tile_pad)
                y1 = min(h, (y + 1) * tile_size + tile_pad)

                # Extract tile
                tile = img_tensor[:, :, y0:y1, x0:x1].contiguous()

                # Process
                with torch.no_grad():
                    tile_out = self.model(tile)
                    # Move to CPU immediately to free GPU memory
                    tile_out_cpu = tile_out.float().cpu()
                    del tile_out

                # Output bounds
                out_x0 = x0 * scale
                out_y0 = y0 * scale
                out_x1 = x1 * scale
                out_y1 = y1 * scale

                # Paste output (on CPU)
                output[:, :, out_y0:out_y1, out_x0:out_x1] += tile_out_cpu
                weight[:, :, out_y0:out_y1, out_x0:out_x1] += 1
                del tile_out_cpu

                # Aggressive memory cleanup
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                    torch.cuda.empty_cache()
                gc.collect()

                if tile_num % 5 == 0 or tile_num == total_tiles:
                    print(f"  Real-ESRGAN tiles: {tile_num}/{total_tiles}")

        # Average overlapping regions
        output = output / weight.clamp(min=1)

        return output

    def _upscale_basicsr(self, img: Image.Image, scale: int = 4) -> Image.Image:
        """Upscale using basicsr/realesrgan."""
        # Convert to numpy for Real-ESRGAN (BGR format)
        img_np = np.array(img)[:, :, ::-1]  # RGB to BGR

        # Upscale
        output, _ = self.model.enhance(img_np, outscale=scale)

        # Convert back to PIL (BGR to RGB)
        output_rgb = output[:, :, ::-1]
        return Image.fromarray(output_rgb)

    def _upscale_simple(self, img: Image.Image, output_path: str, scale: int = 4) -> str:
        """Simple Lanczos upscale with sharpening fallback."""
        w, h = img.size

        # Upscale with Lanczos
        upscaled = img.resize((w * scale, h * scale), Image.Resampling.LANCZOS)

        # Sharpen to compensate for interpolation blur
        upscaled = upscaled.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=2))

        # Slight contrast boost for architectural renders
        enhancer = ImageEnhance.Contrast(upscaled)
        upscaled = enhancer.enhance(1.05)

        upscaled.save(output_path, 'PNG')
        print(f"Simple upscale: {w}x{h} -> {w*scale}x{h*scale}")

        return output_path

    def cancel(self):
        """Cancel any running operation."""
        pass  # Real-ESRGAN doesn't have built-in cancellation


class SDUpscaler:
    """Stable Diffusion based upscaler for creative upscaling with text guidance."""

    def __init__(self):
        self.pipe = None
        print("SD Upscaler initialized (lazy loading)")

    def _load_model(self):
        """Lazy load the SD x4 upscaler."""
        if self.pipe is not None:
            return

        from diffusers import StableDiffusionUpscalePipeline
        import torch

        print("Loading Stable Diffusion x4 Upscaler...")

        self.pipe = StableDiffusionUpscalePipeline.from_pretrained(
            "stabilityai/stable-diffusion-x4-upscaler",
            torch_dtype=torch.float16
        )
        self.pipe.to("cuda")
        self.pipe.enable_attention_slicing(1)

        print("SD Upscaler loaded!")

    def upscale(self, input_path: str, output_path: str,
                prompt: str = "high quality architectural visualization, detailed, sharp",
                negative_prompt: str = "blurry, low quality, artifacts",
                num_inference_steps: int = 25,
                guidance_scale: float = 7.5,
                **kwargs) -> str:
        """
        Upscale image 4x using Stable Diffusion.

        This method is more creative and can add details, but may change
        the image more than Real-ESRGAN.
        """
        self._load_model()

        img = Image.open(input_path).convert('RGB')
        w, h = img.size

        # SD upscaler works best with smaller inputs
        max_size = 512
        if w > max_size or h > max_size:
            ratio = min(max_size / w, max_size / h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.Resampling.LANCZOS)
            print(f"Resized input to {img.size} for SD upscaler")

        print(f"SD Upscaling with prompt: {prompt[:50]}...")

        result = self.pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            image=img,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale
        ).images[0]

        result.save(output_path, 'PNG')
        print(f"SD Upscaled: {w}x{h} -> {result.size[0]}x{result.size[1]}")

        return output_path


class UltraQualityUpscaler:
    """
    Maximum quality upscaler using multi-pass approach.

    Pipeline:
    1. Real-ESRGAN 4x for clean structural upscale
    2. ControlNet + SD refinement for detail enhancement
    3. Optional second refinement pass

    Takes 5-40 minutes depending on settings but produces exceptional detail.
    """

    def __init__(self):
        self.realesrgan = None
        self.pipe = None
        self.controlnet = None
        print("Ultra Quality Upscaler initialized (lazy loading)")

    def _load_realesrgan(self):
        """Load Real-ESRGAN for initial upscale."""
        if self.realesrgan is not None:
            return

        base_upscaler = TileUpscaler(model_name="realesrgan-x4plus")
        base_upscaler._load_model()
        self.realesrgan = base_upscaler

    def _load_refinement_pipeline(self):
        """Load ControlNet + SD for refinement."""
        if self.pipe is not None:
            return

        from diffusers import (
            StableDiffusionControlNetImg2ImgPipeline,
            ControlNetModel,
            UniPCMultistepScheduler
        )

        print("Loading ControlNet for refinement...")
        self.controlnet = ControlNetModel.from_pretrained(
            "lllyasviel/control_v11f1p_sd15_depth",
            torch_dtype=torch.float16
        )

        print("Loading SD pipeline for refinement...")
        self.pipe = StableDiffusionControlNetImg2ImgPipeline.from_pretrained(
            "SG161222/Realistic_Vision_V5.1_noVAE",
            controlnet=self.controlnet,
            torch_dtype=torch.float16,
            safety_checker=None
        )
        self.pipe.scheduler = UniPCMultistepScheduler.from_config(self.pipe.scheduler.config)
        self.pipe.to("cuda")
        self.pipe.enable_attention_slicing(1)
        self.pipe.enable_vae_slicing()
        self.pipe.enable_vae_tiling()

        print("Refinement pipeline ready!")

    def upscale(self, input_path: str, output_path: str,
                prompt: str = "highly detailed architectural visualization, photorealistic, sharp details, professional photography, 8k uhd",
                negative_prompt: str = "blurry, low quality, artifacts, distorted, deformed",
                depth_path: str = None,
                num_passes: int = 2,
                refinement_strength: float = 0.25,
                refinement_steps: int = 30,
                tile_size: int = 512,
                tile_overlap: int = 64,
                progress_callback=None,
                **kwargs) -> str:
        """
        Ultra quality upscale with refinement.

        Args:
            input_path: Input image path
            output_path: Output image path
            prompt: Text prompt for detail enhancement
            negative_prompt: What to avoid
            depth_path: Optional depth map for better structure preservation
            num_passes: Number of refinement passes (1-3, more = better but slower)
            refinement_strength: How much to change (0.15-0.35 recommended)
            refinement_steps: Diffusion steps per tile (20-50)
            tile_size: Processing tile size (512-1024)
            tile_overlap: Overlap between tiles for seamless blending
            progress_callback: Optional progress callback(current, total, stage)

        Returns:
            Path to upscaled image
        """
        import time

        start_time = time.time()

        # Load base image
        img = Image.open(input_path).convert('RGB')
        w, h = img.size
        print(f"Ultra Quality Upscale: {w}x{h} -> {w*4}x{h*4}")
        print(f"Settings: {num_passes} passes, {refinement_steps} steps, strength={refinement_strength}")

        # Stage 1: Real-ESRGAN 4x upscale
        print("\n=== Stage 1: Real-ESRGAN 4x Upscale ===")
        self._load_realesrgan()

        if progress_callback:
            progress_callback(1, 10, "Real-ESRGAN upscale")

        # Use Real-ESRGAN
        temp_path = Path(output_path).parent / "temp_upscaled.png"
        self.realesrgan.upscale(input_path, str(temp_path))
        upscaled = Image.open(temp_path).convert('RGB')

        elapsed = time.time() - start_time
        print(f"Stage 1 complete ({elapsed:.1f}s)")

        # Stage 2: ControlNet refinement passes
        if num_passes > 0:
            print(f"\n=== Stage 2: {num_passes} Refinement Pass(es) ===")
            self._load_refinement_pipeline()

            # Load or generate depth for control
            if depth_path and Path(depth_path).exists():
                depth = Image.open(depth_path).convert('RGB')
                # Upscale depth to match
                depth = depth.resize(upscaled.size, Image.Resampling.LANCZOS)
            else:
                # Generate depth from upscaled image
                depth = self._estimate_depth(upscaled)

            for pass_num in range(num_passes):
                print(f"\nRefinement pass {pass_num + 1}/{num_passes}")

                if progress_callback:
                    progress_callback(2 + pass_num * 3, 10, f"Refinement pass {pass_num + 1}")

                # Process in tiles for large images
                upscaled = self._process_tiles(
                    upscaled, depth, prompt, negative_prompt,
                    tile_size, tile_overlap,
                    refinement_strength, refinement_steps,
                    progress_callback
                )

                elapsed = time.time() - start_time
                print(f"Pass {pass_num + 1} complete ({elapsed:.1f}s total)")

        # Save final result
        upscaled.save(output_path, 'PNG', quality=95)

        # Clean up temp file
        if temp_path.exists():
            temp_path.unlink()

        elapsed = time.time() - start_time
        print(f"\n=== Ultra Quality Upscale Complete ===")
        print(f"Total time: {elapsed/60:.1f} minutes")
        print(f"Output: {upscaled.size[0]}x{upscaled.size[1]}")

        if progress_callback:
            progress_callback(10, 10, "Complete")

        return output_path

    def _estimate_depth(self, img: Image.Image) -> Image.Image:
        """
        Estimate depth using Depth Anything v2 model.
        Falls back to luminance-based estimation if model fails.
        """
        try:
            from image_channels import get_image_extractor

            print("Estimating depth with Depth Anything v2...")
            extractor = get_image_extractor()

            # Get depth as numpy array (0-1 range)
            depth_np = extractor.estimate_depth(img)

            # Convert to 8-bit image
            depth_img = Image.fromarray((depth_np * 255).astype(np.uint8))

            # Convert to RGB for ControlNet compatibility
            return depth_img.convert('RGB')

        except Exception as e:
            print(f"Depth Anything failed: {e}, falling back to luminance")
            # Fallback to simple luminance-based depth
            gray = img.convert('L')
            inverted = Image.eval(gray, lambda x: 255 - x)
            return inverted.convert('RGB')

    def _process_tiles(self, img: Image.Image, depth: Image.Image,
                       prompt: str, negative_prompt: str,
                       tile_size: int, overlap: int,
                       strength: float, steps: int,
                       progress_callback=None) -> Image.Image:
        """Process image in overlapping tiles for memory efficiency."""

        w, h = img.size
        result = img.copy()

        # Calculate tile grid
        x_tiles = max(1, (w - overlap) // (tile_size - overlap) + 1)
        y_tiles = max(1, (h - overlap) // (tile_size - overlap) + 1)
        total_tiles = x_tiles * y_tiles

        print(f"Processing {total_tiles} tiles ({x_tiles}x{y_tiles})")

        tile_num = 0
        for y in range(y_tiles):
            for x in range(x_tiles):
                tile_num += 1

                # Calculate tile bounds
                x0 = x * (tile_size - overlap)
                y0 = y * (tile_size - overlap)
                x1 = min(x0 + tile_size, w)
                y1 = min(y0 + tile_size, h)

                # Adjust for edge tiles
                if x1 - x0 < tile_size // 2:
                    x0 = max(0, w - tile_size)
                    x1 = w
                if y1 - y0 < tile_size // 2:
                    y0 = max(0, h - tile_size)
                    y1 = h

                # Extract tiles
                img_tile = img.crop((x0, y0, x1, y1))
                depth_tile = depth.crop((x0, y0, x1, y1))

                # Resize to SD resolution if needed
                tile_w, tile_h = img_tile.size
                process_size = (
                    (tile_w // 8) * 8,
                    (tile_h // 8) * 8
                )

                img_tile_resized = img_tile.resize(process_size, Image.Resampling.LANCZOS)
                depth_tile_resized = depth_tile.resize(process_size, Image.Resampling.LANCZOS)

                # Process tile
                try:
                    refined = self.pipe(
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                        image=img_tile_resized,
                        control_image=depth_tile_resized,
                        strength=strength,
                        num_inference_steps=steps,
                        guidance_scale=7.5,
                        controlnet_conditioning_scale=0.8
                    ).images[0]

                    # Resize back if needed
                    if refined.size != (tile_w, tile_h):
                        refined = refined.resize((tile_w, tile_h), Image.Resampling.LANCZOS)

                    # Blend tile into result (simple paste, overlap handles blending)
                    # For better blending, use feathered edges
                    result = self._blend_tile(result, refined, x0, y0, overlap)

                except Exception as e:
                    print(f"Tile {tile_num} failed: {e}, keeping original")

                # Aggressive memory cleanup
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                    torch.cuda.empty_cache()
                gc.collect()

                if tile_num % 5 == 0 or tile_num == total_tiles:
                    print(f"  Refinement tiles: {tile_num}/{total_tiles}")

        return result

    def _blend_tile(self, canvas: Image.Image, tile: Image.Image,
                    x: int, y: int, overlap: int) -> Image.Image:
        """
        Blend tile into canvas with improved feathering.
        Uses cosine falloff for smoother transitions and larger feather regions.
        """
        tile_w, tile_h = tile.size
        canvas_w, canvas_h = canvas.size

        # Use larger feather region for smoother blending
        feather = min(overlap, 64)

        # Create feather mask
        mask_array = np.ones((tile_h, tile_w), dtype=np.float32)

        # Cosine falloff function for smoother blending
        def cosine_falloff(distance, max_dist):
            if max_dist <= 0:
                return 1.0
            t = min(distance / max_dist, 1.0)
            return 0.5 * (1 - np.cos(np.pi * t))

        # Feather left edge (if not at canvas left)
        if x > 0:
            for i in range(feather):
                mask_array[:, i] *= cosine_falloff(i, feather)

        # Feather top edge (if not at canvas top)
        if y > 0:
            for i in range(feather):
                mask_array[i, :] *= cosine_falloff(i, feather)

        # Feather right edge (if not at canvas right)
        if x + tile_w < canvas_w:
            for i in range(feather):
                mask_array[:, tile_w - 1 - i] *= cosine_falloff(i, feather)

        # Feather bottom edge (if not at canvas bottom)
        if y + tile_h < canvas_h:
            for i in range(feather):
                mask_array[tile_h - 1 - i, :] *= cosine_falloff(i, feather)

        # Apply gaussian blur to mask for extra smoothness
        from scipy.ndimage import gaussian_filter
        mask_array = gaussian_filter(mask_array, sigma=feather / 8)

        mask = Image.fromarray((mask_array * 255).astype(np.uint8))

        # Composite with alpha blending
        canvas.paste(tile, (x, y), mask)
        return canvas


class SDXLUpscaler:
    """
    SDXL-based upscaler for higher quality creative upscaling.
    Uses SDXL img2img with low strength for detail enhancement.
    """

    def __init__(self):
        self.pipe = None
        self.realesrgan = None
        print("SDXL Upscaler initialized (lazy loading)")

    def _load_model(self):
        """Lazy load SDXL img2img pipeline."""
        if self.pipe is not None:
            return

        from diffusers import StableDiffusionXLImg2ImgPipeline

        print("Loading SDXL img2img pipeline...")
        self.pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
            "stabilityai/stable-diffusion-xl-refiner-1.0",
            torch_dtype=torch.float16,
            variant="fp16"
        )
        self.pipe.to("cuda")
        self.pipe.enable_model_cpu_offload()
        self.pipe.enable_vae_slicing()

        print("SDXL Upscaler loaded!")

    def _load_realesrgan(self):
        """Load Real-ESRGAN for initial upscale."""
        if self.realesrgan is not None:
            return
        self.realesrgan = TileUpscaler(model_name="realesrgan-x4plus")
        self.realesrgan._load_model()

    def upscale(self, input_path: str, output_path: str,
                prompt: str = "highly detailed, sharp, professional photography, 8K UHD",
                negative_prompt: str = "blurry, low quality, artifacts, noise",
                scale: int = 4,
                strength: float = 0.25,
                num_inference_steps: int = 30,
                guidance_scale: float = 7.5,
                **kwargs) -> str:
        """
        Upscale using Real-ESRGAN followed by SDXL refinement.

        Args:
            input_path: Input image path
            output_path: Output image path
            prompt: Enhancement prompt
            negative_prompt: What to avoid
            scale: Upscale factor (2 or 4)
            strength: SDXL refinement strength (0.15-0.35 recommended)
            num_inference_steps: SDXL diffusion steps
            guidance_scale: CFG scale
        """
        import time

        t0 = time.time()
        img = Image.open(input_path).convert('RGB')
        w, h = img.size

        print(f"SDXL Upscale: {w}x{h} -> {w*scale}x{h*scale}")

        # Step 1: Real-ESRGAN upscale
        print("Step 1: Real-ESRGAN upscale...")
        self._load_realesrgan()

        temp_path = Path(output_path).parent / "temp_esrgan.png"
        self.realesrgan.upscale(input_path, str(temp_path), scale=scale)
        upscaled = Image.open(temp_path).convert('RGB')

        # Step 2: SDXL refinement
        print(f"Step 2: SDXL refinement (strength={strength})...")
        self._load_model()

        # SDXL works best at 1024x1024, process in tiles if larger
        max_dim = 1024
        up_w, up_h = upscaled.size

        if up_w <= max_dim and up_h <= max_dim:
            # Can process whole image
            result = self._refine_image(upscaled, prompt, negative_prompt,
                                        strength, num_inference_steps, guidance_scale)
        else:
            # Process in tiles
            result = self._refine_tiled(upscaled, prompt, negative_prompt,
                                        strength, num_inference_steps, guidance_scale,
                                        tile_size=1024, overlap=128)

        # Save
        result.save(output_path, 'PNG', quality=95)

        # Cleanup temp
        if temp_path.exists():
            temp_path.unlink()

        elapsed = time.time() - t0
        print(f"SDXL Upscale complete: {result.size[0]}x{result.size[1]} ({elapsed:.1f}s)")

        return output_path

    def _refine_image(self, img: Image.Image, prompt: str, negative_prompt: str,
                      strength: float, steps: int, guidance: float) -> Image.Image:
        """Refine a single image with SDXL."""
        # Ensure dimensions divisible by 8
        w, h = img.size
        new_w = (w // 8) * 8
        new_h = (h // 8) * 8
        if new_w != w or new_h != h:
            img = img.resize((new_w, new_h), Image.LANCZOS)

        result = self.pipe(
            prompt=prompt,
            negative_prompt=negative_prompt,
            image=img,
            strength=strength,
            num_inference_steps=steps,
            guidance_scale=guidance
        ).images[0]

        # Resize back if needed
        if result.size != (w, h):
            result = result.resize((w, h), Image.LANCZOS)

        return result

    def _refine_tiled(self, img: Image.Image, prompt: str, negative_prompt: str,
                      strength: float, steps: int, guidance: float,
                      tile_size: int = 1024, overlap: int = 128) -> Image.Image:
        """Refine large image in tiles."""
        w, h = img.size
        result = img.copy()

        x_tiles = max(1, (w - overlap) // (tile_size - overlap) + 1)
        y_tiles = max(1, (h - overlap) // (tile_size - overlap) + 1)
        total_tiles = x_tiles * y_tiles

        print(f"  Processing {total_tiles} tiles...")

        tile_num = 0
        for y_idx in range(y_tiles):
            for x_idx in range(x_tiles):
                tile_num += 1

                # Calculate tile bounds
                x0 = x_idx * (tile_size - overlap)
                y0 = y_idx * (tile_size - overlap)
                x1 = min(x0 + tile_size, w)
                y1 = min(y0 + tile_size, h)

                # Extract tile
                tile = img.crop((x0, y0, x1, y1))

                # Refine tile
                try:
                    refined = self._refine_image(tile, prompt, negative_prompt,
                                                 strength, steps, guidance)

                    # Blend into result using cosine feathering
                    result = self._blend_tile(result, refined, x0, y0, overlap)

                except Exception as e:
                    print(f"  Tile {tile_num} failed: {e}")

                # Memory cleanup
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                gc.collect()

                if tile_num % 4 == 0 or tile_num == total_tiles:
                    print(f"  SDXL tiles: {tile_num}/{total_tiles}")

        return result

    def _blend_tile(self, canvas: Image.Image, tile: Image.Image,
                    x: int, y: int, overlap: int) -> Image.Image:
        """Blend tile with cosine feathering."""
        tile_w, tile_h = tile.size
        canvas_w, canvas_h = canvas.size
        feather = min(overlap, 64)

        mask_array = np.ones((tile_h, tile_w), dtype=np.float32)

        def cosine_falloff(d, max_d):
            if max_d <= 0:
                return 1.0
            t = min(d / max_d, 1.0)
            return 0.5 * (1 - np.cos(np.pi * t))

        if x > 0:
            for i in range(feather):
                mask_array[:, i] *= cosine_falloff(i, feather)
        if y > 0:
            for i in range(feather):
                mask_array[i, :] *= cosine_falloff(i, feather)
        if x + tile_w < canvas_w:
            for i in range(feather):
                mask_array[:, tile_w - 1 - i] *= cosine_falloff(i, feather)
        if y + tile_h < canvas_h:
            for i in range(feather):
                mask_array[tile_h - 1 - i, :] *= cosine_falloff(i, feather)

        from scipy.ndimage import gaussian_filter
        mask_array = gaussian_filter(mask_array, sigma=feather / 8)

        mask = Image.fromarray((mask_array * 255).astype(np.uint8))
        canvas.paste(tile, (x, y), mask)
        return canvas


# Factory function
def get_upscaler(upscaler_type: str = "realesrgan"):
    """
    Get an upscaler instance.

    Args:
        upscaler_type:
            - "realesrgan" (default) - Fast, good quality Real-ESRGAN 4x
            - "sd" - Stable Diffusion 1.5 creative upscale
            - "sdxl" - SDXL-based upscale (Real-ESRGAN + SDXL refinement)
            - "ultra" - Maximum quality multi-pass (slow, 5-40 min)
            - "simple" - Lanczos fallback (no AI)
    """
    if upscaler_type == "sd":
        return SDUpscaler()
    elif upscaler_type == "sdxl":
        return SDXLUpscaler()
    elif upscaler_type == "ultra":
        return UltraQualityUpscaler()
    elif upscaler_type == "simple":
        return TileUpscaler(model_name="simple")
    else:
        return TileUpscaler(model_name="realesrgan-x4plus")
