# LegiCAD Grasshopper Regime Script

## What's Here

| File | Purpose |
|------|---------|
| `LegiCAD_RegimeScript.cs` | C# script (v0.2) for a Grasshopper C# Script component — zero dependencies |
| `sudbury_r1_constraints.json` | Sudbury R1 residential zoning constraints |
| `LegiCAD_Site.3dm` | Starter Rhino file: 15m × 30m lot (R1 minimum), setback guides, meters |
| `make_site.py` | Regenerates `LegiCAD_Site.3dm` (requires `pip install rhino3dm`) |

## How to Use

### 1. Open the starter site

Open `LegiCAD_Site.3dm` in Rhino 8. It contains:

- **Layer `SiteBoundary`** — a closed polyline lot, 15m frontage × 30m depth
  (450 sqm, the exact R1 minimum). This is your `SiteBoundary` input.
- **Layer `Reference`** — the true R1 setback envelope (6m front / 7.5m rear /
  1.2m sides), a street line, and labels. Visual reference only.

### 2. Create the Grasshopper component

1. Run `Grasshopper` in Rhino
2. Add a **C# Script** component (Maths → Script → C# Script)
3. Double-click it to open the editor
4. Delete the default code
5. Paste the entire contents of `LegiCAD_RegimeScript.cs`
6. Click **OK**

No assembly references needed — v0.2 parses JSON with an embedded
dependency-free parser (MiniJson), so there is no Newtonsoft.Json step.

### 3. Set up inputs

Right-click each input on the C# component and rename/set it:

| Input | Rename to | Type hint | Wire to |
|-------|-----------|-----------|---------|
| `x` | `SiteBoundary` | Curve | A `Curve` param → Set One Curve → the lot polyline |
| `y` | `JsonPath` | (string) | A `Panel` with the full path to `sudbury_r1_constraints.json` |

Then zoom in on the component and add three more inputs (`z+` button):

| Input | Rename to | Type hint | Wire to |
|-------|-----------|-----------|---------|
| `z` | `UnitCount` | int | Integer slider, 1–4 |
| + | `CeilingHeight` | double | Number slider, 2.4–3.0 |
| + | `TargetUnitSize` | double | Number slider, 60–120 |

**Names must match exactly** — Grasshopper binds parameters to `RunScript`
arguments by name.

### 4. Set up outputs

Right-click each output (`out`, `a`) and rename, adding more with `z+`:

| Output | Rename to | Wire to |
|--------|-----------|---------|
| `out` | `Massing` | (preview is automatic) |
| `a` | `Envelope` | (preview is automatic) |
| + | `Compliance` | A `Panel` (Params → Input → Panel) |
| + | `IsValid` | A `Panel` |
| + | `DebugInfo` | A `Panel` |

### 5. Run it

```
[Curve param: lot] ──── SiteBoundary ─┐
[Panel: JSON path] ──── JsonPath ─────┤
[Slider 1–4] ────────── UnitCount ────┤                  ├─ Massing
[Slider 2.4–3.0] ────── CeilingHeight ┼──[C# Script]─────┼─ Envelope
[Slider 60–120] ─────── TargetUnitSize┘                  ├─ Compliance → Panel
                                                       ├─ IsValid → Panel
                                                       └─ DebugInfo → Panel
```

Expected result with defaults on the 15×30 lot (1 unit, 80 sqm, 2.7m ceilings):
**COMPLIANT** — 1 storey, 80 sqm footprint, FSR 0.178, coverage 0.178.

Try `UnitCount = 2` to see it go **NON-COMPLIANT** (R1 is single-detached only,
`max_units = 1`).

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "SiteBoundary input is null" | Connect a closed curve; check the Type hint is `Curve` |
| "Setback offset failed" | Setbacks too large for the lot — draw a bigger site |
| "Constraint not found in JSON: ..." | The JSON schema changed; check the path named in the error |
| Compile error after pasting | Make sure you deleted ALL default code before pasting |
| Nothing previews | Grasshopper previews Breps by default — check the component isn't hidden (right-click → Preview) |

## Notes & Limitations

- **Simplified setback model**: the envelope uses a uniform inset (minimum of
  all setbacks). The true R1 envelope (drawn on the `Reference` layer) is
  larger on the side yards. Distinguishing front/rear/side edges requires lot
  orientation — future work.
- **Massing is program-driven**: footprint = (units × target size) ÷ storeys,
  capped by both the envelope and the lot-coverage rule. Storeys are the
  minimum that fits the program, capped by `max_storeys`.
- If the program doesn't fit within coverage × storeys caps, the massing is
  capped and a warning appears in the Compliance report.

## Next Steps

- [ ] Edge classification (front/rear/side) from lot orientation
- [ ] Corner-lot logic (`side_exterior` setback)
- [ ] Parking layout check (2 spaces/unit, 2.6m × 5.2m each)
- [ ] Floor-plate slicing per storey
- [ ] Color preview via a Custom Preview component keyed on `IsValid`
- [ ] Export compliance report to JSON for `ls-obc` (Phase 2)

---

*LegiCAD — Computer Assisted Design, as it should be.*
