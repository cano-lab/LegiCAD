# Viewer Integration for Massing Options

## What Was Built

### New Binary: `archview-massing`

A standalone viewer that demonstrates the complete pipeline from zoning constraints to 3D visualization:

```bash
# Generate and visualize massing options for a rectangular lot
cargo run --bin archview-massing --features windowed -- \
    --lot-width 20 --lot-depth 40 --zone R1

# Or load from a JSON site definition
cargo run --bin archview-massing --features windowed -- \
    --site path/to/site.json

# Full options
cargo run --bin archview-massing --features windowed -- --help
```

### Pipeline Flow

```
┌─────────────────┐     ┌──────────────────┐     ┌───────────────────┐
│  Zoning Rules   │────▶│  Massing Solver  │────▶│  Massing Options  │
│  (regime-zoning)│     │  (regime-params) │     │  (2D footprints)  │
└─────────────────┘     └──────────────────┘     └─────────┬─────────┘
                                                           │
┌─────────────────┐     ┌──────────────────┐     ┌────────▼─────────┐
│  Vulkan Viewer  │◀────│ StructuralElement │◀────│ Building Mass   │
│  (archview)     │     │  (custom mesh)    │     │ (3D extrusion)  │
└─────────────────┘     └──────────────────┘     └───────────────────┘
```

### Key Components

#### 1. Massing Bridge (`archengine/geometry/src/massing_bridge.rs`)

Converts 2D massing options from the constraint solver into 3D building masses:

- **`BuildingMass`** struct - Complete 3D building with mesh, storeys, height, GFA, FSR
- **`from_footprint()`** - Extrudes 2D polygon footprint into 3D mesh with floor levels
- **`massing_to_building_mass()`** - Convenience function for regime→geometry conversion

Features:
- Proper floor level calculation (storey_height = total_height / storeys)
- FSR and coverage tracking
- Validation (`is_valid()`) for degenerate geometries
- 7 passing tests including integration with regime-params

#### 2. Viewer Binary (`archengine/viewer/src/bin/archview_massing.rs`)

Command-line tool that:
1. Parses site parameters (lot dimensions, zone, program brief)
2. Solves for valid massing options using regime-params + regime-zoning
3. Converts options to 3D meshes via massing_bridge
4. Displays all options side-by-side in the Vulkan viewer for comparison

Usage patterns:
```bash
# Quick test with default R1 zoning
archview-massing --lot-width 15 --lot-depth 30

# Multi-unit scenario
archview-massing --lot-width 20 --lot-depth 40 --units 3 --unit-size 100

# Custom jurisdiction
archview-massing --site my_site.json --jurisdiction "Toronto" --zone "R2"
```

### Controls

Standard archview controls apply:
- **WASD** - Move camera
- **Q/E** - Move down/up
- **Right mouse** - Orbit camera around pivot point
- **Scroll** - Zoom toward cursor
- **F** - Frame entire scene
- **Esc** - Quit

### Output

The viewer displays 3-5 massing options side-by-side (offset by 30m along X axis), each showing:
- Different storey counts (exploring vertical vs horizontal development)
- Different aspect ratios within setback envelopes
- Color-coded by option number for easy comparison

Console output shows summary for each option:
```
Option 1: 2 storeys, 6.0m height, 250 m² GFA, FSR 0.42
Option 2: 3 storeys, 9.0m height, 250 m² GFA, FSR 0.42
Option 3: 1 storeys, 3.0m height, 180 m² GFA, FSR 0.30
```

## Testing

### Unit Tests

Run tests for the massing bridge:
```bash
cargo test -p archengine-geometry massing_bridge
```

Tests cover:
- Rectangular footprint extrusion
- L-shaped and complex polygons
- Invalid/rejected footprints (too few vertices)
- Floor level calculations
- Full regime→geometry integration pipeline

### Integration Test

Full pipeline test in `massing_bridge.rs`:
```rust
#[test]
fn test_regime_to_geometry_pipeline() {
    // Creates a 20×40m Sudbury R1 lot
    // Solves for massing options
    // Converts first option to 3D building mass
    // Validates mesh generation
}
```

## Dependencies Added

### `archengine/viewer/Cargo.toml`
```toml
[dependencies]
regime-params = { path = "../../regime/params" }
regime-zoning = { path = "../../regime/zoning" }
```

These enable the viewer to directly invoke the constraint solver and geometry bridge.

## Next Steps

### Immediate (Phase 1 Complete ✅)
- [x] Connect regime massing options to geometry kernel
- [x] Create viewer binary for visualization
- [x] Add integration tests
- [x] Document usage

### Recommended Next

1. **LP/MILP Solver Integration** (Priority: High)
   - Replace direct geometric calculation with good_lp + HiGHS
   - Enable true optimization (maximize GFA, minimize cost, etc.)
   - Add objective functions and multi-objective Pareto fronts

2. **Interactive Manipulation** (Priority: Medium)
   - Add gizmos in viewer for sculpting massing within envelope
   - Real-time compliance checking as user drags faces
   - Push/pull tools constrained by zoning rules

3. **Grasshopper Prototype** (Parallel Track)
   - Test UX friction points in Rhino before full Rust implementation
   - Validate constraint feedback loops with real users
   - Export learned patterns back to regime-params

4. **Export Formats** (Priority: Low)
   - OBJ/FBX export for external rendering
   - IFC export for BIM workflows
   - JSON serialization for web viewers

## Architecture Notes

### Why Side-by-Side Display?

Displaying multiple options simultaneously allows:
- Direct visual comparison of different strategies
- Understanding trade-offs (height vs coverage, FSR utilization)
- Rapid iteration on program requirements

Future enhancement: Toggle visibility per-option with number keys (1-5).

### Mesh Generation Strategy

Current approach uses simple extrusion:
1. Take 2D footprint polygon (XZ plane)
2. Extrude along Y axis to specified height
3. Generate side quads + top/bottom caps
4. Assign flat per-face normals for crisp edges

This matches the convention in `scene.rs` for structural elements and works well with the viewer's raster pipeline.

### Color Coding

Default massing color: light gray-blue `(0.85, 0.85, 0.9)`
- Neutral, architectural appearance
- Good contrast against sky/procedural environment
- Can be overridden per-option for emphasis

---

*Viewer integration complete. The bridge from zoning constraints → parametric massing → 3D visualization is now functional.*
