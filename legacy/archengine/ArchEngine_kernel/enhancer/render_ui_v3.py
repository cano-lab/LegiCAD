# render_ui_v6.py
print("=== STARTING ===")
import time
import numpy as np
from pathlib import Path
import tempfile
from PIL import Image
import json
import threading
import queue

# Initialize Warp FIRST on main thread
import warp as wp
wp.init()

from channel_extractor_warp import WarpChannelExtractor
import trimesh

print("Modules loaded")

# ============ STATE ============
class State:
    mesh_path = None
    mesh = None
    center = None
    bounds = None
    size = None
    extractor = None
    out_dir = Path(tempfile.gettempdir()) / "render_ui"
    
state = State()
state.out_dir.mkdir(exist_ok=True)

# Queue for main-thread mesh loading
load_queue = queue.Queue()
result_queue = queue.Queue()

RESOLUTIONS = {
    "960x540": (960, 540),
    "1920x1080": (1920, 1080),
    "3840x2160": (3840, 2160),
}

CHANNELS = ["depth", "normals", "edges", "shadow", "ao", "curvature", "material_id", "object_id"]

PRESETS = {
    "Corner": (45, 25, 1.5),
    "Front": (0, 15, 1.5),
    "Back": (180, 15, 1.5),
    "Left": (270, 15, 1.5), 
    "Right": (90, 15, 1.5),
    "Top": (0, 89, 2.0),
}


def load_mesh_internal(path):
    """Load mesh - call only from main thread."""
    print(f"Loading: {path}")
    t0 = time.time()
    
    state.mesh = trimesh.load(path)
    if hasattr(state.mesh, 'to_geometry'):
        state.mesh = state.mesh.to_geometry()
    
    state.mesh_path = path
    state.center = state.mesh.centroid
    state.bounds = state.mesh.bounds
    state.size = np.linalg.norm(state.bounds[1] - state.bounds[0])
    
    # Create extractor
    camera = get_camera_dict(45, 25, 1.5)
    state.extractor = WarpChannelExtractor(path, camera, state.bounds.flatten())
    
    # Pre-compile
    state.extractor.extract_all(str(state.out_dir), (240, 135), ["depth"])
    
    print(f"Loaded in {time.time()-t0:.2f}s")
    return f"✅ {Path(path).name} ({time.time()-t0:.1f}s)"


def get_camera_dict(azimuth, elevation, distance):
    if state.center is None:
        return None
    
    az = np.radians(azimuth)
    el = np.radians(elevation)
    dist = state.size * distance
    
    eye = state.center + np.array([
        dist * np.cos(el) * np.sin(az),
        -dist * np.cos(el) * np.cos(az),
        dist * np.sin(el)
    ])
    
    forward = state.center - eye
    forward = forward / np.linalg.norm(forward)
    
    return {
        "Eye": eye.tolist(),
        "Forward": forward.tolist(),
        "Up": [0, 0, 1],
        "IsPerspective": True,
        "FieldOfView": 0.785,
        "NearClip": 1.0,
        "FarClip": state.size * 5
    }


def extract_internal(res_name, channels, azimuth, elevation, distance):
    """Extract channels - call only from main thread."""
    if state.extractor is None:
        return [None]*8 + ["Load a mesh first"]
    
    t0 = time.time()
    
    camera = get_camera_dict(azimuth, elevation, distance)
    state.extractor.update_camera(camera)
    
    resolution = RESOLUTIONS.get(res_name, (960, 540))
    state.extractor.extract_all(str(state.out_dir), resolution, channels)
    
    elapsed = time.time() - t0
    
    results = []
    for ch in CHANNELS:
        p = state.out_dir / f"{ch}.png"
        results.append(np.array(Image.open(p)) if p.exists() else None)
    
    results.append(f"✅ {len(channels)} channels in {elapsed:.2f}s")
    return results


def load_revit_camera_internal(mesh_path):
    """Load camera.json sidecar."""
    if mesh_path is None:
        return 45, 25, 1.5, "No mesh"
    
    json_path = Path(mesh_path).parent / "camera.json"
    if not json_path.exists():
        json_path = Path(mesh_path).with_suffix(".json")
    
    if json_path.exists():
        try:
            with open(json_path) as f:
                cam = json.load(f)
            
            forward = np.array(cam["Forward"])
            az = np.degrees(np.arctan2(forward[0], -forward[1])) % 360
            el = np.degrees(np.arcsin(np.clip(-forward[2], -1, 1)))
            
            return float(az), float(el), 1.5, f"✅ {json_path.name}"
        except Exception as e:
            return 45, 25, 1.5, f"Error: {e}"
    
    return 45, 25, 1.5, "No camera.json"


# ============ PRE-LOAD DEFAULT MESH ============
DEFAULT_MESH = "C:\\Users\\jerro\\Desktop\\channel_test\\Small gothic cottage JR 3D View.obj"
if Path(DEFAULT_MESH).exists():
    load_mesh_internal(DEFAULT_MESH)
    print("Default mesh ready")


# ============ GRADIO ============
import gradio as gr

def load_mesh_handler(obj_file):
    if obj_file is None:
        return "No file"
    return load_mesh_internal(obj_file.name)

def extract_handler(res, channels, az, el, dist):
    return extract_internal(res, channels, az, el, dist)

def load_camera_handler():
    return load_revit_camera_internal(state.mesh_path)

def apply_preset(name):
    return PRESETS.get(name, (45, 25, 1.5))


with gr.Blocks(title="Channel Extractor") as demo:
    gr.Markdown("# 📐 Revit Channel Extractor (GPU)")
    
    with gr.Row():
        with gr.Column(scale=1):
            obj_file = gr.File(label="OBJ File", file_types=[".obj"])
            load_status = gr.Textbox(label="Mesh Status", value=f"✅ {Path(DEFAULT_MESH).name}" if state.extractor else "")
            
            res = gr.Dropdown(list(RESOLUTIONS.keys()), value="960x540", label="Resolution")
            channels = gr.CheckboxGroup(CHANNELS, value=["depth", "normals", "edges", "shadow", "ao"], label="Channels")
            
            gr.Markdown("### 📷 Camera")
            with gr.Row():
                preset = gr.Dropdown(list(PRESETS.keys()), value="Corner", label="Preset")
                load_cam_btn = gr.Button("📥 Revit", size="sm")
            
            azimuth = gr.Slider(0, 360, 45, label="Azimuth (°)")
            elevation = gr.Slider(-10, 90, 25, label="Elevation (°)")
            distance = gr.Slider(0.5, 3, 1.5, step=0.1, label="Distance")
            cam_status = gr.Textbox(label="Camera Status", max_lines=1)
            
            extract_btn = gr.Button("🔧 Extract Channels", variant="primary", size="lg")
            status = gr.Textbox(label="Result")
        
        with gr.Column(scale=2):
            with gr.Row():
                img0 = gr.Image(label="Depth")
                img1 = gr.Image(label="Normals")
                img2 = gr.Image(label="Edges")
                img3 = gr.Image(label="Shadow")
            with gr.Row():
                img4 = gr.Image(label="AO")
                img5 = gr.Image(label="Curvature")
                img6 = gr.Image(label="Material")
                img7 = gr.Image(label="Object")
    
    # Events
    obj_file.change(load_mesh_handler, inputs=[obj_file], outputs=[load_status])
    preset.change(apply_preset, inputs=[preset], outputs=[azimuth, elevation, distance])
    load_cam_btn.click(load_camera_handler, outputs=[azimuth, elevation, distance, cam_status])
    extract_btn.click(
        extract_handler,
        inputs=[res, channels, azimuth, elevation, distance],
        outputs=[img0, img1, img2, img3, img4, img5, img6, img7, status]
    )

print("\n=== LAUNCHING UI ===\n")
demo.queue(max_size=1).launch()