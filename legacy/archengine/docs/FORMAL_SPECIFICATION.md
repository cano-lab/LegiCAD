# QBD Algebra: Formal Mathematical Specification

## Version 0.1 — Draft for Review

---

## 1. Introduction

The Question-Based Design (QBD) Algebra is a formal system for transforming human intent into valid geometric designs through a structured dialogue. This document provides the mathematical foundation.

**Core Thesis:** Design is constraint satisfaction. Questions are entropy-reduction operations. The algebra guarantees that any valid sequence of answers produces a buildable, legal, and optimal design.

---

## 2. Primitives

### 2.1 Design State (S)

A design state is a tuple:

```
S = (E, R, C, P, V, L)

Where:
  E: Set of entities
  R: Set of relationships  
  C: Set of constraints
  P: Priority vector
  V: Version identifier
  L: Lifecycle state ∈ {EMPTY, ACCUMULATING, COMPLETE, SOLVED, LOCKED}
```

### 2.2 Entity (e ∈ E)

```
e = (id, type, props, pinned)

Where:
  id: Unique identifier
  type: Entity type ∈ TypeSpace
  props: Dict of properties
  pinned: Boolean (locked from modification)
```

### 2.3 Relationship (r ∈ R)

```
r = (source, target, type, strength)

Where:
  source, target: Entity IDs
  type: Relationship type ∈ RelSpace
  strength: "required" | "preferred" | "optional"
```

### 2.4 Constraint (c ∈ C)

```
c = (target, operator, value, hard)

Where:
  target: Property path (e.g., "entity_id.property")
  operator: ∈ {<, ≤, =, ≥, >, ∈, ∉}
  value: Constraint value
  hard: Boolean (hard vs soft constraint)
```

### 2.5 Priority Vector (P)

```
P = [p₁, p₂, ..., pₙ] where pᵢ ∈ [0, 10]

Standard priorities:
  p₁: natural_light
  p₂: privacy
  p₃: open_plan
  p₄: circulation_efficiency
  p₅: mep_clustering
  p₆: structural_simplicity
```

---

## 3. Operations

### 3.1 Fragment Application (⊕)

The fundamental operation: applying a fragment to a state.

```
⊕: S × F → S ∪ Error

apply(S, f) = S' if valid(S, f)
           = Error(error_code, message, resolution) otherwise
```

**Fragment Types:**

| Fragment | Effect | Validation |
|----------|--------|------------|
| `add_entity(type, props)` | E' = E ∪ {new_entity} | type ∈ TypeSpace |
| `remove_entity(id)` | E' = E \\ {e} | id exists, not pinned |
| `update_entity(id, props)` | props' = props ∪ updates | id exists, not pinned |
| `add_rel(a, b, type, strength)` | R' = R ∪ {(a,b,type,strength)} | a,b ∈ E |
| `remove_rel(a, b)` | R' = R \\ {(a,b,*,*)} | relationship exists |
| `add_constraint(target, op, val, hard)` | C' = C ∪ {c} | target valid |
| `set_priority(factor, value)` | P'[factor] = value | value ∈ [0,10] |
| `pin_entity(id, locked_props)` | pinned' = true | id exists |
| `unpin_entity(id)` | pinned' = false | id exists |

### 3.2 Validation (valid)

```
valid: S × F → Boolean

valid(S, f) = structural_valid(S, f) ∧ 
              logical_valid(S, f) ∧
              feasibility_valid(S, f)
```

**Structural Validation:**
- All references in f resolve to existing entities
- All property values in f are of correct type
- No duplicate IDs created

**Logical Validation:**
- No contradictions introduced (e.g., both adjacency and separation between same pair)
- No self-references (entity related to itself)
- Dependency chains resolve (e.g., ensuite requires parent bedroom)

**Feasibility Validation:**
- Constraint satisfaction possible (not UNSAT)
- Area requirements ≤ available footprint
- All rooms have valid path to entry

### 3.3 Derivation (derive)

```
derive: S → S

derive(S) = S with implied values computed
```

**Derivation Rules:**

| Input | Derivation | Formula |
|-------|------------|---------|
| furniture list | room area | A_min = (1+β) × Σ(bounds + clearances) |
| room type | default relationships | lookup(TypeSpace, type, defaults) |
| adjacency graph | wall existence | edge → shared wall |
| wet rooms | plumbing clustering | group rooms with is_wet=true |
| exterior requirements | window placement | room.exterior=REQUIRED → exterior wall |

### 3.4 Solving (solve)

```
solve: S → Layout ∪ Error

solve(S) = Layout if satisfiable(S)
        = Error(UNSATISFIABLE, diagnosis) otherwise
```

**Solver Stages:**

1. **Constraint Propagation**
   ```
   propagate: S → S'
   
   Eliminates impossible configurations:
   - If separate(A,B) required → A and B cannot share edge
   - If room.area > X → room cannot fit in small corners
   - If window.east required → room must be on east side
   ```

2. **Search**
   ```
   search: S' → {Layout}
   
   Generates candidate layouts:
   - Grid-based placement (snap to grid)
   - Constraint satisfaction (backtracking)
   - Wave Function Collapse (tile-based)
   - Rectangular duals (graph to rectangles)
   ```

3. **Optimization**
   ```
   optimize: {Layout} × P → Layout
   
   Scores candidates:
   score(L, P) = Σᵢ P[i] × satisfaction(L, factorᵢ)
   
   Returns highest scoring layout
   ```

### 3.5 Scoring (score)

```
score: Layout × P → [0, 1]

score(L, P) = Σᵢ (P[i]/ΣP) × satᵢ(L)

Where satᵢ(L) ∈ [0,1] is satisfaction of priority i
```

**Satisfaction Functions:**

| Priority | Satisfaction Metric |
|----------|---------------------|
| natural_light | % of window preferences satisfied |
| privacy | distance from public zones to private zones |
| open_plan | ratio of open connections to total connections |
| circulation_efficiency | 1 - (hallway_area / total_area) |
| mep_clustering | 1 - (plumbing_wall_length / total_wall_length) |
| structural_simplicity | % of walls vertically aligned (multi-story) |

---

## 4. Algebraic Properties

### 4.1 Associativity of Fragment Sequences

**Theorem 1:** Fragment application is not generally associative.

```
(f₁ ⊕ f₂) ⊕ f₃ ≠ f₁ ⊕ (f₂ ⊕ f₃) in general
```

**Proof:**
- Let f₁ = add_entity(A), f₂ = add_rel(A,B), f₃ = remove_entity(A)
- (f₁ ⊕ f₂) ⊕ f₃: Add A, add relation A-B, remove A → relation orphaned
- f₁ ⊕ (f₂ ⊕ f₃): f₂ fails (B doesn't exist), so f₃ never applied

**However:** Fragments on independent entities are associative.

### 4.2 Commutativity

**Theorem 2:** Fragments are commutative if they operate on disjoint entity sets.

```
If entities(f₁) ∩ entities(f₂) = ∅:
  apply(apply(S, f₁), f₂) = apply(apply(S, f₂), f₁)
```

**Proof:** Direct from independence — no shared state means order doesn't matter.

### 4.3 Idempotence

**Theorem 3:** No fragment is idempotent except `pin_entity` on already-pinned entity.

```
apply(S, f) ≠ apply(apply(S, f), f) for most f
```

**Counter-example:**
- `add_entity(A)` twice creates two entities (different IDs)
- `update_entity(A, {x: 5})` twice is same result but not idempotent by definition

### 4.4 Confluence

**Theorem 4:** Different valid fragment sequences can converge to the same state.

```
∃ sequences σ₁, σ₂: apply(S₀, σ₁) = apply(S₀, σ₂) = Sₙ
```

**Example:**
- σ₁: add_room(A), add_room(B), add_rel(A,B)
- σ₂: add_room(B), add_room(A), add_rel(A,B)
- Both produce same final state

### 4.5 Completeness

**Theorem 5:** The algebra is complete for the design space — any valid design can be reached.

```
∀ valid designs D: ∃ sequence σ: apply(S_EMPTY, σ) = S_D
```

**Proof Sketch:**
- Any design has finite entities and relationships
- Each can be added via `add_entity` and `add_rel`
- Properties set via `update_entity`
- Therefore any design is constructible

---

## 5. Question Generation as Inverse Operation

### 5.1 Information-Theoretic Question Selection

```
question: S → Q

select_question(S) = argmax_{q ∈ Q_pool} I(S; q)

Where I(S; q) is mutual information between state and answer
```

**Entropy Reduction:**

```
H(S) = entropy over possible designs consistent with S

H(S | q=a) = entropy after observing answer a to question q

Expected reduction: E[H(S) - H(S | q)] over possible answers
```

### 5.2 Question Types by Entropy Impact

| Question Type | Typical Entropy Reduction | When Asked |
|---------------|---------------------------|------------|
| Building type (residential/commercial) | High (determines room types) | Early (EMPTY) |
| Room count | High (determines graph size) | Early (EMPTY) |
| Specific room size | Medium (constrains solver) | Mid (ACCUMULATING) |
| Style preference | Low-Medium (affects scoring) | Late (ACCUMULATING) |
| Detail (outlet placement) | Low (doesn't affect topology) | Very late (COMPLETE) |

### 5.3 Blocking Questions

A question **blocks** the solver if:

```
blocks(q, S) = ¬satisfiable(S) ∧ satisfiable(S ∪ {q=a}) for some a
```

**Priority:** Blocking questions always have highest priority.

---

## 6. Conflict Resolution

### 6.1 Conflict Types

| Type | Definition | Resolution |
|------|------------|------------|
| **Contradiction** | C contains (a,b,adjacent) and (a,b,separate) | User must remove one |
| **Unsatisfiable** | No layout satisfies all hard constraints | Relax constraints or remove entities |
| **Underdetermined** | Multiple layouts satisfy constraints equally | Ask clarifying question |
| **Tradeoff** | Multiple layouts, different priority satisfaction | Present options with scores |

### 6.2 Surgical Reduction

When UNSATISFIABLE, generate resolution options:

```
reduce(S) = {S' : satisfiable(S') ∧ minimal_distance(S, S')}

Where distance is number of changes required
```

**Options generated:**
1. Increase footprint limit
2. Reduce room sizes proportionally
3. Remove lowest-priority room
4. Split into multiple buildings

---

## 7. Version Control

### 7.1 State as Version Graph

```
V = (S, parent, branch, timestamp)

Versions form a DAG:
  V₀ (root)
   ├── V₁ ── V₂ ── V₃ (main branch)
   └── V₁' ── V₂' (exploration branch)
```

### 7.2 Operations

| Operation | Effect |
|-----------|--------|
| `fork(V)` | Create new branch from V |
| `merge(V₁, V₂)` | Combine changes from two branches |
| `lock(V)` | Mark V as immutable (construction documents) |
| `unlock(V)` | Create V' = copy(V) for editing |

### 7.3 Diff and Merge

```
diff(V₁, V₂) = minimal fragment sequence σ: apply(V₁, σ) = V₂

merge(V₁, V₂, V_base) = V₁ ∪ V₂ - conflicts
```

---

## 8. Domain Generalization

### 8.1 Core Algebra (Domain-Independent)

```
Core = (Entity, Relationship, Constraint, Priority, Solver)
```

### 8.2 Domain Schema (Domain-Specific)

```
Schema = (TypeSpace, RelSpace, DerivationRules, Defaults, ValidationRules)
```

### 8.3 Domain Instances

| Domain | TypeSpace Examples | RelSpace Examples |
|--------|-------------------|-------------------|
| Architecture | room, wall, door, window | adjacent, opens_to, separates |
| Product Design | component, assembly, part | mounts_to, connects_to, clears |
| Urban Planning | zone, block, parcel | borders, serves, accesses |
| Exhibition Design | booth, aisle, display | views, flows_to, adjacent |

---

## 9. Proofs

### 9.1 Proof: Solver Termination

**Theorem:** The solver always terminates.

**Proof:**
1. Search space is finite (grid size × max rooms)
2. Each candidate layout is checked once
3. Optimization scores and sorts finite set
4. Therefore terminates in O(|candidates| × |scoring|)

### 9.2 Proof: Validity Preservation

**Theorem:** If S is valid and valid(S, f), then apply(S, f) is valid.

**Proof:**
- Structural validation ensures all references resolve
- Logical validation ensures no contradictions
- Feasibility validation ensures constraints satisfiable
- Therefore S' = apply(S, f) maintains all validity conditions

### 9.3 Proof: Question Progress

**Theorem:** Each blocking question reduces the solution space.

**Proof:**
- Blocking question q has |answers| ≥ 2
- Each answer aᵢ constrains S to Sᵢ ⊂ S
- Therefore |solutions(S)| > |solutions(Sᵢ)| for all i
- Solution space strictly decreases

---

## 10. Implementation Notes

### 10.1 Data Structures

```python
# State representation
@dataclass
class State:
    entities: Dict[ID, Entity]
    relationships: Set[Relationship]
    constraints: Set[Constraint]
    priorities: PriorityVector
    version: VersionID
    lifecycle: LifecycleState

# Fragment representation  
@dataclass
class Fragment:
    action: ActionType
    target: Optional[ID]
    properties: Dict[str, Any]
    timestamp: datetime
```

### 10.2 Validation Pipeline

```python
def validate(state: State, fragment: Fragment) -> Result:
    # Stage 1: Structural
    if not structural_valid(state, fragment):
        return Error(STRUCTURAL, details)
    
    # Stage 2: Logical
    if not logical_valid(state, fragment):
        return Error(LOGICAL, details)
    
    # Stage 3: Feasibility (expensive, run last)
    if not feasibility_valid(state, fragment):
        return Error(FEASIBILITY, details)
    
    return OK
```

### 10.3 Solver Pipeline

```python
def solve(state: State) -> Result[Layout, Error]:
    # Stage 1: Propagation
    state = propagate(state)
    
    # Stage 2: Search
    candidates = search(state)
    if not candidates:
        return Error(UNSATISFIABLE, diagnose(state))
    
    # Stage 3: Optimization
    best = optimize(candidates, state.priorities)
    
    return OK(best)
```

---

## 11. Future Work

### 11.1 Inverse Design

Given target layout L, find fragment sequence σ:

```
inverse: Layout → {σ : apply(S_EMPTY, σ) = L}
```

### 11.2 Probabilistic Constraints

Soft constraints with probability distributions:

```
c = (target, op, value, confidence)

P(constraint satisfied) = confidence
```

### 11.3 Multi-Objective Optimization

Pareto frontier for conflicting priorities:

```
pareto: {Layout} × P → {Layout}

Returns layouts where no priority can improve without hurting another
```

### 11.4 Machine Learning Integration

Learn from design corpus:

```
learn: {Design} → ImprovedPriorities

Adjusts default priorities based on successful designs
```

---

## 12. References

1. QBD Algebra v2.0 Specification (Shared/Docs/QBD_ALGEBRA.md)
2. QBD Algebra v2.1 Specification (Shared/Docs/QBD_Algebra_2.md)
3. QBD Format v2.1 (Shared/Specs/QBD_Format_v2.1.md)
4. Constraint Satisfaction Problems (Dechter, 2003)
5. Wave Function Collapse (Gumin, 2016)
6. Rectangular Duals (Kant & He, 1997)

---

## Appendix A: Formal Grammar

### A.1 State Grammar

```
State ::= "{" Entities "," Relationships "," Constraints "," Priorities "," Version "," Lifecycle "}"

Entities ::= "\"entities\"" ":" "{" Entity* "}"
Entity ::= ID ":" "{" Type "," Props "," Pinned "}"

Relationships ::= "\"relationships\"" ":" "[" Relationship* "]"
Relationship ::= "{" Source "," Target "," RelType "," Strength "}"

Constraints ::= "\"constraints\"" ":" "[" Constraint* "]"
Constraint ::= "{" Target "," Operator "," Value "," Hard "}"

Priorities ::= "\"priorities\"" ":" "{" Priority* "}"
Priority ::= Factor ":" Number

Version ::= "\"version\"" ":" VersionID
Lifecycle ::= "\"lifecycle\"" ":" ("EMPTY" | "ACCUMULATING" | "COMPLETE" | "SOLVED" | "LOCKED")
```

### A.2 Fragment Grammar

```
Fragment ::= AddEntity | RemoveEntity | UpdateEntity |
             AddRel | RemoveRel |
             AddConstraint | SetPriority |
             PinEntity | UnpinEntity

AddEntity ::= "{" "\"action\"" ":" "\"add_entity\"" "," Type "," Props "}"
RemoveEntity ::= "{" "\"action\"" ":" "\"remove_entity\"" "," ID "}"
UpdateEntity ::= "{" "\"action\"" ":" "\"update_entity\"" "," ID "," Props "}"

AddRel ::= "{" "\"action\"" ":" "\"add_rel\"" "," Source "," Target "," RelType "," Strength "}"
RemoveRel ::= "{" "\"action\"" ":" "\"remove_rel\"" "," Source "," Target "}"
```

---

*Document Status: Draft v0.1*
*Last Updated: 2026-02-24*
*Author: ArchEngine Team*
