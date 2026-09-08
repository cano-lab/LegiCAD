# render_ui.py
import gradio as gr
import torch
from PIL import Image
import numpy as np
from pathlib import Path
import tempfile
import time

from ai_enhancer import ChannelEnhancer
from upscaler import TileUpscaler
from presets import MATERIAL_PRESETS, ROOF_PRESETS, STYLE_PRESETS, build_prompt
from scipy import ndimage
from scipy.ndimage import gaussian_filter

from channel_extractor_warp import WarpChannelExtractor

class RenderPipeline:
    def __init__(self):
        self.enhancer = None
        self.upscaler = None
        self.cancelled = False
        self.last_channels = {}
        self.last_mesh_path = None
        self.cached_mesh = None
        self.cached_extractor = None
    
    def cancel(self):
        self.cancelled = True
        if self.upscaler:
            self.upscaler.cancel()
    
    def reset(self):
        self.cancelled = False
        if self.upscaler:
            self.upscaler.cancelled = False
    
    def load_enhancer(self):
        if self.enhancer is None:
            print("Loading enhancer...")
            self.enhancer = ChannelEnhancer(model_id="SG161222/Realistic_Vision_V5.1_noVAE")
        return self.enhancer
    
    def load_upscaler(self):
        if self.upscaler is None:
            print("Loading upscaler...")
            self.upscaler = TileUpscaler()
        return self.upscaler


pipeline = RenderPipeline()

OUTPUT_FORMATS = {
    "PNG (Lossless)": {"ext": ".png", "params": {}},
    "JPEG (Smaller)": {"ext": ".jpg", "params": {"quality": 95}},
    "TIFF (Professional)": {"ext": ".tiff", "params": {"compression": "tiff_lzw"}},
}

INPUT_SIZES = {
    "Original": None,
    "512px (Fast)": 512,
    "768px (Balanced)": 768,
    "1024px (Quality)": 1024,
}

CHANNEL_OPTIONS = [
    "depth", "normals", "edges", "shadow", "ao", "curvature", "material_id", "object_id"
]

RESOLUTIONS = {
    "960x540 (Fast)": (960, 540),
    "1920x1080 (HD)": (1920, 1080),
    "2560x1440 (2K)": (2560, 1440),
    "3840x2160 (4K)": (3840, 2160),
}

CAMERA_PRESETS = {
    "Corner (default)": {"azimuth": 45, "elevation": 25, "distance": 1.5},
    "Front": {"azimuth": 0, "elevation": 15, "distance": 1.5},
    "Back": {"azimuth": 180, "elevation": 15, "distance": 1.5},
    "Left": {"azimuth": 270, "elevation": 15, "distance": 1.5},
    "Right": {"azimuth": 90, "elevation": 15, "distance": 1.5},
    "Front-Left": {"azimuth": 315, "elevation": 20, "distance": 1.5},
    "Front-Right": {"azimuth": 45, "elevation": 20, "distance": 1.5},
    "Top-Down": {"azimuth": 0, "elevation": 89, "distance": 2.0},
    "Bird's Eye": {"azimuth": 45, "elevation": 60, "distance": 2.0},
}


def save_image(image, base_path, format_name):
    fmt = OUTPUT_FORMATS.get(format_name, OUTPUT_FORMATS["PNG (Lossless)"])
    output_path = Path(base_path).with_suffix(fmt["ext"])
    image.save(output_path, **fmt["params"])
    return str(output_path)


def resize_input(image, max_size=None):
    if max_size is None:
        return image
    w, h = image.size
    if max(w, h) <= max_size:
        return image
    if w > h:
        new_w = max_size
        new_h = int(h * max_size / w)
    else:
        new_h = max_size
        new_w = int(w * max_size / h)
    new_w = (new_w // 8) * 8
    new_h = (new_h // 8) * 8
    return image.resize((new_w, new_h), Image.Resampling.LANCZOS)


def apply_depth_fog(image, depth, fog_strength, fog_color=(200, 210, 220)):
    if fog_strength == 0:
        return image
    img_arr = np.array(image).astype(np.float32)
    depth_arr = np.array(depth.convert('L').resize(image.size)).astype(np.float32) / 255.0
    fog_amount = (1 - depth_arr) * fog_strength
    fog_amount = fog_amount[:, :, np.newaxis]
    fog_layer = np.array(fog_color, dtype=np.float32)
    result = img_arr * (1 - fog_amount) + fog_layer * fog_amount
    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8))


def apply_edge_sharpening(image, edges, strength):
    if strength == 0:
        return image
    img_arr = np.array(image).astype(np.float32)
    edge_arr = np.array(edges.convert('L').resize(image.size)).astype(np.float32) / 255.0
    for c in range(3):
        channel = img_arr[:, :, c]
        blurred = gaussian_filter(channel, sigma=1)
        sharpened = channel + (channel - blurred) * strength * 2
        edge_weight = edge_arr * strength
        img_arr[:, :, c] = channel * (1 - edge_weight) + sharpened * edge_weight
    return Image.fromarray(np.clip(img_arr, 0, 255).astype(np.uint8))


def apply_ao_darkening(image, depth, ao_strength):
    if ao_strength == 0:
        return image
    img_arr = np.array(image).astype(np.float32)
    depth_arr = np.array(depth.convert('L').resize(image.size)).astype(np.float32)
    depth_dx = ndimage.sobel(depth_arr, axis=1)
    depth_dy = ndimage.sobel(depth_arr, axis=0)
    depth_gradient = np.sqrt(depth_dx**2 + depth_dy**2)
    ao = gaussian_filter(depth_gradient, sigma=3)
    ao = ao / (ao.max() + 1e-6)
    ao = ao[:, :, np.newaxis] * ao_strength
    result = img_arr * (1 - ao * 0.5)
    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8))


def apply_normal_lighting(image, normals, light_dir, intensity):
    if intensity == 0:
        return image
    img_arr = np.array(image).astype(np.float32)
    normal_arr = np.array(normals.resize(image.size)).astype(np.float32) / 255.0
    normal_arr = normal_arr * 2 - 1
    light = np.array(light_dir)
    light = light / (np.linalg.norm(light) + 1e-6)
    dot = np.sum(normal_arr * light, axis=2)
    dot = np.clip(dot, 0, 1)
    lighting = 1 + (dot - 0.5) * intensity
    lighting = lighting[:, :, np.newaxis]
    result = img_arr * lighting
    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8))


def update_prompt_from_presets(wall_mat, roof_mat, style, custom):
    config = build_prompt(wall_mat, roof_mat, style, custom)
    return config["prompt"], config["negative"], config["strength"], config["guidance"]


def apply_camera_preset(preset_name):
    preset = CAMERA_PRESETS.get(preset_name, CAMERA_PRESETS["Corner (default)"])
    return preset["azimuth"], preset["elevation"], preset["distance"]


def calculate_camera(mesh_center, mesh_size, azimuth, elevation, distance):
    az_rad = np.radians(azimuth)
    el_rad = np.radians(elevation)
    dist = mesh_size * distance
    
    eye = mesh_center + np.array([
        dist * np.cos(el_rad) * np.sin(az_rad),
        -dist * np.cos(el_rad) * np.cos(az_rad),
        dist * np.sin(el_rad)
    ])
    
    forward = (mesh_center - eye)
    forward = forward / np.linalg.norm(forward)
    
    return eye, forward


def quick_preview(obj_file, cam_azimuth, cam_elevation, cam_distance):
    """Fast depth-only preview for camera adjustment."""
    if not WARP_AVAILABLE or obj_file is None:
        return None, "Upload OBJ first"
    
    import trimesh
    
    try:
        mesh = trimesh.load(obj_file.name)
        if hasattr(mesh, 'to_geometry'):
            mesh = mesh.to_geometry()
        
        center = mesh.centroid
        bounds = mesh.bounds
        size = np.linalg.norm(bounds[1] - bounds[0])
        
        eye, forward = calculate_camera(center, size, cam_azimuth, cam_elevation, cam_distance)
        
        camera = {
            "Eye": eye.tolist(),
            "Forward": forward.tolist(),
            "Up": [0, 0, 1],
            "IsPerspective": True,
            "FieldOfView": 0.785,
            "NearClip": 1.0,
            "FarClip": size * 5
        }
        
        bbox = bounds.flatten().tolist()
        
        output_dir = Path(tempfile.gettempdir()) / "render_ui" / "preview"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        start = time.time()
        extractor = WarpChannelExtractor(obj_file.name, camera, np.array(bbox))
        _, depth = extractor.extract_depth(str(output_dir), (480, 270))
        elapsed = time.time() - start
        
        return depth, f"Preview: {elapsed:.2f}s"
    except Exception as e:
        return None, f"Error: {e}"


def load_revit_camera(obj_file):
    """Load camera from JSON sidecar file if exists."""
    if obj_file is None:
        return 45, 25, 1.5, "No file loaded"
    
    # Check for camera.json in same folder
    json_path = Path(obj_file.name).parent / "camera.json"
    
    if not json_path.exists():
        json_path = Path(obj_file.name).with_suffix(".json")
    
    if json_path.exists():
        import json
        try:
            with open(json_path) as f:
                cam = json.load(f)
            
            eye = np.array(cam["Eye"])
            forward = np.array(cam["Forward"])
            
            # Convert to spherical (approximate)
            azimuth = np.degrees(np.arctan2(forward[0], -forward[1])) % 360
            elevation = np.degrees(np.arcsin(np.clip(-forward[2], -1, 1)))
            
            return float(azimuth), float(elevation), 1.5, f"✅ Loaded from {json_path.name}"
        except Exception as e:
            return 45, 25, 1.5, f"Error: {e}"
    
    return 45, 25, 1.5, "No camera.json found"


def extract_channels(obj_file, resolution_name, selected_channels, 
                     light_x, light_y, light_z,
                     cam_azimuth, cam_elevation, cam_distance,
                     progress=gr.Progress()):
    if not WARP_AVAILABLE:
        return [None] * 8, "Warp not available"
    
    if obj_file is None:
        return [None] * 8, "Please upload an OBJ file"
    
    progress(0.1, "Loading mesh...")
    
    import trimesh
    t0 = time.time()
    progress(0.1, "Loading mesh...")
    mesh = trimesh.load(obj_file.name)
    # Cache mesh loading
    if pipeline.last_mesh_path != obj_file.name:
        pipeline.cached_mesh = trimesh.load(obj_file.name)
        if hasattr(pipeline.cached_mesh, 'to_geometry'):
            pipeline.cached_mesh = pipeline.cached_mesh.to_geometry()
        pipeline.last_mesh_path = obj_file.name
        pipeline.cached_extractor = None  # Force new extractor
    
    mesh = pipeline.cached_mesh
    t1 = time.time()
    print(f"Mesh load: {t1-t0:.2f}s")
    
    center = mesh.centroid
    bounds = mesh.bounds
    size = np.linalg.norm(bounds[1] - bounds[0])
    
    eye, forward = calculate_camera(center, size, cam_azimuth, cam_elevation, cam_distance)
    
    camera = {
        "Eye": eye.tolist(),
        "Forward": forward.tolist(),
        "Up": [0, 0, 1],
        "IsPerspective": True,
        "FieldOfView": 0.785,
        "NearClip": 1.0,
        "FarClip": size * 5
    }
    
    bbox = bounds.flatten().tolist()
    resolution = RESOLUTIONS.get(resolution_name, (960, 540))
    
    output_dir = Path(tempfile.gettempdir()) / "render_ui" / "channels"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    t2 = time.time()
    progress(0.2, "Initializing extractor...")
    
    # Cache extractor (BVH build is expensive)
    if pipeline.cached_extractor is None:
        pipeline.cached_extractor = WarpChannelExtractor(obj_file.name, camera, np.array(bbox))
    else:
        # Just update camera
        pipeline.cached_extractor.update_camera(camera)
    
    extractor = pipeline.cached_extractor
    
    t3 = time.time()
    print(f"Extractor init: {t3-t2:.2f}s")
    
    progress(0.3, "Extracting channels...")
    
    results = extractor.extract_all(str(output_dir), resolution, selected_channels)
    
    t4 = time.time()
    print(f"Extraction: {t4-t3:.2f}s")
    print(f"Total: {t4-t0:.2f}s")

    if hasattr(mesh, 'to_geometry'):
        mesh = mesh.to_geometry()
    
    center = mesh.centroid
    bounds = mesh.bounds
    size = np.linalg.norm(bounds[1] - bounds[0])
    
    eye, forward = calculate_camera(center, size, cam_azimuth, cam_elevation, cam_distance)
    
    camera = {
        "Eye": eye.tolist(),
        "Forward": forward.tolist(),
        "Up": [0, 0, 1],
        "IsPerspective": True,
        "FieldOfView": 0.785,
        "NearClip": 1.0,
        "FarClip": size * 5
    }
    
    bbox = bounds.flatten().tolist()
    resolution = RESOLUTIONS.get(resolution_name, (960, 540))
    
    output_dir = Path(tempfile.gettempdir()) / "render_ui" / "channels"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    progress(0.2, "Initializing extractor...")
    
    pipeline.last_mesh_path = obj_file.name
    
    extractor = WarpChannelExtractor(obj_file.name, camera, np.array(bbox))
    
    progress(0.3, "Extracting channels...")
    
    start_time = time.time()
    results = extractor.extract_all(str(output_dir), resolution, selected_channels)
    elapsed = time.time() - start_time
    
    progress(1.0, "Done!")
    
    channel_images = {}
    for ch in CHANNEL_OPTIONS:
        path = output_dir / f"{ch}.png"
        if path.exists():
            img = np.array(Image.open(path))
            channel_images[ch] = img
            pipeline.last_channels[ch] = img
        else:
            channel_images[ch] = None
    
    status = f"✅ {len(results)} channels in {elapsed:.1f}s @ {resolution[0]}x{resolution[1]}"
    
    return (
        channel_images.get("depth"),
        channel_images.get("normals"),
        channel_images.get("edges"),
        channel_images.get("shadow"),
        channel_images.get("ao"),
        channel_images.get("curvature"),
        channel_images.get("material_id"),
        channel_images.get("object_id"),
        status
    )


def transfer_channels():
    return (
        pipeline.last_channels.get("depth"),
        pipeline.last_channels.get("normals"),
        pipeline.last_channels.get("edges"),
        pipeline.last_channels.get("ao"),
        "✅ Transferred!"
    )


def cancel_render():
    pipeline.cancel()
    return "Cancelled!"


def enhance_image(
    revit_image, depth_image, normals_image, edges_image, ao_image,
    prompt, negative_prompt, strength, guidance,
    fog_strength, edge_sharpness, ao_strength,
    light_x, light_y, light_z, light_intensity,
    input_size, output_format, do_upscale,
    progress=gr.Progress()
):
    pipeline.reset()
    
    if revit_image is None:
        return None, None, "Please upload an image"
    
    progress(0.1, "Loading models...")
    enhancer = pipeline.load_enhancer()
    
    temp_dir = Path(tempfile.gettempdir()) / "render_ui"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    revit_pil = Image.fromarray(revit_image)
    max_size = INPUT_SIZES.get(input_size)
    revit_pil = resize_input(revit_pil, max_size)
    
    input_path = temp_dir / "input.png"
    revit_pil.save(input_path)
    
    if pipeline.cancelled:
        return None, None, "Cancelled"
    
    progress(0.2, "Running AI enhancement...")
    
    orig_w, orig_h = revit_pil.size
    aspect = orig_w / orig_h
    if aspect > 1:
        new_w = 512
        new_h = (int(512 / aspect) // 8) * 8
    else:
        new_h = 512
        new_w = (int(512 * aspect) // 8) * 8
    
    new_h = max(new_h, 8)
    new_w = max(new_w, 8)
    
    result = enhancer.enhance(
        depth_path=str(input_path),
        prompt=prompt,
        negative_prompt=negative_prompt,
        num_inference_steps=25,
        guidance_scale=guidance,
        controlnet_conditioning_scale=strength,
        width=new_w,
        height=new_h
    )
    
    result = result.resize(revit_pil.size, Image.Resampling.LANCZOS)
    
    if pipeline.cancelled:
        return np.array(result), None, "Cancelled"
    
    progress(0.5, "Applying effects...")
    
    if depth_image is not None and fog_strength > 0:
        result = apply_depth_fog(result, Image.fromarray(depth_image), fog_strength)
    
    if depth_image is not None and ao_strength > 0:
        result = apply_ao_darkening(result, Image.fromarray(depth_image), ao_strength)
    
    if edges_image is not None and edge_sharpness > 0:
        result = apply_edge_sharpening(result, Image.fromarray(edges_image), edge_sharpness)
    
    if normals_image is not None and light_intensity > 0:
        result = apply_normal_lighting(result, Image.fromarray(normals_image), 
                                       (light_x, light_y, light_z), light_intensity)
    
    if pipeline.cancelled:
        return np.array(result), None, "Cancelled"
    
    if do_upscale:
        progress(0.6, "Upscaling...")
        upscaler = pipeline.load_upscaler()
        small_path = temp_dir / "small.png"
        result.save(small_path)
        upscaled_path = temp_dir / "upscaled.png"
        
        def upscale_progress(current, total):
            if not pipeline.cancelled:
                progress(0.6 + 0.35 * (current / total), f"Tile {current}/{total}")
        
        result_path = upscaler.upscale(
            str(small_path), str(upscaled_path), 
            prompt=prompt, progress_callback=upscale_progress
        )
        
        if result_path is None:
            return np.array(result), None, "Cancelled"
        
        result = Image.open(upscaled_path)
    
    progress(0.98, "Saving...")
    output_path = save_image(result, temp_dir / "output", output_format)
    
    progress(1.0, "Done!")
    return np.array(result), output_path, f"Saved: {output_path}"


def create_ui():
    with gr.Blocks(title="Revit AI Render Pipeline", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🏠 Revit AI Render Pipeline")
        
        with gr.Tabs():
            with gr.TabItem("📐 Extract Channels"):
                with gr.Row():
                    with gr.Column(scale=1):
                        obj_input = gr.File(label="OBJ File", file_types=[".obj"])
                        
                        resolution_select = gr.Dropdown(
                            choices=list(RESOLUTIONS.keys()),
                            value="960x540 (Fast)",
                            label="Resolution"
                        )
                        
                        channel_select = gr.CheckboxGroup(
                            choices=CHANNEL_OPTIONS,
                            value=["depth", "normals", "edges", "shadow", "ao"],
                            label="Channels"
                        )
                        
                        gr.Markdown("### 📷 Camera")
                        with gr.Row():
                            camera_preset = gr.Dropdown(
                                choices=list(CAMERA_PRESETS.keys()),
                                value="Corner (default)",
                                label="Preset",
                                scale=2
                            )
                            load_cam_btn = gr.Button("📥 Load Revit", size="sm", scale=1)
                        
                        with gr.Row():
                            cam_azimuth = gr.Slider(0, 360, value=45, label="Azimuth (°)")
                            cam_elevation = gr.Slider(-10, 90, value=25, label="Elevation (°)")
                        cam_distance = gr.Slider(0.5, 3, value=1.5, step=0.1, label="Distance")
                        
                        preview_btn = gr.Button("👁 Quick Preview", variant="secondary")
                        preview_image = gr.Image(label="Preview", type="numpy", height=180)
                        preview_status = gr.Textbox(show_label=False, max_lines=1)
                        
                        gr.Markdown("### ☀️ Light")
                        with gr.Row():
                            light_x = gr.Slider(-1, 1, value=0.5, label="X")
                            light_y = gr.Slider(-1, 1, value=0.8, label="Y")
                            light_z = gr.Slider(0, 2, value=1.0, label="Z")
                        
                        extract_btn = gr.Button("🔧 Extract Channels", variant="primary", size="lg")
                        transfer_btn = gr.Button("📤 Transfer to Enhancement", variant="secondary")
                        extract_status = gr.Textbox(label="Status")
                    
                    with gr.Column(scale=2):
                        with gr.Row():
                            depth_out = gr.Image(label="Depth", type="numpy")
                            normals_out = gr.Image(label="Normals", type="numpy")
                            edges_out = gr.Image(label="Edges", type="numpy")
                            shadow_out = gr.Image(label="Shadow", type="numpy")
                        with gr.Row():
                            ao_out = gr.Image(label="AO", type="numpy")
                            curvature_out = gr.Image(label="Curvature", type="numpy")
                            material_out = gr.Image(label="Material ID", type="numpy")
                            object_out = gr.Image(label="Object ID", type="numpy")
            
            with gr.TabItem("🎨 AI Enhancement"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("### Input")
                        revit_input = gr.Image(label="Render Image", type="numpy")
                        
                        with gr.Row():
                            input_size = gr.Dropdown(
                                choices=list(INPUT_SIZES.keys()),
                                value="512px (Fast)",
                                label="Size"
                            )
                            output_format = gr.Dropdown(
                                choices=list(OUTPUT_FORMATS.keys()),
                                value="PNG (Lossless)",
                                label="Format"
                            )
                        
                        gr.Markdown("### Channels")
                        with gr.Row():
                            depth_input = gr.Image(label="Depth", type="numpy", height=80)
                            normals_input = gr.Image(label="Normals", type="numpy", height=80)
                        with gr.Row():
                            edges_input = gr.Image(label="Edges", type="numpy", height=80)
                            ao_input = gr.Image(label="AO", type="numpy", height=80)
                        
                        gr.Markdown("### Style")
                        with gr.Row():
                            wall_preset = gr.Dropdown(
                                choices=["None"] + list(MATERIAL_PRESETS.keys()),
                                value="None", label="Wall"
                            )
                            roof_preset = gr.Dropdown(
                                choices=["None"] + list(ROOF_PRESETS.keys()),
                                value="None", label="Roof"
                            )
                        
                        style_preset = gr.Dropdown(
                            choices=list(STYLE_PRESETS.keys()),
                            value="Clean Studio", label="Style"
                        )
                        
                        custom_prompt = gr.Textbox(label="Custom", placeholder="Extra details...")
                        apply_presets_btn = gr.Button("Apply Presets", size="sm")
                        
                        prompt = gr.Textbox(
                            label="Prompt",
                            value="architectural visualization, residential home, clean render",
                            lines=2
                        )
                        negative_prompt = gr.Textbox(
                            label="Negative",
                            value="blurry, distorted, ugly, deformed",
                            lines=1
                        )
                        
                        with gr.Row():
                            strength = gr.Slider(0.1, 0.8, value=0.35, label="Strength")
                            guidance = gr.Slider(1, 15, value=8.0, label="Guidance")
                        
                        gr.Markdown("### Effects")
                        with gr.Row():
                            fog_strength = gr.Slider(0, 1, value=0, label="Fog")
                            ao_slider = gr.Slider(0, 1, value=0, label="AO")
                        edge_sharpness = gr.Slider(0, 2, value=0, label="Edge Sharpen")
                        
                        with gr.Accordion("Lighting", open=False):
                            with gr.Row():
                                enh_light_x = gr.Slider(-1, 1, value=0.5, label="X")
                                enh_light_y = gr.Slider(-1, 1, value=0.5, label="Y")
                                enh_light_z = gr.Slider(-1, 1, value=1, label="Z")
                            light_intensity = gr.Slider(0, 2, value=0, label="Intensity")
                        
                        do_upscale = gr.Checkbox(label="4x Upscale", value=False)
                        
                        with gr.Row():
                            enhance_btn = gr.Button("🚀 Enhance", variant="primary", scale=3)
                            cancel_btn = gr.Button("⏹ Cancel", variant="stop", scale=1)
                    
                    with gr.Column(scale=1):
                        gr.Markdown("### Output")
                        output_image = gr.Image(label="Result", type="numpy")
                        output_file = gr.File(label="Download")
                        status = gr.Textbox(label="Status")
        
        # Wiring
        camera_preset.change(fn=apply_camera_preset, inputs=[camera_preset], 
                            outputs=[cam_azimuth, cam_elevation, cam_distance])
        
        preview_btn.click(fn=quick_preview, 
                         inputs=[obj_input, cam_azimuth, cam_elevation, cam_distance],
                         outputs=[preview_image, preview_status])
        
        load_cam_btn.click(fn=load_revit_camera, inputs=[obj_input],
                          outputs=[cam_azimuth, cam_elevation, cam_distance, preview_status])
        
        extract_btn.click(
            fn=extract_channels,
            inputs=[obj_input, resolution_select, channel_select, 
                   light_x, light_y, light_z, cam_azimuth, cam_elevation, cam_distance],
            outputs=[depth_out, normals_out, edges_out, shadow_out, ao_out, 
                    curvature_out, material_out, object_out, extract_status]
        )
        
        transfer_btn.click(fn=transfer_channels,
                          outputs=[depth_input, normals_input, edges_input, ao_input, status])
        
        apply_presets_btn.click(fn=update_prompt_from_presets,
                               inputs=[wall_preset, roof_preset, style_preset, custom_prompt],
                               outputs=[prompt, negative_prompt, strength, guidance])
        
        cancel_btn.click(fn=cancel_render, outputs=[status])
        
        enhance_btn.click(
            fn=enhance_image,
            inputs=[revit_input, depth_input, normals_input, edges_input, ao_input,
                   prompt, negative_prompt, strength, guidance,
                   fog_strength, edge_sharpness, ao_slider,
                   enh_light_x, enh_light_y, enh_light_z, light_intensity,
                   input_size, output_format, do_upscale],
            outputs=[output_image, output_file, status]
        )
    
    return demo


if __name__ == "__main__":
    demo = create_ui()
    demo.launch(allowed_paths=[tempfile.gettempdir()])