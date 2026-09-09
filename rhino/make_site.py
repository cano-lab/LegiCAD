"""Generate the LegiCAD starter Rhino file.

Creates rhino/LegiCAD_Site.3dm containing:
  - Layer "SiteBoundary": a closed polyline lot, 15m frontage x 30m depth
    (450 sqm — the exact R1 minimum lot from sudbury_r1_constraints.json)
  - Layer "Reference": setback offset curves (front 6m / rear 7.5m / sides 1.2m)
    as visual guides, and a street line along the front edge
  - Model units: meters
"""

import rhino3dm

W = 15.0   # frontage (m), along X
D = 30.0   # depth (m), along Y
FRONT, REAR, SIDE = 6.0, 7.5, 1.2

model = rhino3dm.File3dm()
model.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Meters

# Layers
layer_site = rhino3dm.Layer()
layer_site.Name = "SiteBoundary"
layer_site.Color = (0, 0, 0, 255)
model.Layers.Add(layer_site)

layer_ref = rhino3dm.Layer()
layer_ref.Name = "Reference"
layer_ref.Color = (150, 150, 150, 255)
model.Layers.Add(layer_ref)

def polyline(points, layer_name, name=None):
    """Closed polyline from (x, y) tuples, on the named layer."""
    pl = rhino3dm.Polyline(len(points) + 1)
    for x, y in points:
        pl.Add(x, y, 0.0)
    x0, y0 = points[0]
    pl.Add(x0, y0, 0.0)  # close
    attrs = rhino3dm.ObjectAttributes()
    attrs.LayerIndex = next(
        i for i, l in enumerate(model.Layers) if l.Name == layer_name
    )
    if name:
        attrs.Name = name
    curve = rhino3dm.PolylineCurve(pl)
    model.Objects.AddCurve(curve, attrs)
    return curve

# Lot boundary: front lot line along Y=0 (street side), lot extends +Y
polyline(
    [(0, 0), (W, 0), (W, D), (0, D)],
    "SiteBoundary",
    name="Lot_15x30_R1",
)

# Street centerline guide in front of the lot
street = rhino3dm.Polyline(2)
street.Add(-5.0, -3.0, 0.0)
street.Add(W + 5.0, -3.0, 0.0)
attrs = rhino3dm.ObjectAttributes()
attrs.LayerIndex = next(i for i, l in enumerate(model.Layers) if l.Name == "Reference")
attrs.Name = "StreetLine"
model.Objects.AddCurve(rhino3dm.PolylineCurve(street), attrs)

# Setback envelope guide (true R1 setbacks, not the simplified uniform inset)
polyline(
    [
        (SIDE, FRONT),
        (W - SIDE, FRONT),
        (W - SIDE, D - REAR),
        (SIDE, D - REAR),
    ],
    "Reference",
    name="R1_SetbackEnvelope",
)

# Text dot labels
def dot(text, x, y):
    attrs = rhino3dm.ObjectAttributes()
    attrs.LayerIndex = next(i for i, l in enumerate(model.Layers) if l.Name == "Reference")
    model.Objects.AddTextDot(text, rhino3dm.Point3d(x, y, 0.0), attrs)

dot("FRONT (street) — 6.0m setback", W / 2, -1.0)
dot("REAR — 7.5m setback", W / 2, D + 1.0)

out = "rhino/LegiCAD_Site.3dm"
model.Write(out, 8)
print("Wrote", out)
