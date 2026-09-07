import json
import math
import os
import re
import requests
import statistics
from pathlib import Path
from typing import List, Dict, Any


def _get_vision_model_from_config() -> str:
    """Load vision model name from config file"""
    config_path = Path(os.getenv('APPDATA', os.path.expanduser('~'))) / 'RevitMCP' / 'models' / 'multi_model_config.json'
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
            return config.get("vision_primary", {}).get("model_id", "qwen/qwen3-vl-4b")
        except:
            pass
    return "qwen/qwen3-vl-4b"


class VisionProcessor:
    """
    Handles image-to-geometry conversion with Manhattan Grid Clustering.
    Forces 'almost aligned' walls to snap to shared X/Y coordinates.
    """
    
    def __init__(self, api_url: str = "http://localhost:1234/v1"):
        self.api_url = api_url
        self.system_prompt = """You are an expert at extracting floor plan geometry from sketches.

TASK: Count and locate ONLY the corners where walls meet at angles (typically 90 degrees).

RULES:
1. A corner is where TWO walls meet and change direction
2. Count ONLY visible corners in the sketch - do NOT invent or hallucinate extra corners
3. Trace the OUTER boundary of the shape in clockwise or counter-clockwise order
4. Use pixel coordinates from the image (top-left is 0,0)
5. Double-check your count matches what you actually see

EXAMPLES:
- Simple rectangle = 4 corners
- L-shape = 6 corners
- T-shape = 8 corners
- Rectangle with one notch = 6 corners

OUTPUT FORMAT (JSON only, no explanation):
{"corners": [[x,y], [x,y], ...], "corner_count": N}
"""

    def process_layout(self, image_data: str, target_area: float, detail_level: str = "high", num_passes: int = 3):
        print(f"   [*] VisionProcessor: Analyzing image for {target_area} sq ft layout...")

        # 0. DISCOVER LEVELS - Get the lowest level dynamically
        lowest_level_name = self._get_lowest_level()
        print(f"   [*] Using level: {lowest_level_name}")

        # 1. MULTI-PASS VISION ANALYSIS
        raw_corners, raw_windows, raw_doors = self._multi_pass_vision(image_data, num_passes)

        if len(raw_corners) < 3:
            print("   [!] Vision Model failed to detect geometry.")
            return []

        print(f"   [OK] Final consensus: {len(raw_corners)} corners")

        # 2. Process corners into walls
        return self._process_corners(raw_corners, target_area, lowest_level_name)

    def _multi_pass_vision(self, image_data: str, num_passes: int = 3):
        """
        Run vision model multiple times and take consensus result.
        Returns the corners that appear most consistently.
        """
        from collections import Counter

        all_results = []
        print(f"   [*] Running {num_passes} vision passes for consensus...")

        for i in range(num_passes):
            data = self._query_vision_model(image_data, pass_num=i+1)
            corners = data.get("corners", [])
            corner_count = len(corners)
            windows = data.get("windows", [])
            doors = data.get("doors", [])

            if corner_count >= 3:
                all_results.append({
                    "corners": corners,
                    "corner_count": corner_count,
                    "windows": windows,
                    "doors": doors
                })
                print(f"       Pass {i+1}: {corner_count} corners")
            else:
                print(f"       Pass {i+1}: Failed (< 3 corners)")

        if not all_results:
            print("   [X] All passes failed")
            return [], [], []

        # Count how many times each corner count appears
        corner_counts = [r["corner_count"] for r in all_results]
        count_frequency = Counter(corner_counts)
        most_common_count = count_frequency.most_common(1)[0][0]

        print(f"   [*] Corner counts: {corner_counts} -> Consensus: {most_common_count}")

        # Get the first result that matches the consensus count
        for result in all_results:
            if result["corner_count"] == most_common_count:
                return result["corners"], result["windows"], result["doors"]

        # Fallback to first result
        return all_results[0]["corners"], all_results[0]["windows"], all_results[0]["doors"]

    def _process_corners(self, raw_corners, target_area: float, lowest_level_name: str):
        """Process raw corners into walls - extracted for reuse"""

        # 2. PRE-PROCESS: NORMALIZE
        # Scale to 1000x1000 so our thresholds work consistently
        normalized_corners = self._normalize_scale(raw_corners, target_size=1000.0)
        
        # Ensure Counter-Clockwise (Fixes Auto-Flip)
        ordered_corners = self._ensure_ccw(normalized_corners)
        
        # 3. MANHATTAN REGULARIZATION
        # Reduced thresholds to preserve more detail from the sketch

        # A. First, merge points that are super close (Double-taps)
        # Reduced from 40.0 to 10.0 to preserve detail
        merged_corners = self._merge_close_points(ordered_corners, threshold=10.0)

        # B. Align to Major Axes (Fixes rotation/slanted drawings)
        # Reduced from 20.0 to 5.0 to preserve detail
        aligned_corners = self._align_to_grid(merged_corners, snap_threshold=5.0)

        # C. Remove collinear/useless points created by the snap
        clean_corners = self._prune_collinear(aligned_corners)
        
        # D. Final check: Force closed loop
        if len(clean_corners) > 2:
            if clean_corners[0] != clean_corners[-1]:
                clean_corners.append(clean_corners[0])

        print(f"   ✨ Final Geometry: {len(clean_corners)-1} corners (closed loop).")

        # 4. EXACT SCALING
        current_area = self.calculate_polygon_area(clean_corners)
        if current_area <= 50.0: current_area = 1000.0 
        
        # Zoning Correction (0.83) to account for Exterior Wall thickness
        zoning_factor = 0.83
        adjusted_target = target_area * zoning_factor
        scale_factor = (adjusted_target / current_area) ** 0.5
        
        # 5. GENERATE WALLS
        revit_walls = []
        # Iterate up to len-1 because the list is closed (Start==End)
        for i in range(len(clean_corners) - 1):
            p1 = clean_corners[i]
            p2 = clean_corners[i+1]
            
            start_scaled = [p1[0] * scale_factor, p1[1] * scale_factor, 0.0]
            end_scaled   = [p2[0] * scale_factor, p2[1] * scale_factor, 0.0]
            
            # Distance check to avoid zero-length walls
            dist = math.hypot(start_scaled[0]-end_scaled[0], start_scaled[1]-end_scaled[1])
            
            if dist > 0.1: # Only create if length > 0.1 ft
                revit_walls.append({
                    "start_point": start_scaled, 
                    "end_point": end_scaled, 
                    "height": 10.0, 
                    "level_name": lowest_level_name,  # Use discovered level name
                    "wall_type": "${default_wall_type}"
                })

        # 🛑 FIX: Create proper boundary points for floors/roofs
        # Scale the cleaned corners (without the duplicate last point) for floor/roof creation
        boundary_points_scaled = []
        for i in range(len(clean_corners) - 1):  # Exclude duplicate last point
            p = clean_corners[i]
            scaled_point = [p[0] * scale_factor, p[1] * scale_factor, 0.0]
            boundary_points_scaled.append(scaled_point)

        print(f"   🏠 Generated: {len(revit_walls)} walls, {len(boundary_points_scaled)} boundary points")

        # CRITICAL: Return all geometry items for the Orchestrator to handle
        return {
            "walls": revit_walls,
            "boundary_points": boundary_points_scaled,  # Complete polygon for floors/roofs
            "level_name": lowest_level_name  # Pass the discovered level name for floors/roofs
        }
         
    # --- NEW MANHATTAN LOGIC ---

    def _merge_close_points(self, corners, threshold=40.0):
        if not corners: return []
        merged = [corners[0]]
        for i in range(1, len(corners)):
            last = merged[-1]
            curr = corners[i]
            dist = math.hypot(curr[0]-last[0], curr[1]-last[1])
            if dist > threshold:
                merged.append(curr)
        # Check wrap-around
        if len(merged) > 1:
            if math.hypot(merged[0][0]-merged[-1][0], merged[0][1]-merged[-1][1]) < threshold:
                merged.pop()
        return merged

    def _align_to_grid(self, corners, snap_threshold=20):
        """
        Collects all X and Y coordinates, clusters them, and snaps points to these
        dominant grid lines. This forces walls to be straight and aligned.
        """
        if not corners: return []
        
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        
        # Cluster X coordinates
        def get_clusters(values, threshold):
            sorted_vals = sorted(values)
            clusters = []
            if not sorted_vals: return []
            current_cluster = [sorted_vals[0]]
            
            for v in sorted_vals[1:]:
                if v - current_cluster[-1] <= threshold:
                    current_cluster.append(v)
                else:
                    clusters.append(statistics.mean(current_cluster))
                    current_cluster = [v]
            clusters.append(statistics.mean(current_cluster))
            return clusters

        x_grid = get_clusters(xs, snap_threshold)
        y_grid = get_clusters(ys, snap_threshold)
        
        snapped = []
        for p in corners:
            # Find nearest X grid line
            nearest_x = min(x_grid, key=lambda x: abs(x - p[0]))
            # Find nearest Y grid line
            nearest_y = min(y_grid, key=lambda y: abs(y - p[1]))
            snapped.append([nearest_x, nearest_y])
            
        return snapped

    def _prune_collinear(self, corners):
        """Removes points that sit on a straight line."""
        if len(corners) < 3: return corners
        
        # We process as a closed loop
        points = corners + [corners[0]]
        pruned = [points[0]]
        
        for i in range(1, len(points) - 1):
            prev = pruned[-1]
            curr = points[i]
            next_p = points[i+1]
            
            # Check if horizontal
            if abs(prev[1] - curr[1]) < 1.0 and abs(curr[1] - next_p[1]) < 1.0:
                continue # Skip curr, it's just a point on a flat line
                
            # Check if vertical
            if abs(prev[0] - curr[0]) < 1.0 and abs(curr[0] - next_p[0]) < 1.0:
                continue # Skip curr, it's just a point on a vertical line
                
            pruned.append(curr)
            
        # Don't duplicate start/end in the return, the main logic handles closure
        return pruned

    # --- EXISTING UTILITIES ---

    def _normalize_scale(self, corners: List[List[float]], target_size: float = 1000.0) -> List[List[float]]:
        """
        Normalize corners to a target size and correct orientation.

        Image coordinates: Y=0 at top, increases downward
        Revit coordinates: Y=0 at origin, increases upward

        Apply 90° counter-clockwise rotation to correct the orientation:
        - new_x = flipped Y (max_y - p[1])
        - new_y = X (p[0] - min_x)
        """
        if not corners: return []
        min_x = min(p[0] for p in corners)
        max_x = max(p[0] for p in corners)
        min_y = min(p[1] for p in corners)
        max_y = max(p[1] for p in corners)
        width = max_x - min_x
        height = max_y - min_y
        max_dim = max(width, height)
        if max_dim == 0: return corners
        scale = target_size / max_dim
        # Rotate 90° counter-clockwise: (x, y) → (-y, x)
        # With translation: new_x = (max_y - p[1]), new_y = (p[0] - min_x)
        return [[(max_y - p[1]) * scale, (p[0] - min_x) * scale] for p in corners]

    def _ensure_ccw(self, corners: List[List[float]]) -> List[List[float]]:
        area = 0.0
        for i in range(len(corners)):
            j = (i + 1) % len(corners)
            area += (corners[j][0] - corners[i][0]) * (corners[j][1] + corners[i][1])
        if area > 0: return corners[::-1]
        return corners

    def calculate_polygon_area(self, corners):
        n = len(corners)
        area = 0.0
        for i in range(n):
            j = (i + 1) % n 
            area += corners[i][0] * corners[j][1]
            area -= corners[j][0] * corners[i][1]
        return abs(area) / 2.0

    def _query_vision_model(self, b64_image: str, pass_num: int = 1) -> Dict:
        if "," in b64_image: b64_image = b64_image.split(",")[1]
        vision_model = _get_vision_model_from_config()

        # Only print model name on first pass
        if pass_num == 1:
            print(f"   [*] Using vision model: {vision_model}")

        # Slightly vary temperature for different results on each pass
        temperature = 0.1 + (pass_num - 1) * 0.05  # 0.1, 0.15, 0.2

        payload = {
            "model": vision_model,
            "messages": [{"role": "user", "content": [{"type": "text", "text": self.system_prompt}, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}}]}],
            "temperature": temperature,
            "max_tokens": 1000
        }
        try:
            response = requests.post(f"{self.api_url}/chat/completions", json=payload, timeout=120)
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
            return self._parse_json_from_text(content)
        except Exception as e:
            print(f"   [X] Vision API Error (pass {pass_num}): {e}")
            return {}

    def _parse_json_from_text(self, text: str) -> Dict:
        try:
            match = re.search(r'\{[\s\S]*\}', text, re.DOTALL)
            if match: return json.loads(match.group())
        except: pass
        return {}

    def _get_lowest_level(self) -> str:
        """
        Dynamically discover available levels and return the lowest one.
        Falls back to common level names if API fails.
        """
        try:
            # Call the Revit API to get available levels
            response = requests.get("http://localhost:48884/revit_mcp/list_levels", timeout=10)
            if response.status_code == 200:
                levels = response.json()
                if levels:
                    # Sort levels by elevation (lowest first)
                    sorted_levels = sorted(levels, key=lambda x: float(x.get('elevation', 0)))
                    lowest_level = sorted_levels[0]
                    level_name = lowest_level.get('name', 'Level 1')
                    print(f"   🎯 Discovered {len(levels)} levels, using lowest: '{level_name}' (elevation: {lowest_level.get('elevation', 0)})")
                    return level_name
        except Exception as e:
            print(f"   ⚠️ Level discovery failed: {e}")
        
        # Fallback to common level names
        fallback_names = ["Level 0", "Ground Floor", "Level 1", "Floor 01", "00 - Ground"]
        print(f"   ⚠️ Using fallback level name: '{fallback_names[0]}'")
        return fallback_names[0]