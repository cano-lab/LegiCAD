#!/usr/bin/env python3
"""
Material Library Validation Tool

Validates all materials in the library for:
- Required texture presence (albedo, normal, roughness)
- Optional texture presence (metallic, ao, height, emissive, opacity)
- Texture resolution consistency
- File format validity
- Generates updated material_map.json
"""

import argparse
import json
import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from PIL import Image


@dataclass
class TextureInfo:
    """Info about a single texture file."""
    path: str
    width: int
    height: int
    format: str
    channels: int
    size_kb: float


@dataclass
class MaterialValidation:
    """Validation result for a material."""
    name: str
    path: str
    textures: dict = field(default_factory=dict)
    missing_required: list = field(default_factory=list)
    missing_optional: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    resolution: Optional[tuple] = None

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0 and len(self.missing_required) == 0


# Required and optional texture types
REQUIRED_TEXTURES = ["albedo"]
OPTIONAL_TEXTURES = ["normal", "roughness", "metallic", "ao", "height", "emissive", "opacity"]
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
VALID_EXTENSIONS = [".png", ".jpg", ".jpeg", ".tga", ".bmp"]


def find_texture(directory: Path, texture_type: str) -> Optional[Path]:
    """Find a texture file by type, checking aliases."""
    aliases = TEXTURE_ALIASES.get(texture_type, [texture_type])

    for alias in aliases:
        for ext in VALID_EXTENSIONS:
            path = directory / f"{alias}{ext}"
            if path.exists():
                return path
    return None


def get_texture_info(path: Path) -> Optional[TextureInfo]:
    """Get information about a texture file."""
    try:
        with Image.open(path) as img:
            return TextureInfo(
                path=str(path),
                width=img.width,
                height=img.height,
                format=img.format or "Unknown",
                channels=len(img.getbands()),
                size_kb=path.stat().st_size / 1024
            )
    except Exception as e:
        return None


def validate_material(material_path: Path) -> MaterialValidation:
    """Validate a single material directory."""
    name = material_path.name
    result = MaterialValidation(name=name, path=str(material_path))

    # Check for required textures
    for tex_type in REQUIRED_TEXTURES:
        tex_path = find_texture(material_path, tex_type)
        if tex_path:
            info = get_texture_info(tex_path)
            if info:
                result.textures[tex_type] = info
                if result.resolution is None:
                    result.resolution = (info.width, info.height)
            else:
                result.errors.append(f"Failed to read {tex_type} texture: {tex_path}")
        else:
            result.missing_required.append(tex_type)
            result.errors.append(f"Missing required texture: {tex_type}")

    # Check for optional textures
    for tex_type in OPTIONAL_TEXTURES:
        tex_path = find_texture(material_path, tex_type)
        if tex_path:
            info = get_texture_info(tex_path)
            if info:
                result.textures[tex_type] = info
                # Check resolution consistency
                if result.resolution and (info.width, info.height) != result.resolution:
                    result.warnings.append(
                        f"{tex_type} resolution ({info.width}x{info.height}) differs from albedo ({result.resolution[0]}x{result.resolution[1]})"
                    )
            else:
                result.warnings.append(f"Failed to read {tex_type} texture: {tex_path}")
        else:
            result.missing_optional.append(tex_type)

    # Check for power-of-two resolution
    if result.resolution:
        w, h = result.resolution
        if not (w > 0 and (w & (w - 1)) == 0) or not (h > 0 and (h & (h - 1)) == 0):
            result.warnings.append(f"Resolution {w}x{h} is not power-of-two")

    return result


def validate_library(materials_root: Path) -> list:
    """Validate all materials in the library."""
    results = []

    for entry in sorted(materials_root.iterdir()):
        if not entry.is_dir():
            continue
        # Skip special directories
        if entry.name in ["walls", "roofs", "floors", "windows", "doors"]:
            # Check subdirectories
            for subentry in sorted(entry.iterdir()):
                if subentry.is_dir():
                    result = validate_material(subentry)
                    result.name = f"{entry.name}/{subentry.name}"
                    results.append(result)
        else:
            result = validate_material(entry)
            results.append(result)

    return results


def generate_material_map(results: list, existing_map: dict = None) -> dict:
    """Generate an updated material_map.json from validation results."""
    material_map = existing_map or {
        "category_defaults": {},
        "name_overrides": {},
        "materials": {}
    }

    for result in results:
        if not result.is_valid:
            continue

        material_entry = {
            "name": result.name.replace("_", " ").title(),
            "textures": {}
        }

        for tex_type, info in result.textures.items():
            material_entry["textures"][tex_type] = os.path.basename(info.path)

        if result.resolution:
            material_entry["resolution"] = list(result.resolution)

        material_map["materials"][result.name] = material_entry

    return material_map


def print_report(results: list, verbose: bool = False):
    """Print validation report."""
    valid_count = sum(1 for r in results if r.is_valid)
    warning_count = sum(len(r.warnings) for r in results)
    error_count = sum(len(r.errors) for r in results)

    print(f"\n{'=' * 60}")
    print(f"Material Library Validation Report")
    print(f"{'=' * 60}")
    print(f"Total materials:  {len(results)}")
    print(f"Valid materials:  {valid_count}")
    print(f"With warnings:    {sum(1 for r in results if r.warnings)}")
    print(f"With errors:      {sum(1 for r in results if r.errors)}")
    print(f"{'=' * 60}\n")

    # Group by category
    categories = {}
    for result in results:
        if "/" in result.name:
            cat = result.name.split("/")[0]
        else:
            cat = result.name.split("_")[0] if "_" in result.name else "other"
        categories.setdefault(cat, []).append(result)

    for cat, mats in sorted(categories.items()):
        print(f"\n{cat.upper()} ({len(mats)} materials)")
        print("-" * 40)
        for result in mats:
            status = "[OK]" if result.is_valid else "[ERROR]"
            tex_count = len(result.textures)
            res = f"{result.resolution[0]}x{result.resolution[1]}" if result.resolution else "N/A"
            print(f"  {status} {result.name}: {tex_count} textures, {res}")

            if verbose:
                for tex_type, info in result.textures.items():
                    print(f"       - {tex_type}: {info.width}x{info.height} ({info.size_kb:.1f}KB)")
                for warning in result.warnings:
                    print(f"       ! {warning}")
                for error in result.errors:
                    print(f"       X {error}")

    # Summary of missing textures
    print(f"\n{'=' * 60}")
    print("Missing Texture Summary")
    print(f"{'=' * 60}")

    missing_counts = {}
    for result in results:
        for tex in result.missing_optional:
            missing_counts[tex] = missing_counts.get(tex, 0) + 1

    for tex, count in sorted(missing_counts.items(), key=lambda x: -x[1]):
        pct = count / len(results) * 100
        print(f"  {tex}: missing in {count} materials ({pct:.0f}%)")


def main():
    parser = argparse.ArgumentParser(description="Validate material library")
    parser.add_argument("--path", default="materials", help="Path to materials directory")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--output-map", "-o", help="Output updated material_map.json")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    materials_root = Path(args.path)
    if not materials_root.exists():
        # Try relative to script location
        script_dir = Path(__file__).parent.parent
        materials_root = script_dir / "materials"

    if not materials_root.exists():
        print(f"Error: Materials directory not found: {materials_root}", file=sys.stderr)
        return 1

    print(f"Validating materials in: {materials_root}")
    results = validate_library(materials_root)

    if args.json:
        output = []
        for r in results:
            output.append({
                "name": r.name,
                "valid": r.is_valid,
                "textures": {k: {"width": v.width, "height": v.height} for k, v in r.textures.items()},
                "missing_required": r.missing_required,
                "missing_optional": r.missing_optional,
                "warnings": r.warnings,
                "errors": r.errors,
            })
        print(json.dumps(output, indent=2))
    else:
        print_report(results, args.verbose)

    if args.output_map:
        existing_map = None
        map_path = materials_root / "material_map.json"
        if map_path.exists():
            with open(map_path) as f:
                existing_map = json.load(f)

        new_map = generate_material_map(results, existing_map)

        output_path = Path(args.output_map)
        with open(output_path, "w") as f:
            json.dump(new_map, f, indent=2)
        print(f"\nUpdated material map written to: {output_path}")

    return 0 if all(r.is_valid for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
