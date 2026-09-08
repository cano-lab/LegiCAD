import trimesh
import numpy as np
from PIL import Image
from pathlib import Path
from dataclasses import dataclass
import math

print("=== CHANNEL_EXTRACTOR MODULE LOADED ===")

@dataclass
class CameraData:
    eye: np.ndarray
    forward: np.ndarray
    up: np.ndarray
    is_perspective: bool
    field_of_view: float
    ortho_bounds: tuple[float, float] | None
    near_clip: float
    far_clip: float
    
    @classmethod
    def from_revit_response(cls, data: dict) -> "CameraData":
        return cls(
            eye=np.array(data["Eye"]),
            forward=np.array(data["Forward"]),
            up=np.array(data["Up"]),
            is_perspective=data["IsPerspective"],
            field_of_view=data.get("FieldOfView", math.pi / 4),
            ortho_bounds=tuple(data["OrthoBounds"]) if data.get("OrthoBounds") else None,
            near_clip=data.get("NearClip", 0.1),
            far_clip=data.get("FarClip", 10000)
        )


@dataclass 
class ViewExportData:
    geometry_path: str
    camera: CameraData
    material_map: dict[str, int]
    bounding_box: np.ndarray
    
    @classmethod
    def from_revit_response(cls, data: dict) -> "ViewExportData":
        return cls(
            geometry_path=data["GeometryPath"],
            camera=CameraData.from_revit_response(data["Camera"]),
            material_map=data["MaterialMap"],
            bounding_box=np.array(data["BoundingBox"])
        )


class ChannelExtractor:
    """Extracts render channels from Revit geometry exports."""
    
    def __init__(self, export_data: ViewExportData):
        self.export_data = export_data
        self.mesh = trimesh.load(export_data.geometry_path)
        self.scene = self._setup_scene()
    
    def _setup_scene(self) -> trimesh.Scene:
        """Configure scene with camera matching Revit view."""
        if isinstance(self.mesh, trimesh.Scene):
            scene = self.mesh
        else:
            scene = trimesh.Scene(self.mesh)
        
        camera_transform = self._build_camera_transform()
        scene.camera_transform = camera_transform
        
        return scene
    
    def _build_camera_transform(self) -> np.ndarray:
        """Convert Revit camera data to trimesh transform matrix."""
        cam = self.export_data.camera
        
        forward = cam.forward / np.linalg.norm(cam.forward)
        up = cam.up / np.linalg.norm(cam.up)
        right = np.cross(forward, up)
        right = right / np.linalg.norm(right)
        up = np.cross(right, forward)
        
        transform = np.eye(4)
        transform[:3, 0] = right
        transform[:3, 1] = up
        transform[:3, 2] = -forward
        transform[:3, 3] = cam.eye
        
        return transform
    
    def extract_all(
        self,
        output_dir: str,
        channels: list[str] = None,
        resolution: tuple[int, int] = (3840, 2160)
    ) -> dict[str, str]:
        """Extract all requested channels."""
        print("=== EXTRACT_ALL CALLED ===")
        print(f"Channels: {channels}")
        
        if channels is None:
            channels = ["depth", "normals", "material_id", "edges"]
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        results = {}
        
        for channel in channels:
            extractor_method = getattr(self, f"_extract_{channel}", None)
            if extractor_method:
                results[channel] = extractor_method(output_path, resolution)
            else:
                print(f"Unknown channel: {channel}")
        
        return results
    
    def _extract_depth(self, output_path: Path, resolution: tuple[int, int]) -> str:
        """Extract depth channel - near=white, far=black."""
        print("=== EXTRACT DEPTH CALLED ===")
    
        depth_image = self._render_depth_buffer(resolution)
    
        far_clip = self.export_data.camera.far_clip
        # Filter out both background (0) and far plane
        valid_depths = depth_image[(depth_image > 0.1) & (depth_image < far_clip * 0.99)]
    
        print(f"Far clip: {far_clip}")
        print(f"Depth image min: {depth_image.min()}, max: {depth_image.max()}")
    
        if len(valid_depths) > 0:
            min_depth = valid_depths.min()
            max_depth = valid_depths.max()
            print(f"Valid depths min: {min_depth}, max: {max_depth}")
        else:
            bbox = self.export_data.bounding_box
            min_depth = 0.1
            max_depth = np.linalg.norm(bbox[3:] - bbox[:3])
    
        print(f"Using range: {min_depth} to {max_depth}")
    
        # Normalize to actual range, invert (near=white)
        depth_normalized = (depth_image - min_depth) / (max_depth - min_depth + 1e-6)
        depth_normalized = np.clip(1.0 - depth_normalized, 0, 1)
    
        # Background (0 or far plane) should be black
        depth_normalized[(depth_image < 0.1) | (depth_image >= far_clip * 0.99)] = 0
    
        # Convert to 16-bit
        depth_16bit = (depth_normalized * 65535).astype(np.uint16)
    
        filepath = output_path / "depth.png"
        Image.fromarray(depth_16bit, mode='I;16').save(filepath)
    
        return str(filepath)
    
    def _render_depth_buffer(self, resolution: tuple[int, int]) -> np.ndarray:
        """Render depth buffer using trimesh."""
        try:
            import pyrender
            return self._render_depth_pyrender(resolution)
        except ImportError:
            return self._render_depth_trimesh(resolution)
    
    def _render_depth_pyrender(self, resolution: tuple[int, int]) -> np.ndarray:
        """Render depth using pyrender for accurate Z-buffer."""
        import pyrender
        
        pr_scene = pyrender.Scene.from_trimesh_scene(self.scene)
        
        cam = self.export_data.camera
        if cam.is_perspective:
            camera = pyrender.PerspectiveCamera(
                yfov=cam.field_of_view,
                znear=cam.near_clip,
                zfar=cam.far_clip
            )
        else:
            camera = pyrender.OrthographicCamera(
                xmag=cam.ortho_bounds[0] / 2,
                ymag=cam.ortho_bounds[1] / 2,
                znear=cam.near_clip,
                zfar=cam.far_clip
            )
        
        camera_node = pr_scene.add(camera, pose=self.scene.camera_transform)
        
        renderer = pyrender.OffscreenRenderer(resolution[0], resolution[1])
        _, depth = renderer.render(pr_scene)
        renderer.delete()
        
        return depth
    
    def _render_depth_trimesh(self, resolution: tuple[int, int]) -> np.ndarray:
        """Fallback depth rendering using trimesh ray casting."""
        cam = self.export_data.camera
        width, height = resolution
        aspect = width / height
        
        depth_buffer = np.full((height, width), cam.far_clip, dtype=np.float32)
        
        batch_size = 10000
        rays_origin = []
        rays_direction = []
        pixel_indices = []
        
        right = np.cross(cam.forward, cam.up)
        right = right / np.linalg.norm(right)
        
        for y in range(height):
            for x in range(width):
                ndc_x = (2 * x / width - 1) * math.tan(cam.field_of_view / 2) * aspect
                ndc_y = (1 - 2 * y / height) * math.tan(cam.field_of_view / 2)
                
                direction = cam.forward + right * ndc_x + cam.up * ndc_y
                direction = direction / np.linalg.norm(direction)
                
                rays_origin.append(cam.eye)
                rays_direction.append(direction)
                pixel_indices.append((y, x))
                
                if len(rays_origin) >= batch_size:
                    self._cast_ray_batch(rays_origin, rays_direction, pixel_indices, depth_buffer)
                    rays_origin, rays_direction, pixel_indices = [], [], []
        
        if rays_origin:
            self._cast_ray_batch(rays_origin, rays_direction, pixel_indices, depth_buffer)
        
        return depth_buffer
    
    def _cast_ray_batch(self, origins, directions, indices, depth_buffer):
        """Cast a batch of rays and update depth buffer."""
        origins = np.array(origins)
        directions = np.array(directions)
        
        if isinstance(self.mesh, trimesh.Scene):
            mesh = self.mesh.dump(concatenate=True)
        else:
            mesh = self.mesh
        
        locations, index_ray, _ = mesh.ray.intersects_location(
            ray_origins=origins,
            ray_directions=directions
        )
        
        for i, loc in zip(index_ray, locations):
            y, x = indices[i]
            dist = np.linalg.norm(loc - origins[i])
            depth_buffer[y, x] = min(depth_buffer[y, x], dist)
    
    def _extract_normals(self, output_path: Path, resolution: tuple[int, int]) -> str:
        """Extract normals from depth gradient."""
        print("=== EXTRACT NORMALS CALLED ===")
    
        # Get depth buffer
        depth_image = self._render_depth_buffer(resolution)
    
        far_clip = self.export_data.camera.far_clip
    
        # Compute normals from depth gradient
        height, width = depth_image.shape
    
        # Sobel gradients
        from scipy import ndimage
        dz_dx = ndimage.sobel(depth_image, axis=1)  # horizontal gradient
        dz_dy = ndimage.sobel(depth_image, axis=0)  # vertical gradient
    
        # Construct normal vectors: n = (-dz/dx, -dz/dy, 1) normalized
        normals = np.zeros((height, width, 3), dtype=np.float32)
        normals[:, :, 0] = -dz_dx
        normals[:, :, 1] = -dz_dy
        normals[:, :, 2] = 1.0
    
        # Normalize
        magnitude = np.sqrt(np.sum(normals ** 2, axis=2, keepdims=True))
        magnitude[magnitude == 0] = 1  # avoid divide by zero
        normals = normals / magnitude
    
        # Mask out background (where depth is 0 or at far clip)
        background = (depth_image < 0.1) | (depth_image >= far_clip * 0.99)
        normals[background] = [0, 0, 0]
    
        # Convert from [-1, 1] to [0, 255]
        # Background becomes gray (128, 128, 128) with standard encoding
        normals_rgb = ((normals + 1) / 2 * 255).astype(np.uint8)
    
        # Set background to neutral gray
        normals_rgb[background] = [128, 128, 128]
    
        filepath = output_path / "normals.png"
        Image.fromarray(normals_rgb, mode='RGB').save(filepath)
    
        return str(filepath)
    
    def _render_normals_raycast(self, resolution: tuple[int, int]) -> np.ndarray:
        """Render normals via ray casting."""
        print("=== RENDER NORMALS RAYCAST ===")
    
        cam = self.export_data.camera
        width, height = resolution
        aspect = width / height
    
        normals_buffer = np.zeros((height, width, 3), dtype=np.float32)
    
        if isinstance(self.mesh, trimesh.Scene):
            mesh = self.mesh.dump(concatenate=True)
        else:
            mesh = self.mesh
    
        right = np.cross(cam.forward, cam.up)
        right = right / np.linalg.norm(right)
    
        # Process row by row for memory efficiency
        for y in range(height):
            if y % 100 == 0:
                print(f"  Normals: row {y}/{height}")
        
            origins = []
            directions = []
        
            for x in range(width):
                ndc_x = (2 * x / width - 1) * math.tan(cam.field_of_view / 2) * aspect
                ndc_y = (1 - 2 * y / height) * math.tan(cam.field_of_view / 2)
            
                direction = cam.forward + right * ndc_x + cam.up * ndc_y
                direction = direction / np.linalg.norm(direction)
            
                origins.append(cam.eye)
                directions.append(direction)
        
            origins = np.array(origins)
            directions = np.array(directions)
        
            locations, index_ray, index_tri = mesh.ray.intersects_location(
                ray_origins=origins,
                ray_directions=directions
            )
        
            for i, tri_idx in zip(index_ray, index_tri):
                normal = mesh.face_normals[tri_idx]
                normals_buffer[y, i] = normal
    
        return normals_buffer
    
    def _extract_material_id(self, output_path: Path, resolution: tuple[int, int]) -> str:
        """Extract material IDs as flat colors."""
        print("=== EXTRACT MATERIAL ID CALLED ===")
    
        import pyrender
    
        material_map = self.export_data.material_map
        num_materials = max(len(material_map), 1)
        colors = self._generate_distinct_colors(num_materials + 10)
    
        height, width = resolution[1], resolution[0]
    
        # Build normalized material name lookup
        # Normalize: lowercase, remove spaces, dashes, underscores
        def normalize_name(name):
            return name.lower().replace(' ', '').replace('-', '').replace('_', '').replace(',', '')
    
        material_colors = {}
        normalized_map = {}
        for mat_name, mat_idx in material_map.items():
            color = colors[mat_idx % len(colors)]
            material_colors[mat_name] = color
            normalized_map[normalize_name(mat_name)] = color
    
        print(f"Material map has {len(material_map)} materials")
    
        # Get camera setup
        cam = self.export_data.camera
        if cam.is_perspective:
            camera = pyrender.PerspectiveCamera(
                yfov=cam.field_of_view,
                znear=cam.near_clip,
                zfar=cam.far_clip
            )
        else:
            camera = pyrender.OrthographicCamera(
                xmag=cam.ortho_bounds[0] / 2,
                ymag=cam.ortho_bounds[1] / 2,
                znear=cam.near_clip,
                zfar=cam.far_clip
            )
    
        # Create renderer
        renderer = pyrender.OffscreenRenderer(width, height)
    
        # Build scene with all geometries, each with flat material color
        scene = pyrender.Scene(ambient_light=[1.0, 1.0, 1.0], bg_color=[0, 0, 0, 0])
        scene.add(camera, pose=self.scene.camera_transform)
    
        matched = 0
        unmatched = []
    
        if isinstance(self.mesh, trimesh.Scene):
            for geom_name, geom in self.mesh.geometry.items():
                # Get material name from geometry
                mat_name = None
                if hasattr(geom, 'visual') and hasattr(geom.visual, 'material'):
                    mat_name = getattr(geom.visual.material, 'name', None)
            
                if not mat_name:
                    mat_name = geom_name
            
                # Try to match - first exact, then normalized
                color = None
                if mat_name in material_colors:
                    color = material_colors[mat_name]
                    matched += 1
                else:
                    normalized = normalize_name(mat_name)
                    if normalized in normalized_map:
                        color = normalized_map[normalized]
                        matched += 1
                    else:
                        # Assign a unique color based on geometry index
                        color = colors[hash(mat_name) % len(colors)]
                        unmatched.append(mat_name)
            
                # Create flat colored material
                flat_material = pyrender.MetallicRoughnessMaterial(
                    baseColorFactor=[color[0]/255, color[1]/255, color[2]/255, 1.0],
                    metallicFactor=0.0,
                    roughnessFactor=1.0
                )
            
                # Add mesh to scene
                try:
                    pr_mesh = pyrender.Mesh.from_trimesh(geom, material=flat_material)
                    scene.add(pr_mesh)
                except Exception as e:
                    print(f"  Failed to add {geom_name}: {e}")
    
        print(f"Matched {matched} materials, {len(unmatched)} unmatched")
        if unmatched[:5]:
            print(f"  Unmatched samples: {unmatched[:5]}")
    
        # Render
        color_img, _ = renderer.render(scene)
        renderer.delete()
    
        filepath = output_path / "material_id.png"
        Image.fromarray(color_img, mode='RGB').save(filepath)
    
        return str(filepath)
    
    def _generate_distinct_colors(self, n: int) -> list[tuple[int, int, int]]:
        """Generate n visually distinct colors."""
        colors = []
        for i in range(n):
            hue = i / n
            r, g, b = self._hsv_to_rgb(hue, 1.0, 1.0)
            colors.append((int(r * 255), int(g * 255), int(b * 255)))
        return colors
    
    def _hsv_to_rgb(self, h, s, v):
        if s == 0.0:
            return (v, v, v)
        i = int(h * 6)
        f = (h * 6) - i
        p = v * (1 - s)
        q = v * (1 - s * f)
        t = v * (1 - s * (1 - f))
        i %= 6
        if i == 0: return (v, t, p)
        if i == 1: return (q, v, p)
        if i == 2: return (p, v, t)
        if i == 3: return (p, q, v)
        if i == 4: return (t, p, v)
        if i == 5: return (v, p, q)
    def _extract_shadow(self, output_path: Path, resolution: tuple[int, int], 
                        light_direction: tuple = (0.5, 0.8, 0.3)) -> str:
        """Extract shadow pass using batched ray casting."""
        print("=== EXTRACT SHADOW CALLED ===")
    
        height, width = resolution[1], resolution[0]
    
        # First render depth to get visible surface points
        depth_buffer = self._render_depth_buffer(resolution)
    
        cam = self.export_data.camera
        far_clip = cam.far_clip
    
        # Normalize light direction
        light_dir = np.array(light_direction)
        light_dir = light_dir / np.linalg.norm(light_dir)
    
        # Get mesh for ray casting
        if isinstance(self.mesh, trimesh.Scene):
            mesh = self.mesh.to_geometry()
        else:
            mesh = self.mesh
    
        # Camera parameters
        aspect = width / height
        fov_y = cam.field_of_view
        fov_x = 2 * math.atan(math.tan(fov_y / 2) * aspect)
    
        forward = np.array(cam.forward)
        up = np.array(cam.up)
        right = np.cross(forward, up)
        right = right / np.linalg.norm(right)
        eye = np.array(cam.eye)
    
        shadow_buffer = np.ones((height, width), dtype=np.float32)
    
        stride = 2  # Higher quality
        print(f"  Collecting surface points (stride={stride})...")
    
        # Collect all valid surface points first
        origins = []
        pixel_coords = []
    
        for y in range(0, height, stride):
            for x in range(0, width, stride):
                depth = depth_buffer[y, x]
            
                if depth < 0.1 or depth >= far_clip * 0.99:
                    continue
            
                ndc_x = (2 * x / width - 1) * math.tan(fov_x / 2)
                ndc_y = (1 - 2 * y / height) * math.tan(fov_y / 2)
            
                ray_dir = forward + right * ndc_x + up * ndc_y
                ray_dir = ray_dir / np.linalg.norm(ray_dir)
            
                world_pos = eye + ray_dir * depth
                shadow_origin = world_pos + light_dir * 0.5
            
                origins.append(shadow_origin)
                pixel_coords.append((y, x))
    
        print(f"  Casting {len(origins)} shadow rays in batch...")
    
        if len(origins) > 0:
            origins = np.array(origins)
            directions = np.tile(light_dir, (len(origins), 1))
        
            # Batch ray cast
            hits = mesh.ray.intersects_any(
                ray_origins=origins,
                ray_directions=directions
            )
        
            # Apply results
            for i, (y, x) in enumerate(pixel_coords):
                shadow_val = 0.2 if hits[i] else 1.0  # Darker shadows
            
                # Fill stride block
                for dy in range(stride):
                    for dx in range(stride):
                        if y + dy < height and x + dx < width:
                            shadow_buffer[y + dy, x + dx] = shadow_val
    
        # Soften shadows more
        from scipy.ndimage import gaussian_filter
        shadow_buffer = gaussian_filter(shadow_buffer, sigma=3.0)
    
        # Blend with depth mask to keep background white
        background = depth_buffer < 0.1
        shadow_buffer[background] = 1.0
    
        shadow_img = (shadow_buffer * 255).astype(np.uint8)
    
        filepath = output_path / "shadow.png"
        Image.fromarray(shadow_img, mode='L').save(filepath)
    
        print(f"  Shadow pass saved to {filepath}")
        return str(filepath)


    def _extract_curvature(self, output_path: Path, resolution: tuple[int, int]) -> str:
        """Extract surface curvature from depth buffer."""
        print("=== EXTRACT CURVATURE CALLED ===")
    
        from scipy import ndimage
        from scipy.ndimage import gaussian_filter
    
        height, width = resolution[1], resolution[0]
        depth_buffer = self._render_depth_buffer(resolution)
    
        cam = self.export_data.camera
        far_clip = cam.far_clip
    
        # Compute second derivatives (curvature)
        # First smooth slightly to reduce noise
        depth_smooth = gaussian_filter(depth_buffer, sigma=1.0)
    
        # Second derivatives
        d2z_dx2 = ndimage.sobel(ndimage.sobel(depth_smooth, axis=1), axis=1)
        d2z_dy2 = ndimage.sobel(ndimage.sobel(depth_smooth, axis=0), axis=0)
        d2z_dxdy = ndimage.sobel(ndimage.sobel(depth_smooth, axis=1), axis=0)
    
        # Mean curvature approximation
        curvature = np.abs(d2z_dx2) + np.abs(d2z_dy2)
    
        # Normalize
        curvature = curvature / (curvature.max() + 1e-6)
    
        # Mask background
        background = (depth_buffer < 0.1) | (depth_buffer >= far_clip * 0.99)
        curvature[background] = 0
    
        # Convert to image (edges/high curvature = white)
        curvature_img = (curvature * 255).astype(np.uint8)
    
        filepath = output_path / "curvature.png"
        Image.fromarray(curvature_img, mode='L').save(filepath)
    
        print(f"  Curvature saved to {filepath}")
        return str(filepath)


    def _extract_object_id(self, output_path: Path, resolution: tuple[int, int]) -> str:
        """Extract unique color per object/element (not material)."""
        print("=== EXTRACT OBJECT ID CALLED ===")
    
        import pyrender
    
        height, width = resolution[1], resolution[0]
    
        # Generate colors for each geometry
        if isinstance(self.mesh, trimesh.Scene):
            num_objects = len(self.mesh.geometry)
        else:
            num_objects = 1
    
        colors = self._generate_distinct_colors(num_objects + 10)
    
        cam = self.export_data.camera
        if cam.is_perspective:
            camera = pyrender.PerspectiveCamera(
                yfov=cam.field_of_view,
                znear=cam.near_clip,
                zfar=cam.far_clip
            )
        else:
            camera = pyrender.OrthographicCamera(
                xmag=cam.ortho_bounds[0] / 2,
                ymag=cam.ortho_bounds[1] / 2,
                znear=cam.near_clip,
                zfar=cam.far_clip
            )
    
        renderer = pyrender.OffscreenRenderer(width, height)
    
        scene = pyrender.Scene(ambient_light=[1.0, 1.0, 1.0], bg_color=[0, 0, 0, 0])
        scene.add(camera, pose=self.scene.camera_transform)
    
        if isinstance(self.mesh, trimesh.Scene):
            for i, (geom_name, geom) in enumerate(self.mesh.geometry.items()):
                color = colors[i % len(colors)]
            
                flat_material = pyrender.MetallicRoughnessMaterial(
                    baseColorFactor=[color[0]/255, color[1]/255, color[2]/255, 1.0],
                    metallicFactor=0.0,
                    roughnessFactor=1.0
                )
            
                try:
                    pr_mesh = pyrender.Mesh.from_trimesh(geom, material=flat_material)
                    scene.add(pr_mesh)
                except Exception as e:
                    print(f"  Failed to add {geom_name}: {e}")
        else:
            flat_material = pyrender.MetallicRoughnessMaterial(
                baseColorFactor=[colors[0][0]/255, colors[0][1]/255, colors[0][2]/255, 1.0],
                metallicFactor=0.0,
                roughnessFactor=1.0
            )
            pr_mesh = pyrender.Mesh.from_trimesh(self.mesh, material=flat_material)
            scene.add(pr_mesh)
    
        color_img, _ = renderer.render(scene)
        renderer.delete()
    
        filepath = output_path / "object_id.png"
        Image.fromarray(color_img, mode='RGB').save(filepath)
    
        print(f"  Object ID saved to {filepath}")
        return str(filepath)


    def _extract_position(self, output_path: Path, resolution: tuple[int, int]) -> str:
        """Extract world space position as RGB (normalized to bounding box)."""
        print("=== EXTRACT POSITION CALLED ===")
    
        height, width = resolution[1], resolution[0]
        depth_buffer = self._render_depth_buffer(resolution)
    
        cam = self.export_data.camera
        far_clip = cam.far_clip
        bbox = self.export_data.bounding_box
    
        # Camera parameters
        aspect = width / height
        fov_y = cam.field_of_view
        fov_x = 2 * math.atan(math.tan(fov_y / 2) * aspect)
    
        forward = np.array(cam.forward)
        up = np.array(cam.up)
        right = np.cross(forward, up)
        right = right / np.linalg.norm(right)
        eye = np.array(cam.eye)
    
        # Bounding box for normalization
        bbox_min = bbox[:3]
        bbox_max = bbox[3:]
        bbox_range = bbox_max - bbox_min
        bbox_range[bbox_range == 0] = 1  # Avoid divide by zero
    
        position_buffer = np.zeros((height, width, 3), dtype=np.float32)
    
        for y in range(height):
            for x in range(width):
                depth = depth_buffer[y, x]
            
                if depth < 0.1 or depth >= far_clip * 0.99:
                    continue
            
                ndc_x = (2 * x / width - 1) * math.tan(fov_x / 2)
                ndc_y = (1 - 2 * y / height) * math.tan(fov_y / 2)
            
                ray_dir = forward + right * ndc_x + up * ndc_y
                ray_dir = ray_dir / np.linalg.norm(ray_dir)
            
                world_pos = eye + ray_dir * depth
            
                # Normalize to [0, 1] based on bounding box
                normalized = (world_pos - bbox_min) / bbox_range
                normalized = np.clip(normalized, 0, 1)
            
                position_buffer[y, x] = normalized
    
        # Convert to image
        position_img = (position_buffer * 255).astype(np.uint8)
    
        filepath = output_path / "position.png"
        Image.fromarray(position_img, mode='RGB').save(filepath)
    
        print(f"  Position saved to {filepath}")
        return str(filepath)

    def _extract_ao(self, output_path: Path, resolution: tuple[int, int],
                    num_samples: int = 16, ao_radius: float = 50.0) -> str:
        """Extract ambient occlusion by sampling hemisphere around each point."""
        print("=== EXTRACT AO CALLED ===")
    
        from scipy.ndimage import gaussian_filter
    
        height, width = resolution[1], resolution[0]
    
        depth_buffer = self._render_depth_buffer(resolution)
    
        cam = self.export_data.camera
        far_clip = cam.far_clip
    
        if isinstance(self.mesh, trimesh.Scene):
            mesh = self.mesh.to_geometry()
        else:
            mesh = self.mesh
    
        # Camera parameters
        aspect = width / height
        fov_y = cam.field_of_view
        fov_x = 2 * math.atan(math.tan(fov_y / 2) * aspect)
    
        forward = np.array(cam.forward)
        up = np.array(cam.up)
        right = np.cross(forward, up)
        right = right / np.linalg.norm(right)
        eye = np.array(cam.eye)
    
        ao_buffer = np.ones((height, width), dtype=np.float32)
    
        stride = 2
        print(f"  Collecting surface points (stride={stride})...")
    
        # Generate hemisphere sample directions
        def generate_hemisphere_samples(n, normal):
            """Generate n random directions in hemisphere around normal."""
            samples = []
            for _ in range(n):
                # Random direction in sphere
                theta = np.random.uniform(0, 2 * np.pi)
                phi = np.random.uniform(0, np.pi / 2)  # Hemisphere
            
                # Convert to cartesian (in tangent space)
                x = np.sin(phi) * np.cos(theta)
                y = np.sin(phi) * np.sin(theta)
                z = np.cos(phi)
            
                # Build tangent space basis
                tangent = np.cross(normal, [0, 0, 1])
                if np.linalg.norm(tangent) < 0.01:
                    tangent = np.cross(normal, [0, 1, 0])
                tangent = tangent / np.linalg.norm(tangent)
                bitangent = np.cross(normal, tangent)
            
                # Transform to world space
                world_dir = tangent * x + bitangent * y + normal * z
                samples.append(world_dir / np.linalg.norm(world_dir))
        
            return samples
    
        # Get normals from depth (approximate)
        from scipy import ndimage
        dz_dx = ndimage.sobel(depth_buffer, axis=1)
        dz_dy = ndimage.sobel(depth_buffer, axis=0)
    
        normals = np.zeros((height, width, 3), dtype=np.float32)
        normals[:, :, 0] = -dz_dx
        normals[:, :, 1] = -dz_dy
        normals[:, :, 2] = 1.0
        mag = np.sqrt(np.sum(normals ** 2, axis=2, keepdims=True))
        mag[mag == 0] = 1
        normals = normals / mag
    
        print(f"  Computing AO with {num_samples} samples per point...")
    
        points_data = []
    
        for y in range(0, height, stride):
            for x in range(0, width, stride):
                depth = depth_buffer[y, x]
            
                if depth < 0.1 or depth >= far_clip * 0.99:
                    continue
            
                ndc_x = (2 * x / width - 1) * math.tan(fov_x / 2)
                ndc_y = (1 - 2 * y / height) * math.tan(fov_y / 2)
            
                ray_dir = forward + right * ndc_x + up * ndc_y
                ray_dir = ray_dir / np.linalg.norm(ray_dir)
            
                world_pos = eye + ray_dir * depth
                normal = normals[y, x]
            
                # Transform normal to world space (approximate)
                world_normal = right * normal[0] + up * normal[1] - forward * normal[2]
                world_normal = world_normal / (np.linalg.norm(world_normal) + 1e-6)
            
                points_data.append((y, x, world_pos, world_normal))
    
        print(f"  Processing {len(points_data)} surface points...")
    
        # Process in batches for speed
        batch_size = 1000
        for batch_start in range(0, len(points_data), batch_size):
            batch = points_data[batch_start:batch_start + batch_size]
        
            if batch_start % 5000 == 0:
                print(f"    Batch {batch_start}/{len(points_data)}")
        
            for y, x, world_pos, world_normal in batch:
                samples = generate_hemisphere_samples(num_samples, world_normal)
            
                origins = np.array([world_pos + world_normal * 0.5] * num_samples)
                directions = np.array(samples)
            
                # Check occlusion within radius
                hits, ray_ids, _ = mesh.ray.intersects_location(
                    ray_origins=origins,
                    ray_directions=directions
                )
            
                if len(hits) > 0:
                    # Count how many rays hit something within ao_radius
                    distances = np.linalg.norm(hits - origins[ray_ids], axis=1)
                    occluded = np.sum(distances < ao_radius)
                    ao_val = 1.0 - (occluded / num_samples) * 0.8  # Keep some ambient
                else:
                    ao_val = 1.0
            
                # Fill stride block
                for dy in range(stride):
                    for dx in range(stride):
                        if y + dy < height and x + dx < width:
                            ao_buffer[y + dy, x + dx] = ao_val
    
        # Soften AO
        ao_buffer = gaussian_filter(ao_buffer, sigma=2.0)
    
        # Background white
        background = depth_buffer < 0.1
        ao_buffer[background] = 1.0
    
        ao_img = (ao_buffer * 255).astype(np.uint8)
    
        filepath = output_path / "ao.png"
        Image.fromarray(ao_img, mode='L').save(filepath)
    
        print(f"  AO pass saved to {filepath}")
        return str(filepath)
    def _extract_edges(self, output_path: Path, resolution: tuple[int, int]) -> str:
        """Extract edges/silhouettes."""
        depth_path = output_path / "depth.png"
        normals_path = output_path / "normals.png"
        
        if not depth_path.exists():
            self._extract_depth(output_path, resolution)
        if not normals_path.exists():
            self._extract_normals(output_path, resolution)
        
        depth = np.array(Image.open(depth_path)).astype(np.float32)
        normals = np.array(Image.open(normals_path)).astype(np.float32)
        
        from scipy import ndimage
        depth_edges_x = ndimage.sobel(depth, axis=1)
        depth_edges_y = ndimage.sobel(depth, axis=0)
        depth_edges = np.hypot(depth_edges_x, depth_edges_y)
        
        normal_diff = np.zeros(depth.shape, dtype=np.float32)
        for c in range(3):
            ex = ndimage.sobel(normals[:, :, c], axis=1)
            ey = ndimage.sobel(normals[:, :, c], axis=0)
            normal_diff += np.hypot(ex, ey)
        
        edges = np.clip(depth_edges / depth_edges.max() + normal_diff / normal_diff.max(), 0, 1)
        edges = (edges * 255).astype(np.uint8)
        
        filepath = output_path / "edges.png"
        Image.fromarray(edges, mode='L').save(filepath)
        
        return str(filepath)


async def render_channels(
    view_export_data: dict,
    output_dir: str,
    channels: list[str] = ["depth", "normals", "edges", "material_id", "shadow"],
    resolution: tuple[int, int] = (3840, 2160)
) -> dict[str, str]:
    """MCP tool entry point for channel extraction."""
    print("=== RENDER_CHANNELS CALLED ===")
    export_data = ViewExportData.from_revit_response(view_export_data)
    extractor = ChannelExtractor(export_data)
    
    return extractor.extract_all(output_dir, channels, resolution)