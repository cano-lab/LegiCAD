print("=== DEBUG SHADOW ===")
import numpy as np
from PIL import Image
from channel_extractor import ChannelExtractor, ViewExportData

test_data = {
    "GeometryPath": "C:\\Users\\jerro\\Desktop\\channel_test\\Small gothic cottage JR 3D View.obj",
    "Camera": {
        "Eye": [100, 50, 30],
        "Forward": [-0.7, -0.5, -0.2],
        "Up": [0, 0, 1],
        "IsPerspective": True,
        "FieldOfView": 0.785,
        "NearClip": 0.1,
        "FarClip": 10000
    },
    "MaterialMap": {},
    "BoundingBox": [0, 0, 0, 200, 200, 50]
}

export_data = ViewExportData.from_revit_response(test_data)
extractor = ChannelExtractor(export_data)

# Check depth buffer
depth = extractor._render_depth_buffer((960, 540))
print(f"Depth min: {depth.min()}, max: {depth.max()}")
print(f"Non-zero pixels: {np.sum(depth > 0.1)}")

# Check mesh
mesh = extractor.mesh
if hasattr(mesh, 'dump'):
    mesh = mesh.dump(concatenate=True)
print(f"Mesh vertices: {len(mesh.vertices)}")
print(f"Mesh bounds: {mesh.bounds}")