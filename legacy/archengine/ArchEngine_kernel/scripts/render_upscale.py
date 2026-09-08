#!/usr/bin/env python3
"""
Upscale rendered images using Real-ESRGAN or Lanczos.
"""

import argparse
import sys
from pathlib import Path

def upscale_with_realesrgan(input_path: str, output_path: str, scale: int = 2) -> bool:
    """Upscale using Real-ESRGAN via render_server API."""
    import json
    import urllib.request

    server_url = "http://localhost:5000"
    payload = {
        "input_path": str(Path(input_path).resolve()),
        "output_path": str(Path(output_path).resolve()),
        "scale": scale,
        "method": "realesrgan"
    }

    try:
        url = f"{server_url}/api/upscale_image"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("status") == "ok":
                print(f"Upscaled to {output_path}")
                return True
            else:
                print(f"Server error: {result}", file=sys.stderr)
                return False
    except Exception as e:
        print(f"Server not available, falling back to PIL: {e}", file=sys.stderr)
        return upscale_with_pil(input_path, output_path, scale, "lanczos")


def upscale_with_pil(input_path: str, output_path: str, scale: int = 2, method: str = "lanczos") -> bool:
    """Upscale using PIL (fallback method)."""
    try:
        from PIL import Image

        img = Image.open(input_path)
        new_size = (img.width * scale, img.height * scale)

        if method == "lanczos":
            resampling = Image.Resampling.LANCZOS
        elif method == "bicubic":
            resampling = Image.Resampling.BICUBIC
        else:
            resampling = Image.Resampling.BILINEAR

        upscaled = img.resize(new_size, resampling)

        # Create output directory if needed
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        upscaled.save(output_path)
        print(f"Upscaled {img.width}x{img.height} -> {new_size[0]}x{new_size[1]}: {output_path}")
        return True

    except ImportError:
        print("PIL not available. Install with: pip install Pillow", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Upscale failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Upscale rendered images")
    parser.add_argument("--input", "-i", required=True, help="Input image path")
    parser.add_argument("--output", "-o", required=True, help="Output image path")
    parser.add_argument("--scale", "-s", type=int, default=2, choices=[2, 4], help="Upscale factor")
    parser.add_argument("--method", "-m", default="realesrgan",
                        choices=["realesrgan", "lanczos", "bicubic"],
                        help="Upscale method")

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Input file not found: {args.input}", file=sys.stderr)
        return 1

    if args.method == "realesrgan":
        success = upscale_with_realesrgan(args.input, args.output, args.scale)
    else:
        success = upscale_with_pil(args.input, args.output, args.scale, args.method)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
