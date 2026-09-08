# Vulkan Kernel → Rust Port Plan

**Source:** `F:/Software/ArchEngine_Suite_Kernel/ArchEngine_kernel/` + `F:/Software/ArchEngine_Suite_Kernel/Shared/ArchGeometry/`
**Audience:** The author (this document supplements existing context, doesn't replace it).
**Date:** 2026-05-15 (decisions baked 2026-05-16)
**Companion:** `RUST_PORT_ROADMAP.md` (Legible Studio Python pipeline) — referenced, not duplicated.
**Status:** All 12 architecture questions decided — see §8 for resolutions.

---

## 0. TL;DR

The codebase is **two cleanly separable halves** plus an aux addon:

1. **Geometry kernel** (~12,500 LOC pure-CPU code, no Vulkan): `ArchGeometry/`, `csg`, `bvh` (CPU build half), `qbd_interface`, `obc_engine`, the merged `drawing` module (slicer_2d + plan_generator — §8 Q1), `wall_system`, `geometry_loader`, the CPU half of `mesh.hpp` (`Geometry::` namespace), and the domain half of `types.hpp`. **This half is the critical path for Legible Studio permit drawings and is what to port first.** Total Rust effort: **~13–17 weeks at hobby pace** (~20 weeks with buffer), dominated by the QBD/OBC/drawing trio and CSG correctness.
2. **Vulkan renderer** (~22,800 LOC C++ + ~2,700 LOC GLSL): `renderer.cpp` (5,473 LOC) plus the standard pipeline/descriptor/swapchain stack, post-process, IBL, path tracer, ImGui, GLFW window. Recommended target: **`wgpu` for the bulk, `ash` only if a Vulkan-RT path proves load-bearing for the path tracer**. Total Rust effort: **~16–24 weeks**, but secondary per the pivot — sketch only.
3. **Auxiliary:** `addons/physics_sim/` (~7,300 LOC hygrothermal/structural physics) — well past the permit-drawing critical path; defer until Legible Studio has surplus capacity.

Three structural facts dominate the port:

- **`include/types.hpp` is a kitchen sink** (722 LOC mixing GPU layouts, domain semantic types, frustum culling, color palettes). It must be split at the start of the port — graphics types go into a renderer crate, semantic types into the geometry crate. Get this right early or both halves entangle.
- **A second schema lives at `Shared/ArchGeometry/`**, parallel to and partly duplicated by the kernel's own `qbd_interface`. ArchGeometry is the cleaner, library-shaped layer; the kernel uses it via `parseWithArchGeometry()` but ALSO has its own JSON path. The Rust port should consolidate on ArchGeometry's design and delete the parallel path.
- **License is MIT** (`LICENSE.txt`). README.md says "Proprietary - All rights reserved" — that line is wrong and should be deleted (§8 Q12). Permissively-licensed deps (zlib/MIT/CC0). No licensing constraint on translating any of it to Rust; Rust port stays MIT.

---

## 1. Tree map + split

### File counts by category

| Category | Files | LOC (approx) | Notes |
|---|---|---|---|
| GEOMETRY KERNEL | 28 | ~12,500 | The Rust-port priority |
| VULKAN RENDERER | 24 | ~22,800 | `renderer.cpp` alone is 5,473 |
| SHADERS (GLSL source) | 28 | ~2,700 | + ~22 .spv compiled artifacts (drop) |
| SHARED INFRA | 4 | ~1,100 | mostly `memory`, `lights`, parts of `types` |
| BUILD / GLUE | 4 | — | `CMakeLists.txt`, launcher script |
| THIRD-PARTY VENDORED | 2 + FetchContent | ~7k (stb) | + GLFW/GLM/ImGui/json/httplib auto-fetched |
| AUXILIARY (physics_sim addon) | 25 | ~7,300 | Hygrothermal/material physics — defer |
| AUXILIARY (other) | 5 | ~1,800 | `llm_assistant`, `memory_test`, `ipc_server`, `project`, `physics_bridge` |

### Per-category classification

**GEOMETRY KERNEL — pure CPU, no Vulkan dependency** (port priority):

- `Shared/ArchGeometry/include/*` (11 headers, ~1,400 LOC) — schema types, geometry types, generators, query API
- `Shared/ArchGeometry/src/*` (8 cpp, ~2,300 LOC) — wall_geometry, floor_geometry, roof_geometry, opening_geometry, room_geometry, schema_parser, query_api, archgeometry
- `ArchEngine_kernel/include/csg.hpp` + `src/csg.cpp` (~364 LOC) — hand-rolled BSP CSG (Möller-Trumbore, plane splitting, union/intersection/difference)
- `ArchEngine_kernel/include/bvh.hpp` + `src/bvh.cpp` (~1,314 LOC) — SAH BVH builder; CPU construction stage is geometry, GPU node layout is renderer-adjacent
- `ArchEngine_kernel/include/qbd_interface.hpp` + `src/qbd_interface.cpp` (~1,564 LOC) — QBD JSON parsing, building conversion, OBC validation orchestration, documentation
- `ArchEngine_kernel/include/obc_engine.hpp` + `src/obc_engine.cpp` (~872 LOC) — Ontario Building Code span/stud/header tables, compliance validation
- `ArchEngine_kernel/include/slicer_2d.hpp` + `src/slicer_2d.cpp` (~1,033 LOC) — 3D → 2D plane slicing, SVG + DXF export, wall section details
- `ArchEngine_kernel/include/plan_generator.hpp` (header-only, ~560 LOC) — floor plan annotations, dimensions, north arrow, grid, SVG export
- `ArchEngine_kernel/include/wall_system.hpp` (header-only, ~298 LOC) — parametric wall geometry, corner detection, L-corner adjustment
- `ArchEngine_kernel/include/geometry_loader.hpp` + `src/geometry_loader.cpp` (~1,049 LOC) — JSON building loader, sample builders, nlohmann ser/de
- `ArchEngine_kernel/include/mesh.hpp` — the `Geometry::` namespace half (createBeam/Column/Floor/GableRoof/etc.) — generators only, no Vulkan. **`mesh.cpp` is mostly here too** (~988 LOC of which most is geometry generation; Vulkan buffer wrapper is the small minority)
- `ArchEngine_kernel/include/types.hpp` — domain half (StructuralElement, Building, WallType, WallLayer, ParametricWall, WallCorner, color palettes, Frustum, AABB, Plane, MaterialPreset) — keep, split out the GPU types

**VULKAN RENDERER — GPU-bound** (sketch only):

- `src/renderer.cpp` (5,473 LOC) + `include/renderer.hpp` (1,366 LOC) — the spine; pipeline orchestration, frame graph
- `src/vulkan_context.cpp` (832) + `include/vulkan_context.hpp` (450) — instance/device/swapchain/queue
- `src/pipeline.cpp` (395) + `include/pipeline.hpp` (83) — VkPipeline wrapper
- `src/descriptor_manager.cpp` (273) + `include/descriptor_manager.hpp` (121) — descriptor pool/set/layout
- `src/instance_batch.cpp` (141) + `include/instance_batch.hpp` (77) — instance buffer for batched draws
- `src/shadow_map.cpp` (566) + `include/shadow_map.hpp` (94) — shadow pass, PCF
- `src/environment_map.cpp` (1,205) + `include/environment_map.hpp` (121) — HDR equirect → cubemap, IBL precompute
- `src/post_process.cpp` (1,878) + `include/post_process.hpp` (247) — SSAO, bloom, tonemap, composite
- `src/texture.cpp` (575) + `include/texture.hpp` (131) — Vulkan image upload, mip generation
- `src/path_tracer.cpp` (1,290) + `include/path_tracer.hpp` (340) — compute path tracer on GPU, uses BVH
- `src/imgui_layer.cpp` (2,940) + `include/imgui_layer.hpp` (447) — ImGui Vulkan backend + the entire material/scene UI
- `src/mesh.cpp` (988) — VkBuffer vertex/index wrappers (small) + most of `Geometry::` namespace implementations (large)
- `src/window.cpp` (110) + `include/window.hpp` (73) — GLFW wrapper
- `src/main.cpp` (2,014) — application entry, scene setup, camera control, input handling
- `src/arch_api.cpp` (1,627) + `include/arch_api.h` (1,009) — C API for DLL embedding (renderer-facing, ctypes/PyQt6 consumer)

**SHADERS** (`shaders/*.{vert,frag,comp,tesc,tese,rgen,rmiss,rchit}` + `shaders/include/ubo.glsl`):

- Forward PBR: `structural.vert`/`frag`/`tesc`/`tese`, `sky.vert`/`frag`
- IBL precompute (compute): `brdf_lut.comp`, `irradiance_convolve.comp`, `prefilter_envmap.comp`
- Post-process: `ssao.vert`/`frag`, `ssao_blur.frag`, `bloom_bright.frag`, `bloom_blur.frag`, `composite.frag`, `ssr.vert`/`frag`
- Shadows: `shadow.vert`, `shadow_tess.vert`, `shadow.tesc`/`tese`, `shadow_miss.rmiss`
- Vulkan ray tracing (KHR_ray_tracing): `raygen.rgen`, `closesthit.rchit`, `miss.rmiss`
- Compute path tracer: `path_trace.comp` (653 LOC — the heavyweight)
- Denoiser (compute): `denoise.comp`
- Shared: `include/ubo.glsl` (72 LOC of std140 UBO layout)
- All also exist as `.spv` artifacts — drop from version control on the Rust side; emit from the build.

**SHARED INFRA**:

- `include/memory.hpp` + `src/memory.cpp` (~386 LOC) — Vulkan device memory allocator (custom, not VMA). Renderer-side; mentioned here because the kernel also has a CPU-side `memory_test.hpp`/`.cpp` that is diagnostic and should be cut.
- `include/lights.hpp` (148 LOC) — `Light` struct, declared CPU-side, consumed by both UI and renderer. Renderer-adjacent but data-only.
- `external/stb_image.h`, `stb_image_write.h` (~7k LOC) — image I/O. Replace with `image` crate in Rust.

**BUILD / GLUE**:

- `ArchEngine_kernel/CMakeLists.txt` (385 LOC) — replace with `Cargo.toml`(s); workspace likely
- `Shared/ArchGeometry/CMakeLists.txt`, `addons/physics_sim/CMakeLists.txt` — same
- `launch_archengine.bat` — replace with `cargo run` once a Rust binary exists
- `update_phase5.ps1`, `update_imgui_panel.ps1` — one-off migration scripts, drop

**THIRD-PARTY VENDORED**:

- `external/stb_image.h`, `external/stb_image_write.h` — replace with `image` crate
- (FetchContent-pulled, not in repo): GLFW 3.3.8 (zlib), GLM 1.0.1 (MIT), nlohmann/json 3.11.3 (MIT), Dear ImGui v1.90.1 (MIT), cpp-httplib v0.15.3 (MIT)
- License posture: all permissive, no copyleft. Free to port.

**AUXILIARY** (defer or cut):

- `addons/physics_sim/` (~7,300 LOC) — hygrothermal, moisture, climate, decay, corrosion, UV, room air exchange models. Real building physics simulation. Per pivot: not permit-drawing path. **Defer.**
- `include/llm_assistant.hpp` + `src/llm_assistant.cpp` (~351 LOC) — cpp-httplib calls to local LLM endpoint. Per pivot brief, AI features cut. **Drop.**
- `include/memory_test.hpp` + `src/memory_test.cpp` (~208 LOC) — diagnostic only. **Drop.**
- `include/ipc_server.hpp` + `src/ipc_server.cpp` (~374 LOC) — TCP IPC server for external CAD app. Either survives in some form (Rust `axum`/`tokio` HTTP service) or is replaced by the `headless/` HTTP API on the Python side. Cross-reference with `RUST_PORT_ROADMAP.md` §1.
- `include/project.hpp` + `src/project.cpp` (~568 LOC) — project save/load JSON. Renderer-coupled (saves CameraState, material overrides). Split: serde data → geometry crate; renderer-specific fields → renderer crate.
- `include/physics_bridge.hpp` + `src/physics_bridge.cpp` (~506 LOC) — bridge from Building to `addons/physics_sim`. Defers with physics_sim.
- `src/physics_bridge_fixed.cpp` (434) — duplicate of `physics_bridge.cpp` (not in CMake source list). **Drop.**

---

## 2. Geometry kernel — full Rust port plan

### Crate structure (proposed)

```
legible_studio_geometry/         # Pure CPU. The deliverable.
├── archgeometry/                # Schema + canonical geometry generators (port of Shared/ArchGeometry)
│   ├── schema_types             # SchemaDocument, SchemaWall, ...
│   ├── geometry_types           # Mesh3D, Geometry2D, WallGeometry, ...
│   ├── schema_parser            # JSON → SchemaDocument
│   ├── wall_geometry            # generators
│   ├── floor_geometry
│   ├── roof_geometry
│   ├── opening_geometry
│   ├── room_geometry
│   └── query_api
├── csg                          # BSP CSG: union/diff/intersection
├── bvh                          # SAH BVH builder (CPU only; GPU node format moves to renderer crate)
├── drawing                      # MERGED slicer_2d + plan_generator (§8 Q1):
│   ├── slice                    #   3D → 2D plane slicing
│   ├── annotate                 #   dimensions, grids, north arrow, symbols, roof pitch indicators
│   ├── svg                      #   SVG emission
│   └── dxf                      #   DXF emission (via `dxf` crate)
├── wall_system                  # Parametric walls, corner detection, L-corner adjustment
├── qbd                          # QBD JSON ingest, building conversion
├── obc                          # Span/stud/header tables, compliance validation
├── domain                       # StructuralElement, Building, WallType, ParametricWall, color palettes, AABB/Frustum
├── io                           # JSON ser/de (serde), geometry_loader equivalent
└── api                          # axum HTTP API (replaces ipc_server, §8 Q6)
```

`legible_studio_geometry` should compile with **no Vulkan, no wgpu, no GLFW, no ImGui**. Add `#![forbid(unsafe_code)]` at the crate root to make this a structural property, and `cargo deny` to keep transitive deps small.

### Per-module detail

#### `archgeometry::schema_types`
- **Purpose:** Canonical C++ types for the ArchEngine JSON schema (SchemaDocument, SchemaWall, SchemaFloor, SchemaDoor, SchemaWindow, SchemaRoof, SchemaRoom, WallLayer, WallType, etc.).
- **Source:** `Shared/ArchGeometry/include/archgeometry/schema_types.hpp` (269 LOC)
- **C++ deps:** `<vector>`, `<string>`, `<array>`, `<optional>`, `<unordered_map>`, `<cmath>`. Own `Vec3`/`Vec2` types (does NOT use GLM — important: this part is GLM-free, unlike the kernel side).
- **Rust crates:** `serde` + `serde_json`. Replace own `Vec3`/`Vec2` with `glam::Vec3` / `glam::Vec2`. `Option` for `std::optional`. `HashMap` for `std::unordered_map`.
- **Port complexity:** Small (days). Almost a direct translation. Watch for `std::array<std::string,2>` (a fixed-size 2-tuple) → `[String; 2]`.
- **Depends on:** nothing.
- **Depended on by:** every other module in `archgeometry`, plus `qbd`, `slicer_2d`, `plan_generator`, `domain`.

#### `archgeometry::geometry_types`
- **Purpose:** Output structures for generated meshes and 2D drawings (Mesh3D, Vertex3D, Triangle, Geometry2D, Line2D, Polygon2D, Arc2D, Text2D, WallGeometry, FloorGeometry, RoofGeometry, DoorGeometry, WindowGeometry, RoomBoundary, BuildingGeometry).
- **Source:** `Shared/ArchGeometry/include/archgeometry/geometry_types.hpp` (233 LOC)
- **C++ deps:** `schema_types.hpp` for `Vec3`/`Vec2`/`Point2D`.
- **Rust crates:** `glam` for vectors. The `addQuad`/`addTriangle`/`merge` methods translate to associated functions on `Mesh3D`.
- **Port complexity:** Small (days). Watch the `std::array<float, 4>` fill_color → `[f32; 4]`.
- **Depends on:** `schema_types`.

#### `archgeometry::schema_parser`
- **Purpose:** Parse a JSON document into `SchemaDocument`.
- **Source:** `Shared/ArchGeometry/include/archgeometry/schema_parser.hpp` (52 LOC) + `src/schema_parser.cpp` (390 LOC)
- **C++ deps:** nlohmann/json. Returns `ParseResult<T>` (their own Result-like type).
- **Rust crates:** `serde` derives for every schema type — replaces both the parser AND `geometry_loader`'s nlohmann serialization in one go. `serde_json::from_str` / `from_reader`. `ParseResult<T>` becomes `Result<T, ParseError>` with `thiserror`.
- **Port complexity:** Small (days). Big simplification: nlohmann's manual `to_json`/`from_json` becomes `#[derive(Serialize, Deserialize)]`.
- **Depends on:** `schema_types`.

#### `archgeometry::wall_geometry` / `floor_geometry` / `roof_geometry` / `opening_geometry` / `room_geometry`
- **Purpose:** Generators that turn schema elements into output geometry. Walls produce both `Mesh3D` and `Geometry2D` plan/section views, plus cutout regions for doors/windows.
- **Source:** 5 cpp files totaling ~1,200 LOC (243 + 154 + 288 + 399 + 146)
- **C++ deps:** schema_types, geometry_types. Pure math, no I/O.
- **Rust crates:** `glam` for vectors. `parry3d` is overkill here — these generators emit triangles directly, no collision queries needed.
- **Port complexity:** Medium (1-2 weeks for all five). Cleanest part of the codebase — straight geometry, no Vulkan, no surprises. Roof generators may be the trickiest (gable/hip/mansard/gambrel polygon construction).
- **Depends on:** `schema_types`, `geometry_types`.

#### `archgeometry::query_api`
- **Purpose:** Spatial queries — walls in a room, openings on a wall, etc. (104 + 292 LOC).
- **Rust crates:** `HashMap`s for index lookups. `rstar` only if perf demands spatial indexing — start without it.
- **Port complexity:** Small (3-5 days).

#### `csg`
- **Purpose:** BSP-based CSG. Union/intersection/difference on triangle meshes. Used for door/window cutouts in walls.
- **Source:** `include/csg.hpp` (90 LOC) + `src/csg.cpp` (274 LOC)
- **Algorithm:** Möller–Trumbore ray-triangle, plane-classify-and-split per triangle, recursive BSP tree, clip-and-invert for boolean ops. Custom `Triangle`/`Mesh`/`Plane`/`BSPNode` types.
- **C++ deps:** GLM (vec3, cross, dot, normalize). `<unique_ptr>` for BSP node ownership.
- **Rust crates:** `glam`. Two options:
  - **(a) Port directly** — the code is 364 LOC and self-contained. BSP children become `Option<Box<BSPNode>>`. EPSILON constants port verbatim. Recommended for fidelity: matches existing behavior bit-for-bit.
  - **(b) Replace with `csgrs`** (https://crates.io/crates/csgrs) or `boolean-csg` — saves the port effort but introduces a behavior delta that needs validation against the C++ output.
- **Port complexity:** Small-to-medium (1 week if porting; 2-3 days if swapping for a crate + a few days re-validating). **Recommend (a)** — too small to be worth the abstraction risk, and the comments admit the impl is hand-rolled.
- **Depends on:** `domain::Vertex`-like types.
- **Depended on by:** `wall_system` (for openings), `mesh::Geometry::CSG` (walls with multiple openings).

#### `bvh`
- **Purpose:** SAH-based BVH builder. Output is a flat node array that the GPU path tracer traverses. The builder itself is pure CPU; only the output format is GPU-bound.
- **Source:** `include/bvh.hpp` (307 LOC) + `src/bvh.cpp` (1,007 LOC)
- **Algorithm:** Standard PBRT-style SAH with bucket partitioning. 32-byte aligned GPU node layout using `memcpy`-based bit-aliasing to store `u32` child indices in `vec4.w` (`f32`) fields — clever but a clear C++ idiom that needs a deliberate Rust redesign.
- **C++ deps:** GLM (AABB math). `std::span`. `std::vector` heavily.
- **Rust crates:** `glam`. Standard `Vec<T>`. Replace `std::span<T>` with `&[T]`.
- **Port complexity:** Medium (1-2 weeks). The SAH algorithm ports cleanly. **The pitfall is the GPU node layout** — see §7. In Rust, use a `union`-free design: store child indices as `u32` in a separate field rather than bit-aliasing into a `[f32; 4]`. The GPU upload code can then `bytemuck::cast` into the GPU's expected format at the renderer boundary, with the boundary explicit and tested.
- **Depends on:** `glam`, `domain::AABB`.
- **Depended on by:** Path tracer (renderer side). The CPU builder belongs to the geometry crate; the GPU node format lives in the renderer crate.

#### `qbd`
- **Purpose:** QBD layout ingest. Loads layouts from the Python QBD generator, converts to internal `Building` type, dispatches OBC validation and documentation generation. The orchestration entry point that the rest of Legible Studio talks to.
- **Source:** `include/qbd_interface.hpp` (479 LOC) + `src/qbd_interface.cpp` (1,085 LOC)
- **C++ deps:** nlohmann/json, archgeometry (optional, used via `parseWithArchGeometry`), obc_engine, slicer_2d.
- **Rust crates:** `serde` + `serde_json`. `Option` for the unique_ptr-based `m_archDoc` / `m_archQuery`. `HashMap` for `m_layerConfigs`.
- **Port complexity:** Medium (2-3 weeks). The orchestration logic is straightforward; the validation/dispatch code is large but routine. The main port decision: the C++ has BOTH its own JSON path AND a `parseWithArchGeometry` path that delegates to the shared library. **In Rust, collapse to one path** — use `archgeometry::schema_parser` exclusively. The kernel's own QBD parsing logic is legacy duplication.
- **Depends on:** `archgeometry::*`, `obc`, `slicer_2d`, `domain`.

#### `obc`
- **Purpose:** Ontario Building Code tables — joist/stud/header/rafter span lookups, thermal R-value requirements by climate zone, compliance reports for a wall assembly or whole building.
- **Source:** `include/obc_engine.hpp` (271 LOC) + `src/obc_engine.cpp` (601 LOC)
- **C++ deps:** Loads tables from disk (path passed via `initialize()`). `std::optional` everywhere for "not applicable" / "data missing." `<unordered_map>`.
- **Rust crates:** `Option<T>` directly. `HashMap`. Table files are loaded as JSON or CSV — keep the same on-disk format to avoid data migration.
- **Port complexity:** Small-to-medium (1-2 weeks). The algorithmic content is table lookups + arithmetic comparisons; no clever math. The volume comes from the number of code checks. **Recommend porting test fixtures first** — span values from the OBC tables are an excellent regression oracle (they should match C++ output exactly).
- **Depends on:** `domain::WallType` for assembly validation.
- **Depended on by:** `qbd::QBDInterface::validateLayout`.

#### `drawing` (merged `slicer_2d` + `plan_generator` — §8 Q1)
- **Purpose:** Single 2D-drawing module that owns everything from slicing 3D geometry through to emitting SVG/DXF/PDF. Sub-modules: `slice` (3D → 2D math), `annotate` (dimensions, grids, north arrow, symbols, roof pitch indicators), `svg` (SVG emission), `dxf` (DXF emission). Wall section details (`WallSectionDetail`) live in `slice` since they're geometry-first.
- **Source:** `include/slicer_2d.hpp` (329) + `src/slicer_2d.cpp` (704) + `include/plan_generator.hpp` (560, header-only). C++ total ~1,593 LOC.
- **C++ deps:** GLM, nlohmann/json (plan_generator uses `json` directly for room/roof data), `<sstream>`, `<cmath>`, `<iomanip>`, `<unordered_map>`.
- **Rust crates:**
  - `glam` for vectors.
  - **SVG emission:** manual `write!` — both C++ halves do manual string assembly, no clever XML, keep parity.
  - **DXF emission:** `dxf` crate (https://crates.io/crates/dxf) — DXF spec is finicky and the crate handles it.
  - **Geometric primitives:** own structs (`Line2D`, `Polyline2D`, `Polygon2D`, `Arc2D`, `Circle2D`, `Text2D`, `Hatch2D`, `Dimension2D`). Don't pull `geo` — the C++ types are tight and well-shaped already.
  - `serde_json::Value` for the few dynamic-JSON paths in annotation generation.
- **Port complexity:** Medium-large (3 weeks). Combined module slightly more than the sum of the parts because of the up-front refactor to a clean `slice → annotate → emit` pipeline. Pays off in maintenance — no more drift between two SVG paths.
- **Depends on:** `domain::Building` / `ParametricWall` / `WallType` / `MeshData` / `Frustum`.
- **Depended on by:** `qbd::generateDocumentation`.
- **Note:** the merge is the deliberate point. Don't recreate the two-path structure.

#### `wall_system`
- **Purpose:** Parametric wall geometry generation. Detects corners between walls (endpoints within tolerance), classifies corner type (L/butt/miter), adjusts wall endpoints so layers connect properly, generates per-layer box meshes. Includes inline `createExterior2x6Wall`/`Interior` default factories.
- **Source:** `include/wall_system.hpp` (298 LOC, header-only)
- **C++ deps:** `<cmath>`, types.hpp. No external deps. Note: per-face winding both ways (each face is emitted with both orientations) — a quirk that suggests culling was disabled or unreliable; revisit during port.
- **Rust crates:** `glam`. Pure math.
- **Port complexity:** Small (3-5 days). The corner-detection algorithm is O(N²) over walls; a small wall set makes this fine but flag for future indexing if it ever needs to scale. The "both winding orders" quirk should NOT be carried over without understanding — investigate why before porting.
- **Depends on:** `domain::ParametricWall`, `WallType`, `MeshData`, `vec2`/`vec3`.

#### `geometry_loader`
- **Purpose:** JSON building loader + sample building constructors (createSimpleFrame, createMultiStoryFrame, createWarehouse, createResidential) + IFC import (simplified) + nlohmann `to_json`/`from_json` for Building/WallType/ParametricWall/LayerFastener/AssemblyConstraint/IntentBlock/WallLayer.
- **Source:** `include/geometry_loader.hpp` (57 LOC) + `src/geometry_loader.cpp` (992 LOC)
- **C++ deps:** nlohmann/json, `<fstream>`, `renderer.hpp` (for `loadMaterialOverrides(Renderer&)` — the ONE renderer dependency in the geometry half).
- **Rust crates:** `serde` derives replace all manual `to_json`/`from_json`. `std::fs` for file I/O.
- **Port complexity:** Medium (1-2 weeks). Sample builders are volume but mechanical. IFC import is intentionally simplified ("just extracts basic geometry") — port the simplified version, defer real IFC parsing.
- **Decoupling:** `loadMaterialOverrides(filepath, Renderer&)` should split — the JSON parsing goes here, the renderer mutation goes in the renderer crate via a callback or a returned `MaterialOverrideSet` value.

#### `mesh::Geometry` namespace (CPU half of `mesh.hpp`/`mesh.cpp`)
- **Purpose:** Procedural mesh generators for structural primitives — beams, columns, floor slabs, deflected beams, grids, spheres, arrows, doors, windows, roofs (flat/gable), gable walls. Plus `Geometry::CSG::wallWithOpening` / `wallWithMultipleOpenings`.
- **Source:** The CPU half of `mesh.hpp` (~80 of 91 LOC) + the CPU half of `src/mesh.cpp` (estimate ~700 of 988 LOC).
- **C++ deps:** GLM, `<cmath>`. No Vulkan.
- **Rust crates:** `glam`. Pure functions.
- **Port complexity:** Medium (1-2 weeks). Mostly volume. The `createDeflectedBeam` (curved due to load) uses a parabolic deflection profile that ports verbatim. `createGableRoof`/`createGableWall` are non-trivial polygon construction — port carefully and validate.
- **Depends on:** `domain::Vertex`, vec3, vec2.

#### `domain` (the domain half of `types.hpp`)
- **Purpose:** The semantic types that the rest of the geometry crate needs — `StructuralElement`, `Building`, `WallType`, `WallLayer`, `ParametricWall`, `WallCorner`, `MeshData`, `TerrainMesh`, `MaterialPreset`, `LightingData`/`ThermalData`/`AcousticData`, color palettes (StressColors, ThermalColors, LightingColors, AcousticColors), Frustum + AABB + Plane (CPU-side culling math), all the enums (ElementType, LayerFunction, FastenerType, ConstraintType, IntentCategory, CornerType, VisualizationMode, MaterialStyle, WallCategory, DoorType/Swing, WindowType, RoomZone, RoofType, SymbolType, RoofAnnotationType, PlanType).
- **Source:** The non-GPU portion of `include/types.hpp` (~450 of 722 LOC).
- **C++ deps:** GLM, `<vector>`, `<string>`, `<array>`, `<unordered_map>`.
- **Rust crates:** `glam`. The color palettes' `glm::mix` becomes `glam::Vec3::lerp`. The `inline` factory functions for `Materials::OakWood()` etc. become `pub const fn` or `pub fn` factories.
- **Port complexity:** Medium (1 week). Volume work; few decisions. Major decision: how to split — see §7 "types.hpp split."

### Dependency graph (geometry kernel)

```
domain (no deps)
  ↑
schema_types ← geometry_types
  ↑              ↑
schema_parser    (cycles forbidden; geometry_types only uses schema_types' Vec2/Vec3)
  ↑
[wall|floor|roof|opening|room]_geometry  ← query_api
  ↑
csg ← wall_system
  ↑
mesh::Geometry
  ↑
geometry_loader ← obc ← drawing (slice/annotate/svg/dxf)
                    ↑       ↑
                    └── qbd ┘
                         ↑
                         api (axum HTTP)
                         ↑
                       (top-level Legible Studio app or external CAD consumer)

bvh: parallel — consumed by renderer, not by geometry app code
```

### Topological port order

1. **domain** (week 1)
2. **archgeometry::schema_types**, **geometry_types** (week 1)
3. **archgeometry::schema_parser** (week 1-2; quick because of serde)
4. **archgeometry generators** (wall/floor/roof/opening/room, week 2-3)
5. **archgeometry::query_api** (week 3)
6. **csg** (week 3-4)
7. **wall_system** (week 4)
8. **mesh::Geometry** generators (week 4-5)
9. **geometry_loader** (week 5-6; serde makes this trivial vs C++'s manual)
10. **obc** (week 6-7)
11. **drawing** (week 7-10; merged slicer + plan_generator — see §8 Q1)
12. **qbd** (week 10-12; depends on everything above)
13. **bvh** (week 12-13; parallel deliverable, but useful for renderer integration)
14. **api** (week 13; axum HTTP, replaces ipc_server — see §8 Q6)

Headroom buffer: 3 weeks for surprises in CSG, the merged drawing module's refactor surface, and the types.hpp split. **Honest estimate: 13–17 weeks at hobby pace** (15-20h/week).

### Milestones (as regression tests)

- **M1 (week 3):** `archgeometry` Rust output matches C++ output to 4 decimal places on the QBD test corpus (`test_building.json`, `test_building_qbd.json`). Specifically: parse a QBD JSON, generate all walls/floors/roofs, hash the vertex/index arrays, diff against C++.
- **M2 (week 6):** CSG operations produce matching meshes for wall-with-door and wall-with-multiple-openings test cases. Vertex count and topology must match (vertex positions to 4 decimals).
- **M3 (week 8):** OBC validation results (`ComplianceReport`) byte-identical to C++ for the full QBD corpus.
- **M4 (week 10):** SVG output from `drawing::floor_plan` is diff-clean against C++ on all test buildings. Text positions to 1px tolerance. (Note: bit-identical for 2D per §8 Q11.)
- **M5 (week 12):** End-to-end: QBD JSON → permit-set SVG bundle in pure Rust, no C++ in the pipeline.
- **M6 (week 14):** The Legible Studio Python orchestration calls the Rust binary (via subprocess or pyo3 binding) instead of the C++ DLL. C++ removed from the desktop build.

---

## 3. Vulkan renderer — inventory + sketch

The handoff calls for sketch, not blueprint. Below is the inventory; recommended Rust target is `wgpu` for the bulk with `ash` reserved for the path tracer only if KHR_ray_tracing performance proves load-bearing.

**Reminder:** the Semantic OS kernel does NOT yet have a Vulkan implementation. Phase 9+ kernel work targets the iGPU (Iris Xe). Until that exists, this Rust port runs on desktop only. `wgpu` is the right choice precisely because it maps onto whatever backend the kernel exposes when it ships — Vulkan on desktop today, kernel-iGPU-driver tomorrow.

### Renderer module inventory

| Module | LOC (cpp+hpp) | Render technique | Inputs from geometry | Shader lang | Rust target |
|---|---|---|---|---|---|
| `vulkan_context` | 1,282 | Vulkan init: instance, device, queues, swapchain, command pools | n/a | n/a | `wgpu::Instance`/`Device`/`Queue` replaces 90%; drop |
| `pipeline` | 478 | VkPipeline wrapper, shader module loading | n/a | SPIR-V loader | `wgpu::RenderPipeline` builder pattern |
| `descriptor_manager` | 394 | Descriptor pool/layout/set | n/a | n/a | `wgpu::BindGroup`/`BindGroupLayout` |
| `instance_batch` | 218 | Per-instance vertex buffer for batched draws | `Vec<InstanceData>` | n/a | `wgpu::Buffer` with `Vertex` step mode `Instance` |
| `shadow_map` | 660 | Depth-only pass, PCF in shader | `Vec<StructuralElement>` | GLSL (vert+tesc+tese) | `wgpu` render pass with depth attachment only |
| `environment_map` | 1,326 | Equirect HDR → cubemap; IBL precompute (irradiance, prefiltered envmap, BRDF LUT) | HDR image file (Poly Haven) | GLSL compute | `wgpu` compute passes; one-shot at load |
| `post_process` | 2,125 | SSAO, bloom (bright + multi-tap blur), tonemap (Reinhard/ACES/Uncharted2), composite, SSR | HDR color + depth + normal textures | GLSL frag | `wgpu` ping-pong textures + fragment shaders |
| `texture` | 706 | Image upload, mip generation, format conversion | image files via stb_image | n/a | `wgpu::Texture` + `image` crate for decode |
| `path_tracer` | 1,630 | Compute path tracer w/ BVH traversal, BRDF sampling, MIS, denoiser | `GPUTriangle[]`, `GPUBVHNode[]`, `GPUPTMaterial[]` from `bvh` | GLSL compute (`path_trace.comp` 653 LOC + KHR-RT `raygen.rgen`/`closesthit.rchit`/`miss.rmiss`) | **wgpu compute in v1; KHR-RT later behind `hardware-rt` feature flag** (§8 Q3) |
| `renderer` | 6,839 | The orchestrator: forward PBR + shadow + IBL + post + path tracer + UI compositing. Multi-light system (16 max). Per-element material overrides via push constants. | `Building`, `Vec<StructuralElement>`, `TerrainMesh`, materials | GLSL forward (`structural.vert`/`frag`/`tesc`/`tese`, `sky.vert`/`frag`) | `wgpu` |
| `mesh` (Vulkan half) | ~300 | RAII VkBuffer + VkDeviceMemory wrappers | `Vec<Vertex>` + `Vec<u32>` | n/a | `wgpu::Buffer` with `usage: VERTEX \| INDEX` |
| `imgui_layer` | 3,387 | Dear ImGui Vulkan backend + the entire app UI (materials panel, scene tree, light editor, render settings) | n/a | ImGui's own | `egui` + `egui-wgpu` is the natural Rust analog; OR keep `imgui-rs` + `imgui-wgpu`. **Recommend `egui`** — better ecosystem fit, simpler bind-group story. UI logic is a rewrite, not a port. |
| `window` | 183 | GLFW wrapper | n/a | n/a | `winit` |
| `main` | 2,014 | Application entry, scene setup, input, camera | All the above | n/a | Rewrite; UI shell |
| `arch_api` | 2,636 | C ABI for DLL embedding in CAD/Python | All the above | n/a | **Do not port** (§8 Q4) — Python orchestration is itself becoming Rust, C ABI becomes dead weight. Re-add only when a concrete non-Rust consumer reappears. |
| `memory` (Vulkan alloc) | 386 | Custom VkDeviceMemory allocator (not VMA) | n/a | n/a | `wgpu` handles allocation; drop. (If raw Vulkan via `ash`, use `gpu-allocator`.) |
| `lights` | 148 | Light struct (Directional/Point/Spot) | n/a | UBO layout | Data type; lives in renderer crate as both CPU struct and `bytemuck`-friendly GPU layout. |

### Path tracer: wgpu vs ash decision

The path tracer has TWO implementations side-by-side:
- A **compute shader path** (`shaders/path_trace.comp`, 653 LOC) that does BVH traversal in software inside a compute kernel.
- A **KHR_ray_tracing path** (`raygen.rgen`/`closesthit.rchit`/`miss.rmiss`/`shadow_miss.rmiss`) using hardware acceleration structures.

`wgpu` (as of late 2025) **does not expose KHR_ray_tracing** in stable. The compute-shader path tracer ports cleanly to wgpu; the hardware-RT path does not.

**Decision (§8 Q3):** port the **compute path tracer to wgpu** as the primary in v1. Keep a placeholder `ash`-based KHR-RT module behind `cargo` feature `hardware-rt` for future use — don't write the ash code until the need is concrete (offline-quality renders of finished designs is the most likely trigger).

**Per the pivot:** the renderer is verification view, not centerpiece. Spending engineering on hardware RT is premature optimization. Compute path tracer is fine.

### Shader layer

All GLSL ports to `wgsl` (wgpu's shader language) — or compile GLSL → SPIR-V → wgpu directly via `wgpu`'s SPIR-V support. Two options:

- **(a) Rewrite to WGSL.** More work upfront but the shaders become Rust-native, version-controlled, and benefit from `naga` validation. Recommended for new code.
- **(b) Reuse SPIR-V.** Feed existing `.spv` to wgpu via `ShaderSource::SpirV`. Lower friction; preserves shader behavior exactly; loses WGSL's static checking. Recommended as the migration bridge during port.

Recommend **(b) initially, (a) over time.** Don't gate the renderer port on shader rewriting.

### Inputs from the geometry kernel

The renderer consumes from the geometry crate:
- `Building` (the scene)
- `Vec<StructuralElement>` (drawables)
- `TerrainMesh` (terrain plane)
- `Vec<WallType>` + `Vec<ParametricWall>` (parametric walls, generated into `StructuralElement`s on the fly via `WallSystem::toStructuralElements`)
- `Vec<MaterialPreset>` + per-element material overrides
- `bvh::{GPUTriangle, GPUBVHNode, GPUPTMaterial}` for the path tracer
- Camera state, light arrays

All of these are POD-ish. With `serde` for serialization and `bytemuck` for GPU upload, the boundary is clean.

---

## 4. Shared infra

### `types.hpp` split

This is the highest-leverage decision in the whole port. Split `include/types.hpp` (722 LOC) at the port start into three pieces:

1. **`legible_studio_geometry::domain`** (pure CPU) — `StructuralElement`, `Building`, `WallType`, `WallLayer`, `ParametricWall`, `WallCorner`, `MeshData`, `TerrainMesh`, `MaterialPreset`, `Materials::*` factories, `ThermalData`/`LightingData`/`AcousticData`, all `StressColors`/`ThermalColors`/`LightingColors`/`AcousticColors` palettes, `Plane`, `Frustum`, `AABB` (CPU culling math), all the enums.
2. **`legible_studio_renderer::gpu_layouts`** (renderer-only) — `Vertex` (with vertex attribute bindings adapted to wgpu's `VertexBufferLayout`), `InstanceData`, `GPULight`, `PushConstants`, `UniformBufferObject`, `MaterialOverrideBits`, `EffectFlags`.
3. **`legible_studio_renderer::camera`** — `Camera`, `CameraState`. The serialize/deserialize half belongs to `domain` (so `project.cpp` save/load works without renderer dep); the matrix math belongs here.

The C++'s `Vertex::getBindingDescriptions()` returning Vulkan-specific `VkVertexInputBindingDescription` becomes `Vertex::wgpu_layout() -> wgpu::VertexBufferLayout<'static>` in the renderer crate.

### Common shared infra replacements

| C++ | Rust | Notes |
|---|---|---|
| GLM (`vec2`/`vec3`/`vec4`/`mat3`/`mat4`/`quat`) | `glam` | Same naming conventions; SIMD by default. Use `glam` consistently across both crates. |
| Custom `AABB`/`Frustum`/`Plane` | own types in `domain`, or `parry3d::bounding_volume::Aabb` | Recommend own types — the C++ AABB/Frustum/Plane are small and the kernel's algorithmic usage is tight; importing parry3d for this is overkill. |
| `<vector>` / `<unordered_map>` / `<string>` / `<optional>` / `<span>` | `Vec`/`HashMap`/`String`/`Option`/`&[T]` | Direct. |
| `<memory>` `unique_ptr`/`shared_ptr` | `Box<T>` / `Arc<T>` | Most usages are `unique_ptr` → `Box`. |
| `<fstream>` | `std::fs::File`, `BufReader`/`BufWriter` | |
| nlohmann/json | `serde` + `serde_json` | Massive simplification — no manual `to_json`/`from_json`. |
| stb_image / stb_image_write | `image` crate | Same formats. |
| Logging (the C++ has very little — std::cerr scattered) | `tracing` | Strong recommendation; structured logs are worth setting up from day 1. |
| GLFW | `winit` | Window + input. |
| Dear ImGui | `egui` + `egui-wgpu` | Rewrite UI layer. |
| cpp-httplib (LLM endpoint, IPC server) | `reqwest` (client) / `axum` (server) | Per pivot, LLM is cut. IPC server may survive — see §1 aux. |
| File paths — C++ uses `std::string` for everything | `PathBuf` / `&Path` | Don't perpetuate `String`-as-path. |
| Custom `u8`/`u16`/`u32`/`u64`/`i*`/`f32`/`f64` aliases | Built-ins (`u8`, `i32`, `f32`, etc.) | Drop the aliases. |
| `namespace arch { ... }` everywhere | Crate-level module structure | Rust modules replace nested namespaces (`arch::qbd::*` → `qbd::*` within a crate). |

### no_std posture

Per the handoff: desktop Rust port can use `std`. Eventual kernel target requires dropping `std::thread`, `std::sync::Mutex` (in favor of kernel-provided sync primitives), etc.

- **Geometry crate:** could be `no_std`-friendly with `alloc` if `serde`, `serde_json`, `image`, `dxf`, file I/O, and `tracing` are gated behind `std` feature flag. **Recommend std-only for v1**, with the intent to feature-gate the I/O later when the kernel target firms up. Don't pre-optimize for `no_std` — it's a measurable port-time cost for a kernel-side milestone that's 12+ months out.
- **Renderer crate:** `wgpu` requires `std`. Period. Doesn't matter — renderer doesn't run on the kernel until Phase 9+ anyway.

---

## 5. Port order — geometry kernel (concrete sequence)

(Same as §2 topological order, restated as a checklist.)

**Foundation (weeks 1-2):**
- [ ] Split `types.hpp` into `domain` (Rust) + a renderer-crate GPU-layouts stub
- [ ] Port `domain` enums, structs, color palettes, AABB/Frustum
- [ ] Port `archgeometry::{schema_types, geometry_types}` with serde derives
- [ ] **Milestone M1a:** parse `test_building.json` and `test_building_qbd.json` into `SchemaDocument`; round-trip equality test

**Mid (weeks 3-8):**
- [ ] Port `archgeometry::schema_parser` (mostly: derive + tweaks)
- [ ] Port `archgeometry::{wall, floor, roof, opening, room}_geometry` generators
- [ ] Port `archgeometry::query_api`
- [ ] **Milestone M1:** Rust archgeometry output matches C++ to 4 decimals on test corpus
- [ ] Port `csg` (hand-port the BSP)
- [ ] Port `wall_system` (corner detection + L-corner adjustment)
- [ ] Port `mesh::Geometry::*` procedural generators (beam/column/floor/door/window/roof variants)
- [ ] **Milestone M2:** CSG wall-with-opening matches C++
- [ ] Port `geometry_loader` (with serde everywhere)
- [ ] Port `obc` engine + tables
- [ ] **Milestone M3:** OBC validation reports byte-identical

**Late (weeks 9-13):**
- [ ] Port `drawing` module: `slice` + `annotate` + `svg` + `dxf` (merged slicer_2d + plan_generator per §8 Q1)
- [ ] **Milestone M4:** SVG floor plan diff-clean (bit-identical per §8 Q11)
- [ ] Port `qbd::QBDInterface` (the orchestrator)
- [ ] **Milestone M5:** end-to-end permit-set in pure Rust
- [ ] Build `api` module (axum HTTP, replaces ipc_server per §8 Q6)
- [ ] Build `project-migrate` one-shot binary (splits old single-file projects per §8 Q7)

**Parallel (weeks 9-13):**
- [ ] Port `bvh::BVHBuilder` (CPU only). GPU node format goes in renderer crate.

**Integration (weeks 13-17):**
- [ ] Wire Rust geometry binary into Legible Studio Python pipeline (subprocess or `pyo3` binding)
- [ ] **Milestone M6:** C++ engine removed from Legible Studio desktop build
- [ ] Update README.md to remove "Proprietary - All rights reserved" line (per §8 Q12)

---

## 6. LOC + effort estimate

### Geometry kernel — per module

| Module | C++ LOC | Rust LOC est. (0.6× factor due to serde + better stdlib) | Effort |
|---|---|---|---|
| `domain` (types.hpp split) | ~450 | ~300 | 1 wk |
| `archgeometry::schema_types` | 269 | 180 | 0.3 wk |
| `archgeometry::geometry_types` | 233 | 160 | 0.3 wk |
| `archgeometry::schema_parser` | 442 | 200 (serde does the work) | 0.5 wk |
| `archgeometry` generators (5 modules) | 1,438 | 1,000 | 2 wk |
| `archgeometry::query_api` | 396 | 280 | 0.5 wk |
| `csg` | 364 | 300 | 1 wk |
| `bvh` (CPU half) | 1,314 | 900 | 1.5 wk |
| `wall_system` | 298 | 220 | 0.5 wk |
| `mesh::Geometry` | ~780 | 550 | 1.5 wk |
| `geometry_loader` | 1,049 | 400 (serde collapses most) | 1 wk |
| `obc` | 872 | 600 | 1.5 wk |
| `drawing` (merged slicer_2d + plan_generator, §8 Q1) | 1,593 | 1,150 | 3 wk |
| `qbd::QBDInterface` | 1,564 | 1,100 | 2.5 wk |
| `api` (axum HTTP, replaces ipc_server, §8 Q6) | (new) | 200 | 0.5 wk |
| `project-migrate` binary (one-shot, §8 Q7) | (new) | 100 | 0.2 wk |
| **Total geometry** | **~11,062** | **~7,400** | **~17 weeks** |
| Buffer (CSG, merged drawing refactor, types-split surprises) | | | +3 wk |
| **Honest estimate, hobby pace** | | | **~20 weeks (5 months)** |

Note: estimates lean optimistic on routine translation (since the author wrote the C++ and has deepest context). The buffer covers the 3 modules with the highest pattern-divergence risk (CSG ownership, BVH bit-aliasing, types.hpp split). If those land cleanly, knock 2 weeks off the buffer.

### Renderer (sketch, not blueprint)

~22,800 LOC C++ + ~2,700 LOC GLSL. With `wgpu` absorbing 60% of the Vulkan plumbing, expect:
- Pipeline/descriptor/swapchain/memory infrastructure: ~3-4 weeks (wgpu compresses this hard).
- Forward PBR + shadow + IBL: ~4-6 weeks.
- Post-process suite (SSAO/bloom/tonemap/SSR): ~3-4 weeks.
- Path tracer (compute path only): ~3-5 weeks.
- UI rewrite (ImGui → egui): ~4-6 weeks (more if you keep feature parity).
- Path tracer KHR-RT alternative: skip in v1.

**Renderer total: 16-24 weeks at hobby pace.** Secondary to geometry per pivot.

### Auxiliary

- `physics_sim` addon (~7,300 LOC): **defer.** Not on critical path; building physics models are a separate research effort.
- `llm_assistant`, `memory_test`: **drop.**
- `ipc_server` (~374 LOC): decision pending — see §8.
- `project` (~568 LOC): port alongside `geometry_loader`, ~3-5 days.

---

## 7. Pitfalls — C++ idioms that need redesign

### `types.hpp` is a kitchen sink — split or get entangled

**Where:** `include/types.hpp` lines 270–328 (GPU layouts) mixed with lines 156–168, 596–696 (domain types) and 703–797 (CPU culling math).

**Why it's a pitfall:** if you port `types.hpp` as one Rust module, both `domain` and `renderer` crates depend on it, and the renderer's `wgpu` dependency leaks into the geometry crate — defeating the whole reason for splitting.

**Redesign:** split at the start (see §4). The boundary is "does it have `VkVertexInputBindingDescription` or std140 padding in it?" → renderer. Otherwise → geometry.

### BVH node bit-aliasing (`memcpy` of `u32` into `f32`)

**Where:** `include/bvh.hpp` lines 86–131, `GPUBVHNode::setInternalNode`/`setLeafNode`/`getLeftChild`/`getPrimOffset`.

**Why it's a pitfall:** the C++ stores `u32` child indices in `vec4.w` fields (which are `f32`) using `std::memcpy` to bit-alias. This works in C++ because GLSL doesn't care about the bit-pattern in a `vec4` — it can `floatBitsToUint(node.boundsMin.w)` on the GPU side. Direct Rust port via `unsafe { transmute }` works but is needlessly `unsafe`.

**Redesign:** in Rust, use a `#[repr(C)]` struct with explicit `u32` and `f32` fields. Keep them separate in the CPU representation. At GPU upload boundary, use `bytemuck::cast_slice` to flatten into `[f32; 8]`-like GPU layout. The GPU shader (WGSL or GLSL) still uses `floatBitsToUint`, but the CPU side stays in safe Rust.

### CSG `std::unique_ptr<BSPNode>` recursive ownership

**Where:** `include/csg.hpp` lines 73-93.

**Why it's a pitfall:** Rust's borrow checker handles recursive ownership via `Option<Box<T>>`, but `BSPNode::clipTo(mut)` and `invert()` mutate the tree in-place. Translating naively yields `&mut self` recursion that fights the borrow checker if both children are visited and one's borrow outlives.

**Redesign:** structure as `&mut self` taking ownership at each level (`fn invert(self) -> Self`) — purely functional. Or use indices into a `Vec<BSPNode>` (arena) and pass `(arena, idx)` everywhere. Recommend the arena pattern — matches the eventual GPU upload anyway.

### Wall geometry emits both winding orders [RESOLVED §8 Q8]

**Where:** `include/wall_system.hpp` lines 178–200, `generateLayerMesh` emits every face with both `{a,b,c}` and `{a,c,b}` winding.

**Confirmed hack:** `pipeline.cpp:19` sets `VK_CULL_MODE_BACK_BIT` as default; `wall_system.hpp:177` emits both winding orders to work around inconsistent wall normals. Doubles wall triangle count.

**Fix during port:** match the pattern in `qbd_interface.cpp:728-751` — compute face normal from the first triangle, reverse winding if it points the wrong way. Single-sided faces. Halves wall triangle count and unblocks back-face-culled passes (no need for `VK_CULL_MODE_NONE` overrides on wall draws).

### Header-only with inline implementations (`plan_generator.hpp`, `wall_system.hpp`)

**Where:** both files are ~80% inline implementation, not just declarations.

**Why it's a pitfall:** in C++, header-only is a compile-time choice. In Rust, modules are modules — there's no real analog. Inline-heavy headers also smell like they were written quickly without a CMake source-list update.

**Redesign:** in Rust, just write normal `pub fn` in a regular module file. Nothing inline-only about it.

### nlohmann `to_json`/`from_json` per type

**Where:** `geometry_loader.hpp` lines 52–73 — 7 type pairs of free functions.

**Why it's a pitfall:** verbose, error-prone, easy to drift between `to_json` and `from_json`.

**Redesign:** `#[derive(Serialize, Deserialize)]` once per type. This is one of the biggest LOC compressions in the whole port.

### Parallel JSON paths in `qbd_interface` [RESOLVED — collapse to archgeometry]

**Where:** `QBDInterface::loadFromJSON` (its own nlohmann path) vs `QBDInterface::parseWithArchGeometry` (delegates to shared library).

**Why it's a pitfall:** two parse paths for the same input format → divergence over time. The `archgeometry` library was added as the canonical version but the kernel kept its old path.

**Redesign:** in Rust, only one path — `archgeometry::schema_parser`. Delete the legacy QBD-specific JSON code.

### Slicer + plan_generator overlap [RESOLVED §8 Q1]

**Where:** both have SVG export, both render floor plans.

**Resolution:** merge into single `drawing` module with sub-modules `slice` (3D→2D math), `annotate` (dims/grids/symbols), `svg` and `dxf` (emission). No more parallel SVG paths. See §2 crate structure.

### `arch_api.h` — 70+ exported C functions for DLL embedding [RESOLVED §8 Q4]

**Where:** `include/arch_api.h` (1,009 LOC) — `arch_init`, `arch_load_file`, `arch_render_frame`, `arch_set_element_material`, etc.

**Resolution:** do not port in v1. Python orchestration is itself becoming Rust per the sibling roadmap; the C ABI vanishes when both halves are Rust. Re-add only when a concrete non-Rust consumer reappears.

### Custom `u8`/`f32`/etc. type aliases everywhere

**Where:** `types.hpp` lines 30–46.

**Why it's a pitfall:** harmless but pervasive — every signature reads `f32` instead of `float`. Rust's `f32` is already the right name; the aliases are noise on the Rust side.

**Redesign:** drop the aliases. Use Rust built-ins directly.

### Push constant 160-byte struct (`PushConstants` in `types.hpp`)

**Where:** `types.hpp` lines 279-290.

**Why it's a pitfall:** the comment says "Total: 160 bytes (most GPUs support 256+)" — this is at the upper end of what's guaranteed by Vulkan spec (128 bytes minimum). `wgpu` exposes push constants only as an extension on some backends.

**Redesign:** in wgpu, replace push constants with a small dynamic-offset uniform buffer (slot 0 of a bind group). Adds one indirection but is universally portable. The 160-byte struct becomes a `#[repr(C)]` uniform with `bytemuck::Pod` impl. Same data, slightly different binding model.

### `<span>` heavy in BVH

**Where:** `bvh.hpp` line 14, `bvh.cpp` `buildRecursive` uses `std::span<BVHPrimitive>` to pass mutable subranges during partitioning.

**Why it's a pitfall:** trivial — `std::span<T>` → `&mut [T]`. Listed because it's pervasive in `bvh.cpp` and a clean translation pattern.

**Redesign:** `&mut [BVHPrimitive]`. Use `slice.split_at_mut(pivot)` to partition.

---

## 8. Resolutions (decisions baked in 2026-05-16)

All twelve open questions are decided. Recording here so future readers (and future-you) don't relitigate.

1. **Slicer + plan_generator → merge into single `drawing` module.** More aggressive than just subordinating `plan_generator`. Both halves collapse into `legible_studio_geometry::drawing` with sub-modules for slicing math, annotation, and SVG/DXF emission. See updated §2 crate structure. *Implication:* §5 port order swaps the separate slicer/plan_generator slots for one larger `drawing` slot (~3 weeks).

2. **CSG: hand-port the BSP.** 1 week. Preserves behavior exactly, gives a clean M2 diff oracle, no third-party dependency on a niche crate.

3. **Path tracer: compute path in v1, ash-based KHR-RT later behind a feature flag.** Port `path_trace.comp` (653 LOC) to wgpu compute as the default. Leave room for an `ash`-based KHR-RT module behind `cargo` feature `hardware-rt` for offline-quality renders if/when wanted. Don't write the ash code until that need is concrete.

4. **`arch_api` C ABI: defer indefinitely, do not port in v1.** If the Python orchestration becomes Rust (per the sibling roadmap), the C ABI becomes dead weight. Saves ~2-3 weeks of `extern "C" fn` boilerplate. Re-add only when a concrete non-Rust consumer reappears.

5. **`addons/physics_sim`: defer until post-M6.** Park the 7,300 LOC addon until C++ engine is removed from the desktop build. Revisit only if a paying customer or compliance check needs hygrothermal output. Realistically 6–12 months out.

6. **`ipc_server` → replace with `axum` HTTP API in the geometry crate.** Cleaner than the custom TCP protocol, reuses serde types, single Rust binary owns the network surface. ~3-5 days of `axum` wiring replaces ~374 LOC of custom TCP. Coordinates with the Legible Studio Python-port roadmap.

7. **`project.cpp` file format: split into separate files.** `project.json` (geometry — building, materials, levels) owned by geometry crate; `project.render.json` (camera, material overrides, render settings, light arrays) owned by renderer crate. Cleaner ownership, geometry crate has zero renderer dep. **Breaks backward compat with existing one-file `.json` projects** — provide a one-shot migration tool (`cargo run --bin project-migrate <old.json>`) that emits both new files.

8. **Wall mesh double-winding: fix during port.** Investigation confirmed it's a hack — `pipeline.cpp:19` enables back-face culling by default but `wall_system.hpp:177` emits both winding orders to work around inconsistent normals. Meanwhile `qbd_interface.cpp:728-751` already does the correct pattern for roof surfaces (compute face normal, reverse winding if it points the wrong way). **Port walls to match the roof pattern.** Halves wall triangle count and unblocks back-face-culled passes.

9. **OBC table file format: JSON (confirmed).** Tables live at `OBC_Library/tables/{obc_9.23_headers,joists,rafters,studs,fastener_schedules}.json`. Serde handles them directly — keep the on-disk format byte-identical so the C++ and Rust engines can share the same data dir during the cutover.

10. **Test corpus: known gap.** ArchGeometry has gtest unit tests (`test_schema_parser.cpp`, `test_wall_geometry.cpp`, `test_floor_geometry.cpp`, `test_query_api.cpp`). `csg`, `obc`, `slicer`, `qbd`, `plan_generator`, `wall_system`, `bvh` have **no unit tests in the kernel** — only the whole-pipeline diff against `test_building.json` / `test_building_qbd.json`. **The Rust port grows per-module tests as it goes.** Each milestone (M1–M6) ships with new unit tests covering the modules it landed; the diff-against-C++ corpus is a backstop, not the primary oracle.

11. **Output fidelity bar: split — 2D bit-identical, 3D visually equivalent.** Permit drawings (SVG/DXF/PDF) must diff-clean against C++ output — they're vector, reviewer-visible, and the natural diff oracle is clean. 3D renderer output only needs to look right; bit-identical is infeasible across GPU drivers anyway. Milestones M1–M5 enforce bit-identical for 2D; the renderer half has no equivalent gate.

12. **License: MIT (matches `LICENSE.txt`).** README.md's "Proprietary - All rights reserved" line is wrong — update the README to remove it. Rust port stays MIT-licensed, freely shareable. Permissive deps (glam BSD/MIT, serde MIT/Apache, wgpu MIT/Apache, image MIT/Apache, dxf MIT) all compatible.

---

## Cross-references

- This document: `F:/Software/LegibleStudios/docs/VULKAN_KERNEL_PORT_PLAN.md`
- Sibling handoff (Legible Studio roadmap): `F:/Software/LegibleStudios/HANDOFF_2026-05-15_LEGIBLE_STUDIO_RUST_PORT.md`
- Sibling roadmap output (when written): `F:/Software/LegibleStudios/docs/RUST_PORT_ROADMAP.md`
- Source: `F:/Software/ArchEngine_Suite_Kernel/ArchEngine_kernel/` and `F:/Software/ArchEngine_Suite_Kernel/Shared/ArchGeometry/`
- Pivot brief: `F:/Software/LegibleStudios/LEGIBLE_STUDIO_PIVOT_BRIEF.md`
- Semantic OS kernel: `F:/Software/ArmKernel3/`
- Semantic OS app requirements: `C:/Users/jerro/.claude/projects/F--Software-ArmKernel3/memory/project_semantic_os_app_requirements.md`

---

## Appendix A — Per-file inventory

Full file listing with category, LOC, and one-sentence purpose. Ordered by category, then alphabetically.

### A.1 Geometry kernel (28 files, ~12,500 LOC)

| File | LOC | Purpose |
|---|---|---|
| `Shared/ArchGeometry/include/archgeometry/archgeometry.hpp` | 102 | Main include + `ArchGeometry::generateFromJson/File` entry point |
| `Shared/ArchGeometry/include/archgeometry/schema_types.hpp` | 269 | Canonical schema types: Vec3/Vec2, WallType, WallLayer, SchemaWall/Floor/Door/Window/Roof/Room, SchemaDocument, QBDAnswers |
| `Shared/ArchGeometry/include/archgeometry/geometry_types.hpp` | 233 | Output types: Vertex3D, Triangle, Mesh3D, Line2D, Polygon2D, Arc2D, Text2D, Geometry2D, WallGeometry, FloorGeometry, RoofGeometry, DoorGeometry, WindowGeometry, RoomBoundary, BuildingGeometry |
| `Shared/ArchGeometry/include/archgeometry/schema_parser.hpp` + `src/schema_parser.cpp` | 52 + 390 | JSON → SchemaDocument |
| `Shared/ArchGeometry/include/archgeometry/wall_geometry.hpp` + `src/wall_geometry.cpp` | 89 + 243 | Wall mesh + plan + section generator with cutouts |
| `Shared/ArchGeometry/include/archgeometry/floor_geometry.hpp` + `src/floor_geometry.cpp` | 72 + 154 | Floor slab mesh + plan generator |
| `Shared/ArchGeometry/include/archgeometry/roof_geometry.hpp` + `src/roof_geometry.cpp` | 71 + 288 | Roof surface mesh + plan generator (gable/hip/etc.) |
| `Shared/ArchGeometry/include/archgeometry/opening_geometry.hpp` + `src/opening_geometry.cpp` | 143 + 399 | Door/window frame + glass mesh + plan symbol |
| `Shared/ArchGeometry/include/archgeometry/room_geometry.hpp` + `src/room_geometry.cpp` | 75 + 146 | Room boundary polygon + centroid + area |
| `Shared/ArchGeometry/include/archgeometry/query_api.hpp` + `src/query_api.cpp` | 104 + 292 | Spatial queries: walls in room, openings on wall, etc. |
| `Shared/ArchGeometry/src/archgeometry.cpp` | 199 | Top-level `generateFromJson/File/Schema` impl |
| `ArchEngine_kernel/include/csg.hpp` + `src/csg.cpp` | 90 + 274 | BSP-based CSG (Möller-Trumbore + plane splitting + union/intersection/difference) |
| `ArchEngine_kernel/include/bvh.hpp` + `src/bvh.cpp` | 307 + 1,007 | SAH BVH builder (CPU build → flat GPU node array) |
| `ArchEngine_kernel/include/qbd_interface.hpp` + `src/qbd_interface.cpp` | 479 + 1,085 | QBD JSON ingest, building conversion, OBC validation orchestration, documentation pipeline |
| `ArchEngine_kernel/include/obc_engine.hpp` + `src/obc_engine.cpp` | 271 + 601 | Ontario Building Code: joist/stud/header/rafter span tables, thermal R-value by zone, compliance reports |
| `ArchEngine_kernel/include/slicer_2d.hpp` + `src/slicer_2d.cpp` | 329 + 704 | 3D mesh → 2D plane slicing, SVG + DXF export, wall section details — merges with plan_generator into `drawing` (§8 Q1) |
| `ArchEngine_kernel/include/plan_generator.hpp` | 560 | Floor plan annotations: dimensions, grid, north arrow, section markers, roof pitch indicators (header-only) — merges with slicer_2d into `drawing` (§8 Q1) |
| `ArchEngine_kernel/include/wall_system.hpp` | 298 | Parametric wall geometry + corner detection + L-corner adjustment + default wall factories (header-only) |
| `ArchEngine_kernel/include/geometry_loader.hpp` + `src/geometry_loader.cpp` | 57 + 992 | JSON building loader + sample builders + nlohmann ser/de for Building/WallType/ParametricWall/* |
| `ArchEngine_kernel/include/mesh.hpp` (Geometry:: half) + `src/mesh.cpp` (Geometry:: impl, ~700 LOC) | (split from full files) | Procedural generators: beam, column, floor slab, deflected beam, grid, sphere, arrow, door, window, gable roof, gable wall, CSG::wallWithOpening |
| `ArchEngine_kernel/include/types.hpp` (domain half) | ~450 LOC of 722 | StructuralElement, Building, WallType, WallLayer, ParametricWall, WallCorner, MeshData, TerrainMesh, MaterialPreset, color palettes, Frustum, AABB, Plane, all the enums |

### A.2 Vulkan renderer (24 files, ~22,800 LOC + ~2,700 GLSL)

| File | LOC | Purpose |
|---|---|---|
| `include/renderer.hpp` + `src/renderer.cpp` | 1,366 + 5,473 | Orchestrator: forward PBR + shadow + IBL + post + path tracer + UI composite; multi-light (16 max); per-element material overrides |
| `include/vulkan_context.hpp` + `src/vulkan_context.cpp` | 450 + 832 | VkInstance, VkPhysicalDevice, VkDevice, queues, swapchain, command pools |
| `include/pipeline.hpp` + `src/pipeline.cpp` | 83 + 395 | VkPipeline + VkRenderPass wrapper, shader module loading from SPIR-V |
| `include/descriptor_manager.hpp` + `src/descriptor_manager.cpp` | 121 + 273 | VkDescriptorPool/Layout/Set lifecycle |
| `include/instance_batch.hpp` + `src/instance_batch.cpp` | 77 + 141 | Per-instance vertex buffer for instanced draws |
| `include/shadow_map.hpp` + `src/shadow_map.cpp` | 94 + 566 | Depth-only render pass, shadow map array (up to 4 lights), PCF in shader |
| `include/environment_map.hpp` + `src/environment_map.cpp` | 121 + 1,205 | Equirect HDR → cubemap, IBL precompute (irradiance + prefiltered env + BRDF LUT) |
| `include/post_process.hpp` + `src/post_process.cpp` | 247 + 1,878 | SSAO, bloom (bright + multi-tap blur), SSR, tonemap (Reinhard/ACES/Uncharted2), composite |
| `include/texture.hpp` + `src/texture.cpp` | 131 + 575 | Image upload via stb_image, mip generation, VkImageView/VkSampler |
| `include/path_tracer.hpp` + `src/path_tracer.cpp` | 340 + 1,290 | Compute path tracer + KHR-RT variant; uses BVH from geometry side |
| `include/imgui_layer.hpp` + `src/imgui_layer.cpp` | 447 + 2,940 | Dear ImGui Vulkan backend + entire app UI (materials, scene, lights, render settings) |
| `include/mesh.hpp` (Mesh class) + `src/mesh.cpp` (VkBuffer half) | ~12 + ~280 | RAII VkBuffer + VkDeviceMemory for vertex/index buffers |
| `include/window.hpp` + `src/window.cpp` | 73 + 110 | GLFW window wrapper, input event polling |
| `src/main.cpp` | 2,014 | Application entry, scene setup, camera control, input handling |
| `include/arch_api.h` + `src/arch_api.cpp` | 1,009 + 1,627 | C ABI for DLL embedding (`arch_init`, `arch_load_file`, `arch_render_frame`, `arch_set_element_material`, 70+ exports) |

### A.3 Shaders (28 files, ~2,700 LOC of GLSL source)

| File | LOC | Stage | Purpose |
|---|---|---|---|
| `shaders/structural.vert` | 61 | vertex | Per-element transform + UBO bind |
| `shaders/structural.frag` | 602 | fragment | PBR material eval + IBL + shadow sampling + per-element overrides + viz modes |
| `shaders/structural.tesc` | 90 | tess control | Tessellation factor based on view distance |
| `shaders/structural.tese` | 173 | tess eval | Displacement mapping along tess output |
| `shaders/sky.vert` + `.frag` | 31 + 90 | vert+frag | Procedural sky with sun/atmosphere |
| `shaders/shadow.vert` | 27 | vertex | Depth-only output for shadow map |
| `shaders/shadow_tess.vert` | 34 | vertex | Same as shadow.vert but for tessellated geometry |
| `shaders/shadow.tesc` + `.tese` | 35 + 42 | tess | Tessellated shadow pass |
| `shaders/ssao.vert` + `.frag` | 15 + 87 | vert+frag | Screen-space AO |
| `shaders/ssao_blur.frag` | 44 | fragment | SSAO bilateral blur |
| `shaders/ssr.vert` + `.frag` | 15 + 159 | vert+frag | Screen-space reflections |
| `shaders/bloom_bright.frag` | 33 | fragment | Bloom luminance threshold pass |
| `shaders/bloom_blur.frag` | 24 | fragment | Bloom separable Gaussian blur |
| `shaders/composite.frag` | 142 | fragment | HDR + bloom + tonemap → display |
| `shaders/brdf_lut.comp` | 106 | compute | One-shot BRDF integration LUT |
| `shaders/irradiance_convolve.comp` | 93 | compute | One-shot diffuse irradiance convolution |
| `shaders/prefilter_envmap.comp` | 113 | compute | One-shot prefiltered specular envmap |
| `shaders/path_trace.comp` | 653 | compute | Software BVH traversal + path tracing (the heavyweight) |
| `shaders/denoise.comp` | 116 | compute | Path tracer output denoiser (À-trous or similar) |
| `shaders/raygen.rgen` | 75 | rt raygen | KHR_ray_tracing entry — variant path tracer |
| `shaders/closesthit.rchit` | 348 | rt closesthit | KHR-RT material shading on hit |
| `shaders/miss.rmiss` | 48 | rt miss | KHR-RT environment lookup on miss |
| `shaders/shadow_miss.rmiss` | 7 | rt miss | KHR-RT shadow ray miss |
| `shaders/include/ubo.glsl` | 72 | shared | std140 UBO layout shared by multiple shaders |

### A.4 Shared infra (4 files, ~1,100 LOC)

| File | LOC | Purpose |
|---|---|---|
| `include/memory.hpp` + `src/memory.cpp` | 226 + 160 | Custom VkDeviceMemory allocator (renderer-side) |
| `include/lights.hpp` | 148 | `Light` struct (Directional/Point/Spot) |
| `include/types.hpp` (GPU layouts half) | ~270 of 722 | Vertex, InstanceData, GPULight, PushConstants, UniformBufferObject, MaterialOverrideBits, EffectFlags |

### A.5 Build / glue

| File | Purpose |
|---|---|
| `ArchEngine_kernel/CMakeLists.txt` (385 LOC) | Top-level build: FetchContent for GLFW/GLM/json/ImGui/cpp-httplib, shader compilation rules, CPack ZIP packaging |
| `Shared/ArchGeometry/CMakeLists.txt` | ArchGeometry static lib config |
| `addons/physics_sim/CMakeLists.txt` (190 LOC) | physics_sim static lib + examples |
| `launch_archengine.bat`, `update_phase5.ps1`, `update_imgui_panel.ps1` | Launcher + migration scripts (drop) |

### A.6 Third-party vendored

| File | License | Replacement |
|---|---|---|
| `external/stb_image.h`, `external/stb_image_write.h` | Public domain | `image` crate |
| (FetchContent: GLFW 3.3.8) | zlib | `winit` |
| (FetchContent: GLM 1.0.1) | MIT | `glam` |
| (FetchContent: nlohmann/json 3.11.3) | MIT | `serde` + `serde_json` |
| (FetchContent: Dear ImGui v1.90.1) | MIT | `egui` + `egui-wgpu` |
| (FetchContent: cpp-httplib v0.15.3) | MIT | `reqwest` / `axum` (per use case) |

### A.7 Auxiliary

| Module | LOC | Disposition |
|---|---|---|
| `addons/physics_sim/` (13 headers + 12 cpp + 3 examples) | ~7,300 | **Defer.** Hygrothermal/moisture/decay/material physics — not permit-drawing path. |
| `include/llm_assistant.hpp` + `src/llm_assistant.cpp` | 90 + 261 | **Drop.** Cut per pivot. |
| `include/memory_test.hpp` + `src/memory_test.cpp` | 37 + 171 | **Drop.** Diagnostic only. |
| `include/ipc_server.hpp` + `src/ipc_server.cpp` | 81 + 293 | **Replace with `axum` HTTP API** in geometry crate (§8 Q6). New `legible_studio_geometry::api` module, ~3-5 days, ~200 LOC. |
| `include/project.hpp` + `src/project.cpp` | 139 + 429 | **Port alongside geometry_loader** (~3-5 days). Split into TWO files (§8 Q7): `project.json` (geometry — owned by geometry crate) + `project.render.json` (camera, overrides, render settings — owned by renderer crate). Ship a `project-migrate` binary to split existing one-file projects. |
| `include/physics_bridge.hpp` + `src/physics_bridge.cpp` | 73 + 433 | **Defer with physics_sim.** |
| `src/physics_bridge_fixed.cpp` | 434 | **Drop.** Duplicate; not in CMake source list. |
