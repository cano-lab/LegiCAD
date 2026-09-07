# history/

Archived points-in-time from before and during the Rust port. **Nothing here is
part of the current build** — it's kept for provenance and reference only. The
live project is the Rust workspace under `rust/`; see the top-level `README.md`
and `docs/ROADMAP_2026-05-31.md`.

## Contents

### Legacy code
- `ArchEngine_CAD/` — original Python/PyQt6 CAD application.
- `ArchEngine_kernel/` — original C++ Vulkan kernel + Python drawing scripts.
  Many Rust crates carry `// Port of ArchEngine_kernel/...` provenance comments
  that point back here.
- `headless/` — original FastAPI server.
- `Shared/` — pre-Rust canonical schema JSON + design docs. The schema contract
  now lives in the `ls-archgeometry` crate.
- `archengine_gui.py`, `permit_drawing_set.py`, `schema_diff.py` — old Python
  entry points / tooling.
- `_archive/` — earlier prunings (UE5 viewer, render-server orchestration,
  duplicated solvers, etc.).
- `python-diff-tests/` — old root-level Python diff tests.
- `rust-tests/` — Python/PowerShell cross-language oracle scripts from the port
  era (`m*_diff.py`, `run_oracles.ps1`). Superseded by the Rust `smoke-test`
  crate and per-crate `cargo test` integration tests.

### Historical docs
- `docs/` — dated handoffs, the pivot brief/review, the original Rust-port
  roadmap, session summaries, the formal spec, research paper, and the Vulkan
  port plan. The current roadmap is `docs/ROADMAP_2026-05-31.md` (kept live).
