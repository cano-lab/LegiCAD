# postprocessor.py
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance
from scipy import ndimage
from pathlib import Path

print("=== POSTPROCESSOR MODULE LOADED ===")

class ArchitecturalPostProcessor:
    """Commercial-quality post-processing like Lumion/Enscape/V-Ray."""
    
    def __init__(self):
        print("PostProcessor ready!")
    
    def process(
        self,
        image: Image.Image,
        depth: Image.Image = None,
        edges: Image.Image = None,
        shadow: Image.Image = None,
        ao: Image.Image = None,
        # Color grading
        exposure: float = 0.0,  # -1 to 1
        contrast: float = 0.0,  # -1 to 1
        saturation: float = 0.0,  # -1 to 1
        temperature: float = 0.0,  # -1 (cool) to 1 (warm)
        vibrance: float = 0.0,  # -1 to 1
        # Effects
        bloom_intensity: float = 0.0,  # 0 to 1
        bloom_threshold: float = 0.8,  # 0 to 1
        vignette: float = 0.0,  # 0 to 1
        grain: float = 0.0,  # 0 to 1
        sharpness: float = 0.0,  # 0 to 1
        # Channel-based effects
        ao_strength: float = 0.0,  # 0 to 1
        edge_darkening: float = 0.0,  # 0 to 1
        shadow_boost: float = 0.0,  # 0 to 1
        depth_fog: float = 0.0,  # 0 to 1
        fog_color: tuple = (220, 230, 245),
        # Depth of field
        dof_amount: float = 0.0,  # 0 to 1
        dof_focus: float = 0.5,  # 0 to 1 (depth to focus on)
    ) -> Image.Image:
        """Apply post-processing effects."""
        
        img = np.array(image).astype(np.float32)
        h, w = img.shape[:2]
        
        # === COLOR GRADING ===
        
        # Exposure (multiply)
        if exposure != 0:
            factor = 2 ** exposure  # -1 = 0.5x, 0 = 1x, 1 = 2x
            img = img * factor
        
        # Contrast (S-curve around middle gray)
        if contrast != 0:
            factor = 1 + contrast
            img = (img - 128) * factor + 128
        
        # Temperature (shift red/blue)
        if temperature != 0:
            img[:,:,0] = img[:,:,0] * (1 + temperature * 0.1)  # Red
            img[:,:,2] = img[:,:,2] * (1 - temperature * 0.1)  # Blue
        
        # Saturation
        if saturation != 0:
            gray = np.mean(img, axis=2, keepdims=True)
            factor = 1 + saturation
            img = gray + (img - gray) * factor
        
        # Vibrance (saturate less-saturated colors more)
        if vibrance != 0:
            gray = np.mean(img, axis=2, keepdims=True)
            sat = np.std(img, axis=2, keepdims=True) / 128  # 0-1 saturation
            factor = 1 + vibrance * (1 - sat)  # Less saturated = more boost
            img = gray + (img - gray) * factor
        
        img = np.clip(img, 0, 255)
        
        # === CHANNEL-BASED EFFECTS ===
        
        # AO darkening
        if ao_strength > 0 and ao is not None:
            ao_array = np.array(ao.resize((w, h)).convert('L')).astype(np.float32) / 255
            ao_mask = 1 - (1 - ao_array[:,:,None]) * ao_strength
            img = img * ao_mask
        
        # Edge darkening (architectural line emphasis)
        if edge_darkening > 0 and edges is not None:
            edge_array = np.array(edges.resize((w, h)).convert('L')).astype(np.float32) / 255
            edge_mask = 1 - edge_array[:,:,None] * edge_darkening * 0.5
            img = img * edge_mask
        
        # Shadow boost
        if shadow_boost > 0 and shadow is not None:
            shadow_array = np.array(shadow.resize((w, h)).convert('L')).astype(np.float32) / 255
            shadow_mask = 1 - (1 - shadow_array[:,:,None]) * shadow_boost * 0.5
            img = img * shadow_mask
        
        # Depth fog
        if depth_fog > 0 and depth is not None:
            depth_array = np.array(depth.resize((w, h)).convert('L')).astype(np.float32) / 255
            fog = np.array(fog_color, dtype=np.float32)
            fog_mask = depth_array[:,:,None] * depth_fog
            img = img * (1 - fog_mask) + fog * fog_mask
        
        img = np.clip(img, 0, 255)
        
        # === EFFECTS ===
        
        # Bloom (glow on bright areas)
        if bloom_intensity > 0:
            # Find bright areas
            luminance = np.mean(img, axis=2)
            bright_mask = np.clip((luminance - bloom_threshold * 255) / (255 * (1 - bloom_threshold)), 0, 1)
            
            # Blur bright areas
            from scipy.ndimage import gaussian_filter
            bloom = np.zeros_like(img)
            for c in range(3):
                bright_channel = img[:,:,c] * bright_mask
                bloom[:,:,c] = gaussian_filter(bright_channel, sigma=w/30)
            
            # Add bloom
            img = img + bloom * bloom_intensity
        
        # Depth of field blur
        if dof_amount > 0 and depth is not None:
            depth_array = np.array(depth.resize((w, h)).convert('L')).astype(np.float32) / 255
            
            # Calculate blur amount based on distance from focus
            blur_map = np.abs(depth_array - dof_focus) * dof_amount * 20
            
            # Apply variable blur (simplified - use max blur)
            from scipy.ndimage import gaussian_filter
            max_blur = np.max(blur_map)
            if max_blur > 0.5:
                blurred = np.zeros_like(img)
                for c in range(3):
                    blurred[:,:,c] = gaussian_filter(img[:,:,c], sigma=max_blur)
                
                # Blend based on blur map
                blend = blur_map[:,:,None] / max_blur
                img = img * (1 - blend) + blurred * blend
        
        img = np.clip(img, 0, 255)
        
        # Convert for PIL operations
        result = Image.fromarray(img.astype(np.uint8))
        
        # Sharpness
        if sharpness > 0:
            enhancer = ImageEnhance.Sharpness(result)
            result = enhancer.enhance(1 + sharpness * 2)
        
        # Vignette
        if vignette > 0:
            result = self._apply_vignette(result, vignette)
        
        # Film grain
        if grain > 0:
            result = self._apply_grain(result, grain)
        
        return result
    
    def _apply_vignette(self, image: Image.Image, strength: float) -> Image.Image:
        """Apply vignette (darken edges)."""
        w, h = image.size
        img = np.array(image).astype(np.float32)
        
        # Create radial gradient
        y, x = np.ogrid[:h, :w]
        cx, cy = w / 2, h / 2
        r = np.sqrt((x - cx)**2 + (y - cy)**2)
        r = r / np.max(r)  # Normalize 0-1
        
        # Vignette curve (smooth falloff)
        vignette = 1 - (r ** 2) * strength
        vignette = np.clip(vignette, 0, 1)[:,:,None]
        
        img = img * vignette
        return Image.fromarray(img.astype(np.uint8))
    
    def _apply_grain(self, image: Image.Image, strength: float) -> Image.Image:
        """Apply film grain."""
        img = np.array(image).astype(np.float32)

        # Generate noise
        noise = np.random.normal(0, strength * 25, img.shape)

        # Add noise
        img = img + noise
        img = np.clip(img, 0, 255)

        return Image.fromarray(img.astype(np.uint8))

    def process_masked(
        self,
        image: Image.Image,
        mask: Image.Image,
        invert_mask: bool = False,
        feather: int = 10,
        **kwargs
    ) -> Image.Image:
        """
        Apply post-processing only to masked region.

        Args:
            image: Input image
            mask: Mask image (white = affected area)
            invert_mask: If True, affect the black area instead
            feather: Edge feathering in pixels
            **kwargs: All standard process() parameters

        Returns:
            Image with selective post-processing applied
        """
        # Ensure same size
        if mask.size != image.size:
            mask = mask.resize(image.size, Image.Resampling.LANCZOS)

        # Convert mask to float
        mask_np = np.array(mask.convert('L')).astype(np.float32) / 255.0

        # Invert if needed
        if invert_mask:
            mask_np = 1.0 - mask_np

        # Feather the mask edges
        if feather > 0:
            mask_np = ndimage.gaussian_filter(mask_np, sigma=feather / 2)

        # Process the full image
        processed = self.process(image, **kwargs)

        # Blend original and processed using mask
        original_np = np.array(image).astype(np.float32)
        processed_np = np.array(processed).astype(np.float32)
        mask_3d = mask_np[:, :, np.newaxis]

        result_np = original_np * (1 - mask_3d) + processed_np * mask_3d
        result_np = np.clip(result_np, 0, 255).astype(np.uint8)

        return Image.fromarray(result_np)


# Presets for quick access
POSTPROCESS_PRESETS = {
    'none': {},
    'subtle': {
        'contrast': 0.1,
        'saturation': 0.1,
        'sharpness': 0.2,
        'vignette': 0.1
    },
    'vivid': {
        'exposure': 0.1,
        'contrast': 0.2,
        'saturation': 0.3,
        'vibrance': 0.2,
        'sharpness': 0.3
    },
    'warm': {
        'temperature': 0.3,
        'exposure': 0.05,
        'contrast': 0.1,
        'saturation': 0.15,
        'vignette': 0.15
    },
    'cool': {
        'temperature': -0.2,
        'contrast': 0.15,
        'saturation': -0.1,
        'sharpness': 0.2
    },
    'dramatic': {
        'exposure': -0.1,
        'contrast': 0.3,
        'saturation': 0.1,
        'vignette': 0.25,
        'sharpness': 0.3
    },
    'film': {
        'contrast': 0.15,
        'saturation': -0.1,
        'temperature': 0.1,
        'vignette': 0.2,
        'grain': 0.15
    },
    'hdr': {
        'exposure': 0.1,
        'contrast': -0.1,
        'saturation': 0.2,
        'vibrance': 0.3,
        'sharpness': 0.4,
        'ao_strength': 0.3
    },
    'architectural': {
        'contrast': 0.15,
        'sharpness': 0.3,
        'edge_darkening': 0.2,
        'ao_strength': 0.25,
        'vignette': 0.1
    },
    'foggy': {
        'contrast': -0.1,
        'saturation': -0.2,
        'depth_fog': 0.3,
        'fog_color': (220, 225, 235)
    },
    'golden_hour': {
        'temperature': 0.4,
        'exposure': 0.1,
        'contrast': 0.2,
        'saturation': 0.2,
        'bloom_intensity': 0.2,
        'vignette': 0.15
    },
    'print_ready': {
        'saturation': 0.4,      # Boost saturation to survive CMYK conversion
        'vibrance': 0.3,        # Extra boost to less saturated colors
        'contrast': 0.2,        # Slight contrast boost
        'sharpness': 0.35,      # Crisp for print
        'exposure': -0.05       # Slightly darker (prints often come out lighter)
    }
}
