#!/usr/bin/env python3
"""
Material Preview and Management Tool

Interactive tool for:
- Previewing materials on test geometry
- Adjusting UV scale and material parameters
- Upscaling textures via render_server
- Generating new materials via AI
"""

import argparse
import json
import os
import sys
import shutil
import urllib.request
import urllib.error
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("Warning: PIL not installed. Install with: pip install Pillow")


@dataclass
class MaterialInfo:
    """Information about a loaded material."""
    name: str
    path: Path
    textures: Dict[str, Path] = field(default_factory=dict)
    resolution: tuple = (512, 512)

    def get_texture(self, tex_type: str) -> Optional[Path]:
        return self.textures.get(tex_type)

    def has_texture(self, tex_type: str) -> bool:
        return tex_type in self.textures


class MaterialLibrary:
    """Manages the material library."""

    TEXTURE_TYPES = ["albedo", "normal", "roughness", "metallic", "ao", "height", "emissive", "opacity"]
    TEXTURE_ALIASES = {
        "albedo": ["albedo", "diffuse", "basecolor", "base_color", "color"],
        "normal": ["normal", "norm", "nrm"],
        "roughness": ["roughness", "rough"],
        "metallic": ["metallic", "metal", "metalness"],
        "ao": ["ao", "ambient_occlusion", "occlusion"],
        "height": ["height", "displacement", "disp", "bump"],
        "emissive": ["emissive", "emission", "emit", "glow"],
        "opacity": ["opacity", "alpha", "transparency"],
    }

    def __init__(self, root_path: Path):
        self.root = root_path
        self.materials: Dict[str, MaterialInfo] = {}
        self._scan_materials()

    def _find_texture(self, directory: Path, tex_type: str) -> Optional[Path]:
        """Find a texture file by type."""
        aliases = self.TEXTURE_ALIASES.get(tex_type, [tex_type])
        for alias in aliases:
            for ext in [".png", ".jpg", ".jpeg", ".tga"]:
                path = directory / f"{alias}{ext}"
                if path.exists():
                    return path
        return None

    def _scan_materials(self):
        """Scan the materials directory."""
        if not self.root.exists():
            return

        for entry in sorted(self.root.iterdir()):
            if not entry.is_dir():
                continue

            # Skip special directories, scan their subdirs
            if entry.name in ["walls", "roofs", "floors", "windows", "doors"]:
                for subentry in sorted(entry.iterdir()):
                    if subentry.is_dir():
                        self._load_material(subentry, f"{entry.name}/{subentry.name}")
            else:
                self._load_material(entry, entry.name)

    def _load_material(self, path: Path, name: str):
        """Load a single material."""
        mat = MaterialInfo(name=name, path=path)

        for tex_type in self.TEXTURE_TYPES:
            tex_path = self._find_texture(path, tex_type)
            if tex_path:
                mat.textures[tex_type] = tex_path
                if tex_type == "albedo" and HAS_PIL:
                    try:
                        with Image.open(tex_path) as img:
                            mat.resolution = img.size
                    except:
                        pass

        if mat.textures:
            self.materials[name] = mat

    def list_materials(self) -> List[str]:
        """Get list of material names."""
        return sorted(self.materials.keys())

    def get_material(self, name: str) -> Optional[MaterialInfo]:
        """Get a material by name."""
        return self.materials.get(name)

    def get_categories(self) -> Dict[str, List[str]]:
        """Get materials grouped by category."""
        categories = {}
        for name in self.materials:
            if "/" in name:
                cat = name.split("/")[0]
            else:
                cat = name.split("_")[0]
            categories.setdefault(cat, []).append(name)
        return categories


class RenderServerClient:
    """Client for the render_server API."""

    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url.rstrip("/")

    def _post_json(self, endpoint: str, payload: dict, timeout: int = 600) -> dict:
        """POST JSON to an endpoint."""
        url = f"{self.base_url}{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.URLError as e:
            return {"status": "error", "error": str(e)}

    def _get_json(self, endpoint: str, timeout: int = 30) -> dict:
        """GET JSON from an endpoint."""
        url = f"{self.base_url}{endpoint}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.URLError as e:
            return {"status": "error", "error": str(e)}

    def is_available(self) -> bool:
        """Check if render_server is available."""
        result = self._get_json("/api/health")
        return result.get("status") == "ok"

    def upscale_texture(self, input_path: str, output_path: str,
                        scale: int = 4, method: str = "realesrgan") -> dict:
        """Upscale a texture using the render_server."""
        payload = {
            "input_path": str(input_path),
            "output_path": str(output_path),
            "scale": scale,
            "method": method
        }
        return self._post_json("/api/upscale", payload)

    def generate_material(self, prompt: str, name: str,
                          output_root: str, size: int = 1024,
                          **kwargs) -> dict:
        """Generate a new material using AI."""
        payload = {
            "prompt": prompt,
            "name": name,
            "output_root": output_root,
            "size": size,
            "tileable": True,
            **kwargs
        }
        return self._post_json("/api/materials/generate", payload, timeout=600)


def create_material_preview_grid(library: MaterialLibrary, output_path: Path,
                                  cols: int = 6, tile_size: int = 128):
    """Create a grid preview of all materials."""
    if not HAS_PIL:
        print("PIL required for preview grid")
        return

    materials = library.list_materials()
    rows = (len(materials) + cols - 1) // cols

    grid_w = cols * tile_size
    grid_h = rows * tile_size

    grid = Image.new("RGB", (grid_w, grid_h), (40, 40, 40))
    draw = ImageDraw.Draw(grid)

    try:
        font = ImageFont.truetype("arial.ttf", 10)
    except:
        font = ImageFont.load_default()

    for i, name in enumerate(materials):
        mat = library.get_material(name)
        if not mat:
            continue

        x = (i % cols) * tile_size
        y = (i // cols) * tile_size

        # Load albedo thumbnail
        albedo = mat.get_texture("albedo")
        if albedo:
            try:
                with Image.open(albedo) as img:
                    img = img.convert("RGB")
                    img = img.resize((tile_size - 4, tile_size - 20), Image.Resampling.LANCZOS)
                    grid.paste(img, (x + 2, y + 2))
            except Exception as e:
                draw.rectangle([x + 2, y + 2, x + tile_size - 2, y + tile_size - 22], fill=(60, 60, 60))

        # Draw label
        label = name.split("/")[-1][:15]
        draw.text((x + 2, y + tile_size - 16), label, fill=(200, 200, 200), font=font)

    grid.save(output_path)
    print(f"Preview grid saved to: {output_path}")


def create_material_sphere_preview(material: MaterialInfo, output_path: Path, size: int = 256):
    """Create a sphere preview of a material (simplified 2D representation)."""
    if not HAS_PIL:
        print("PIL required for sphere preview")
        return

    # Load albedo
    albedo_path = material.get_texture("albedo")
    if not albedo_path:
        print(f"No albedo texture for {material.name}")
        return

    with Image.open(albedo_path) as albedo:
        albedo = albedo.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)

        # Create sphere mask
        mask = Image.new("L", (size, size), 0)
        mask_draw = ImageDraw.Draw(mask)
        margin = size // 16
        mask_draw.ellipse([margin, margin, size - margin, size - margin], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(2))

        # Apply spherical shading (simple gradient overlay)
        import math
        shading = Image.new("L", (size, size), 128)
        for y in range(size):
            for x in range(size):
                cx, cy = size // 2, size // 2
                dx = (x - cx) / (size / 2)
                dy = (y - cy) / (size / 2)
                dist = math.sqrt(dx * dx + dy * dy)
                if dist <= 1.0:
                    # Simple diffuse shading
                    nx = dx
                    ny = dy
                    nz = math.sqrt(max(0, 1 - dx*dx - dy*dy))
                    # Light from top-left
                    light = max(0, -0.5 * nx - 0.5 * ny + 0.7 * nz)
                    shade = int(80 + 175 * light)
                    shading.putpixel((x, y), shade)

        # Composite
        result = Image.new("RGB", (size, size), (30, 30, 30))

        # Apply shading to albedo
        shaded = Image.blend(albedo, Image.new("RGB", (size, size), (0, 0, 0)), 0.0)
        shaded = Image.composite(
            Image.eval(albedo, lambda x: int(x * 1.2)),
            Image.eval(albedo, lambda x: int(x * 0.6)),
            shading
        )

        result.paste(shaded, (0, 0), mask)
        result.save(output_path)
        print(f"Sphere preview saved to: {output_path}")


def upscale_material(material: MaterialInfo, output_dir: Path,
                     server: RenderServerClient, scale: int = 4,
                     method: str = "realesrgan"):
    """Upscale all textures in a material."""
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nUpscaling material: {material.name}")
    print(f"Current resolution: {material.resolution[0]}x{material.resolution[1]}")
    print(f"Target resolution: {material.resolution[0] * scale}x{material.resolution[1] * scale}")

    for tex_type, tex_path in material.textures.items():
        output_path = output_dir / f"{tex_type}{tex_path.suffix}"

        print(f"  Upscaling {tex_type}...", end=" ", flush=True)

        result = server.upscale_texture(str(tex_path), str(output_path), scale, method)

        if result.get("status") == "ok":
            print("OK")
        else:
            print(f"FAILED: {result.get('error', 'Unknown error')}")
            # Copy original as fallback
            shutil.copy(tex_path, output_path)

    print(f"Upscaled textures saved to: {output_dir}")


def interactive_mode(library: MaterialLibrary, server: Optional[RenderServerClient] = None):
    """Interactive material browser."""
    print("\n" + "=" * 60)
    print("Material Preview Tool - Interactive Mode")
    print("=" * 60)

    categories = library.get_categories()

    while True:
        print("\nCategories:")
        cat_list = sorted(categories.keys())
        for i, cat in enumerate(cat_list):
            print(f"  {i + 1}. {cat} ({len(categories[cat])} materials)")

        print("\nCommands:")
        print("  [number] - Browse category")
        print("  list     - List all materials")
        print("  preview  - Generate preview grid")
        print("  generate - Generate new material (requires render_server)")
        print("  upscale  - Upscale material textures (requires render_server)")
        print("  quit     - Exit")

        cmd = input("\n> ").strip().lower()

        if cmd == "quit" or cmd == "q":
            break
        elif cmd == "list":
            print("\nAll materials:")
            for name in library.list_materials():
                mat = library.get_material(name)
                res = f"{mat.resolution[0]}x{mat.resolution[1]}" if mat else "?"
                tex_count = len(mat.textures) if mat else 0
                print(f"  {name}: {tex_count} textures, {res}")
        elif cmd == "preview":
            output = library.root / "preview_grid.png"
            create_material_preview_grid(library, output)
        elif cmd == "generate":
            if not server or not server.is_available():
                print("Error: render_server not available")
                continue

            print("\nGenerate New Material")
            prompt = input("Prompt (e.g. 'weathered red brick wall'): ").strip()
            if not prompt:
                continue
            name = input("Material name (e.g. 'brick_weathered_red'): ").strip()
            if not name:
                continue

            print(f"\nGenerating '{name}' from prompt: {prompt}")
            result = server.generate_material(prompt, name, str(library.root))

            if result.get("status") == "ok":
                print(f"Material generated: {result.get('path')}")
                library._scan_materials()  # Refresh
            else:
                print(f"Generation failed: {result.get('error', 'Unknown error')}")
        elif cmd == "upscale":
            if not server or not server.is_available():
                print("Error: render_server not available")
                continue

            mat_name = input("Material name to upscale: ").strip()
            mat = library.get_material(mat_name)
            if not mat:
                print(f"Material not found: {mat_name}")
                continue

            output_dir = library.root / f"{mat_name}_upscaled"
            upscale_material(mat, output_dir, server)
        elif cmd.isdigit():
            idx = int(cmd) - 1
            if 0 <= idx < len(cat_list):
                cat = cat_list[idx]
                print(f"\n{cat.upper()} materials:")
                for name in sorted(categories[cat]):
                    mat = library.get_material(name)
                    res = f"{mat.resolution[0]}x{mat.resolution[1]}" if mat else "?"
                    print(f"  {name}: {res}")
        else:
            print("Unknown command")


def main():
    parser = argparse.ArgumentParser(description="Material Preview and Management Tool")
    parser.add_argument("--path", default="materials", help="Path to materials directory")
    parser.add_argument("--server", default="http://localhost:5000", help="render_server URL")
    parser.add_argument("--list", action="store_true", help="List all materials")
    parser.add_argument("--preview", action="store_true", help="Generate preview grid")
    parser.add_argument("--sphere", type=str, help="Generate sphere preview for material")
    parser.add_argument("--upscale", type=str, help="Upscale material textures")
    parser.add_argument("--scale", type=int, default=4, choices=[2, 4], help="Upscale factor (2 or 4)")
    parser.add_argument("--method", type=str, default="realesrgan", choices=["realesrgan", "simple"], help="Upscale method")
    parser.add_argument("--generate", type=str, help="Generate material from prompt")
    parser.add_argument("--name", type=str, help="Name for generated material")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    args = parser.parse_args()

    # Find materials directory
    materials_root = Path(args.path)
    if not materials_root.exists():
        script_dir = Path(__file__).parent.parent
        materials_root = script_dir / "materials"

    if not materials_root.exists():
        print(f"Error: Materials directory not found: {materials_root}")
        return 1

    print(f"Materials directory: {materials_root}")

    # Load library
    library = MaterialLibrary(materials_root)
    print(f"Loaded {len(library.materials)} materials")

    # Connect to render_server if needed
    server = None
    if args.upscale or args.generate or args.interactive:
        server = RenderServerClient(args.server)
        if server.is_available():
            print(f"render_server connected: {args.server}")
        else:
            print(f"Warning: render_server not available at {args.server}")
            server = None

    # Execute command
    if args.list:
        for name in library.list_materials():
            mat = library.get_material(name)
            textures = ", ".join(mat.textures.keys()) if mat else ""
            print(f"{name}: {textures}")
    elif args.preview:
        output = materials_root / "preview_grid.png"
        create_material_preview_grid(library, output)
    elif args.sphere:
        mat = library.get_material(args.sphere)
        if mat:
            output = materials_root / f"{args.sphere.replace('/', '_')}_sphere.png"
            create_material_sphere_preview(mat, output)
        else:
            print(f"Material not found: {args.sphere}")
    elif args.upscale:
        mat = library.get_material(args.upscale)
        if mat and server:
            output_dir = materials_root / f"{args.upscale.replace('/', '_')}_upscaled"
            upscale_material(mat, output_dir, server, scale=args.scale, method=args.method)
        elif not mat:
            print(f"Material not found: {args.upscale}")
        else:
            print("render_server not available")
    elif args.generate:
        if server and args.name:
            result = server.generate_material(args.generate, args.name, str(materials_root))
            print(json.dumps(result, indent=2))
        elif not args.name:
            print("--name required for generation")
        else:
            print("render_server not available")
    elif args.interactive:
        interactive_mode(library, server)
    else:
        # Default: show summary
        print("\nMaterial Library Summary:")
        categories = library.get_categories()
        for cat, mats in sorted(categories.items()):
            print(f"  {cat}: {len(mats)} materials")
        print(f"\nTotal: {len(library.materials)} materials")
        print("\nUse --interactive for full browsing, or --help for options")

    return 0


if __name__ == "__main__":
    sys.exit(main())
