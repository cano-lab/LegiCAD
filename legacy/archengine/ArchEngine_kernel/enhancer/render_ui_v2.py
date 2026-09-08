# render_ui_v2.py
import gradio as gr
import numpy as np
from PIL import Image
from pathlib import Path
import tempfile
import time
import trimesh

print("Loading Warp...")
from channel_extractor_warp import WarpChannelExtractor
print("Warp loaded!")

# Global cache
CACHE = {
    "mesh_path": None,
    "mesh": None,
    "extractor": None,
}

RESOLUTIONS = {
    "960x540": (960, 540),
    "1920x1080": (1920, 1080),
    "3840x2160": (3840, 2160),
}

CHANNELS = ["depth", "normals", "edges", "shadow", "ao", "curvature", "material_id", "object_id"]


def load_mesh(obj_path):
    """Load and cache mesh."""
    if CACHE["mesh_path"] != obj_path:
        print(f"Loading: {obj_path}")
        CACHE["mesh"] = trimesh.load(obj_path)
        if hasattr(CACHE["mesh"], 'to_geometry'):
            CACHE["mesh"] = CACHE["mesh"].to_geometry()
        CACHE["mesh_path"] = obj_path
        CACHE["extractor"] = None
    return CACHE["mesh"]


def get_camera(mesh, azimuth, elevation, distance):
    """Calculate camera from spherical coords."""
    center = mesh.centroid
    bounds = mesh.bounds
    size = np.linalg.norm(bounds[1] - bounds[0])
    
    az = np.radians(azimuth)
    el = np.radians(elevation)
    dist = size * distance
    
    eye = center + np.array([
        dist * np.cos(el) * np.sin(az),
        -dist * np.cos(el) * np.cos(az),
        dist * np.sin(el)
    ])
    
    forward = center - eye
    forward = forward / np.linalg.norm(forward)
    
    return {
        "Eye": eye.tolist(),
        "Forward": forward.tolist(),
        "Up": [0, 0, 1],
        "IsPerspective": True,
        "FieldOfView": 0.785,
        "NearClip": 1.0,
        "FarClip": size * 5
    }, bounds.flatten().tolist()


def extract(obj_file, res_name, channels, azimuth, elevation, distance):
    """Extract channels."""
    if obj_file is None:
        return [None] * 8 + ["Upload an OBJ file"]
    
    t0 = time.time()
    
    # Load mesh
    mesh = load_mesh(obj_file.name)
    camera, bbox = get_camera(mesh, azimuth, elevation, distance)
    
    # Get or create extractor
    if CACHE["extractor"] is None:
        print("Creating extractor...")
        CACHE["extractor"] = WarpChannelExtractor(obj_file.name, camera, np.array(bbox))
    else:
        CACHE["extractor"].update_camera(camera)
    
    # Output dir
    out_dir = Path(tempfile.gettempdir()) / "channel_extract"
    out_dir.mkdir(exist_ok=True)
    
    # Extract
    resolution = RESOLUTIONS.get(res_name, (960, 540))
    print(f"Extracting {channels} at {resolution}...")
    
    t1 = time.time()
    CACHE["extractor"].extract_all(str(out_dir), resolution, channels)
    t2 = time.time()
    
    print(f"Extraction took {t2-t1:.2f}s")
    
    # Load results
    results = []
    for ch in CHANNELS:
        p = out_dir / f"{ch}.png"
        results.append(np.array(Image.open(p)) if p.exists() else None)
    
    results.append(f"✅ {len(channels)} channels in {t2-t0:.2f}s")
    return results


def load_revit_camera(obj_file):
    """Load camera.json if exists."""
    if obj_file is None:
        return 45, 25, 1.5, "No file"
    
    import json
    json_path = Path(obj_file.name).with_suffix(".json")
    if not json_path.exists():
        json_path = Path(obj_file.name).parent / "camera.json"
    
    if json_path.exists():
        try:
            with open(json_path) as f:
                cam = json.load(f)
            
            forward = np.array(cam["Forward"])
            az = np.degrees(np.arctan2(forward[0], -forward[1])) % 360
            el = np.degrees(np.arcsin(np.clip(-forward[2], -1, 1)))
            
            return float(az), float(el), 1.5, f"✅ Loaded {json_path.name}"
        except Exception as e:
            return 45, 25, 1.5, f"Error: {e}"
    
    return 45, 25, 1.5, "No camera.json found"


# Build UI
with gr.Blocks(title="Channel Extractor") as demo:
    gr.Markdown("# 📐 Channel Extractor (Warp GPU)")
    
    with gr.Row():
        with gr.Column(scale=1):
            obj_file = gr.File(label="OBJ File", file_types=[".obj"])
            res_dropdown = gr.Dropdown(list(RESOLUTIONS.keys()), value="960x540", label="Resolution")
            channel_check = gr.CheckboxGroup(CHANNELS, value=["depth", "normals", "edges"], label="Channels")
            
            gr.Markdown("### Camera")
            with gr.Row():
                load_cam_btn = gr.Button("📥 Load from Revit", size="sm")
            azimuth = gr.Slider(0, 360, 45, label="Azimuth")
            elevation = gr.Slider(-10, 90, 25, label="Elevation")
            distance = gr.Slider(0.5, 3, 1.5, label="Distance")
            
            cam_status = gr.Textbox(label="Camera Status", max_lines=1)
            
            extract_btn = gr.Button("🔧 Extract", variant="primary", size="lg")
            status = gr.Textbox(label="Status")
        
        with gr.Column(scale=2):
            with gr.Row():
                img_depth = gr.Image(label="Depth")
                img_normals = gr.Image(label="Normals")
                img_edges = gr.Image(label="Edges")
                img_shadow = gr.Image(label="Shadow")
            with gr.Row():
                img_ao = gr.Image(label="AO")
                img_curv = gr.Image(label="Curvature")
                img_mat = gr.Image(label="Material")
                img_obj = gr.Image(label="Object")
    
    # Wire events
    load_cam_btn.click(
        load_revit_camera, 
        inputs=[obj_file], 
        outputs=[azimuth, elevation, distance, cam_status]
    )
    
    extract_btn.click(
        extract,
        inputs=[obj_file, res_dropdown, channel_check, azimuth, elevation, distance],
        outputs=[img_depth, img_normals, img_edges, img_shadow, img_ao, img_curv, img_mat, img_obj, status]
    )

demo.launch()
