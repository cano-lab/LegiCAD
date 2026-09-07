"""
Photo-to-Family Processor

Analyzes photos of objects and generates geometry definitions
for creating parametric Revit families.

Supports:
- Multiple AI providers (Claude, Gemini, LM Studio)
- Multi-view photo analysis (front, side, top)
- Complex shapes with solids and voids
- Proportion estimation and dimension hints
"""

import json
import math
import os
import re
import requests
from typing import List, Dict, Any, Optional, Tuple

# Try to import AI providers
try:
    from anthropic import Anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


class PhotoToFamilyProcessor:
    """
    Processes photos of objects to generate Revit family geometry.
    """

    # Vision analysis prompt for extracting 3D object geometry
    ANALYSIS_PROMPT = """You are an expert 3D geometry analyst. Analyze this photo of an object and extract its geometric properties for CAD modeling.

CRITICAL: Output ONLY valid JSON, no explanations.

Extract:
1. object_type: What is this object? (table, chair, cabinet, shelf, etc.)
2. category: Revit category (Furniture, Casework, Generic Models, Specialty Equipment)
3. shape_type: Primary shape (box, cylinder, L-shape, U-shape, compound)
4. proportions: Relative dimensions as ratios (width:height:depth where width=1.0)
5. solids: Array of solid shapes making up the object
   - Each solid: {name, type (extrusion/cylinder), profile (2D points), depth, offset}
6. voids: Array of cutouts/holes (same format as solids, with cut_from field)
7. features: Notable features (legs, drawers, shelves, handles)
8. symmetry: x_symmetric, y_symmetric, z_symmetric (boolean)

For profiles, use normalized coordinates (0.0 to 1.0 range).
For proportions, width is always 1.0, express height and depth relative to width.

Example output for a simple desk:
{
    "object_type": "desk",
    "category": "Furniture",
    "shape_type": "compound",
    "proportions": {"width": 1.0, "height": 0.5, "depth": 0.4},
    "solids": [
        {"name": "top", "type": "extrusion", "profile": [[0,0], [1,0], [1,0.4], [0,0.4]], "depth": 0.02, "offset": [0, 0.48, 0]},
        {"name": "left_leg", "type": "extrusion", "profile": [[0,0], [0.05,0], [0.05,0.48], [0,0.48]], "depth": 0.35, "offset": [0, 0, 0.025]}
    ],
    "voids": [],
    "features": ["flat_top", "four_legs"],
    "symmetry": {"x_symmetric": true, "y_symmetric": false, "z_symmetric": false}
}

Respond with ONLY the JSON object, no markdown formatting or explanations."""

    MULTI_VIEW_PROMPT = """You are analyzing multiple views of the same object. Combine information from all views to create a complete 3D geometry definition.

Views provided: {views}

Use the front view for width/height, side view for depth/height confirmation, and top view for width/depth footprint.

Output ONLY valid JSON with the same structure as single-view analysis."""

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize processor with configuration.

        Args:
            config: Configuration dict with llm_provider and provider-specific settings
        """
        self.config = config or self._load_default_config()
        self.provider = self.config.get("llm_provider", "lmstudio")
        self._init_provider()

    def _load_default_config(self) -> Dict:
        """Load config from default location"""
        config_path = os.path.join(
            os.getenv('APPDATA', ''),
            'RevitMCP',
            'llm_config.json'
        )
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Failed to load config: {e}")

        return {
            "llm_provider": "lmstudio",
            "lmstudio": {"base_url": "http://localhost:1234/v1"},
            "claude": {"api_key_env": "ANTHROPIC_API_KEY"},
            "gemini": {"api_key_env": "GOOGLE_API_KEY"}
        }

    def _init_provider(self):
        """Initialize the selected AI provider"""
        self.client = None

        if self.provider == "claude" and CLAUDE_AVAILABLE:
            api_key = os.environ.get(self.config.get("claude", {}).get("api_key_env", "ANTHROPIC_API_KEY"))
            if api_key:
                self.client = Anthropic(api_key=api_key)
                print(f"   Initialized Claude provider")
            else:
                print(f"   Warning: Claude API key not found, falling back to LM Studio")
                self.provider = "lmstudio"

        elif self.provider == "gemini" and GEMINI_AVAILABLE:
            api_key = os.environ.get(self.config.get("gemini", {}).get("api_key_env", "GOOGLE_API_KEY"))
            if api_key:
                genai.configure(api_key=api_key)
                self.client = genai.GenerativeModel('gemini-1.5-flash')
                print(f"   Initialized Gemini provider")
            else:
                print(f"   Warning: Gemini API key not found, falling back to LM Studio")
                self.provider = "lmstudio"

        if self.provider == "lmstudio":
            self.lmstudio_url = self.config.get("lmstudio", {}).get("base_url", "http://localhost:1234/v1")
            print(f"   Using LM Studio at {self.lmstudio_url}")

    def analyze_photos(
        self,
        images: List[Dict[str, str]],
        object_hint: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Analyze one or more photos of an object.

        Args:
            images: List of {"data": base64_string, "view": "front"|"side"|"top"}
            object_hint: Optional hint about what the object is

        Returns:
            Geometry analysis with proportions, solids, voids, etc.
        """
        print(f"   Analyzing {len(images)} photo(s)...")

        # Build prompt
        if len(images) == 1:
            prompt = self.ANALYSIS_PROMPT
            if object_hint:
                prompt = f"The object is a {object_hint}.\n\n" + prompt
        else:
            view_names = [img.get("view", "unknown") for img in images]
            prompt = self.MULTI_VIEW_PROMPT.format(views=", ".join(view_names))
            if object_hint:
                prompt = f"The object is a {object_hint}.\n\n" + prompt

        # Call appropriate provider
        if self.provider == "claude":
            result = self._analyze_with_claude(images, prompt)
        elif self.provider == "gemini":
            result = self._analyze_with_gemini(images, prompt)
        else:
            result = self._analyze_with_lmstudio(images, prompt)

        # Parse and validate result
        analysis = self._parse_analysis(result)

        if analysis:
            print(f"   Detected: {analysis.get('object_type', 'unknown')} ({analysis.get('shape_type', 'unknown')})")

        return analysis

    def _analyze_with_claude(self, images: List[Dict], prompt: str) -> str:
        """Use Claude for vision analysis"""
        try:
            content = []

            for img in images:
                img_data = img["data"]
                if "," in img_data:
                    img_data = img_data.split(",")[1]

                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_data
                    }
                })

                if img.get("view"):
                    content.append({
                        "type": "text",
                        "text": f"[{img['view'].upper()} VIEW]"
                    })

            content.append({"type": "text", "text": prompt})

            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                messages=[{"role": "user", "content": content}]
            )

            return response.content[0].text

        except Exception as e:
            print(f"   Claude error: {e}")
            return "{}"

    def _analyze_with_gemini(self, images: List[Dict], prompt: str) -> str:
        """Use Gemini for vision analysis"""
        try:
            import PIL.Image
            import io
            import base64

            parts = []

            for img in images:
                img_data = img["data"]
                if "," in img_data:
                    img_data = img_data.split(",")[1]

                # Convert base64 to PIL Image
                image_bytes = base64.b64decode(img_data)
                pil_image = PIL.Image.open(io.BytesIO(image_bytes))
                parts.append(pil_image)

                if img.get("view"):
                    parts.append(f"[{img['view'].upper()} VIEW]")

            parts.append(prompt)

            response = self.client.generate_content(parts)
            return response.text

        except Exception as e:
            print(f"   Gemini error: {e}")
            return "{}"

    def _analyze_with_lmstudio(self, images: List[Dict], prompt: str) -> str:
        """Use LM Studio for vision analysis"""
        try:
            # Build content with images
            content = []

            for img in images:
                img_data = img["data"]
                if "," in img_data:
                    img_data = img_data.split(",")[1]

                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_data}"}
                })

                if img.get("view"):
                    content.append({
                        "type": "text",
                        "text": f"[{img['view'].upper()} VIEW]"
                    })

            content.append({"type": "text", "text": prompt})

            payload = {
                "model": "qwen-vl-chat",
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.1,
                "max_tokens": 2000
            }

            response = requests.post(
                f"{self.lmstudio_url}/chat/completions",
                json=payload,
                timeout=120
            )
            response.raise_for_status()

            return response.json()['choices'][0]['message']['content']

        except Exception as e:
            print(f"   LM Studio error: {e}")
            return "{}"

    def _parse_analysis(self, response: str) -> Dict[str, Any]:
        """Parse JSON from AI response"""
        try:
            # Try to find JSON in response
            match = re.search(r'\{[\s\S]*\}', response, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return self._validate_analysis(data)
        except json.JSONDecodeError as e:
            print(f"   JSON parse error: {e}")
        except Exception as e:
            print(f"   Parse error: {e}")

        return {}

    def _validate_analysis(self, data: Dict) -> Dict:
        """Validate and normalize analysis data"""
        # Ensure required fields
        defaults = {
            "object_type": "generic",
            "category": "Generic Models",
            "shape_type": "box",
            "proportions": {"width": 1.0, "height": 1.0, "depth": 1.0},
            "solids": [],
            "voids": [],
            "features": [],
            "symmetry": {"x_symmetric": False, "y_symmetric": False, "z_symmetric": False}
        }

        for key, default in defaults.items():
            if key not in data:
                data[key] = default

        # If no solids defined, create a default box
        if not data["solids"]:
            p = data["proportions"]
            data["solids"] = [{
                "name": "main_body",
                "type": "extrusion",
                "profile": [[0, 0], [1, 0], [1, p.get("height", 1.0)], [0, p.get("height", 1.0)]],
                "depth": p.get("depth", 1.0),
                "offset": [0, 0, 0]
            }]

        return data

    def estimate_dimensions(
        self,
        analysis: Dict,
        user_hints: Optional[Dict] = None
    ) -> Dict[str, float]:
        """
        Estimate real-world dimensions from analysis.

        Args:
            analysis: Output from analyze_photos
            user_hints: Optional dict with known dimensions {"width": 1.5, ...}

        Returns:
            Dict with Width, Height, Depth in feet
        """
        proportions = analysis.get("proportions", {})
        object_type = analysis.get("object_type", "generic").lower()

        # Default dimension estimates based on object type
        type_defaults = {
            "desk": {"width": 5.0, "height": 2.5, "depth": 2.0},
            "table": {"width": 4.0, "height": 2.5, "depth": 3.0},
            "chair": {"width": 1.5, "height": 3.0, "depth": 1.5},
            "cabinet": {"width": 3.0, "height": 6.0, "depth": 2.0},
            "shelf": {"width": 3.0, "height": 6.0, "depth": 1.0},
            "bookcase": {"width": 3.0, "height": 6.0, "depth": 1.0},
            "sofa": {"width": 7.0, "height": 3.0, "depth": 3.0},
            "bed": {"width": 5.0, "height": 2.5, "depth": 7.0},
            "generic": {"width": 3.0, "height": 3.0, "depth": 3.0}
        }

        # Get base dimensions for object type
        base = type_defaults.get(object_type, type_defaults["generic"])

        # Apply proportions to base
        width = base["width"]
        height = width * proportions.get("height", 1.0)
        depth = width * proportions.get("depth", 1.0)

        dimensions = {
            "Width": round(width, 2),
            "Height": round(height, 2),
            "Depth": round(depth, 2)
        }

        # Override with user hints
        if user_hints:
            for key, value in user_hints.items():
                if key in dimensions and value is not None:
                    dimensions[key] = float(value)

        print(f"   Estimated dimensions: {dimensions}")
        return dimensions

    def generate_family_geometry(
        self,
        analysis: Dict,
        dimensions: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Generate complete family geometry definition.

        Args:
            analysis: Output from analyze_photos
            dimensions: Real-world dimensions from estimate_dimensions

        Returns:
            Complete geometry definition ready for ParametricFamilyBuilder
        """
        width = dimensions.get("Width", 3.0)
        height = dimensions.get("Height", 3.0)
        depth = dimensions.get("Depth", 3.0)

        # Scale normalized profiles to real dimensions
        scaled_solids = []
        for solid in analysis.get("solids", []):
            scaled = self._scale_solid(solid, width, height, depth)
            scaled_solids.append(scaled)

        scaled_voids = []
        for void in analysis.get("voids", []):
            scaled = self._scale_solid(void, width, height, depth)
            scaled_voids.append(scaled)

        # Build parameters list
        parameters = [
            {"name": "Width", "value": width, "type": "Length"},
            {"name": "Height", "value": height, "type": "Length"},
            {"name": "Depth", "value": depth, "type": "Length"}
        ]

        # Add any detected sub-dimensions
        for solid in scaled_solids:
            if "thickness" in solid.get("name", "").lower():
                parameters.append({
                    "name": f"{solid['name']}_Thickness",
                    "value": solid.get("depth", 0.1),
                    "type": "Length"
                })

        return {
            "object_type": analysis.get("object_type", "generic"),
            "category": analysis.get("category", "Generic Models"),
            "proportions": analysis.get("proportions", {}),
            "solids": scaled_solids,
            "voids": scaled_voids,
            "parameters": parameters,
            "symmetry": analysis.get("symmetry", {}),
            "features": analysis.get("features", [])
        }

    def _scale_solid(
        self,
        solid: Dict,
        width: float,
        height: float,
        depth: float
    ) -> Dict:
        """Scale normalized solid definition to real dimensions"""
        scaled = dict(solid)

        # Scale profile points
        profile = solid.get("profile", [])
        scaled_profile = []
        for point in profile:
            # Profile is in XY plane, X = width, Y = height
            scaled_point = [
                point[0] * width,
                point[1] * height
            ]
            if len(point) > 2:
                scaled_point.append(point[2] * depth)
            scaled_profile.append(scaled_point)
        scaled["profile"] = scaled_profile

        # Scale depth
        solid_depth = solid.get("depth", 1.0)
        scaled["depth"] = solid_depth * depth

        # Scale offset
        offset = solid.get("offset", [0, 0, 0])
        scaled["offset"] = [
            offset[0] * width,
            offset[1] * height,
            offset[2] * depth if len(offset) > 2 else 0
        ]

        return scaled

    def process_photo_to_geometry(
        self,
        images: List[Dict[str, str]],
        object_hint: Optional[str] = None,
        dimension_hints: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Complete pipeline: photo -> analysis -> dimensions -> geometry.

        Args:
            images: List of {"data": base64_string, "view": "front"|"side"|"top"}
            object_hint: Optional hint about object type
            dimension_hints: Optional known dimensions

        Returns:
            Complete geometry definition for family creation
        """
        # Step 1: Analyze
        analysis = self.analyze_photos(images, object_hint)
        if not analysis:
            return {"error": "Failed to analyze photo"}

        # Step 2: Estimate dimensions
        dimensions = self.estimate_dimensions(analysis, dimension_hints)

        # Step 3: Generate geometry
        geometry = self.generate_family_geometry(analysis, dimensions)

        return geometry


# Standalone test
if __name__ == "__main__":
    processor = PhotoToFamilyProcessor()

    # Test with a simple prompt (no actual image)
    print("\nPhotoToFamilyProcessor initialized")
    print(f"Provider: {processor.provider}")
