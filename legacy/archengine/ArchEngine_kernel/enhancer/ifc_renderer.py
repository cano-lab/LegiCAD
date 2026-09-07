# ifc_renderer.py
# Renders IFC elements with unique ID colors for per-element masking

import numpy as np
from PIL import Image
from pathlib import Path
import hashlib

print("=== IFC RENDERER MODULE LOADING ===")

try:
    import ifcopenshell
    import ifcopenshell.geom
    IFC_GEOM_AVAILABLE = True
    print("ifcopenshell.geom available")
except ImportError:
    IFC_GEOM_AVAILABLE = False
    print("WARNING: ifcopenshell.geom not available")

try:
    import trimesh
    TRIMESH_AVAILABLE = True
except ImportError:
    TRIMESH_AVAILABLE = False


def global_id_to_color(global_id: str) -> tuple:
    """Convert IFC GlobalId to unique RGB color."""
    hash_bytes = hashlib.md5(global_id.encode()).digest()
    # Avoid black (0,0,0) as it's our background
    r = max(1, hash_bytes[0])
    g = max(1, hash_bytes[1])
    b = max(1, hash_bytes[2])
    return (r, g, b)


def color_to_global_id_lookup(colors_dict: dict) -> dict:
    """Create reverse lookup from RGB tuple to GlobalId."""
    return {v: k for k, v in colors_dict.items()}


class IFCElementRenderer:
    """
    Renders IFC elements with unique colors for element ID pass.
    Each element gets a color based on its GlobalId hash.
    """

    def __init__(self, ifc_path: str):
        self.ifc_path = ifc_path
        self.ifc = ifcopenshell.open(ifc_path)
        self.elements = {}  # GlobalId -> element info
        self.colors = {}    # GlobalId -> (r, g, b)
        self.color_lookup = {}  # (r, g, b) -> GlobalId
        self.combined_mesh = None
        self.vertex_colors = None

        self._build_element_colors()

    def _build_element_colors(self):
        """Build color mapping for all elements."""
        # Get all building elements
        for element in self.ifc.by_type("IfcBuildingElement"):
            global_id = element.GlobalId
            self.elements[global_id] = {
                "id": element.id(),
                "type": element.is_a(),
                "name": element.Name or f"Unnamed {element.is_a()}"
            }
            color = global_id_to_color(global_id)
            self.colors[global_id] = color
            self.color_lookup[color] = global_id

        # Also get spaces, furniture, etc.
        for type_name in ["IfcSpace", "IfcFurnishingElement", "IfcCovering"]:
            for element in self.ifc.by_type(type_name):
                global_id = element.GlobalId
                self.elements[global_id] = {
                    "id": element.id(),
                    "type": element.is_a(),
                    "name": element.Name or f"Unnamed {element.is_a()}"
                }
                color = global_id_to_color(global_id)
                self.colors[global_id] = color
                self.color_lookup[color] = global_id

        print(f"Built colors for {len(self.elements)} IFC elements")

    def extract_geometry(self):
        """Extract triangulated geometry from IFC with per-element colors."""
        if not IFC_GEOM_AVAILABLE:
            raise RuntimeError("ifcopenshell.geom not available")

        settings = ifcopenshell.geom.settings()
        settings.set(settings.USE_WORLD_COORDS, True)

        all_vertices = []
        all_faces = []
        all_colors = []
        vertex_offset = 0

        print("Extracting IFC geometry...")

        for global_id, info in self.elements.items():
            try:
                element = self.ifc.by_guid(global_id)
                shape = ifcopenshell.geom.create_shape(settings, element)

                # Get mesh data
                verts = shape.geometry.verts
                faces = shape.geometry.faces

                # Convert flat lists to arrays
                vertices = np.array(verts).reshape(-1, 3)
                triangles = np.array(faces).reshape(-1, 3)

                if len(vertices) == 0:
                    continue

                # Add vertices
                all_vertices.append(vertices)

                # Add faces with offset
                all_faces.append(triangles + vertex_offset)
                vertex_offset += len(vertices)

                # Add colors (one per vertex)
                color = self.colors[global_id]
                colors = np.tile(color, (len(vertices), 1))
                all_colors.append(colors)

            except Exception as e:
                # Some elements may not have geometry
                continue

        if not all_vertices:
            raise RuntimeError("No geometry extracted from IFC")

        # Combine all
        combined_verts = np.vstack(all_vertices)
        combined_faces = np.vstack(all_faces)
        combined_colors = np.vstack(all_colors)

        print(f"Extracted {len(combined_verts)} vertices, {len(combined_faces)} triangles")

        # Create trimesh with vertex colors
        self.combined_mesh = trimesh.Trimesh(
            vertices=combined_verts,
            faces=combined_faces,
            vertex_colors=combined_colors.astype(np.uint8)
        )
        self.vertex_colors = combined_colors

        return self.combined_mesh

    def render_element_ids(self, camera: dict, resolution: tuple = (960, 540), distance_scale: float = 1.0) -> Image.Image:
        """
        Render element ID pass - each element has unique color.

        Args:
            camera: Camera dict with Eye, Forward, Up, etc.
            resolution: Output resolution (width, height)
            distance_scale: Camera distance multiplier (0.25 = 4x closer, 1.0 = original)

        Returns:
            PIL Image with element ID colors
        """
        if self.combined_mesh is None:
            self.extract_geometry()

        # Use pyrender for rendering with vertex colors
        try:
            import pyrender

            # Create scene
            scene = pyrender.Scene(bg_color=[0, 0, 0, 0])

            # Add mesh with vertex colors
            mesh = pyrender.Mesh.from_trimesh(self.combined_mesh)
            scene.add(mesh)

            # Set up camera
            eye = np.array(camera["Eye"])
            forward = np.array(camera["Forward"])
            forward = forward / np.linalg.norm(forward)
            up = np.array(camera.get("Up", [0, 0, 1]))
            up = up / np.linalg.norm(up)

            # Apply distance scale - move camera closer/farther from model center
            if distance_scale != 1.0:
                center = self.combined_mesh.centroid
                direction = eye - center
                eye = center + direction * distance_scale

            # Camera matrix (look at)
            z = -forward  # Camera looks down -Z
            x = np.cross(up, z)
            if np.linalg.norm(x) < 0.001:
                up = np.array([0, 1, 0])
                x = np.cross(up, z)
            x = x / np.linalg.norm(x)
            y = np.cross(z, x)

            pose = np.eye(4)
            pose[:3, 0] = x
            pose[:3, 1] = y
            pose[:3, 2] = z
            pose[:3, 3] = eye

            # Create camera
            fov = camera.get("FieldOfView", 0.785)  # radians
            aspect = resolution[0] / resolution[1]

            cam = pyrender.PerspectiveCamera(yfov=fov, aspectRatio=aspect)
            scene.add(cam, pose=pose)

            # Render
            r = pyrender.OffscreenRenderer(resolution[0], resolution[1])
            color, _ = r.render(scene, flags=pyrender.RenderFlags.FLAT)
            r.delete()

            return Image.fromarray(color)

        except ImportError:
            print("pyrender not available, using fallback renderer")
            return self._render_fallback(camera, resolution)

    def _render_fallback(self, camera: dict, resolution: tuple) -> Image.Image:
        """Simple software rasterizer fallback."""
        # This is a simplified fallback - in production you'd want proper rasterization
        # For now, create a placeholder that shows we need pyrender
        img = Image.new('RGB', resolution, (0, 0, 0))
        return img

    def render_base(self, camera: dict, resolution: tuple = (960, 540)) -> Image.Image:
        """
        Render a shaded base image from IFC geometry for AI enhancement.

        Args:
            camera: Camera dict with Eye, Forward, Up, etc.
            resolution: Output resolution (width, height)

        Returns:
            PIL Image with shaded geometry (suitable for AI enhancement)
        """
        if self.combined_mesh is None:
            self.extract_geometry()

        try:
            import pyrender

            # Create a clean mesh for proper shading
            clean_mesh = trimesh.Trimesh(
                vertices=self.combined_mesh.vertices,
                faces=self.combined_mesh.faces
            )

            # Create scene with light background (like sky)
            scene = pyrender.Scene(bg_color=[0.7, 0.85, 1.0, 1.0], ambient_light=[0.4, 0.4, 0.45])

            # Create a proper material for architectural look
            material = pyrender.MetallicRoughnessMaterial(
                baseColorFactor=[0.85, 0.85, 0.82, 1.0],  # Warm grey/white
                metallicFactor=0.0,
                roughnessFactor=0.7
            )

            # Add mesh with material
            mesh = pyrender.Mesh.from_trimesh(clean_mesh, material=material)
            scene.add(mesh)

            # Set up camera
            eye = np.array(camera["Eye"])
            forward = np.array(camera["Forward"])
            forward = forward / np.linalg.norm(forward)
            up = np.array(camera.get("Up", [0, 0, 1]))
            up = up / np.linalg.norm(up)

            # Camera matrix (look at)
            z = -forward
            x = np.cross(up, z)
            if np.linalg.norm(x) < 0.001:
                # up and forward are parallel, use different up
                up = np.array([0, 1, 0])
                x = np.cross(up, z)
            x = x / np.linalg.norm(x)
            y = np.cross(z, x)

            pose = np.eye(4)
            pose[:3, 0] = x
            pose[:3, 1] = y
            pose[:3, 2] = z
            pose[:3, 3] = eye

            # Create camera
            fov = camera.get("FieldOfView", 0.785)
            aspect = resolution[0] / resolution[1]
            cam = pyrender.PerspectiveCamera(yfov=fov, aspectRatio=aspect)
            scene.add(cam, pose=pose)

            # Add sun light (key light)
            sun_direction = np.array([0.5, 0.7, 1.0])
            sun_direction = sun_direction / np.linalg.norm(sun_direction)
            light_pose = np.eye(4)
            light_pose[:3, 2] = -sun_direction
            light = pyrender.DirectionalLight(color=[1.0, 0.98, 0.92], intensity=4.0)
            scene.add(light, pose=light_pose)

            # Add fill light
            fill_direction = np.array([-0.5, -0.3, 0.5])
            fill_direction = fill_direction / np.linalg.norm(fill_direction)
            fill_pose = np.eye(4)
            fill_pose[:3, 2] = -fill_direction
            fill_light = pyrender.DirectionalLight(color=[0.85, 0.9, 1.0], intensity=1.5)
            scene.add(fill_light, pose=fill_pose)

            # Add rim/back light for depth
            rim_direction = np.array([0, -1, 0.3])
            rim_direction = rim_direction / np.linalg.norm(rim_direction)
            rim_pose = np.eye(4)
            rim_pose[:3, 2] = -rim_direction
            rim_light = pyrender.DirectionalLight(color=[1.0, 1.0, 0.95], intensity=1.0)
            scene.add(rim_light, pose=rim_pose)

            # Render with full shading
            r = pyrender.OffscreenRenderer(resolution[0], resolution[1])
            color, depth = r.render(scene)
            r.delete()

            # Normalize depth
            depth_valid = depth[depth > 0]
            if len(depth_valid) > 0:
                depth_normalized = (depth - depth_valid.min()) / (depth_valid.max() - depth_valid.min() + 1e-6)
                depth_normalized = np.clip(depth_normalized, 0, 1)
                depth_img = Image.fromarray((depth_normalized * 255).astype(np.uint8))
            else:
                depth_img = Image.fromarray((depth * 255).astype(np.uint8))

            return Image.fromarray(color), depth_img

        except Exception as e:
            print(f"Base render failed: {e}")
            import traceback
            traceback.print_exc()
            return Image.new('RGB', resolution, (128, 128, 128)), None

    def render_channels(self, camera: dict, resolution: tuple = (960, 540), distance_scale: float = 1.0) -> dict:
        """
        Render multiple channels from IFC geometry for AI enhancement.

        Returns dict with: base, depth, normals, edges
        """
        if self.combined_mesh is None:
            self.extract_geometry()

        try:
            import pyrender
            import cv2

            clean_mesh = trimesh.Trimesh(
                vertices=self.combined_mesh.vertices,
                faces=self.combined_mesh.faces
            )

            # Set up camera with distance scaling
            eye = np.array(camera["Eye"])
            forward = np.array(camera["Forward"])
            forward = forward / np.linalg.norm(forward)
            up = np.array(camera.get("Up", [0, 0, 1]))
            up = up / np.linalg.norm(up)

            # Apply distance scale - move camera closer or farther
            if distance_scale != 1.0:
                center = clean_mesh.centroid
                direction = eye - center
                eye = center + direction * distance_scale

            # Camera matrix
            z = -forward
            x = np.cross(up, z)
            if np.linalg.norm(x) < 0.001:
                up = np.array([0, 1, 0])
                x = np.cross(up, z)
            x = x / np.linalg.norm(x)
            y = np.cross(z, x)

            pose = np.eye(4)
            pose[:3, 0] = x
            pose[:3, 1] = y
            pose[:3, 2] = z
            pose[:3, 3] = eye

            fov = camera.get("FieldOfView", 0.785)
            aspect = resolution[0] / resolution[1]

            results = {}

            # === RENDER BASE (shaded) ===
            scene = pyrender.Scene(bg_color=[0.7, 0.85, 1.0, 1.0], ambient_light=[0.4, 0.4, 0.45])
            material = pyrender.MetallicRoughnessMaterial(
                baseColorFactor=[0.85, 0.85, 0.82, 1.0],
                metallicFactor=0.0,
                roughnessFactor=0.7
            )
            mesh = pyrender.Mesh.from_trimesh(clean_mesh, material=material)
            scene.add(mesh)
            cam = pyrender.PerspectiveCamera(yfov=fov, aspectRatio=aspect)
            scene.add(cam, pose=pose)

            # Lights
            for direction, color, intensity in [
                ([0.5, 0.7, 1.0], [1.0, 0.98, 0.92], 4.0),
                ([-0.5, -0.3, 0.5], [0.85, 0.9, 1.0], 1.5),
                ([0, -1, 0.3], [1.0, 1.0, 0.95], 1.0)
            ]:
                d = np.array(direction)
                d = d / np.linalg.norm(d)
                lp = np.eye(4)
                lp[:3, 2] = -d
                scene.add(pyrender.DirectionalLight(color=color, intensity=intensity), pose=lp)

            r = pyrender.OffscreenRenderer(resolution[0], resolution[1])
            color, depth = r.render(scene)
            r.delete()

            results['base'] = Image.fromarray(color)

            # === DEPTH ===
            depth_valid = depth[depth > 0]
            if len(depth_valid) > 0:
                depth_norm = (depth - depth_valid.min()) / (depth_valid.max() - depth_valid.min() + 1e-6)
                depth_norm = np.clip(1.0 - depth_norm, 0, 1)  # Invert so closer = brighter
                depth_norm[depth == 0] = 0  # Background stays black
            else:
                depth_norm = depth
            results['depth'] = Image.fromarray((depth_norm * 255).astype(np.uint8))

            # === NORMALS ===
            scene_normals = pyrender.Scene(bg_color=[0.5, 0.5, 1.0, 1.0])
            # Use vertex normals as colors
            if clean_mesh.vertex_normals is not None:
                normals = (clean_mesh.vertex_normals + 1) / 2  # Map -1,1 to 0,1
                normal_colors = (normals * 255).astype(np.uint8)
                normal_colors = np.hstack([normal_colors, np.full((len(normals), 1), 255, dtype=np.uint8)])
                normal_mesh = trimesh.Trimesh(vertices=clean_mesh.vertices, faces=clean_mesh.faces)
                normal_mesh.visual.vertex_colors = normal_colors
                mesh_n = pyrender.Mesh.from_trimesh(normal_mesh)
                scene_normals.add(mesh_n)
                scene_normals.add(cam, pose=pose)
                r = pyrender.OffscreenRenderer(resolution[0], resolution[1])
                normals_img, _ = r.render(scene_normals, flags=pyrender.RenderFlags.FLAT)
                r.delete()
                results['normals'] = Image.fromarray(normals_img)

            # === EDGES ===
            base_gray = np.array(results['base'].convert('L'))
            edges = cv2.Canny(base_gray, 50, 150)
            results['edges'] = Image.fromarray(255 - edges)  # Invert so edges are dark

            return results

        except Exception as e:
            print(f"Channel render failed: {e}")
            import traceback
            traceback.print_exc()
            return {'base': Image.new('RGB', resolution, (128, 128, 128))}

    def get_elements_at_pixel(self, element_id_image: Image.Image, x: int, y: int) -> str:
        """Get GlobalId of element at pixel position."""
        pixel = element_id_image.getpixel((x, y))
        if pixel[:3] == (0, 0, 0):
            return None  # Background
        return self.color_lookup.get(pixel[:3])

    def create_mask_from_selection(
        self,
        element_id_image: Image.Image,
        selected_global_ids: list,
        invert: bool = False,
        feather: int = 0
    ) -> Image.Image:
        """
        Create mask from selected elements.

        Args:
            element_id_image: Rendered element ID pass
            selected_global_ids: List of GlobalIds to select
            invert: If True, mask everything EXCEPT selected
            feather: Blur radius for soft edges

        Returns:
            Grayscale mask (white = selected)
        """
        from PIL import ImageFilter

        # Convert to numpy
        id_np = np.array(element_id_image)

        # Get colors of selected elements
        selected_colors = set()
        for gid in selected_global_ids:
            if gid in self.colors:
                selected_colors.add(self.colors[gid])

        # Create mask
        mask = np.zeros((id_np.shape[0], id_np.shape[1]), dtype=np.uint8)

        for color in selected_colors:
            # Match pixels with this color
            match = (
                (id_np[:, :, 0] == color[0]) &
                (id_np[:, :, 1] == color[1]) &
                (id_np[:, :, 2] == color[2])
            )
            mask[match] = 255

        if invert:
            mask = 255 - mask

        mask_img = Image.fromarray(mask, mode='L')

        if feather > 0:
            mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=feather))

        return mask_img

    def get_elements_by_type(self, element_type: str) -> list:
        """Get GlobalIds of all elements of a specific type."""
        result = []
        for global_id, info in self.elements.items():
            if info["type"] == element_type:
                result.append(global_id)
        return result


# Singleton instance cache
_renderer_cache = {}

def get_ifc_renderer(ifc_path: str) -> IFCElementRenderer:
    """Get or create IFC renderer (cached by path)."""
    if ifc_path not in _renderer_cache:
        _renderer_cache[ifc_path] = IFCElementRenderer(ifc_path)
    return _renderer_cache[ifc_path]


def clear_renderer_cache():
    """Clear the renderer cache."""
    global _renderer_cache
    _renderer_cache = {}


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python ifc_renderer.py <ifc_path>")
        sys.exit(1)

    ifc_path = sys.argv[1]

    print(f"\nLoading: {ifc_path}")
    renderer = IFCElementRenderer(ifc_path)

    print(f"\nElements: {len(renderer.elements)}")
    for gid, info in list(renderer.elements.items())[:5]:
        print(f"  {info['type']}: {info['name']} -> {renderer.colors[gid]}")

    print("\nExtracting geometry...")
    try:
        mesh = renderer.extract_geometry()
        print(f"Mesh: {len(mesh.vertices)} verts, {len(mesh.faces)} faces")
    except Exception as e:
        print(f"Geometry extraction failed: {e}")
