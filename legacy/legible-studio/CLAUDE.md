# Legible Studio — Agent Guide

## What this is

A pure-Rust system that generates **code-compliant Ontario Building Code (OBC)
Part 9 residential permit sets** from a few high-level answers, and captures
existing buildings from LiDAR to overlay new design on as-built conditions.

The pipeline: **answers → solver → building JSON → drawings (SVG/PDF/DXF) +
IFC**. The structured building JSON is the product contract; the drawings, IFC,
and DWG/DXF are renderings of it.

Scope: OBC Part 9, new construction. Zoning and Part 11 (renovations) are out of
v1 scope (the data model flags existing-vs-new, but Part 11 rules are deferred).

> **The codebase is the Rust workspace under `rust/`.** Everything legacy —
> the Python `ArchEngine_CAD`, the C++ `ArchEngine_kernel`, the UE5 viewer, the
> old `Shared/` schema, the FastAPI `headless/`, the Python oracle tests, and
> the dated handoff/spec markdown — now lives under `history/` (see
> `history/README.md`). It's kept for provenance only; don't wire new work into
> it. Many Rust crates carry `// Port of ArchEngine_kernel/...` comments that
> point back there. The live plan is `docs/ROADMAP_2026-05-31.md`.

## Status

Phases 1–3 are complete: permit-ready PDF bundle, engineer handoff (IFC + DWG/DXF
+ HTTP API), and LiDAR as-built capture with design overlay. See
`docs/ROADMAP_2026-05-31.md` for the authoritative state and what's next.

## Workspace layout (`rust/crates/`)

| Crate | Responsibility |
|---|---|
| `solver` (`ls-solver`) | Answers → room layout, walls, doors, windows, smoke/CO detectors, electrical. Bin: `qbd_solve`. |
| `archgeometry` (`ls-archgeometry`) | Schema types — **the building-JSON contract** (`SchemaDocument`/`SchemaWall`/…). Room/wall geometry, renovation `existing` flag. |
| `obc` (`ls-obc`) | OBC span tables (joist/stud/header/rafter), thermal compliance, smoke/CO + electrical placement. |
| `drawing` (`ls-drawing`) | 2D slicer → SVG/DXF: plans, elevations, sections, details, schedules, as-built overlay. |
| `qbd` (`ls-qbd`) | Orchestration, documentation bundle, IFC4 export, compliance report, SVG→PDF, title blocks. Bin: `qbd_dump`. |
| `site` (`ls-site`) | LiDAR download, GeoTIFF/terrain, OSM streets, map widget, **footprint + as-built wall/elevation detection**. Bins: `legible-stitch`, `legible-fetch`, `legible-streets`, `legible-footprint`, `legible-aswall`, `legible-elevation`. |
| `api` (`ls-api`) | `axum` HTTP server. Bin: `ls-api-server` (`/health`, `/solve`, `/draw`). |
| `app` (`ls-app`) | Desktop head. Bin: `legible` — bare-metal window (winit + tiny-skia software rendering), sketch pad + map mode + floor-plan view. |
| `domain`, `csg`, `bvh`, `mesh-gen`, `wall-system`, `catalog`, `geometry-loader` | Shared kernel: object model, geometry primitives, CSG, BVH. |
| `smoke-test` | Pure-Rust end-to-end regression: answers → bundle → PDF round-trip. |

The desktop UI is **bare-metal** (winit + softbuffer + tiny-skia + fontdue,
hand-rolled immediate-mode), via the shared `pk-surface`/`pk-object` parametric
kernel — no wgpu, no Tauri, no webview, no GPU.

## Build & test

```bash
cd rust
cargo build --release                 # all crates + binaries
cargo test  --release --workspace     # ~620 tests
cargo test  --release -p smoke-test   # end-to-end oracle
cargo clippy --release --workspace    # pedantic is warn-level (see workspace [lints])
```

Toolchain: stable Rust, `rust-version = 1.92`, edition 2024. The platform here is
Windows (PowerShell); a Bash tool is also available.

## End-to-end, by hand

```bash
cargo run --release --bin qbd_solve -- --bedrooms 3 --bathrooms 2 --sqft 1600 > house.json
cargo run --release --bin qbd_dump  -- house.json --bundle out --pdf out --dxf out   # ~16 sheets
cargo run --release --bin qbd_dump  -- house.json --ifc house.ifc                     # Revit
cargo run --release --bin legible   -- house.json                                     # desktop view
```

`qbd_dump --help` lists every flag (`--bundle`, `--pdf`, `--png` (in-house
SVG→PNG raster, no Inkscape), `--dxf`, `--ifc`, `--obc <lib>`, `--footprint`,
`--designer`, `--bcin`, `--bare`, …).

## Conventions & gotchas

- **Units:** millimetres throughout the schema/geometry. `Vec3` is `[x, y, z]`
  with **y up** (x east, z north). Plan views use the XZ plane.
- **Building-JSON wire format:** the schema renames `walls` → `walls_batch` and
  `floors` → `floors_batch` in JSON (legacy keys); `doors`/`windows` are plain.
  `archgeometry::parse_file` is the entry point.
- **Renovation flag:** `existing: bool` on `SchemaWall`/`SchemaDoor`/`SchemaWindow`
  marks as-built elements (separate from `category`, the construction type).
  Walls also honour the legacy `category == "as_built"`. Existing elements render
  dashed grey in the floor plan; new design is solid black.
- **Coordinate frames:** point clouds for the as-built tools are ASCII XYZ,
  metres, y-up (`ls_site::cloud::parse_xyz`). LiDAR DEMs are Ontario zone-17N
  GeoTIFF (DSM/DTM).
- **`svg_polyline`/`svg_line`** honour `line_type` `"dashed"`/`"hidden"` →
  `stroke-dasharray`. Colour is `Vec3` RGB 0..1.
- Treat any external AI model (image-to-3D, render) as a **swappable dependency
  behind an abstraction** — never load-bearing.

## When changing the schema (`archgeometry`)

It's the contract between solver, drawings, IFC, and the API. New fields should
be `#[serde(default)]` (and `skip_serializing_if` when they default to
empty/false) to stay backward-compatible with existing building JSON. Add a
round-trip test.
