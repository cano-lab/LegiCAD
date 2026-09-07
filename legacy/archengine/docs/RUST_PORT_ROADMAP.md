# Legible Studio — Rust port roadmap

**Date:** 2026-05-15
**Audience:** Architect/owner scoping the port of Legible Studio to a pure Rust binary, ultimately targeting the [Semantic OS kernel](../../ArmKernel3/) (`F:/Software/ArmKernel3`).
**Status:** Planning. No code written. No execution committed.
**Inputs to this doc:** `LEGIBLE_STUDIO_PIVOT_BRIEF.md` (product source-of-truth), `LEGIBLE_STUDIO_PIVOT_REVIEW.md` (current architecture state), Semantic OS memory `project_semantic_os_app_requirements.md`, and a survives/cuts sample pass of this repo.
**Parallel doc:** `HANDOFF_2026-05-15_VULKAN_KERNEL_PORT.md` covers the C++ Vulkan engine port. That work is excluded from this document and not duplicated.

---

## TL;DR

The pivoted product — **inputs → permit-ready 2D drawings via constraint satisfaction** — is unexpectedly small once the AI render pipeline, PyQt shell, Vulkan engine, and database persistence are set aside. The minimum-viable Rust core is approximately:

| Module | Source LOC today | Language | Difficulty |
|---|---|---|---|
| Constraint solver + spatial graph | ~8,200 (qbd) / ~3,000 (CAD dup) | Python (stdlib only) | medium |
| QBD layout generator | ~1,200 (in qbd LOC above) | Python | small |
| OBC compliance engine | 872 + 5 JSON tables | C++ | medium |
| OBC validators (egress, light, costs) | 776 | Python | small |
| Drawing generators (9 SVG sheets) | ~5,000 | Python | medium |
| Schema parser | 5,071 (ArchGeometry C++) | C++ | medium |
| **Core Rust port total (estimate)** | **~24,000 LOC equivalent** | **mixed** | |

This excludes the 35K-LOC Vulkan kernel (separate handoff), the 17K-LOC AI render pipeline (CUT for Rust target), and the 16K-LOC PyQt shell (CUT for Rust target).

The Python core is dependency-light — `stdlib` only (no numpy, scipy, OR-Tools, z3, shapely). That is the single largest portability win. Maps to Rust crates `geo`, `roxmltree`/`quick-xml`, `serde_json` (desktop) or hand-rolled JSON parser (kernel), `tiny-skia` (preview/raster), `pdf-writer` (export). All MIT or Apache-2.0.

The Semantic OS app-requirements memory already names the right crates for the kernel target; this roadmap aligns with them.

---

## 1. Survives/cuts inventory

Classification key:
- **SURVIVES — Rust port needed** (Python or C++ today; ports cleanly)
- **SURVIVES — desktop-only** (depends on infrastructure the kernel won't have for years; keep in the Python product alongside the Rust core, or run the Rust binary on a desktop OS instead)
- **CUT** (per pivot brief — does not serve the constraint-solver → permit-drawing pipeline)
- **UNCLASSIFIED** (needs the architect's call)

### Repo root

| Path | LOC | Classification | Rationale |
|---|---|---|---|
| `permit_drawing_set.py` | 306 | SURVIVES — Rust port | Top-level orchestrator of the 9-sheet pipeline. *This is what the product is.* |
| `archengine_gui.py` | 385 | CUT | Old PyQt GUI; superseded by `ArchEngine_CAD/app/application.py`. Already a tabs-and-spinbox toy demo with placeholder Vulkan launch — explicit cut. |
| `smoke_test.py` | 354 | SURVIVES — Rust port (as regression harness) | Doubles as the *only* end-to-end test of the product. Port semantics to Rust as the cross-language regression oracle. |
| `schema_diff.py` | (small) | UNCLASSIFIED | Schema diffing utility; depends whether it's still used in CI. |
| `tests/` | 458 | SURVIVES — Rust port | Port what survives the cut. |
| `README.md` | — | rewrite after port lands | — |
| `RESEARCH_PAPER.md`, `FORMAL_SPECIFICATION.md`, `IMPLEMENTATION_MAPPING.md`, `HANDOFF_*.md`, `LEGIBLE_STUDIO_PIVOT_*.md` | — | docs only | No port action. |
| `Shared/Schemas/*.json` (78 JSON files) | data | SURVIVES — data, no port | JSON schema is the contract; both sides of port consume it. |
| `Shared/ArchGeometry/` (5,071 C++ LOC) | 5,071 | SURVIVES — Rust port | Schema parser + geometry computation. Single source of truth for schema interpretation. Highest-leverage C++ to port. |
| `Shared/Docs/`, `Shared/Specs/`, `Shared/TestData/` | data | SURVIVES — data | — |
| `_archive/` | (archive) | ignore | Already pruned per `LEGIBLE_STUDIO_PIVOT_REVIEW.md`. |

### `headless/` (1,527 LOC)

| File | LOC | Classification | Rationale |
|---|---|---|---|
| `api_server.py` | 736 | SURVIVES — desktop-only | FastAPI server. Kernel doesn't host HTTP servers; Rust port may expose the same shape via a `headless` binary on desktop. Many endpoints are stale TODOs (PDF export 501, constraint API placeholder). |
| `mcp_server.py` | 609 | SURVIVES — desktop-only (optional) | MCP for Claude Desktop. Replaces RevitMCP entirely per pivot review. Useful but not on the 5-min permit-drawing critical path. |
| `elevation_extractor.py` | ~180 | SURVIVES — Rust port | Drawing-adjacent helper. |
| `requirements.txt` | — | reduce | FastAPI/Uvicorn/pydantic/MCP stay only for desktop headless binary. |

### `ArchEngine_CAD/` — Python application layer

#### Pipeline core (SURVIVES — Rust port)
| Path | LOC | Notes |
|---|---|---|
| `solver_suite.py`, `complete_solver_suite.py`, `advanced_solvers.py`, `normalized_solver.py`, `room_relationships.py`, `core/constraints.py` | 2,994 | CAD-side solver duplicate of `ArchEngine_kernel/qbd/`. Per `LEGIBLE_STUDIO_PIVOT_REVIEW.md` "Pending decisions: Solver duplicates" — **the qbd/ copy is canonical (headless API uses it via sys.path order). Don't port the CAD copy.** Resolve the duplicate as the *first* step of the port — porting both is pure waste. |
| `legible_studios/` (validators) | 776 | `code_studio.py` (OBC compliance), `cost_studio.py` (cost estimator), `core/constraint_lens.py` (base). Pure Python, stdlib only. Currently orphaned — needs wiring in Python *and* Rust. |
| `core/document.py`, `core/events.py`, `core/commands.py`, `core/constraints.py`, `core/version_control.py`, `core/selection.py`, `core/diagnostics.py`, `core/terrain.py` | 5,884 | UNCLASSIFIED — partly load-bearing (`document.py`, `version_control.py`), partly editor-shell scaffolding tied to PyQt (`commands.py`, `events.py`, `selection_manager.py`). Triage during port. Keep only what the headless pipeline actually constructs. |
| `database/` (SQLAlchemy models + repository) | 2,129 | SURVIVES — Rust port (replace SQLAlchemy with `sqlx` 0.8 + SQLite on desktop; on Semantic OS, use the kernel's encrypted KV store). The schema is canonical; the persistence layer is the swap. Smoke test already exercises round-trip. |
| `sheets/` (`models.py`, `sheet_registry.py`, `dimension_item.py`, `svg_parser.py`, `lod_manager.py`) | 1,338 | SURVIVES — Rust port. Sheet data model. |
| `generators/` (`generator_adapters.py`, `generator_service.py`) | 649 | SURVIVES — Rust port. In-memory adapter glue. |

#### Editor shell (CUT for Rust target; survives in Python desktop product)
| Path | LOC | Classification | Notes |
|---|---|---|---|
| `app/application.py` + `config.py` + `sheet_tab_widget.py` | 2,730 | CUT (Rust target) | `application.py` alone is 2,400+ lines wired to PyQt panels the pivot review already flagged for cut. Per the review's "Lean PyQt shell rewrite" item, a fresh shell is planned even for the Python product. Do not port. |
| `panels/` (chat_panel, sheet_manager, smart_panels, viewport_panel, properties_panel, solver_params_panel, panel_registry, gravity_triangle, lod_indicator, version_history, onboarding_overlay, sheet_properties, sheet_tab_widget) | 6,629 | **CUT** | All flagged in pivot review as "Cut (pending lean-shell rewrite)." Three-mode ghost architecture. |
| `panels/materials_panel.py` | (part of 6,629) | SURVIVES — desktop-only | Only material panel survives. Tied to Vulkan viewport; desktop product only. |
| `dialogs/qbd_questionnaire.py`, `dialogs/site_dialog_simple.py` | (part of 3,957) | SURVIVES — desktop-only | Question elicitation. Kernel needs a native immediate-mode UI replacement. |
| `dialogs/path_tracer_dialog.py`, `solver_comparison_dialog.py`, `site_dialog.py` (older variant) | (part of 3,957) | CUT | Flagged in pivot review. |
| `widgets/embedded_map_widget.py` + `osm_map.html`, `widgets/site_editor_widget.py` | 754 | SURVIVES — desktop-only | LiDAR-driven site capture. Uses an embedded HTML map; kernel will not have an OSM webview. Replace with on-kernel site dialog post-v1. |
| `viewport/vulkan_widget.py` + `archengine_viewport.dll` | 2,341 | CUT (Rust target) | Qt-Vulkan glue. Obsolete once Rust is the host; the C++ kernel becomes a separate process or static lib called via FFI. |
| `views/plan_view.py` (in `views/`) | — | CUT | Listed in pivot review as cut. |
| `solver_cli.py`, `solver_integration.py`, `solver_menu.py` | small | SURVIVES — Rust port (CLI face) | Minimal CLI wrappers; port as Rust `clap` subcommands. |
| `client/`, `sync/`, `tools/` | unsampled | UNCLASSIFIED | Subdirs not sampled. Likely most-or-all PyQt-coupled. Default to CUT if confirmed shell-coupled. |
| `test_cad_basic.py`, `test_onboarding_logic.py`, `test_reality_load.py`, `run_debug.py`, `visual_comparison.py` | small | UNCLASSIFIED | Spot-check during port. Most likely CUT. |
| `shaders/`, `resources/`, `docs/`, `pipeline_cache.bin`, `__pycache__/` | data | ignore | — |
| `_archive/` | data | ignore | Already archived. |

### `ArchEngine_kernel/` — C++ Vulkan + Python pipeline

#### Vulkan engine — out of scope for THIS doc
| Path | LOC | Notes |
|---|---|---|
| `include/` + `src/` (53 files, Vulkan/renderer/path_tracer/etc.) | 35,601 | See `HANDOFF_2026-05-15_VULKAN_KERNEL_PORT.md`. Semantic OS app-requirements memory marks 3D as Phase 9+ ("post-EOY, explicitly deferred"). |
| `external/`, `shaders/`, `materials/`, `hdri/`, `installer/`, `OBC_Library/` (data) | data | ignore here |

#### Inside `src/`/`include/` — pieces that DO matter for 2D pipeline
| Path | LOC | Classification | Notes |
|---|---|---|---|
| `include/obc_engine.hpp` + `src/obc_engine.cpp` | 872 | SURVIVES — Rust port | OBC Section 9.23 compliance with real tables (joists, rafters, studs, headers). Load-bearing for permit certainty. |
| `OBC_Library/tables/*.json` (5 files) | data | SURVIVES — data | Code tables. |
| `include/qbd_interface.hpp` + `src/qbd_interface.cpp` | 2,108 | SURVIVES partial — Rust port if decoupled from Vulkan | QBD JSON ingestor on the C++ side. Today it bridges to mesh generation; in a Rust world it merges with `ArchGeometry` schema parser. |
| `include/slicer_2d.hpp` + `src/slicer_2d.cpp` | (~part of 35K) | UNCLASSIFIED | Could feed floor-plan generator with C++-computed cross-sections, but the current Python pipeline doesn't use it. Default CUT unless wired post-port. |
| `include/types.hpp` | 832 | SURVIVES — Rust port (rewritten as types crate) | Shared geometry/math/JSON types. |
| `include/arch_api.h` + `src/arch_api.cpp` | 4,344 | CUT for 2D pipeline | C ABI for embedding Vulkan in PyQt. Obsolete post-port. |

#### `qbd/` — Python live pipeline (SURVIVES — Rust port)
| File | LOC (total dir: 8,192) | Notes |
|---|---|---|
| `qbd_layout_generator.py` | ~1,200 | Entry: QBD answers → SpatialGraph → PlacedLayout → QBD JSON. **The mouth of the pipeline.** First port target candidate. |
| `room_relationships.py` | ~1,500 | SpatialGraph + Zone/Opening enums. Pure data. |
| `wall_graph.py` | ~600 | Wall topology data model. |
| `coordinate_solver.py` | ~1,300 | Coordinate placement. Pure Python. |
| `layout_refiner.py` | ~800 | Post-solve refiner (open plan, doors, windows, design fragments). |
| `solver_suite.py`, `complete_solver_suite.py`, `advanced_solvers.py`, `subdivision_solver.py` | ~2,800 | Multi-algorithm solvers (BSP/CSP/WFC/genetic/annealing/etc.). **Most recent commits (`391c5a7`, `857e3ed`) report a 4700× perf win on the subdivision solver — the BSP top-down approach is the winner; older solvers may be candidates for cut after the port lands and benchmarks confirm.** |

#### `scripts/` — Python drawing generators
| File | LOC (total dir: ~4,705 for keepers) | Classification | Notes |
|---|---|---|---|
| `generate_plans.py`, `generate_elevations.py`, `generate_sections.py`, `generate_schedules.py`, `generate_site_plan.py`, `intelligent_dimensions.py`, `title_block.py`, `pdf_export.py`, `generator_base.py` | 4,705 | SURVIVES — Rust port | The 9-sheet permit set. SVG output by hand-rolled string construction; PDF via `reportlab`/`svglib`. |
| `generate_drawings.py`, `generate_all.py`, `generate_details.py` | small | UNCLASSIFIED | Overlap with above; consolidate during port. |
| `plan_editor_2d.py` | (~part of 4,505) | CUT | PyQt editor for 2D plans — out of scope for headless pipeline. |
| `roof_generator.py`, `truss_calculator.py`, `wall_types.py` | (~part of 4,505) | SURVIVES — Rust port | Geometry helpers. |
| `schema_validator.py` | (~part of 4,505) | SURVIVES — Rust port | JSON-schema validation. |
| `text_to_json.py`, `text_to_json_gui.py` | (~part of 4,505) | CUT | LLM-to-JSON converter; old QBD-front flow now handled by MCP / questionnaire. |
| `ifc_import.py` | (~part of 4,505) | UNCLASSIFIED | IFC import is not in the pivot brief's deliverable list. Default CUT. |
| `material_generate.py`, `material_preview.py`, `validate_materials.py` | (~part of 4,505) | CUT | Material library tooling — desktop-only Vulkan adjunct. |
| `monitor_memory.py`, `memory_leak_test.py`, `render_upscale.py`, `physics_bridge.py`, `logging_config.py` | small | utility | Keep `logging_config` semantics in Rust (`tracing`). Rest: CUT or move to debug-only. |
| `test_pipeline.py` | small | SURVIVES — Rust port (as regression test) | — |
| `*.bat` scripts | data | dev infra | — |
| `legiqbd/`, `llm/`, `qbd/`, `sheets/` subdirs | unsampled | UNCLASSIFIED | Default CUT unless smoke test transitively imports them. |

#### `enhancer/` — AI render pipeline (26 files, 17,257 LOC)
| Classification | Notes |
|---|---|
| **CUT from the Rust port.** | 17K LOC of torch/diffusers/transformers/opencv/xformers/numba/CUDA. Not portable to Rust in any reasonable timeline and not on the 5-min permit-drawing critical path. |
| **Caveat:** `LEGIBLE_STUDIO_PIVOT_REVIEW.md` and `memory/project_visualization_role.md` say AI render is client-facing product surface (hero shots), so it can't simply be deleted from the Python product. Resolution: **desktop product retains it as an out-of-process Python service**; Rust binary calls it over a socket only when running on a desktop OS with that service available. **On Semantic OS, no AI render — period (no GPU until kernel Phase 9+, no PyTorch stack).** |
| Files: `enhancer_server.py`, `upscaler.py`, `vision_processor.py`, `ai_segmentation.py`, `channel_extractor*.py`, `multi_model_processor.py`, `height_generator.py`, `ifc_renderer.py`, `photo_to_family_processor.py`, `render_ui*.py`, `postprocess*.py`, `image_channels.py`, `gpu_memory.py`, `ai_enhancer.py`, `debug_shadow.py`, `fix_color_profile.py`, `render*.py` | — |
| `enhancer/requirements.txt` | ~125 packages incl. torch 2.6+cu124, diffusers 0.36, gradio 6.1, ifcopenshell 0.8, pyrender, realesrgan, xformers, warp-lang. **Snapshot this exactly. Do not try to reproduce in Rust.** |

### Dependency summary (Python `requirements.txt` files)

| Source | Heaviest deps | Port plan |
|---|---|---|
| `headless/requirements.txt` | `fastapi`, `uvicorn`, `pydantic`, `mcp`, `reportlab`, `svglib`, `lxml`, `numpy` | `axum` 0.8 + `tokio` for HTTP; `serde` for schemas; `printpdf` 0.7 or `pdf-writer` 0.10 for PDF; drop numpy (Rust has nalgebra/glam if needed but solver doesn't use it) |
| `ArchEngine_kernel/scripts/requirements.txt` | unsampled | inspect during port |
| `ArchEngine_kernel/enhancer/requirements.txt` | full ML stack | CUT — not ported |

---

## 2. Minimum-viable native Rust Legible Studio on Semantic OS

Per `project_semantic_os_app_requirements.md` (Layer 2, "Creativity / Design"), the kernel will provide: persistent FS + paths, keyboard/pointer events, framebuffer drawing API, TTF rasterization (userspace `fontdue` crate), 2D vector rasterizer (userspace `tiny-skia` port). No GPU until Phase 9+.

Minimum module set, in dependency order:

1. **Types crate** — geometry primitives, units, schema types. Ports `ArchEngine_kernel/include/types.hpp` (832 LOC) + the Python implicit-dict shapes from `qbd/room_relationships.py` and `core/constraints.py`. Pure no_std-compatible Rust. **~1,500 LOC estimated.**
2. **Schema crate** — reads/writes the building JSON contract (`Shared/Schemas/*.json`). On desktop: `serde_json` 1.0. On kernel: hand-rolled ~300 LOC JSON parser (Semantic OS memory recommends avoiding `serde` for alloc-heaviness). Ports `Shared/ArchGeometry` (5,071 C++ LOC). **~3,500 LOC Rust.**
3. **OBC engine** — ports `obc_engine.cpp` (872 LOC) + 5 JSON tables. Pure CPU lookup + validation. **~1,200 LOC Rust.**
4. **Spatial graph + constraint solver** — ports `qbd/` (`room_relationships`, `wall_graph`, `coordinate_solver`, `solver_suite`, `subdivision_solver`, `layout_refiner`). Pure stdlib Python today → pure-std Rust. **~6,000–7,000 LOC Rust.** Subdivision solver is the recent perf winner per commits `391c5a7`/`857e3ed`; lead with that, prune the others.
5. **QBD layout generator** — ports `qbd_layout_generator.py` (~1,200 LOC). Glues answer dict → spatial graph → placed layout. **~800 LOC Rust.**
6. **Validators** — ports `legible_studios/studios/code_studio.py` + `cost_studio.py` (776 LOC). Wires post-solve into the pipeline. **~900 LOC Rust.** Pivot review explicitly calls out the wiring as a "to-build" item — port and wire in one motion.
7. **Drawing generators** — ports `ArchEngine_kernel/scripts/generate_*.py` (~5,000 LOC). Floor plan, elevations, sections, schedules, site plan, intelligent dimensions, title block. Emit SVG as string output. **~6,000 LOC Rust.** No external library for SVG generation needed for v1 (strings are fine).
8. **Permit drawing orchestrator** — ports `permit_drawing_set.py` (306 LOC). Wires generators 1–7. **~400 LOC Rust.**
9. **Persistence (kernel target)** — uses Semantic OS encrypted KV store. ~300 LOC Rust glue.
10. **Persistence (desktop target)** — `sqlx` 0.8 + SQLite. Ports `ArchEngine_CAD/database/` (2,129 LOC). **~1,800 LOC Rust.**
11. **PDF export (optional v1)** — `pdf-writer` 0.10 or `printpdf` 0.7. **~500 LOC Rust glue.**

**Total core Rust port: ~22,000–25,000 LOC** to deliver the pivoted product end-to-end, headless, on a desktop test rig OR on Semantic OS once Layer 1 lands.

UI is deliberately deferred. On desktop, the v1 Rust binary runs headless (CLI + optional `axum` HTTP). On kernel, UI waits for `tiny-skia` + `fontdue` ports of the framebuffer/font stack, and a minimal immediate-mode UI crate (`egui` is the obvious candidate but is `std`-coupled; `egui` on kernel is a deferred research item).

---

## 3. Per-surviving-module port detail

| # | Module | Source path | Today | LOC today | Deps today | Rust crate(s) | no_std-friendly? | Complexity | Port order |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Types | `ArchEngine_kernel/include/types.hpp` + Python implicit | C++ + Python dicts | 832 + scattered | GLM 1.0.1, nlohmann/json 3.11.3 | `glam` 0.30 (alt: `nalgebra` 0.34), in-tree struct defs | yes (`glam` has `default-features=false`) | small | 1 |
| 2 | Schema parser | `Shared/ArchGeometry/` | C++ | 5,071 (incl. tests) | nlohmann/json, GLM | `serde` 1.0 + `serde_json` 1.0 on desktop; hand-rolled JSON parser (~300 LOC) on kernel | partial (`serde` is alloc-heavy — see OS memory) | medium | 2 |
| 3 | OBC engine | `ArchEngine_kernel/src/obc_engine.cpp` + `OBC_Library/tables/*.json` | C++ | 872 + data | nlohmann/json | in-tree types + `serde` for table loading | yes if hand-rolled JSON | small (logic) + medium (tables) | 3 |
| 4 | SpatialGraph + ROOM_TYPES | `ArchEngine_kernel/qbd/room_relationships.py` (qbd-canonical per pending decision) | Python | ~1,500 | stdlib only | in-tree | yes | small | 4 |
| 5 | Wall graph | `ArchEngine_kernel/qbd/wall_graph.py` | Python | ~600 | stdlib only | in-tree | yes | small | 4 |
| 6 | Coordinate solver | `ArchEngine_kernel/qbd/coordinate_solver.py` | Python | ~1,300 | stdlib only | in-tree | yes | medium | 4 |
| 7 | Solver suite | `ArchEngine_kernel/qbd/solver_suite.py` + `complete_solver_suite.py` + `advanced_solvers.py` + `subdivision_solver.py` | Python | ~2,800 | stdlib only | in-tree | yes | medium-large (multi-algorithm; consider pruning to just BSP/subdivision after benchmarks) | 5 |
| 8 | Layout refiner | `ArchEngine_kernel/qbd/layout_refiner.py` | Python | ~800 | stdlib | in-tree | yes | small | 5 |
| 9 | QBD layout generator | `ArchEngine_kernel/qbd/qbd_layout_generator.py` | Python | ~1,200 | stdlib | in-tree | yes | small | 6 |
| 10 | OBC validators (code) | `ArchEngine_CAD/legible_studios/studios/code_studio.py` | Python | ~400 | stdlib | in-tree | yes | small | 7 |
| 11 | OBC validators (cost) | `ArchEngine_CAD/legible_studios/studios/cost_studio.py` | Python | ~350 | stdlib | in-tree | yes | small | 7 |
| 12 | Constraint lens base | `ArchEngine_CAD/legible_studios/core/constraint_lens.py` | Python | ~150 | stdlib | in-tree (trait) | yes | small | 7 |
| 13 | Floor plan generator | `ArchEngine_kernel/scripts/generate_plans.py` | Python | ~1,200 | stdlib | in-tree + SVG-string output | yes | medium | 8 |
| 14 | Intelligent dimensions | `ArchEngine_kernel/scripts/intelligent_dimensions.py` | Python | ~700 | stdlib | in-tree | yes | small | 8 |
| 15 | Elevation generator | `ArchEngine_kernel/scripts/generate_elevations.py` | Python | ~600 | stdlib | in-tree | yes | small | 8 |
| 16 | Section generator | `ArchEngine_kernel/scripts/generate_sections.py` | Python | ~500 | stdlib | in-tree | yes | small | 8 |
| 17 | Schedule generator | `ArchEngine_kernel/scripts/generate_schedules.py` | Python | ~400 | stdlib | in-tree | yes | small | 8 |
| 18 | Site plan generator | `ArchEngine_kernel/scripts/generate_site_plan.py` | Python | ~300 | stdlib | in-tree | yes | small | 8 |
| 19 | Title block | `ArchEngine_kernel/scripts/title_block.py` | Python | ~200 | stdlib | in-tree | yes | trivial | 8 |
| 20 | Sheet models | `ArchEngine_CAD/sheets/` | Python | 1,338 | stdlib | in-tree | yes | small | 8 |
| 21 | Generator adapters | `ArchEngine_CAD/generators/` | Python | 649 | stdlib | in-tree | yes | small | 8 |
| 22 | PDF export | `ArchEngine_kernel/scripts/pdf_export.py` | Python | ~400 | `reportlab` + `svglib` | `pdf-writer` 0.10 (low-level) or `printpdf` 0.7 (higher-level) | partial (both crates use `alloc`) | medium | 9 (optional v1) |
| 23 | Permit set orchestrator | `permit_drawing_set.py` | Python | 306 | stdlib | in-tree | yes | trivial | 10 |
| 24 | Persistence (desktop) | `ArchEngine_CAD/database/` | Python (SQLAlchemy) | 2,129 | SQLAlchemy 2.x | `sqlx` 0.8 + `sqlite` feature, OR `rusqlite` 0.32 | no (both want `std`) | medium | 11 (desktop only) |
| 25 | Persistence (kernel) | n/a (kernel KV store) | — | — | — | Semantic OS encrypted KV API (kernel-side) | yes | small (glue) | 11 (kernel only) |
| 26 | CLI/headless face | `headless/api_server.py` + `solver_cli.py` | Python (FastAPI) | 736 + small | `fastapi`, `uvicorn`, `pydantic` | `clap` 4.5 for CLI; `axum` 0.8 + `tokio` 1.40 for desktop HTTP | no (axum/tokio want `std`) | medium | 12 (desktop only) |
| 27 | Smoke test harness | `smoke_test.py` | Python | 354 | stdlib | `cargo test` + golden SVG fixtures | yes | small | 1 (used throughout) |

**Total estimated Rust output**: ~22,000–25,000 LOC for the core; +1,800 for desktop persistence; +1,000 for desktop HTTP/CLI face; +500 for PDF.

**Crate notes:**
- `glam` 0.30 over `nalgebra` 0.34 unless you need full linear algebra (this product mostly needs 2D/3D vectors and transforms). `glam` is faster, smaller, and has `no_std` support.
- `tiny-skia` 0.11: Apache-2.0, no_std-friendly (~25k LOC of Rust). For SVG-string output we don't need it in the core; needed only for on-screen preview on Semantic OS.
- `fontdue` 0.9: MIT, no_std-friendly (~7k LOC). Needed when on-kernel UI lands.
- `pulldown-cmark` 0.12: MIT, no_std-friendly. Only relevant if rendering markdown help text on kernel.
- `serde` 1.0 / `serde_json` 1.0: ubiquitous on desktop; flag as alloc-heavy for kernel (per Semantic OS memory).
- Avoid `polars`, `ndarray`, `nalgebra` unless a specific solver needs them. Today's solvers don't.

---

## 4. Port order — milestones

1. **Milestone A: foundations** *(weeks 1–2)*
   - Stand up Rust workspace + cargo features for `desktop` vs `kernel` targets.
   - Port types crate (#1).
   - Port schema crate (#2) on desktop with `serde_json`; defer kernel JSON parser to milestone F.
   - **Exit:** Rust can round-trip `Shared/TestData/test_building.json` and re-emit it diff-clean against Python's `json.dumps(..., indent=2)`.

2. **Milestone B: solver passes regression test against Python output on the smoke-test corpus** *(weeks 3–6)*
   - Resolve the qbd/CAD solver-duplicate question (pending decision in pivot review). Choose qbd as canonical (already wins via headless API sys.path), archive the CAD copy.
   - Port modules #4–9 (SpatialGraph through QBD layout generator).
   - **Exit:** Rust `qbd_layout_generator` produces a building JSON whose `walls_batch`, `rooms`, `doors`, `windows` match Python's output for the smoke-test answers (3-bed/3-bath/1800sqft ranch). Tolerance: bit-identical for integer mm coordinates, ±1mm for derived geometry.

3. **Milestone C: first SVG drawing produced from Rust matches Python's drawing diff-clean** *(weeks 7–10)*
   - Port modules #13–14, #20 (floor plan + dimensions + sheet models).
   - **Exit:** `02_floor_plan.svg` byte-equivalent (or visually equivalent after normalization) between Rust and Python output on smoke-test input.

4. **Milestone D: full permit set generated end-to-end in pure Rust** *(weeks 11–14)*
   - Port modules #3, #10–12 (OBC engine + validators).
   - Port modules #15–19, #21 (remaining sheets).
   - Port #23 (orchestrator).
   - **Exit:** Rust binary takes QBD answers → 9-sheet permit set in <5 minutes on a desktop Windows test rig, with code/cost validators wired and surfacing violations.

5. **Milestone E: running as native Rust binary on a desktop test rig** *(week 15)*
   - Add desktop persistence (#24) and CLI face (#26).
   - **Exit:** Single Rust binary deployable on Windows/Linux, no Python in the loop. PyQt frontend (if retained) calls it as subprocess.

6. **Milestone F: kernel-compatible build target** *(open-ended, gated on Semantic OS Layer 1)*
   - Replace `serde_json` with hand-rolled JSON parser.
   - Replace `sqlx` with kernel KV store glue (#25).
   - Strip `std::thread`, `std::sync::Mutex` (use `spin::Mutex` or kernel-provided primitives).
   - Verify `cargo build --no-default-features --target x86_64-unknown-none` succeeds.
   - **Exit:** Rust binary boots under Semantic OS user-mode, reads building JSON from kernel FS, writes SVG back. Verify via Semantic OS's first interactive shell once Layer 1 keyboard input lands.

7. **Milestone G: post-v1 UI on Semantic OS** *(post-EOY 2026)*
   - Integrate `tiny-skia` and `fontdue` ports.
   - Build minimal immediate-mode UI (likely a custom mini-framework — `egui` is `std`-bound today).
   - **Exit:** Question elicitation + preview on Semantic OS, no desktop dependency.

---

## 5. Dependencies without clean Rust replacements

| Today's dep | Used for | Rust gap | Recommendation |
|---|---|---|---|
| **`reportlab` + `svglib`** (Python) | PDF export from SVG | No 1:1 Rust replacement. `printpdf` 0.7 and `pdf-writer` 0.10 are lower-level — you build the PDF page primitive-by-primitive rather than rasterizing SVG into PDF. `usvg` 0.43 + `resvg` 0.43 can rasterize SVG; combining with `printpdf` is workable but custom. | (a) For v1, **accept a feature loss**: ship SVG-only and let the user print-to-PDF. (b) For v2, build a custom svg→pdf bridge with `usvg` + `printpdf`. ~2 weeks of work. |
| **SQLAlchemy** (Python) | Persistence layer | `sqlx` 0.8 (async, compile-time-checked) and `diesel` 2.2 (sync, type-safe ORM) are the two mature Rust ORMs. Neither matches SQLAlchemy 1:1, but both are production-grade. | Pick `sqlx` for desktop. Kernel uses Semantic OS KV store, no ORM needed. |
| **OR-Tools / z3 / scipy.optimize** | Not used today | — | The solver is hand-rolled, not library-backed. Lucky break — no port gap. Rust ecosystem has `good_lp`, `russcip`, `z3.rs`, but you don't need them. |
| **shapely / sympy / geopandas** | Not used today | — | Same — no port gap. If geo ops are added later: `geo` 0.30 (MIT, no_std-optional), `geo-types` 0.7, `wkt` 0.11. |
| **OpenCASCADE / CGAL** | Not used today | — | No Rust equivalent at parity, but the product doesn't need BRep CAD. Hard pass. |
| **Open CASCADE / IFC export** | If IFC export survives | `ifc-rs` exists but is alpha; `ifcopenshell` (the de-facto IFC lib) has no Rust port. | Per `memory/project_editing_strategy.md` IFC export is in scope. **Open question for architect** — wrap Python `ifcopenshell` via subprocess on desktop, OR accept IFC as desktop-only Python feature, OR build minimal IFC4 writer in Rust (~5K LOC of careful work). |
| **PyQt6** | Editor shell | `egui` 0.30, `iced` 0.13, `slint` 1.8 are the candidates. None are `no_std`-compatible today (kernel target blocked here). | Desktop Rust: pick `egui` (immediate-mode, closest to PyQt's signal-slot mental model is `iced`, but `egui` is simpler). Kernel target: defer until tiny-skia + fontdue land — then write a thin immediate-mode UI from scratch. |
| **FastAPI / Uvicorn / pydantic** | Headless HTTP | `axum` 0.8 + `tokio` 1.40 (axum is a Tokio-team project, mature). pydantic ≈ `validator` 0.20 + `serde`. | Direct swap on desktop. Kernel doesn't host HTTP servers. |
| **mcp** (Anthropic MCP SDK, Python) | Claude Desktop integration | Official MCP Rust SDK exists (`mcp-rust`) but is young. | Optional feature on desktop. **Don't block port on this.** |
| **PyTorch / diffusers / transformers / xformers / opencv** (~125 deps) | AI render hero shots | Rust has `candle` 0.7, `burn` 0.15, but you'd be rewriting the entire AI render pipeline. | **CUT from Rust port.** Retain Python service on desktop as out-of-process subprocess if hero-shot feature must persist. |
| **PyQt6 WebView for embedded OSM map** | LiDAR-driven site capture | No clean Rust equivalent of an in-process browser; `wry` 0.46 wraps system WebView2/WebKitGTK. | Desktop: keep PyQt for site capture *only*, OR use `wry` in a small auxiliary Rust window. Kernel: defer LiDAR/site capture to post-v1. |
| **CUDA / NVIDIA Warp** (in enhancer) | Not used in core 2D pipeline | — | Cut with enhancer. No port. |

---

## 6. Suggested first port target

**`ArchEngine_kernel/qbd/room_relationships.py` + `wall_graph.py` + `coordinate_solver.py` (combined ~3,400 LOC)**, exercised through a minimal `qbd_layout_generator`-shaped entry point that takes a 1-bed ranch (`smoke_test.py --small` mode) and emits a building JSON.

**Why this:**
- Small, self-contained, pure stdlib in both source and target — no external deps to vet.
- Exercises Rust traits + enums (Zone / OpeningType / WallType), HashMap-heavy graph code, and JSON serialization. Validates the whole "port pattern" before you commit to the bigger solver suite.
- Has a clean regression oracle: run `smoke_test.py --small` in Python, dump `building.json`, then assert Rust matches that file exactly (modulo float ordering).
- Subsumes the foundational types crate by necessity, so milestone A and milestone B's first step land together.
- Validates the dependency story for everything downstream — if these 3,400 LOC port cleanly, all 7,000 LOC of the larger solver suite will too.

**Why not the OBC engine first** (which is the obvious "small + self-contained" pick): the OBC engine is C++ today, so it adds a C++→Rust translation difficulty on top of the Python→Rust one. Better to validate the Python→Rust path first, then take on the C++ port with more confidence.

**Why not the floor plan generator first**: it has zero load-bearing logic without a building JSON input. Building the input is the prerequisite.

---

## 7. Open questions for the architect

1. **PyQt6 shell — survives in any form?** The pivot review's "Lean PyQt shell rewrite" item still has shell design as a pending decision. If shell survives in the post-Rust desktop product, what's its surface? (Materials panel + questionnaire + site dialog + viewport, per the review.) If the Rust core ships first as headless, when does the shell get attention?

2. **Solver duplicates — confirm qbd is canonical for the port.** Pivot review flags it as pending; my reading of `headless/api_server.py:28`'s sys.path order says qbd wins for the live API. Confirm and archive `ArchEngine_CAD/solver_suite.py` et al before the port starts. Porting both is pure waste.

3. **Test corpus for solver regression — is `smoke_test.py`'s synthetic 3-bed/3-bath/1800sqft enough?** Want at least: (a) one tiny ranch (`--small`), (b) one large multi-floor, (c) one edge case that previously broke, (d) one regression for the recent `subdivision_solver.py` work. If a richer corpus exists outside `smoke_test.py`, point me at it.

4. **JSON contract — is `Shared/Schemas/qbd_output.schema.json` the canonical contract for cross-port?** The Rust port must consume and produce the exact byte shape Python does, or the smoke test loses its oracle status. Lock this schema (semver it) before the port begins.

5. **IFC export — in or out for v1?** `memory/project_editing_strategy.md` says output is IFC → Revit. The Python pipeline doesn't ship IFC export today (`ArchEngine_kernel/scripts/ifc_import.py` exists; ifc_export does not — confirm). If IFC is critical for v1, that's a 5K LOC additional Rust port. If post-v1, defer cleanly.

6. **PDF export — feature loss in v1 acceptable?** SVG-only would shorten the v1 port by ~2 weeks (no svg→pdf bridge). User can print-to-PDF from any browser. Acceptable?

7. **Cost rate data for Ontario regions — same loop as code wiring?** `cost_studio.py` ships placeholders. Pivot review item #2 is "Cost rates by Ontario region — replace placeholders with real Ontario-region rates." Is the data table available, or is rate collection a parallel project the port shouldn't block on?

8. **Enhancer/AI render — desktop subprocess strategy acceptable?** Pivot review and `memory/project_visualization_role.md` say AI render is client-facing product surface (hero shots). Confirm: Rust desktop binary calls Python `enhancer_server.py` as a subprocess, kernel binary has no AI render. Acceptable, or does the architect want a more native answer in v1?

9. **Vulkan engine — convergence timing with this port.** `HANDOFF_2026-05-15_VULKAN_KERNEL_PORT.md` runs in parallel. Both ports landing simultaneously is ideal but unrealistic. If the Rust core ships first (likely), does it talk to the C++ Vulkan engine via the existing `arch_api` C ABI as an interim measure, or does it ship with no 3D view until the Vulkan port also lands?

10. **`ArchEngine_CAD/core/` triage — full review needed.** 5,884 LOC, partly load-bearing (`document.py`, `version_control.py`) and partly PyQt-coupled scaffolding. Did not classify each file. Architect call: drive triage from the lean-shell rewrite or from this port?

---

## Appendix: Files explicitly classified

**SURVIVES — Rust port needed (core, kernel-eligible):**
- `permit_drawing_set.py`
- `ArchEngine_kernel/qbd/*.py` (8 files, 8,192 LOC) — canonical solver pipeline
- `ArchEngine_CAD/legible_studios/` (7 files, 776 LOC) — validators
- `ArchEngine_CAD/sheets/` (6 files, 1,338 LOC) — sheet models
- `ArchEngine_CAD/generators/` (3 files, 649 LOC) — generator adapters
- `ArchEngine_kernel/scripts/generate_*.py`, `intelligent_dimensions.py`, `title_block.py`, `generator_base.py`, `roof_generator.py`, `truss_calculator.py`, `wall_types.py`, `schema_validator.py` (~5,000 LOC) — drawing generators
- `ArchEngine_kernel/include/obc_engine.hpp` + `src/obc_engine.cpp` (872 LOC) — OBC compliance
- `ArchEngine_kernel/OBC_Library/tables/*.json` (5 files) — code tables
- `ArchEngine_kernel/include/types.hpp` (832 LOC) — shared types
- `Shared/ArchGeometry/` (5,071 C++ LOC) — schema parser
- `Shared/Schemas/*.json` (78 JSON files) — schema contract

**SURVIVES — desktop-only (out of kernel scope):**
- `headless/api_server.py` (FastAPI → axum on desktop)
- `headless/mcp_server.py` (optional)
- `ArchEngine_CAD/database/` (SQLAlchemy → sqlx on desktop; KV store on kernel)
- `ArchEngine_CAD/panels/materials_panel.py`
- `ArchEngine_CAD/dialogs/qbd_questionnaire.py`, `site_dialog_simple.py`
- `ArchEngine_CAD/widgets/` (LiDAR site capture)
- `ArchEngine_kernel/enhancer/` (17,257 LOC AI render — subprocess on desktop, absent on kernel)

**CUT (per pivot brief, regardless of target):**
- `archengine_gui.py` (root toy GUI)
- `ArchEngine_CAD/app/application.py` and shell wiring (2,730 LOC)
- `ArchEngine_CAD/panels/` except materials_panel (~5,500 LOC of the 6,629)
- `ArchEngine_CAD/dialogs/path_tracer_dialog.py`, `solver_comparison_dialog.py`, `site_dialog.py` (older)
- `ArchEngine_CAD/viewport/vulkan_widget.py` + `archengine_viewport.dll` (Qt-Vulkan glue obsolete post-port)
- `ArchEngine_CAD/views/`, most of `client/`, `sync/`, `tools/` (PyQt-coupled — default cut unless confirmed otherwise)
- `ArchEngine_CAD/solver_suite.py` and its CAD-side duplicates of qbd (pending decision; default cut)
- `ArchEngine_kernel/scripts/plan_editor_2d.py`, `text_to_json_gui.py`, `material_generate.py`, `material_preview.py`, `validate_materials.py`, `render_upscale.py`, `monitor_memory.py`, `memory_leak_test.py`, `text_to_json.py`
- `ArchEngine_kernel/include/arch_api.h` + `src/arch_api.cpp` (4,344 LOC C ABI for Qt embedding)
- `_archive/` (already archived)

**UNCLASSIFIED — architect call needed:**
- `ArchEngine_CAD/core/` (5,884 LOC — mixed load-bearing and PyQt scaffolding)
- `ArchEngine_CAD/client/`, `sync/`, `tools/` (unsampled)
- `ArchEngine_kernel/scripts/ifc_import.py` (gated on IFC question above)
- `ArchEngine_kernel/scripts/slicer_2d.cpp` (could feed Rust floor plan generator with C++ cross-sections, but Python pipeline doesn't use it today)
- `schema_diff.py` (root)
- `ArchEngine_kernel/scripts/legiqbd/`, `llm/`, `qbd/`, `sheets/` subdirs (unsampled)

---

*Document written 2026-05-15 by Claude (Opus 4.7) per the briefing in `HANDOFF_2026-05-15_LEGIBLE_STUDIO_RUST_PORT.md`. Cross-reference parallel handoff `HANDOFF_2026-05-15_VULKAN_KERNEL_PORT.md` and Semantic OS app-requirements memory at `C:/Users/jerro/.claude/projects/F--Software-ArmKernel3/memory/project_semantic_os_app_requirements.md`.*
