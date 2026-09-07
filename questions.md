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
