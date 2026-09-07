# Legible Studio — Pivot Review Brief for Claude Code

**Purpose of this file:** Context for a pivot review of the Legible Studio codebase. The product has been redefined. Most of what's in the codebase was built for the previous product. This review identifies what survives, what gets archived, and what needs to be built. Read this file first, then proceed with the codebase analysis.

This is not a scope trim. It is a pivot. The job is harder and the cuts are deeper.

---

## The new product, in one paragraph

**Inputs:** location, constraints, budget.
**Output:** permit-ready drawings (building permit set).
**Time target:** 5 minutes from question-completion to drawings, if the first iteration is correct.
**Mechanism:** constraint satisfaction, not CAD drawing. Valid floor plans emerge from the constraint set; they are not drawn by the user or generated and edited.
**User:** the architect, designer, or builder preparing a permit submission.
**Scope:** residential, initially. Permit-set deliverable, not a full design tool.

That is the entire product description. If a feature, module, or subsystem in the codebase doesn't serve this, it is a candidate for cutting regardless of how well it works.

## What this is NOT, anymore

- Not a three-mode product (LegiQBD / LegiCAD / LegiDoc). The three-mode architecture was exploratory. The convergent version is one pipeline.
- Not a 3D modeling tool. 3D may exist as a verification view; it is not the centerpiece.
- Not a CAD drawing tool. The user does not draw walls. The constraint solver produces the geometry.
- Not a Revit plugin (necessarily). The output is a permit-ready 2D drawing set. Revit may or may not be in the pipeline depending on whether the output format requires it.
- Not a rendering tool. Stable Diffusion, CUDA-accelerated rendering, AI visualization — these served the previous product, not this one.
- Not a markdown editor. LegiWrite was the text engine for the three-mode product; its role in the new product is much smaller or zero.

The author has built substantial infrastructure for the previous product. That infrastructure is not free to maintain. Carrying it forward "in case it's useful later" is the failure mode this review is meant to prevent.

## What the codebase likely contains

Inventory based on prior context (verify against the actual repo):

**Possibly load-bearing for the new product:**
- Constraint-related logic: room layout solvers, wall generation systems with constraint logic
- LLM integration patterns from RevitMCP (the integration patterns themselves, not necessarily Revit-specific code)
- Question-elicitation logic from LegiQBD (constraint extraction from natural language)
- Any drawing-set generation code (permit drawings, dimensioning, annotations)

**Possibly archivable:**
- 3D rendering pipeline using Stable Diffusion
- CUDA / NVIDIA Warp acceleration code
- Real-time logging and performance metrics for multi-LLM comparison
- Bridge server for remote Claude Code access
- Local chat app with isomorphic-git versioning
- LegiWrite as a standalone IDE
- Most of RevitMCP if the output is no longer Revit-centric

**Probably needs to be built:**
- A constraint solver that takes (location, constraints, budget) and emits valid floor plan(s)
- Location-aware zoning/code rule retrieval (what does the building department in this jurisdiction require?)
- Permit drawing set generator (plans, elevations, sections, schedules formatted to permit standards)
- A user flow for the question phase that elicits constraints in 5-15 minutes

This inventory is approximate. The reviewer should verify what's actually in the codebase and adjust.

## The frame for this review

The review is structured around three questions, in this order:

**1. What survives the pivot?**
For each significant module/subsystem, decide: does it serve the new product? Specifically — does it contribute to the (location, constraints, budget) → (permit drawings) pipeline?

If yes: keep, possibly with refactoring.
If partially: identify what survives and what doesn't.
If no: archive.

"Could be useful later" is not a yes. The pivot question is "does this serve the product *as now defined*."

**2. What needs to be archived (not deleted)?**
The author has invested real effort in things like the rendering pipeline, the bridge server, RevitMCP. These should not be deleted — they may have value as standalone tools, future projects, or reference implementations. They should be moved out of the active codebase so they stop demanding maintenance attention.

For each archive candidate, recommend:
- Move to separate repo / branch
- Document what it was for and what state it's in
- Stop maintaining it as part of Legible Studio

**3. What's missing that needs to be built?**
The new product requires components that may not exist yet. The reviewer should identify these specifically. Common candidates:
- Jurisdiction-specific code/zoning rule retrieval
- Constraint formalization (translating natural-language constraints into solver-readable form)
- Solver itself (or selection of an existing one — likely SMT, mixed-integer, or a domain-specific layout solver)
- Drawing set generator and formatter
- Verification / sanity check layer between solver output and final drawings

The point is not to write a roadmap. The point is to identify the specific gaps between what exists and what the new product requires, so the author knows what work is ahead.

## Patterns to watch for (this is the important part)

The author has identified specific cognitive patterns in his own working style that show up in the code. The reviewer should look for these explicitly.

**Pivot resistance via reframing.** When a pivot is real, there is a temptation to keep work by reframing it as serving the new product. The 3D rendering pipeline "could be the verification view." LegiWrite "could be the constraint specification editor." RevitMCP "could be the output backend." These claims may be true, but they should be treated as suspect by default. The honest test: would you build this from scratch for the new product? If no, archive it even if a plausible role can be invented.

**Constraint geometry as architecture vs decoration.** The framework's structural claim that constraints generate valid solutions is *literally true* of the new product — this is a constraint satisfaction problem. The risk is that the framework leaks into the architecture as ornament rather than as mechanism. Look for code that uses constraint-geometry vocabulary without doing constraint-geometry work. The constraint solver should be a real constraint solver, not a system that calls itself one.

**Generative scope creep.** The author generates new ideas faster than he closes existing ones. In a pivot context, this looks like: defining the new product narrowly (location, constraints, budget → permit drawings) and then inflating it back to the previous scope through "and also" additions. Watch for any drift from the one-paragraph product definition.

**Three-mode ghost architecture.** The codebase was structured around LegiQBD, LegiCAD, LegiDoc. Those names and their organizing logic may persist in directory structures, class hierarchies, naming conventions, and module boundaries. The new product is one pipeline, not three modes. Ghost architecture from the previous design will create friction. Flag it.

**Foundational reach.** The author tends to want frameworks and abstractions to be foundational — to underwrite everything. In code, this looks like base classes with too many responsibilities, configuration systems anticipating uses that don't exist, abstractions whose justification is "this could generalize" rather than "this is needed." For a pivot, this is especially dangerous: it's where the previous product's ambition gets preserved through abstraction even when concrete features get cut.

## What the review should produce

A document with five sections, in this order:

1. **Survives.** Specific files, modules, or subsystems that serve the new product. For each: what role it plays in the new pipeline, what refactoring (if any) it needs.

2. **Archive.** Things to move out of the active codebase. For each: brief description, recommended archive destination, what state it's in.

3. **Build.** Components that don't exist yet but the new product requires. Order them by dependency (what blocks what). Don't roadmap — just identify the gaps.

4. **Ghost architecture.** Specific places where the old three-mode design is creating friction in the new pipeline. Naming, structure, module boundaries that should be reworked.

5. **Risk flags.** Things the reviewer is uncertain about. Where might the pivot recommendation be wrong? Where does the codebase suggest the author may have already worked through a problem the reviewer is assuming hasn't been addressed?

## What the review should NOT produce

- A full roadmap or sprint plan. The author can plan; he needs the cuts.
- A defense of existing work. If something is well-built but doesn't serve the new product, "well-built" is not a reason to keep it.
- Suggestions to "consider." The review should make calls. The author can disagree.
- Generic best-practices. Test coverage, documentation, code style — out of scope unless directly related to the pivot.
- Cheerleading the new direction. The author has committed to the pivot. The job is to execute the pivot honestly, not to validate the decision.

## A note on register

The author has explicitly asked for ruthless honesty. He has high tolerance for being told he overbuilt. He has low tolerance for hedging.

If the codebase contains substantial work that doesn't survive the pivot, say so directly. If something the author seems attached to should be archived, say so. If the new product as defined is missing critical infrastructure that doesn't exist in the codebase yet, say so without softening.

The review is in service of getting a real product shipped. Politeness that delays shipping is not a service.

## A final note on what this pivot represents

The new product description — (location, constraints, budget) → permit drawings via constraint satisfaction — is the convergent form of work that has been exploratory for some time. The previous architecture was scaffolding. This is the building.

The author's broader thinking about constraint geometry, boundary conditions, and generative exclusions has spent a lot of time looking for a domain where it does real load-bearing work rather than serving as metaphor. This product is that domain. The constraint framework is not decoration here; it is the literal mechanism. That is significant and it is why this pivot is worth executing rather than treating as another conveyor-belt direction change.

Execute accordingly.

---

*Pivot brief written 2026. Supersedes any earlier scope review brief.*
