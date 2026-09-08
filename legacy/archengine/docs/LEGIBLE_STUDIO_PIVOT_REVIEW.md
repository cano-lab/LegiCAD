# Legible Studio — Architecture & State

**Last updated:** 2026-04-27
**Supersedes:** the original pivot review (see git history for `LEGIBLE_STUDIO_PIVOT_REVIEW.md` prior to this date).

This document is the current reference for what Legible Studio is, what's load-bearing in the codebase, what's been archived, what's still to build, and what decisions are still open. Read alongside `LEGIBLE_STUDIO_PIVOT_BRIEF.md` (which states the product intent) and `MEMORY.md` in the Claude memory store (which captures decisions with reasoning).

---

## Product

**Inputs:** location (with LiDAR-derived lot data for Ontario regions), program/constraints (via questionnaire), budget.
**Outputs:** (1) Ontario-Building-Code-compliant permit drawing set, (2) canonical Vulkan path-traced visualization for design verification, (3) AI-rendered hero shots for client presentation, (4) interior design layer with image-derived furniture.
**Mechanism:** constraint satisfaction → geometry → OBC validation → drawing generation → visualization. Not a CAD drawing tool. The user does not draw walls.
**Time target:** 5 minutes from question-completion to deliverables, if the first iteration is correct.
**User:** the architect, designer, or builder preparing a residential building permit submission in Ontario.
**Scope:** Ontario residential, OBC compliance only (no zoning, no other jurisdictions). v1 ships behind the constraint-solver wedge.

---

## Architecture

Three layers, plus an integration bus between them:

```
┌─────────────────────────────────────────────────────────────────┐
│  Python layer                                                   │
│  ├── Question elicitation: PyQt dialogs                         │
│  │     (qbd_questionnaire, site_dialog_simple with LiDAR map)   │
│  ├── Constraint solver: ArchEngine_CAD/solver_suite.py + ...    │
│  │     OR qbd/'s parallel versions (DECISION PENDING)           │
│  ├── QBD layout pipeline: qbd/qbd_layout_generator.py           │
│  │     → QBD JSON (mm-based)                                    │
│  ├── Validators (post-solve): legible_studios/code_studio.py    │
│  │     + cost_studio.py — orphaned today, need wiring           │
│  ├── Drawing-set generator: 9-sheet permit set (SVG/PDF)        │
│  ├── AI render server: enhancer_server, upscaler, etc.          │
│  │     → presentation hero shots (NOT canonical viz)            │
│  └── Headless API + MCP: FastAPI + MCP server                   │
│                                                                 │
│  C++ kernel (ArchEngine_kernel/)                                │
│  ├── arch_api: C API for Python ctypes binding                  │
│  ├── qbd_interface: consumes QBD JSON (mm), produces geometry   │
│  ├── obc_engine: OBC Section 9.23 compliance with real tables   │
│  │     (joists, rafters, studs, headers, fastener schedules)    │
│  ├── Vulkan renderer + path_tracer: canonical visualization     │
│  └── Geometry: wall_system, plan_generator, slicer_2d, csg, bvh │
│                                                                 │
│  PyQt shell (ArchEngine_CAD/app/)                               │
│  ├── Canonical viewport: viewport/vulkan_widget.py (DLL embed)  │
│  ├── Materials panel                                            │
│  ├── Dialogs (questionnaire + site)                             │
│  └── Furniture (returning — interior design layer)              │
└─────────────────────────────────────────────────────────────────┘
```

The Python and C++ layers are a **pipeline, not parallel implementations**. Python builds layouts and emits QBD JSON; C++ validates against OBC and renders. This was misread in the original review and is documented in `memory/project_kernel_scope.md` so it doesn't get re-misread.

---

## Survives — load-bearing in v1

### Compliance (OBC)
- `ArchEngine_kernel/include/obc_engine.hpp` + `src/obc_engine.cpp` (~1,055 lines C++)
- `ArchEngine_kernel/OBC_Library/tables/*.json` (real Section 9.23 tables)
- `ArchEngine_CAD/legible_studios/studios/code_studio.py` — Python validators (egress, corridor widths, stair geometry, natural light, accessibility). Currently orphaned; needs wiring.
- `ArchEngine_CAD/legible_studios/studios/cost_studio.py` — Python cost estimator with Ontario-region-tunable rates. Currently orphaned; needs wiring.
- `ArchEngine_CAD/legible_studios/core/constraint_lens.py` — base class for the validators.

### Constraint solving / layout generation
- `ArchEngine_CAD/solver_suite.py`, `complete_solver_suite.py`, `advanced_solvers.py`, `normalized_solver.py` — multi-algorithm constraint solver (CSP, WFC, BSP, force-directed, genetic, etc.).
- `ArchEngine_CAD/room_relationships.py` — `SpatialGraph` data model.
- `ArchEngine_CAD/core/constraints.py` — constraint type vocabulary.
- `ArchEngine_kernel/qbd/qbd_layout_generator.py` — converts QBD answers → spatial graph → placed layout → QBD JSON for the C++ engine.
- `ArchEngine_kernel/qbd/coordinate_solver.py`, `wall_graph.py`, `layout_refiner.py` — supporting layout pipeline.
- `ArchEngine_kernel/qbd/room_relationships.py` — qbd-side parallel version (see Pending Decisions).

### Drawing set generation
- `permit_drawing_set.py` (repo root) — orchestrates the 9-sheet permit set.
- `ArchEngine_kernel/scripts/generate_plans.py` — floor plan SVG.
- `ArchEngine_kernel/scripts/generate_elevations.py`, `generate_sections.py`, `generate_schedules.py` — other sheets.
- `ArchEngine_kernel/scripts/intelligent_dimensions.py` — four-tier dimensioning (overall / structural / opening / interior).
- `ArchEngine_kernel/scripts/title_block.py`.
- `ArchEngine_CAD/generators/generator_adapters.py` — in-memory adapter layer.
- `ArchEngine_CAD/sheets/` — sheet data models (`models.py`, `sheet_registry.py`, `dimension_item.py`, `svg_parser.py`).

### Visualization
- **Canonical (real-time, accurate)**: Vulkan renderer + path tracer + supporting pipeline in `ArchEngine_kernel/src/`. Embedded into the PyQt shell via `ArchEngine_CAD/viewport/vulkan_widget.py` ↔ `arch_api`.
- **Presentation (hero shots)**: AI render pipeline in `ArchEngine_kernel/enhancer/` — `enhancer_server.py`, `upscaler.py`, `vision_processor.py`, `ai_segmentation.py`, channel extractors, Stable Diffusion inpainting. (Vulkan does the actual rendering; this layer enhances/post-processes.)
- **Image-to-3D for furniture**: TripoSR (MIT) chosen for v1, behind a swappable `Image3DGenerator` abstraction. To be implemented when furniture returns. Hunyuan3D evaluated and rejected for license incompatibility (EU/UK exclusion, MAU ceiling). See `memory/project_furniture_direction.md`.

### Integration / API surface
- `headless/api_server.py` — FastAPI for solve/get-plan/export.
- `headless/mcp_server.py` — MCP server for Claude Desktop integration. **Replaces RevitMCP entirely.**
- `ArchEngine_CAD/api/routes/solvers.py`, `routes/buildings.py`, `routes/projects.py`.

### PyQt shell (current — being slimmed)
The shell is in transition. Today's `ArchEngine_CAD/app/application.py` is a 2,400-line file deeply wired to many panels that should not survive. Targeted final shape:

- **Keep:** `viewport/vulkan_widget.py`, `panels/materials_panel.py`, `dialogs/qbd_questionnaire.py`, `dialogs/site_dialog_simple.py`, `widgets/embedded_map_widget.py` + `osm_map.html`, `widgets/site_editor_widget.py`, furniture (returning).
- **Cut (pending lean-shell rewrite):** `panels/chat_panel.py`, `onboarding_overlay.py`, `sheet_manager.py`, `version_history.py`, `viewport_panel.py` (with `gravity_triangle` + `lod_indicator`), `properties_panel.py`, `solver_params_panel.py`, all of `smart_panel*` + `panel_registry.py`, `views/plan_view.py`, `dialogs/path_tracer_dialog.py`, `dialogs/solver_comparison_dialog.py`, `dialogs/site_dialog.py` (older variant). See Pending Decisions for the rewrite approach.

### Document model and infrastructure
- `ArchEngine_CAD/core/document.py`, `core/events.py`, `core/commands.py`, `core/version_control.py`.

---

## Archived

All archives live under `_archive/` in the repo. Recoverable via git, not deleted. Subdirectory structure reflects what they were and roughly when:

| Archive | Source | Reason |
|---------|--------|--------|
| `_archive/viewer_ue5/` | `ArchEngine_Viewer_ue5/` (132M) | UE5 viewer; replaced by embedded Vulkan; was already disabled in app/application.py:61 |
| `_archive/furniture/` | `ArchEngine_CAD/furniture/` | Will return as interior design layer with image-to-3D; existing AI-generator code is wrong shape and will be rebuilt |
| `_archive/legible_studios_partial/` | three of five `studios/` (climate, structural, acoustic) + `integration/` (LOD bridge, indicator) | Out of permit-set scope; LOD-blending UI infra not needed headless |
| `_archive/render_server_revitmcp/` | ~70 files: entire `tools/`, `tests/`, `family_editor_tools/`, `endpoints/`, `llm_providers/`, `physics/` subdirs + `family_builder.py`, `detail_tools.py`, `ifc_tools.py`, `openai_tools_schema.py`, etc. | RevitMCP-era tooling; product is no longer Revit-centric (MCP is the new integration) |
| `_archive/render_server_orchestration/` | `server.py`, `client_orchestrator.py`, `check_httpx.py`, `planner*.py`, `session_manager.py`, `progress_state.py` | RevitMCP web server + LLM orchestration |
| `_archive/render_server_orphans/` | ~22 files + 3 subdirs: `assemblies/`, `ui/`, `utils/`, plus duplicates of CAD-canonical files (visual_comparison, version_control), older QBD UI cluster (qbd_interview, qbd_session, entropy_questions), older floor-plan-tool cluster (room_layout_solver_v2_fixed, v3, layout_to_walls) | Verified orphan or CAD-superseded |
| `_archive/kernel_pruned/` | `ipc_server.hpp/cpp`, `llm_assistant.hpp/cpp`, `physics_bridge_fixed.cpp` | IPC was for UE5 (now embedded); LLM render-tuning was nice-to-have; physics_bridge_fixed was unreferenced dead duplicate |
| `_archive/cad_ui_orphans/` | Map alternatives (google_maps_widget, static_map_widget, browser_map_launcher, webview_map_launcher, webview_map_widget, map_widget_qt), constraint_info, UE5 viewport leftovers (viewport_widget, viewport_bridge, ue5_launcher, example_integration), native bridge subdir, UE5-focused README | Duplicate map widgets; UE5 leftovers (UE5 already archived) |

**Counts as of 2026-04-26:** `render_server` reduced from 137 → 34 .py files. C++ kernel down by 5 files. CAD UI down by 13 files. Plus the bigger directory-level archives.

**Renamed 2026-04-27:** the surviving 34 files split into `enhancer/` (~22 .py + scripts — the AI/render layer) and `qbd/` (8 .py — live layout pipeline + parallel-canonical solvers). `render_server/` no longer exists. Path strings updated in `application.py`, `api_server.py`, `smoke_test.py`, `main.cpp`, `imgui_layer.cpp`. `start_render_server.ps1` retained its name inside `enhancer/` since it still launches `render_server.py` (the Flask app file kept its name too — internal naming consistency).

**One soft break to remember:** the C++ kernel's `main.cpp` no longer instantiates the IPC server, but it still references `enhancer/start_render_server.ps1` for the AI launcher button. The standalone .exe still compiles; the CAD-app-syncs-via-IPC flow is gone (PyQt embeds the DLL instead).

---

## To build

Ordered by dependency (earlier blocks later):

### 1. Wire the validators into the pipeline
`code_studio.py` and `cost_studio.py` exist and are good. Nothing calls them today. The work: instantiate them, pass solver output to them, surface their `ComplianceReport` violations back through the pipeline (and ideally cause re-solve on critical failures). Smaller job than originally estimated because the validators are real.

### 2. Cost rates by Ontario region
`cost_studio.py` ships with placeholder COST_RATES ($/m² for walls, floors, etc.). Replace with real Ontario-region rates. Manual curation is realistic for v1 (Toronto / Ottawa / mid-Ontario / north). Data sources: local builder surveys, RSMeans Ontario, recent permit data.

### 3. LiDAR → solver-input pipeline
The site dialog captures a lot polygon visually from LiDAR-derived map data. Need an explicit step that converts the captured polygon into the constraint schema the solver consumes (lot boundary, dimensions, slope if relevant). Today this likely flows manually.

### 4. Furniture interior design layer
- `Image3DGenerator` abstraction interface (mandatory — see `memory/feedback_dependency_portability.md`).
- TripoSR implementation behind that interface. Runs in `enhancer/` alongside the AI render pipeline.
- Furniture data structures (`models.py`, `catalog.py`, `primitives.py` from the archive can return as-is).
- Vulkan-side scene composition: place generated furniture meshes into rendered rooms, allow client interaction.
- Output format: confirm Vulkan engine ingests glTF/OBJ from TripoSR (likely needs assimp or cgltf integration).

### 5. Lean PyQt shell rewrite
Replace `app/application.py` (2,400+ lines, deeply wired to soon-to-be-archived panels) with a minimal shell that hosts only: vulkan viewport + materials panel + dialogs + furniture. Approach: design the new shape (single window? toolbar layout? dock topology?) → write fresh shell → archive the old `application.py`. Trying to surgically edit the existing file is the wrong move — too many signal chains.

### 6. End-to-end smoke test
Today, no test runs the full pipeline (location → questions → solve → validate → drawings → render). Build one against a known building, time it, verify the 5-minute target.

### 7. Solver duplicates resolution
Strategic call (see Pending Decisions): pick `ArchEngine_CAD/` or `ArchEngine_kernel/qbd/` as canonical, migrate `headless/api_server.py`, archive the loser.

---

## Pending decisions

### Solver duplicates between qbd/ and ArchEngine_CAD/
`solver_suite.py`, `complete_solver_suite.py`, `advanced_solvers.py`, `room_relationships.py` exist in **both** `ArchEngine_CAD/` and `ArchEngine_kernel/qbd/`. They differ in size; sys.path order in `headless/api_server.py:28` puts qbd first, so the headless API uses qbd's versions; the CAD app uses CAD's own. Both are in active use through different entry points. Strategic call needed: which is canonical, migrate api_server, archive the other.

### Lean shell design
What does the new minimal PyQt app look like? Single window with vulkan viewport center, materials side panel, dialogs as modals? Or something more web-app-like? Decide before rewriting `application.py`.

### Image-to-3D quality threshold
TripoSR is MIT-clean but lower quality than Hunyuan3D 2.5. If client feedback shows TripoSR isn't good enough for hero-shot furniture, the abstraction layer makes a swap easy — but the business question (rebuild quality story, accept license risk, or fine-tune?) is unresolved.

### Standalone kernel .exe
The C++ kernel still builds an .exe target alongside the .dll. With IPC removed, the .exe has no incoming-data path other than command-line arguments. Decide whether to keep the .exe (useful for development, standalone testing) or strip the target from CMakeLists.

---

## Notes for future work / future sessions

- **Read code before classifying.** The original review undervalued the kernel and missed the legible_studios validators. Both were "verify what's actually in the codebase" failures the brief warned about. Specifically, `obc_engine.hpp/cpp` and the OBC_Library tables were already-built infrastructure that the original inventory pass missed.
- **The architecture is a pipeline, not parallel systems.** Python (qbd_layout_generator) → QBD JSON → C++ (qbd_interface) → OBC validation + Vulkan render. Don't propose archiving "most of the kernel" — most of it is doing real product work. Pruning is surgical (see `memory/project_kernel_scope.md`).
- **Visualization is product surface, not internal.** The AI/enhancer pipeline is for client-facing presentation, not developer verification. Cuts to the AI side were reversed for this reason. See `memory/project_visualization_role.md`.
- **Ontario-only / OBC-only narrows the build list significantly.** What was originally "build a jurisdiction layer" is now "use the OBC engine that already exists." See `memory/project_jurisdictional_scope.md`.
- **Treat external AI models as swappable.** Hunyuan3D's license excluded EU/UK/South Korea — load-bearing dependency on it would have forced a rewrite at acquisition. Always abstract. See `memory/feedback_dependency_portability.md`.
- **The pivot brief's "ghost architecture" warning still applies.** `legible_studios/` directory inside `ArchEngine_CAD/`, the `ArchEngine_*` paths under a `LegibleStudios` repo, "QBD" naming throughout, two parallel constraint vocabularies in `core/constraints.py` and `room_relationships.py` — none of these have been renamed yet. Worth a cleanup pass once the lean shell lands.

---

*Document maintained by Claude (Opus 4.7) sessions in collaboration with Jerroy. When making architectural decisions, update this file alongside the corresponding memory file in the Claude memory store.*
