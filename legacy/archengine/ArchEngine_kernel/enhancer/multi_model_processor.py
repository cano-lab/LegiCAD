"""
Multi-Model Sketch-to-Plan Processor
====================================
Ensemble architecture using multiple small models working together:
- 2 Vision Models: Qwen 3 VL 4B, Ministral 3B for geometry extraction
- 5-6 Small Text Models (0.5B): Specialized tasks

Architecture:
┌─────────────────────────────────────────────────────────────────┐
│                        SKETCH IMAGE                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         v                 v                 v
┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│  Vision Model 1│ │  Vision Model 2│ │  Reference     │
│  (Qwen 3 VL)   │ │  (Ministral 3B)│ │  Geometry Lib  │
│  Corner Extract│ │  Room Detect   │ │                │
└───────┬────────┘ └───────┬────────┘ └───────┬────────┘
        │                  │                  │
        v                  v                  v
┌────────────────────────────────────────────────────────┐
│              GEOMETRY FUSION LAYER                      │
│  - Consensus voting on corners                          │
│  - Confidence weighting                                 │
│  - Outlier rejection                                    │
└────────────────────────────┬───────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         v                   v                   v
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Text Model 1│    │  Text Model 2│    │  Text Model 3│
│  (0.5B)      │    │  (0.5B)      │    │  (0.5B)      │
│  Wall Align  │    │  Scale Calc  │    │  Room Label  │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       v                   v                   v
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Text Model 4│    │  Text Model 5│    │  Text Model 6│
│  (0.5B)      │    │  (0.5B)      │    │  (0.5B)      │
│  Door Place  │    │  Window Place│    │  Validation  │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                           v
              ┌────────────────────────┐
              │   FINAL REVIT OUTPUT   │
              │   Walls, Doors, Windows│
              │   Rooms, Dimensions    │
              └────────────────────────┘
"""

import json
import math
import re
import requests
import statistics
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field


# =============================================================================
# MODEL CONFIGURATION
# =============================================================================

@dataclass
class ModelConfig:
    """Configuration for a model endpoint"""
    name: str
    api_url: str
    model_id: str
    role: str  # "vision", "text"
    task: str  # What this model specializes in
    weight: float = 1.0  # Confidence weight for ensemble
    timeout: int = 60


# Default model configurations
DEFAULT_MODELS = {
    # Vision Models
    "vision_primary": ModelConfig(
        name="Qwen 3 VL 4B",
        api_url="http://localhost:1234/v1",
        model_id="qwen-3-vl-4b",
        role="vision",
        task="corner_extraction",
        weight=1.0,
        timeout=120
    ),
    "vision_secondary": ModelConfig(
        name="Ministral 3B",
        api_url="http://localhost:1234/v1",
        model_id="ministral-3b",
        role="vision",
        task="room_detection",
        weight=0.8,
        timeout=120
    ),

    # Small Text Models (0.5B each)
    "text_aligner": ModelConfig(
        name="Wall Aligner",
        api_url="http://localhost:1234/v1",
        model_id="local-model",  # Placeholder - user will configure
        role="text",
        task="wall_alignment",
        weight=1.0,
        timeout=30
    ),
    "text_scaler": ModelConfig(
        name="Scale Calculator",
        api_url="http://localhost:1234/v1",
        model_id="local-model",
        role="text",
        task="scale_calculation",
        weight=1.0,
        timeout=30
    ),
    "text_labeler": ModelConfig(
        name="Room Labeler",
        api_url="http://localhost:1234/v1",
        model_id="local-model",
        role="text",
        task="room_labeling",
        weight=1.0,
        timeout=30
    ),
    "text_door_placer": ModelConfig(
        name="Door Placer",
        api_url="http://localhost:1234/v1",
        model_id="local-model",
        role="text",
        task="door_placement",
        weight=1.0,
        timeout=30
    ),
    "text_window_placer": ModelConfig(
        name="Window Placer",
        api_url="http://localhost:1234/v1",
        model_id="local-model",
        role="text",
        task="window_placement",
        weight=1.0,
        timeout=30
    ),
    "text_validator": ModelConfig(
        name="Geometry Validator",
        api_url="http://localhost:1234/v1",
        model_id="local-model",
        role="text",
        task="validation",
        weight=1.0,
        timeout=30
    ),
}


# =============================================================================
# PROMPTS FOR SPECIALIZED MODELS
# =============================================================================

PROMPTS = {
    "corner_extraction": """You are a precise geometry extractor. Analyze this floor plan sketch.
Extract ALL corner points of the building outline as [x, y] coordinates.
Output ONLY valid JSON: {"corners": [[x,y], ...], "confidence": 0.0-1.0}""",

    "room_detection": """Analyze this floor plan sketch for room boundaries.
Identify distinct rooms and their approximate boundaries.
Output JSON: {"rooms": [{"name": "room_type", "corners": [[x,y],...]}], "confidence": 0.0-1.0}""",

    "wall_alignment": """Given these raw corner coordinates, align them to a clean Manhattan grid.
Snap nearly-horizontal walls to exact horizontal lines.
Snap nearly-vertical walls to exact vertical lines.
Input corners: {corners}
Output JSON: {"aligned_corners": [[x,y], ...], "adjustments_made": N}""",

    "scale_calculation": """Given the corner coordinates and target area, calculate the scale factor.
Corners: {corners}
Target area: {target_area} sq ft
Output JSON: {"scale_factor": float, "current_area": float, "scaled_corners": [[x,y],...]}""",

    "room_labeling": """Given the floor plan geometry and detected rooms, assign room labels.
Building corners: {corners}
Room boundaries: {rooms}
Output JSON: {"labeled_rooms": [{"name": "Living Room", "center": [x,y], "area_sqft": N}, ...]}""",

    "door_placement": """Given wall segments, suggest door placements.
Walls: {walls}
Rooms: {rooms}
Output JSON: {"doors": [{"wall_index": N, "position": 0.0-1.0, "width": 3.0, "type": "interior/exterior"}]}""",

    "window_placement": """Given exterior walls and rooms, suggest window placements.
Exterior walls: {exterior_walls}
Rooms: {rooms}
Output JSON: {"windows": [{"wall_index": N, "position": 0.0-1.0, "width": 4.0, "sill_height": 3.0}]}""",

    "validation": """Validate this floor plan geometry for architectural correctness.
Walls: {walls}
Rooms: {rooms}
Doors: {doors}
Windows: {windows}
Check for: overlapping walls, unreachable rooms, too-small spaces, missing doors
Output JSON: {"valid": true/false, "issues": ["issue1", "issue2"], "suggestions": ["fix1"]}"""
}


# =============================================================================
# GEOMETRY FUSION
# =============================================================================

@dataclass
class GeometryCandidate:
    """A geometry candidate from one model"""
    source: str
    corners: List[List[float]]
    confidence: float
    metadata: Dict = field(default_factory=dict)


class GeometryFusion:
    """Combines geometry outputs from multiple vision models"""

    def __init__(self, distance_threshold: float = 30.0):
        self.distance_threshold = distance_threshold

    def fuse_corners(self, candidates: List[GeometryCandidate]) -> List[List[float]]:
        """
        Fuse corner detections from multiple models using weighted voting.
        Points within distance_threshold are considered the same corner.
        """
        if not candidates:
            return []

        if len(candidates) == 1:
            return candidates[0].corners

        # Collect all corners with weights
        all_corners: List[Tuple[List[float], float, str]] = []
        for cand in candidates:
            for corner in cand.corners:
                all_corners.append((corner, cand.confidence, cand.source))

        # Cluster nearby corners
        clusters: List[List[Tuple[List[float], float]]] = []

        for corner, weight, _ in all_corners:
            matched = False
            for cluster in clusters:
                # Check distance to cluster centroid
                centroid = self._cluster_centroid(cluster)
                dist = math.hypot(corner[0] - centroid[0], corner[1] - centroid[1])
                if dist < self.distance_threshold:
                    cluster.append((corner, weight))
                    matched = True
                    break

            if not matched:
                clusters.append([(corner, weight)])

        # For each cluster, compute weighted centroid
        fused_corners = []
        for cluster in clusters:
            if len(cluster) >= 1:  # Could require minimum agreement
                weighted_x = sum(c[0][0] * c[1] for c in cluster) / sum(c[1] for c in cluster)
                weighted_y = sum(c[0][1] * c[1] for c in cluster) / sum(c[1] for c in cluster)
                fused_corners.append([weighted_x, weighted_y])

        # Sort corners to form a proper polygon (convex hull order)
        if fused_corners:
            fused_corners = self._order_polygon(fused_corners)

        return fused_corners

    def _cluster_centroid(self, cluster: List[Tuple[List[float], float]]) -> List[float]:
        """Calculate centroid of a cluster"""
        if not cluster:
            return [0, 0]
        x = sum(c[0][0] for c in cluster) / len(cluster)
        y = sum(c[0][1] for c in cluster) / len(cluster)
        return [x, y]

    def _order_polygon(self, corners: List[List[float]]) -> List[List[float]]:
        """Order corners to form a proper polygon (counter-clockwise)"""
        if len(corners) < 3:
            return corners

        # Find centroid
        cx = sum(c[0] for c in corners) / len(corners)
        cy = sum(c[1] for c in corners) / len(corners)

        # Sort by angle from centroid
        def angle_from_centroid(corner):
            return math.atan2(corner[1] - cy, corner[0] - cx)

        sorted_corners = sorted(corners, key=angle_from_centroid)
        return sorted_corners


# =============================================================================
# MULTI-MODEL PROCESSOR
# =============================================================================

class MultiModelProcessor:
    """
    Orchestrates multiple small models for sketch-to-plan conversion.
    Uses ensemble of vision models + specialized text models.
    """

    def __init__(self, models: Dict[str, ModelConfig] = None):
        self.models = models or DEFAULT_MODELS
        self.fusion = GeometryFusion()
        self.executor = ThreadPoolExecutor(max_workers=4)

    async def process_sketch(
        self,
        image_data: str,
        target_area: float = 500.0,
        include_rooms: bool = True,
        include_openings: bool = True
    ) -> Dict[str, Any]:
        """
        Process a sketch through the multi-model pipeline.

        Returns:
            {
                "walls": [...],
                "rooms": [...],
                "doors": [...],
                "windows": [...],
                "boundary_points": [...],
                "validation": {...}
            }
        """
        print("\n" + "=" * 60)
        print("MULTI-MODEL SKETCH PROCESSOR")
        print("=" * 60)

        # Stage 1: Parallel Vision Analysis
        print("\n📸 Stage 1: Vision Model Analysis")
        vision_results = await self._run_vision_models(image_data)

        # Stage 2: Geometry Fusion
        print("\n🔀 Stage 2: Geometry Fusion")
        fused_geometry = self._fuse_geometry(vision_results)

        # Stage 3: Sequential Text Model Pipeline
        print("\n⚙️ Stage 3: Text Model Processing")
        processed = await self._run_text_pipeline(fused_geometry, target_area)

        # Stage 4: Validation
        print("\n✅ Stage 4: Validation")
        validation = await self._validate_output(processed)

        result = {
            **processed,
            "validation": validation,
            "pipeline_info": {
                "vision_models_used": len(vision_results),
                "text_models_used": 6,
                "fusion_method": "weighted_centroid"
            }
        }

        print("\n" + "=" * 60)
        print(f"✨ Processing Complete: {len(result.get('walls', []))} walls")
        print("=" * 60)

        return result

    async def _run_vision_models(self, image_data: str) -> List[GeometryCandidate]:
        """Run vision models in parallel"""
        candidates = []

        # Get vision model configs
        vision_models = {k: v for k, v in self.models.items() if v.role == "vision"}

        async def query_vision(name: str, config: ModelConfig):
            print(f"   🔍 Querying {config.name}...")
            try:
                result = await self._query_vision_model(config, image_data)
                corners = result.get("corners", [])
                confidence = result.get("confidence", 0.5)
                print(f"   ✅ {config.name}: {len(corners)} corners (conf: {confidence:.2f})")
                return GeometryCandidate(
                    source=name,
                    corners=corners,
                    confidence=confidence * config.weight,
                    metadata=result
                )
            except Exception as e:
                print(f"   ❌ {config.name} failed: {e}")
                return None

        # Run in parallel
        tasks = [query_vision(name, config) for name, config in vision_models.items()]
        results = await asyncio.gather(*tasks)

        candidates = [r for r in results if r is not None]
        print(f"   📊 Got {len(candidates)} vision responses")

        return candidates

    async def _query_vision_model(self, config: ModelConfig, image_data: str) -> Dict:
        """Query a single vision model"""
        if "," in image_data:
            image_data = image_data.split(",")[1]

        prompt = PROMPTS.get(config.task, PROMPTS["corner_extraction"])

        payload = {
            "model": config.model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_data}"}
                        }
                    ]
                }
            ],
            "temperature": 0.1,
            "max_tokens": 2000
        }

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            self.executor,
            lambda: requests.post(
                f"{config.api_url}/chat/completions",
                json=payload,
                timeout=config.timeout
            )
        )
        response.raise_for_status()

        content = response.json()['choices'][0]['message']['content']
        return self._parse_json(content)

    def _fuse_geometry(self, candidates: List[GeometryCandidate]) -> Dict:
        """Fuse geometry from multiple vision models"""
        if not candidates:
            return {"corners": [], "rooms": []}

        # Fuse corners
        fused_corners = self.fusion.fuse_corners(candidates)
        print(f"   🔗 Fused to {len(fused_corners)} corners")

        # Collect room detections (from room detection model)
        rooms = []
        for cand in candidates:
            if "rooms" in cand.metadata:
                rooms.extend(cand.metadata["rooms"])

        return {
            "corners": fused_corners,
            "rooms": rooms,
            "confidence": sum(c.confidence for c in candidates) / len(candidates)
        }

    async def _run_text_pipeline(self, geometry: Dict, target_area: float) -> Dict:
        """Run the text model pipeline sequentially"""
        corners = geometry.get("corners", [])
        rooms = geometry.get("rooms", [])

        # Step 1: Wall Alignment
        print("   1️⃣ Wall Alignment...")
        aligned = await self._run_text_model("text_aligner", {
            "corners": corners
        })
        aligned_corners = aligned.get("aligned_corners", corners)

        # Step 2: Scale Calculation
        print("   2️⃣ Scale Calculation...")
        scaled = await self._run_text_model("text_scaler", {
            "corners": aligned_corners,
            "target_area": target_area
        })
        scale_factor = scaled.get("scale_factor", 1.0)
        scaled_corners = scaled.get("scaled_corners", aligned_corners)

        # Generate walls from corners
        walls = self._corners_to_walls(scaled_corners)

        # Step 3: Room Labeling
        print("   3️⃣ Room Labeling...")
        labeled = await self._run_text_model("text_labeler", {
            "corners": scaled_corners,
            "rooms": rooms
        })
        labeled_rooms = labeled.get("labeled_rooms", [])

        # Step 4: Door Placement
        print("   4️⃣ Door Placement...")
        doors_result = await self._run_text_model("text_door_placer", {
            "walls": walls,
            "rooms": labeled_rooms
        })
        doors = doors_result.get("doors", [])

        # Step 5: Window Placement
        print("   5️⃣ Window Placement...")
        # Identify exterior walls (walls on the boundary)
        exterior_walls = [w for i, w in enumerate(walls) if i < 4]  # Simple heuristic
        windows_result = await self._run_text_model("text_window_placer", {
            "exterior_walls": exterior_walls,
            "rooms": labeled_rooms
        })
        windows = windows_result.get("windows", [])

        return {
            "walls": walls,
            "rooms": labeled_rooms,
            "doors": doors,
            "windows": windows,
            "boundary_points": scaled_corners,
            "scale_factor": scale_factor
        }

    async def _run_text_model(self, model_key: str, data: Dict) -> Dict:
        """Run a text model with formatted prompt"""
        config = self.models.get(model_key)
        if not config:
            print(f"   ⚠️ Model {model_key} not configured")
            return {}

        prompt_template = PROMPTS.get(config.task, "")
        prompt = prompt_template.format(**data)

        payload = {
            "model": config.model_id,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 2000
        }

        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: requests.post(
                    f"{config.api_url}/chat/completions",
                    json=payload,
                    timeout=config.timeout
                )
            )
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
            return self._parse_json(content)
        except Exception as e:
            print(f"   ⚠️ {config.name} error: {e}")
            return {}

    async def _validate_output(self, processed: Dict) -> Dict:
        """Run validation model"""
        validation = await self._run_text_model("text_validator", {
            "walls": processed.get("walls", []),
            "rooms": processed.get("rooms", []),
            "doors": processed.get("doors", []),
            "windows": processed.get("windows", [])
        })
        return validation

    def _corners_to_walls(self, corners: List[List[float]]) -> List[Dict]:
        """Convert corner list to wall segments"""
        walls = []
        for i in range(len(corners)):
            start = corners[i]
            end = corners[(i + 1) % len(corners)]

            # Calculate length
            length = math.hypot(end[0] - start[0], end[1] - start[1])
            if length < 0.1:
                continue

            walls.append({
                "start_point": [start[0], start[1], 0.0],
                "end_point": [end[0], end[1], 0.0],
                "length": length,
                "height": 10.0
            })

        return walls

    def _parse_json(self, text: str) -> Dict:
        """Parse JSON from model output"""
        try:
            # Try to find JSON in the text
            match = re.search(r'\{[\s\S]*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass
        return {}


# =============================================================================
# FALLBACK PROCESSOR (Single Model)
# =============================================================================

class SingleModelFallback:
    """
    Fallback to single-model processing when multi-model isn't available.
    Uses the same interface as MultiModelProcessor.
    """

    def __init__(self, api_url: str = "http://localhost:1234/v1"):
        self.api_url = api_url

    async def process_sketch(
        self,
        image_data: str,
        target_area: float = 500.0,
        **kwargs
    ) -> Dict[str, Any]:
        """Process with single model (backward compatible)"""
        # Import the original vision processor
        try:
            from vision_processor import VisionProcessor
            processor = VisionProcessor(self.api_url)
            return processor.process_layout(image_data, target_area)
        except ImportError:
            return {"error": "VisionProcessor not available"}


# =============================================================================
# FACTORY
# =============================================================================

def create_processor(use_multi_model: bool = True) -> MultiModelProcessor:
    """
    Create the appropriate processor based on configuration.

    Args:
        use_multi_model: If True, use ensemble architecture.
                         If False, fall back to single model.
    """
    if use_multi_model:
        return MultiModelProcessor()
    else:
        return SingleModelFallback()


# =============================================================================
# MCP INTEGRATION ADAPTER
# =============================================================================

class MCPVisionAdapter:
    """
    Adapter that makes MultiModelProcessor compatible with existing MCP setup.
    Drop-in replacement for VisionProcessor in client_orchestrator.py
    """

    def __init__(self, api_url: str = "http://localhost:1234/v1", use_multi_model: bool = False):
        self.api_url = api_url
        self.use_multi_model = use_multi_model

        if use_multi_model:
            self.processor = MultiModelProcessor()
        else:
            # Use single model for now, can be upgraded
            self.processor = None

    def process_layout(self, image_data: str, target_area: float, detail_level: str = "high") -> Dict:
        """
        Process layout - same interface as VisionProcessor.process_layout()
        This makes it a drop-in replacement in the orchestrator.
        """
        if self.use_multi_model and self.processor:
            # Run async processor in sync context
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            result = loop.run_until_complete(
                self.processor.process_sketch(image_data, target_area)
            )

            # Transform to match VisionProcessor output format
            return self._transform_to_legacy_format(result)
        else:
            # Fall back to original VisionProcessor
            try:
                from vision_processor import VisionProcessor
                legacy_processor = VisionProcessor(self.api_url)
                return legacy_processor.process_layout(image_data, target_area, detail_level)
            except ImportError:
                return {"walls": [], "boundary_points": [], "error": "No processor available"}

    def _transform_to_legacy_format(self, multi_result: Dict) -> Dict:
        """Transform multi-model output to match VisionProcessor format"""
        walls = multi_result.get("walls", [])
        boundary = multi_result.get("boundary_points", [])

        # Add level_name and wall_type if missing
        for wall in walls:
            if "level_name" not in wall:
                wall["level_name"] = "${base_level_name}"
            if "wall_type" not in wall:
                wall["wall_type"] = "${default_wall_type}"

        return {
            "walls": walls,
            "boundary_points": boundary,
            "level_name": multi_result.get("level_name"),
            "rooms": multi_result.get("rooms", []),
            "doors": multi_result.get("doors", []),
            "windows": multi_result.get("windows", []),
            "validation": multi_result.get("validation", {})
        }


def get_vision_processor(use_multi_model: bool = False, api_url: str = "http://localhost:1234/v1"):
    """
    Factory function to get the appropriate vision processor.
    Use this in client_orchestrator.py instead of direct VisionProcessor import.

    Example:
        # In client_orchestrator.py, replace:
        # from vision_processor import VisionProcessor
        # self.vision = VisionProcessor()

        # With:
        from multi_model_processor import get_vision_processor
        self.vision = get_vision_processor(use_multi_model=True)
    """
    return MCPVisionAdapter(api_url=api_url, use_multi_model=use_multi_model)


# =============================================================================
# TOOL REGISTRATION FOR ORCHESTRATOR
# =============================================================================

def get_multi_model_tools() -> Dict[str, Any]:
    """
    Returns tool definitions for the orchestrator's tool registry.
    Add these to the 'generation' category in list_available_tools.
    """
    return {
        "multi_model_sketch_to_plan": {
            "description": "Process sketch using ensemble of vision models for more accurate geometry",
            "handler": "process_sketch_multi_model",
            "requires_image": True,
            "parameters": {
                "target_area": "Target area in sqft",
                "include_rooms": "Detect room boundaries (default: True)",
                "include_openings": "Suggest door/window placements (default: True)"
            }
        },
        "configure_vision_models": {
            "description": "Configure which vision models to use for sketch processing",
            "handler": "configure_models",
            "parameters": {
                "primary_model": "Primary vision model ID",
                "secondary_model": "Secondary vision model ID",
                "text_models": "List of text model IDs for specialized tasks"
            }
        }
    }


# =============================================================================
# MODEL CONFIGURATION PERSISTENCE
# =============================================================================

import os
from pathlib import Path

CONFIG_DIR = Path(os.getenv('APPDATA', '~')) / 'RevitMCP' / 'models'


def save_model_config(config: Dict[str, ModelConfig]) -> None:
    """Save model configuration to disk"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_path = CONFIG_DIR / "multi_model_config.json"

    serializable = {}
    for key, model in config.items():
        serializable[key] = {
            "name": model.name,
            "api_url": model.api_url,
            "model_id": model.model_id,
            "role": model.role,
            "task": model.task,
            "weight": model.weight,
            "timeout": model.timeout
        }

    with open(config_path, 'w') as f:
        json.dump(serializable, f, indent=2)
    print(f"Saved model config to {config_path}")


def load_model_config() -> Dict[str, ModelConfig]:
    """Load model configuration from disk"""
    config_path = CONFIG_DIR / "multi_model_config.json"

    if not config_path.exists():
        return DEFAULT_MODELS

    try:
        with open(config_path) as f:
            data = json.load(f)

        config = {}
        for key, model_data in data.items():
            config[key] = ModelConfig(**model_data)
        return config
    except Exception as e:
        print(f"Error loading model config: {e}")
        return DEFAULT_MODELS


# =============================================================================
# CLI TEST
# =============================================================================

if __name__ == "__main__":
    import sys

    print("\n" + "=" * 60)
    print("MULTI-MODEL PROCESSOR TEST")
    print("=" * 60)

    # Test with a simple geometry
    test_corners = [
        [0, 0], [100, 0], [100, 80], [0, 80]
    ]

    fusion = GeometryFusion()

    # Simulate two models with slightly different outputs
    candidates = [
        GeometryCandidate("model_1", [[0, 0], [102, 2], [98, 78], [2, 80]], 0.9),
        GeometryCandidate("model_2", [[1, 1], [99, 0], [100, 81], [0, 79]], 0.8),
    ]

    fused = fusion.fuse_corners(candidates)
    print(f"\nFused corners: {fused}")

    # Test MCP adapter
    print("\n" + "-" * 60)
    print("MCP ADAPTER TEST")
    print("-" * 60)

    adapter = MCPVisionAdapter(use_multi_model=False)
    print(f"Adapter created: use_multi_model={adapter.use_multi_model}")

    print("\n✅ Multi-model processor module loaded successfully")
    print("\nUsage in client_orchestrator.py:")
    print("  from multi_model_processor import get_vision_processor")
    print("  self.vision = get_vision_processor(use_multi_model=True)")
