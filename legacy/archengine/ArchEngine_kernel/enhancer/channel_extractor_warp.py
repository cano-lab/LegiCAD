import warp as wp
import numpy as np
from PIL import Image
from pathlib import Path
import math

wp.init()

print("=== WARP CHANNEL EXTRACTOR LOADED ===")
print(f"Warp devices: {wp.get_devices()}")

# Use CUDA device
device = "cuda:0"


@wp.kernel
def generate_rays_kernel(
    eye: wp.vec3,
    forward: wp.vec3,
    right: wp.vec3,
    up: wp.vec3,
    fov: float,
    width: int,
    height: int,
    origins: wp.array(dtype=wp.vec3),
    directions: wp.array(dtype=wp.vec3)
):
    tid = wp.tid()
    
    x = tid % width
    y = tid // width
    
    aspect = float(width) / float(height)
    
    ndc_x = (2.0 * float(x) / float(width) - 1.0) * wp.tan(fov / 2.0) * aspect
    ndc_y = (1.0 - 2.0 * float(y) / float(height)) * wp.tan(fov / 2.0)
    
    direction = forward + right * ndc_x + up * ndc_y
    direction = wp.normalize(direction)
    
    origins[tid] = eye
    directions[tid] = direction


@wp.kernel
def shadow_rays_kernel(
    world_pos: wp.array(dtype=wp.vec3),
    light_dir: wp.vec3,
    offset: float,
    shadow_origins: wp.array(dtype=wp.vec3),
    shadow_dirs: wp.array(dtype=wp.vec3)
):
    tid = wp.tid()
    shadow_origins[tid] = world_pos[tid] + light_dir * offset
    shadow_dirs[tid] = light_dir


@wp.kernel
def compute_world_pos_kernel(
    eye: wp.vec3,
    directions: wp.array(dtype=wp.vec3),
    depths: wp.array(dtype=float),
    world_pos: wp.array(dtype=wp.vec3)
):
    tid = wp.tid()
    world_pos[tid] = eye + directions[tid] * depths[tid]


@wp.kernel
def depth_to_image_kernel(
    depths: wp.array(dtype=float),
    min_depth: float,
    max_depth: float,
    far_clip: float,
    output: wp.array(dtype=wp.uint8)
):
    tid = wp.tid()
    d = depths[tid]
    
    if d >= far_clip * 0.99 or d < 0.1:
        output[tid] = wp.uint8(0)
    else:
        normalized = (d - min_depth) / (max_depth - min_depth + 1e-6)
        normalized = 1.0 - normalized  # Invert: near = white
        normalized = wp.clamp(normalized, 0.0, 1.0)
        output[tid] = wp.uint8(normalized * 255.0)


@wp.kernel
def shadow_to_image_kernel(
    hit_mask: wp.array(dtype=wp.uint8),
    depths: wp.array(dtype=float),
    far_clip: float,
    shadow_val: float,
    output: wp.array(dtype=float)
):
    tid = wp.tid()
    
    if depths[tid] >= far_clip * 0.99 or depths[tid] < 0.1:
        output[tid] = 1.0
    elif hit_mask[tid] > wp.uint8(0):
        output[tid] = shadow_val
    else:
        output[tid] = 1.0


class WarpChannelExtractor:
    def __init__(self, mesh_path: str, camera_data: dict, bbox: np.ndarray):
        import trimesh
        self.mesh_path = mesh_path
        self.camera = camera_data
        print("Loading mesh for Warp...")

        raw_mesh = trimesh.load(mesh_path)
        if isinstance(raw_mesh, trimesh.Scene):
            raw_mesh = raw_mesh.to_geometry()
        
        self.trimesh_mesh = raw_mesh

        vertices = raw_mesh.vertices.astype(np.float32)
        faces = raw_mesh.faces.astype(np.int32)
        
        print(f"  Building BVH for {len(faces)} triangles...")
        
        # Create Warp mesh (builds BVH automatically)
        self.mesh = wp.Mesh(
            points=wp.array(vertices, dtype=wp.vec3, device=device),
            indices=wp.array(faces.flatten(), dtype=int, device=device)
        )
        
        print(f"  Mesh loaded to GPU")
        
        # Camera setup
        self.eye = wp.vec3(camera_data['Eye'][0], camera_data['Eye'][1], camera_data['Eye'][2])
        
        forward = np.array(camera_data['Forward'], dtype=np.float32)
        forward = forward / np.linalg.norm(forward)
        self.forward = wp.vec3(forward[0], forward[1], forward[2])
        
        up = np.array(camera_data['Up'], dtype=np.float32)
        up = up / np.linalg.norm(up)
        self.up = wp.vec3(up[0], up[1], up[2])
        
        right = np.cross(forward, up)
        right = right / np.linalg.norm(right)
        self.right = wp.vec3(right[0], right[1], right[2])
        
        self.fov = float(camera_data.get('FieldOfView', 0.785))
        self.near = float(camera_data.get('NearClip', 0.1))
        self.far = float(camera_data.get('FarClip', 10000))

        self.bbox = bbox
        self.section_box = None  # Clipping bounds from Revit
        self.near_clip_offset = 0.0  # Offset ray origins forward (mm)
    
    

    def _generate_rays(self, width: int, height: int):
        n_pixels = width * height
        
        origins = wp.zeros(n_pixels, dtype=wp.vec3, device=device)
        directions = wp.zeros(n_pixels, dtype=wp.vec3, device=device)
        
        wp.launch(
            kernel=generate_rays_kernel,
            dim=n_pixels,
            inputs=[self.eye, self.forward, self.right, self.up, 
                   self.fov, width, height, origins, directions],
            device=device
        )
        
        return origins, directions
    
    def _cast_rays(self, origins: wp.array, directions: wp.array, max_dist: float = None):
        if max_dist is None:
            max_dist = self.far
        
        n_rays = origins.shape[0]
        
        # Query results
        hit_faces = wp.zeros(n_rays, dtype=int, device=device)
        hit_u = wp.zeros(n_rays, dtype=float, device=device)
        hit_v = wp.zeros(n_rays, dtype=float, device=device)
        hit_sign = wp.zeros(n_rays, dtype=float, device=device)
        hit_normal = wp.zeros(n_rays, dtype=wp.vec3, device=device)
        hit_t = wp.zeros(n_rays, dtype=float, device=device)
        
        # Use mesh query
        wp.launch(
            kernel=raycast_kernel,
            dim=n_rays,
            inputs=[
                self.mesh.id,
                origins,
                directions,
                max_dist,
                hit_faces,
                hit_t
            ],
            device=device
        )
        
        return hit_faces, hit_t
    
    def extract_depth(self, output_path: str, resolution: tuple):
        print("=== WARP EXTRACT DEPTH ===")

        width, height = resolution
        n_pixels = width * height

        origins, directions = self._generate_rays(width, height)

        # Apply near clip offset if set (push origins forward to skip through walls)
        if hasattr(self, 'near_clip_offset') and self.near_clip_offset > 0:
            print(f"  Applying near clip offset: {self.near_clip_offset}mm")
            # Offset origins forward along ray direction
            origins_np = origins.numpy()
            directions_np = directions.numpy()

            # Handle structured array from warp
            if origins_np.dtype.names is not None:
                orig_arr = np.column_stack([origins_np['x'], origins_np['y'], origins_np['z']])
                dir_arr = np.column_stack([directions_np['x'], directions_np['y'], directions_np['z']])
            else:
                orig_arr = origins_np.reshape(-1, 3)
                dir_arr = directions_np.reshape(-1, 3)

            # Push origins forward
            orig_arr = orig_arr + dir_arr * self.near_clip_offset
            origins = wp.array(orig_arr.astype(np.float32), dtype=wp.vec3, device=device)

        print(f"  Casting {n_pixels} rays...")

        # Ray cast using mesh query
        depths = wp.zeros(n_pixels, dtype=float, device=device)

        wp.launch(
            kernel=mesh_raycast_kernel,
            dim=n_pixels,
            inputs=[self.mesh.id, origins, directions, self.far, depths],
            device=device
        )
        
        wp.synchronize()

        depths_np = depths.numpy()
        directions_np = directions.numpy()

        # Apply section box clipping if enabled
        if self.section_box and self.section_box.get("enabled"):
            depths_np = self._clip_depth_to_section_box(depths_np, directions_np)
            # Re-upload clipped depths to GPU for image conversion
            depths = wp.array(depths_np, dtype=float, device=device)

        # Find valid range
        valid = (depths_np > 0.1) & (depths_np < self.far * 0.99)
        if valid.any():
            min_d = depths_np[valid].min()
            max_d = depths_np[valid].max()
        else:
            min_d, max_d = 0.1, self.far

        print(f"  Depth range: {min_d:.1f} to {max_d:.1f}")
        
        # Convert to image
        output_img = wp.zeros(n_pixels, dtype=wp.uint8, device=device)
        
        wp.launch(
            kernel=depth_to_image_kernel,
            dim=n_pixels,
            inputs=[depths, min_d, max_d, self.far, output_img],
            device=device
        )
        
        wp.synchronize()
        
        depth_np = output_img.numpy().reshape(height, width)
        
        filepath = Path(output_path) / "depth.png"
        Image.fromarray(depth_np, mode='L').save(filepath)
        
        print(f"  Depth saved to {filepath}")
        return str(filepath), depths_np.reshape(height, width)
    
    def extract_shadow(self, output_path: str, resolution: tuple,
                       depth_buffer: np.ndarray = None,
                       light_direction: tuple = (0.5, 0.8, 1.0)):
        print("=== WARP EXTRACT SHADOW ===")
    
        width, height = resolution
        n_pixels = width * height
    
        if depth_buffer is None:
            _, depth_buffer = self.extract_depth(output_path, resolution)
    
        origins, directions = self._generate_rays(width, height)
    
        # Compute world positions
        depths_flat = wp.array(depth_buffer.flatten().astype(np.float32), dtype=float, device=device)
        world_pos = wp.zeros(n_pixels, dtype=wp.vec3, device=device)
    
        wp.launch(
            kernel=compute_world_pos_kernel,
            dim=n_pixels,
            inputs=[self.eye, directions, depths_flat, world_pos],
            device=device
        )
    
        # Generate shadow rays
        light_dir_np = np.array(light_direction, dtype=np.float32)
        light_dir_np = light_dir_np / np.linalg.norm(light_dir_np)
        light_dir = wp.vec3(light_dir_np[0], light_dir_np[1], light_dir_np[2])
    
        shadow_origins = wp.zeros(n_pixels, dtype=wp.vec3, device=device)
        shadow_dirs = wp.zeros(n_pixels, dtype=wp.vec3, device=device)
    
        wp.launch(
            kernel=shadow_rays_kernel,
            dim=n_pixels,
            inputs=[world_pos, light_dir, 2.0, shadow_origins, shadow_dirs],  # Larger offset
            device=device
        )
    
        print(f"  Casting {n_pixels} shadow rays...")
    
        # Cast shadow rays
        shadow_hits = wp.zeros(n_pixels, dtype=float, device=device)
    
        wp.launch(
            kernel=mesh_raycast_kernel,
            dim=n_pixels,
            inputs=[self.mesh.id, shadow_origins, shadow_dirs, self.far, shadow_hits],
            device=device
        )
    
        wp.synchronize()
    
        # Convert to shadow image
        shadow_np = shadow_hits.numpy().reshape(height, width)
        depth_valid = (depth_buffer > 0.1) & (depth_buffer < self.far * 0.99)
    
        # Start with lit (white)
        shadow_img = np.ones((height, width), dtype=np.float32)
    
        # Where shadow ray hit something before reaching far = in shadow
        in_shadow = shadow_np < (self.far * 0.99)
        shadow_img[depth_valid & in_shadow] = 0.3
    
        # Background stays white
        shadow_img[~depth_valid] = 1.0
    
        # Blur for soft shadows
        from scipy.ndimage import gaussian_filter
        shadow_img = gaussian_filter(shadow_img, sigma=3.0)
    
        shadow_out = (shadow_img * 255).astype(np.uint8)
    
        filepath = Path(output_path) / "shadow.png"
        Image.fromarray(shadow_out, mode='L').save(filepath)
    
        print(f"  Shadow saved to {filepath}")
        return str(filepath)
    
    def extract_normals(self, output_path: str, resolution: tuple, depth_buffer: np.ndarray = None):
        """Extract normals from depth gradient (fast, no ray casting)."""
        print("=== WARP EXTRACT NORMALS ===")
    
        width, height = resolution
    
        if depth_buffer is None:
            _, depth_buffer = self.extract_depth(output_path, resolution)
    
        from scipy import ndimage
    
        # Compute gradients
        dz_dx = ndimage.sobel(depth_buffer, axis=1)
        dz_dy = ndimage.sobel(depth_buffer, axis=0)
    
        # Build normal vectors
        normals = np.zeros((height, width, 3), dtype=np.float32)
        normals[:, :, 0] = -dz_dx
        normals[:, :, 1] = -dz_dy
        normals[:, :, 2] = 1.0
    
        # Normalize
        mag = np.sqrt(np.sum(normals ** 2, axis=2, keepdims=True))
        mag[mag == 0] = 1
        normals = normals / mag
    
        # Mask background
        background = (depth_buffer < 0.1) | (depth_buffer >= self.far * 0.99)
        normals[background] = [0, 0, 0]
    
        # Convert [-1,1] to [0,255]
        normals_rgb = ((normals + 1) / 2 * 255).astype(np.uint8)
        normals_rgb[background] = [128, 128, 128]
    
        filepath = Path(output_path) / "normals.png"
        Image.fromarray(normals_rgb, mode='RGB').save(filepath)
    
        print(f"  Normals saved to {filepath}")
        return str(filepath)


    def extract_edges(self, output_path: str, resolution: tuple, depth_buffer: np.ndarray = None):
        """Extract edges from depth and normals."""
        print("=== WARP EXTRACT EDGES ===")
    
        width, height = resolution
    
        if depth_buffer is None:
            _, depth_buffer = self.extract_depth(output_path, resolution)
    
        from scipy import ndimage
    
        # Depth edges
        depth_edges_x = ndimage.sobel(depth_buffer, axis=1)
        depth_edges_y = ndimage.sobel(depth_buffer, axis=0)
        depth_edges = np.hypot(depth_edges_x, depth_edges_y)
    
        # Normalize
        if depth_edges.max() > 0:
            depth_edges = depth_edges / depth_edges.max()
    
        # Mask background
        background = (depth_buffer < 0.1) | (depth_buffer >= self.far * 0.99)
        depth_edges[background] = 0
    
        edges_img = (depth_edges * 255).astype(np.uint8)
    
        filepath = Path(output_path) / "edges.png"
        Image.fromarray(edges_img, mode='L').save(filepath)
    
        print(f"  Edges saved to {filepath}")
        return str(filepath)


    def extract_curvature(self, output_path: str, resolution: tuple, depth_buffer: np.ndarray = None):
        """Extract curvature from second derivatives of depth."""
        print("=== WARP EXTRACT CURVATURE ===")
    
        width, height = resolution
    
        if depth_buffer is None:
            _, depth_buffer = self.extract_depth(output_path, resolution)
    
        from scipy import ndimage
        from scipy.ndimage import gaussian_filter
    
        # Smooth first
        depth_smooth = gaussian_filter(depth_buffer, sigma=1.0)
    
        # Second derivatives
        d2z_dx2 = ndimage.sobel(ndimage.sobel(depth_smooth, axis=1), axis=1)
        d2z_dy2 = ndimage.sobel(ndimage.sobel(depth_smooth, axis=0), axis=0)
    
        curvature = np.abs(d2z_dx2) + np.abs(d2z_dy2)
    
        # Normalize
        if curvature.max() > 0:
            curvature = curvature / curvature.max()
    
        # Mask background
        background = (depth_buffer < 0.1) | (depth_buffer >= self.far * 0.99)
        curvature[background] = 0
    
        curvature_img = (curvature * 255).astype(np.uint8)
    
        filepath = Path(output_path) / "curvature.png"
        Image.fromarray(curvature_img, mode='L').save(filepath)
    
        print(f"  Curvature saved to {filepath}")
        return str(filepath)


    def extract_ao(self, output_path: str, resolution: tuple, 
                   depth_buffer: np.ndarray = None, num_samples: int = 32):
        """Extract AO using GPU hemisphere sampling."""
        print("=== WARP EXTRACT AO ===")
    
        width, height = resolution
        n_pixels = width * height
    
        if depth_buffer is None:
            _, depth_buffer = self.extract_depth(output_path, resolution)
    
        origins, directions = self._generate_rays(width, height)
    
        # Compute world positions
        depths_flat = wp.array(depth_buffer.flatten().astype(np.float32), dtype=float, device=device)
        world_pos = wp.zeros(n_pixels, dtype=wp.vec3, device=device)
    
        wp.launch(
            kernel=compute_world_pos_kernel,
            dim=n_pixels,
            inputs=[self.eye, directions, depths_flat, world_pos],
            device=device
        )
    
        # Get normals from depth
        from scipy import ndimage
        dz_dx = ndimage.sobel(depth_buffer, axis=1)
        dz_dy = ndimage.sobel(depth_buffer, axis=0)
    
        normals_np = np.zeros((height, width, 3), dtype=np.float32)
        normals_np[:, :, 0] = -dz_dx
        normals_np[:, :, 1] = -dz_dy
        normals_np[:, :, 2] = 1.0
        mag = np.sqrt(np.sum(normals_np ** 2, axis=2, keepdims=True))
        mag[mag == 0] = 1
        normals_np = normals_np / mag
    
        # Generate random hemisphere samples
        np.random.seed(42)
        ao_buffer = np.ones(n_pixels, dtype=np.float32)
    
        # Flatten normals
        normals_flat = normals_np.reshape(-1, 3)
        world_pos_np = world_pos.numpy()
    
        depth_valid = (depth_buffer.flatten() > 0.1) & (depth_buffer.flatten() < self.far * 0.99)
        valid_indices = np.where(depth_valid)[0]
    
        print(f"  Computing AO for {len(valid_indices)} points with {num_samples} samples...")
    
        # Generate all random directions at once
        theta = np.random.uniform(0, 2 * np.pi, num_samples)
        phi = np.random.uniform(0, np.pi / 2, num_samples)
    
        base_dirs = np.stack([
            np.sin(phi) * np.cos(theta),
            np.sin(phi) * np.sin(theta),
            np.cos(phi)
        ], axis=-1).astype(np.float32)
    
        ao_radius = 50.0  # Adjust based on scene scale
    
        # Process in batches
        batch_size = 50000
        for batch_start in range(0, len(valid_indices), batch_size):
            batch_end = min(batch_start + batch_size, len(valid_indices))
            batch_idx = valid_indices[batch_start:batch_end]
            B = len(batch_idx)
        
            batch_pos = world_pos_np[batch_idx]
            batch_normals = normals_flat[batch_idx]
        
            # For each sample direction, cast rays
            total_hits = np.zeros(B, dtype=np.float32)
        
            for s in range(num_samples):
                # Simple hemisphere - just use base direction + normal offset
                sample_dir = base_dirs[s]
            
                # Flip if pointing away from normal
                dots = np.sum(batch_normals * sample_dir, axis=1)
                sample_dirs = np.where(dots[:, None] < 0, -sample_dir, sample_dir)
            
                # Offset origins along normal
                ao_origins = batch_pos + batch_normals * 1.0
            
                # Cast rays
                origins_wp = wp.array(ao_origins.astype(np.float32), dtype=wp.vec3, device=device)
                dirs_wp = wp.array(sample_dirs.astype(np.float32), dtype=wp.vec3, device=device)
                hit_dist = wp.zeros(B, dtype=float, device=device)
            
                wp.launch(
                    kernel=mesh_raycast_kernel,
                    dim=B,
                    inputs=[self.mesh.id, origins_wp, dirs_wp, ao_radius, hit_dist],
                    device=device
                )
            
                wp.synchronize()
            
                hits = hit_dist.numpy() < ao_radius
                total_hits += hits.astype(np.float32)
        
            # Compute occlusion
            occlusion = total_hits / num_samples
            ao_buffer[batch_idx] = 1.0 - occlusion * 0.7
    
        ao = ao_buffer.reshape(height, width)
    
        # Blur
        from scipy.ndimage import gaussian_filter
        ao = gaussian_filter(ao, sigma=2.0)
    
        # Background white
        ao[~depth_valid.reshape(height, width)] = 1.0
    
        ao_img = (ao * 255).astype(np.uint8)
    
        filepath = Path(output_path) / "ao.png"
        Image.fromarray(ao_img, mode='L').save(filepath)
    
        print(f"  AO saved to {filepath}")
        return str(filepath)
    
    def extract_all(self, output_path: str, resolution: tuple, channels: list = None):
        """Extract all requested channels."""
        if channels is None:
            channels = ["depth", "normals", "edges"]
    
        Path(output_path).mkdir(parents=True, exist_ok=True)
    
        results = {}
        depth_buffer = None
    
        for channel in channels:
            if channel == "base":
                results["base"] = self.extract_base(output_path, resolution)
            elif channel == "depth":
                results["depth"], depth_buffer = self.extract_depth(output_path, resolution)
            elif channel == "normals":
                results["normals"] = self.extract_normals(output_path, resolution, depth_buffer)
            elif channel == "edges":
                results["edges"] = self.extract_edges(output_path, resolution, depth_buffer)
            elif channel == "shadow":
                results["shadow"] = self.extract_shadow(output_path, resolution, depth_buffer)
            elif channel == "ao":
                results["ao"] = self.extract_ao(output_path, resolution, depth_buffer)
            elif channel == "curvature":
                results["curvature"] = self.extract_curvature(output_path, resolution, depth_buffer)
            elif channel == "material_id":
                results["material_id"] = self.extract_material_id(output_path, resolution)
            elif channel == "object_id":
                results["object_id"] = self.extract_object_id(output_path, resolution)
    
        return results

    def extract_material_id(self, output_path: str, resolution: tuple):
        """Extract material IDs as flat colors using pyrender."""
        print("=== WARP EXTRACT MATERIAL_ID ===")
    
        import pyrender
        import trimesh
    
        width, height = resolution
    
        # Reload mesh with materials
        raw_mesh = trimesh.load(self.mesh_path)
    
        # Generate distinct colors
        def generate_colors(n):
            colors = []
            for i in range(n):
                hue = i / n
                # HSV to RGB
                h = hue * 6
                x = 1 - abs(h % 2 - 1)
                if h < 1: r, g, b = 1, x, 0
                elif h < 2: r, g, b = x, 1, 0
                elif h < 3: r, g, b = 0, 1, x
                elif h < 4: r, g, b = 0, x, 1
                elif h < 5: r, g, b = x, 0, 1
                else: r, g, b = 1, 0, x
                colors.append((r, g, b))
            return colors
    
        # Setup camera
        if self.camera.get('IsPerspective', True):
            camera = pyrender.PerspectiveCamera(
                yfov=self.fov,
                znear=self.near,
                zfar=self.far
            )
        else:
            camera = pyrender.OrthographicCamera(
                xmag=self.camera.get('OrthoWidth', 100) / 2,
                ymag=self.camera.get('OrthoHeight', 100) / 2,
                znear=self.near,
                zfar=self.far
            )
    
        # Build camera transform
        forward = np.array(self.camera['Forward'])
        forward = forward / np.linalg.norm(forward)
        up = np.array(self.camera['Up'])
        up = up / np.linalg.norm(up)
        right = np.cross(forward, up)
        right = right / np.linalg.norm(right)
        up = np.cross(right, forward)
    
        cam_transform = np.eye(4)
        cam_transform[:3, 0] = right
        cam_transform[:3, 1] = up
        cam_transform[:3, 2] = -forward
        cam_transform[:3, 3] = self.camera['Eye']
    
        # Create scene
        scene = pyrender.Scene(ambient_light=[1.0, 1.0, 1.0], bg_color=[0, 0, 0, 0])
        scene.add(camera, pose=cam_transform)
    
        # Collect unique materials
        material_names = set()
        if isinstance(raw_mesh, trimesh.Scene):
            for geom in raw_mesh.geometry.values():
                if hasattr(geom, 'visual') and hasattr(geom.visual, 'material'):
                    mat_name = getattr(geom.visual.material, 'name', None)
                    if mat_name:
                        material_names.add(mat_name)
    
        material_list = sorted(list(material_names))
        colors = generate_colors(max(len(material_list), 10) + 10)
        material_color_map = {name: colors[i] for i, name in enumerate(material_list)}
    
        print(f"  Found {len(material_list)} unique materials")
    
        # Add geometry with flat material colors
        if isinstance(raw_mesh, trimesh.Scene):
            for geom_name, geom in raw_mesh.geometry.items():
                mat_name = None
                if hasattr(geom, 'visual') and hasattr(geom.visual, 'material'):
                    mat_name = getattr(geom.visual.material, 'name', None)
            
                if mat_name and mat_name in material_color_map:
                    color = material_color_map[mat_name]
                else:
                    color = colors[hash(geom_name) % len(colors)]
            
                flat_material = pyrender.MetallicRoughnessMaterial(
                    baseColorFactor=[color[0], color[1], color[2], 1.0],
                    metallicFactor=0.0,
                    roughnessFactor=1.0
                )
            
                try:
                    pr_mesh = pyrender.Mesh.from_trimesh(geom, material=flat_material)
                    scene.add(pr_mesh)
                except:
                    pass
        else:
            color = colors[0]
            flat_material = pyrender.MetallicRoughnessMaterial(
                baseColorFactor=[color[0], color[1], color[2], 1.0],
                metallicFactor=0.0,
                roughnessFactor=1.0
            )
            pr_mesh = pyrender.Mesh.from_trimesh(raw_mesh, material=flat_material)
            scene.add(pr_mesh)
    
        # Render
        renderer = pyrender.OffscreenRenderer(width, height)
        color_img, _ = renderer.render(scene)
        renderer.delete()
    
        filepath = Path(output_path) / "material_id.png"
        Image.fromarray(color_img, mode='RGB').save(filepath)
    
        print(f"  Material ID saved to {filepath}")
        return str(filepath)


    def extract_object_id(self, output_path: str, resolution: tuple):
        """Extract object IDs as flat colors (one color per geometry object)."""
        print("=== WARP EXTRACT OBJECT_ID ===")
    
        import pyrender
        import trimesh
    
        width, height = resolution
    
        # Reload mesh
        raw_mesh = trimesh.load(self.mesh_path)
    
        # Generate distinct colors
        def generate_colors(n):
            colors = []
            for i in range(n):
                hue = i / n
                h = hue * 6
                x = 1 - abs(h % 2 - 1)
                if h < 1: r, g, b = 1, x, 0
                elif h < 2: r, g, b = x, 1, 0
                elif h < 3: r, g, b = 0, 1, x
                elif h < 4: r, g, b = 0, x, 1
                elif h < 5: r, g, b = x, 0, 1
                else: r, g, b = 1, 0, x
                colors.append((r, g, b))
            return colors
    
        # Setup camera
        if self.camera.get('IsPerspective', True):
            camera = pyrender.PerspectiveCamera(
                yfov=self.fov,
                znear=self.near,
                zfar=self.far
            )
        else:
            camera = pyrender.OrthographicCamera(
                xmag=self.camera.get('OrthoWidth', 100) / 2,
                ymag=self.camera.get('OrthoHeight', 100) / 2,
                znear=self.near,
                zfar=self.far
            )
    
        # Build camera transform
        forward = np.array(self.camera['Forward'])
        forward = forward / np.linalg.norm(forward)
        up = np.array(self.camera['Up'])
        up = up / np.linalg.norm(up)
        right = np.cross(forward, up)
        right = right / np.linalg.norm(right)
        up = np.cross(right, forward)
    
        cam_transform = np.eye(4)
        cam_transform[:3, 0] = right
        cam_transform[:3, 1] = up
        cam_transform[:3, 2] = -forward
        cam_transform[:3, 3] = self.camera['Eye']
    
        # Create scene
        scene = pyrender.Scene(ambient_light=[1.0, 1.0, 1.0], bg_color=[0, 0, 0, 0])
        scene.add(camera, pose=cam_transform)
    
        # Count objects
        if isinstance(raw_mesh, trimesh.Scene):
            num_objects = len(raw_mesh.geometry)
        else:
            num_objects = 1
    
        colors = generate_colors(num_objects + 10)
    
        print(f"  Found {num_objects} objects")
    
        # Add geometry with unique color per object
        if isinstance(raw_mesh, trimesh.Scene):
            for i, (geom_name, geom) in enumerate(raw_mesh.geometry.items()):
                color = colors[i % len(colors)]
            
                flat_material = pyrender.MetallicRoughnessMaterial(
                    baseColorFactor=[color[0], color[1], color[2], 1.0],
                    metallicFactor=0.0,
                    roughnessFactor=1.0
                )
            
                try:
                    pr_mesh = pyrender.Mesh.from_trimesh(geom, material=flat_material)
                    scene.add(pr_mesh)
                except:
                    pass
        else:
            color = colors[0]
            flat_material = pyrender.MetallicRoughnessMaterial(
                baseColorFactor=[color[0], color[1], color[2], 1.0],
                metallicFactor=0.0,
                roughnessFactor=1.0
            )
            pr_mesh = pyrender.Mesh.from_trimesh(raw_mesh, material=flat_material)
            scene.add(pr_mesh)
    
        # Render
        renderer = pyrender.OffscreenRenderer(width, height)
        color_img, _ = renderer.render(scene)
        renderer.delete()
    
        filepath = Path(output_path) / "object_id.png"
        Image.fromarray(color_img, mode='RGB').save(filepath)
    
        print(f"  Object ID saved to {filepath}")
        return str(filepath)
    
    def update_camera(self, camera_data: dict):
        """Update camera without rebuilding mesh/BVH."""
        self.camera = camera_data

        self.eye = wp.vec3(camera_data['Eye'][0], camera_data['Eye'][1], camera_data['Eye'][2])

        forward = np.array(camera_data['Forward'], dtype=np.float32)
        forward = forward / np.linalg.norm(forward)
        self.forward = wp.vec3(forward[0], forward[1], forward[2])

        up = np.array(camera_data['Up'], dtype=np.float32)
        up = up / np.linalg.norm(up)
        self.up = wp.vec3(up[0], up[1], up[2])

        right = np.cross(forward, up)
        right = right / np.linalg.norm(right)
        self.right = wp.vec3(right[0], right[1], right[2])

        self.fov = float(camera_data.get('FieldOfView', 0.785))
        self.near = float(camera_data.get('NearClip', 0.1))
        self.far = float(camera_data.get('FarClip', 10000))

    def set_near_clip_offset(self, offset_mm: float):
        """
        Set near clip offset to skip through geometry near camera.
        Useful for interior views where camera might be inside/near walls.

        Args:
            offset_mm: Distance in mm to push ray origins forward
        """
        self.near_clip_offset = float(offset_mm)
        print(f"Near clip offset set to {offset_mm}mm")

    def set_section_box(self, section_box: dict):
        """Set section box clipping bounds."""
        if section_box and section_box.get("enabled"):
            self.section_box = {
                "min": np.array(section_box["min"], dtype=np.float32),
                "max": np.array(section_box["max"], dtype=np.float32),
                "enabled": True
            }
            print(f"Section box set: min={self.section_box['min']}, max={self.section_box['max']}")
        else:
            self.section_box = None

    def clear_section_box(self):
        """Clear section box clipping."""
        self.section_box = None
        print("Section box cleared")

    def _ray_box_intersection(self, origins: np.ndarray, directions: np.ndarray,
                                box_min: np.ndarray, box_max: np.ndarray):
        """
        Calculate ray-box intersection distances.
        Returns (t_enter, t_exit) for each ray - the distances along the ray where it enters/exits the box.
        """
        # Avoid division by zero
        inv_dir = np.where(np.abs(directions) > 1e-10, 1.0 / directions, np.sign(directions) * 1e10)

        # Calculate intersection with each slab
        t1 = (box_min - origins) * inv_dir
        t2 = (box_max - origins) * inv_dir

        # Get entry and exit for each axis
        t_min = np.minimum(t1, t2)
        t_max = np.maximum(t1, t2)

        # Entry is the max of all min intersections
        t_enter = np.max(t_min, axis=1)
        # Exit is the min of all max intersections
        t_exit = np.min(t_max, axis=1)

        # Clamp entry to 0 (can't enter behind the ray origin)
        t_enter = np.maximum(t_enter, 0)

        return t_enter, t_exit

    def _clip_depth_to_section_box(self, depths: np.ndarray, directions, origins=None) -> np.ndarray:
        """
        Clip depth values based on section box bounds.

        This implements proper ray-box clipping:
        - If hit is before ray enters box: clip (geometry in front of section)
        - If hit is after ray exits box: clip (geometry behind section)
        - If hit is inside box: keep
        """
        if not self.section_box or not self.section_box.get("enabled"):
            print("  Section box not enabled, skipping clip")
            return depths

        eye = np.array([float(self.eye[0]), float(self.eye[1]), float(self.eye[2])])
        box_min = np.array(self.section_box["min"])
        box_max = np.array(self.section_box["max"])

        print(f"  Section box clipping: min={box_min}, max={box_max}")
        print(f"  Eye position: {eye}")

        # Convert directions to numpy if needed (warp vec3 array)
        if hasattr(directions, 'numpy'):
            dirs_np = directions.numpy()
            if dirs_np.dtype.names is not None:
                dirs_np = np.column_stack([dirs_np['x'], dirs_np['y'], dirs_np['z']])
            elif len(dirs_np.shape) == 1:
                dirs_np = dirs_np.reshape(-1, 3)
        else:
            dirs_np = np.array(directions)
            if len(dirs_np.shape) == 1:
                dirs_np = dirs_np.reshape(-1, 3)

        # Use provided origins or broadcast eye position
        if origins is not None:
            if hasattr(origins, 'numpy'):
                orig_np = origins.numpy()
                if orig_np.dtype.names is not None:
                    orig_np = np.column_stack([orig_np['x'], orig_np['y'], orig_np['z']])
                elif len(orig_np.shape) == 1:
                    orig_np = orig_np.reshape(-1, 3)
            else:
                orig_np = np.array(origins).reshape(-1, 3)
        else:
            orig_np = np.broadcast_to(eye, dirs_np.shape)

        # Calculate ray-box intersections
        t_enter, t_exit = self._ray_box_intersection(orig_np, dirs_np, box_min, box_max)

        # Valid box intersection: ray actually passes through box
        valid_box = t_exit > t_enter

        # Hit is valid if:
        # 1. Ray intersects the box (valid_box)
        # 2. Hit distance is after entering the box (depths >= t_enter)
        # 3. Hit distance is before exiting the box (depths <= t_exit)
        # 4. Hit is not at far clip (actual geometry hit)
        has_hit = depths < self.far * 0.99
        inside_box = (depths >= t_enter) & (depths <= t_exit)

        keep = valid_box & has_hit & inside_box

        # Count what we're clipping
        clipped_front = np.sum(has_hit & valid_box & (depths < t_enter))
        clipped_back = np.sum(has_hit & valid_box & (depths > t_exit))
        clipped_outside = np.sum(has_hit & ~valid_box)

        print(f"  Clipping: {clipped_front} in front, {clipped_back} behind, {clipped_outside} outside ray path")
        print(f"  Keeping {np.sum(keep)} hits inside section box")

        # Apply clipping
        clipped_depths = depths.copy()
        clipped_depths[~keep] = self.far

        return clipped_depths

    def extract_base(self, output_path: str, resolution: tuple):
        """Render a basic shaded view using pyrender."""
        print("=== EXTRACT BASE RENDER ===")
        import pyrender
    
        width, height = resolution
    
        # Create scene with white background
        scene = pyrender.Scene(bg_color=[1.0, 1.0, 1.0, 1.0], ambient_light=[0.3, 0.3, 0.3])
    
        # Add mesh
        mesh = pyrender.Mesh.from_trimesh(self.trimesh_mesh)
        scene.add(mesh)
    
        # Get camera vectors as numpy
        eye = np.array([float(self.eye[0]), float(self.eye[1]), float(self.eye[2])])
        forward = np.array([float(self.forward[0]), float(self.forward[1]), float(self.forward[2])])
        up = np.array([float(self.up[0]), float(self.up[1]), float(self.up[2])])
    
        # Normalize
        forward = forward / np.linalg.norm(forward)
        up = up / np.linalg.norm(up)
        right = np.cross(forward, up)
        right = right / np.linalg.norm(right)
        # Recompute up to ensure orthogonal
        up = np.cross(right, forward)
        up = up / np.linalg.norm(up)
    
        # Build camera pose matrix for pyrender
        # Pyrender camera looks down -Z axis, Y is up
        cam_pose = np.eye(4)
        cam_pose[:3, 0] = right      # X axis = right
        cam_pose[:3, 1] = up         # Y axis = up  
        cam_pose[:3, 2] = -forward   # Z axis = -forward (camera looks down -Z)
        cam_pose[:3, 3] = eye        # Position
    
        # Camera
        camera = pyrender.PerspectiveCamera(yfov=self.fov, aspectRatio=width/height)
        scene.add(camera, pose=cam_pose)
    
        # Key light (from camera direction, slightly above)
        light_pose = cam_pose.copy()
        key_light = pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=3.0)
        scene.add(key_light, pose=light_pose)
    
        # Fill light (from opposite side)
        fill_pose = np.eye(4)
        fill_pose[:3, 2] = forward  # Opposite direction
        fill_light = pyrender.DirectionalLight(color=[0.7, 0.7, 0.8], intensity=1.5)
        scene.add(fill_light, pose=fill_pose)
    
        # Render
        try:
            renderer = pyrender.OffscreenRenderer(width, height)
            color, _ = renderer.render(scene)
            renderer.delete()
        except Exception as e:
            print(f"  Pyrender error: {e}")
            # Fallback: create gray image
            color = np.full((height, width, 3), 200, dtype=np.uint8)
    
        # Save
        filepath = Path(output_path) / "base.png"
        Image.fromarray(color).save(filepath)
        print(f"  Base render saved to {filepath}")
    
        return str(filepath)

# Mesh raycast kernel
@wp.kernel
def mesh_raycast_kernel(
    mesh_id: wp.uint64,
    origins: wp.array(dtype=wp.vec3),
    directions: wp.array(dtype=wp.vec3),
    max_dist: float,
    hit_dist: wp.array(dtype=float)
):
    tid = wp.tid()
    
    origin = origins[tid]
    direction = directions[tid]
    
    t = float(0.0)
    u = float(0.0)
    v = float(0.0)
    sign = float(0.0)
    n = wp.vec3()
    f = int(0)
    
    hit = wp.mesh_query_ray(mesh_id, origin, direction, max_dist, t, u, v, sign, n, f)
    
    if hit:
        hit_dist[tid] = t
    else:
        hit_dist[tid] = max_dist


def extract_channels_warp(mesh_path: str, camera: dict, bbox: list,
                          output_dir: str, channels: list = None,
                          resolution: tuple = (960, 540)) -> dict:
    extractor = WarpChannelExtractor(mesh_path, camera, np.array(bbox))
    return extractor.extract_all(output_dir, resolution, channels)