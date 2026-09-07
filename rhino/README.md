# LegiCAD Grasshopper Regime Script

## What's Here

| File | Purpose |
|------|---------|
| `LegiCAD_RegimeScript.cs` | C# script for Grasshopper C# Script component |
| `sudbury_r1_constraints.json` | Sudbury R1 residential zoning constraints |

## How to Use

### 1. Install Newtonsoft.Json (if not already installed)

Grasshopper C# components need the Newtonsoft.Json DLL to parse JSON.

**Option A: Use the one that comes with Rhino**
- Rhino 7/8 usually has it at: `C:\Program Files\Rhino 7\System\Newtonsoft.Json.dll`
- In the Grasshopper C# script editor, go to **Manage Assemblies** and add this path

**Option B: Download it**
- Get `Newtonsoft.Json.dll` from NuGet
- Place it somewhere accessible and reference it in the C# script editor

### 2. Create the Grasshopper Component

1. Open Grasshopper in Rhino
2. Add a **C# Script** component (Maths → Script → C#)
3. Double-click to open the editor
4. Delete the default code
5. Copy and paste the entire contents of `LegiCAD_RegimeScript.cs`
6. Click **Manage Assemblies** and add `Newtonsoft.Json.dll`
7. Click **OK**

### 3. Set Up Inputs

Right-click the C# component inputs and add these parameters:

| Input | Type | Default | Description |
|-------|------|---------|-------------|
| `SiteBoundary` | Curve | (none) | Connect a closed polyline (your lot) |
| `JsonPath` | String | (empty) | Path to `sudbury_r1_constraints.json` |
| `UnitCount` | Integer | 1 | Number of units (slider: 1-4) |
| `CeilingHeight` | Number | 2.7 | Ceiling height in meters (slider: 2.4-3.0) |
| `TargetUnitSize` | Number | 80 | Area per unit in sqm (slider: 60-120) |

### 4. Set Up Outputs

Right-click the C# component outputs and rename them:

| Output | Type | Description |
|--------|------|-------------|
| `Massing` | Brep | The 3D building massing |
| `Envelope` | Brep | The feasible envelope (with setbacks) |
| `Compliance` | String | Human-readable compliance report |
| `IsValid` | Boolean | True if all constraints pass |
| `DebugInfo` | String | Internal calculation log |

### 5. Draw a Site Boundary in Rhino

1. In Rhino, draw a closed polyline representing your lot
2. In Grasshopper, add a `Curve` parameter (Params → Geometry → Curve)
3. Right-click → **Set One Curve** and select your polyline
4. Connect it to the `SiteBoundary` input

### 6. Run It

1. Set the JSON path (or leave empty to use defaults)
2. Adjust sliders for unit count, ceiling height, target size
3. The script will:
   - Calculate setbacks and create the feasible envelope
   - Generate massing based on your program inputs
   - Validate against all R1 constraints
   - Output green massing if compliant, red if not

## Example Workflow

```
[Curve: Site Polygon] ──┐
                        ├──[C# Script]──[Massing (Brep)]──[Preview]
[Slider: UnitCount] ────┤         └──[Compliance (String)]──[Panel]
[Slider: CeilingHeight]─┘
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Newtonsoft.Json not found" | Add the DLL in Manage Assemblies |
| "SiteBoundary is null" | Connect a closed curve to the input |
| "Setback offset failed" | Your setbacks may be too large for the lot. Reduce them or use a larger site. |
| Massing is red | Check the Compliance output to see which constraint was violated |
| No JSON file | The script uses embedded defaults, but you should use the real `sudbury_r1_constraints.json` |

## Next Steps

- [ ] Add more zoning rules (parking, side setbacks, corner lots)
- [ ] Read JSON from URL instead of file path
- [ ] Add color coding to the Rhino viewport (green = valid, red = invalid)
- [ ] Generate floor plates per storey
- [ ] Export compliance report to PDF

## Notes

- This is a **simplified setback model**. Real setback calculation needs to know which edge is front/rear/side (requires lot orientation).
- The envelope uses uniform setback (minimum of all setbacks). For more accuracy, you'll need to identify front vs side edges.
- FSR calculation is simplified: footprint × storeys / site area.

---

*LegiCAD — Computer Assisted Design, as it should be.*
