# Legible Studio

**Code-compliant Part 9 residential permit sets, generated in one sitting.**

Answer a handful of questions about a house → get a permit-ready drawing set
(floor plans, elevations, sections, foundation, framing, details, schedules,
compliance report) as SVG + PDF, plus IFC for engineers and DWG/DXF for
AutoCAD. Capture an existing building with LiDAR and overlay the new design on
the as-built.

Scope: Ontario Building Code (OBC) Part 9, new construction. Zoning and Part 11
(renovations) are out of v1 scope.

> This is a pure-Rust workspace (`rust/`). The earlier Python/C++ ArchEngine and
> the UE5 viewer are legacy and not part of the current build.

---

## Status (June 2026)

Three build phases are complete end-to-end:

| Phase | Outcome | State |
|---|---|---|
| **1 — Permit-ready PDF** | One command → a PDF bundle a building department can accept for a simple house. | ✅ |
| **2 — Engineer handoff** | IFC (walls/openings/slabs/footings) for Revit, DWG/DXF for AutoCAD, an HTTP API. | ✅ |
| **3 — LiDAR as-built → plans** | Capture existing conditions from LiDAR and overlay new design (existing dashed grey, new solid black). | ✅ |

Detail lives in [`docs/ROADMAP_2026-05-31.md`](docs/ROADMAP_2026-05-31.md).

**Tested:** ~620 tests across the workspace (`cargo test --release --workspace`),
including a pure-Rust end-to-end `smoke-test` crate that round-trips every core
sheet to PDF.

---

## What works today

### Generate a permit set from answers

```bash
cd rust

# Answers → building JSON (rooms, walls, doors, windows, detectors, electrical)
cargo run --release --bin qbd_solve -- \
    --bedrooms 3 --bathrooms 2 --sqft 1600 --garage 2car --roof gable > house.json

# Building JSON → full permit-set bundle (SVG + PDF + DXF)
cargo run --release --bin qbd_dump -- house.json --bundle permit_set --pdf permit_set --dxf permit_set
```

`permit_set/` then contains ~16 sheets:

- `01_site_plan` · `02_floor_plan` (one per storey) · `03_elevation_{n,s,e,w}`
- `04_section_aa` · `06_roof_plan` · `08_foundation_plan` · `10_framing_plan`
- `07_wall_detail_*` · `11_footing_detail` · `09_compliance_report`
- `05_door_schedule` · `05_window_schedule` · `manifest.json`

Each sheet is emitted as SVG, the same set as PDF (permit submission / engineer
review), and the plan + elevations also as DXF (AutoCAD).

### Export for engineers

```bash
# IFC4 for Revit — walls, spaces, doors/windows with opening voids, slabs, strip footings
cargo run --release --bin qbd_dump -- house.json --ifc house.ifc

# Title block + designer/BCIN on every sheet
cargo run --release --bin qbd_dump -- house.json --bundle permit_set \
    --project "123 Main St" --designer "Jane Doe" --bcin 12345
```

### Run the HTTP API

```bash
cargo run --release --bin ls-api-server      # binds a local port, ctrl-c to stop
```

- `GET  /health`
- `POST /solve` — answers JSON → building JSON
- `POST /draw`  — building JSON → SVG bundle (+ optional IFC, DXF, compliance summary
  via `?include_ifc=true&include_dxf=true`)

### LiDAR as-built capture (Ontario)

```bash
# 1. Building footprint from DSM/DTM tiles (height-threshold + convex hull)
cargo run --release --bin legible-footprint -- --site site.json --dsm ./dsm --dtm ./dtm --out footprint.json

# 2. Interior walls from a point cloud (Hough vertical-plane segmentation)
cargo run --release --bin legible-aswall -- --cloud interior.xyz --out aswalls.json

# 3. Elevations from an exterior point cloud (per-facade outline + window/door openings)
cargo run --release --bin legible-elevation -- --cloud exterior.xyz --out elevations.json
```

Merge the as-built walls (`category: "as_built"` / `existing: true`) into a
building doc and the floor plan renders them **dashed grey** under your new
**solid black** design — including existing doors and windows.

### Desktop app

```bash
cargo run --release --bin legible -- [house.json]
```

A bare-metal window (winit + tiny-skia software rendering — no GPU, no webview).
What you can do today:

- **View mode** (default): pan (right-drag), zoom (scroll). If you pass a
  `house.json`, it renders that permit floor plan as the underlay.
- **`b` boundary mode**: click to sketch a lot outline, `Enter` to close — the
  room solver lays out a 3-bed/2-bath program inside it, live.
- **`f` freeform mode**: sketch arbitrary shapes.
- **`m` map mode**: OSM map tiles; click to trace a parcel polygon, `Enter`
  saves `site.json`. **`g`** fires the LiDAR fetch + terrain-stitch pipeline for
  that parcel on a background thread.
- **`v`** back to view, **`c`** clear, **`Esc`** quit.

It's a working sketch/site front end, not yet a full Revit-style editor — wall/
door/window editing in-app is the active next direction.

---

## How it fits together

```
answers ──► solver ──► building JSON (schema) ──► drawing ──► SVG/PDF/DXF
            (ls-solver)   (ls-archgeometry)        (ls-drawing)
                              │                        │
                              ├──► OBC rules ──────────┤  (ls-obc: spans, thermal,
                              │    (compliance report)    smoke/CO, electrical)
                              └──► IFC4 export (ls-qbd → house.ifc)

LiDAR DEM / point cloud ──► ls-site ──► footprint / as-built walls / elevations
                                          └──► merged into building JSON ──► overlay
```

| Crate | Responsibility |
|---|---|
| `ls-solver` | Answers → room layout, walls, doors, windows, smoke/CO detectors, electrical |
| `ls-archgeometry` | Schema types (the building-JSON contract), room/wall geometry, renovation flag |
| `ls-obc` | OBC span tables (joist/stud/header/rafter), thermal, detector + electrical placement |
| `ls-drawing` | 2D slicer → SVG/DXF: plans, elevations, sections, details, schedules, as-built overlay |
| `ls-qbd` | Orchestration, documentation bundle, IFC4 export, compliance report, SVG→PDF, title blocks |
| `ls-site` | LiDAR download, GeoTIFF/terrain, OSM streets, map widget, footprint + as-built detection |
| `ls-api` | `axum` HTTP server (`/health`, `/solve`, `/draw`) |
| `ls-app` | `legible` desktop head (sketch pad, map mode, floor-plan view) |
| `domain`, `csg`, `bvh`, `mesh-gen`, `wall-system`, `catalog`, `geometry-loader` | Shared kernel: object model, geometry, primitives |

---

## Build & test

```bash
cd rust
cargo build --release            # all crates + binaries
cargo test  --release --workspace
cargo test  --release -p smoke-test   # end-to-end: answers → bundle → PDF round-trip
```

Requires a recent stable Rust (workspace pins `rust-version = 1.92`, edition 2024).

---

## Not in v1 (and why)

| Item | Reason |
|---|---|
| **Part 11 (renovations)** | Different code + drawing conventions. The data model already flags existing-vs-new; rules come later. |
| **Plumbing / HVAC plans** | Not required for an Ontario Part 9 permit. Most-requested nice-to-have. |
| **3D render / Vulkan** | Separate product line (LegiView). Permit drawings are 2D. |
| **Full structural engineering** | Requires an engineer's stamp. We pre-mark assumptions; the engineer verifies via the IFC/PDF handoff. |

## License

MIT · Copyright (c) 2026 Legible Studios
