"""
Terrain Mesh Generator
======================
Convert elevation data to 3D mesh for rendering.
"""

import math
from typing import List, Tuple, Dict


class TerrainVertex:
    """Single vertex in terrain mesh."""
    def __init__(self, x: float, y: float, z: float, nx: float, ny: float, nz: float, u: float, v: float):
        self.x = x
        self.y = y
        self.z = z
        self.nx = nx
        self.ny = ny
        self.nz = nz
        self.u = u
        self.v = v

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            "position": [self.x, self.y, self.z],
            "normal": [self.nx, self.ny, self.nz],
            "uv": [self.u, self.v]
        }

    @classmethod
    def from_dict(cls, data):
        """Create from dictionary."""
        pos = data["position"]
        normal = data["normal"]
        uv = data["uv"]
        return cls(pos[0], pos[1], pos[2], normal[0], normal[1], normal[2], uv[0], uv[1])


class TerrainMesh:
    """3D terrain mesh generated from elevation data."""

    def __init__(self, vertices: List[TerrainVertex], indices: List[int],
                 width_ft: float, depth_ft: float, min_elevation: float, max_elevation: float):
        self.vertices = vertices
        self.indices = indices
        self.width_ft = width_ft
        self.depth_ft = depth_ft
        self.min_elevation = min_elevation
        self.max_elevation = max_elevation

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            "vertices": [v.to_dict() for v in self.vertices],
            "indices": self.indices,
            "width_ft": self.width_ft,
            "depth_ft": self.depth_ft,
            "min_elevation": self.min_elevation,
            "max_elevation": self.max_elevation,
            "vertex_count": len(self.vertices),
            "triangle_count": len(self.indices) // 3,
            "version": 2  # Version 2 = correct CCW winding order
        }

    @classmethod
    def from_dict(cls, data):
        """Create from dictionary."""
        vertices = [TerrainVertex.from_dict(v) for v in data["vertices"]]
        return cls(
            vertices,
            data["indices"],
            data["width_ft"],
            data["depth_ft"],
            data["min_elevation"],
            data["max_elevation"]
        )


class TerrainGenerator:
    """Generate terrain mesh from elevation grid data."""

    def __init__(self, elevation_grid: Dict[str, Dict], property_width_ft: float, property_depth_ft: float):
        """
        Initialize generator.

        Args:
            elevation_grid: Dict of {"lat,lng": {elevation_ft: value, ...}}
            property_width_ft: Property width in feet
            property_depth_ft: Property depth in feet
        """
        self.elevation_grid = elevation_grid
        self.width_ft = property_width_ft
        self.depth_ft = property_depth_ft

        # Sort points into grid
        self._organize_grid()

    def _organize_grid(self):
        """Sort elevation points into a regular grid."""
        # Extract and sort points
        points = list(self.elevation_grid.values())

        # Get unique lats and lngs to determine grid size
        lats = sorted(set(p['lat'] for p in points))
        lngs = sorted(set(p['lng'] for p in points))

        self.grid_rows = len(lats)
        self.grid_cols = len(lngs)

        # Create 2D array
        self.grid = [[None for _ in range(self.grid_cols)] for _ in range(self.grid_rows)]

        # Fill grid
        for point in points:
            lat_idx = lats.index(point['lat'])
            lng_idx = lngs.index(point['lng'])
            self.grid[lat_idx][lng_idx] = point

        print(f"[Terrain] Organized into {self.grid_rows}x{self.grid_cols} grid")

    def generate_mesh(self) -> TerrainMesh:
        """Generate terrain mesh from elevation grid."""
        vertices = []
        indices = []

        # Calculate elevation range for coloring
        elevations = [p['elevation_ft'] for row in self.grid for p in row if p]
        min_elev = min(elevations)
        max_elev = max(elevations)
        elev_range = max_elev - min_elev if max_elev != min_elev else 1.0

        # Offset elevation so min_elevation is slightly below ground level (buildings sit on top)
        # Use -10mm offset so terrain appears as ground plane beneath building floors at Y=0
        elevation_offset = -min_elev - 0.0328  # -0.0328 ft = -10 mm

        # Generate vertices
        for i in range(self.grid_rows):
            for j in range(self.grid_cols):
                point = self.grid[i][j]
                if not point:
                    continue

                # World position (origin at property corner)
                # Convert feet to millimeters (1 ft = 304.8 mm)
                # Building coordinate system: X=east-west, Y=up, Z=north-south
                x = (j / max(1, self.grid_cols - 1)) * self.width_ft * 304.8  # east-west
                y = (point['elevation_ft'] + elevation_offset) * 304.8  # elevation offset to start at 0
                z = (i / max(1, self.grid_rows - 1)) * self.depth_ft * 304.8  # north-south

                # Compute normal from adjacent heights
                nx, ny, nz = self._compute_normal(i, j)

                # UV coordinates
                u = j / max(1, self.grid_cols - 1)
                v = i / max(1, self.grid_rows - 1)

                vertices.append(TerrainVertex(x, y, z, nx, ny, nz, u, v))

        # Generate triangle indices
        for i in range(self.grid_rows - 1):
            for j in range(self.grid_cols - 1):
                # Current quad vertex indices
                idx = i * self.grid_cols + j

                # Two triangles per quad (clockwise winding for front faces)
                # Triangle 1: (i,j) -> (i+1,j) -> (i,j+1)
                indices.extend([idx, idx + self.grid_cols, idx + 1])

                # Triangle 2: (i,j+1) -> (i+1,j) -> (i+1,j+1)
                indices.extend([idx + 1, idx + self.grid_cols, idx + self.grid_cols + 1])

        mesh = TerrainMesh(vertices, indices, self.width_ft, self.depth_ft, min_elev, max_elev)

        # Print scale information
        width_mm = self.width_ft * 304.8
        depth_mm = self.depth_ft * 304.8
        print(f"[Terrain] Generated mesh: {len(vertices)} vertices, {len(indices)//3} triangles")
        print(f"[Terrain] Property size: {self.width_ft:.1f}'x{self.depth_ft:.1f}' ({width_mm:.0f}x{depth_mm:.0f} mm)")
        print(f"[Terrain] Original elevation (from Google): {min_elev:.1f}' to {max_elev:.1f}' above sea level")
        if vertices:
            x_range = (vertices[0].x, vertices[-1].x)
            z_range = (vertices[0].z, vertices[-1].z)
            y_range = (min(v.y for v in vertices), max(v.y for v in vertices))
            print(f"[Terrain] After offset - vertex ranges: X=[{x_range[0]:.0f}, {x_range[1]:.0f}], Y=[{y_range[0]:.0f}, {y_range[1]:.0f}], Z=[{z_range[0]:.0f}, {z_range[1]:.0f}] mm")
            print(f"[Terrain] Ground level (Y=0) is {(max_elev - min_elev):.1f}' ({(max_elev - min_elev) * 304.8:.0f} mm) above lowest terrain point")

        return mesh

    def _compute_normal(self, row: int, col: int) -> Tuple[float, float, float]:
        """
        Compute vertex normal from adjacent elevations.

        Uses central difference to approximate surface normal.
        """
        # Get current elevation
        current = self.grid[row][col]
        if not current:
            return (0, 0, 1)  # Default upward normal

        z = current['elevation_ft']

        # Sample neighbors with boundary checking
        z_left = self._get_elevation(row, col - 1, z)
        z_right = self._get_elevation(row, col + 1, z)
        z_up = self._get_elevation(row - 1, col, z)
        z_down = self._get_elevation(row + 1, col, z)

        # Compute gradients
        dz_dx = (z_right - z_left) / 2.0
        dz_dy = (z_down - z_up) / 2.0

        # Normal is perpendicular to surface
        # Tangent vectors: (1, 0, dz_dx) and (0, 1, dz_dy)
        # Normal = cross product
        nx = -dz_dx
        ny = -dz_dy
        nz = 1.0

        # Normalize
        length = math.sqrt(nx*nx + ny*ny + nz*nz)
        if length > 0:
            nx /= length
            ny /= length
            nz /= length

        return (nx, ny, nz)

    def _get_elevation(self, row: int, col: int, default: float) -> float:
        """Get elevation at grid position with boundary checking."""
        if 0 <= row < self.grid_rows and 0 <= col < self.grid_cols:
            point = self.grid[row][col]
            if point:
                return point['elevation_ft']
        return default


def generate_terrain_from_site(site_data: dict) -> TerrainMesh:
    """
    Generate terrain mesh from site data.

    Supports:
    - Polygon boundaries with elevation data (best quality)
    - Polygon boundaries without elevation (flat terrain)
    - Rectangular elevation grids (fallback)

    The terrain is offset and rotated so the building_origin becomes (0,0),
    which is where the building geometry is placed. Rotation aligns the
    terrain with the building's orientation.

    Args:
        site_data: Site data dictionary with google_maps data

    Returns:
        TerrainMesh object, or None if no data
    """
    google_maps = site_data.get("google_maps", {})
    boundary = google_maps.get("boundary", {})
    elevation_grid = google_maps.get("elevation_grid", {})

    # Get building origin offset and rotation (in mm and radians)
    building_origin = site_data.get("building_origin", {})
    origin_x_mm = building_origin.get("x_ft", 0) * 304.8  # Convert ft to mm
    origin_z_mm = building_origin.get("z_ft", 0) * 304.8
    rotation_deg = building_origin.get("rotation_deg", 0)
    rotation_rad = rotation_deg * math.pi / 180.0
    print(f"[Terrain] Building origin offset: ({origin_x_mm:.0f}, {origin_z_mm:.0f}) mm, rotation: {rotation_deg:.1f}°")

    # Check for polygon vertices
    vertices_mm = boundary.get("vertices_mm")
    if not vertices_mm:
        # Try vertices_ft and convert
        vertices_ft = boundary.get("vertices_ft")
        if vertices_ft and len(vertices_ft) >= 3:
            vertices_mm = [[v[0] * 304.8, v[1] * 304.8] for v in vertices_ft]

    # Helper function to apply offset and rotation to mesh vertices
    def apply_building_transform(mesh, origin_x, origin_z, rot_rad):
        """Apply translation and rotation to align terrain with building."""
        if not mesh:
            return
        has_offset = (origin_x != 0 or origin_z != 0)
        has_rotation = abs(rot_rad) > 0.001
        if not has_offset and not has_rotation:
            return

        cos_r = math.cos(-rot_rad)  # Negative because we're rotating terrain opposite to building
        sin_r = math.sin(-rot_rad)

        for v in mesh.vertices:
            # First translate (so building origin becomes 0,0)
            x = v.x - origin_x
            z = v.z - origin_z

            # Then rotate around origin
            if has_rotation:
                v.x = x * cos_r - z * sin_r
                v.z = x * sin_r + z * cos_r
            else:
                v.x = x
                v.z = z

        if has_offset or has_rotation:
            print(f"[Terrain] Applied transform: offset=({-origin_x:.0f}, {-origin_z:.0f}) mm, rotation={-rot_rad * 180 / math.pi:.1f}°")

    # If we have both polygon AND elevation data, use combined generator
    if vertices_mm and len(vertices_mm) >= 3 and elevation_grid:
        # Check for custom grid resolution from user settings
        custom_grid_res = site_data.get("terrain_grid_resolution")

        if custom_grid_res:
            grid_res = custom_grid_res
            print(f"[Terrain] Using custom grid resolution: {grid_res}")
        else:
            # Auto-select based on data density
            # Higher resolution for smoother terrain - modern GPUs handle 500k+ triangles easily
            # Formula: triangles ≈ 2 * grid_res^2
            # grid_res 300 = ~180k triangles, 400 = ~320k, 500 = ~500k
            num_elev_points = len(elevation_grid)
            if num_elev_points > 50000:
                grid_res = 400  # Very high-res LiDAR: ~320,000 triangles
            elif num_elev_points > 10000:
                grid_res = 300  # High-res LiDAR: ~180,000 triangles
            elif num_elev_points > 1000:
                grid_res = 200  # Medium LiDAR: ~80,000 triangles
            else:
                grid_res = 100  # Low-res data: ~20,000 triangles
        expected_triangles = 2 * grid_res * grid_res
        print(f"[Terrain] Using polygon ({len(vertices_mm)} vertices) WITH elevation data ({len(elevation_grid)} points)")
        print(f"[Terrain] Grid resolution: {grid_res} → ~{expected_triangles:,} triangles (smooth terrain)")
        mesh = generate_polygon_terrain_with_elevation(
            vertices_mm=vertices_mm,
            elevation_grid=elevation_grid,
            boundary=boundary,
            grid_resolution=grid_res
        )
        # Apply building origin offset and rotation so building aligns with origin point
        apply_building_transform(mesh, origin_x_mm, origin_z_mm, rotation_rad)
        return mesh

    # Polygon without elevation - flat terrain
    if vertices_mm and len(vertices_mm) >= 3:
        print(f"[Terrain] Using polygon boundary with {len(vertices_mm)} vertices (no elevation data)")
        mesh = generate_polygon_terrain_with_grid(vertices_mm, grid_resolution=150)  # Smoother flat terrain
        apply_building_transform(mesh, origin_x_mm, origin_z_mm, rotation_rad)
        return mesh

    # Rectangular elevation grid (no polygon)
    if elevation_grid:
        width_ft = site_data.get("property_width_ft", 100)
        depth_ft = site_data.get("property_depth_ft", 120)
        print(f"[Terrain] Using rectangular elevation grid ({len(elevation_grid)} points)")
        generator = TerrainGenerator(elevation_grid, width_ft, depth_ft)
        mesh = generator.generate_mesh()
        apply_building_transform(mesh, origin_x_mm, origin_z_mm, rotation_rad)
        return mesh

    print("[Terrain] No elevation data or polygon vertices in site")
    return None


def generate_polygon_terrain_with_elevation(vertices_mm: List[Tuple[float, float]],
                                             elevation_grid: Dict[str, Dict],
                                             boundary: Dict,
                                             grid_resolution: int = 15) -> TerrainMesh:
    """
    Generate polygon terrain with elevation data interpolation.

    Args:
        vertices_mm: Polygon vertices in mm [x, z]
        elevation_grid: Dict of elevation points with lat/lng/elevation_ft
        boundary: Boundary dict with lat/lng bounds for coordinate mapping
        grid_resolution: Grid divisions for internal mesh

    Returns:
        TerrainMesh with elevation variations within polygon shape
    """
    if not vertices_mm or len(vertices_mm) < 3:
        return None

    FT_TO_MM = 304.8

    # Get polygon bounding box in mm
    xs = [v[0] for v in vertices_mm]
    zs = [v[1] for v in vertices_mm]
    min_x, max_x = min(xs), max(xs)
    min_z, max_z = min(zs), max(zs)
    width_mm = max_x - min_x
    depth_mm = max_z - min_z

    # Get lat/lng bounds from boundary
    lat_min = boundary.get("lat_min", 0)
    lat_max = boundary.get("lat_max", 0)
    lng_min = boundary.get("lng_min", 0)
    lng_max = boundary.get("lng_max", 0)
    lat_range = lat_max - lat_min
    lng_range = lng_max - lng_min

    # Build elevation lookup for interpolation
    # Sort elevation points into a grid
    elev_points = list(elevation_grid.values())
    if not elev_points:
        print("[Terrain] No elevation points, falling back to flat")
        return generate_polygon_terrain_with_grid(vertices_mm, grid_resolution)

    elevations_ft = [p.get('elevation_ft', 0) for p in elev_points]
    min_elev_ft = min(elevations_ft)
    max_elev_ft = max(elevations_ft)
    print(f"[Terrain] Elevation range: {min_elev_ft:.1f}' to {max_elev_ft:.1f}' (change: {max_elev_ft - min_elev_ft:.1f}')")

    # Build spatial index for fast elevation lookup (grid-based hash)
    # This reduces O(n) search to O(1) average lookup
    print(f"[Terrain] Building spatial index for {len(elev_points)} points...")
    GRID_CELLS = 500  # 500x500 grid for spatial hashing
    elev_grid = {}  # (cell_x, cell_z) -> list of points

    for pt in elev_points:
        pt_lat = pt.get('lat', 0)
        pt_lng = pt.get('lng', 0)
        # Map lat/lng to grid cell
        cell_x = int((pt_lng - lng_min) / lng_range * GRID_CELLS) if lng_range > 0 else 0
        cell_z = int((pt_lat - lat_min) / lat_range * GRID_CELLS) if lat_range > 0 else 0
        cell_x = max(0, min(GRID_CELLS - 1, cell_x))
        cell_z = max(0, min(GRID_CELLS - 1, cell_z))
        key = (cell_x, cell_z)
        if key not in elev_grid:
            elev_grid[key] = []
        elev_grid[key].append(pt)

    print(f"[Terrain] Spatial index built: {len(elev_grid)} cells")

    # Function to get elevation at a local mm coordinate (fast version)
    def get_elevation_at(x_mm, z_mm):
        """Interpolate elevation at local coordinate using spatial hash lookup."""
        if lat_range == 0 or lng_range == 0:
            return min_elev_ft

        # Convert local mm to lat/lng fraction
        frac_x = (x_mm - min_x) / width_mm if width_mm > 0 else 0
        frac_z = (z_mm - min_z) / depth_mm if depth_mm > 0 else 0

        # Map to lat/lng (z=north-south=lat, x=east-west=lng)
        target_lat = lat_min + frac_z * lat_range
        target_lng = lng_min + frac_x * lng_range

        # Find grid cell
        cell_x = int(frac_x * GRID_CELLS)
        cell_z = int(frac_z * GRID_CELLS)
        cell_x = max(0, min(GRID_CELLS - 1, cell_x))
        cell_z = max(0, min(GRID_CELLS - 1, cell_z))

        # Search in current cell and neighbors (3x3 area)
        best_dist = float('inf')
        best_elev = min_elev_ft
        for dx in range(-1, 2):
            for dz in range(-1, 2):
                key = (cell_x + dx, cell_z + dz)
                if key in elev_grid:
                    for pt in elev_grid[key]:
                        pt_lat = pt.get('lat', 0)
                        pt_lng = pt.get('lng', 0)
                        dist = (pt_lat - target_lat) ** 2 + (pt_lng - target_lng) ** 2
                        if dist < best_dist:
                            best_dist = dist
                            best_elev = pt.get('elevation_ft', min_elev_ft)
        return best_elev

    # Point-in-polygon test
    def point_in_polygon(px, pz, poly):
        n = len(poly)
        inside = False
        j = n - 1
        for i in range(n):
            xi, zi = poly[i]
            xj, zj = poly[j]
            if ((zi > pz) != (zj > pz)) and (px < (xj - xi) * (pz - zi) / (zj - zi) + xi):
                inside = not inside
            j = i
        return inside

    # Generate grid points inside polygon with elevation
    vertices = []
    indices = []
    grid_points = []
    step_x = width_mm / grid_resolution
    step_z = depth_mm / grid_resolution

    # Offset elevation so min is at ground level (-10mm)
    elevation_offset = -min_elev_ft - 0.0328  # ft

    for iz in range(grid_resolution + 1):
        for ix in range(grid_resolution + 1):
            px = min_x + ix * step_x
            pz = min_z + iz * step_z

            if point_in_polygon(px, pz, vertices_mm):
                # Get elevation at this point
                elev_ft = get_elevation_at(px, pz)
                elev_mm = (elev_ft + elevation_offset) * FT_TO_MM

                u = ix / grid_resolution
                v = iz / grid_resolution
                idx = len(vertices)
                vertices.append(TerrainVertex(px, elev_mm, pz, 0, 1, 0, u, v))
                grid_points.append((ix, iz, idx))

    if len(vertices) < 3:
        return generate_polygon_terrain(vertices_mm, min_elev_ft)

    # Create triangles
    point_map = {(gp[0], gp[1]): gp[2] for gp in grid_points}

    for ix, iz, idx in grid_points:
        right = (ix + 1, iz)
        bottom = (ix, iz + 1)
        diag = (ix + 1, iz + 1)

        if right in point_map and bottom in point_map:
            if diag in point_map:
                indices.extend([idx, point_map[bottom], point_map[right]])
                indices.extend([point_map[right], point_map[bottom], point_map[diag]])
            else:
                indices.extend([idx, point_map[bottom], point_map[right]])

    # Compute normals
    for i, vertex in enumerate(vertices):
        # Find adjacent vertices for normal calculation
        neighbors = []
        for ix, iz, idx in grid_points:
            if idx == i:
                for dx, dz in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    neighbor_key = (ix + dx, iz + dz)
                    if neighbor_key in point_map:
                        neighbors.append(vertices[point_map[neighbor_key]])
                break

        if len(neighbors) >= 2:
            # Compute normal from cross product
            v1 = (neighbors[0].x - vertex.x, neighbors[0].y - vertex.y, neighbors[0].z - vertex.z)
            v2 = (neighbors[1].x - vertex.x, neighbors[1].y - vertex.y, neighbors[1].z - vertex.z)
            nx = v1[1] * v2[2] - v1[2] * v2[1]
            ny = v1[2] * v2[0] - v1[0] * v2[2]
            nz = v1[0] * v2[1] - v1[1] * v2[0]
            length = math.sqrt(nx*nx + ny*ny + nz*nz)
            if length > 0:
                vertex.nx = nx / length
                vertex.ny = abs(ny / length)  # Ensure normal points up
                vertex.nz = nz / length

    print(f"[Terrain] Polygon+elevation terrain: {len(vertices)} vertices, {len(indices)//3} triangles")
    print(f"[Terrain] Elevation range in mesh: {min_elev_ft:.1f}' to {max_elev_ft:.1f}'")

    return TerrainMesh(
        vertices=vertices,
        indices=indices,
        width_ft=width_mm / FT_TO_MM,
        depth_ft=depth_mm / FT_TO_MM,
        min_elevation=min_elev_ft,
        max_elevation=max_elev_ft
    )


def generate_polygon_terrain(vertices_mm: List[Tuple[float, float]], elevation_ft: float = 0.0) -> TerrainMesh:
    """
    Generate terrain mesh from polygon vertices (quadrilateral or any convex polygon).

    Args:
        vertices_mm: List of [x_mm, z_mm] polygon vertices in order
        elevation_ft: Base elevation in feet

    Returns:
        TerrainMesh matching the polygon shape
    """
    if not vertices_mm or len(vertices_mm) < 3:
        print("[Terrain] Need at least 3 vertices for polygon terrain")
        return None

    vertices = []
    indices = []
    FT_TO_MM = 304.8

    # Convert elevation to mm
    elev_mm = elevation_ft * FT_TO_MM

    # Find bounding box for width/depth
    xs = [v[0] for v in vertices_mm]
    zs = [v[1] for v in vertices_mm]
    min_x, max_x = min(xs), max(xs)
    min_z, max_z = min(zs), max(zs)
    width_mm = max_x - min_x
    depth_mm = max_z - min_z

    print(f"[Terrain] Generating polygon terrain with {len(vertices_mm)} vertices")

    # Create vertices at polygon corners
    for i, (x_mm, z_mm) in enumerate(vertices_mm):
        # UV based on position within bounding box
        u = (x_mm - min_x) / width_mm if width_mm > 0 else 0
        v = (z_mm - min_z) / depth_mm if depth_mm > 0 else 0

        vertices.append(TerrainVertex(x_mm, elev_mm, z_mm, 0, 1, 0, u, v))

    # Add center point for fan triangulation
    center_x = sum(xs) / len(xs)
    center_z = sum(zs) / len(zs)
    center_u = 0.5
    center_v = 0.5
    center_idx = len(vertices)
    vertices.append(TerrainVertex(center_x, elev_mm, center_z, 0, 1, 0, center_u, center_v))

    # Create triangles from center to each edge (fan triangulation)
    n = len(vertices_mm)
    for i in range(n):
        next_i = (i + 1) % n
        # CCW winding: center, current, next
        indices.extend([center_idx, i, next_i])

    print(f"[Terrain] Polygon terrain: {len(vertices)} vertices, {len(indices)//3} triangles")

    return TerrainMesh(
        vertices=vertices,
        indices=indices,
        width_ft=width_mm / FT_TO_MM,
        depth_ft=depth_mm / FT_TO_MM,
        min_elevation=elevation_ft,
        max_elevation=elevation_ft
    )


def generate_polygon_terrain_with_grid(vertices_mm: List[Tuple[float, float]],
                                        grid_resolution: int = 10,
                                        elevation_ft: float = 0.0) -> TerrainMesh:
    """
    Generate terrain mesh from polygon with internal grid for smoother surface.

    Args:
        vertices_mm: List of [x_mm, z_mm] polygon vertices
        grid_resolution: Number of grid divisions for internal mesh
        elevation_ft: Base elevation in feet

    Returns:
        TerrainMesh with gridded interior
    """
    if not vertices_mm or len(vertices_mm) < 3:
        return None

    FT_TO_MM = 304.8
    elev_mm = elevation_ft * FT_TO_MM

    # Get bounding box
    xs = [v[0] for v in vertices_mm]
    zs = [v[1] for v in vertices_mm]
    min_x, max_x = min(xs), max(xs)
    min_z, max_z = min(zs), max(zs)
    width_mm = max_x - min_x
    depth_mm = max_z - min_z

    vertices = []
    indices = []

    # Helper: check if point is inside polygon (ray casting)
    def point_in_polygon(px, pz, poly):
        n = len(poly)
        inside = False
        j = n - 1
        for i in range(n):
            xi, zi = poly[i]
            xj, zj = poly[j]
            if ((zi > pz) != (zj > pz)) and (px < (xj - xi) * (pz - zi) / (zj - zi) + xi):
                inside = not inside
            j = i
        return inside

    # Generate grid points inside polygon
    grid_points = []
    step_x = width_mm / grid_resolution
    step_z = depth_mm / grid_resolution

    for iz in range(grid_resolution + 1):
        for ix in range(grid_resolution + 1):
            px = min_x + ix * step_x
            pz = min_z + iz * step_z

            if point_in_polygon(px, pz, vertices_mm):
                u = ix / grid_resolution
                v = iz / grid_resolution
                idx = len(vertices)
                vertices.append(TerrainVertex(px, elev_mm, pz, 0, 1, 0, u, v))
                grid_points.append((ix, iz, idx))

    if len(vertices) < 3:
        # Fall back to simple polygon if grid is too sparse
        return generate_polygon_terrain(vertices_mm, elevation_ft)

    # Create triangles using Delaunay-like approach (simplified)
    # Group points by grid position for neighbor lookup
    point_map = {(gp[0], gp[1]): gp[2] for gp in grid_points}

    for ix, iz, idx in grid_points:
        # Try to form triangles with right and bottom neighbors
        right = (ix + 1, iz)
        bottom = (ix, iz + 1)
        diag = (ix + 1, iz + 1)

        if right in point_map and bottom in point_map:
            # Two triangles forming a quad
            if diag in point_map:
                # Full quad
                indices.extend([idx, point_map[bottom], point_map[right]])
                indices.extend([point_map[right], point_map[bottom], point_map[diag]])
            else:
                # Single triangle
                indices.extend([idx, point_map[bottom], point_map[right]])

    print(f"[Terrain] Polygon grid terrain: {len(vertices)} vertices, {len(indices)//3} triangles")

    return TerrainMesh(
        vertices=vertices,
        indices=indices,
        width_ft=width_mm / FT_TO_MM,
        depth_ft=depth_mm / FT_TO_MM,
        min_elevation=elevation_ft,
        max_elevation=elevation_ft
    )


def generate_test_terrain(width_ft: float = 100, depth_ft: float = 100, grid_size: int = 15) -> TerrainMesh:
    """
    Generate a simple test terrain with gentle rolling hills.

    Args:
        width_ft: Terrain width in feet
        depth_ft: Terrain depth in feet
        grid_size: Number of grid points per axis

    Returns:
        TerrainMesh object for testing
    """
    vertices = []
    indices = []

    # Convert to mm (renderer uses mm internally with Y-up)
    FT_TO_MM = 304.8
    width_mm = width_ft * FT_TO_MM
    depth_mm = depth_ft * FT_TO_MM

    # Generate vertices with simple sine-wave hills
    min_elev = 0.0
    max_elev = 0.0

    for z in range(grid_size):
        for x in range(grid_size):
            # Position in mm - terrain starts at origin and extends positive (like buildings)
            px = (x / (grid_size - 1)) * width_mm
            pz = (z / (grid_size - 1)) * depth_mm

            # SIMPLE TEST: Tilted plane - should be VERY obvious
            # X axis: 0 to 100ft, elevation goes from 0mm to 15000mm (50ft!)
            # Z axis: constant 5000mm elevation
            elev_mm = (x / (grid_size - 1)) * 15000.0  # 0 to 50ft ramp on X
            if z == 0 and x == 0:
                print(f"[Terrain] DEBUG: Vertex (0,0) elevation = {elev_mm:.1f} mm")
            if z == 0 and x == grid_size - 1:
                print(f"[Terrain] DEBUG: Vertex ({grid_size-1},0) elevation = {elev_mm:.1f} mm")

            min_elev = min(min_elev, elev_mm)
            max_elev = max(max_elev, elev_mm)

            # UV coordinates
            u = x / (grid_size - 1)
            v = z / (grid_size - 1)

            # Normal will be computed after
            vertices.append(TerrainVertex(px, elev_mm, pz, 0, 1, 0, u, v))

    # Compute proper normals using finite differences
    for z in range(grid_size):
        for x in range(grid_size):
            idx = z * grid_size + x

            # Get neighboring heights
            h_left = vertices[idx - 1].y if x > 0 else vertices[idx].y
            h_right = vertices[idx + 1].y if x < grid_size - 1 else vertices[idx].y
            h_down = vertices[idx - grid_size].y if z > 0 else vertices[idx].y
            h_up = vertices[idx + grid_size].y if z < grid_size - 1 else vertices[idx].y

            # Compute normal from height differences
            dx = width_mm / (grid_size - 1)
            dz = depth_mm / (grid_size - 1)

            nx = (h_left - h_right) / (2 * dx)
            nz = (h_down - h_up) / (2 * dz)
            ny = 1.0

            # Normalize
            length = math.sqrt(nx*nx + ny*ny + nz*nz)
            if length > 0.0001:
                vertices[idx].nx = nx / length
                vertices[idx].ny = ny / length
                vertices[idx].nz = nz / length

    # Generate triangle indices
    for z in range(grid_size - 1):
        for x in range(grid_size - 1):
            top_left = z * grid_size + x
            top_right = top_left + 1
            bottom_left = (z + 1) * grid_size + x
            bottom_right = bottom_left + 1

            # Two triangles per quad (counter-clockwise winding for front faces when viewed from above)
            # Vulkan uses CCW as front face by default
            indices.extend([top_left, bottom_left, top_right])
            indices.extend([top_right, bottom_left, bottom_right])

    # Print sample vertices to debug
    print(f"[Terrain] Sample vertex positions:")
    print(f"  (0,0): pos=[{vertices[0].x:.1f}, {vertices[0].y:.1f}, {vertices[0].z:.1f}]")
    mid_idx = len(vertices) // 2
    print(f"  (mid): pos=[{vertices[mid_idx].x:.1f}, {vertices[mid_idx].y:.1f}, {vertices[mid_idx].z:.1f}]")
    last_idx = len(vertices) - 1
    print(f"  (last): pos=[{vertices[last_idx].x:.1f}, {vertices[last_idx].y:.1f}, {vertices[last_idx].z:.1f}]")

    print(f"[Terrain] Generated test terrain: {len(vertices)} vertices, {len(indices)//3} triangles")
    print(f"[Terrain] Position range: X=[0, {width_mm:.0f}], Z=[0, {depth_mm:.0f}] mm")
    print(f"[Terrain] Elevation range: Y=[{min_elev:.0f}, {max_elev:.0f}] mm")

    return TerrainMesh(
        vertices=vertices,
        indices=indices,
        width_ft=width_ft,
        depth_ft=depth_ft,
        min_elevation=min_elev / FT_TO_MM,
        max_elevation=max_elev / FT_TO_MM
    )
