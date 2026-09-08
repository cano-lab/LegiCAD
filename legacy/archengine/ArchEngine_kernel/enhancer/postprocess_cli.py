#!/usr/bin/env python3
"""
Command-line interface for post-processing rendered images.
Usage: python postprocess_cli.py --input image.png --output processed.png --preset architectural
"""

import argparse
import sys
from pathlib import Path
from PIL import Image

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from postprocessor import ArchitecturalPostProcessor, POSTPROCESS_PRESETS


def main():
    parser = argparse.ArgumentParser(description='Post-process rendered images')
    parser.add_argument('--input', '-i', required=True, help='Input image path')
    parser.add_argument('--output', '-o', required=True, help='Output image path')
    parser.add_argument('--preset', '-p', default='architectural',
                        choices=list(POSTPROCESS_PRESETS.keys()),
                        help='Post-processing preset')

    # Optional manual overrides
    parser.add_argument('--exposure', type=float, help='Exposure adjustment (-1 to 1)')
    parser.add_argument('--contrast', type=float, help='Contrast adjustment (-1 to 1)')
    parser.add_argument('--saturation', type=float, help='Saturation adjustment (-1 to 1)')
    parser.add_argument('--vibrance', type=float, help='Vibrance adjustment (-1 to 1)')
    parser.add_argument('--sharpness', type=float, help='Sharpness (0 to 1)')
    parser.add_argument('--bloom', type=float, help='Bloom intensity (0 to 1)')
    parser.add_argument('--vignette', type=float, help='Vignette strength (0 to 1)')

    args = parser.parse_args()

    # Load image
    print(f"[PostProcess] Loading: {args.input}")
    try:
        image = Image.open(args.input).convert('RGB')
    except Exception as e:
        print(f"[PostProcess] Error loading image: {e}")
        return 1

    # Get preset parameters
    params = POSTPROCESS_PRESETS.get(args.preset, {}).copy()

    # Apply manual overrides if provided
    if args.exposure is not None:
        params['exposure'] = args.exposure
    if args.contrast is not None:
        params['contrast'] = args.contrast
    if args.saturation is not None:
        params['saturation'] = args.saturation
    if args.vibrance is not None:
        params['vibrance'] = args.vibrance
    if args.sharpness is not None:
        params['sharpness'] = args.sharpness
    if args.bloom is not None:
        params['bloom_intensity'] = args.bloom
    if args.vignette is not None:
        params['vignette'] = args.vignette

    print(f"[PostProcess] Applying preset: {args.preset}")
    print(f"[PostProcess] Parameters: {params}")

    # Process
    processor = ArchitecturalPostProcessor()
    result = processor.process(image, **params)

    # Save with embedded sRGB ICC profile for proper color in print/PDF
    print(f"[PostProcess] Saving: {args.output}")

    # Try to embed sRGB ICC profile for proper color management
    try:
        from PIL import ImageCms
        srgb_profile = ImageCms.createProfile('sRGB')
        srgb_bytes = ImageCms.ImageCmsProfile(srgb_profile).tobytes()
        result.save(args.output, quality=95, icc_profile=srgb_bytes)
        print("[PostProcess] Saved with sRGB ICC profile embedded")
    except Exception as e:
        print(f"[PostProcess] Could not embed ICC profile: {e}")
        result.save(args.output, quality=95)

    print("[PostProcess] Done!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
