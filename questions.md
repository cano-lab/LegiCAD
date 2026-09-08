# What You Need to Know Right Now

**For the next agent working on Legible Engine.**

These are the open questions that block progress. Answer them, or document what you learned.

---

## 1. Solid Modeling Kernel: Build vs. Integrate?

**The question:** Does ArchEngine build a geometry kernel from scratch, integrate an existing one (OCCT, CGAL), or hybrid?

**Context:**
- Current Legible Studio has 2D geometry (lines, arcs, polygons) in Rust
- Need 3D solid modeling for massing (CSG, B-rep, meshes)
- Need it to be fast enough for real-time manipulation
- Need IFC export (already works via `ls-qbd`)

**Options:**
- **Build** — Pure Rust B-rep/CSG kernel. Maximum control, maximum effort.
- **OCCT (OpenCASCADE)** — Industry standard, heavy dependency, C++ wrapper needed.
- **CGAL** — Robust geometry algorithms, C++ header-only, Rust bindgen possible.
- **Hybrid** — Use `parry3d`/`rapier` for collision, custom B-rep for surfaces, OCCT only for STEP/IGES import.

**What to find out:**
- [ ] What 3D geometry crates exist in the Rust ecosystem today? (check crates.io: `parry3d`, `rapier3d`, `truck`, `cgm`, `fenris`)
- [ ] Can `truck` (Rust B-rep) handle the complexity of architectural massing?
- [ ] What's the state of OCCT Rust bindings? (`occt-rs`, `opencascade-sys`)
- [ ] Performance comparison: native Rust vs. C++ wrapper for simple CSG operations

**Blocking:** Yes. This decision affects every subsequent geometry decision.

---

## 2. Sudbury Zoning Bylaws: Do We Have Them?

**The question:** Where are the Sudbury zoning documents, and what's the fastest path to encoded rules?

**Context:**
- Need Sudbury municipality bylaws + Sudbury Easy Planning boards
- These are text documents (PDFs, bylaws) that need to become machine-readable rules
- The user (Jer) may already have access or know where to get them

**What to find out:**
- [ ] Does Jer have copies of the Sudbury zoning bylaws already?
- [ ] If not, are they online? (City of Greater Sudbury website)
- [ ] What's the scope: just zoning, or also site plan control, minor variances, heritage?
- [ ] Are the Easy Planning bylaws the same as city bylaws, or separate?

**Blocking:** No, but it's the first concrete step after the architecture decision.

---

## 3. Constraint Solver: Which Library?

**The question:** What Rust-accessible constraint solver do we use for the regime engine?

**Context:**
- Need CSP (Constraint Satisfaction Problem) + MILP (Mixed Integer Linear Programming)
- Use case: zoning constraints + OBC rules → feasible design envelope
- GraphBU paper (July 2026) showed structural fidelity matters for learned MILP solvers
- The constraint problem is NOT huge (dozens of variables, not thousands)

**Options:**
- **OR-Tools** (Google) — Best-in-class, but C++ with Rust bindings uncertain
- **CBC (Coin-OR)** — Open source, proven, C++ with `good_lp` Rust crate
- **MiniZinc** — High-level modeling, compiles to various solvers
- **Custom** — Build a simple CSP solver in Rust (feasible for small problem sizes)

**What to find out:**
- [ ] Does `good_lp` (Rust LP/MILP interface) support CBC? Is it maintained?
- [ ] What's the compile-time and runtime cost of adding CBC as a dependency?
- [ ] For Part 9 housing, how many constraints are we actually talking about? (estimate: 50-200)
- [ ] Would a custom CSP solver be simpler than integrating a heavy library?

**Blocking:** Yes. The regime engine needs this.

---

## 4. Vulkan Viewer: Resurrect or Rebuild?

**The question:** What's the state of the Vulkan viewer code, and is it worth resurrecting?

**Context:**
- ArchEngine had a Vulkan viewer in earlier iterations
- It's in `/root/.openclaw/workspace/legible-studio/history/ArchEngine_kernel/` or similar
- Current Legible Studio uses tiny-skia (software rendering) for 2D
- Need real-time 3D viewer for massing exploration

**What to find out:**
- [ ] Where exactly is the Vulkan viewer code? (check history dirs)
- [ ] What state is it in? (compiles? runs? renders anything?)
- [ ] What dependencies does it have? (ash, wgpu, vulkano, raw Vulkan?)
- [ ] Is it faster to fix the old code or start fresh with `wgpu` (cross-platform, safer)?

**Blocking:** No. 2D mode can work first. But 3D viewer is needed for massing.

---

## 5. Rhino/Grasshopper Prototype: What's the Learning?

**The question:** Jer wants to prototype regimes in Rhino/Grasshopper first. What should that prototype prove?

**Context:**
- Jer has access to Rhino + Grasshopper
- The goal is to learn UX friction and validate the regime concept
- This is NOT the final implementation — it's a learning tool

**What to define:**
- [ ] What's the simplest regime to encode? (e.g., "single-family detached, Sudbury R1 zone")
- [ ] What parameters should be exposed? (setbacks, height, coverage, unit count)
- [ ] What's the output? (3D mass, floor area, compliance check list)
- [ ] How do we capture learnings? (screen recordings, notes on friction points)

**Blocking:** No. This is parallel to the Rust work.

---

## 6. OBC Rules: Reactive → Proactive

**The question:** How do we transform `ls-obc` from a checker into a constraint generator?

**Context:**
- `ls-obc` currently validates a design AFTER it's created
- Example: "Check if this wall meets span table requirements"
- We need: "Given this program, what's the maximum allowable span?"
- The rules are the same, but the direction is reversed

**What to find out:**
- [ ] Which OBC Part 9 rules are already encoded in `ls-obc`?
- [ ] What's the pattern for inverting a check into a constraint?
- [ ] Can we express OBC rules as a constraint library that works both ways?

**Blocking:** Partially. Can build forward without this, but it's core to the vision.

---

## 7. Question-Based UX: What's the Right Granularity?

**The question:** How many questions, and how deep, before the user sees a result?

**Context:**
- Current `qbd_solve` asks ~10 questions and produces a full house
- For generative design, the user needs to explore options, not just get one answer
- Too many questions = fatigue. Too few = generic results.

**What to find out:**
- [ ] What's the minimum viable question set for a Sudbury multiplex?
- [ ] Should the UX be: questions → massing options → refine → details?
- [ ] Or: site → envelope → sculpt → questions fill in the gaps?
- [ ] What's the cognitive load limit? (5 questions? 10? 20?)

**Blocking:** No. UX can evolve. But it affects the first prototype.

---

## 8. LiDAR / Site Capture: Integrate Now or Later?

**The question:** Does the new platform include site capture from day one, or is that a v2 feature?

**Context:**
- `ls-site` already does LiDAR footprint, as-built walls, elevations
- This is a differentiator — most design tools start with a blank canvas
- But it's complex (GeoTIFF, point clouds, OSM integration)

**What to decide:**
- [ ] Is site capture part of the first demo?
- [ ] Or do we start with manual site boundary input?
- [ ] What's the simplest integration: boundary polygon → zoning lookup → constraints?

**Blocking:** No. Can start with manual input.

---

## 9. Student Involvement: What Can They Build?

**The question:** Jer wants students working on this. What are safe, meaningful contributions?

**Context:**
- Jer is a professor with students who can code
- Need tasks that are well-scoped, educational, and actually useful
- Not just busywork — real parts of the system

**What to define:**
- [ ] What skill level are the students? (Rust? Python? JS?)
- [ ] What components are student-friendly? (UI, data entry, testing, documentation)
- [ ] What components are NOT student-friendly? (geometry kernel, constraint solver)
- [ ] Can students encode bylaws into structured data? (good learning exercise)

**Blocking:** No. But it affects project planning.

---

## 10. First Demo: What Does "Working" Look Like?

**The question:** What's the smallest proof-of-concept that demonstrates the full loop?

**Context:**
- The full loop is: site → questions → constraints → mass → SVG
- We need a demo that convinces Jer (and eventually others) that this works
- It doesn't need to be pretty. It needs to be end-to-end.

**What to define:**
- [ ] Input: manual site boundary (rectangle) + "I want a duplex"
- [ ] Constraints: simplified Sudbury rules (setbacks, height, coverage)
- [ ] Output: 3D massing options + 2D site plan + compliance summary
- [ ] Platform: Rust command-line tool (no UI needed for v0)

**Blocking:** No. But it focuses the work.

---

## Summary: Priority Order

| Priority | Question | Action |
|----------|----------|--------|
| 1 | Solid modeling kernel | Research Rust geometry crates, decide build vs. integrate |
| 2 | Constraint solver | Evaluate `good_lp` + CBC, test with simple regime |
| 3 | First demo scope | Define the minimal end-to-loop proof |
| 4 | Sudbury bylaws | Get documents, extract first rules |
| 5 | Vulkan viewer | Assess old code, decide resurrect vs. wgpu |
| 6 | OBC proactive | Design constraint library pattern |
| 7 | Rhino prototype | Define scope, start Grasshopper regime |
| 8 | UX granularity | Sketch question flow |
| 9 | Site capture | Defer to v2 |
| 10 | Student tasks | Define after kernel decisions |

---

*Ask Jer these questions. Document the answers here. Then build.*

---

# Documented Answers (2026-09-08)

Answers below come from two passes: (a) verifying claims in this repo and the legacy Legible Studio tree, and (b) researching the current Rust ecosystem. Items marked **[Jer]** still need Jer's input — everything else is decided or recommended.

## A1. Solid Modeling Kernel → **Hybrid, but not the hybrid we guessed**

**Decision: use the ported ArchEngine kernel + `parry3d` for queries; treat true B-rep as out of scope for the massing phase.**

What the research actually showed (crates.io, checked 2026-09-08):

- **`truck`** (pure-Rust B-rep/NURBS kernel): last release 0.6.0, **September 2024** — quiet for a year. Architectural massing doesn't need NURBS; using truck would buy complexity we don't need. **Rejected.**
- **`parry3d`**: actively maintained (0.30.x, updated August 2026, ~2.4M downloads). It's a collision/geometry-query library, not a solid modeler — which is exactly what massing needs (ray casts, intersection tests, convex hulls). **Adopt for spatial queries.**
- **OCCT bindings (`opencascade-rs`)**: still a part-time hobby project, "major work in progress," needs cmake + a C++ toolchain and drags in a huge dependency for booleans we already have. The broader ecosystem confirms the pattern — serious projects that need OCCT wrap it via a Python sidecar (CadQuery/build123d) or WASM (occt-wasm), not Rust bindings. **Rejected for now.** STEP/IGES import is not a v1 need; IFC export already works without OCCT (see A6).
- **CGAL**: no practical Rust path; header-heavy C++ template library. **Rejected.**

**The reframe:** the question assumed we'd need B-rep for massing. We don't. Massing envelopes, setbacks, coverage, and storey stacking are all convex-box / polygon operations. The ported `archengine/geometry` crate (146 tests passing) already has mesh generation, SAH BVH, AABBs, and CSG-with-openings. Add `parry3d` when we need precise polygon boolean or proximity queries. Revisit OCCT only if we ever need STEP import from mechanical CAD — and then as a sidecar, not an in-process binding.

## A2. Sudbury Zoning Bylaws → **Found, online, current**

The full text of **Zoning By-law 2010-100Z** is published on the City of Greater Sudbury website, maintained with amendments through 2026 (e.g. 2024-22Z, 2026-45Z, 2026-98Z all folded in). The city also replaced its PDF zone maps with an **interactive zoning map searchable by street address** — that plus the text version is enough to build the regime without asking anyone for documents.

- Text: https://www.greatersudbury.ca/do-business/zoning/zoning-by-law-2010-100z/
- Hub + interactive map: https://www.greatersudbury.ca/do-business/zoning/
- Caveat stated by the city: where the website text differs from the official printed publication, **the printed publication takes precedence** — encode with citations to section numbers so fixes are cheap.

Scope already encoded in `regime/zoning`: R1 setbacks (front 6.0 m, interior side 1.2 m, exterior side 6.0 m, rear 7.5 m — matches Table 6.2-family values seen in city planning reports), height, coverage, parking. Site Plan Control By-law 2010-220 also found; defer encoding it.

**[Jer]** Two things only Jer can answer: (1) does "Sudbury Easy Planning" refer to a separate document set or the city's online planning portal — if separate, we need those docs; (2) confirm the first target zone is R1 (vs R2-2 for the duplex demo).

## A3. Constraint Solver → **`good_lp` + HiGHS (with CBC available)**

The recommendation in the file (good_lp + CBC) is sound but the ecosystem has shifted slightly: **HiGHS is now the better default backend**, CBC the fallback.

- **`good_lp`**: actively maintained — v1.15.3, updated **August 2026**, ~4M downloads. Supports integer variables (MILP), multiple solver backends through a single API.
- **`highs`** crate: v2.4.0, updated July 2026, ~1.1M downloads. HiGHS is the strongest open-source LP/MILP solver and builds from vendored C++ source (no system install).
- **`coin_cbc`**: v0.1.9, updated August 2026 — still maintained and available if HiGHS ever gives trouble.

Problem size: a Part 9 multiplex regime is 50–200 linear constraints — trivial for HiGHS (millisecond solves). A custom CSP solver is **not** worth it: the regime wants weights and objectives ("maximize floor area subject to envelope"), which is LP-shaped, not CSP-shaped.

**Action:** add `good_lp = { version = "1", features = ["highs"] }` to the workspace and prototype `regime/solver` on the existing `RectEnvelope` example (maximize footprint area subject to setbacks/coverage/height).

## A4. Vulkan Viewer → **SUPERSEDED by Jer's directive: full Vulkan renderer → Rust, with Lumion-class path tracing**

**Jer (2026-09-08): "I want the Vulkan viewer, game and path tracing like Lumion. It has to become Rust — I'll need it for demos."**

Located and measured: `legacy/archengine/ArchEngine_kernel/` — **~41,000 lines of C++** (renderer.cpp alone is 6,601) plus ~3,100 lines of GLSL, written against **raw Vulkan** (no `ash`, no wrapper). It includes a path tracer, post-process chain, ImGui layer, and environment mapping — a full game-engine renderer, not a viewer.

Key discovery that makes the port tractable: **the path tracer is compute-shader based** (`path_trace.comp`, progressive Monte Carlo, GGX PBR, next-event estimation, Russian roulette, ACES tonemap) and traverses the exact GPU BVH layout already ported to `archengine/geometry::bvh` (32-byte nodes, 48-byte triangles, bit-packed materials). **No `VK_KHR_ray_tracing_pipeline` dependency** — it runs on any Vulkan GPU, and the Rust BVH feeds it directly. The GLSL ports verbatim via shaderc.

**Decision: port the renderer to Rust with `ash` 0.38 (raw Vulkan bindings — near-1:1 mapping from the C++), winit for windowing, shaderc for GLSL→SPIR-V at build time.** wgpu was rejected: no mature ray/path-tracing story, and fidelity to the existing shaders matters more than cross-platform abstraction for demos.

Port order (demos-first):
1. `vulkan_context` (986 LOC) — instance/device/queues/swapchain ✅ ported (`vulkan/context.rs`)
2. ~~`memory` (185 LOC)~~ — intentionally not ported; Rust ownership replaces CPU-side tracking. Vulkan buffer/image helpers live on `VulkanContext`.
3. Raster pipeline (`structural.vert/frag`) + mesh upload from `archengine_geometry` — real-time "game" navigation (WASD + mouse)
4. **Path tracer** (`path_tracer.cpp` 1,531 LOC + `path_trace.comp`) — progressive accumulation, the Lumion money shot ✅ ported (`vulkan/path_tracer.rs` + headless `archrender` CLI)
5. Post chain (bloom/SSAO/SSR/denoise) + environment-map IBL (`environment_map.cpp`) — polish
6. Deferred: slicer_2d, physics_bridge — not needed for demos

**Re-add checklist (Jer 2026-09-08 — do not lose these):**
- [ ] **Environment-map IBL** — `environment_map.cpp` (1,454 LOC) + `brdf_lut.comp` / `irradiance_convolve.comp` / `prefilter_envmap.comp` / `sky.vert/frag`. Path tracer currently writes `envMapInfo.x = 0` (shader fallback path); the raster UBO has `iblParams` waiting.
- [ ] **Polyhaven texture array** — `PathTracer::loadMaterialTextures` + `material_map.json`, bound at descriptor 6. Materials currently render with flat albedo/roughness from the material table.
- [ ] **OIDN denoise** — replace the ported 3×3 edge-aware CPU filter behind a cargo feature (`oidn` crate links Intel Open Image Denoise; aarch64-macOS binaries exist upstream).
- [ ] **ImGui overlay** — `imgui_layer.cpp` (3,314 LOC) → `imgui-rs` (or egui, decision when we get there).

**Target machine: M1 Mac → MoltenVK (Vulkan-on-Metal).** Ported consequences:
- Device features are now **gated on support** (C++ requested `wideLines`, `fillModeNonSolid`, `sampleRateShading`, `shaderClipDistance`, `tessellationShader` unconditionally — `wideLines` does not exist on Metal and would fail device creation). Unavailable features degrade gracefully with a logged warning; check `supports_*()` before use.
- Tessellation shaders (`structural.tesc/tese`, `shadow.*`) are supported by MoltenVK on Apple silicon but keep them behind `supports_tessellation()` anyway.
- Descriptor indexing (UPDATE_AFTER_BIND, used by post-processing) works on M1 via Metal 3 argument buffers — if a bring-up failure ever points there, that's the knob to gate.
- Setup on the Mac: `brew install --cask vulkan-sdk` (or `molten-vk`); `shaderc` builds from source via cmake (already handled by build.rs); run `archrender` headless first — it needs no window server.

## A5. Rhino/Grasshopper Prototype → **Scope defined below; [Jer] to confirm**

Simplest regime that proves the concept: **Sudbury R1, single-detached or duplex, rectangular lot.**

- **Encode:** setbacks (front/interior side/exterior side/rear), max height, lot coverage, parking count — the same five rules already in `regime/zoning`.
- **Expose as Grasshopper sliders:** lot width/depth, unit count, storeys, target floor area.
- **Output:** (a) the legal envelope as a 3D solid, (b) a generated mass inside it, (c) a live compliance readout (green/red per rule).
- **Capture learnings:** which parameters users touch first, where the "why is this red?" moments are, whether envelope-first (sculpt inside the legal space) reads better than mass-first. Screen recordings + a friction log.

The point to prove: **users understand the envelope-first loop faster than question-first.** That determines Q7's answer.

## A6. OBC Reactive → Proactive → **Pattern identified; build `rule` as bidirectional**

Current inventory in `regime/obc` (verified against source):
- **Part 9:** stairs (9.8), egress (9.9), fire separation / spatial separation (9.10), windows, smoke/CO detectors, electrical, headers, roof snow loads (9.25-region tables)
- **Part 3:** occupancy classification, occupant load, egress, stairs, elevators, fire separation, suite separation — backed by the OBC_Library tables at the workspace root
- IFC4 export exists in the legacy qbd crate ("Revit-importable subset") — so export does **not** depend on the kernel decision.

Every encoded check has the shape `check(design, rule) -> violations`. The inversion pattern for v1 is mechanical:

| Reactive (have) | Proactive (build) |
|---|---|
| `span_ok(joist, spacing, span) -> bool` | `max_span(joist, spacing) -> Length` |
| `window_area_ok(room, windows) -> bool` | `min_window_area(room) -> Area` |
| `egress_width_ok(occupants, width) -> bool` | `min_egress_width(occupants) -> Length` |

Most Part 9 rules are table lookups whose inverse is "read the table the other way" — monotone in one variable. **Design: each rule exposes both `check()` and `bound()`; the regime engine consumes `bound()`, the report consumes `check()`.** Start with stairs and spatial separation (most constrained, highest demo value).

## A7. Question-Based UX Granularity → **Envelope-first, ≤5 questions to first image**

Current `qbd_solve` takes ~13 flags (bedrooms, bathrooms, sqft, garage, storeys, windows, style, zone, street, roof, stair-config, lot, mode). That's the old question-first philosophy. Per the vision ("site → questions → constraints → masses → sculpt"), the new flow inverts the order:

1. **Site in** (draw or import boundary) — 0 questions
2. **Zone lookup** — 0 questions (from address; manual override)
3. **≤5 questions:** unit count, target floor area, storeys (or "you choose"), parking, and one style lever
4. **Envelope + 3 massing options appear** — everything else is sculpting, not questions

Defer the full 13-question QBD set to *after* the user has picked a mass. The Grasshopper prototype (A5) is where we validate that 5 is the right number.

## A8. LiDAR / Site Capture → **v2, confirmed**

`ls-site` in the legacy tree does LiDAR footprints, as-built walls, and elevation (GeoTIFF/point-cloud/OSM) — it exists and is real, but porting it is not needed to prove the loop. v0 takes a **manual boundary polygon** (or address → parcel outline later). The seam is already designed: `regime/params::Site { boundary, jurisdiction, zone, street }` doesn't care whether the boundary was hand-drawn or LiDAR-derived.

## A9. Student Tasks → **Scoped list (skill-independent entry points)**

Safe, useful, and well-bounded:

1. **Bylaw encoding (best task):** turn By-law 2010-100Z tables into structured JSON/Rust data with section citations — zone-by-zone setbacks, coverage, parking. Teaches precision; zero geometry math. The R1 table in `regime/zoning` is the template.
2. **OBC table digitization:** extend OBC_Library CSV/JSON tables (span tables, spatial separation) with test fixtures.
3. **Golden-file tests:** render known designs through `qbd_solve`, snapshot outputs as regression fixtures.
4. **Rhino/Grasshopper regime (A5):** a student with Grasshopper skills can own this outright.
5. **Compliance report UX:** the report module output → human-readable summaries.

**Not student-safe (core team only):** geometry kernel, BVH/CSG internals, solver integration, viewer.

## A10. First Demo → **Defined, and already half-built**

**Spec:** CLI tool. Input: rectangular lot (e.g. 15 m × 30 m), "duplex" (2 units), Sudbury R1 rules from `regime/zoning`. Output: buildable envelope, 3 massing options, an SVG site plan, and a compliance summary citing bylaw sections.

**What already exists toward this (as of commit `9698785`):** the full Rust workspace — `archengine/geometry` (kernel: mesh, BVH, wall system, CSG openings), `archengine/solver` + `qbd_solve` (working end-to-end: answers → building JSON), `regime/obc` (Part 3 + Part 9 rules), `regime/zoning` (Sudbury table + `rect_envelope`), `regime/params` (Site/ProgramBrief). **314 tests passing.**

**Remaining for the demo:** (a) `regime/solver` crate per A3 to fuse zoning + OBC bounds into an envelope, (b) massing generator (stack boxes in the envelope), (c) SVG site-plan output (pattern exists in legacy ls-drawing), (d) a `legicad-demo` binary tying it together. Est. 2–3 focused weeks, no new dependencies beyond good_lp/HiGHS and an SVG writer.

---

## Revised priority order

| Priority | Question | Status |
|----------|----------|--------|
| 1 | Kernel | **Answered:** ported kernel + parry3d; no OCCT |
| 2 | Solver | **Answered:** good_lp + HiGHS — prototype next |
| 3 | Demo | **Answered:** spec in A10; ~half the crates exist |
| 4 | Bylaws | **Answered:** online; **[Jer]** confirm R1-first + Easy Planning |
| 5 | Viewer | **Answered:** wgpu rebuild; not blocking |
| 6 | OBC proactive | **Answered:** `check()`/`bound()` pattern; start with stairs |
| 7 | Rhino | Scoped; **[Jer]** confirm + assign |
| 8 | UX | **Answered:** envelope-first, ≤5 questions; validate via A5 |
| 9 | Site capture | **Answered:** v2 |
| 10 | Students | **Answered:** list in A9; bylaw encoding first |
