# Grasshopper Prototype Status

## Overview

The Grasshopper prototype (`/workspace/rhino/`) provides a working Rhino/Grasshopper implementation of the LegiCAD regime script for testing UX friction points before full Rust implementation.

## What's Available

### Files

| File | Purpose |
|------|---------|
| `LegiCAD_RegimeScript.cs` | C# script for Grasshopper C# Script component (v0.2, zero dependencies) |
| `sudbury_r1_constraints.json` | Sudbury R1 residential zoning constraints |
| `LegiCAD_Site.3dm` | Starter Rhino file: 15m × 30m lot with setback guides |
| `make_site.py` | Regenerates the starter site (requires `pip install rhino3dm`) |

### Current Features (v0.2)

✅ **Inputs:**
- Site boundary (closed curve)
- JSON path to zoning constraints
- Unit count (slider 1-4)
- Ceiling height (slider 2.4-3.0m)
- Target unit size (slider 60-120 sqm)

✅ **Outputs:**
- 3D massing Brep
- Envelope Brep (setbacks + max height)
- Compliance report (text)
- IsValid boolean
- Debug info

✅ **Functionality:**
- Loads Sudbury R1 zoning from JSON
- Calculates setback envelope
- Generates program-driven massing
- Validates against coverage and FSR limits
- Reports violations and warnings

### Known Limitations

⚠️ **Simplified setback model**: Uses uniform inset (minimum of all setbacks) rather than distinguishing front/rear/side edges. True R1 envelope is larger on side yards.

⚠️ **No edge classification**: Cannot identify which lot line is the front (street-facing) vs rear vs sides. Requires lot orientation logic.

⚠️ **No corner-lot logic**: Doesn't handle `side_exterior` setback for corner lots.

⚠️ **No parking layout check**: Doesn't verify 2 spaces/unit (2.6m × 5.2m each) fit on site.

⚠️ **No floor-plate slicing**: Massing is a single extruded volume, not sliced into per-storey floor plates.

⚠️ **No interactive sculpting**: User cannot manually carve exclusion zones or push/pull faces.

## How to Use

### 1. Open the Starter Site

```bash
# In Rhino 8
Open LegiCAD_Site.3dm
```

This contains:
- **Layer `SiteBoundary`**: Closed polyline lot (15m × 30m = 450 sqm, R1 minimum)
- **Layer `Reference`**: True R1 setback envelope (6m front / 7.5m rear / 1.2m sides), street line, labels

### 2. Create Grasshopper Component

1. Run `Grasshopper` in Rhino
2. Add **C# Script** component (Maths → Script → C# Script)
3. Double-click to open editor
4. Delete default code
5. Paste entire contents of `LegiCAD_RegimeScript.cs`
6. Click **OK**

No assembly references needed — v0.2 uses embedded MiniJson parser.

### 3. Set Up Inputs

Right-click inputs and rename:

| Input | Rename To | Type Hint | Wire To |
|-------|-----------|-----------|---------|
| `x` | `SiteBoundary` | Curve | Curve param → lot polyline |
| `y` | `JsonPath` | (string) | Panel with path to `sudbury_r1_constraints.json` |

Add three more inputs (`z+` button):

| Input | Rename To | Type Hint | Wire To |
|-------|-----------|-----------|---------|
| `z` | `UnitCount` | int | Integer slider (1-4) |
| + | `CeilingHeight` | double | Number slider (2.4-3.0) |
| + | `TargetUnitSize` | double | Number slider (60-120) |

**Names must match exactly** — Grasshopper binds by name to `RunScript` arguments.

### 4. Set Up Outputs

Rename outputs (`out`, `a`) and add more (`z+`):

| Output | Rename To | Wire To |
|--------|-----------|---------|
| `out` | `Massing` | Preview (automatic) |
| `a` | `Envelope` | Preview (automatic) |
| + | `Compliance` | Panel (Params → Input → Panel) |
| + | `IsValid` | Panel |
| + | `DebugInfo` | Panel |

### 5. Run It

```
[Curve param: lot] ──── SiteBoundary ─┐
[Panel: JSON path] ──── JsonPath ─────┤
[Slider 1–4] ────────── UnitCount ────┤                  ├─ Massing
[Slider 2.4–3.0] ────── CeilingHeight ┼──[C# Script]─────┼─ Envelope
[Slider 60–120] ─────── TargetUnitSize┘                  ├─ Compliance → Panel
                                                       ├─ IsValid → Panel
                                                       └─ DebugInfo → Panel
```

**Expected result** with defaults (1 unit, 80 sqm, 2.7m ceilings on 15×30 lot):
- **COMPLIANT** — 1 storey, 80 sqm footprint, FSR 0.178, coverage 0.178

Try `UnitCount = 2` to see **NON-COMPLIANT** (R1 allows only 1 unit).

## Comparison: Grasshopper vs Rust Implementation

| Feature | Grasshopper (v0.2) | Rust (regime-params + viewer) |
|---------|-------------------|-------------------------------|
| **Zoning rules** | JSON file | Encoded in `regime-zoning` |
| **Setback calculation** | Uniform inset | Directional (front/rear/side) |
| **Massing generation** | Program-driven footprint | Multi-option solver |
| **Visualization** | Rhino viewport | Vulkan path tracer |
| **Interaction** | Sliders + manual Brep editing | WASD camera, future gizmos |
| **Compliance feedback** | Text panel | Console log, future UI overlay |
| **Export** | Rhino geometry | OBJ/FBX/IFC (planned) |
| **Performance** | Interactive (~60 FPS) | Real-time raster + offline path trace |
| **Platform** | macOS (Rhino 8) | Cross-platform (Vulkan) |

## Lessons Learned from Grasshopper Prototype

### UX Friction Points Identified

1. **JSON Path Input**: Users don't want to type file paths. Better: embed constraints or provide file picker.

2. **Slider Granularity**: Default slider ranges (1-4 units, 60-120 sqm) need adjustment based on zone type. R1 should lock unit count to 1.

3. **Compliance Visibility**: Text panel is hard to read at a glance. Color-coded preview (green/red) would be faster.

4. **Setback Confusion**: Users expect to see which side is "front" (street-facing). Need visual indicator.

5. **No Sculpting**: Users want to carve out light wells, step back upper floors manually. Current script is all-or-nothing.

### Patterns to Port to Rust

1. **Program-first workflow**: Start with unit count + target size, derive massing (not the reverse).

2. **Immediate compliance feedback**: Show violations as they occur, not just at end.

3. **Constraint hierarchy**: Hard constraints (setbacks, max height) vs soft targets (preferred unit size).

4. **Multi-option exploration**: Generate several valid configurations, let user choose (implemented in Rust viewer).

## Next Steps for Grasshopper Prototype

### Immediate Improvements

- [ ] Add color preview via Custom Preview component keyed on `IsValid`
- [ ] Edge classification from lot orientation (identify front lot line)
- [ ] Corner-lot logic (`side_exterior` setback)
- [ ] Parking layout check (2 spaces/unit, 2.6m × 5.2m each)
- [ ] Floor-plate slicing per storey

### Future Enhancements

- [ ] Manual sculpting layer (user draws exclusion zones)
- [ ] Real-time FSR/coverage updates during sculpting
- [ ] Export compliance report to JSON for `ls-obc` (Phase 2)
- [ ] Batch mode: test multiple unit counts automatically

## Testing Checklist

Before considering Grasshopper prototype complete:

- [x] Single-detached house (R1, 1 unit) passes compliance
- [ ] Duplex (R1, 2 units) correctly fails with "max_units exceeded"
- [ ] Corner lot applies `side_exterior` setback
- [ ] Large lot (2000+ sqm) allows higher coverage
- [ ] Small lot (<400 sqm) shows appropriate warnings
- [ ] Parking spaces fit within remaining site area
- [ ] Upper floor setbacks (if any) are respected
- [ ] Exported geometry is watertight (valid Brep)

## Resources

- [START_HERE.md](../START_HERE.md) — Phase 1 instructions
- [VIEWER_INTEGRATION.md](../docs/VIEWER_INTEGRATION.md) — Rust viewer documentation
- [VISION.md](../VISION.md) — Full project vision

---

*Grasshopper prototype status: v0.2 functional for basic R1 scenarios. Edge cases and advanced features pending.*
