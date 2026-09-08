# Handoff: ArchEngine Vulkan kernel → Rust port plan

**Date:** 2026-05-15
**Audience:** A fresh agent or human starting Rust-port work on the C++ codebase at `ArchEngine_kernel/`.
**Context not assumed:** all relevant facts are below or in the referenced files.

---

## Mission

Produce a **Rust-port architecture document** for `ArchEngine_kernel/`. Write it to:

    F:\Software\LegibleStudios\docs\VULKAN_KERNEL_PORT_PLAN.md

The codebase contains **two distinct halves** that need separate treatment:

1. **Geometry kernel** (CPU math: boolean ops, constraint solving, mesh generation, parametric primitives) → **plan the Rust port in full detail.** This is on the critical path for native Rust Legible Studio.
2. **Vulkan renderer** (GPU pipeline, shaders, swapchain, draw calls) → **inventory + Rust port sketch.** 3D rendering is now planned for the Semantic OS kernel in Phase 9 or later (added 2026-05-15) for CAD verification view + video playback + retro games. The realistic kernel-side rendering target is the iGPU (Intel Iris Xe), not NVIDIA. So a forward-looking port plan targets `wgpu` for portability or `ash` for hand-rolled Vulkan, but the kernel-side Vulkan-equivalent doesn't exist yet.

---

## Background

Read `HANDOFF_2026-05-15_LEGIBLE_STUDIO_RUST_PORT.md` (sibling handoff in this repo) for the broader product context: three-project family, pivot, Path B (full native convergence — no Linux compat). Critical context summary: there is **no Linux ABI compatibility layer**. The kernel rejected this on security grounds. So the port is the path; running the existing C++ via any kind of translation layer is not an option.

Key facts specific to *this* port:

- The author wrote the Vulkan engine themselves and has the deepest context on the C++. The document is for their planning, not for an outsider to execute.
- The **geometry kernel half** is on the **critical path for the pivoted Legible Studio product** (permit drawings). The constraint solver and geometric primitives are what produce the deliverable.
- The **Vulkan renderer half** is needed for the CAD verification view (per pivot: "verification view, not centerpiece") and — separately — is valuable as a reference for the eventual Semantic-OS-side rendering stack.
- **GPU plan on Semantic OS** (per kernel memory `project_semantic_os_kernel.md`, updated 2026-05-15):
  - **iGPU (Iris Xe):** drives the display via UEFI GOP framebuffer for boot; Phase 9+ kernel work adds a real rendering driver for the iGPU specifically. This is where 3D rendering lives on the kernel.
  - **NVIDIA dGPU:** compute-only for local LLM inference (Tinygrad-NV-style path, post-EOY-2026). Not used for graphics.
  - **No NVIDIA Vulkan driver planned.** A Mesa-equivalent for NVIDIA is out of reach for a hobby kernel. iGPU Vulkan-equivalent in Phase 9+ is the only realistic in-kernel 3D path.

---

## Read order before scoping

1. `ArchEngine_kernel/README.md` (if present) — what this engine is and what it expects.
2. `ArchEngine_kernel/CMakeLists.txt` — build shape, third-party deps.
3. `ArchEngine_kernel/LICENSE.txt` — confirm license posture before referencing any code in the Rust port.
4. `ArchEngine_kernel/CAD_API_REFERENCE.txt` — the public surface area.
5. Walk `src/`, `include/`, `shaders/` at tree-level.
6. Sample representative files in `src/` (5-10 .cpp/.hpp) to gauge per-module surface area.
7. Note what's in `external/`, `OBC_Library/`, `enhancer/`, `qbd/` — these may be third-party vendored or auxiliary modules; identify which.

You do not need to read every file. Sample representatively.

---

## What to produce

`docs/VULKAN_KERNEL_PORT_PLAN.md` with these sections:

### 1. Tree map + split

Walk `ArchEngine_kernel/` and classify every file into one of:

- **GEOMETRY KERNEL** (CPU math: boolean ops, constraint solving, mesh generation, parametric primitives, BREP/NURBS if present, geometric algorithms)
- **VULKAN RENDERER** (GPU-side: pipeline setup, draw calls, descriptor sets, swapchain, shader loading, command buffers)
- **SHADERS** (`.glsl`, `.hlsl`, `.spv` — call out language and target stage)
- **SHARED INFRA** (math types, vector/matrix libs, logging, file I/O — used by both)
- **BUILD / GLUE** (CMakeLists, scripts, headers without real code)
- **THIRD-PARTY VENDORED** (anything in `external/` or `OBC_Library/`)
- **AUXILIARY** (e.g., `enhancer/`, `qbd/` — describe what each is)

Provide a file-count summary per category.

### 2. Geometry kernel — full Rust port plan (PRIMARY DELIVERABLE)

For each file or logical module:

- One-sentence purpose
- LOC
- C++ dependencies (Eigen, GLM, CGAL, Boost, custom math headers — name each)
- Rust crate equivalents:
  - **Linear algebra:** `nalgebra` (rich, has SIMD), `glam` (game-dev, smaller), `cgmath` (legacy, less active)
  - **Geometric algorithms:** `parry2d` / `parry3d` (collision), `geo` (GIS-style 2D), `lyon` (path tessellation), `rstar` (R-tree)
  - **BREP/NURBS:** sparse Rust ecosystem; flag as a gap (likely "port the C++ directly" or "accept v1 feature loss")
  - **Constraint solving:** `good_lp` (LP/MIP), `russcip` (MIP), `z3` (SMT bindings), `lpsolve` bindings — depends on what current C++ uses
  - **Mesh processing:** `meshopt`, `mesh-tools` — flag what's missing
  - For each, note no_std-friendliness (relevant because the kernel target requires it eventually, though desktop Rust port can use `std`)
- Port complexity: **small (days)** / **medium (weeks)** / **large (months)**
- What it depends on (other modules in this tree)
- What depends on it

Produce a dependency graph (textual is fine — "A depends on [B, C]"). Then derive a **topological port order**: which module first, what natural milestones.

### 3. Vulkan renderer — inventory + sketch

Per file or module:

- One-sentence purpose
- LOC
- Render technique (forward / deferred / PBR / depth-only / hybrid)
- Inputs expected from the geometry kernel (vertex buffer format, materials, scene graph?)
- Shader languages used (GLSL? HLSL? source-or-compiled SPIR-V?) and their locations
- **Light sketch** of what a Rust port would target:
  - **`wgpu`** — portable Rust GPU library, runs on Vulkan/Metal/DX12/WebGPU. Use as a desktop target; future port to Semantic OS happens when the kernel exposes a wgpu-compatible backend.
  - **`ash`** — thin Vulkan bindings. Lower-level, more code, more control. Use if the engine has highly tuned Vulkan paths that don't survive wgpu's abstractions.

  Pick one (or recommend a hybrid) per significant module and justify briefly.

**Explicitly note** in this section: the Semantic OS kernel does **not** yet have a Vulkan implementation. The kernel's 3D rendering plan (Phase 9+) targets the iGPU (Iris Xe). When that exists, this Rust port becomes runnable on the kernel; until then, the port runs on desktop only.

### 4. Shared infra

What sits in shared headers / utility files used by both halves? List with Rust equivalents. Common cases:

- Custom vec2/vec3/vec4/mat4 types → replace with `nalgebra` or `glam` consistently
- Custom AABB / OBB / Frustum → exist in `parry2d`/`parry3d`
- Logging → `log` + `env_logger` (desktop) or a custom no_std logger (kernel)
- File I/O → `std::fs` (desktop); `core::io`-equivalent + Semantic OS syscall wrappers (kernel)
- Custom string types → just use `&str` / `String`; flag where the C++ uses non-UTF-8

### 5. Port order — geometry kernel

Concrete sequence:

- **Foundation:** small, foundational modules (vec/mat types, basic geometric predicates)
- **Mid:** the heart of the geometry kernel (constraint solving, parametric primitives, boolean ops)
- **Late:** modules with heavy dependencies on everything else

With milestones, framed as regression tests:

- "Rust output matches C++ output to N decimal places on the test corpus for module X"
- "Constraint solver Rust port produces equivalent floor plans for the standard inputs"
- "Geometry kernel passes full regression suite against C++ outputs"
- "Swap-in in Legible Studio desktop pipeline complete (C++ engine removed from build)"

### 6. LOC + effort estimate

Per module and total, for the geometry kernel half. Honest calendar weeks at hobby pace. Note that the author does the work themselves — they have the deepest context on the C++ already, so estimates can lean optimistic for routine translation but should add buffer for any module that uses non-trivial C++ patterns (see §7).

### 7. Pitfalls

Specific C++ idioms in this codebase that don't translate cleanly:

- **Template metaprogramming** — Rust's generics + traits are different; some patterns need redesign
- **Deep inheritance** — Rust prefers composition; virtual hierarchies often map to enums or trait objects
- **Operator overloads** with non-obvious semantics — Rust's `std::ops` traits have stricter contracts (e.g., no allocation in `+`)
- **Manual memory management** — `unique_ptr` / `shared_ptr` patterns map roughly to `Box` / `Rc`/`Arc`, but ownership patterns may need rethinking
- **Friend classes** — no direct equivalent; usually means restructuring or accepting `pub(crate)`
- **Multiple inheritance** — not possible in Rust; trait objects + composition

For each pitfall you find in the actual code, point at a specific file/symbol and describe the redesign approach.

### 8. Open questions

Anything that needs the architect's judgement. Likely candidates:

- License of vendored third-party libraries — does the Rust port need to swap them out?
- Are there hand-tuned SIMD intrinsics that need to be re-validated post-port?
- Is the existing test corpus sufficient as a regression oracle, or does it need extension?
- Does the rendered output need to be bit-identical, visually equivalent, or just "looks right"?

---

## What NOT to do

- **Don't plan the Legible Studio Python orchestration.** That's `HANDOFF_2026-05-15_LEGIBLE_STUDIO_RUST_PORT.md` (sibling handoff). Cross-reference, don't duplicate.
- **Don't plan a Semantic-OS-side GPU driver.** That's a kernel-side scope; this document plans the **app-side** port only. Note the kernel target where relevant, but don't design the driver here.
- **Don't generate Rust code.** Planning document.
- **Don't over-invest in the Vulkan renderer port plan.** It's secondary — sketch, don't blueprint. The geometry kernel is the primary deliverable.
- **Don't propose a Linux ABI compatibility layer** as a way to keep the C++ running. Rejected on security grounds — see sibling handoff.

---

## Operating notes

- The author wrote the Vulkan engine; the document supplements their context, doesn't replace it.
- Cite specific file paths. Numbers > "lots."
- If the engine architecture diverges meaningfully from typical CAD-engine patterns, call that out — those divergences are usually where the C++ → Rust port gets sticky.

---

## Cross-references

- This handoff: `F:\Software\LegibleStudios\HANDOFF_2026-05-15_VULKAN_KERNEL_PORT.md`
- Legible Studio handoff (parallel): `F:\Software\LegibleStudios\HANDOFF_2026-05-15_LEGIBLE_STUDIO_RUST_PORT.md`
- Semantic OS kernel: `F:\Software\ArmKernel3\`
- Semantic OS kernel memory: `C:\Users\jerro\.claude\projects\F--Software-ArmKernel3\memory\project_semantic_os_kernel.md`
- Semantic OS app requirements: `C:\Users\jerro\.claude\projects\F--Software-ArmKernel3\memory\project_semantic_os_app_requirements.md`
- Pivot brief: `F:\Software\LegibleStudios\LEGIBLE_STUDIO_PIVOT_BRIEF.md`
- Vulkan engine source: `F:\Software\LegibleStudios\ArchEngine_kernel\src\`, `include\`, `shaders\`
