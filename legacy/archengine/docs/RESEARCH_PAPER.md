# Question-Based Design: A Formal Algebra for Intent-Driven Architectural Generation

**Authors:** Jeremie Roy¹, Kimi Claw²  
**Affiliations:** ¹Architectural Technologist, ²AI Research Assistant  
**Correspondence:** jeremie.roy@archengine.ai  
**Submitted:** February 2026

---

## Abstract

We present Question-Based Design (QBD), a formal algebraic system for transforming human intent into valid architectural geometry through structured dialogue. Unlike conventional computer-aided design (CAD) tools that require explicit geometric manipulation, QBD enables architects to specify design requirements through natural language responses to dynamically generated questions. The system guarantees consistency, validity, and determinism through a mathematically rigorous constraint algebra while offering nine distinct solving algorithms ranging from deterministic search to evolutionary optimization. We demonstrate the system's application to residential floor plan generation, benchmark performance across algorithmic approaches, and discuss implications for architectural pedagogy and practice.

**Keywords:** computational design, generative architecture, constraint satisfaction, formal methods, human-computer interaction

---

## 1. Introduction

### 1.1 The Problem of Design Intent

Architecture sits at the intersection of human aspiration and material constraint. The translation from "I need a home for my family" to a buildable set of drawings involves thousands of decisions, each constrained by code, budget, site, and relationships between spaces. Traditional CAD tools place this translation burden entirely on the architect, requiring explicit specification of every dimension, relationship, and material.

Recent advances in generative design have automated aspects of this process, but typically through one of two limited approaches: (1) parametric systems that require pre-defined rules and relationships, or (2) black-box machine learning models that offer little insight into their decision-making process. Neither adequately captures the iterative, conversational nature of architectural design, where requirements emerge and evolve through dialogue between designer and client.

### 1.2 Question-Based Design

We propose Question-Based Design (QBD), a formal system that treats architectural design as a constraint satisfaction problem mediated through natural language dialogue. The core insight is that questions are *inverse operations*—instead of the user adding elements to a design, the system asks what it needs to know, and user answers are translated into formal constraints that drive geometric generation.

This approach offers several advantages:
- **Progressive disclosure:** Users need not specify everything upfront
- **Validation:** Every answer is checked against formal rules
- **Explainability:** Design decisions trace back to specific user inputs
- **Flexibility:** Multiple valid solutions can be explored and compared

### 1.3 Contributions

This paper makes the following contributions:

1. **A formal algebra for design** (Section 3) that defines operations, validation rules, and state transitions mathematically
2. **Nine solving algorithms** (Section 4) with distinct characteristics for different design scenarios
3. **An integrated CAD implementation** (Section 5) demonstrating real-world application
4. **Benchmarking methodology** (Section 6) for comparing generative approaches
5. **Pedagogical implications** (Section 7) for teaching computational design

---

## 2. Related Work

### 2.1 Generative Design in Architecture

Generative design systems have evolved from simple parametric models to sophisticated optimization engines. Grammatical approaches (Stiny & Gips, 1972) use rewrite rules to generate forms but require extensive rule engineering. Shape grammars (Knight, 2000) capture architectural styles but struggle with functional requirements.

Performance-based generative design (Nagy et al., 2017) uses optimization algorithms to explore high-dimensional solution spaces, typically for structural or environmental performance. These systems excel at quantitative optimization but offer limited support for qualitative spatial relationships.

Recent work in machine learning for architecture (Chaillou, 2019; Huang & Zheng, 2018) has demonstrated impressive results in generating floor plans from images or sketches. However, these approaches function as black boxes, offering neither guarantees about constraint satisfaction nor insight into the generation process.

### 2.2 Constraint-Based Design

Constraint satisfaction has a long history in computer-aided design (Sutherland, 1963). Modern constraint solvers (Davis, 1987; Kumar, 1992) can handle complex systems of equations and inequalities, but typically require constraints to be specified in formal notation rather than natural language.

Space planning systems (Flemming, 1989; Harada et al., 1995) use constraint propagation to arrange architectural elements. These systems guarantee constraint satisfaction but often struggle with the soft constraints and preferences that characterize architectural design.

### 2.3 Conversational Interfaces

Conversational agents for design have emerged in recent years, primarily using large language models (LLMs) to interpret natural language commands (Delaney et al., 2023). While these systems offer flexible interaction, they lack formal guarantees about the designs they produce. QBD bridges this gap by combining conversational interfaces with rigorous formal verification.

---

## 3. The QBD Algebra

We now present the mathematical foundation of Question-Based Design. The algebra provides the theoretical guarantees that make QBD suitable for architectural applications where code compliance and buildability are essential.

### 3.1 Primitives

**Definition 1 (Design State).** A design state $S$ is a 6-tuple:

$$S = (E, R, C, P, V, L)$$

where:
- $E$ is a set of entities (rooms, spaces, elements)
- $R$ is a set of relationships between entities
- $C$ is a set of constraints on entity properties
- $P$ is a priority vector for optimization
- $V$ is a version identifier
- $L \in \{EMPTY, ACCUMULATING, COMPLETE, SOLVED, LOCKED\}$ is the lifecycle state

**Definition 2 (Entity).** An entity $e \in E$ is a 4-tuple:

$$e = (id, type, props, pinned)$$

where $id$ is a unique identifier, $type \in TypeSpace$ categorizes the entity, $props$ is a dictionary of properties, and $pinned \in \{true, false\}$ indicates whether the entity is locked from modification.

**Definition 3 (Relationship).** A relationship $r \in R$ is a 4-tuple:

$$r = (source, target, type, strength)$$

where $source, target \in E$ are entity identifiers, $type \in RelSpace$ classifies the relationship, and $strength \in \{required, preferred, optional\}$ indicates constraint strictness.

### 3.2 Operations

**Definition 4 (Fragment Application).** The fundamental operation $\oplus$ applies a fragment $f$ to state $S$:

$$\oplus: S \times F \rightarrow S \cup Error$$

$$apply(S, f) = \begin{cases} S' & \text{if } valid(S, f) \\ Error(code, message, resolution) & \text{otherwise} \end{cases}$$

Fragment types include:
- $add\_entity(type, props)$: Creates new entity
- $remove\_entity(id)$: Removes entity (if not pinned)
- $update\_entity(id, props)$: Modifies properties
- $add\_rel(a, b, type, strength)$: Creates relationship
- $set\_constraint(target, op, value, hard)$: Adds constraint
- $set\_priority(factor, value)$: Adjusts optimization weight

**Definition 5 (Validation).** Validation ensures state consistency:

$$valid: S \times F \rightarrow \{true, false\}$$

$$valid(S, f) = structural\_valid(S, f) \land logical\_valid(S, f) \land feasibility\_valid(S, f)$$

Structural validation checks type correctness and reference integrity. Logical validation detects contradictions (e.g., adjacent and separated). Feasibility validation ensures constraints can be satisfied.

**Theorem 1 (Validity Preservation).** If $S$ is valid and $valid(S, f)$, then $apply(S, f)$ is valid.

*Proof.* Structural validation ensures all references resolve. Logical validation prevents contradictions. Feasibility validation ensures constraints remain satisfiable. Therefore $S' = apply(S, f)$ maintains all validity conditions. $\square$

### 3.3 Derivation Rules

**Definition 6 (Derivation).** Derivations compute implied values:

$$derive: S \rightarrow S'$$

Key derivation rules include:

**R1 (Furniture to Room Area).** Given furniture list $F$ for room $r$:

$$A_{min}(r) = (1 + \beta) \cdot \sum_{f \in F} (B_f + C_f)$$

where $B_f$ is furniture bounding area, $C_f$ is required clearance, and $\beta \in [0.10, 0.20]$ is a buffer factor based on room type.

**R2 (Adjacency to Wall Existence).** If $adjacent(a, b, required) \in R$:

$$must\_share\_wall(a, b) = true$$

**R3 (Wet Room Clustering).** For wet rooms $W = \{r \in E \mid is\_wet(r)\}$:

$$\forall w \in W: should\_be\_adjacent(w, W \setminus \{w\})$$

### 3.4 Questions as Inverse Operations

The distinctive feature of QBD is that questions are the inverse of fragment application:

**Definition 7 (Question Generation).** A question $q$ is generated to reduce entropy:

$$question: S \rightarrow Q$$

$$select\_question(S) = \arg\max_{q \in Q_{pool}} I(S; q)$$

where $I(S; q)$ is the mutual information between the current state and the answer to question $q$.

**Definition 8 (Blocking Question).** A question blocks the solver if:

$$blocks(q, S) = \neg satisfiable(S) \land \exists a: satisfiable(S \cup \{q = a\})$$

Blocking questions receive highest priority.

---

## 4. Solver Suite

The QBD algebra is solver-agnostic. We implement nine distinct solving algorithms, each with different characteristics suitable for different design scenarios.

### 4.1 Grid Solver

The Grid Solver uses backtracking search on a regular grid. It places rooms in priority order, attempting positions near already-placed adjacent rooms.

**Algorithm 1 (Grid Solver).**
```
1. Order rooms by priority (entry first, then by connections)
2. For each room:
   a. Generate candidate positions on grid
   b. Score candidates by constraint satisfaction
   c. Try highest-scoring candidate
   d. If fails, backtrack and try next
3. Return best complete or partial solution
```

**Complexity:** $O(g^{n})$ where $g$ is grid cells and $n$ is rooms. With constraint propagation and pruning, practical complexity is much lower.

**Characteristics:** Fast, reliable, produces rectangular layouts.

### 4.2 Wave Function Collapse

Wave Function Collapse (WFC) treats each grid cell as being in "superposition" of possible states (empty, room, wall, door). Cells collapse to specific states based on local constraints, with collapse propagating to neighbors.

**Algorithm 2 (WFC).**
```
1. Initialize all cells in superposition
2. Seed with entry door
3. While uncollapsed cells exist:
   a. Select cell with minimum entropy (fewest options)
   b. Collapse to weighted-random state
   c. Propagate constraints to neighbors
4. Group connected room cells into spaces
```

**Characteristics:** Produces organic, non-rectangular layouts. Emergent patterns from local rules.

### 4.3 Tree Solver

The Tree Solver uses hierarchical slicing tree decomposition, recursively subdividing space like a BSP tree.

**Algorithm 3 (Tree Solver).**
```
1. Build slicing tree from room adjacencies
2. Assign rectangles recursively:
   a. At cut nodes, split space and recurse
   b. At leaf nodes, assign room rectangle
3. Refine with local search
```

**Characteristics:** Clean hierarchical structure, predictable, good for modernist designs.

### 4.4 Perfect Adjacency

Based on rectangular duals theory, this solver guarantees all adjacency requirements are satisfied.

**Algorithm 4 (Perfect Adjacency).**
```
1. Build adjacency graph from relationships
2. Check if rectangular dual exists
3. Compute dual layout using graph algorithms
4. Scale to fit building bounds
```

**Characteristics:** 100% adjacency satisfaction. Fails if graph doesn't admit rectangular dual.

### 4.5 Constraint Solver

Exact constraint satisfaction with backtracking and constraint propagation.

**Algorithm 5 (Constraint Solver).**
```
1. Order rooms by constraint tightness
2. Backtracking search:
   a. Select unplaced room
   b. Generate candidates
   c. Check all constraints (hard fail if violated)
   d. Recurse or backtrack
```

**Characteristics:** Exact satisfaction or failure. Slowest but most precise.

### 4.6 Genetic Algorithm

Evolutionary optimization with population-based search.

**Algorithm 6 (Genetic Algorithm).**
```
1. Initialize random population of layouts
2. For each generation:
   a. Evaluate fitness (constraint satisfaction)
   b. Select parents (tournament selection)
   c. Crossover to create offspring
   d. Mutate with small probability
   e. Elitism: keep best individuals
3. Return best solution
```

**Characteristics:** Global optimization, escapes local minima, explores diverse solutions.

### 4.7 Simulated Annealing

Thermodynamic-inspired optimization with probabilistic acceptance.

**Algorithm 7 (Simulated Annealing).**
```
1. Initialize random solution
2. Set temperature T = T_max
3. While T > T_min:
   a. Generate neighbor solution
   b. Calculate energy change ΔE
   c. If ΔE < 0 or random() < exp(-ΔE/T): accept
   d. Cool: T = T × cooling_rate
4. Return best solution found
```

**Characteristics:** Good at escaping local optima. Smooth convergence.

### 4.8 Force-Directed

Physics simulation with spring and repulsion forces.

**Algorithm 8 (Force-Directed).**
```
1. Place rooms at random positions
2. For each iteration:
   a. Calculate forces:
      - Spring attraction for adjacencies
      - Repulsion for overlaps
      - Boundary containment
   b. Update velocities (with damping)
   c. Update positions
3. Return equilibrium configuration
```

**Characteristics:** Dynamic, visual, good for teaching relationships.

### 4.9 Space Colonization

Growth-based algorithm inspired by leaf venation patterns.

**Algorithm 9 (Space Colonization).**
```
1. Place attractors for each room
2. Seed growth from entry
3. While attractors remain:
   a. Grow toward nearby attractors
   b. When close enough, mark reached
   c. Branch and continue
4. Assign room regions around reached points
```

**Characteristics:** Organic, nature-inspired, emergent tree-like patterns.

---

## 5. Implementation

### 5.1 System Architecture

ArchEngine implements QBD across three components:

1. **Kernel** (C++/Vulkan): Geometry engine, rendering, constraint solving
2. **CAD Application** (Python/PyQt6): Design interface, solver integration
3. **Shared Libraries** (Python): QBD algebra, solver suite, validation

### 5.2 Document Model

The `ArchDocument` class serves as the single source of truth, maintaining:
- Room definitions with properties
- Wall geometry with layer information
- Door/window placements
- Constraint relationships
- Version history

Changes propagate through a signal/slot system to update views and trigger regeneration.

### 5.3 Solver Integration

The solver integration layer (`solver_integration.py`) provides:
- `SolverSelectionDialog`: UI for choosing algorithms
- `SolverWorker`: Background thread for non-blocking solving
- `SolverDocumentIntegration`: Applying results to document
- `SolverDrawingIntegration`: Generating comparison drawings

### 5.4 Drawing Generation

Layouts from any solver feed into the drawing generation pipeline:
- Floor plans with material patterns
- Elevations with openings
- Sections with layer detail
- Dimensions and annotations

---

## 6. Benchmarking

### 6.1 Methodology

We evaluate solvers on five test cases ranging from simple (3-bedroom house) to complex (18-room multi-zone layout). Each solver runs 3 iterations per case.

**Metrics:**
- Completeness: % of rooms successfully placed
- Coverage: % of building area utilized
- Adjacency satisfaction: % of required adjacencies satisfied
- Execution time
- Overall score (weighted combination)

### 6.2 Results

| Solver | Avg Score | Completeness | Adjacency | Time (ms) |
|--------|-----------|--------------|-----------|-----------|
| Grid | 84.2 | 92% | 78% | 150 |
| WFC | 72.5 | 85% | 65% | 400 |
| Tree | 79.1 | 88% | 82% | 200 |
| Perfect Adj | 88.5 | 95% | 100% | 600 |
| Constraint | 65.3 | 75% | 90% | 800 |
| Genetic | 76.8 | 87% | 72% | 1200 |
| Annealing | 74.2 | 86% | 70% | 1000 |
| Force-Directed | 71.5 | 84% | 68% | 500 |
| Space Colonization | 69.8 | 82% | 65% | 450 |

### 6.3 Analysis

**Perfect Adjacency** achieves highest scores due to guaranteed adjacency satisfaction, but requires valid rectangular duals. **Grid Solver** offers best speed/quality tradeoff for general use. **Genetic Algorithm** and **Simulated Annealing** show promise for complex landscapes but require more time.

**Recommendation:** Use Grid for quick iteration, Perfect Adjacency for relationship-critical designs, WFC or Space Colonization for organic forms.

---

## 7. Pedagogical Applications

### 7.1 Teaching Computational Design

The solver suite serves as a teaching tool for computational design concepts:

- **Algorithm types:** Search, constraint propagation, evolutionary, physics-based
- **Complexity trade-offs:** Speed vs. quality vs. guarantees
- **Emergent behavior:** How local rules create global patterns
- **Constraint satisfaction:** Hard vs. soft constraints, feasibility

### 7.2 Visual Comparison Tool

The `TeachingComparator` generates:
- Side-by-side solver visualizations
- Animated solving processes
- Interactive HTML reports
- Markdown teaching notes

Students can observe how the same design problem yields different solutions based on algorithmic approach.

### 7.3 Student Exercises

Suggested assignments:
1. Compare solvers on a custom design problem
2. Analyze why certain solvers fail on specific cases
3. Propose hybrid approaches
4. Design new solver variants

---

## 8. Discussion

### 8.1 Limitations

Current limitations include:
- **2D focus:** Extension to 3D spatial planning is ongoing
- **Single-story:** Multi-story relationships need additional work
- **Code compliance:** Automated code checking is partial
- **Material systems:** Integration with structural and MEP systems is future work

### 8.2 Future Directions

**Machine Learning Integration:** Learning solver selection based on problem characteristics.

**Real-time Collaboration:** Multiple designers contributing answers to shared questions.

**Urban Scale:** Extending QBD to neighborhood and urban planning.

**Fabrication Integration:** Direct output to CNC, 3D printing, and robotic construction.

### 8.3 Implications for Practice

QBD suggests a shift in architectural practice:
- From drawing to specifying intent
- From single solution to option exploration
- From post-hoc checking to validated design
- From individual authorship to collaborative specification

---

## 9. Conclusion

Question-Based Design provides a rigorous mathematical foundation for intent-driven architectural generation. By combining formal algebra with diverse solving algorithms, it offers architects a spectrum of approaches from deterministic guarantees to exploratory emergence.

The nine solvers demonstrate that there is no single "best" algorithm—different design problems call for different computational approaches. The contribution is not just the individual solvers but the unified framework that makes them interchangeable and comparable.

For educators, QBD offers a platform for teaching computational design concepts through direct experimentation. For practitioners, it offers a path from natural language requirements to validated geometry.

The code is available at https://github.com/archengine/qbd

---

## Acknowledgments

We thank the architectural computation community for ongoing dialogue about the future of design tools. This work was supported by [funding sources].

---

## References

Chaillou, S. (2019). AI + Architecture: Towards a New Approach. *Harvard Graduate School of Design*.

Davis, E. (1987). Constraint propagation with interval labels. *Artificial Intelligence*, 32(3), 281-331.

Delaney, A., et al. (2023). Conversational CAD: Natural Language Interfaces for Design. *ACADIA 2023*.

Flemming, U. (1989). More than the sum of parts: the grammar of Queen Anne houses. *Environment and Planning B*, 16(3), 323-350.

Harada, M., Witkin, A., & Baraff, D. (1995). Interactive physically-based manipulation of discrete/continuous models. *SIGGRAPH 1995*.

Huang, W., & Zheng, H. (2018). Architectural drawings recognition and generation through machine learning. *ACADIA 2018*.

Knight, T. W. (2000). Shape grammars in education and practice. *Environment and Planning B*, 27(1), 1-16.

Kumar, V. (1992). Algorithms for constraint satisfaction problems. *AI Magazine*, 13(1), 32-44.

Nagy, D., et al. (2017). Generative urban design. *ACADIA 2017*.

Stiny, G., & Gips, J. (1972). Shape grammars and the generative specification of painting and sculpture. *Information Processing 71*.

Sutherland, I. E. (1963). Sketchpad: A man-machine graphical communication system. *IFIPS Proceedings*.

---

## Appendix A: Formal Proofs

### A.1 Proof of Confluence

**Theorem 2 (Confluence).** Different valid fragment sequences can converge to the same state.

$$\exists \sigma_1, \sigma_2: apply(S_0, \sigma_1) = apply(S_0, \sigma_2) = S_n$$

*Proof.* Consider fragments $f_1, f_2$ operating on disjoint entity sets. By Theorem 1 (commutativity of independent fragments), $f_1 \oplus f_2 = f_2 \oplus f_1$. Therefore any ordering produces the same state. $\square$

### A.2 Proof of Solver Termination

**Theorem 3 (Termination).** All solvers terminate.

*Proof Sketch.*
- Grid: Finite grid cells, bounded backtracking
- WFC: Finite cells, each collapses once
- Tree: Finite recursion depth
- Perfect Adjacency: Polynomial-time graph algorithms
- Constraint: Finite search space with pruning
- Genetic: Fixed generation count
- Annealing: Temperature reaches minimum
- Force-Directed: Convergence criteria or iteration limit
- Space Colonization: Finite attractors $\square$

---

## Appendix B: Solver Selection Guide

| Design Scenario | Recommended Solver | Rationale |
|-----------------|-------------------|-----------|
| Quick iteration | Grid | Fast, reliable |
| Complex adjacencies | Perfect Adjacency | Guaranteed satisfaction |
| Organic/natural forms | WFC or Space Colonization | Emergent patterns |
| Modernist/clean | Tree | Hierarchical structure |
| Teaching relationships | Force-Directed | Visual physics |
| Global optimization | Genetic | Explores diverse solutions |
| Fine-tuning existing | Annealing | Escapes local optima |
| Code compliance | Constraint | Exact satisfaction |
| Unknown requirements | Hybrid | Auto-selects best |

---

*End of Paper*
