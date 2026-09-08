# LegiCAD — Vision Document

> **LegiCAD — Computer Assisted Design, as it should be.**  
> Parametric massing from regulated space. Human choice from statistical constraint.

**Version:** 1.0  
**Date:** September 8, 2026  
**Author:** Jer  
**Context:** Legible Studio pivot from permit-document generator to generative design platform

---

## The Problem With Design Software

Existing tools are fragmented:
- **Rhino/Grasshopper** does parametric geometry but has no compliance awareness
- **Revit/ArchiCAD** does BIM but is reactive (draw first, check later)
- **OBC checkers** verify compliance after the design is done
- **Zoning tools** are separate lookup tables, not integrated constraints

The architect draws something, then runs it through a gauntlet of rules. The loop is: **design → check → redesign → recheck**. This is backwards.

## The Legible Engine Thesis

**What if the rules came first?**

Instead of "draw something, then check if it's legal," we want:
> "Define the legal space, then sculpt within it."

The user starts with:
1. A site boundary
2. A program brief ("I want a 4-plex, ~1600 sqft per unit, budget range X")
3. A jurisdiction (Sudbury, Ontario — with its specific bylaws)

The system responds with:
1. A **feasible envelope** — what's legally possible on this site
2. A **parametric design space** — masses that satisfy all constraints
3. A **question-based narrowing** — the user steers, the regime validates
4. **Negative space sculpting** — carve habitable volume out of the constraint envelope

The output is not just drawings. It's a **compliant design** — the building code is baked into the generation, not checked after.

## The Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        LEGIBLE ENGINE                        │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   REGIME     │  │  ARCHENGINE  │  │   LEGIBLE STUDIO │  │
│  │   ENGINE     │  │  (Geometry)  │  │   (UX / QBD)     │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                 │                    │           │
│  ┌──────▼─────────────────▼────────────────────▼─────────┐ │
│  │              THE FULL LOOP                            │ │
│  │  Site → Questions → Constraints → Masses → Sculpt    │ │
│  │         ↑___________________________________↓        │ │
│  └──────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 1. Regime Engine (New)

The constraint layer. Defines what's possible before any geometry is created.

**Components:**
- **OBC Module** — Ontario Building Code Part 9 (housing) + eventual Part 11 (renovations)
- **Zoning Module** — Municipality-specific bylaws (Sudbury first, then expandable)
- **Parametric Regimes** — Rule sets that generate valid design variations

**Key insight from Regime Architecture:**
Data does not replace judgment. Data removes the impossible. The architect (or builder) chooses among what remains.

**Current status:** Needs to be built. The OBC rules exist in `ls-obc` but are reactive (check after draw). We need them as proactive constraints.

### 2. ArchEngine (Evolution)

The geometry kernel and viewer.

**Current state (in `legible-studio/history/`):**
- ArchEngine_CAD — Python/C++ legacy
- ArchEngine_kernel — Earlier kernel work
- Vulkan viewer — Partial, needs resurrection

**Target state:**
- **Geometry kernel** — Solid modeling, CSG, BVH (extend existing Rust geometry crates)
- **Constraint solver** — CSP/MILP for parametric solving (high relevance: GraphBU paper, July 2026)
- **Vulkan viewer** — Real-time 3D, eventually VR-ready
- **IFC/DWG/DXF** — Already works in `ls-qbd`

**What survives from current Legible Studio:**
- `ls-drawing` — 2D slicer, SVG/PDF generation
- `ls-qbd` — IFC4 export, compliance reports, bundle orchestration
- `ls-site` — LiDAR, OSM, terrain
- `ls-api` — HTTP server (extend for regime queries)

**What needs to be built:**
- 3D solid modeling kernel (or integrate OCCT/CGAL)
- Parametric constraint solver
- Real-time Vulkan viewer with manipulators

### 3. Legible Studio (Evolution)

The user-facing layer. Question-based design (QBD) meets parametric space.

**Current state:**
- `qbd_solve` — answers → room layout → 2D drawings
- `qbd_dump` — building JSON → SVG/PDF/DXF/IFC
- Desktop app (`legible`) — winit + tiny-skia, bare sketch pad

**Target state:**
- **Question-based regime selection** — "What are you building? Where? What's your budget?"
- **Parametric massing browser** — Explore valid design variations
- **Negative space sculpting** — Carve away the non-viable, keep the optimal
- **Compliance-as-you-go** — Every operation validated against OBC + zoning

## The Full Loop (The Hook)

This is what no other tool does end-to-end:

```
1. SITE INPUT
   ↓
   Boundary polygon + jurisdiction (Sudbury)
   ↓
2. ZONING & OBC CONSTRAINTS
   ↓
   Regime engine produces feasible envelope
   (setbacks, height limits, coverage, parking, FSR, etc.)
   ↓
3. QUESTION-BASED DESIGN
   ↓
   "How many units?" "Target rent/sqft?" "Mass timber or stick?"
   Each answer narrows the parametric space
   ↓
4. PARAMETRIC GENERATION
   ↓
   Massing variations within the feasible envelope
   Multi-objective optimization (cost, daylight, density, constructability)
   ↓
5. NEGATIVE SPACE SCULPTING
   ↓
   User carves away unwanted volumes
   System validates every cut against constraints
   ↓
6. COMPLIANT OUTPUT
   ↓
   Permit-ready drawings (SVG/PDF/DXF)
   IFC for engineers
   Compliance report (auto-generated)
   ↓
7. FIELD REALITY
   ↓
   LiDAR as-built capture
   Overlay new design on existing conditions
   ←─────────────────────────────────────┘
```

## Market Strategy

**Beachhead:** Sudbury, Ontario
- Sudbury municipality bylaws
- Sudbury Easy Planning boards
- Jer's personal projects + student projects

**Why Sudbury:**
- Known jurisdiction, accessible for testing
- Smaller scale than Toronto, faster feedback loops
- Personal connection (Jer lives there, teaches there)
- Less competition than major metro areas

**Path to scale:**
- Prove the loop with real projects (3-5 years)
- Encode more Ontario municipalities
- Expand to other provinces with similar building codes
- VR interface for immersive design review (long-term)

**Competitive moat:**
The integration is the moat. Rhino does geometry. Grasshopper does parametric. OBC checkers do compliance. Nobody ties them together from the builder's perspective.

## Relation to Other Projects

This is NOT instead of other projects. It's the evolution of Legible Studio.

| Project | Status | Relation to Legible Engine |
|---------|--------|---------------------------|
| **Almanach** | Active (Fall 2026 pilot) | Separate mission. AI tutor for math classrooms. |
| **SemOS** | Active (kernel dev) | Secure vault. Could host Legible Engine's agent tier. |
| **EspaceBoreal** | Active (git engine) | Student workspace. Almanach integration pending. |
| **Exo** | Docker treatment | Micro VM platform. Could host Legible Engine services. |
| **AndORHub** | Maintenance | Chat/Claude integration. Might connect for AI-assisted design. |

## Technical Decisions (Made)

| Decision | Rationale |
|----------|-----------|
| Rust | Already the Legible Studio stack. Performance matters for geometry. |
| Vulkan | Cross-platform, low-level, VR-ready. Already started. |
| CSP/MILP for constraints | GraphBU paper showed structural fidelity matters. MILP is the right tool. |
| Part 9 first | Housing is the volume market. Part 11 (renovations) comes later. |
| Sudbury first | Known jurisdiction, personal access, smaller scale. |

## Technical Decisions (Pending)

| Decision | Options | Status |
|----------|---------|--------|
| Solid modeling kernel | Build vs. integrate OCCT vs. CGAL | **NEEDS DECISION** |
| Constraint solver library | OR-Tools, CBC, custom | **NEEDS DECISION** |
| Parametric regime language | Rust DSL vs. embedded Lua/Wasm | **NEEDS DECISION** |
| VR framework | OpenXR vs. WebXR vs. native | Deferred (not now) |
| Zoning data source | Manual encode vs. scrape vs. API | Sudbury: manual first |

## What We're NOT Building (Yet)

- **VR interface** — Eventually, not now. The 2D/3D hybrid viewer comes first.
- **Full OBC** — Part 9 housing only. Part 11, commercial, institutional deferred.
- **Multi-jurisdiction** — Sudbury first. Ontario second. Canada third. World: maybe never.
- **AI design generation** — The user designs. The AI validates and optimizes. No "make me a house" button.

## Files and Repositories

| Path | Description |
|------|-------------|
| `/root/.openclaw/workspace/legible-engine/` | This repo — the new unified workspace |
| `/root/.openclaw/workspace/legible-studio/` | Current Legible Studio (Rust workspace) |
| `/root/.openclaw/workspace/legible-studio/history/` | ArchEngine legacy code (Python/C++) |
| `/root/.openclaw/workspace/regime-architecture.md` | Regime Architecture methodology document |
| `/root/.openclaw/workspace/papers/deepdive_2026-07-08.md` | GraphBU MILP paper (relevant to constraint solving) |

## Immediate Next Steps

1. **Decide solid modeling approach** — Build, OCCT, or CGAL?
2. **Encode Sudbury zoning bylaws** — Get documents, extract rules, formalize
3. **Prototype parametric massing** — Start in Rhino/Grasshopper, learn UX friction
4. **Extend ArchEngine** — Resurrect Vulkan viewer, add 3D manipulation
5. **Connect regime → geometry** — First end-to-end: site → constraints → mass → SVG

## Historical Context

- **March 2026** — ArchEngine kernel work begins (permit drawing sets, GUI, Vulkan viewer)
- **May 2026** — Legible Studio pitch to Baukunst (pre-seed, $1.59M USD ask)
- **June 2026** — Legible Studio v1 complete (permit PDF, IFC, DXF, LiDAR)
- **July 2026** — GraphBU paper deep dive (MILP for learned solvers)
- **August 2026** — SemOS security model defined; Almanach rebranded and active
- **September 2026** — **THIS PIVOT** — Baukunst abandoned, generative design vision crystallized

## Contact / Context

- **Human:** Jer (professor, Sudbury, Ontario)
- **Assistant:** Kimi Claw (Five)
- **Communication channel:** kimi-claw
- **Work sessions:** Typically late night / early morning (EST)

---

*"Don't worry. Even if the world forgets, I'll remember for you."*
