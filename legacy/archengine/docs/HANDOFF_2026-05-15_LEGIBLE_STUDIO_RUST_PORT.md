# Handoff: Legible Studio → Rust port roadmap

**Date:** 2026-05-15
**Audience:** A fresh agent or human starting Rust-port work on Legible Studio so it eventually runs as a native Rust app on the Semantic OS kernel.
**Context not assumed:** all relevant facts are below or in the referenced files. Read this top to bottom before touching anything.

---

## Mission

Produce a **Rust-port roadmap document** for Legible Studio. Write it to:

    F:\Software\LegibleStudios\docs\RUST_PORT_ROADMAP.md

Goal of the roadmap: give the architect/owner a single document they can use to start scoping the work of porting Legible Studio away from Python orchestration + C++ Vulkan engine + PyQt6 GUI, toward a pure Rust binary that eventually targets the **Semantic OS kernel** (`F:\Software\ArmKernel3`).

---

## Background — the three-project family

Legible Studio is the design-app member of a three-project family. The other two:

- **Semantic OS kernel** at `F:\Software\ArmKernel3` — bare-metal x86_64 Rust kernel that will host this app natively. See its `MEMORY.md` (in `C:\Users\jerro\.claude\projects\F--Software-ArmKernel3\memory\`) for OS-side context, especially `project_semantic_os_app_requirements.md` which describes the kernel-side contract.
- **MarlOS** at `F:\CanoLab\MarlOS` — Tauri-based productivity environment (typesetter, citation manager, semantic search, AI conversation analyzer). Also slated to port to the kernel.

The owner has committed to **Path B (full native convergence)**: all apps eventually run as native Rust binaries against the Semantic OS syscall ABI. **No Linux ABI compatibility layer** — considered and rejected on security grounds. Bringing Linux syscall translation into the kernel would reintroduce the entire Linux attack surface, which directly contradicts the kernel's thesis (tier-aware LLM mediation at ring 0). Apps must be ported natively to get any kind of execution on the kernel. There is no "just run the existing Python via WSL" escape hatch.

Legible Studio therefore has to become a pure Rust app to land on the kernel at all. This handoff exists to scope that work.

---

## The pivot — READ THESE FIRST

Two documents in this repo, in order:

1. `LEGIBLE_STUDIO_PIVOT_BRIEF.md` — canonical statement of what the product *is now*.
2. `LEGIBLE_STUDIO_PIVOT_REVIEW.md` — accompanying review.

The pivot in one sentence: **inputs (location, constraints, budget) → permit-ready 2D drawings in 5 minutes**, via constraint satisfaction, not CAD drawing. Many features from the previous three-mode product are cut: AI rendering, Stable Diffusion, Revit plugin, LegiWrite markdown editor. The Vulkan 3D engine in `ArchEngine_kernel/` is demoted to "verification view, not centerpiece."

The pivot brief states explicitly: *"If a feature, module, or subsystem in the codebase doesn't serve this, it is a candidate for cutting regardless of how well it works."* Be brutal about cuts when you do the inventory.

---

## Read order before scoping

Once you've internalised the pivot:

1. `README.md` (root) — current quickstart, gives the shape of the orchestration.
2. `permit_drawing_set.py` (root) — main pipeline entrypoint. This is what the product *is* today.
3. `archengine_gui.py` (root) — the PyQt6 GUI. Likely cut or heavily replaced; needs explicit decision.
4. `smoke_test.py` (root) — what's actually exercised by tests; tells you what's load-bearing.
5. `headless/` — directory; the headless API server. Probably the cleanest core that survives.
6. `ArchEngine_CAD/` — sample 5-10 representative Python files to gauge surface area.
7. `ArchEngine_kernel/` — tree-level only. Detailed audit is the separate handoff `HANDOFF_2026-05-15_VULKAN_KERNEL_PORT.md` — don't duplicate that work.

You do not need to read every file. Sample representatively.

---

## What to produce

`docs/RUST_PORT_ROADMAP.md` with these sections:

### 1. Survives/cuts inventory

Walk every top-level directory and significant file. Classify each into:

- **SURVIVES — needs Rust port** (currently Python or C++ that will become Rust)
- **SURVIVES — already Rust, lightly tweak**
- **SURVIVES — stays in desktop version only** (e.g., things that need infrastructure Semantic OS won't have for a while)
- **CUT** — per pivot brief
- **UNCLASSIFIED** — needs the architect's judgement (note why)

For each entry, cite the source path and the rationale. Especially for SURVIVES: what evidence in the pivot brief or code justifies keeping it?

Where the pivot brief and the code disagree (i.e. code exists for a feature the brief cut), flag it explicitly. The brief is the source of truth; the code is the legacy.

### 2. Minimum-viable native Rust Legible Studio on Semantic OS

What's the smallest module set that delivers the pivoted product (constraint solver → 2D permit drawings)? List in dependency order. Reference `project_semantic_os_app_requirements.md` in the Semantic OS kernel memory — the kernel will provide persistent FS, keyboard/pointer input, framebuffer, font rasterization, 2D vector rasterizer, network/TLS. Legible Studio needs to do constraint solving, geometry, SVG generation, optionally PDF export, optionally a simple UI.

### 3. Per-surviving-module port detail

For each SURVIVES (Rust port needed) module:

- Language today (Python / C++)
- LOC (rough count via `Get-ChildItem -Recurse | Measure-Object -Property Length` or `wc -l`)
- One-sentence purpose
- Dependencies it pulls in (Python packages, C++ libraries) — name each
- Rust crate equivalents (with no_std-friendliness flagged where it matters; first-party-app code doesn't strictly need no_std today, but the kernel target does eventually require dropping `std::thread`, `std::sync` Mutex variants, etc.)
- Port complexity: **small (days)** / **medium (weeks)** / **large (months)**
- Position in port order

### 4. Port order

Linearised sequence with milestones. Suggested milestone framings:

- "Constraint solver passes regression test against current Python output on the smoke-test corpus"
- "First SVG drawing produced from Rust matches Python's drawing diff-clean"
- "Permit set generated end-to-end in pure Rust"
- "Running as native Rust binary on a desktop test rig (Windows or Linux)"
- "Running on Semantic OS"

### 5. Dependencies without clean Rust replacements

Be specific. Examples to look for:

- **Solver libraries** — OR-Tools, z3, custom solver? Rust ecosystem has `good_lp`, `russcip`, `z3` bindings, plus several SMT/SAT solvers, but feature gaps exist.
- **CAD geometry libraries** — Open CASCADE? CGAL? These don't have Rust equivalents at parity.
- **Drawing / rendering** — Cairo, librsvg, custom SVG generator? Rust has `tiny-skia`, `resvg`, `usvg`, `lyon`.
- **PDF generation** — ReportLab? Rust has `printpdf`, `pdf-writer`.
- **Geometric primitives** — Shapely, Sympy? Rust has `geo`, `parry2d`/`parry3d`.

For each gap, name it explicitly and recommend either: (a) port the C++/Python directly, (b) wrap an existing Rust crate that's close-enough, (c) accept a feature loss in v1, or (d) ask the architect for a redesign call.

### 6. Suggested first port target

Pick **one** module that's small, self-contained, useful as a first deliverable, and exercises enough of the Rust ecosystem to validate the approach. Justify the pick.

### 7. Open questions for the architect

Anything that needs human judgement before further work proceeds. Examples likely to come up:

- Does the PyQt6 GUI survive in any form, or is the post-port product headless-only initially?
- Which solver does the current pipeline use, and is that Rust-replaceable?
- What's the test corpus for the constraint solver, and can it serve as a regression oracle for the Rust port?
- Should the Rust port be drop-in compatible with the existing JSON inputs at `headless/`?

---

## What NOT to do

- **Don't plan the Vulkan engine port.** That's `HANDOFF_2026-05-15_VULKAN_KERNEL_PORT.md` (separate document, parallel handoff). You may cross-reference it but don't duplicate its content.
- **Don't generate Rust code.** This is a planning document.
- **Don't pad with generic Rust-ecosystem material.** Cite specific crate names, link to crates.io where useful, give version numbers if a specific MSRV matters.
- **Don't second-guess the pivot.** If a feature is cut, it's cut. If you think it shouldn't be, surface that in §7 (Open questions), don't override the brief.
- **Don't propose a Linux ABI compatibility layer** as a way to avoid the port. The kernel rejected this explicitly on security grounds (see Background above). The port is the path.

---

## Operating notes

- The owner does this kind of porting work themselves. The roadmap is for *their* planning, not for an agent or contractor to execute. Optimize for "an architect can read this and start scoping work" over "a worker can pick this up and start coding."
- Be brutal about cuts. The pivot brief is unsparing — if a feature isn't on the critical path to permit drawings, default to CUT.
- Numbers > "lots." LOC, file counts, dep counts. Concrete > generic.
- File paths are Windows-style here because the codebase lives on `F:\`. Use forward-slash paths in the document itself for portability.

---

## Cross-references

- This handoff: `F:\Software\LegibleStudios\HANDOFF_2026-05-15_LEGIBLE_STUDIO_RUST_PORT.md`
- Vulkan kernel handoff (parallel): `F:\Software\LegibleStudios\HANDOFF_2026-05-15_VULKAN_KERNEL_PORT.md`
- Semantic OS kernel: `F:\Software\ArmKernel3\`
- Semantic OS app requirements memory: `C:\Users\jerro\.claude\projects\F--Software-ArmKernel3\memory\project_semantic_os_app_requirements.md`
- Pivot brief: `F:\Software\LegibleStudios\LEGIBLE_STUDIO_PIVOT_BRIEF.md`
- Pivot review: `F:\Software\LegibleStudios\LEGIBLE_STUDIO_PIVOT_REVIEW.md`
- Previous handoff (for historical context, not active): `F:\Software\LegibleStudios\HANDOFF_2025-12-24.md`
