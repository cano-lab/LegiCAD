#!/usr/bin/env python3
"""
Fix color profile for PNG images so they print correctly.
Embeds sRGB ICC profile which ensures colors are interpreted correctly
by printers and PDF software.

Usage: python fix_color_profile.py image.png
       python fix_color_profile.py image.png --output fixed.png
"""

import argparse
import sys
from pathlib import Path
from PIL import Image, ImageCms


def fix_color_profile(input_path: str, output_path: str = None) -> bool:
    """Embed sRGB ICC profile in an image for proper print colors."""

    if output_path is None:
        output_path = input_path  # Overwrite original

    try:
        # Load image
        print(f"Loading: {input_path}")
        img = Image.open(input_path)

        # Check if already has ICC profile
        if 'icc_profile' in img.info:
            print("Image already has ICC profile embedded")
            # Re-embed to ensure it's sRGB

        # Convert to RGB if needed
        if img.mode != 'RGB':
            print(f"Converting from {img.mode} to RGB")
            img = img.convert('RGB')

        # Create sRGB profile
        srgb_profile = ImageCms.createProfile('sRGB')
        srgb_bytes = ImageCms.ImageCmsProfile(srgb_profile).tobytes()

        # Determine format from extension
        ext = Path(output_path).suffix.lower()

        if ext == '.png':
            img.save(output_path, 'PNG', icc_profile=srgb_bytes)
        elif ext in ['.jpg', '.jpeg']:
            img.save(output_path, 'JPEG', quality=95, icc_profile=srgb_bytes)
        elif ext == '.tiff' or ext == '.tif':
            img.save(output_path, 'TIFF', icc_profile=srgb_bytes)
        else:
            # Try generic save
            img.save(output_path, icc_profile=srgb_bytes)

        print(f"Saved with sRGB profile: {output_path}")
        return True

    except Exception as e:
        print(f"Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Embed sRGB ICC profile in images for correct print colors')
    parser.add_argument('input', help='Input image path')
    parser.add_argument('--output', '-o', help='Output path (default: overwrite input)')

    args = parser.parse_args()

    success = fix_color_profile(args.input, args.output)
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
