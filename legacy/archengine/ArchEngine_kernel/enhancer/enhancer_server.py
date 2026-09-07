# enhancer_server.py

# HuggingFace configuration - always allow online downloads
import os
os.environ.pop('HF_HUB_OFFLINE', None)
os.environ.pop('TRANSFORMERS_OFFLINE', None)
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
print("[INFO] HuggingFace online mode - models will download if needed")

print("=== STARTING SERVER ===")
import time
import numpy as np
from pathlib import Path
import tempfile
from PIL import Image
import json
import base64
import io
import torch
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from postprocessor import ArchitecturalPostProcessor, POSTPROCESS_PRESETS

# Try to initialize Warp (may fail in PyInstaller bundles)
WARP_AVAILABLE = False
WarpChannelExtractor = None
try:
    import warp as wp
    wp.init()

    # In PyInstaller bundles, we need to dynamically import from source file
    # because warp's @wp.kernel decorator needs source code access
    import sys
    if getattr(sys, 'frozen', False):
        # Running in PyInstaller bundle
        import importlib.util
        bundle_dir = sys._MEIPASS
        source_path = os.path.join(bundle_dir, 'channel_extractor_warp.py')
        if os.path.exists(source_path):
            spec = importlib.util.spec_from_file_location("channel_extractor_warp", source_path)
            channel_extractor_warp = importlib.util.module_from_spec(spec)
            sys.modules["channel_extractor_warp"] = channel_extractor_warp
            spec.loader.exec_module(channel_extractor_warp)
            WarpChannelExtractor = channel_extractor_warp.WarpChannelExtractor
            print(f"[OK] Warp loaded from bundle: {source_path}")
        else:
            raise FileNotFoundError(f"channel_extractor_warp.py not found in bundle at {source_path}")
    else:
        # Normal import
        from channel_extractor_warp import WarpChannelExtractor

    WARP_AVAILABLE = True
    print("[OK] Warp GPU acceleration available")
except Exception as e:
    print(f"[WARN] Warp not available (will use CPU fallback): {e}")

import trimesh

# IFC support
try:
    from ifc_tools import (
        load_ifc, get_element_summary, get_elements_by_type,
        get_materials, get_elements_by_material, global_id_to_color
    )
    IFC_AVAILABLE = True
    print("IFC support available")
except ImportError:
    IFC_AVAILABLE = False
    print("IFC support not available (install ifcopenshell)")

# IFC geometry renderer for element ID pass
try:
    from ifc_renderer import get_ifc_renderer, IFCElementRenderer
    IFC_RENDERER_AVAILABLE = True
    print("IFC renderer available")
except ImportError as e:
    IFC_RENDERER_AVAILABLE = False
    print(f"IFC renderer not available: {e}")

print("Modules loaded")

# ============================================================
# GPU MEMORY OPTIMIZATION (8GB VRAM)
# ============================================================
import gc

# Check for xformers (20-40% speedup, less VRAM)
XFORMERS_AVAILABLE = False
try:
    import xformers
    XFORMERS_AVAILABLE = True
    print("[OK] xformers available - memory efficient attention enabled")
except ImportError:
    print("[WARN] xformers not installed - using standard attention")


def optimize_pipeline(pipe, device="cuda"):
    """Apply all memory optimizations for 8GB VRAM."""
    if not torch.cuda.is_available():
        return pipe

    pipe = pipe.to(device)

    # Enable xformers if available (significant speedup and memory savings)
    if XFORMERS_AVAILABLE:
        try:
            pipe.enable_xformers_memory_efficient_attention()
            print("    [OK] xformers memory efficient attention enabled")
        except Exception as e:
            print(f"    [WARN] xformers failed: {e}")

    # Attention slicing (reduces VRAM by processing in chunks)
    try:
        pipe.enable_attention_slicing(1)
    except Exception:
        pass

    # VAE optimizations (significant memory savings for large images)
    if hasattr(pipe, 'vae') and pipe.vae is not None:
        try:
            pipe.vae.enable_slicing()
            pipe.vae.enable_tiling()
        except Exception:
            pass

    # Clear CUDA cache after optimization
    torch.cuda.empty_cache()
    gc.collect()

    return pipe


def clear_vram():
    """Aggressively clear VRAM between operations."""
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    gc.collect()


app = Flask(__name__)
CORS(app)
# Add this global to store Revit camera
class State:
    mesh_path = None
    mesh = None
    center = None
    bounds = None
    size = None
    extractor = None
    postprocessor = None
    out_dir = Path(tempfile.gettempdir()) / "render_server"

    # AI (lazy loaded)
    enhancer = None
    upscaler = None

    # Revit camera (direct)
    revit_camera = None

    # Revit environment sync
    section_box = None  # Clipping bounds from Revit
    sun_settings = None  # Sun/lighting settings

    # Live sync
    live_sync_enabled = False
    live_sync_data = None  # Latest pushed data from Revit
    live_sync_timestamp = None

    # Image history for undo/redo
    history = []  # List of history entries: [{"timestamp": ..., "label": ..., "files": {...}}, ...]
    history_position = -1  # Current position in history (-1 = latest/no history)
    max_history = 20  # Maximum history entries to keep

    # IFC data
    ifc_path = None
    ifc_data = None  # Loaded IFC file object
    ifc_summary = None  # Element type summary
    ifc_materials = None  # Material list
    selected_elements = []  # Currently selected element GlobalIds
    ifc_renderer = None  # IFC geometry renderer for element ID pass
    element_id_image = None  # Rendered element ID pass
    ifc_bounds = None  # IFC geometry bounds [min, max]
    ifc_center = None  # IFC geometry center
    ifc_size = None  # IFC geometry size (diagonal)

state = State()


# ============================================================
# IMAGE HISTORY - Undo/Redo for enhancements
# ============================================================
def history_save(label: str = "Enhancement"):
    """Save current image state to history before making changes."""
    import shutil
    from datetime import datetime

    history_dir = state.out_dir / "history"
    history_dir.mkdir(exist_ok=True)

    # Generate timestamp-based folder name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    entry_dir = history_dir / timestamp
    entry_dir.mkdir(exist_ok=True)

    # Files to save in history
    files_to_save = ["enhanced.png", "enhanced_original.png", "postprocessed.png", "upscaled.png", "base.png"]
    saved_files = {}

    for filename in files_to_save:
        src = state.out_dir / filename
        if src.exists():
            dst = entry_dir / filename
            shutil.copy2(src, dst)
            saved_files[filename] = str(dst)

    if not saved_files:
        # Nothing to save
        return None

    # If we're not at the end of history (user did undo then new action), truncate future
    if state.history_position >= 0 and state.history_position < len(state.history) - 1:
        # Remove future entries
        for entry in state.history[state.history_position + 1:]:
            entry_path = Path(entry.get("path", ""))
            if entry_path.exists():
                shutil.rmtree(entry_path, ignore_errors=True)
        state.history = state.history[:state.history_position + 1]

    # Add new entry
    entry = {
        "timestamp": timestamp,
        "label": label,
        "path": str(entry_dir),
        "files": saved_files,
        "datetime": datetime.now().isoformat()
    }
    state.history.append(entry)
    state.history_position = len(state.history) - 1

    # Trim old history if exceeds max
    while len(state.history) > state.max_history:
        old_entry = state.history.pop(0)
        old_path = Path(old_entry.get("path", ""))
        if old_path.exists():
            shutil.rmtree(old_path, ignore_errors=True)
        state.history_position -= 1

    print(f"History saved: {label} ({len(saved_files)} files)")
    return entry


def history_undo():
    """Restore previous state from history."""
    import shutil

    if state.history_position < 0 or len(state.history) == 0:
        return None, "No history to undo"

    # Save current state first if at the end (so we can redo back to it)
    if state.history_position == len(state.history) - 1:
        # Save current as "Current" before undoing
        history_save("Current (before undo)")

    # Move back in history
    if state.history_position > 0:
        state.history_position -= 1
    else:
        return None, "Already at oldest history"

    entry = state.history[state.history_position]

    # Restore files
    for filename, src_path in entry.get("files", {}).items():
        src = Path(src_path)
        dst = state.out_dir / filename
        if src.exists():
            shutil.copy2(src, dst)

    print(f"Undo to: {entry.get('label')} ({entry.get('timestamp')})")
    return entry, None


def history_redo():
    """Restore next state from history (after undo)."""
    import shutil

    if state.history_position >= len(state.history) - 1:
        return None, "Nothing to redo"

    state.history_position += 1
    entry = state.history[state.history_position]

    # Restore files
    for filename, src_path in entry.get("files", {}).items():
        src = Path(src_path)
        dst = state.out_dir / filename
        if src.exists():
            shutil.copy2(src, dst)

    print(f"Redo to: {entry.get('label')} ({entry.get('timestamp')})")
    return entry, None


def history_list():
    """Get list of history entries."""
    return {
        "entries": [
            {
                "index": i,
                "label": e.get("label"),
                "timestamp": e.get("timestamp"),
                "datetime": e.get("datetime"),
                "files": list(e.get("files", {}).keys()),
                "is_current": i == state.history_position
            }
            for i, e in enumerate(state.history)
        ],
        "position": state.history_position,
        "total": len(state.history),
        "can_undo": state.history_position > 0,
        "can_redo": state.history_position < len(state.history) - 1
    }


@app.route('/api/history/undo', methods=['POST'])
def api_history_undo():
    """Undo to previous image state."""
    entry, error = history_undo()
    if error:
        return jsonify({"error": error}), 400

    # Return the restored enhanced image
    enhanced_path = state.out_dir / "enhanced.png"
    if enhanced_path.exists():
        with open(enhanced_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode()
    else:
        img_b64 = None

    return jsonify({
        "success": True,
        "restored": entry.get("label"),
        "timestamp": entry.get("timestamp"),
        "image": img_b64,
        "history": history_list()
    })


@app.route('/api/history/redo', methods=['POST'])
def api_history_redo():
    """Redo to next image state."""
    entry, error = history_redo()
    if error:
        return jsonify({"error": error}), 400

    # Return the restored enhanced image
    enhanced_path = state.out_dir / "enhanced.png"
    if enhanced_path.exists():
        with open(enhanced_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode()
    else:
        img_b64 = None

    return jsonify({
        "success": True,
        "restored": entry.get("label"),
        "timestamp": entry.get("timestamp"),
        "image": img_b64,
        "history": history_list()
    })


@app.route('/api/history/list', methods=['GET'])
def api_history_list():
    """Get history list."""
    return jsonify(history_list())


@app.route('/api/history/jump/<int:index>', methods=['POST'])
def api_history_jump(index):
    """Jump to specific history entry."""
    import shutil

    if index < 0 or index >= len(state.history):
        return jsonify({"error": f"Invalid history index {index}"}), 400

    entry = state.history[index]
    state.history_position = index

    # Restore files
    for filename, src_path in entry.get("files", {}).items():
        src = Path(src_path)
        dst = state.out_dir / filename
        if src.exists():
            shutil.copy2(src, dst)

    # Return the restored enhanced image
    enhanced_path = state.out_dir / "enhanced.png"
    if enhanced_path.exists():
        with open(enhanced_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode()
    else:
        img_b64 = None

    return jsonify({
        "success": True,
        "restored": entry.get("label"),
        "timestamp": entry.get("timestamp"),
        "image": img_b64,
        "history": history_list()
    })


@app.route('/api/history/clear', methods=['POST'])
def api_history_clear():
    """Clear all history."""
    import shutil

    history_dir = state.out_dir / "history"
    if history_dir.exists():
        shutil.rmtree(history_dir, ignore_errors=True)

    state.history = []
    state.history_position = -1

    return jsonify({"success": True, "message": "History cleared"})


# ============================================================
# LIVE SYNC - Receives pushed updates from Revit
# ============================================================
@app.route('/api/live_sync', methods=['POST'])
def api_live_sync_receive():
    """Receives live camera/section box updates pushed from Revit."""
    data = request.json

    if data:
        state.live_sync_data = data
        state.live_sync_timestamp = time.time()

        # Update camera if present
        if 'camera' in data:
            cam = data['camera']
            state.revit_camera = {
                "Eye": cam.get('eye', [0, 0, 0]),
                "Forward": cam.get('forward', [0, 1, 0]),
                "Up": cam.get('up', [0, 0, 1]),
                "IsPerspective": cam.get('isPerspective', True),
                "FieldOfView": cam.get('fov', 0.785),
                "NearClip": 1.0,
                "FarClip": state.size * 5 if state.size else 100000
            }

        # Update section box if present
        if 'sectionBox' in data and data['sectionBox']:
            state.section_box = data['sectionBox']

        return jsonify({"status": "ok"})

    return jsonify({"status": "error", "message": "No data"}), 400


@app.route('/api/live_sync/status', methods=['GET'])
def api_live_sync_status():
    """Get current live sync status and latest data."""
    return jsonify({
        "enabled": state.live_sync_enabled,
        "hasData": state.live_sync_data is not None,
        "lastUpdate": state.live_sync_timestamp,
        "viewName": state.live_sync_data.get('viewName') if state.live_sync_data else None
    })


@app.route('/api/live_sync/latest', methods=['GET'])
def api_live_sync_latest():
    """Get the latest synced camera/view data."""
    if state.live_sync_data:
        return jsonify({
            "status": "ok",
            "data": state.live_sync_data,
            "age_ms": (time.time() - state.live_sync_timestamp) * 1000 if state.live_sync_timestamp else None
        })
    return jsonify({"status": "ok", "data": None, "message": "No live sync data yet"})


@app.route('/api/debug/section_box', methods=['GET'])
def api_debug_section_box():
    """Debug endpoint to check section box state."""
    import requests

    result = {
        "python_state": {
            "section_box": state.section_box,
            "has_extractor": state.extractor is not None,
            "extractor_has_method": hasattr(state.extractor, 'set_section_box') if state.extractor else False,
            "extractor_section_box": getattr(state.extractor, 'section_box', None) if state.extractor else None
        },
        "revit_response": None
    }

    # Try to fetch from Revit
    try:
        resp = requests.get("http://localhost:48884/revit_mcp/export_section_box/", timeout=5)
        result["revit_response"] = resp.json()
        result["revit_status_code"] = resp.status_code
    except Exception as e:
        result["revit_error"] = str(e)

    return jsonify(result)


@app.route('/api/set_section_box', methods=['POST'])
def api_set_section_box():
    """
    Manually set section box bounds for testing (bypasses Revit).

    POST body: {
        "min": [x, y, z],  // in mm
        "max": [x, y, z],  // in mm
        "enabled": true
    }

    Or use "auto" to estimate from mesh bounds:
    POST body: {"auto": true, "margin": 0.1}  // 10% margin
    """
    if not state.extractor:
        return jsonify({"error": "No mesh loaded"}), 400

    data = request.json or {}

    if data.get("auto"):
        # Auto-calculate from mesh bounds
        margin = data.get("margin", 0.1)
        if state.bounds is not None:
            bounds = np.array(state.bounds)
            size = bounds[1] - bounds[0]
            box_min = bounds[0] + size * margin
            box_max = bounds[1] - size * margin

            section_box = {
                "enabled": True,
                "min": box_min.tolist(),
                "max": box_max.tolist(),
                "source": "auto"
            }
        else:
            return jsonify({"error": "No mesh bounds available"}), 400
    elif "min" in data and "max" in data:
        section_box = {
            "enabled": data.get("enabled", True),
            "min": data["min"],
            "max": data["max"],
            "source": "manual"
        }
    elif data.get("enabled") == False:
        # Disable section box
        state.section_box = None
        if hasattr(state.extractor, 'clear_section_box'):
            state.extractor.clear_section_box()
        return jsonify({"status": "ok", "message": "Section box disabled"})
    else:
        return jsonify({"error": "Provide min/max arrays or auto:true"}), 400

    # Apply to state and extractor
    state.section_box = section_box
    if hasattr(state.extractor, 'set_section_box'):
        state.extractor.set_section_box(section_box)

    return jsonify({
        "status": "ok",
        "section_box": section_box,
        "message": "Section box set. Run /api/reextract to apply."
    })


@app.route('/api/live_sync/toggle', methods=['POST'])
def api_live_sync_toggle():
    """Toggle live sync on/off in Revit."""
    import requests

    action = request.json.get('action', 'toggle')

    try:
        if action == 'start' or (action == 'toggle' and not state.live_sync_enabled):
            resp = requests.get("http://localhost:48884/revit_mcp/live_sync/start/", timeout=5)
            result = resp.json()
            if result.get('status') == 'ok':
                state.live_sync_enabled = True
            return jsonify(result)
        else:
            resp = requests.get("http://localhost:48884/revit_mcp/live_sync/stop/", timeout=5)
            result = resp.json()
            if result.get('status') == 'ok':
                state.live_sync_enabled = False
            return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


state.out_dir.mkdir(exist_ok=True)

def get_postprocessor():
    if state.postprocessor is None:
        state.postprocessor = ArchitecturalPostProcessor()
    return state.postprocessor


@app.route('/api/sync_revit', methods=['POST'])
def api_sync_revit():
    """Full sync from Revit: camera, section box, sun settings, then re-extract channels."""
    import requests

    sync_result = {
        "camera": None,
        "section_box": None,
        "sun": None,
        "channels_extracted": False
    }

    # 1. Sync camera - use response data directly
    cam_data = None
    try:
        resp = requests.get("http://localhost:48884/revit_mcp/export_camera/", timeout=5)
        cam_result = resp.json()
        sync_result["camera"] = cam_result.get("status", "ok")
        # Get camera data directly from response (new format)
        if cam_result.get("camera"):
            cam_data = cam_result["camera"]
        print(f"Camera synced: {cam_result.get('viewName', 'unknown')}")
    except Exception as e:
        sync_result["camera"] = f"error: {e}"

    # 2. Try to get section box
    try:
        resp = requests.get("http://localhost:48884/revit_mcp/export_section_box/", timeout=5)
        if resp.status_code == 200:
            box_data = resp.json()
            if box_data.get("status") == "ok":
                state.section_box = box_data
                sync_result["section_box"] = "synced" if box_data.get("enabled") else "disabled"
                print(f"Section box synced: enabled={box_data.get('enabled')}")
            else:
                sync_result["section_box"] = box_data.get("message", "not available")
        else:
            sync_result["section_box"] = "not available"
    except Exception as e:
        sync_result["section_box"] = f"not available: {e}"

    # 3. Try to get sun/lighting settings
    try:
        resp = requests.get("http://localhost:48884/revit_mcp/export_sun_settings/", timeout=5)
        if resp.status_code == 200:
            sun_data = resp.json()
            if sun_data.get("status") == "ok":
                state.sun_settings = sun_data
                sync_result["sun"] = "synced"
                print(f"Sun settings synced: {sun_data.get('sun', {})}")
            else:
                sync_result["sun"] = sun_data.get("message", "not available")
        else:
            sync_result["sun"] = "not available"
    except Exception as e:
        sync_result["sun"] = f"not available: {e}"

    # 4. Auto re-extract channels with new camera
    if state.extractor and sync_result["camera"] == "ok":
        try:
            # Use camera data from response, fallback to file
            cam = cam_data
            if not cam:
                json_path = Path(r"C:\Users\jerro\Desktop\channel_test\camera.json")
                if state.mesh_path:
                    alt_path = Path(state.mesh_path).parent / "camera.json"
                    if alt_path.exists():
                        json_path = alt_path
                if json_path.exists():
                    with open(json_path) as f:
                        cam = json.load(f)

            if cam:
                FEET_TO_MM = 304.8
                eye = np.array(cam["Eye"]) * FEET_TO_MM
                forward = np.array(cam["Forward"])
                forward = forward / np.linalg.norm(forward)
                up = np.array(cam.get("Up", [0, 0, 1]))
                up = up / np.linalg.norm(up)

                state.revit_camera = {
                    "Eye": eye.tolist(),
                    "Forward": forward.tolist(),
                    "Up": up.tolist(),
                    "IsPerspective": cam.get("IsPerspective", True),
                    "FieldOfView": cam.get("FieldOfView", 0.785),
                    "NearClip": 1.0,
                    "FarClip": state.size * 5 if state.size else 100000
                }

                # Update extractor with camera and section box
                state.extractor.update_camera(state.revit_camera)

                # Apply section box clipping if enabled
                if state.section_box and state.section_box.get("enabled"):
                    if hasattr(state.extractor, 'set_section_box'):
                        state.extractor.set_section_box(state.section_box)
                        print(f"Section box applied: {state.section_box.get('min')} to {state.section_box.get('max')}")
                    else:
                        print("WARNING: Extractor doesn't have set_section_box method - restart server!")
                else:
                    if hasattr(state.extractor, 'clear_section_box'):
                        state.extractor.clear_section_box()
                    print("Section box disabled or not available")

                # Extract channels with synced camera
                channels = ['depth', 'normals', 'edges', 'shadow', 'ao']
                result = state.extractor.extract(channels=channels, resolution=(960, 540))

                for ch_name, ch_img in result.items():
                    if ch_img is not None:
                        out_path = state.out_dir / f"{ch_name}.png"
                        ch_img.save(out_path)

                sync_result["channels_extracted"] = True
                print("Channels re-extracted with synced camera")

        except Exception as e:
            sync_result["channels_extracted"] = f"error: {e}"
            print(f"Channel extraction failed: {e}")

    return jsonify(sync_result)


@app.route('/api/reextract', methods=['POST'])
def api_reextract():
    """Re-extract channels with current camera (no Revit sync needed)."""
    if not state.revit_camera:
        return jsonify({"error": "No camera data. Sync from Revit first."}), 400

    # Reload mesh if extractor was destroyed (happens after AI enhancement)
    if not state.extractor:
        if state.mesh_path:
            print("Reloading mesh for channel extraction...")
            # Unload AI to free GPU
            if state.enhancer is not None:
                state.enhancer = None
                import torch
                import gc
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

            load_mesh(state.mesh_path)
        else:
            return jsonify({"error": "No mesh loaded. Load a mesh first."}), 400

    t0 = time.time()

    try:
        # Update extractor with current camera
        state.extractor.update_camera(state.revit_camera)

        # Re-extract all channels with current settings
        channels = ['depth', 'normals', 'edges', 'shadow', 'ao']
        state.extractor.extract_all(str(state.out_dir), (960, 540), channels)

        return jsonify({
            "status": "ok",
            "channels": channels,
            "time": time.time() - t0
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/near_clip_offset', methods=['POST'])
def api_near_clip_offset():
    """
    Set near clip offset to skip through geometry near camera.
    Useful for interior views where exterior walls block the view.

    POST body: {"offset_mm": 1000}  (e.g., 1000mm = 1 meter)
    """
    if not state.extractor:
        return jsonify({"error": "No mesh loaded"}), 400

    data = request.json or {}
    offset = float(data.get('offset_mm', 0))

    if hasattr(state.extractor, 'set_near_clip_offset'):
        state.extractor.set_near_clip_offset(offset)
        return jsonify({
            "status": "ok",
            "offset_mm": offset,
            "message": f"Near clip offset set to {offset}mm. Re-extract to apply."
        })
    else:
        return jsonify({"error": "Extractor doesn't support near clip offset"}), 400


@app.route('/api/camera', methods=['GET'])
def api_camera():
    import requests

    # Try to trigger Revit export
    try:
        resp = requests.get("http://localhost:48884/revit_mcp/export_camera/", timeout=5)
        result = resp.json()
        print(f"Revit export: {result}")
    except Exception as e:
        print(f"Revit not available: {e}")
    
    # Load camera.json
    json_path = Path(r"C:\Users\jerro\Desktop\channel_test\camera.json")
    
    if state.mesh_path:
        alt_path = Path(state.mesh_path).parent / "camera.json"
        if alt_path.exists():
            json_path = alt_path
    
    if json_path.exists():
        with open(json_path) as f:
            cam = json.load(f)
        
        # Convert feet to mm
        FEET_TO_MM = 304.8
        
        eye = np.array(cam["Eye"]) * FEET_TO_MM
        forward = np.array(cam["Forward"])
        forward = forward / np.linalg.norm(forward)
        up = np.array(cam.get("Up", [0, 0, 1]))
        up = up / np.linalg.norm(up)
        
        # Store the ACTUAL Revit camera for direct use
        state.revit_camera = {
            "Eye": eye.tolist(),
            "Forward": forward.tolist(),
            "Up": up.tolist(),
            "IsPerspective": cam.get("IsPerspective", True),
            "FieldOfView": cam.get("FieldOfView", 0.785),
            "NearClip": 1.0,
            "FarClip": state.size * 5 if state.size else 100000
        }
        
        # Also compute spherical for UI sliders
        az = float(np.degrees(np.arctan2(-forward[0], forward[1])) % 360)
        el = float(np.degrees(np.arcsin(np.clip(-forward[2], -1, 1))))
        
        if state.center is not None:
            dist_to_center = np.linalg.norm(eye - state.center)
            distance = dist_to_center / state.size
        else:
            distance = 1.5
        
        print(f"Revit camera stored: eye={eye}, forward={forward}")
        print(f"UI: az={az:.1f}°, el={el:.1f}°, dist={distance:.2f}x")
        
        return jsonify({
            "status": "ok",
            "azimuth": az,
            "elevation": el,
            "distance": distance,
            "viewName": cam.get("ViewName", "Unknown"),
            "timestamp": cam.get("Timestamp", ""),
            "useRevitDirect": True  # Tell UI we have direct camera
        })
    
    return jsonify({"error": "No camera.json found"}), 404


@app.route('/api/extract', methods=['POST'])
def api_extract():
    if state.extractor is None:
        if state.mesh_path:
            load_mesh(state.mesh_path)
        else:
            return jsonify({"error": "No mesh loaded"}), 400
    
    data = request.json
    channels = data.get('channels', ['depth'])
    resolution = tuple(data.get('resolution', [960, 540]))
    use_revit_camera = data.get('useRevitCamera', False)
    
    t0 = time.time()
    
    # Use Revit camera directly if available and requested
    if use_revit_camera and state.revit_camera:
        print("Using Revit camera directly")
        camera = state.revit_camera
    else:
        azimuth = data.get('azimuth', 45)
        elevation = data.get('elevation', 25)
        distance = data.get('distance', 1.5)
        camera = get_camera(azimuth, elevation, distance)
    
    state.extractor.update_camera(camera)
    state.extractor.extract_all(str(state.out_dir), resolution, channels)
    
    elapsed = time.time() - t0
    
    results = {}
    for ch in channels:
        p = state.out_dir / f"{ch}.png"
        if p.exists():
            with open(p, 'rb') as f:
                results[ch] = base64.b64encode(f.read()).decode('utf-8')
    
    return jsonify({
        "status": "ok",
        "time": elapsed,
        "channels": results
    })


def load_mesh(path):
    print(f"Loading: {path}")
    t0 = time.time()
    
    state.mesh = trimesh.load(path)
    if hasattr(state.mesh, 'to_geometry'):
        state.mesh = state.mesh.to_geometry()
    
    state.mesh_path = path
    state.center = state.mesh.centroid
    state.bounds = state.mesh.bounds
    state.size = np.linalg.norm(state.bounds[1] - state.bounds[0])
    
    camera = get_camera(45, 25, 1.5)

    # Initialize channel extractor (requires Warp GPU acceleration)
    if WARP_AVAILABLE and WarpChannelExtractor is not None:
        state.extractor = WarpChannelExtractor(path, camera, state.bounds.flatten())
        # Pre-compile
        state.extractor.extract_all(str(state.out_dir), (240, 135), ["depth"])
    else:
        state.extractor = None
        print("[WARN] Channel extraction disabled (Warp not available)")
    
    elapsed = time.time() - t0
    print(f"Loaded in {elapsed:.2f}s")
    return elapsed


def get_camera(azimuth, elevation, distance):
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


def get_enhancer():
    """Lazy load the AI enhancer - completely free GPU first."""
    if state.enhancer is None:
        print("Freeing GPU memory for AI...")
        import torch
        import gc
        
        # Completely destroy the extractor
        if state.extractor is not None:
            state.extractor = None
        
        # Force Warp cleanup
        wp.synchronize()
        
        # Multiple rounds of cleanup
        for _ in range(3):
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        
        print("Loading AI enhancer...")
        from ai_enhancer import ChannelEnhancer
        state.enhancer = ChannelEnhancer()
        print("Enhancer ready!")
    return state.enhancer


@app.route('/')
def index():
    return send_file('render_ui.html')

@app.route('/api/debug/routes')
def debug_routes():
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'endpoint': rule.endpoint,
            'methods': list(rule.methods),
            'rule': rule.rule
        })
    return jsonify(sorted(routes, key=lambda x: x['rule']))

@app.route('/api/extract_from_image', methods=['POST'])
def api_extract_from_image():
    """
    Extract channels (depth, normals, edges, AO, shadow) from a 2D image using AI.
    No mesh required - works with any screenshot or render.

    POST body (JSON):
        channels: list of channels to extract (default: all)

    Or POST with multipart/form-data:
        file: image file to extract from
        channels: comma-separated list (optional)

    If no file provided, uses the existing base.png
    """
    from image_channels import get_image_extractor

    t0 = time.time()

    try:
        # Get image - either from upload or existing base
        if request.files and 'file' in request.files:
            file = request.files['file']
            img = Image.open(file.stream).convert('RGB')
            # Also save as base
            base_path = state.out_dir / "base.png"
            img.save(base_path, 'PNG')
            print(f"Using uploaded image: {file.filename}")
        else:
            base_path = state.out_dir / "base.png"
            if not base_path.exists():
                return jsonify({"error": "No base image. Upload an image first."}), 400
            img = Image.open(base_path).convert('RGB')
            print("Using existing base.png")

        # Get channels to extract
        if request.is_json:
            data = request.json or {}
            channels = data.get('channels', ['depth', 'normals', 'edges', 'ao', 'shadow'])
        else:
            channels_str = request.form.get('channels', '')
            if channels_str:
                channels = [c.strip() for c in channels_str.split(',')]
            else:
                channels = ['depth', 'normals', 'edges', 'ao', 'shadow']

        # Free GPU if AI enhancer is loaded
        if state.enhancer is not None:
            print("Freeing AI enhancer for depth estimation...")
            state.enhancer = None
            import gc
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        # Extract channels
        extractor = get_image_extractor()
        results = extractor.extract_all(img, str(state.out_dir), channels)

        # Build response with base64 images
        channel_data = {}
        for ch_name in results:
            ch_path = state.out_dir / f"{ch_name}.png"
            if ch_path.exists():
                with open(ch_path, 'rb') as f:
                    channel_data[ch_name] = base64.b64encode(f.read()).decode('utf-8')

        return jsonify({
            "status": "ok",
            "channels": list(results.keys()),
            "time": time.time() - t0,
            "images": channel_data
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/upload_base', methods=['POST'])
def api_upload_base():
    """Upload a base image for AI enhancement."""
    try:
        if not request.files:
            return jsonify({"error": "No files in request"}), 400
        
        file = request.files.get('file')
        if not file or not file.filename:
            return jsonify({"error": "No file selected"}), 400
        
        # Load image
        img = Image.open(file.stream).convert('RGB')
        
        # Save as base.png
        base_path = state.out_dir / "base.png"
        img.save(base_path, 'PNG')
        
        print(f"Base image saved: {base_path} ({img.size})")
        
        # Return as base64
        with open(base_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')
        
        return jsonify({
            "status": "ok",
            "size": list(img.size),
            "image": b64
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/crop_base', methods=['POST'])
def api_crop_base():
    """Crop the base image to focus on a region. Uses percentages (0-100)."""
    try:
        data = request.json or {}
        left_pct = data.get('left', 0)
        top_pct = data.get('top', 0)
        right_pct = data.get('right', 100)
        bottom_pct = data.get('bottom', 100)

        # Load base image
        base_path = state.out_dir / "base.png"
        if not base_path.exists():
            return jsonify({"error": "No base image to crop"}), 404

        img = Image.open(base_path).convert('RGB')
        w, h = img.size

        # Convert percentages to pixels
        left = int(w * left_pct / 100)
        top = int(h * top_pct / 100)
        right = int(w * right_pct / 100)
        bottom = int(h * bottom_pct / 100)

        # Validate
        if left >= right or top >= bottom:
            return jsonify({"error": "Invalid crop region"}), 400

        # Crop
        cropped = img.crop((left, top, right, bottom))
        cropped.save(base_path, 'PNG')

        print(f"Cropped base image: {img.size} -> {cropped.size}")

        # Return as base64
        with open(base_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('utf-8')

        return jsonify({
            "status": "ok",
            "size": list(cropped.size),
            "original_size": list(img.size),
            "image": b64
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def clear_gpu_for_ai():
    """Free GPU memory before loading AI models."""
    import torch
    import gc
    
    print("Clearing GPU for AI...")
    state.extractor = None
    wp.synchronize()
    
    for _ in range(3):
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()

# Upscaler is now loaded per-request with get_upscaler(type) from upscaler.py
# This allows choosing between realesrgan, ultra, sd, or simple modes

# Replace the postprocess endpoint
@app.route('/api/postprocess', methods=['POST'])
def api_postprocess():
    """Apply post-processing effects."""
    data = request.json or {}
    
    # Get preset or individual settings
    preset_name = data.get('preset', 'none')
    preset = POSTPROCESS_PRESETS.get(preset_name, {}).copy()
    
    # Override with any individual settings
    for key in ['exposure', 'contrast', 'saturation', 'temperature', 'vibrance',
                'bloom_intensity', 'bloom_threshold', 'vignette', 'grain', 'sharpness',
                'ao_strength', 'edge_darkening', 'shadow_boost', 'depth_fog', 'dof_amount', 'dof_focus']:
        if key in data:
            preset[key] = data[key]
    
    # Get image to process - always use original, not already-processed
    # Priority: enhanced_original (preserved AI result) > enhanced > base
    input_path = state.out_dir / "enhanced_original.png"
    if not input_path.exists():
        input_path = state.out_dir / "enhanced.png"
        # If enhanced exists but original doesn't, create the backup now
        if input_path.exists():
            import shutil
            shutil.copy(input_path, state.out_dir / "enhanced_original.png")
            input_path = state.out_dir / "enhanced_original.png"
    if not input_path.exists():
        input_path = state.out_dir / "base.png"

    if not input_path.exists():
        return jsonify({"error": "No image to process"}), 400
    
    t0 = time.time()
    
    try:
        pp = get_postprocessor()
        
        # Load image and channels
        img = Image.open(input_path).convert('RGB')
        
        depth = None
        edges = None
        shadow = None
        ao = None
        
        depth_path = state.out_dir / "depth.png"
        if depth_path.exists():
            depth = Image.open(depth_path)
        
        edges_path = state.out_dir / "edges.png"
        if edges_path.exists():
            edges = Image.open(edges_path)
        
        shadow_path = state.out_dir / "shadow.png"
        if shadow_path.exists():
            shadow = Image.open(shadow_path)
        
        ao_path = state.out_dir / "ao.png"
        if ao_path.exists():
            ao = Image.open(ao_path)
        
        # Process
        result = pp.process(
            image=img,
            depth=depth,
            edges=edges,
            shadow=shadow,
            ao=ao,
            **preset
        )
        
        # Save
        output_path = state.out_dir / "postprocessed.png"
        result.save(output_path)
        
        # Also update enhanced for upscaling
        result.save(state.out_dir / "enhanced.png")
        
        with open(output_path, 'rb') as f:
            result_b64 = base64.b64encode(f.read()).decode('utf-8')
        
        return jsonify({
            "status": "ok",
            "time": time.time() - t0,
            "image": result_b64,
            "preset": preset_name
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/postprocess_both_regions', methods=['POST'])
def api_postprocess_both_regions():
    """
    Apply post-processing to both regions from the original image.

    This recomputes the result fresh each time, so sliders represent
    absolute values relative to the original, not stacked deltas.

    POST body:
        feather: Edge feathering in pixels
        environment: {exposure, contrast, saturation, temperature, sharpness}
        building: {exposure, contrast, saturation, temperature, sharpness}
    """
    data = request.json or {}

    feather = int(data.get('feather', 10))
    env_settings = data.get('environment', {})
    bld_settings = data.get('building', {})

    # Find the mask
    mask_path = state.out_dir / "ai_mask.png"
    if not mask_path.exists():
        mask_path = state.out_dir / "element_mask.png"
    if not mask_path.exists():
        return jsonify({"error": "No mask available. Generate an AI mask first."}), 400

    # Get ORIGINAL image - always start fresh
    original_path = state.out_dir / "enhanced_original.png"
    if not original_path.exists():
        original_path = state.out_dir / "enhanced.png"
    if not original_path.exists():
        original_path = state.out_dir / "base.png"

    if not original_path.exists():
        return jsonify({"error": "No image to process"}), 400

    t0 = time.time()

    try:
        pp = get_postprocessor()

        img = Image.open(original_path).convert('RGB')
        mask = Image.open(mask_path).convert('L')

        # Check if environment has any non-zero settings
        env_has_effects = any(env_settings.get(k, 0) != 0 for k in ['exposure', 'contrast', 'saturation', 'temperature', 'sharpness'])

        # Check if building has any non-zero settings
        bld_has_effects = any(bld_settings.get(k, 0) != 0 for k in ['exposure', 'contrast', 'saturation', 'temperature', 'sharpness'])

        result = img

        # Apply environment effects (mask as-is: white = environment)
        if env_has_effects:
            result = pp.process_masked(
                image=result,
                mask=mask,
                invert_mask=False,  # white = environment
                feather=feather,
                exposure=float(env_settings.get('exposure', 0)),
                contrast=float(env_settings.get('contrast', 0)),
                saturation=float(env_settings.get('saturation', 0)),
                temperature=float(env_settings.get('temperature', 0)),
                sharpness=float(env_settings.get('sharpness', 0))
            )

        # Apply building effects (invert mask: black becomes white = building)
        if bld_has_effects:
            result = pp.process_masked(
                image=result,
                mask=mask,
                invert_mask=True,  # black = building
                feather=feather,
                exposure=float(bld_settings.get('exposure', 0)),
                contrast=float(bld_settings.get('contrast', 0)),
                saturation=float(bld_settings.get('saturation', 0)),
                temperature=float(bld_settings.get('temperature', 0)),
                sharpness=float(bld_settings.get('sharpness', 0))
            )

        # Save
        output_path = state.out_dir / "postprocessed.png"
        result.save(output_path)
        result.save(state.out_dir / "enhanced.png")

        # Return as base64
        buffer = io.BytesIO()
        result.save(buffer, format='PNG')
        result_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

        return jsonify({
            "status": "ok",
            "time": time.time() - t0,
            "image": result_b64
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/reset_postprocess', methods=['POST'])
def api_reset_postprocess():
    """Reset postprocessed image back to original enhanced result."""
    import shutil

    # Find the original
    original_path = state.out_dir / "enhanced_original.png"
    if not original_path.exists():
        original_path = state.out_dir / "enhanced.png"
    if not original_path.exists():
        original_path = state.out_dir / "base.png"

    if not original_path.exists():
        return jsonify({"error": "No original image found"}), 400

    try:
        # Copy original to postprocessed and enhanced
        img = Image.open(original_path)
        img.save(state.out_dir / "postprocessed.png")
        img.save(state.out_dir / "enhanced.png")

        with open(original_path, 'rb') as f:
            result_b64 = base64.b64encode(f.read()).decode('utf-8')

        return jsonify({
            "status": "ok",
            "image": result_b64
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/postprocess_masked', methods=['POST'])
def api_postprocess_masked():
    """
    Apply post-processing only to a specific region (building or environment).

    Uses the AI-generated mask to selectively apply effects.

    POST body:
        region: "building" or "environment" - which area to affect
        feather: Edge feathering in pixels (default 10)
        preset: Optional preset name (subtle, vivid, warm, cool, dramatic, etc.)
        ...individual settings (exposure, contrast, saturation, temperature, etc.)
    """
    data = request.json or {}

    region = data.get('region', 'environment')  # 'building' or 'environment'
    feather = int(data.get('feather', 10))

    # Get preset or individual settings
    preset_name = data.get('preset', 'none')
    settings = POSTPROCESS_PRESETS.get(preset_name, {}).copy()

    # Override with any individual settings
    for key in ['exposure', 'contrast', 'saturation', 'temperature', 'vibrance',
                'bloom_intensity', 'bloom_threshold', 'vignette', 'grain', 'sharpness',
                'ao_strength', 'edge_darkening', 'shadow_boost', 'depth_fog', 'dof_amount', 'dof_focus']:
        if key in data:
            settings[key] = float(data[key])

    # Find the mask
    mask_path = state.out_dir / "ai_mask.png"
    if not mask_path.exists():
        mask_path = state.out_dir / "element_mask.png"
    if not mask_path.exists():
        return jsonify({"error": "No mask available. Generate an AI mask first."}), 400

    # Get image to process - use CURRENT result so effects can stack
    # Priority: postprocessed (current working image) > enhanced > base
    input_path = state.out_dir / "postprocessed.png"
    if not input_path.exists():
        input_path = state.out_dir / "enhanced.png"
    if not input_path.exists():
        input_path = state.out_dir / "base.png"

    if not input_path.exists():
        return jsonify({"error": "No image to process"}), 400

    t0 = time.time()

    try:
        pp = get_postprocessor()

        img = Image.open(input_path).convert('RGB')
        mask = Image.open(mask_path).convert('L')

        # Determine if we should invert the mask
        # Our masks are typically: white = environment (to be inpainted), black = building
        # For "environment" region: use mask as-is (white = affected)
        # For "building" region: invert mask (black becomes white = affected)
        invert = (region == 'building')

        print(f"Masked post-process: region={region}, invert={invert}, feather={feather}")
        print(f"  Settings: {settings}")

        # Apply masked processing
        result = pp.process_masked(
            image=img,
            mask=mask,
            invert_mask=invert,
            feather=feather,
            **settings
        )

        # Save
        output_path = state.out_dir / "postprocessed.png"
        result.save(output_path)
        result.save(state.out_dir / "enhanced.png")

        with open(output_path, 'rb') as f:
            result_b64 = base64.b64encode(f.read()).decode('utf-8')

        return jsonify({
            "status": "ok",
            "time": time.time() - t0,
            "image": result_b64,
            "region": region,
            "preset": preset_name
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/upscale', methods=['POST'])
def api_upscale():
    """
    4x upscale an image.

    Options:
        upscaler: "realesrgan" (fast), "ultra" (slow, max quality), "sd" (creative), "simple"
        source: "auto" (default), "base", "enhanced", or "postprocessed" - which image to upscale
        prompt: Text prompt for SD/ultra modes
        num_passes: For ultra mode, 1-3 refinement passes (default 2)
        refinement_strength: For ultra mode, 0.15-0.35 (default 0.25)
        refinement_steps: For ultra mode, 20-50 (default 30)
        return_path: If true, return file path instead of base64 (faster for large images)
    """
    from upscaler import get_upscaler

    data = request.json or {}
    upscaler_type = data.get('upscaler', 'realesrgan')
    source = data.get('source', 'auto')
    prompt = data.get('prompt', 'highly detailed architectural visualization, photorealistic, sharp details, professional photography')
    return_path = data.get('return_path', False)

    # Determine input image based on source preference
    if source == 'base':
        input_path = state.out_dir / "base.png"
    elif source == 'enhanced':
        input_path = state.out_dir / "enhanced.png"
    elif source == 'postprocessed':
        input_path = state.out_dir / "postprocessed.png"
    else:  # auto - try enhanced first, then postprocessed, then base
        input_path = state.out_dir / "enhanced.png"
        if not input_path.exists():
            input_path = state.out_dir / "postprocessed.png"
        if not input_path.exists():
            input_path = state.out_dir / "base.png"

    if not input_path.exists():
        return jsonify({"error": "No image to upscale. Upload a base image first."}), 400

    print(f"Upscaling from: {input_path.name}")

    t0 = time.time()
    print(f"\n=== Upscaling with {upscaler_type} ===")

    try:
        upscaler = get_upscaler(upscaler_type)
        output_path = state.out_dir / "upscaled.png"

        # Build kwargs for different upscaler types
        kwargs = {"prompt": prompt}

        if upscaler_type == "ultra":
            # Pass depth map for better structure preservation
            depth_path = state.out_dir / "depth.png"
            if depth_path.exists():
                kwargs["depth_path"] = str(depth_path)

            kwargs["num_passes"] = data.get('num_passes', 2)
            kwargs["refinement_strength"] = data.get('refinement_strength', 0.25)
            kwargs["refinement_steps"] = data.get('refinement_steps', 30)
            kwargs["tile_size"] = data.get('tile_size', 768)

        upscaler.upscale(str(input_path), str(output_path), **kwargs)

        elapsed = time.time() - t0
        print(f"Upscale complete in {elapsed:.1f}s")

        # Return path or base64
        if return_path:
            return jsonify({
                "status": "ok",
                "time": elapsed,
                "upscaler": upscaler_type,
                "path": str(output_path),
                "url": "/channel/upscaled"
            })
        else:
            with open(output_path, 'rb') as f:
                result_b64 = base64.b64encode(f.read()).decode('utf-8')

            return jsonify({
                "status": "ok",
                "time": elapsed,
                "upscaler": upscaler_type,
                "image": result_b64
            })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
@app.route('/api/load', methods=['POST'])
def api_load():
    try:
        # Check for file upload FIRST (before any JSON checks)
        if request.files:
            file = request.files.get('file')
            if file and file.filename:
                temp_path = state.out_dir / file.filename
                file.save(temp_path)
                elapsed = load_mesh(str(temp_path))
                return jsonify({
                    "status": "ok",
                    "time": elapsed,
                    "name": file.filename,
                    "triangles": len(state.mesh.faces)
                })
        
        # Then check for JSON body
        data = request.get_json(silent=True) or {}
        path = data.get('path')
        
        if path:
            if not Path(path).exists():
                return jsonify({"error": f"File not found: {path}"}), 400
            
            elapsed = load_mesh(path)
            return jsonify({
                "status": "ok",
                "time": elapsed,
                "name": Path(path).name,
                "triangles": len(state.mesh.faces)
            })
        
        return jsonify({"error": "No file or path provided"}), 400
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/api/load_base_from_folder', methods=['POST'])
def api_load_base_from_folder():
    """Try to find and load a render image from the mesh folder."""
    if state.mesh_path is None:
        return jsonify({"error": "No mesh loaded"}), 400
    
    mesh_folder = Path(state.mesh_path).parent
    
    # Look for common render file names
    candidates = [
        "render.png", "render.jpg",
        "base.png", "base.jpg", 
        "view.png", "view.jpg",
        Path(state.mesh_path).stem + ".png",
        Path(state.mesh_path).stem + ".jpg",
    ]
    
    for name in candidates:
        img_path = mesh_folder / name
        if img_path.exists():
            img = Image.open(img_path).convert('RGB')
            
            # Save as base.png
            base_path = state.out_dir / "base.png"
            img.save(base_path, 'PNG')
            
            with open(base_path, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('utf-8')
            
            return jsonify({
                "status": "ok",
                "name": name,
                "size": img.size,
                "image": b64
            })
    
    return jsonify({"error": f"No render found in {mesh_folder}"}), 404


@app.route('/api/debug_camera', methods=['GET'])
def api_debug_camera():
    if state.center is None:
        return jsonify({"error": "No mesh loaded"})
    
    with open(r"C:\Users\jerro\Desktop\channel_test\camera.json") as f:
        cam = json.load(f)
    
    eye = np.array(cam["Eye"])
    forward = np.array(cam["Forward"])
    
    # Where is Revit looking? (eye + forward * some_distance)
    look_at = eye + forward * 50  # 50 feet ahead
    
    return jsonify({
        "mesh_center": state.center.tolist(),
        "mesh_bounds": state.bounds.tolist(),
        "revit_eye": eye.tolist(),
        "revit_forward": forward.tolist(),
        "revit_look_at": look_at.tolist(),
        "distance_eye_to_center": float(np.linalg.norm(eye - state.center))
    })
@app.route('/api/enhance', methods=['POST'])
def api_enhance():
    data = request.json

    prompt = data.get('prompt', 'architectural visualization, photorealistic')
    negative = data.get('negative', 'blurry, distorted, ugly, deformed')
    strength = float(data.get('strength', 0.8))
    controlnet_strength = float(data.get('controlnet_strength', 1.0))  # Structure preservation
    guidance = float(data.get('guidance', 7.5))
    use_depth = data.get('use_depth', True)
    use_normals = data.get('use_normals', False)
    use_edges = data.get('use_edges', False)
    use_segmentation = data.get('use_segmentation', False)
    
    # Get base image
    base_path = state.out_dir / "base.png"
    if not base_path.exists():
        base_path = state.out_dir / "depth.png"
    
    if not base_path.exists():
        return jsonify({"error": "No base image. Extract channels or upload first."}), 400

    # Save to history before enhancement
    history_save("Before AI Enhance")

    t0 = time.time()

    try:
        enhancer = get_enhancer()
        
        base_img = Image.open(base_path).convert('RGB')
        w, h = base_img.size
        
        aspect = w / h
        if aspect > 1:
            new_w = 512
            new_h = (int(512 / aspect) // 8) * 8
        else:
            new_h = 512
            new_w = (int(512 * aspect) // 8) * 8
        new_h = max(new_h, 64)
        new_w = max(new_w, 64)
        
        # Get channel paths
        depth_path = state.out_dir / "depth.png" if use_depth else None
        edges_path = state.out_dir / "edges.png" if use_edges else None
        normals_path = state.out_dir / "normals.png" if use_normals else None
        seg_path = state.out_dir / "object_id.png" if use_segmentation else None
        
        result = enhancer.enhance(
            base_path=str(base_path),
            depth_path=str(depth_path) if depth_path and depth_path.exists() else None,
            edges_path=str(edges_path) if edges_path and edges_path.exists() else None,
            normals_path=str(normals_path) if normals_path and normals_path.exists() else None,
            segmentation_path=str(seg_path) if seg_path and seg_path.exists() else None,
            prompt=prompt,
            negative_prompt=negative,
            num_inference_steps=25,
            guidance_scale=guidance,
            controlnet_conditioning_scale=controlnet_strength,
            strength=strength,
            width=new_w,
            height=new_h
        )
        
        result = result.resize((w, h), Image.Resampling.LANCZOS)
        
        output_path = state.out_dir / "enhanced.png"
        result.save(output_path)

        # Save original for post-processing (so adjustments don't stack)
        original_path = state.out_dir / "enhanced_original.png"
        result.save(original_path)

        with open(output_path, 'rb') as f:
            result_b64 = base64.b64encode(f.read()).decode('utf-8')

        return jsonify({
            "status": "ok",
            "time": time.time() - t0,
            "image": result_b64
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/enhance_selective', methods=['POST'])
def api_enhance_selective():
    """Selective enhancement: strict on building, creative on environment."""
    data = request.json

    prompt_building = data.get('prompt_building', 'architectural photography, photorealistic building, detailed materials')
    prompt_environment = data.get('prompt_environment', 'beautiful sky, lush green landscaping, professional photography')
    negative_prompt = data.get('negative', 'blurry, distorted, ugly, deformed')
    building_strength = data.get('building_strength', 0.25)
    environment_strength = data.get('environment_strength', 0.6)
    building_controlnet = data.get('building_controlnet', 1.0)
    environment_controlnet = data.get('environment_controlnet', 0.3)
    depth_threshold = data.get('depth_threshold', 0.7)
    guidance = data.get('guidance', 7.5)

    # Get base image
    base_path = state.out_dir / "base.png"
    if not base_path.exists():
        return jsonify({"error": "No base image. Upload first."}), 400

    depth_path = state.out_dir / "depth.png"
    if not depth_path.exists():
        return jsonify({"error": "No depth channel. Extract channels first."}), 400

    # Save to history before enhancement
    history_save("Before Selective Enhance")

    t0 = time.time()

    try:
        enhancer = get_enhancer()

        base_img = Image.open(base_path).convert('RGB')
        w, h = base_img.size

        aspect = w / h
        if aspect > 1:
            new_w = 512
            new_h = (int(512 / aspect) // 8) * 8
        else:
            new_h = 512
            new_w = (int(512 * aspect) // 8) * 8
        new_h = max(new_h, 64)
        new_w = max(new_w, 64)

        result = enhancer.enhance_selective(
            base_path=str(base_path),
            depth_path=str(depth_path),
            prompt_building=prompt_building,
            prompt_environment=prompt_environment,
            negative_prompt=negative_prompt,
            building_strength=building_strength,
            environment_strength=environment_strength,
            building_controlnet=building_controlnet,
            environment_controlnet=environment_controlnet,
            depth_threshold=depth_threshold,
            guidance_scale=guidance,
            width=new_w,
            height=new_h
        )

        result = result.resize((w, h), Image.Resampling.LANCZOS)

        output_path = state.out_dir / "enhanced.png"
        result.save(output_path)

        # Save original for post-processing
        original_path = state.out_dir / "enhanced_original.png"
        result.save(original_path)

        with open(output_path, 'rb') as f:
            result_b64 = base64.b64encode(f.read()).decode('utf-8')

        return jsonify({
            "status": "ok",
            "time": time.time() - t0,
            "image": result_b64
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/inpaint_environment', methods=['POST'])
def api_inpaint_environment():
    """
    Generate environment around building using inpainting.

    The building stays 100% UNTOUCHED - only sky, landscape, context are generated.
    Uses depth map to auto-mask building vs environment.

    POST body:
        prompt: What environment to generate (e.g., "blue sky, green lawn, trees")
        negative_prompt: What to avoid
        threshold: Depth threshold for building detection (0-1, default 0.3)
        expand_pixels: Safety margin around building (default 10)
        feather: Mask edge blur (default 15)
        steps: Inference steps (default 30)
        guidance: Prompt guidance (default 7.5)
        model: "sd15" (faster) or "sdxl" (higher quality)
        seed: Random seed (optional)
        style_preset: Architectural style preset (default, sunny, overcast, dusk, minimal)
        harmonize: Enable color/style harmonization (default True)
        harmonize_color: Color harmonization strength (0-1, default 0.5)
        harmonize_style: Render style strength (0-1, default 0.3)
        edge_blend: Edge blend width in pixels (default 25)
    """
    from render.enhance.inpainting import get_inpainter
    from render.enhance.style_harmonizer import full_harmonization, get_arch_prompt

    data = request.json or {}

    # Style preset - use architectural rendering prompts by default
    style_preset = data.get('style_preset', 'default')
    default_prompt, default_negative = get_arch_prompt(style_preset)

    prompt = data.get('prompt', default_prompt)
    negative_prompt = data.get('negative_prompt', default_negative)
    threshold = float(data.get('threshold', 0.3))
    expand_pixels = int(data.get('expand_pixels', 10))
    feather = int(data.get('feather', 15))
    steps = int(data.get('steps', 30))
    guidance = float(data.get('guidance', 7.5))
    model_type = data.get('model', 'sd15')
    seed = data.get('seed', None)
    use_ai_mask = data.get('use_ai_mask', False)  # Use pre-generated AI mask instead of depth-based

    # Style harmonization options (match generated to render style)
    harmonize = data.get('harmonize', True)
    harmonize_color = float(data.get('harmonize_color', 0.5))
    harmonize_style = float(data.get('harmonize_style', 0.3))
    edge_blend = int(data.get('edge_blend', 25))

    # Get base image and depth
    base_path = state.out_dir / "base.png"
    if not base_path.exists():
        return jsonify({"error": "No base image. Upload first."}), 400

    # Check for AI mask or depth
    ai_mask_path = state.out_dir / "ai_mask.png"
    element_mask_path = state.out_dir / "element_mask.png"
    depth_path = state.out_dir / "depth.png"

    has_ai_mask = ai_mask_path.exists() or element_mask_path.exists()

    if not has_ai_mask and not depth_path.exists():
        return jsonify({"error": "No mask available. Generate an AI mask or extract depth from your image."}), 400

    # Save to history before inpainting
    history_save("Before Environment Inpaint")

    t0 = time.time()

    try:
        # Free other AI models to make room
        if state.enhancer is not None:
            print("Freeing AI enhancer for inpainting...")
            state.enhancer = None
            import gc
            gc.collect()
            torch.cuda.empty_cache()

        # Load base image
        base_img = Image.open(base_path).convert('RGB')

        # Check if we should use pre-generated AI mask
        existing_mask = None
        if use_ai_mask or has_ai_mask:
            mask_to_use = ai_mask_path if ai_mask_path.exists() else element_mask_path
            if mask_to_use.exists():
                print(f"Using pre-generated AI mask: {mask_to_use.name}")
                existing_mask = Image.open(mask_to_use).convert('L')
                # Resize to match base image if needed
                if existing_mask.size != base_img.size:
                    existing_mask = existing_mask.resize(base_img.size, Image.Resampling.LANCZOS)

        # Load depth if available (for fallback or if no AI mask)
        depth_img = None
        if depth_path.exists():
            depth_img = Image.open(depth_path).convert('L')

        print(f"Inpainting environment: model={model_type}, using_ai_mask={existing_mask is not None}")
        print(f"  Prompt: {prompt[:60]}...")

        # Get inpainter
        inpainter = get_inpainter(model_type)

        # Generate environment (returns tuple: result_image, mask_image)
        if existing_mask is not None:
            # Use the pre-generated mask directly
            result_img = inpainter.inpaint(
                image=base_img,
                mask=existing_mask,
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=steps,
                guidance_scale=guidance,
                seed=seed
            )
            mask_img = existing_mask  # Use the AI-generated mask for display
        else:
            # Fall back to depth-based mask generation
            if depth_img is None:
                return jsonify({"error": "No depth available for mask generation"}), 400

            result_img, mask_img = inpainter.inpaint_environment(
                image=base_img,
                depth=depth_img,
                prompt=prompt,
                negative_prompt=negative_prompt,
                threshold=threshold,
                expand_pixels=expand_pixels,
                feather=feather,
                num_inference_steps=steps,
                guidance_scale=guidance,
                seed=seed
            )

        # Apply style harmonization to match generated area to render style
        if harmonize and (harmonize_color > 0 or harmonize_style > 0 or edge_blend > 0):
            print(f"Applying style harmonization (color={harmonize_color}, style={harmonize_style}, edge={edge_blend}px)...")
            result_img = full_harmonization(
                result=result_img,
                base=base_img,
                mask=mask_img,
                color_strength=harmonize_color,
                style_strength=harmonize_style,
                edge_blend_width=edge_blend
            )
            print("Style harmonization applied")

        # Save results
        output_path = state.out_dir / "enhanced.png"
        result_img.save(output_path)

        # Save mask for debugging
        mask_path = state.out_dir / "inpaint_mask.png"
        mask_img.save(mask_path)

        # Save original for post-processing
        original_path = state.out_dir / "enhanced_original.png"
        result_img.save(original_path)

        elapsed = time.time() - t0
        print(f"Environment generation complete in {elapsed:.1f}s")

        # Return URL instead of base64 for large images
        return jsonify({
            "status": "ok",
            "time": elapsed,
            "model": model_type,
            "url": "/channel/enhanced",
            "mask_url": "/channel/inpaint_mask",
            "path": str(output_path)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/channel/<name>')
def get_channel(name):
    p = state.out_dir / f"{name}.png"
    if p.exists():
        # Check if download is requested
        if request.args.get('download'):
            return send_file(p, mimetype='image/png', as_attachment=True,
                           download_name=f"{name}_{time.strftime('%Y%m%d_%H%M%S')}.png")
        return send_file(p, mimetype='image/png')
    return "Not found", 404


# ============================================================
# IFC SUPPORT - Element-level selection for AI enhancement
# ============================================================

@app.route('/api/ifc/load', methods=['POST'])
def api_ifc_load():
    """
    Load an IFC file for element selection.

    POST body:
        path: Path to IFC file
    Or upload via multipart form
    """
    if not IFC_AVAILABLE:
        return jsonify({"error": "IFC support not available. Install ifcopenshell."}), 400

    try:
        # Handle file upload or path
        if request.files and 'file' in request.files:
            file = request.files['file']
            ifc_path = state.out_dir / file.filename
            file.save(ifc_path)
            ifc_path = str(ifc_path)
        else:
            data = request.json or {}
            ifc_path = data.get('path')

        if not ifc_path or not Path(ifc_path).exists():
            return jsonify({"error": f"IFC file not found: {ifc_path}"}), 400

        print(f"Loading IFC: {ifc_path}")
        t0 = time.time()

        # Load IFC
        state.ifc_path = ifc_path
        state.ifc_data = load_ifc(ifc_path)
        state.ifc_summary = get_element_summary(ifc_path)
        state.ifc_materials = get_materials(ifc_path)
        state.selected_elements = []
        state.element_id_image = None

        # Initialize element renderer if available
        renderer_status = "not available"
        geometry_status = "not extracted"
        if IFC_RENDERER_AVAILABLE:
            try:
                state.ifc_renderer = get_ifc_renderer(ifc_path)
                renderer_status = f"{len(state.ifc_renderer.elements)} elements"
                print(f"IFC renderer initialized with {len(state.ifc_renderer.elements)} elements")

                # Extract geometry to get bounds (needed for camera sync)
                print("Extracting IFC geometry for bounds...")
                mesh = state.ifc_renderer.extract_geometry()
                if mesh is not None:
                    state.ifc_bounds = mesh.bounds  # [[minx,miny,minz], [maxx,maxy,maxz]]
                    state.ifc_center = mesh.centroid
                    state.ifc_size = float(np.linalg.norm(mesh.bounds[1] - mesh.bounds[0]))
                    geometry_status = f"bounds extracted, size={state.ifc_size:.0f}mm"
                    print(f"IFC bounds: {state.ifc_bounds}")
                    print(f"IFC center: {state.ifc_center}, size: {state.ifc_size:.0f}mm")

            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"IFC renderer init failed: {e}")
                renderer_status = f"error: {e}"

        elapsed = time.time() - t0
        print(f"IFC loaded in {elapsed:.2f}s")

        return jsonify({
            "status": "ok",
            "path": ifc_path,
            "time": elapsed,
            "summary": state.ifc_summary,
            "materials": {k: len(v) for k, v in state.ifc_materials.items()},
            "renderer": renderer_status,
            "geometry": geometry_status,
            "bounds": state.ifc_bounds.tolist() if state.ifc_bounds is not None else None,
            "size_mm": state.ifc_size
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/ifc/summary', methods=['GET'])
def api_ifc_summary():
    """Get summary of loaded IFC file."""
    if not state.ifc_path:
        return jsonify({"error": "No IFC file loaded"}), 400

    return jsonify({
        "path": state.ifc_path,
        "elements": state.ifc_summary,
        "materials": {k: len(v) for k, v in state.ifc_materials.items()} if state.ifc_materials else {},
        "selected_count": len(state.selected_elements)
    })


@app.route('/api/ifc/elements/<element_type>', methods=['GET'])
def api_ifc_elements(element_type):
    """Get all elements of a specific type."""
    if not state.ifc_path:
        return jsonify({"error": "No IFC file loaded"}), 400

    try:
        elements = get_elements_by_type(state.ifc_path, element_type)
        return jsonify({
            "type": element_type,
            "count": len(elements),
            "elements": elements
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/ifc/materials', methods=['GET'])
def api_ifc_materials():
    """Get all materials in the IFC file."""
    if not state.ifc_path:
        return jsonify({"error": "No IFC file loaded"}), 400

    return jsonify({
        "materials": state.ifc_materials
    })


@app.route('/api/ifc/select', methods=['POST'])
def api_ifc_select():
    """
    Select elements for AI enhancement.

    POST body:
        element_type: IFC class to select (e.g., "IfcWall")
        material: Material name to select (alternative to element_type)
        global_ids: List of specific GlobalIds to select
        action: "set" (replace), "add", or "remove"
    """
    if not state.ifc_path:
        return jsonify({"error": "No IFC file loaded"}), 400

    data = request.json or {}
    action = data.get('action', 'set')

    new_selection = []

    # Select by element type
    if 'element_type' in data:
        elements = get_elements_by_type(state.ifc_path, data['element_type'])
        new_selection = [e['global_id'] for e in elements]

    # Select by material
    elif 'material' in data:
        elements = get_elements_by_material(state.ifc_path, data['material'])
        new_selection = [e['global_id'] for e in elements]

    # Select specific GlobalIds
    elif 'global_ids' in data:
        new_selection = data['global_ids']

    # Apply action
    if action == 'set':
        state.selected_elements = new_selection
    elif action == 'add':
        state.selected_elements = list(set(state.selected_elements + new_selection))
    elif action == 'remove':
        state.selected_elements = [e for e in state.selected_elements if e not in new_selection]
    elif action == 'clear':
        state.selected_elements = []

    return jsonify({
        "status": "ok",
        "selected_count": len(state.selected_elements),
        "action": action
    })


@app.route('/api/ifc/selection', methods=['GET'])
def api_ifc_selection():
    """Get current selection."""
    return jsonify({
        "selected": state.selected_elements,
        "count": len(state.selected_elements)
    })


@app.route('/api/ifc/capture_from_revit', methods=['POST'])
def api_ifc_capture_from_revit():
    """
    Capture the current view directly from Revit as the base image.
    This bypasses camera sync issues by using Revit's own renderer.
    """
    import requests as req

    data = request.json or {}
    width = data.get('width', 960)
    height = data.get('height', 540)

    t0 = time.time()

    try:
        # Call Revit to export the current view
        print(f"Requesting render from Revit at {width}x{height}...")
        resp = req.post(
            "http://localhost:48884/revit_mcp/export_view/",
            json={"width": width, "height": height, "format": "png"},
            timeout=30
        )
        result = resp.json()

        if result.get("error"):
            return jsonify({"error": f"Revit error: {result['error']}"}), 400

        # Get the exported image path or base64
        if result.get("image_base64"):
            # Decode and save
            img_data = base64.b64decode(result["image_base64"])
            base_path = state.out_dir / "base.png"
            with open(base_path, 'wb') as f:
                f.write(img_data)
            print(f"Saved Revit render to {base_path}")

        elif result.get("path"):
            # Copy from path
            import shutil
            src_path = Path(result["path"])
            if src_path.exists():
                base_path = state.out_dir / "base.png"
                shutil.copy(src_path, base_path)
                print(f"Copied Revit render from {src_path}")
            else:
                return jsonify({"error": f"Revit export path not found: {src_path}"}), 400
        else:
            return jsonify({"error": "Revit didn't return image data"}), 400

        elapsed = time.time() - t0

        # Return base64
        base_path = state.out_dir / "base.png"
        with open(base_path, 'rb') as f:
            base_b64 = base64.b64encode(f.read()).decode('utf-8')

        return jsonify({
            "status": "ok",
            "time": elapsed,
            "resolution": [width, height],
            "source": "Revit",
            "image": base_b64
        })

    except req.exceptions.ConnectionError:
        return jsonify({"error": "Cannot connect to Revit. Ensure RevitMCP is running."}), 400
    except req.exceptions.Timeout:
        return jsonify({"error": "Revit render timed out"}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/ifc/transfer_to_channels', methods=['POST'])
def api_ifc_transfer_to_channels():
    """
    Transfer IFC mesh to the Channels system.

    This allows using all Channels tab features (camera warp, section box, etc.)
    with the IFC geometry.
    """
    if state.ifc_renderer is None:
        return jsonify({"error": "No IFC loaded. Load IFC file first."}), 400

    if state.ifc_renderer.combined_mesh is None:
        return jsonify({"error": "IFC geometry not extracted. Render channels first."}), 400

    try:
        # Transfer IFC mesh to state.mesh (used by Channels tab)
        state.mesh = state.ifc_renderer.combined_mesh

        # Calculate mesh properties
        state.mesh_center = state.mesh.centroid
        state.mesh_size = float(np.linalg.norm(state.mesh.bounds[1] - state.mesh.bounds[0]))

        # Set default camera if not set
        if state.revit_camera is None:
            # Create a default camera looking at the mesh
            center = state.mesh_center
            size = state.mesh_size
            eye = center + np.array([size, size, size * 0.5])
            forward = center - eye
            forward = forward / np.linalg.norm(forward)

            state.revit_camera = {
                "Eye": eye.tolist(),
                "Forward": forward.tolist(),
                "Up": [0, 0, 1],
                "IsPerspective": True,
                "FieldOfView": 0.785,
                "NearClip": 0.1,
                "FarClip": size * 10
            }

        print(f"IFC mesh transferred to Channels: {len(state.mesh.vertices)} verts, {len(state.mesh.faces)} faces")
        print(f"Mesh center: {state.mesh_center}, size: {state.mesh_size:.2f}")

        return jsonify({
            "status": "ok",
            "vertices": len(state.mesh.vertices),
            "faces": len(state.mesh.faces),
            "center": state.mesh_center.tolist(),
            "size": state.mesh_size,
            "message": "IFC mesh ready in Channels tab"
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/ifc/debug', methods=['GET'])
def api_ifc_debug():
    """Debug endpoint to see camera vs geometry positions."""
    if state.ifc_renderer is None:
        return jsonify({"error": "No IFC loaded"}), 400

    camera = state.revit_camera
    bounds = state.ifc_bounds
    center = state.ifc_center

    result = {
        "camera": camera,
        "ifc_bounds": bounds.tolist() if bounds is not None else None,
        "ifc_center": center.tolist() if center is not None else None,
        "ifc_size": state.ifc_size,
    }

    if camera and center is not None:
        eye = np.array(camera["Eye"])
        dist_to_center = float(np.linalg.norm(eye - center))
        result["distance_to_center"] = dist_to_center
        result["distance_ratio"] = dist_to_center / state.ifc_size if state.ifc_size else None

        # Check if camera is inside bounds
        if bounds is not None:
            inside = all(bounds[0][i] <= eye[i] <= bounds[1][i] for i in range(3))
            result["camera_inside_bounds"] = inside

    return jsonify(result)


@app.route('/api/ifc/render_channels', methods=['POST'])
def api_ifc_render_channels():
    """
    Render all channels from IFC geometry: base, depth, normals, edges.

    POST body:
        resolution: [width, height] (default: [960, 540])
        distance_scale: float (default: 1.0) - adjust camera distance (0.5 = closer, 2.0 = farther)
    """
    import requests as req

    if not state.ifc_path:
        return jsonify({"error": "No IFC file loaded"}), 400

    if state.ifc_renderer is None:
        return jsonify({"error": "IFC renderer not initialized. Reload IFC file."}), 400

    data = request.json or {}
    resolution = tuple(data.get('resolution', [960, 540]))
    distance_scale = float(data.get('distance_scale', 1.0))

    # Auto-sync camera from Revit
    print("Syncing camera from Revit...")
    try:
        resp = req.get("http://localhost:48884/revit_mcp/export_camera/", timeout=5)
        cam_result = resp.json()
        cam_data = cam_result.get("camera") or cam_result

        if cam_data and "Eye" in cam_data:
            eye = np.array(cam_data["Eye"])
            forward = np.array(cam_data["Forward"])
            forward = forward / np.linalg.norm(forward)
            up = np.array(cam_data.get("Up", [0, 0, 1]))
            up = up / np.linalg.norm(up)

            state.revit_camera = {
                "Eye": eye.tolist(),
                "Forward": forward.tolist(),
                "Up": up.tolist(),
                "IsPerspective": cam_data.get("IsPerspective", True),
                "FieldOfView": cam_data.get("FieldOfView", 0.785),
                "NearClip": 0.1,
                "FarClip": state.ifc_size * 10 if state.ifc_size else 1000
            }
            print(f"Camera synced: eye={eye}")
    except Exception as e:
        print(f"Camera sync failed: {e}")

    if not state.revit_camera:
        return jsonify({"error": "No camera. Ensure Revit is running."}), 400

    t0 = time.time()

    try:
        print(f"Rendering IFC channels at {resolution} with distance_scale={distance_scale}...")
        channels = state.ifc_renderer.render_channels(state.revit_camera, resolution, distance_scale)

        # Save all channels
        saved = []
        for name, img in channels.items():
            path = state.out_dir / f"{name}.png"
            img.save(path)
            saved.append(name)
            print(f"  Saved {name}.png")

        elapsed = time.time() - t0
        print(f"Channel render complete in {elapsed:.2f}s")

        # Return base64 of base image
        base_path = state.out_dir / "base.png"
        with open(base_path, 'rb') as f:
            base_b64 = base64.b64encode(f.read()).decode('utf-8')

        return jsonify({
            "status": "ok",
            "time": elapsed,
            "channels": saved,
            "distance_scale": distance_scale,
            "image": base_b64
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/ifc/render_base', methods=['POST'])
def api_ifc_render_base():
    """
    Render a shaded base image from IFC geometry for AI enhancement.
    For full channel extraction, use /api/ifc/render_channels instead.
    """
    import requests as req

    if not state.ifc_path:
        return jsonify({"error": "No IFC file loaded"}), 400

    if state.ifc_renderer is None:
        return jsonify({"error": "IFC renderer not initialized. Reload IFC file."}), 400

    data = request.json or {}
    resolution = tuple(data.get('resolution', [960, 540]))
    distance_scale = float(data.get('distance_scale', 1.0))

    # Auto-sync camera from Revit
    print("Auto-syncing camera from Revit...")
    try:
        resp = req.get("http://localhost:48884/revit_mcp/export_camera/", timeout=5)
        cam_result = resp.json()
        cam_data = cam_result.get("camera") or cam_result

        if cam_data and "Eye" in cam_data:
            eye = np.array(cam_data["Eye"])
            forward = np.array(cam_data["Forward"])
            forward = forward / np.linalg.norm(forward)
            up = np.array(cam_data.get("Up", [0, 0, 1]))
            up = up / np.linalg.norm(up)

            state.revit_camera = {
                "Eye": eye.tolist(),
                "Forward": forward.tolist(),
                "Up": up.tolist(),
                "IsPerspective": cam_data.get("IsPerspective", True),
                "FieldOfView": cam_data.get("FieldOfView", 0.785),
                "NearClip": 0.1,
                "FarClip": state.ifc_size * 10 if state.ifc_size else 1000
            }
            print(f"Camera synced: eye={eye}")
    except Exception as e:
        print(f"Camera sync failed: {e}")

    if not state.revit_camera:
        return jsonify({"error": "No camera. Ensure Revit is running."}), 400

    t0 = time.time()

    try:
        print(f"Rendering IFC channels at {resolution}...")
        channels = state.ifc_renderer.render_channels(state.revit_camera, resolution, distance_scale)

        # Save all channels
        for name, img in channels.items():
            path = state.out_dir / f"{name}.png"
            img.save(path)

        elapsed = time.time() - t0
        print(f"Render complete in {elapsed:.2f}s")

        # Return base64
        base_path = state.out_dir / "base.png"
        with open(base_path, 'rb') as f:
            base_b64 = base64.b64encode(f.read()).decode('utf-8')

        return jsonify({
            "status": "ok",
            "time": elapsed,
            "channels": list(channels.keys()),
            "image": base_b64
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


print(">>> REGISTERING /api/ifc/render_ids route")
@app.route('/api/ifc/render_ids', methods=['POST'])
def api_ifc_render_ids():
    """
    Render element ID pass - each IFC element gets a unique color.

    POST body:
        resolution: [width, height] (default: [960, 540])
        distance_scale: float (default: 1.0) - zoom adjustment
    """
    import requests as req

    if not state.ifc_path:
        return jsonify({"error": "No IFC file loaded"}), 400

    if not IFC_RENDERER_AVAILABLE:
        return jsonify({"error": "IFC renderer not available. Install pyrender."}), 400

    if state.ifc_renderer is None:
        return jsonify({"error": "IFC renderer not initialized. Reload IFC file."}), 400

    data = request.json or {}
    resolution = tuple(data.get('resolution', [960, 540]))
    distance_scale = float(data.get('distance_scale', 1.0))

    # Auto-sync camera from Revit
    try:
        resp = req.get("http://localhost:48884/revit_mcp/export_camera/", timeout=5)
        cam_result = resp.json()
        cam_data = cam_result.get("camera") or cam_result

        if cam_data and "Eye" in cam_data:
            eye = np.array(cam_data["Eye"])
            forward = np.array(cam_data["Forward"])
            forward = forward / np.linalg.norm(forward)
            up = np.array(cam_data.get("Up", [0, 0, 1]))
            up = up / np.linalg.norm(up)

            # Apply distance scale
            if distance_scale != 1.0 and state.ifc_center is not None:
                center = state.ifc_center
                direction = eye - center
                eye = center + direction * distance_scale

            state.revit_camera = {
                "Eye": eye.tolist(),
                "Forward": forward.tolist(),
                "Up": up.tolist(),
                "IsPerspective": cam_data.get("IsPerspective", True),
                "FieldOfView": cam_data.get("FieldOfView", 0.785),
                "NearClip": 0.1,
                "FarClip": state.ifc_size * 10 if state.ifc_size else 1000
            }
    except Exception as e:
        print(f"Camera sync failed: {e}")

    camera = state.revit_camera
    if not camera:
        return jsonify({"error": "No camera. Ensure Revit is running."}), 400

    t0 = time.time()

    try:
        # Extract geometry if not done
        if state.ifc_renderer.combined_mesh is None:
            print("Extracting IFC geometry...")
            state.ifc_renderer.extract_geometry()

        # Render element IDs with distance scale
        print(f"Rendering element IDs at {resolution} with distance_scale={distance_scale}...")
        state.element_id_image = state.ifc_renderer.render_element_ids(camera, resolution, distance_scale)

        # Save for reference
        id_path = state.out_dir / "element_ids.png"
        state.element_id_image.save(id_path)

        elapsed = time.time() - t0
        print(f"Element ID pass rendered in {elapsed:.2f}s")

        # Return as base64
        with open(id_path, 'rb') as f:
            id_b64 = base64.b64encode(f.read()).decode('utf-8')

        return jsonify({
            "status": "ok",
            "time": elapsed,
            "resolution": list(resolution),
            "elements": len(state.ifc_renderer.elements),
            "url": "/channel/element_ids",
            "image": id_b64
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/ifc/mask', methods=['POST'])
def api_ifc_mask():
    """
    Generate a mask image from selected IFC elements.

    This creates a black/white mask where selected elements are white
    and everything else is black. Can be used for selective AI enhancement.

    POST body:
        invert: If true, selected elements are black (protected)
        feather: Blur radius for soft edges (default 0)
        use_element_ids: If true, use proper element ID pass (requires render_ids first)
                        If false, falls back to depth threshold

    For true per-element masking, call /api/ifc/render_ids first,
    then this endpoint with use_element_ids=true.
    """
    if not state.ifc_path:
        return jsonify({"error": "No IFC file loaded"}), 400

    if not state.selected_elements:
        return jsonify({"error": "No elements selected"}), 400

    data = request.json or {}
    invert = data.get('invert', False)
    feather = int(data.get('feather', 5))
    use_element_ids = data.get('use_element_ids', True)

    t0 = time.time()

    try:
        from PIL import ImageFilter

        mask_img = None

        # Method 1: Use element ID pass (accurate per-element)
        if use_element_ids and state.element_id_image is not None and state.ifc_renderer is not None:
            print(f"Creating mask from element ID pass for {len(state.selected_elements)} elements...")

            mask_img = state.ifc_renderer.create_mask_from_selection(
                state.element_id_image,
                state.selected_elements,
                invert=invert,
                feather=feather
            )
            method = "element_ids"

        # Method 2: Fallback to depth threshold (approximate)
        else:
            print("Falling back to depth-based mask (render element IDs for accuracy)")
            depth_path = state.out_dir / "depth.png"
            if not depth_path.exists():
                return jsonify({"error": "No depth channel. Extract channels or render element IDs first."}), 400

            depth_img = Image.open(depth_path).convert('L')
            depth_np = np.array(depth_img).astype(np.float32) / 255.0

            threshold = float(data.get('threshold', 0.3))

            if invert:
                mask_np = (depth_np < threshold).astype(np.uint8) * 255
            else:
                mask_np = (depth_np > threshold).astype(np.uint8) * 255

            mask_img = Image.fromarray(mask_np, mode='L')

            if feather > 0:
                mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=feather))

            method = "depth_threshold"

        # Save mask
        mask_path = state.out_dir / "element_mask.png"
        mask_img.save(mask_path)

        elapsed = time.time() - t0

        # Return as base64
        with open(mask_path, 'rb') as f:
            mask_b64 = base64.b64encode(f.read()).decode('utf-8')

        return jsonify({
            "status": "ok",
            "time": elapsed,
            "method": method,
            "selected_count": len(state.selected_elements),
            "mask_url": "/channel/element_mask",
            "image": mask_b64
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/ifc/sync_camera', methods=['POST'])
def api_ifc_sync_camera():
    """
    Sync camera from Revit for IFC-only workflow.

    This allows camera sync without loading an OBJ mesh.
    Uses IFC geometry bounds for camera calculations.

    POST body:
        (optional) - camera will be fetched from Revit automatically
    """
    import requests

    if state.ifc_size is None:
        return jsonify({"error": "No IFC geometry loaded. Load IFC file first."}), 400

    t0 = time.time()
    result = {"camera": None, "message": ""}

    # Try to get camera from Revit
    cam_data = None
    try:
        resp = requests.get("http://localhost:48884/revit_mcp/export_camera/", timeout=5)
        cam_result = resp.json()
        if cam_result.get("camera"):
            cam_data = cam_result["camera"]
            result["camera"] = "synced from Revit"
            print(f"Camera synced from Revit: {cam_result.get('viewName', 'unknown')}")
        elif cam_result.get("status") == "ok":
            # Old format - look for direct camera data
            if "Eye" in cam_result:
                cam_data = cam_result
                result["camera"] = "synced from Revit (legacy format)"
    except Exception as e:
        result["camera"] = f"Revit not available: {e}"
        print(f"Revit camera sync failed: {e}")

    # Fallback: try to read camera.json
    if cam_data is None:
        json_paths = [
            Path(r"C:\Users\jerro\Desktop\channel_test\camera.json"),
        ]
        if state.ifc_path:
            json_paths.insert(0, Path(state.ifc_path).parent / "camera.json")

        for json_path in json_paths:
            if json_path.exists():
                try:
                    with open(json_path) as f:
                        cam_data = json.load(f)
                    result["camera"] = f"loaded from {json_path}"
                    print(f"Camera loaded from {json_path}")
                    break
                except Exception as e:
                    print(f"Failed to load {json_path}: {e}")

    if cam_data is None:
        return jsonify({"error": "No camera data available. Ensure Revit is running or camera.json exists."}), 400

    # IFC exported from Revit is in FEET, same as camera - no conversion needed
    eye = np.array(cam_data["Eye"])
    forward = np.array(cam_data["Forward"])
    forward = forward / np.linalg.norm(forward)
    up = np.array(cam_data.get("Up", [0, 0, 1]))
    up = up / np.linalg.norm(up)

    # Store camera using IFC size for far clip
    state.revit_camera = {
        "Eye": eye.tolist(),
        "Forward": forward.tolist(),
        "Up": up.tolist(),
        "IsPerspective": cam_data.get("IsPerspective", True),
        "FieldOfView": cam_data.get("FieldOfView", 0.785),
        "NearClip": 0.1,
        "FarClip": state.ifc_size * 10
    }

    elapsed = time.time() - t0

    # Compute UI-friendly values
    az = float(np.degrees(np.arctan2(-forward[0], forward[1])) % 360)
    el = float(np.degrees(np.arcsin(np.clip(-forward[2], -1, 1))))

    if state.ifc_center is not None:
        dist_to_center = np.linalg.norm(eye - state.ifc_center)
        distance = dist_to_center / state.ifc_size
    else:
        distance = 1.5

    print(f"IFC camera set: eye={eye}, forward={forward}")

    return jsonify({
        "status": "ok",
        "time": elapsed,
        "result": result,
        "camera": {
            "eye": eye.tolist(),
            "forward": forward.tolist(),
            "up": up.tolist(),
            "fov": cam_data.get("FieldOfView", 0.785),
            "azimuth": az,
            "elevation": el,
            "distance": distance
        },
        "ifc_bounds": state.ifc_bounds.tolist() if state.ifc_bounds is not None else None,
        "ifc_size": state.ifc_size
    })


@app.route('/api/ifc/enhance', methods=['POST'])
def api_ifc_enhance():
    """
    AI enhance only selected IFC elements.

    Uses the element mask to selectively enhance only the selected
    elements while keeping everything else untouched.

    POST body:
        prompt: AI prompt for selected elements
        strength: Enhancement strength (0-1)
        threshold: Depth threshold for mask generation
        invert: If true, enhance everything EXCEPT selected elements
    """
    if not state.ifc_path:
        return jsonify({"error": "No IFC file loaded"}), 400

    if not state.selected_elements:
        return jsonify({"error": "No elements selected. Select elements first."}), 400

    data = request.json or {}
    prompt = data.get('prompt', 'photorealistic architectural materials, detailed texture, 4K')
    negative = data.get('negative', 'blurry, low quality, distorted')
    strength = float(data.get('strength', 0.4))
    threshold = float(data.get('threshold', 0.3))
    invert = data.get('invert', False)
    steps = int(data.get('steps', 30))

    # Get base image
    base_path = state.out_dir / "base.png"
    if not base_path.exists():
        return jsonify({"error": "No base image. Upload first."}), 400

    depth_path = state.out_dir / "depth.png"
    if not depth_path.exists():
        return jsonify({"error": "No depth channel. Extract channels first."}), 400

    # Save to history
    history_save("Before IFC Element Enhance")

    t0 = time.time()

    try:
        from render.enhance.inpainting import get_inpainter
        from PIL import ImageFilter

        # Generate mask from selection
        depth_img = Image.open(depth_path).convert('L')
        depth_np = np.array(depth_img).astype(np.float32) / 255.0

        if invert:
            # Enhance everything except selected (building)
            mask_np = (depth_np < threshold).astype(np.uint8) * 255
        else:
            # Enhance only selected (building)
            mask_np = (depth_np > threshold).astype(np.uint8) * 255

        mask_img = Image.fromarray(mask_np, mode='L')
        mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=10))

        # Save mask for reference
        mask_path = state.out_dir / "element_mask.png"
        mask_img.save(mask_path)

        # Free other AI models
        if state.enhancer is not None:
            state.enhancer = None
            import gc
            gc.collect()
            torch.cuda.empty_cache()

        # Load base image
        base_img = Image.open(base_path).convert('RGB')

        # Get inpainter
        inpainter = get_inpainter('sd15')

        # Inpaint selected region
        result_img = inpainter.inpaint(
            image=base_img,
            mask=mask_img,
            prompt=prompt,
            negative_prompt=negative,
            num_inference_steps=steps,
            guidance_scale=7.5
        )

        # Save result
        output_path = state.out_dir / "enhanced.png"
        result_img.save(output_path)

        # Save original for post-processing
        original_path = state.out_dir / "enhanced_original.png"
        result_img.save(original_path)

        elapsed = time.time() - t0
        print(f"IFC element enhancement complete in {elapsed:.1f}s")

        return jsonify({
            "status": "ok",
            "time": elapsed,
            "selected_count": len(state.selected_elements),
            "url": "/channel/enhanced",
            "mask_url": "/channel/element_mask"
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ============================================================
# REVIT ELEMENT ID EXPORT - Same coordinate system as camera
# ============================================================

@app.route('/api/revit/export_element_ids', methods=['POST'])
def revit_export_element_ids():
    """
    Trigger Revit to export element_ids.obj with unique colors per element.
    This ensures the geometry is in the same coordinate system as the camera.
    """
    import requests as req

    try:
        print("Requesting element ID export from Revit...")
        resp = req.get("http://localhost:48884/revit_mcp/export_element_ids/", timeout=60)
        result = resp.json()

        if result.get("status") == "error":
            return jsonify({"error": result.get("message", "Revit export failed")}), 500

        # Store the exported paths
        obj_path = result.get("objPath")
        mtl_path = result.get("mtlPath")
        map_path = result.get("mapPath")

        if obj_path and Path(obj_path).exists():
            # Load the element ID map for later mask generation
            if map_path and Path(map_path).exists():
                with open(map_path, 'r') as f:
                    state.element_id_map = json.load(f)

            # Store path for rendering
            state.revit_element_obj_path = obj_path

            return jsonify({
                "status": "ok",
                "objPath": obj_path,
                "mtlPath": mtl_path,
                "mapPath": map_path,
                "elementCount": result.get("elementCount", 0),
                "viewName": result.get("viewName", "Unknown")
            })
        else:
            return jsonify({"error": "OBJ file not created"}), 500

    except req.exceptions.ConnectionError:
        return jsonify({"error": "Cannot connect to RevitMCP. Is Revit running with the plugin loaded?"}), 503
    except req.exceptions.Timeout:
        return jsonify({"error": "Revit export timed out (60s)"}), 504
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/revit/render_element_ids', methods=['POST'])
def revit_render_element_ids():
    """
    Render the element ID pass from Revit-exported OBJ.
    Uses the same coordinate system as camera for perfect alignment.
    """
    import requests as req

    try:
        data = request.get_json() or {}
        resolution = (data.get("width", 960), data.get("height", 540))

        # Get OBJ path (from previous export or request)
        obj_path = data.get("objPath") or getattr(state, 'revit_element_obj_path', None)
        if not obj_path:
            obj_path = r"C:\Users\jerro\Desktop\channel_test\element_ids.obj"

        if not Path(obj_path).exists():
            return jsonify({"error": f"Element ID OBJ not found: {obj_path}. Call /api/revit/export_element_ids first."}), 404

        # Sync camera from Revit
        print("Syncing camera from Revit...")
        cam_data = None
        try:
            resp = req.get("http://localhost:48884/revit_mcp/export_camera/", timeout=5)
            cam_result = resp.json()
            cam_data = cam_result.get("camera") or cam_result

            if not all(k in cam_data for k in ["Eye", "Forward", "Up"]):
                return jsonify({"error": "Invalid camera data from Revit"}), 500
        except Exception as e:
            return jsonify({"error": f"Cannot get camera from Revit: {e}"}), 503

        # Load mesh with materials (element colors)
        print(f"Loading element ID mesh: {obj_path}")

        # Load as scene to preserve materials, then combine
        scene_or_mesh = trimesh.load(obj_path)

        if isinstance(scene_or_mesh, trimesh.Scene):
            # Combine all geometries and assign vertex colors from materials
            meshes = []
            mesh_colors = {}  # Store colors for each submesh for pyrender
            for name, geom in scene_or_mesh.geometry.items():
                if isinstance(geom, trimesh.Trimesh):
                    # Get material color if available
                    if hasattr(geom.visual, 'material') and geom.visual.material is not None:
                        mat = geom.visual.material
                        if hasattr(mat, 'diffuse'):
                            color = list(mat.diffuse[:3])
                        elif hasattr(mat, 'main_color'):
                            color = list(mat.main_color[:3])
                        else:
                            color = [128, 128, 128]
                    else:
                        color = [128, 128, 128]

                    # Store color for this geometry
                    mesh_colors[name] = color
                    meshes.append((name, geom, color))

            # We'll render each submesh separately with its own unlit material
            combined_meshes = meshes
            mesh = None  # Don't combine - render separately
        else:
            mesh = scene_or_mesh
            combined_meshes = None

        # Get camera parameters (in Revit feet coordinates)
        eye = np.array(cam_data["Eye"], dtype=np.float64)
        forward = np.array(cam_data["Forward"], dtype=np.float64)
        up = np.array(cam_data["Up"], dtype=np.float64)
        fov = cam_data.get("FieldOfView", 0.785)  # radians

        # Normalize vectors
        forward = forward / np.linalg.norm(forward)
        up = up / np.linalg.norm(up)

        # Create camera pose (look-at)
        right = np.cross(forward, up)
        right = right / np.linalg.norm(right)
        up = np.cross(right, forward)  # Recalculate for orthogonality

        # Build camera matrix (OpenGL convention: -Z is forward)
        camera_pose = np.eye(4)
        camera_pose[:3, 0] = right
        camera_pose[:3, 1] = up
        camera_pose[:3, 2] = -forward  # OpenGL looks down -Z
        camera_pose[:3, 3] = eye

        # Render using pyrender
        import pyrender

        scene = pyrender.Scene(bg_color=[0, 0, 0, 0])

        # Add meshes to scene with unlit materials for exact colors
        if combined_meshes:
            # Add each submesh with its own unlit material
            for name, geom, color in combined_meshes:
                # Create unlit material with exact color (emissive = color, no lighting effect)
                material = pyrender.MetallicRoughnessMaterial(
                    baseColorFactor=[color[0]/255.0, color[1]/255.0, color[2]/255.0, 1.0],
                    metallicFactor=0.0,
                    roughnessFactor=1.0,
                    emissiveFactor=[color[0]/255.0, color[1]/255.0, color[2]/255.0]
                )
                py_submesh = pyrender.Mesh.from_trimesh(geom, material=material, smooth=False)
                scene.add(py_submesh)
        elif mesh is not None:
            # Single mesh - add with default material
            py_mesh = pyrender.Mesh.from_trimesh(mesh, smooth=False)
            scene.add(py_mesh)

        # Add camera - check if perspective or orthographic
        is_perspective = cam_data.get("IsPerspective", True)
        aspect_ratio = resolution[0] / resolution[1]

        # Calculate reasonable near/far planes based on model bounds
        if combined_meshes:
            # Get bounds from all submeshes
            all_vertices = np.vstack([geom.vertices for _, geom, _ in combined_meshes])
            model_center = all_vertices.mean(axis=0)
            model_min = all_vertices.min(axis=0)
            model_max = all_vertices.max(axis=0)
            model_size = np.linalg.norm(model_max - model_min)
        else:
            model_center = mesh.centroid
            model_size = np.linalg.norm(mesh.bounds[1] - mesh.bounds[0])
        dist_to_model = np.linalg.norm(eye - model_center)

        znear = max(0.1, dist_to_model - model_size * 2)
        zfar = dist_to_model + model_size * 2

        print(f"Camera: eye={eye}, dist_to_model={dist_to_model:.1f}, model_size={model_size:.1f}")
        print(f"Clipping: znear={znear:.1f}, zfar={zfar:.1f}, FOV={np.degrees(fov):.1f}°")

        if is_perspective:
            camera = pyrender.PerspectiveCamera(yfov=fov, aspectRatio=aspect_ratio, znear=znear, zfar=zfar)
        else:
            # Orthographic - use model size for scale
            xmag = model_size / 2
            ymag = xmag / aspect_ratio
            camera = pyrender.OrthographicCamera(xmag=xmag, ymag=ymag, znear=znear, zfar=zfar)

        scene.add(camera, pose=camera_pose)

        # Render with FLAT flag and VERTEX_COLORS to get exact colors
        renderer = pyrender.OffscreenRenderer(resolution[0], resolution[1])
        flags = pyrender.RenderFlags.FLAT | pyrender.RenderFlags.SKIP_CULL_FACES | pyrender.RenderFlags.RGBA
        color, depth = renderer.render(scene, flags=flags)
        renderer.delete()

        # Convert to RGB if RGBA
        if color.shape[-1] == 4:
            color = color[:, :, :3]

        # Save element ID pass
        element_img = Image.fromarray(color)
        element_path = state.out_dir / "revit_element_ids.png"
        element_img.save(element_path)
        state.revit_element_id_image = element_img

        print(f"Rendered element ID pass: {resolution[0]}x{resolution[1]}")

        return jsonify({
            "status": "ok",
            "resolution": list(resolution),
            "url": "/channel/revit_element_ids",
            "camera": {
                "eye": eye.tolist(),
                "forward": forward.tolist(),
                "fov": fov
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/revit/element_mask', methods=['POST'])
def revit_element_mask():
    """
    Generate mask from Revit element ID render by selecting specific element colors.
    """
    try:
        data = request.get_json() or {}
        element_ids = data.get("elementIds", [])  # List of ElementIds to include in mask
        invert = data.get("invert", False)

        # Load element ID image
        element_img = getattr(state, 'revit_element_id_image', None)
        if element_img is None:
            element_path = state.out_dir / "revit_element_ids.png"
            if element_path.exists():
                element_img = Image.open(element_path)
            else:
                return jsonify({"error": "No element ID render. Call /api/revit/render_element_ids first."}), 404

        # Load element ID map
        element_map = getattr(state, 'element_id_map', None)
        if element_map is None:
            map_path = r"C:\Users\jerro\Desktop\channel_test\element_id_map.json"
            if Path(map_path).exists():
                with open(map_path, 'r') as f:
                    element_map = json.load(f)
            else:
                return jsonify({"error": "No element ID map found"}), 404

        # Get target colors for selected elements
        target_colors = []
        print(f"Mask request for {len(element_ids)} elements: {element_ids[:5]}...")
        for elem_id in element_ids:
            key = f"elem_{elem_id}"
            if key in element_map:
                color = tuple(element_map[key]["Color"])
                target_colors.append(color)
                print(f"  {key}: color {color}")
            else:
                print(f"  {key}: NOT FOUND in map")

        if not target_colors:
            return jsonify({"error": "No matching elements found in map"}), 400

        # Convert image to array and create mask
        img_array = np.array(element_img)
        mask = np.zeros((img_array.shape[0], img_array.shape[1]), dtype=np.uint8)

        # Analyze ALL unique colors in the rendered image
        unique_colors = set()
        flat_pixels = img_array[:, :, :3].reshape(-1, 3)
        for pixel in flat_pixels:
            c = tuple(int(x) for x in pixel)  # Convert to regular int
            if c != (0, 0, 0):  # Skip black background
                unique_colors.add(c)
        print(f"Total unique colors in rendered image: {len(unique_colors)}")
        print(f"Sample colors: {list(unique_colors)[:15]}")

        total_matches = 0
        tolerance = 15  # Allow color differences due to rendering variations
        print(f"Looking for {len(target_colors)} target colors with tolerance ±{tolerance}")

        for color in target_colors:
            # Find pixels matching this color (with tolerance)
            color_arr = np.array(color)
            diff = np.abs(img_array[:, :, :3].astype(int) - color_arr.astype(int))
            matches = np.all(diff <= tolerance, axis=2)
            match_count = np.sum(matches)
            total_matches += match_count
            mask[matches] = 255

            # Find closest color in image if no matches
            if match_count == 0:
                min_diff = float('inf')
                closest = None
                for uc in unique_colors:
                    # uc is already tuple of ints now
                    d = sum(abs(a - b) for a, b in zip(color, uc))
                    if d < min_diff:
                        min_diff = d
                        closest = uc
                print(f"  Color {color}: 0 pixels (closest: {closest}, diff={min_diff}) - WALL NOT VISIBLE")
            else:
                print(f"  Color {color}: {match_count} pixels matched")

        print(f"Total pixels matched: {total_matches}")

        if invert:
            mask = 255 - mask

        # Apply slight blur for smoother edges
        from PIL import ImageFilter
        mask_img = Image.fromarray(mask, mode='L')
        mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=2))

        # Save mask
        mask_path = state.out_dir / "revit_element_mask.png"
        mask_img.save(mask_path)

        return jsonify({
            "status": "ok",
            "url": "/channel/revit_element_mask",
            "selectedElements": len(element_ids),
            "matchedColors": len(target_colors)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/revit/element_map', methods=['GET'])
def get_revit_element_map():
    """Return the element ID to color mapping from Revit export."""
    # First check state
    element_map = getattr(state, 'element_id_map', None)
    if element_map:
        return jsonify(element_map)

    # Try loading from file
    map_path = Path(r"C:\Users\jerro\Desktop\channel_test\element_id_map.json")
    if map_path.exists():
        with open(map_path, 'r') as f:
            return jsonify(json.load(f))

    return jsonify({"error": "No element map found. Run /api/revit/export_element_ids first."}), 404


@app.route('/channel/revit_element_ids')
def serve_revit_element_ids():
    """Serve the Revit element ID pass."""
    path = state.out_dir / "revit_element_ids.png"
    if path.exists():
        return send_file(path, mimetype='image/png')
    return "Not found", 404


@app.route('/channel/revit_element_mask')
def serve_revit_element_mask():
    """Serve the Revit element mask."""
    path = state.out_dir / "revit_element_mask.png"
    if path.exists():
        return send_file(path, mimetype='image/png')
    return "Not found", 404


@app.route('/api/set_result_as_base', methods=['POST'])
def set_result_as_base():
    """
    Copy the enhanced result to become the new base image.
    This enables iterative enhancement workflows.
    """
    import shutil

    enhanced_path = state.out_dir / "enhanced.png"
    base_path = state.out_dir / "base.png"

    if not enhanced_path.exists():
        return jsonify({"error": "No enhanced result found. Run enhancement first."}), 404

    try:
        # Backup old base if it exists
        if base_path.exists():
            backup_path = state.out_dir / f"base_backup_{int(time.time())}.png"
            shutil.copy(base_path, backup_path)
            print(f"Backed up old base to {backup_path}")

        # Copy enhanced to base
        shutil.copy(enhanced_path, base_path)
        print(f"Set enhanced result as new base image")

        return jsonify({
            "status": "ok",
            "message": "Enhanced result is now the base image",
            "base_path": str(base_path)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/revit/enhance_with_mask', methods=['POST'])
def revit_enhance_with_mask():
    """
    Enhance the base image using the Revit element mask.
    Supports multiple enhancement modes: inpaint, img2img, controlnet.
    """
    data = request.json or {}
    mode = data.get('mode', 'inpaint')  # inpaint, img2img, controlnet
    model = data.get('model', 'sd15')  # sd15 or sdxl
    prompt = data.get('prompt', 'photorealistic, high quality, 4K')
    steps = data.get('steps', 30)
    strength = data.get('strength', 0.75)
    guidance = data.get('guidance', 7.5)
    invert_mask = data.get('invert', False)
    feather = data.get('feather', 15)  # Edge feathering in pixels
    color_match = data.get('color_match', True)  # Auto color matching
    controlnet_type = data.get('controlnet_type', 'depth')  # depth, canny, depth+canny
    controlnet_scale = data.get('controlnet_scale', 0.8)  # How strongly to follow control image

    t0 = time.time()

    # Load base image
    base_path = state.out_dir / "base.png"
    if not base_path.exists():
        return jsonify({"error": "No base image. Capture view from Revit first."}), 404

    base_img = Image.open(base_path).convert("RGB")
    original_size = base_img.size

    # Load mask
    mask_path = state.out_dir / "revit_element_mask.png"
    if not mask_path.exists():
        return jsonify({"error": "No element mask. Generate mask first."}), 404

    mask_img = Image.open(mask_path).convert("L")

    # Invert mask if requested (white = area to modify)
    if invert_mask:
        mask_img = Image.eval(mask_img, lambda x: 255 - x)

    # Apply feathering to mask edges for smoother blending
    if feather > 0:
        from PIL import ImageFilter
        mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=feather))

    try:
        import torch

        if mode == 'inpaint':
            if model == 'sdxl':
                # SDXL Inpainting - higher quality
                from diffusers import StableDiffusionXLInpaintPipeline
                print("Loading SDXL inpainting model (first time may download ~6GB)...")

                pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
                    "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                    variant="fp16" if torch.cuda.is_available() else None
                )
                pipe = optimize_pipeline(pipe)
                if torch.cuda.is_available():
                    pipe.enable_model_cpu_offload()
                clear_vram()

                # SDXL uses 1024x1024
                target_size = (1024, 1024)
                base_resized = base_img.resize(target_size, Image.LANCZOS)
                mask_resized = mask_img.resize(target_size, Image.LANCZOS)

                result = pipe(
                    prompt=prompt,
                    image=base_resized,
                    mask_image=mask_resized,
                    num_inference_steps=steps,
                    guidance_scale=guidance,
                    strength=0.99
                ).images[0]

            else:
                # SD 1.5 Inpainting - faster
                from diffusers import StableDiffusionInpaintPipeline

                pipe = StableDiffusionInpaintPipeline.from_pretrained(
                    "runwayml/stable-diffusion-inpainting",
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
                )
                pipe = optimize_pipeline(pipe)
                clear_vram()

                # SD 1.5 uses 512x512
                target_size = (512, 512)
                base_resized = base_img.resize(target_size, Image.LANCZOS)
                mask_resized = mask_img.resize(target_size, Image.LANCZOS)

                result = pipe(
                    prompt=prompt,
                    image=base_resized,
                    mask_image=mask_resized,
                    num_inference_steps=steps,
                    guidance_scale=guidance
                ).images[0]

            # Resize back to original
            result = result.resize(original_size, Image.LANCZOS)

            # Blend result with original using feathered mask for smooth edges
            result_array = np.array(result).astype(np.float32)
            base_array = np.array(base_img).astype(np.float32)
            mask_array = np.array(mask_img.resize(original_size, Image.LANCZOS)).astype(np.float32) / 255.0
            mask_array = mask_array[:, :, np.newaxis]

            # Blend: result where mask is white, base where mask is black
            blended = result_array * mask_array + base_array * (1 - mask_array)
            result = Image.fromarray(blended.astype(np.uint8))

        elif mode == 'img2img':
            # Use img2img with mask blending
            from diffusers import StableDiffusionImg2ImgPipeline

            pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
                "runwayml/stable-diffusion-v1-5",
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
            )
            pipe = optimize_pipeline(pipe)
            clear_vram()

            target_size = (512, 512)
            base_resized = base_img.resize(target_size, Image.LANCZOS)

            enhanced = pipe(
                prompt=prompt,
                image=base_resized,
                strength=strength,
                num_inference_steps=steps,
                guidance_scale=guidance
            ).images[0]

            enhanced = enhanced.resize(original_size, Image.LANCZOS)

            # Blend using mask - resize mask to match original size
            mask_resized = mask_img.resize(original_size, Image.LANCZOS)
            mask_array = np.array(mask_resized) / 255.0
            mask_array = mask_array[:, :, np.newaxis]

            base_array = np.array(base_img)
            enhanced_array = np.array(enhanced)

            result_array = (enhanced_array * mask_array + base_array * (1 - mask_array)).astype(np.uint8)
            result = Image.fromarray(result_array)

        elif mode == 'controlnet':
            # ControlNet mode - uses depth/edge maps for structural guidance
            from diffusers import ControlNetModel, StableDiffusionControlNetPipeline
            from diffusers import StableDiffusionControlNetInpaintPipeline
            import cv2

            # Load control images based on type
            control_images = []
            controlnets = []

            if 'depth' in controlnet_type:
                depth_path = state.out_dir / "depth.png"
                if not depth_path.exists():
                    return jsonify({"error": "No depth map. Render channels first."}), 404
                depth_img = Image.open(depth_path).convert("RGB")
                control_images.append(depth_img)

                print("Loading ControlNet depth model...")
                controlnet_depth = ControlNetModel.from_pretrained(
                    "lllyasviel/sd-controlnet-depth",
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
                )
                controlnets.append(controlnet_depth)

            if 'normal' in controlnet_type:
                # Normal map - surface direction for proper lighting/texture orientation
                # Note: image_channels saves as "normals.png", pyrender version saves as "normal.png"
                normal_path = state.out_dir / "normals.png"
                if not normal_path.exists():
                    # Try alternate name
                    normal_path = state.out_dir / "normal.png"
                if not normal_path.exists():
                    return jsonify({"error": "No normal map. Click 'Estimate Depth from Base' first."}), 404
                normal_img = Image.open(normal_path).convert("RGB")
                control_images.append(normal_img)

                print("Loading ControlNet normal model...")
                controlnet_normal = ControlNetModel.from_pretrained(
                    "lllyasviel/sd-controlnet-normal",
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
                )
                controlnets.append(controlnet_normal)

            if 'canny' in controlnet_type:
                # Generate canny edges from base image
                base_np = np.array(base_img)
                gray = cv2.cvtColor(base_np, cv2.COLOR_RGB2GRAY)
                edges = cv2.Canny(gray, 100, 200)
                canny_img = Image.fromarray(cv2.cvtColor(edges, cv2.COLOR_GRAY2RGB))
                control_images.append(canny_img)

                # Save canny for debugging
                canny_img.save(state.out_dir / "canny.png")

                print("Loading ControlNet canny model...")
                controlnet_canny = ControlNetModel.from_pretrained(
                    "lllyasviel/sd-controlnet-canny",
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
                )
                controlnets.append(controlnet_canny)

            if 'softedge' in controlnet_type:
                # Softedge/HED - softer edge detection, more creative freedom
                from controlnet_aux import HEDdetector
                hed = HEDdetector.from_pretrained('lllyasviel/Annotators')
                softedge_img = hed(base_img)
                control_images.append(softedge_img)

                softedge_img.save(state.out_dir / "softedge.png")

                print("Loading ControlNet softedge model...")
                controlnet_softedge = ControlNetModel.from_pretrained(
                    "lllyasviel/sd-controlnet-hed",
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
                )
                controlnets.append(controlnet_softedge)

            if 'lineart' in controlnet_type:
                # Lineart - clean line extraction
                from controlnet_aux import LineartDetector
                lineart = LineartDetector.from_pretrained('lllyasviel/Annotators')
                lineart_img = lineart(base_img)
                control_images.append(lineart_img)

                lineart_img.save(state.out_dir / "lineart.png")

                print("Loading ControlNet lineart model...")
                controlnet_lineart = ControlNetModel.from_pretrained(
                    "lllyasviel/control_v11p_sd15_lineart",
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
                )
                controlnets.append(controlnet_lineart)

            if 'mlsd' in controlnet_type:
                # MLSD - straight line detection, great for architecture
                from controlnet_aux import MLSDdetector
                mlsd = MLSDdetector.from_pretrained('lllyasviel/Annotators')
                mlsd_img = mlsd(base_img)
                control_images.append(mlsd_img)

                mlsd_img.save(state.out_dir / "mlsd.png")

                print("Loading ControlNet MLSD model...")
                controlnet_mlsd = ControlNetModel.from_pretrained(
                    "lllyasviel/sd-controlnet-mlsd",
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
                )
                controlnets.append(controlnet_mlsd)

            if 'tile' in controlnet_type:
                # Tile - preserves details while allowing texture changes
                # For tile, we use the base image directly as control
                control_images.append(base_img)

                print("Loading ControlNet tile model...")
                controlnet_tile = ControlNetModel.from_pretrained(
                    "lllyasviel/control_v11f1e_sd15_tile",
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
                )
                controlnets.append(controlnet_tile)

            if not controlnets:
                return jsonify({"error": "No valid controlnet type specified"}), 400

            # Use single or multi-controlnet
            if len(controlnets) == 1:
                controlnet = controlnets[0]
                control_image = control_images[0]
            else:
                controlnet = controlnets
                control_image = control_images

            # Load pipeline with ControlNet + inpainting support
            print("Loading ControlNet inpaint pipeline...")
            pipe = StableDiffusionControlNetInpaintPipeline.from_pretrained(
                "runwayml/stable-diffusion-inpainting",
                controlnet=controlnet,
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
            )
            pipe = optimize_pipeline(pipe)
            if torch.cuda.is_available():
                pipe.enable_model_cpu_offload()
            clear_vram()

            # Use larger resolution while maintaining aspect ratio (768 max dimension)
            # This significantly improves quality over fixed 512x512
            max_dim = 768
            w, h = original_size
            if w > h:
                target_w = max_dim
                target_h = int(h * max_dim / w)
                # Ensure divisible by 8 for SD
                target_h = (target_h // 8) * 8
            else:
                target_h = max_dim
                target_w = int(w * max_dim / h)
                target_w = (target_w // 8) * 8
            target_size = (target_w, target_h)
            print(f"Processing at {target_w}x{target_h} (original: {w}x{h})")

            base_resized = base_img.resize(target_size, Image.LANCZOS)
            mask_resized = mask_img.resize(target_size, Image.LANCZOS)

            if isinstance(control_image, list):
                control_resized = [img.resize(target_size, Image.LANCZOS) for img in control_image]
                # Per-controlnet scales for multi-controlnet (distribute around the base scale)
                # More controlnets = slightly lower individual scales to avoid over-control
                n_controls = len(control_resized)
                if n_controls > 1:
                    # Distribute scale: e.g., 0.6 with 2 controls -> [0.55, 0.55]
                    per_scale = controlnet_scale * 0.9  # Slightly reduce for multi
                    controlnet_scales = [per_scale] * n_controls
                    print(f"Multi-ControlNet: {n_controls} controls at scale {per_scale:.2f} each")
                else:
                    controlnet_scales = controlnet_scale
            else:
                control_resized = control_image.resize(target_size, Image.LANCZOS)
                controlnet_scales = controlnet_scale

            # Generate with ControlNet guidance
            result = pipe(
                prompt=prompt,
                image=base_resized,
                mask_image=mask_resized,
                control_image=control_resized,
                num_inference_steps=steps,
                guidance_scale=guidance,
                controlnet_conditioning_scale=controlnet_scales
            ).images[0]

            # Resize back and blend
            result = result.resize(original_size, Image.LANCZOS)

            result_array = np.array(result).astype(np.float32)
            base_array = np.array(base_img).astype(np.float32)
            mask_array = np.array(mask_img.resize(original_size, Image.LANCZOS)).astype(np.float32) / 255.0
            mask_array = mask_array[:, :, np.newaxis]

            blended = result_array * mask_array + base_array * (1 - mask_array)
            result = Image.fromarray(blended.astype(np.uint8))

        else:
            return jsonify({"error": f"Unknown mode: {mode}"}), 400

        # Auto color matching if enabled
        if color_match:
            print("Applying automatic color matching...")
            result = color_match_histogram(result, base_img, mask_img.resize(original_size, Image.LANCZOS))

        # Save result
        result_path = state.out_dir / "enhanced.png"
        result.save(result_path)

        # Free VRAM after generation
        clear_vram()

        elapsed = time.time() - t0

        # Return base64
        buffered = io.BytesIO()
        result.save(buffered, format="PNG")
        img_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

        return jsonify({
            "status": "ok",
            "time": elapsed,
            "mode": mode,
            "image": img_b64
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def color_match_histogram(source_img, target_img, mask_img=None):
    """
    Match the color distribution of source_img to target_img.
    If mask provided, only match colors in masked region.
    Uses histogram matching for better color consistency.
    """
    import cv2

    source = np.array(source_img).astype(np.float32)
    target = np.array(target_img).astype(np.float32)

    if mask_img is not None:
        mask = np.array(mask_img)
        if len(mask.shape) == 2:
            mask = mask[:, :, np.newaxis]
        mask = mask / 255.0
    else:
        mask = np.ones_like(source[:, :, :1])

    result = source.copy()

    # Match each channel
    for c in range(3):
        # Get pixels in masked region from source
        src_pixels = source[:, :, c][mask[:, :, 0] > 0.5]
        # Get pixels from target (use whole image as reference)
        tgt_pixels = target[:, :, c].flatten()

        if len(src_pixels) == 0:
            continue

        # Calculate mean and std
        src_mean, src_std = src_pixels.mean(), src_pixels.std() + 1e-6
        tgt_mean, tgt_std = tgt_pixels.mean(), tgt_pixels.std() + 1e-6

        # Normalize and rescale
        normalized = (source[:, :, c] - src_mean) / src_std
        matched = normalized * tgt_std + tgt_mean

        # Only apply to masked region
        result[:, :, c] = source[:, :, c] * (1 - mask[:, :, 0]) + matched * mask[:, :, 0]

    result = np.clip(result, 0, 255).astype(np.uint8)
    return Image.fromarray(result)


@app.route('/api/color_match', methods=['POST'])
def api_color_match():
    """
    Apply color matching to blend enhanced areas with the base image.
    """
    data = request.json or {}
    strength = data.get('strength', 1.0)  # 0-1, how much to apply color match

    t0 = time.time()

    # Load images
    base_path = state.out_dir / "base.png"
    enhanced_path = state.out_dir / "enhanced.png"
    mask_path = state.out_dir / "revit_element_mask.png"

    if not enhanced_path.exists():
        return jsonify({"error": "No enhanced image found"}), 404
    if not base_path.exists():
        return jsonify({"error": "No base image found"}), 404

    enhanced = Image.open(enhanced_path).convert("RGB")
    base = Image.open(base_path).convert("RGB")

    mask = None
    if mask_path.exists():
        mask = Image.open(mask_path).convert("L")

    # Apply color matching
    matched = color_match_histogram(enhanced, base, mask)

    # Blend based on strength
    if strength < 1.0:
        enhanced_arr = np.array(enhanced).astype(np.float32)
        matched_arr = np.array(matched).astype(np.float32)
        blended = enhanced_arr * (1 - strength) + matched_arr * strength
        matched = Image.fromarray(blended.astype(np.uint8))

    # Save result
    matched.save(enhanced_path)

    elapsed = time.time() - t0

    # Return base64
    buffered = io.BytesIO()
    matched.save(buffered, format="PNG")
    img_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

    return jsonify({
        "status": "ok",
        "time": elapsed,
        "strength": strength,
        "image": img_b64
    })


@app.route('/api/revit/extract_channels', methods=['POST'])
def revit_extract_channels():
    """
    Extract depth, normals, and element IDs from Revit-exported OBJ.
    Uses the camera from Revit's camera.json for perfect alignment.
    """
    data = request.json or {}
    width = data.get('width', 960)
    height = data.get('height', 540)

    t0 = time.time()

    # Load Revit OBJ
    obj_path = Path(r"C:\Users\jerro\Desktop\channel_test\element_ids.obj")
    cam_path = Path(r"C:\Users\jerro\Desktop\channel_test\camera.json")

    if not obj_path.exists():
        return jsonify({"error": f"Revit OBJ not found: {obj_path}. Export from Revit first."}), 404

    try:
        import pyrender
        import trimesh

        # Load mesh
        print(f"Loading Revit OBJ: {obj_path}")
        scene_or_mesh = trimesh.load(str(obj_path), process=False)

        if isinstance(scene_or_mesh, trimesh.Scene):
            meshes = list(scene_or_mesh.geometry.values())
            combined = trimesh.util.concatenate(meshes)
        else:
            combined = scene_or_mesh

        # Load camera
        cam_data = None
        if cam_path.exists():
            with open(cam_path, 'r') as f:
                cam_data = json.load(f)
            print(f"Loaded camera from {cam_path}")

        # Setup pyrender scene
        render_scene = pyrender.Scene(bg_color=[0, 0, 0, 0])

        # Add mesh with default material for depth/normals
        mesh = pyrender.Mesh.from_trimesh(combined)
        render_scene.add(mesh)

        # Setup camera
        if cam_data and cam_data.get('IsPerspective', True):
            fov = cam_data.get('FieldOfView', 0.785)
            camera = pyrender.PerspectiveCamera(yfov=fov, aspectRatio=width/height)

            eye = np.array(cam_data['Eye'])
            forward = np.array(cam_data['Forward'])
            up = np.array(cam_data['Up'])

            # Build camera matrix
            forward = forward / np.linalg.norm(forward)
            right = np.cross(forward, up)
            right = right / np.linalg.norm(right)
            up = np.cross(right, forward)

            camera_pose = np.eye(4)
            camera_pose[:3, 0] = right
            camera_pose[:3, 1] = up
            camera_pose[:3, 2] = -forward
            camera_pose[:3, 3] = eye
        else:
            # Fallback to auto camera
            bounds = combined.bounds
            center = (bounds[0] + bounds[1]) / 2
            size = np.linalg.norm(bounds[1] - bounds[0])

            camera = pyrender.PerspectiveCamera(yfov=np.pi/4, aspectRatio=width/height)
            camera_pose = np.eye(4)
            camera_pose[:3, 3] = center + np.array([0, 0, size])

        render_scene.add(camera, pose=camera_pose)

        # Add light
        light = pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=3.0)
        render_scene.add(light, pose=camera_pose)

        # Render depth
        renderer = pyrender.OffscreenRenderer(width, height)
        _, depth = renderer.render(render_scene)

        # Normalize depth
        valid_depth = depth[depth > 0]
        if len(valid_depth) > 0:
            d_min, d_max = valid_depth.min(), valid_depth.max()
            depth_normalized = np.zeros_like(depth)
            mask = depth > 0
            depth_normalized[mask] = 1.0 - (depth[mask] - d_min) / (d_max - d_min + 1e-6)
            depth_img = (depth_normalized * 255).astype(np.uint8)
        else:
            depth_img = np.zeros((height, width), dtype=np.uint8)

        # Save depth
        depth_pil = Image.fromarray(depth_img)
        depth_path = state.out_dir / "depth.png"
        depth_pil.save(depth_path)

        # Generate normal map from depth (screen-space normals)
        # This computes surface normals from the depth gradient
        import cv2

        depth_float = depth_normalized.astype(np.float32)

        # Compute gradients
        dzdx = cv2.Sobel(depth_float, cv2.CV_32F, 1, 0, ksize=3)
        dzdy = cv2.Sobel(depth_float, cv2.CV_32F, 0, 1, ksize=3)

        # Create normal vectors (x, y, z)
        normal = np.zeros((height, width, 3), dtype=np.float32)
        normal[:, :, 0] = -dzdx  # X component
        normal[:, :, 1] = -dzdy  # Y component
        normal[:, :, 2] = 1.0    # Z component (pointing toward camera)

        # Normalize vectors
        norm = np.sqrt(np.sum(normal ** 2, axis=2, keepdims=True)) + 1e-6
        normal = normal / norm

        # Convert to 0-255 range (standard normal map encoding)
        # X: -1 to 1 -> 0 to 255 (red)
        # Y: -1 to 1 -> 0 to 255 (green)
        # Z: 0 to 1 -> 128 to 255 (blue, typically pointing out)
        normal_img = np.zeros((height, width, 3), dtype=np.uint8)
        normal_img[:, :, 0] = ((normal[:, :, 0] + 1) * 0.5 * 255).astype(np.uint8)  # R
        normal_img[:, :, 1] = ((normal[:, :, 1] + 1) * 0.5 * 255).astype(np.uint8)  # G
        normal_img[:, :, 2] = ((normal[:, :, 2] + 1) * 0.5 * 255).astype(np.uint8)  # B

        # Apply mask - set background to neutral normal (128, 128, 255)
        background = depth == 0
        normal_img[background] = [128, 128, 255]

        normal_pil = Image.fromarray(normal_img)
        normal_path = state.out_dir / "normal.png"
        normal_pil.save(normal_path)

        renderer.delete()

        elapsed = time.time() - t0

        return jsonify({
            "status": "ok",
            "time": elapsed,
            "channels": ["depth", "normal"],
            "resolution": [width, height]
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/revit/render_mask', methods=['POST'])
def revit_render_mask_from_geometry():
    """
    Render a mask from 3D geometry using the current camera.
    This ensures masks are always accurate regardless of view changes.

    POST body:
        element_ids: list of element IDs to include in mask (optional)
        categories: list of categories to include, e.g. ["Walls", "Roofs"] (optional)
        invert: bool - invert the mask (optional)
        feather: int - feather radius in pixels (optional)
        width/height: resolution (optional)

    If neither element_ids nor categories specified, uses element_id_map.json selection.
    """
    data = request.json or {}
    element_ids = data.get('element_ids', [])
    categories = data.get('categories', [])
    invert = data.get('invert', False)
    feather = data.get('feather', 0)
    width = data.get('width', 960)
    height = data.get('height', 540)

    t0 = time.time()

    obj_path = Path(r"C:\Users\jerro\Desktop\channel_test\element_ids.obj")
    mtl_path = Path(r"C:\Users\jerro\Desktop\channel_test\element_ids.mtl")
    map_path = Path(r"C:\Users\jerro\Desktop\channel_test\element_id_map.json")
    cam_path = Path(r"C:\Users\jerro\Desktop\channel_test\camera.json")

    if not obj_path.exists():
        return jsonify({"error": "element_ids.obj not found. Export from Revit first."}), 404

    try:
        import pyrender
        import trimesh

        # Load element ID map
        element_map = {}
        if map_path.exists():
            with open(map_path, 'r') as f:
                element_map = json.load(f)

        # Determine which elements to include in mask
        target_element_ids = set()

        if element_ids:
            target_element_ids = set(element_ids)
        elif categories:
            # Find all elements matching the categories
            for key, info in element_map.items():
                if info.get('Category') in categories:
                    target_element_ids.add(info.get('ElementId'))

        if not target_element_ids:
            return jsonify({"error": "No elements specified. Provide element_ids or categories."}), 400

        print(f"Rendering mask for {len(target_element_ids)} elements: {list(target_element_ids)[:5]}...")

        # Load OBJ with materials to get per-element meshes
        scene_or_mesh = trimesh.load(str(obj_path), process=False)

        # Build a mesh containing only target elements
        target_meshes = []

        if isinstance(scene_or_mesh, trimesh.Scene):
            for name, geom in scene_or_mesh.geometry.items():
                # Extract element ID from mesh name (format: elem_XXXXX or similar)
                elem_id = None
                if name.startswith('elem_'):
                    try:
                        elem_id = int(name.split('_')[1])
                    except:
                        pass

                # Also check by material color matching
                if elem_id is None and hasattr(geom, 'visual') and hasattr(geom.visual, 'material'):
                    mat = geom.visual.material
                    if hasattr(mat, 'diffuse'):
                        color = mat.diffuse[:3]
                        # Find matching element by color
                        for key, info in element_map.items():
                            if info.get('Color') == list(color):
                                elem_id = info.get('ElementId')
                                break

                if elem_id in target_element_ids:
                    target_meshes.append(geom)
        else:
            # Single mesh - need to filter by vertex colors or materials
            target_meshes = [scene_or_mesh]

        if not target_meshes:
            return jsonify({"error": "No matching geometry found for specified elements."}), 404

        # Combine target meshes
        combined = trimesh.util.concatenate(target_meshes) if len(target_meshes) > 1 else target_meshes[0]

        # Load camera
        cam_data = None
        if cam_path.exists():
            with open(cam_path, 'r') as f:
                cam_data = json.load(f)

        # Setup pyrender scene - white material on black background for mask
        render_scene = pyrender.Scene(bg_color=[0, 0, 0, 255])

        # Create white material for mask
        white_material = pyrender.MetallicRoughnessMaterial(
            baseColorFactor=[1.0, 1.0, 1.0, 1.0],
            metallicFactor=0.0,
            roughnessFactor=1.0
        )

        mesh = pyrender.Mesh.from_trimesh(combined, material=white_material)
        render_scene.add(mesh)

        # Setup camera from Revit
        if cam_data and cam_data.get('IsPerspective', True):
            fov = cam_data.get('FieldOfView', 0.785)
            camera = pyrender.PerspectiveCamera(yfov=fov, aspectRatio=width/height)

            eye = np.array(cam_data['Eye'])
            forward = np.array(cam_data['Forward'])
            up = np.array(cam_data['Up'])

            forward = forward / np.linalg.norm(forward)
            right = np.cross(forward, up)
            right = right / np.linalg.norm(right)
            up = np.cross(right, forward)

            camera_pose = np.eye(4)
            camera_pose[:3, 0] = right
            camera_pose[:3, 1] = up
            camera_pose[:3, 2] = -forward
            camera_pose[:3, 3] = eye
        else:
            bounds = combined.bounds
            center = (bounds[0] + bounds[1]) / 2
            size = np.linalg.norm(bounds[1] - bounds[0])
            camera = pyrender.PerspectiveCamera(yfov=np.pi/4, aspectRatio=width/height)
            camera_pose = np.eye(4)
            camera_pose[:3, 3] = center + np.array([0, 0, size])

        render_scene.add(camera, pose=camera_pose)

        # Add strong ambient light for flat mask
        light = pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=5.0)
        render_scene.add(light, pose=camera_pose)

        # Render
        renderer = pyrender.OffscreenRenderer(width, height)
        color, _ = renderer.render(render_scene)
        renderer.delete()

        # Convert to grayscale mask
        mask = np.mean(color[:, :, :3], axis=2).astype(np.uint8)

        # Invert if requested
        if invert:
            mask = 255 - mask

        # Feather if requested
        if feather > 0:
            from scipy.ndimage import gaussian_filter
            mask = gaussian_filter(mask.astype(float), sigma=feather).astype(np.uint8)

        # Save mask (use element_mask.png so UI can display it)
        mask_img = Image.fromarray(mask)
        mask_path = state.out_dir / "element_mask.png"
        mask_img.save(mask_path)

        # Also save as geometry_mask for reference
        geometry_mask_path = state.out_dir / "geometry_mask.png"
        mask_img.save(geometry_mask_path)

        elapsed = time.time() - t0

        # Return base64
        buffered = io.BytesIO()
        mask_img.save(buffered, format="PNG")
        mask_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

        return jsonify({
            "status": "ok",
            "time": elapsed,
            "element_count": len(target_element_ids),
            "categories": categories,
            "resolution": [width, height],
            "mask": mask_b64
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/revit/sync_camera', methods=['POST'])
def revit_sync_camera():
    """
    Update the camera.json from current Revit view.
    Call this before rendering masks to ensure camera alignment.
    """
    # This endpoint would be called from Revit via the MCP
    # For now, just return the current camera state
    cam_path = Path(r"C:\Users\jerro\Desktop\channel_test\camera.json")

    if cam_path.exists():
        with open(cam_path, 'r') as f:
            cam_data = json.load(f)
        return jsonify({
            "status": "ok",
            "camera": cam_data,
            "message": "Camera loaded. Export new camera.json from Revit to update."
        })
    else:
        return jsonify({
            "status": "no_camera",
            "message": "No camera.json found. Export from Revit first."
        })


# ============================================================
# AI SEGMENTATION - Generate masks from images using AI
# ============================================================
@app.route('/api/ai_segment', methods=['POST'])
def ai_segment():
    """
    Generate semantic segmentation masks from an uploaded image using AI.
    Uses SAM (Segment Anything) or OneFormer for accurate segmentation.
    Falls back to heuristic method if AI models unavailable.

    POST body:
        target: "sky" | "building" | "ground" | "exterior" | "vegetation"
        method: "auto" | "sam" | "oneformer" | "heuristic" (default: auto)
        feather: int - feather radius in pixels (default 10)
        invert: bool - invert the mask
        points: [[x,y], ...] - optional click points for SAM point-based segmentation
    """
    import time
    t0 = time.time()

    try:
        from ai_segmentation import segment_image

        data = request.json or {}
        target = data.get('target', 'sky')
        method = data.get('method', 'auto')
        feather = int(data.get('feather', 10))
        sharpen = float(data.get('sharpen', 0.0))
        invert = data.get('invert', False)
        points = data.get('points', None)

        # Get base image
        base_path = state.out_dir / "base.png"
        if not base_path.exists():
            return jsonify({"error": "No base image. Upload an image first."}), 404

        base_img = Image.open(base_path).convert('RGB')
        width, height = base_img.size

        print(f"AI Segmentation: target={target}, method={method}, feather={feather}, sharpen={sharpen}")

        # Run segmentation
        mask, method_used = segment_image(
            base_img,
            target=target,
            method=method,
            feather=feather,
            sharpen=sharpen,
            points=points
        )

        if mask is None:
            return jsonify({"error": f"Segmentation failed for {target}"}), 500

        # Invert if requested
        if invert:
            mask = 255 - mask

        # Convert to PIL Image
        mask_img = Image.fromarray(mask)

        # Save mask
        mask_path = state.out_dir / "ai_mask.png"
        mask_img.save(mask_path)

        # Also save as element_mask for compatibility with enhance functions
        element_mask_path = state.out_dir / "element_mask.png"
        mask_img.save(element_mask_path)

        elapsed = time.time() - t0

        # Return base64
        buffered = io.BytesIO()
        mask_img.save(buffered, format="PNG")
        mask_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

        # Calculate coverage percentage
        coverage = np.mean(mask) / 255 * 100

        return jsonify({
            "status": "ok",
            "time": elapsed,
            "target": target,
            "method": method_used,
            "coverage": round(coverage, 1),
            "resolution": [width, height],
            "mask": mask_b64
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/ai_mask_invert', methods=['POST'])
def ai_mask_invert():
    """Invert the current AI mask."""
    try:
        mask_path = state.out_dir / "ai_mask.png"
        if not mask_path.exists():
            mask_path = state.out_dir / "element_mask.png"

        if not mask_path.exists():
            return jsonify({"error": "No mask to invert"}), 404

        mask_img = Image.open(mask_path).convert('L')
        mask_arr = np.array(mask_img)
        inverted = 255 - mask_arr

        inverted_img = Image.fromarray(inverted)
        inverted_img.save(state.out_dir / "ai_mask.png")
        inverted_img.save(state.out_dir / "element_mask.png")

        # Return base64
        buffered = io.BytesIO()
        inverted_img.save(buffered, format="PNG")
        mask_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

        coverage = np.mean(inverted) / 255 * 100

        return jsonify({
            "status": "ok",
            "coverage": round(coverage, 1),
            "mask": mask_b64
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/save_edited_mask', methods=['POST'])
def save_edited_mask():
    """Save an edited mask from the canvas."""
    try:
        data = request.json
        mask_b64 = data.get('mask')

        if not mask_b64:
            return jsonify({"error": "No mask data provided"}), 400

        # Decode base64 mask
        mask_data = base64.b64decode(mask_b64)
        mask_img = Image.open(io.BytesIO(mask_data)).convert('L')

        # Save as both ai_mask and element_mask for compatibility
        mask_img.save(state.out_dir / "ai_mask.png")
        mask_img.save(state.out_dir / "element_mask.png")

        # Calculate coverage
        mask_arr = np.array(mask_img)
        coverage = np.mean(mask_arr) / 255 * 100

        return jsonify({
            "status": "ok",
            "coverage": round(coverage, 1),
            "message": "Custom mask saved"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
# GPU MEMORY MANAGEMENT
# ============================================================
@app.route('/api/gpu/status', methods=['GET'])
def gpu_status():
    """Get current GPU memory status."""
    try:
        from gpu_memory import get_vram_info, get_loaded_models
        info = get_vram_info()
        info["loaded_models"] = list(get_loaded_models())
        return jsonify(info)
    except ImportError:
        return jsonify({"error": "GPU memory module not available"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/gpu/cleanup', methods=['POST'])
def gpu_cleanup():
    """
    Force GPU memory cleanup.

    POST body:
        force: bool - if true, also unloads cached models (default: false)
    """
    try:
        from gpu_memory import cleanup_gpu, get_vram_info

        data = request.json or {}
        force = data.get('force', False)

        result = cleanup_gpu(force=force)

        return jsonify({
            "status": "ok",
            "freed_gb": round(result.get("freed_gb", 0), 2),
            "before": result.get("before", {}),
            "after": result.get("after", {})
        })
    except ImportError:
        # Fallback if module not available
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except:
            pass
        return jsonify({"status": "ok", "message": "Basic cleanup done"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/gpu/unload_models', methods=['POST'])
def gpu_unload_models():
    """Unload all AI models from GPU to free memory."""
    try:
        from gpu_memory import cleanup_gpu
        from ai_segmentation import unload_models as unload_seg

        # Unload segmentation models
        unload_seg()

        # Force cleanup
        result = cleanup_gpu(force=True)

        return jsonify({
            "status": "ok",
            "message": "All models unloaded",
            "freed_gb": round(result.get("freed_gb", 0), 2)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/channel/ai_mask')
def serve_ai_mask():
    """Serve the AI-generated mask."""
    mask_path = state.out_dir / "ai_mask.png"
    if mask_path.exists():
        return send_file(mask_path, mimetype='image/png')
    return "Not found", 404


# ============================================================
# EXPORT FOR TRAINING - Extract regions for LoRA training
# ============================================================
@app.route('/api/export_for_training', methods=['POST'])
def export_for_training():
    """
    Export current image as training data for LoRA.

    Automatically segments and saves:
    - Full scene (complete_scenes/)
    - Sky region (skies/)
    - Vegetation region (vegetation/)
    - Ground region (ground/)

    Each image gets a caption .txt file for training.

    POST body:
        project_name: Optional name for the project (used in captions)
        categories: List of categories to export (default: all)
        min_coverage: Minimum mask coverage % to save (default: 5)
    """
    from datetime import datetime

    data = request.json or {}
    project_name = data.get('project_name', 'archviz_render')
    categories = data.get('categories', ['complete_scenes', 'skies', 'vegetation', 'ground'])
    min_coverage = float(data.get('min_coverage', 5))

    # Training data output directory
    training_dir = Path(__file__).parent.parent / "training" / "data" / "raw"
    training_dir.mkdir(parents=True, exist_ok=True)

    # Get base image
    base_path = state.out_dir / "base.png"
    if not base_path.exists():
        return jsonify({"error": "No base image. Upload an image first."}), 404

    base_img = Image.open(base_path).convert('RGB')
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    exported = []
    errors = []

    try:
        from ai_segmentation import segment_image

        # 1. Save complete scene
        if 'complete_scenes' in categories:
            scene_dir = training_dir / "complete_scenes"
            scene_dir.mkdir(exist_ok=True)

            filename = f"{project_name}_{timestamp}_scene.png"
            filepath = scene_dir / filename

            # Resize to training size (1024 max dimension)
            img_resized = resize_for_training(base_img, 1024)
            img_resized.save(filepath)

            # Save caption
            caption = f"archviz exterior render, architectural visualization, professional 3D render, {project_name}"
            (scene_dir / f"{filename[:-4]}.txt").write_text(caption)

            exported.append({"category": "complete_scenes", "file": filename})

        # 2. Extract sky
        if 'skies' in categories:
            try:
                mask, method = segment_image(base_img, target='sky', method='auto', feather=0)
                if mask is not None:
                    coverage = np.mean(mask) / 255 * 100
                    if coverage >= min_coverage:
                        sky_dir = training_dir / "skies"
                        sky_dir.mkdir(exist_ok=True)

                        # Extract sky region
                        sky_img = extract_masked_region(base_img, mask)
                        if sky_img:
                            filename = f"{project_name}_{timestamp}_sky.png"
                            sky_img.save(sky_dir / filename)

                            caption = "archviz sky, architectural visualization, sky gradient, soft clouds, professional render style"
                            (sky_dir / f"{filename[:-4]}.txt").write_text(caption)

                            exported.append({"category": "skies", "file": filename, "coverage": round(coverage, 1)})
            except Exception as e:
                errors.append(f"Sky: {str(e)}")

        # 3. Extract vegetation
        if 'vegetation' in categories:
            try:
                mask, method = segment_image(base_img, target='vegetation', method='auto', feather=0)
                if mask is not None:
                    coverage = np.mean(mask) / 255 * 100
                    if coverage >= min_coverage:
                        veg_dir = training_dir / "vegetation"
                        veg_dir.mkdir(exist_ok=True)

                        veg_img = extract_masked_region(base_img, mask)
                        if veg_img:
                            filename = f"{project_name}_{timestamp}_vegetation.png"
                            veg_img.save(veg_dir / filename)

                            caption = "archviz vegetation, architectural visualization, stylized trees, landscaping, professional render style"
                            (veg_dir / f"{filename[:-4]}.txt").write_text(caption)

                            exported.append({"category": "vegetation", "file": filename, "coverage": round(coverage, 1)})
            except Exception as e:
                errors.append(f"Vegetation: {str(e)}")

        # 4. Extract ground
        if 'ground' in categories:
            try:
                mask, method = segment_image(base_img, target='ground', method='auto', feather=0)
                if mask is not None:
                    coverage = np.mean(mask) / 255 * 100
                    if coverage >= min_coverage:
                        ground_dir = training_dir / "ground"
                        ground_dir.mkdir(exist_ok=True)

                        ground_img = extract_masked_region(base_img, mask)
                        if ground_img:
                            filename = f"{project_name}_{timestamp}_ground.png"
                            ground_img.save(ground_dir / filename)

                            caption = "archviz ground, architectural visualization, lawn, paving, professional render style"
                            (ground_dir / f"{filename[:-4]}.txt").write_text(caption)

                            exported.append({"category": "ground", "file": filename, "coverage": round(coverage, 1)})
            except Exception as e:
                errors.append(f"Ground: {str(e)}")

        return jsonify({
            "status": "ok",
            "exported": exported,
            "errors": errors if errors else None,
            "output_dir": str(training_dir)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def resize_for_training(img: Image.Image, max_size: int = 1024) -> Image.Image:
    """Resize image keeping aspect ratio, max dimension = max_size."""
    w, h = img.size
    if max(w, h) <= max_size:
        return img

    if w > h:
        new_w = max_size
        new_h = int(h * max_size / w)
    else:
        new_h = max_size
        new_w = int(w * max_size / h)

    return img.resize((new_w, new_h), Image.Resampling.LANCZOS)


def extract_masked_region(img: Image.Image, mask: np.ndarray, padding: int = 50) -> Image.Image:
    """
    Extract the masked region with some padding.
    Returns cropped image or None if region too small.
    """
    # Find bounding box of mask
    rows = np.any(mask > 128, axis=1)
    cols = np.any(mask > 128, axis=0)

    if not np.any(rows) or not np.any(cols):
        return None

    y_min, y_max = np.where(rows)[0][[0, -1]]
    x_min, x_max = np.where(cols)[0][[0, -1]]

    # Add padding
    h, w = mask.shape
    y_min = max(0, y_min - padding)
    y_max = min(h, y_max + padding)
    x_min = max(0, x_min - padding)
    x_max = min(w, x_max + padding)

    # Check minimum size
    if (x_max - x_min) < 128 or (y_max - y_min) < 128:
        return None

    # Crop
    cropped = img.crop((x_min, y_min, x_max, y_max))

    # Resize for training
    return resize_for_training(cropped, 1024)


@app.route('/api/training_stats', methods=['GET'])
def training_stats():
    """Get counts of training images per category."""
    training_dir = Path(__file__).parent.parent / "training" / "data" / "raw"

    counts = {}
    categories = ['complete_scenes', 'skies', 'vegetation', 'ground', 'people']

    for cat in categories:
        cat_dir = training_dir / cat
        if cat_dir.exists():
            # Count .png files
            count = len(list(cat_dir.glob("*.png")))
            if count > 0:
                counts[cat] = count

    return jsonify({
        "status": "ok",
        "counts": counts,
        "path": str(training_dir)
    })


# Pre-load default mesh
DEFAULT_MESH = "C:\\Users\\jerro\\Desktop\\channel_test\\Small gothic cottage JR 3D View.obj"
if Path(DEFAULT_MESH).exists():
    load_mesh(DEFAULT_MESH)

print("\n=== SERVER READY ===")
print("Open http://localhost:5000")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=False)