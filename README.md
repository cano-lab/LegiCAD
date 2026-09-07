# Legible Engine

**Generative design platform for housing — starting in Sudbury, Ontario.**

> Question-based design meets regime architecture in parametric space.  
> The rules come first. You sculpt within what's possible.

---

## What This Is

Legible Engine is the unified workspace for two projects that are becoming one:

- **ArchEngine** — Rust geometry kernel + Vulkan viewer (evolving from 2D permit drawings to 3D generative massing)
- **Legible Studio** — Question-based design UX + OBC compliance (evolving from document generator to parametric design platform)

Read [`VISION.md`](VISION.md) for the full thesis.

Read [`questions.md`](questions.md) for the open questions blocking progress.

---

## Repo Structure

```
legible-engine/
├── VISION.md              # The big picture
├── questions.md           # Open questions for the next agent
├── README.md              # This file
├── Cargo.toml             # Workspace root (when we have one)
├── archengine/            # Geometry kernel + viewer (to be built)
│   ├── geometry/          # Solid modeling, CSG, BVH
│   ├── viewer/            # Vulkan / wgpu renderer
│   └── solver/            # Constraint solver (CSP/MILP)
├── regime/                # The regime engine
│   ├── obc/               # Ontario Building Code constraints
│   ├── zoning/            # Zoning bylaws (Sudbury first)
│   └── params/            # Parametric design regimes
├── docs/                  # Design docs, RFCs, decisions
└── scripts/               # Utilities, prototypes, tests
```

**Note:** The existing Legible Studio Rust workspace lives at:
```
/root/.openclaw/workspace/legible-studio/rust/
```

That code is the starting point. This repo (`legible-engine`) is where the new architecture lives. Over time, crates will migrate or be referenced.

---

## Current Legible Studio (Existing Code)

The working codebase is in `/root/.openclaw/workspace/legible-studio/`:

| Crate | What it does |
|-------|-------------|
| `ls-solver` | Answers → room layout, walls, doors, windows |
| `ls-archgeometry` | Building JSON schema, room/wall geometry |
| `ls-obc` | OBC span tables, thermal, detectors, electrical |
| `ls-drawing` | 2D slicer → SVG/DXF (plans, elevations, sections) |
| `ls-qbd` | IFC4 export, compliance reports, PDF bundles |
| `ls-site` | LiDAR, GeoTIFF, OSM, footprint detection |
| `ls-api` | Axum HTTP server |
| `ls-app` | Desktop app (winit + tiny-skia) |

Build it:
```bash
cd /root/.openclaw/workspace/legible-studio/rust
cargo build --release
cargo test --release --workspace
```

---

## ArchEngine Legacy

Historical ArchEngine code (Python/C++, earlier iterations) is archived at:
```
/root/.openclaw/workspace/legible-studio/history/
├── ArchEngine_CAD/        # Python/C++ CAD experiments
├── ArchEngine_kernel/     # Earlier kernel work
├── headless/              # Headless renderer experiments
└── docs/                  # Design documents from that era
```

This code is reference, not current. The new ArchEngine is being built in Rust.

---

## Immediate Goals

1. **Decide the solid modeling approach** (see `questions.md` #1)
2. **Get Sudbury zoning bylaws** (see `questions.md` #2)
3. **Build the first end-to-end demo**: site → constraints → mass → SVG

---

## License

MIT · Copyright (c) 2026 Legible Studios
