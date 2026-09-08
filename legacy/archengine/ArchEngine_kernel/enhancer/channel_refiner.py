import torch
from diffusers import StableDiffusionInpaintPipeline
from PIL import Image
import numpy as np

class ChannelRefiner:
    """Use channel maps to selectively refine regions of an image."""
    
    def __init__(self, model_id: str = "runwayml/stable-diffusion-inpainting"):
        print("Loading inpainting model...")
        self.pipe = StableDiffusionInpaintPipeline.from_pretrained(
            model_id,
            torch_dtype=torch.float16,
            safety_checker=None
        )
        self.pipe.to("cuda")
        self.pipe.enable_attention_slicing()
        print("Inpainting model ready!")
    
    def refine_by_material(
        self,
        image_path: str,
        material_id_path: str,
        target_color: tuple,
        prompt: str,
        output_path: str,
        tolerance: int = 30,
        negative_prompt: str = "blurry, distorted, ugly",
        strength: float = 0.8,
        guidance_scale: float = 7.5
    ) -> str:
        """
        Refine regions matching a specific material color.
        
        Args:
            image_path: The image to refine
            material_id_path: Material ID channel image
            target_color: RGB tuple of the material to refine (e.g., (255, 0, 0) for red)
            prompt: What to generate in that region
            tolerance: Color matching tolerance
        """
        image = Image.open(image_path).convert("RGB")
        material_id = Image.open(material_id_path).convert("RGB")
        
        # Resize material_id to match image if needed
        if material_id.size != image.size:
            material_id = material_id.resize(image.size, Image.Resampling.NEAREST)
        
        # Create mask from material ID
        mat_arr = np.array(material_id)
        target = np.array(target_color)
        
        # Find pixels within tolerance of target color
        diff = np.abs(mat_arr.astype(int) - target.astype(int))
        mask_arr = np.all(diff <= tolerance, axis=2).astype(np.uint8) * 255
        
        # Dilate mask slightly for better blending
        from scipy import ndimage
        mask_arr = ndimage.binary_dilation(mask_arr, iterations=3).astype(np.uint8) * 255
        
        mask = Image.fromarray(mask_arr, mode='L')
        
        print(f"Mask covers {np.mean(mask_arr > 0) * 100:.1f}% of image")
        
        # Resize for processing
        proc_size = (512, 512)
        image_resized = image.resize(proc_size, Image.Resampling.LANCZOS)
        mask_resized = mask.resize(proc_size, Image.Resampling.NEAREST)
        
        # Inpaint
        with torch.no_grad():
            result = self.pipe(
                prompt=prompt,
                negative_prompt=negative_prompt,
                image=image_resized,
                mask_image=mask_resized,
                strength=strength,
                guidance_scale=guidance_scale,
                num_inference_steps=25
            ).images[0]
        
        # Resize back to original
        result = result.resize(image.size, Image.Resampling.LANCZOS)
        
        # Blend result with original using mask
        result_arr = np.array(result).astype(np.float32)
        image_arr = np.array(image).astype(np.float32)
        mask_blend = np.array(mask).astype(np.float32)[:, :, np.newaxis] / 255.0
        
        # Smooth mask edges
        from scipy.ndimage import gaussian_filter
        mask_blend = gaussian_filter(mask_blend, sigma=3)
        
        blended = result_arr * mask_blend + image_arr * (1 - mask_blend)
        blended = np.clip(blended, 0, 255).astype(np.uint8)
        
        output = Image.fromarray(blended)
        output.save(output_path)
        
        # Also save mask for debugging
        mask.save(output_path.replace(".png", "_mask.png"))
        
        return output_path
    
    def refine_by_depth(
        self,
        image_path: str,
        depth_path: str,
        depth_range: tuple,
        prompt: str,
        output_path: str,
        **kwargs
    ) -> str:
        """
        Refine regions within a depth range.
        
        Args:
            depth_range: (min, max) depth values 0-255 to target
        """
        image = Image.open(image_path).convert("RGB")
        depth = Image.open(depth_path).convert("L")
        
        if depth.size != image.size:
            depth = depth.resize(image.size, Image.Resampling.NEAREST)
        
        depth_arr = np.array(depth)
        mask_arr = ((depth_arr >= depth_range[0]) & (depth_arr <= depth_range[1])).astype(np.uint8) * 255
        
        # Save as temp mask and use material refine
        mask = Image.fromarray(mask_arr, mode='L')
        temp_mask_path = output_path.replace(".png", "_depth_mask.png")
        
        # Create a fake material_id that's just the mask
        mask_rgb = Image.merge('RGB', [mask, Image.new('L', mask.size, 0), Image.new('L', mask.size, 0)])
        mask_rgb.save(temp_mask_path)
        
        return self.refine_by_material(
            image_path=image_path,
            material_id_path=temp_mask_path,
            target_color=(255, 0, 0),
            prompt=prompt,
            output_path=output_path,
            tolerance=10,
            **kwargs
        )


def get_material_colors(material_id_path: str) -> dict:
    """Analyze material ID image and return unique colors."""
    img = Image.open(material_id_path).convert("RGB")
    arr = np.array(img)
    
    # Reshape to list of pixels
    pixels = arr.reshape(-1, 3)
    
    # Find unique colors (excluding black background)
    unique = np.unique(pixels, axis=0)
    
    colors = {}
    for i, color in enumerate(unique):
        if not np.all(color == 0):  # Skip black
            colors[f"material_{i}"] = tuple(color)
    
    return colors