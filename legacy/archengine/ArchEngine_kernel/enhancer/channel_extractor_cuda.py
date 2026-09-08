import torch
import numpy as np
from PIL import Image
from pathlib import Path
import math

print("=== CUDA CHANNEL EXTRACTOR LOADED ===")

DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"Using device: {DEVICE}")


class CudaMesh:
    def __init__(self, vertices: np.ndarray, faces: np.ndarray):
        self.vertices = torch.tensor(vertices, dtype=torch.float32, device=DEVICE)
        self.faces = torch.tensor(faces, dtype=torch.int64, device=DEVICE)
        
        v0 = self.vertices[self.faces[:, 0]]
        v1 = self.vertices[self.faces[:, 1]]
        v2 = self.vertices[self.faces[:, 2]]
        
        self.v0 = v0
        self.edge1 = v1 - v0
        self.edge2 = v2 - v0
        self.face_normals = torch.cross(self.edge1, self.edge2, dim=1)
        self.face_normals = self.face_normals / (torch.norm(self.face_normals, dim=1, keepdim=True) + 1e-8)
        
        self.bbox_min = self.vertices.min(dim=0).values
        self.bbox_max = self.vertices.max(dim=0).values
        self.centroid = self.vertices.mean(dim=0)
        
        print(f"  Loaded {len(self.faces)} triangles to GPU")
    
    @classmethod
    def from_trimesh(cls, mesh):
        import trimesh
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.to_geometry()
        return cls(mesh.vertices, mesh.faces)
    
    def ray_intersect_batch(self, origins: torch.Tensor, directions: torch.Tensor, 
                            max_dist: float = 1e10) -> tuple:
        N = origins.shape[0]
        M = self.faces.shape[0]
    
        # Smaller chunks for 8GB VRAM
        ray_chunk_size = 5000
        tri_chunk_size = 20000
    
        hit_mask = torch.zeros(N, dtype=torch.bool, device=DEVICE)
        distances = torch.full((N,), float('inf'), dtype=torch.float32, device=DEVICE)
    
        for ray_start in range(0, N, ray_chunk_size):
            ray_end = min(ray_start + ray_chunk_size, N)
        
            orig_chunk = origins[ray_start:ray_end]
            dir_chunk = directions[ray_start:ray_end]
            C = orig_chunk.shape[0]
        
            chunk_min_t = torch.full((C,), float('inf'), dtype=torch.float32, device=DEVICE)
        
            # Process triangles in chunks too
            for tri_start in range(0, M, tri_chunk_size):
                tri_end = min(tri_start + tri_chunk_size, M)
                T = tri_end - tri_start
            
                v0_chunk = self.v0[tri_start:tri_end]
                e1_chunk = self.edge1[tri_start:tri_end]
                e2_chunk = self.edge2[tri_start:tri_end]
            
                # Expand for broadcasting: (C, T, 3)
                orig_exp = orig_chunk.unsqueeze(1).expand(C, T, 3)
                dir_exp = dir_chunk.unsqueeze(1).expand(C, T, 3)
            
                v0_exp = v0_chunk.unsqueeze(0).expand(C, T, 3)
                e1_exp = e1_chunk.unsqueeze(0).expand(C, T, 3)
                e2_exp = e2_chunk.unsqueeze(0).expand(C, T, 3)
            
                # Möller–Trumbore
                h = torch.linalg.cross(dir_exp, e2_exp)
                a = torch.sum(e1_exp * h, dim=2)
            
                valid = torch.abs(a) > 1e-8
            
                f = torch.where(valid, 1.0 / a, torch.zeros_like(a))
                s = orig_exp - v0_exp
                u = f * torch.sum(s * h, dim=2)
            
                valid = valid & (u >= 0) & (u <= 1)
            
                q = torch.linalg.cross(s, e1_exp)
                v = f * torch.sum(dir_exp * q, dim=2)
            
                valid = valid & (v >= 0) & (u + v <= 1)
            
                t = f * torch.sum(e2_exp * q, dim=2)
                valid = valid & (t > 1e-6) & (t < max_dist)
            
                t_masked = torch.where(valid, t, torch.full_like(t, float('inf')))
                min_t_chunk, _ = t_masked.min(dim=1)
            
                chunk_min_t = torch.minimum(chunk_min_t, min_t_chunk)
            
                # Clear intermediate tensors
                del orig_exp, dir_exp, v0_exp, e1_exp, e2_exp, h, a, f, s, u, q, v, t, valid, t_masked, min_t_chunk
                torch.cuda.empty_cache()
        
            hit_mask[ray_start:ray_end] = chunk_min_t < float('inf')
            distances[ray_start:ray_end] = chunk_min_t
    
        return hit_mask, distances


class CudaChannelExtractor:
    def __init__(self, mesh_path: str, camera_data: dict, bbox: np.ndarray):
        import trimesh
        
        print("Loading mesh to GPU...")
        raw_mesh = trimesh.load(mesh_path)
        self.mesh = CudaMesh.from_trimesh(raw_mesh)
        
        self.camera = camera_data
        self.bbox = torch.tensor(bbox, dtype=torch.float32, device=DEVICE)
        
        self.eye = torch.tensor(camera_data['Eye'], dtype=torch.float32, device=DEVICE)
        self.forward = torch.tensor(camera_data['Forward'], dtype=torch.float32, device=DEVICE)
        self.forward = self.forward / torch.norm(self.forward)
        self.up = torch.tensor(camera_data['Up'], dtype=torch.float32, device=DEVICE)
        self.up = self.up / torch.norm(self.up)
        self.right = torch.cross(self.forward, self.up)
        self.right = self.right / torch.norm(self.right)
        
        self.fov = camera_data.get('FieldOfView', 0.785)
        self.near = camera_data.get('NearClip', 0.1)
        self.far = camera_data.get('FarClip', 10000)
    
    def _generate_rays(self, width: int, height: int):
        aspect = width / height
        
        y_coords = torch.arange(height, device=DEVICE, dtype=torch.float32)
        x_coords = torch.arange(width, device=DEVICE, dtype=torch.float32)
        yy, xx = torch.meshgrid(y_coords, x_coords, indexing='ij')
        
        ndc_x = (2 * xx / width - 1) * math.tan(self.fov / 2) * aspect
        ndc_y = (1 - 2 * yy / height) * math.tan(self.fov / 2)
        
        directions = (self.forward.unsqueeze(0).unsqueeze(0) + 
                     self.right.unsqueeze(0).unsqueeze(0) * ndc_x.unsqueeze(-1) +
                     self.up.unsqueeze(0).unsqueeze(0) * ndc_y.unsqueeze(-1))
        directions = directions / torch.norm(directions, dim=-1, keepdim=True)
        
        directions = directions.reshape(-1, 3)
        origins = self.eye.unsqueeze(0).expand(height * width, 3)
        
        return origins, directions
    
    def extract_depth(self, output_path: str, resolution: tuple):
        print("=== CUDA EXTRACT DEPTH ===")
        
        width, height = resolution
        
        origins, directions = self._generate_rays(width, height)
        
        print(f"  Casting {width * height} rays...")
        hit_mask, distances = self.mesh.ray_intersect_batch(origins, directions, self.far)
        
        depth = distances.reshape(height, width).cpu().numpy()
        
        valid = depth < self.far
        if valid.any():
            min_d, max_d = depth[valid].min(), depth[valid].max()
            depth_norm = (depth - min_d) / (max_d - min_d + 1e-6)
            depth_norm = 1.0 - depth_norm
            depth_norm[~valid] = 0
        else:
            depth_norm = np.zeros_like(depth)
        
        depth_img = (depth_norm * 255).astype(np.uint8)
        
        filepath = Path(output_path) / "depth.png"
        Image.fromarray(depth_img, mode='L').save(filepath)
        
        print(f"  Depth saved to {filepath}")
        return str(filepath), depth
    
    def extract_shadow(self, output_path: str, resolution: tuple,
                       depth_buffer: np.ndarray = None,
                       light_direction: tuple = (0.5, 0.8, 1.0)):
        print("=== CUDA EXTRACT SHADOW ===")
        
        width, height = resolution
        
        if depth_buffer is None:
            _, depth_buffer = self.extract_depth(output_path, resolution)
        
        depth_t = torch.tensor(depth_buffer, dtype=torch.float32, device=DEVICE)
        
        light_dir = torch.tensor(light_direction, dtype=torch.float32, device=DEVICE)
        light_dir = light_dir / torch.norm(light_dir)
        
        origins, directions = self._generate_rays(width, height)
        
        world_pos = self.eye + directions * depth_t.reshape(-1, 1)
        
        shadow_origins = world_pos + light_dir * 1.0
        shadow_dirs = light_dir.unsqueeze(0).expand(height * width, 3)
        
        valid_mask = depth_t.reshape(-1) < self.far * 0.99
        
        print(f"  Casting {valid_mask.sum().item()} shadow rays...")
        
        shadow_buffer = torch.ones(height * width, dtype=torch.float32, device=DEVICE)
        
        if valid_mask.any():
            valid_origins = shadow_origins[valid_mask]
            valid_dirs = shadow_dirs[valid_mask]
            
            hit_mask, _ = self.mesh.ray_intersect_batch(valid_origins, valid_dirs)
            
            shadow_vals = torch.where(hit_mask, 
                                      torch.tensor(0.3, device=DEVICE),
                                      torch.tensor(1.0, device=DEVICE))
            shadow_buffer[valid_mask] = shadow_vals
        
        shadow = shadow_buffer.reshape(height, width).cpu().numpy()
        
        from scipy.ndimage import gaussian_filter
        shadow = gaussian_filter(shadow, sigma=2.0)
        
        shadow_img = (shadow * 255).astype(np.uint8)
        
        filepath = Path(output_path) / "shadow.png"
        Image.fromarray(shadow_img, mode='L').save(filepath)
        
        print(f"  Shadow saved to {filepath}")
        return str(filepath)
    
    def extract_ao(self, output_path: str, resolution: tuple,
                   depth_buffer: np.ndarray = None,
                   num_samples: int = 16, ao_radius: float = 100.0):
        print("=== CUDA EXTRACT AO ===")
        
        width, height = resolution
        
        if depth_buffer is None:
            _, depth_buffer = self.extract_depth(output_path, resolution)
        
        depth_t = torch.tensor(depth_buffer, dtype=torch.float32, device=DEVICE)
        
        origins, directions = self._generate_rays(width, height)
        world_pos = self.eye + directions * depth_t.reshape(-1, 1)
        
        depth_2d = depth_t.reshape(height, width)
        
        pad_depth = torch.nn.functional.pad(depth_2d.unsqueeze(0).unsqueeze(0), 
                                            (1, 1, 1, 1), mode='replicate')[0, 0]
        dz_dx = (pad_depth[1:-1, 2:] - pad_depth[1:-1, :-2]) / 2
        dz_dy = (pad_depth[2:, 1:-1] - pad_depth[:-2, 1:-1]) / 2
        
        normals = torch.stack([-dz_dx, -dz_dy, torch.ones_like(dz_dx)], dim=-1)
        normals = normals / (torch.norm(normals, dim=-1, keepdim=True) + 1e-8)
        normals = normals.reshape(-1, 3)
        
        torch.manual_seed(42)
        theta = torch.rand(num_samples, device=DEVICE) * 2 * math.pi
        phi = torch.rand(num_samples, device=DEVICE) * math.pi / 2
        
        sample_dirs = torch.stack([
            torch.sin(phi) * torch.cos(theta),
            torch.sin(phi) * torch.sin(theta),
            torch.cos(phi)
        ], dim=-1)
        
        valid_mask = depth_t.reshape(-1) < self.far * 0.99
        valid_indices = torch.where(valid_mask)[0]
        
        print(f"  Computing AO for {len(valid_indices)} points with {num_samples} samples each...")
        
        ao_buffer = torch.ones(height * width, dtype=torch.float32, device=DEVICE)
        
        batch_size = 5000
        for batch_start in range(0, len(valid_indices), batch_size):
            batch_end = min(batch_start + batch_size, len(valid_indices))
            batch_idx = valid_indices[batch_start:batch_end]
            B = len(batch_idx)
            
            if batch_start % 10000 == 0:
                print(f"    Processing {batch_start}/{len(valid_indices)}...")
            
            batch_pos = world_pos[batch_idx]
            batch_normals = normals[batch_idx]
            
            ao_origins = batch_pos.unsqueeze(1).expand(B, num_samples, 3).reshape(-1, 3)
            ao_origins = ao_origins + batch_normals.unsqueeze(1).expand(B, num_samples, 3).reshape(-1, 3) * 0.5
            
            ao_dirs = sample_dirs.unsqueeze(0).expand(B, num_samples, 3).reshape(-1, 3)
            
            hits, dists = self.mesh.ray_intersect_batch(ao_origins, ao_dirs, ao_radius)
            
            hits = hits.reshape(B, num_samples)
            occluded = hits.sum(dim=1).float() / num_samples
            
            ao_buffer[batch_idx] = 1.0 - occluded * 0.7
        
        ao = ao_buffer.reshape(height, width).cpu().numpy()
        
        from scipy.ndimage import gaussian_filter
        ao = gaussian_filter(ao, sigma=2.0)
        
        ao[depth_buffer >= self.far * 0.99] = 1.0
        
        ao_img = (ao * 255).astype(np.uint8)
        
        filepath = Path(output_path) / "ao.png"
        Image.fromarray(ao_img, mode='L').save(filepath)
        
        print(f"  AO saved to {filepath}")
        return str(filepath)
    
    def extract_all(self, output_path: str, resolution: tuple, channels: list = None):
        if channels is None:
            channels = ["depth", "shadow", "ao"]
        
        Path(output_path).mkdir(parents=True, exist_ok=True)
        
        results = {}
        depth_buffer = None
        
        for channel in channels:
            if channel == "depth":
                results["depth"], depth_buffer = self.extract_depth(output_path, resolution)
            elif channel == "shadow":
                results["shadow"] = self.extract_shadow(output_path, resolution, depth_buffer)
            elif channel == "ao":
                results["ao"] = self.extract_ao(output_path, resolution, depth_buffer)
        
        return results


def extract_channels_cuda(mesh_path: str, camera: dict, bbox: list,
                          output_dir: str, channels: list = None,
                          resolution: tuple = (960, 540)) -> dict:
    extractor = CudaChannelExtractor(mesh_path, camera, np.array(bbox))
    return extractor.extract_all(output_dir, resolution, channels)