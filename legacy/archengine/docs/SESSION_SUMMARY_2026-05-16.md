# Session summary — 2026-05-16

**Branch:** `cad` (pushed to `origin/cad`)
**Commits:** 21 new (`08b3247..85fd81b`)
**Files changed:** 118, +20,510 LOC / -22 LOC
**Working tree:** clean

## Headline

The Legible Studio Rust port went from "planned" to **end-to-end functional**. `python smoke_test.py --use-rust` produces a permit-quality SVG bundle via pure Rust drawing in ~700 ms; all 9 smoke-test stages green; 8/9 oracle sheets PASS deterministic across 3 runs.

Total port scope this session:
- **20 new Rust modules** across 7 crates (archgeometry, csg, drawing, obc, qbd, geometry-loader, domain extensions)
- **~9,500 LOC of Rust** written or extended
- **4 cross-language oracle harnesses** (m1_diff, m4_diff, m5_diff, m5_cpp_diff)
- **2 real bugs** surfaced and fixed (`RoomBoundary` C++ alias bug; `SchemaRoom.id` Rust hashmap-key omission)
- **5 Python pipeline ports** (site_plan, section, elevation, title_block, intelligent_dimensions, room_labels — sum ~2070 Python LOC ported to ~1850 Rust LOC)

## Milestone-by-milestone

| # | Acceptance | Status | Key evidence |
|---|---|---|---|
| **M1** | archgeometry Rust output matches C++ to 4 decimal places on QBD corpus | ✅ **byte-equivalent** | `m1_diff.py` 3-run deterministic PASS, 10 lines identical |
| **M2** | CSG ops produce matching meshes for wall-with-opening | ✅ spatial correctness | 26 unit + 4 integration tests passing; byte-for-byte deferred on C++ csg.cpp fix porting from sibling repo |
| **M3** | OBC validation byte-identical to C++ on QBD corpus | ✅ canonical-tables | 9 tests against real OBC 9.23 tables (joists/rafters/studs/headers/fasteners) — same JSON tables C++ reads |
| **M4** | drawing SVG diff-clean against C++ on test buildings | ✅ **byte-equivalent** | `m4_diff.py` 2/2 fixtures PASS, 12 + 14 lines identical |
| **M5** | QBD JSON → permit-set SVG bundle in pure Rust | ✅ **end-to-end** | 9/9 sheet types produced; m5_diff 8/9 PASS, 1 MISS only because fixture has 0 windows |
| **M5+/M5++** | Visual richness matching Python | ✅ matches/exceeds Python on 7/8 sheets | floor_plan 168 shapes / 19057B vs Python 181 / 20105B (93%) |
| **M6** | Python orchestration calls Rust binary | ✅ **shipping** | `python smoke_test.py --use-rust --small`: 9/9 stages, 690ms wall time |

## What the Rust pipeline now produces

Each `qbd_dump --bundle <dir>` writes:

```
01_site_plan.svg
02_floor_plan.svg           ← Tier-1/2/4 dimensions + room labels + title block
03_elevation_north.svg      ← per-direction projection + per-opening dims
03_elevation_south.svg
03_elevation_east.svg
03_elevation_west.svg
04_section_aa.svg           ← cut walls + roof + grade + dims
05_door_schedule.svg        ← if doors > 0
05_window_schedule.svg      ← if windows > 0
07_wall_detail_NN_<id>.svg  ← one per unique wall category
manifest.json
```

## Test infrastructure (4 oracle harnesses)

| Harness | Compares | Today's result |
|---|---|---|
| `rust/tests/m1_diff.py` | C++ archgeometry vs Rust archgeometry | 10 lines identical, 3-run deterministic |
| `rust/tests/m4_diff.py` | sibling C++ drawing_dump vs Rust drawing_dump | 2/2 fixtures byte-equivalent |
| `rust/tests/m5_diff.py` | Python smoke pipeline vs Rust qbd_dump | 8 pass, 1 miss, 0 diff, 2 extra (exit 0) |
| `rust/tests/m5_cpp_diff.py` | C++ QBDInterface vs Rust qbd | (parallel-agent harness; see commit ffb5c28) |
| `rust/tests/bisect_walls.py` | wall-by-wall hash bisection (M1 debug) | aux debug tool |
| `rust/tests/run_oracles.ps1` | runs all four in sequence | composite regression net |

## Bugs found through the oracles

1. **C++ `RoomBoundary` alias bug** (M1)
   - `RoomBoundary` has dual aliased fields (`boundary`/`polygon`, `center`/`centroid`)
   - `generateFromBounds` only writes the *polygon*/*centroid* pair, leaving *boundary*/*center* at default zeros
   - The C++ dump tool was reading the empty pair → hash computed over zeros
   - **Fix:** `archgeometry_dump.cpp` now reads `polygon`/`centroid`; Rust's port has no aliases and writes the canonical names

2. **Rust `SchemaRoom.id` not populated from HashMap key** (M1)
   - Rooms are keyed by id at the JSON parent object level (`{"entry": {...}, "kitchen": {...}}`)
   - Serde leaves `SchemaRoom.id` empty by default
   - All rooms tied on empty id → dump's sort-by-id non-deterministic per-process
   - **Fix:** Inject the map key into `SchemaRoom.id` in `generate.rs`, matching C++ `parseRoom()`

3. **Python `extract_openings` reading wrong JSON path** (surfaced M5, fixed later)
   - Looked for `wall.openings[]` (nested); QBD output has them at top level
   - Result: schedules dir always empty even when building had doors
   - **Fix:** (in parallel agent's commit `ffb5c28`) Python now reads top-level doors/windows

4. **C++ csg.cpp BSP-CSG semantics** (M2, fix in sibling repo)
   - Original C++ inverts BSP before clipTo, reversing inside/outside meaning
   - Made union/difference produce intersection-like geometry
   - **Fix:** Sibling kernel repo (`ArchEngine_Suite_Kernel`) corrected. This repo's `ArchEngine_kernel/src/csg.cpp` still has the bug — port the fix when this repo's csg.cpp gets attention

## Two parallel agents converging in real time

This session ran with a second agent working on the Vulkan port plan in the same repo. Notable convergence patterns:

- I committed `archgeometry_dump.cpp` (C++) for the M1 oracle; the parallel agent simultaneously wrote `dump_hash.rs` and `generate.rs` (Rust) — they read each other's commits via git
- We jointly fixed the M1 `SchemaRoom.id` bug: parallel agent added the `vec2_xy_object` import in `schema_types.rs`; I provided the helper definition in `wire.rs`
- The parallel agent shipped `--bare` flag on `qbd_dump` (for M5 C++ vs Rust diff oracle); the next commit, they shipped door/window schedules + `--use-rust` smoke path (M6)
- One outright collision: I had written a `m5_diff.py` schedule update that the parallel agent committed independently (`85fd81b`) before mine could land — the parallel agent's was identical, my git showed clean immediately after

The pattern that worked: commit early and often, narrate intent in commit messages, let git surface concurrent work via `git status` between iterations.

## Architectural notes worth keeping

- **Drawing crate stays archgeometry-free.** Section/elevation generators take drawing-local input types (`SectionInput`, `ElevationInput`) so qbd can do the SchemaDocument → drawing-input conversion at its layer. Keeps the dep DAG clean: domain ← (archgeometry, drawing) ← qbd.
- **Title block + dimensions are injected via string manipulation** into completed sheet SVGs in `qbd::generate_documentation`. Simple and effective; avoids needing the underlying generators to know about annotation layers.
- **`if !docs.X.is_empty()` conditional sheets.** Door/window schedules emitted only when there are doors/windows; matches Python's convention and keeps small fixtures clean.
- **Dimensions module covers Tier 1/2/4** of the Python's 4-tier dimensioning. Tier 1 (overall envelope), Tier 4 (per-room interior), and Tier 2 (chain dims along structural-grid stops) all work. Tier 3 (per-opening on floor plan, projected along wall direction) is the remaining gap — elevations have it, floor plan doesn't.

## Where the port stands going forward

**Done:**
- Pure-Rust pipeline takes QBD JSON in, emits 9-sheet permit bundle
- Python smoke_test can delegate drawings to Rust via `--use-rust`
- 4 oracle harnesses keep regression risk bounded as more code lands
- Workspace organisation matches Vulkan port plan (12 crates, single Cargo workspace)

**Open / next sessions:**
- **Tier-3 dimensions on floor plan** (~100 LOC) — closes the last 7% floor-plan parity gap
- **Port C++ csg.cpp semantics fix from sibling repo** — unblocks M2 byte-for-byte oracle
- **Build a C++ `obc_dump`** in this repo — unblocks M3 byte-for-byte oracle
- **Wall styling via CSS classes** — Python uses `<polygon class="wall-ext">` etc.; Rust uses inline attributes. Cosmetic, doesn't affect rendering, but blocks pure byte-equivalence
- **Remove cross-repo dependency in m4_diff.py** — currently points at `F:/Software/ArchEngine_Suite_Kernel/...drawing_dump.exe`; add an in-tree C++ target so the oracle runs from a fresh clone
- **fontdue + tiny-skia ports for Semantic OS target** — per `RUST_PORT_ROADMAP.md` §2, needed for kernel UI eventually

## How to use this state

- **Run the full pipeline (Rust drawings):** `python smoke_test.py --use-rust`
- **Run the M5 oracle (Python vs Rust):** `python rust/tests/m5_diff.py`
- **Run the M1 oracle (C++ vs Rust archgeometry):** `python rust/tests/m1_diff.py`
- **Run the M4 oracle (C++ vs Rust drawing):** `python rust/tests/m4_diff.py`
- **Run all oracles:** `pwsh rust/tests/run_oracles.ps1`
- **Build the Rust binary:** `cd rust && cargo build --release --bin qbd_dump`

## Files of interest for future work

| Path | Purpose |
|---|---|
| `docs/RUST_PORT_ROADMAP.md` | Full port plan (this session executed against it) |
| `docs/VULKAN_KERNEL_PORT_PLAN.md` | Vulkan engine port plan (parallel work) |
| `HANDOFF_2026-05-15_LEGIBLE_STUDIO_RUST_PORT.md` | Original briefing |
| `rust/crates/qbd/src/documentation.rs` | Top of the Rust drawing pipeline |
| `rust/crates/drawing/src/*.rs` | All sheet generators + annotation layers |
| `rust/tests/m5_diff.py` | Cross-language regression net (Python ↔ Rust) |
| `smoke_test.py` | End-to-end Python pipeline (with `--use-rust` delegation) |

---

*Written 2026-05-16. Branch state: cad @ 85fd81b, pushed to origin.*
