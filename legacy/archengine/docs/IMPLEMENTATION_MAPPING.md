# QBD Algebra: Implementation Mapping

This document maps the formal algebra concepts to their implementations in the ArchEngine codebase.

---

## 1. State Representation

### 1.1 Design State (S = E, R, C, P, V, L)

| Algebra Component | Implementation | File |
|-------------------|----------------|------|
| Entities (E) | `SpatialGraph.rooms` | `render_server/room_relationships.py` |
| Relationships (R) | `SpatialGraph.adjacencies`, `.separations` | `render_server/room_relationships.py` |
| Constraints (C) | `Room.min_area`, `Room.max_area`, `Room.aspect_ratio` | `render_server/room_relationships.py` |
| Priorities (P) | `SpatialGraph.priorities` | `render_server/qbd_layout_generator.py` |
| Version (V) | `format_version`, `edit_history` | `Shared/Specs/QBD_Format_v2.1.md` |
| Lifecycle (L) | `InterviewPhase` enum | `render_server/qbd_interview.py` |

### 1.2 Entity (e)

**Algebra:**
```
e = (id, type, props, pinned)
```

**Implementation:**
```python
# render_server/room_relationships.py
@dataclass
class Room:
    id: str
    name: str
    type: str  # maps to RoomTypeSpec
    min_area: float
    max_area: float
    aspect_ratio: Dict[str, float]
    # pinned equivalent: constraints.locked_properties
```

### 1.3 Relationship (r)

**Algebra:**
```
r = (source, target, type, strength)
```

**Implementation:**
```python
# render_server/room_relationships.py
class SpatialGraph:
    def connect(self, room_a, room_b, opening_type=OpeningType.DOOR):
        # Creates CONNECTS_TO relationship
        
    def open_to(self, room_a, room_b):
        # Creates OPEN_TO relationship
        
    def isolate(self, room_a, room_b):
        # Creates ISOLATED_FROM relationship
        
    def group(self, *rooms):
        # Creates GROUPED_WITH relationship
```

---

## 2. Operations

### 2.1 Fragment Application (⊕)

**Algebra:**
```
apply: S × F → S ∪ Error
```

**Implementation:**
```python
# render_server/qbd_interview.py
class QBDInterview:
    def process_input(self, user_input: str) -> str:
        # 1. Parse natural language to structured data
        # 2. Create DesignRequirements
        # 3. Convert to QBD answers
        # 4. Generate layout (calls solve)
```

**Fragment Translation:**

| Algebra Fragment | Implementation Path |
|------------------|---------------------|
| `add_entity` | `SpatialGraph.add_room()` → creates Room |
| `remove_entity` | `SpatialGraph.remove_room()` (not implemented) |
| `update_entity` | Direct property assignment on Room |
| `add_rel` | `SpatialGraph.connect()`, `.open_to()`, `.isolate()` |
| `add_constraint` | Room property assignment (min_area, etc.) |
| `set_priority` | `SpatialGraph.priorities` dict update |

### 2.2 Validation

**Algebra:**
```
valid: S × F → Boolean
```

**Implementation:**
```python
# render_server/room_relationships.py
class SpatialGraph:
    def validate(self) -> List[str]:
        # Structural validation
        # Logical validation
        # Returns list of issues

# Validation rules implemented:
# - All referenced rooms exist
# - No duplicate room IDs
# - No self-references
# - Dependencies resolved (ensuite has parent bedroom)
```

**Feasibility Validation:**
```python
# render_server/qbd_layout_generator.py
def generate_floor_plan_from_qbd(answers, ...):
    # Check: sum(room_min_areas) <= footprint_max
    # Check: rooms fit in dimensions
    # Returns error if unsatisfiable
```

### 2.3 Derivation

**Algebra:**
```
derive: S → S
```

**Implementation:**
```python
# render_server/qbd_layout_generator.py
def create_spatial_graph_from_qbd(answers: Dict) -> SpatialGraph:
    # Derives room sizes from furniture
    # Derives relationships from room types
    # Derives wet room clustering
    # Derives default connections
```

**Specific Derivations:**

| Derivation | Implementation | Formula Location |
|------------|----------------|------------------|
| Furniture → Room Area | `create_spatial_graph_from_qbd()` | Lines ~85-120 |
| Room Type → Defaults | `ROOM_TYPES` dict | `room_relationships.py` |
| Wet Rooms → Grouping | `graph.group(*wet_rooms)` | `qbd_layout_generator.py` ~line 180 |
| Exterior Req → Window Placement | `rooms_needing_windows` | `qbd_layout_generator.py` ~line 520 |

### 2.4 Solving

**Algebra:**
```
solve: S → Layout ∪ Error
```

**Implementation:**
```python
# render_server/coordinate_solver.py
def solve_layout(
    graph: SpatialGraph,
    width: float,
    depth: float,
    grid_size: float = 2.0,
    max_nodes: int = 50000,
    creative_mode: bool = False
) -> PlacedLayout:
    # Stage 1: Constraint propagation (implicit)
    # Stage 2: Search (grid-based placement)
    # Stage 3: Optimization (scoring)
```

**Solver Algorithm:**
```python
# From coordinate_solver.py (inferred from usage)
# 1. Convert SpatialGraph to layout spec
# 2. Grid-based search for room placements
# 3. Wall generation from room boundaries
# 4. Door/window placement
# 5. Score and return best layout
```

### 2.5 Scoring

**Algebra:**
```
score: Layout × P → [0, 1]
```

**Implementation:**
```python
# render_server/coordinate_solver.py (inferred)
# PlacedLayout has score attribute

# Scoring factors (from QBD docs):
# - natural_light: window preference satisfaction
# - privacy: distance from public zones
# - open_plan: ratio of open connections
# - circulation_efficiency: hallway minimization
# - mep_clustering: wet room grouping
```

---

## 3. Question Generation

### 3.1 Interview State Machine

**Algebra:**
```
question: S → Q
```

**Implementation:**
```python
# render_server/qbd_interview.py
class InterviewPhase(Enum):
    GREETING = "greeting"
    BUILDING_TYPE = "building_type"
    SIZE_SCOPE = "size_scope"
    ROOM_REQUIREMENTS = "room_requirements"
    SPECIAL_FEATURES = "special_features"
    STYLE_PREFERENCES = "style_preferences"
    REVIEW = "review"
    GENERATING = "generating"
    COMPLETE = "complete"

class QBDInterview:
    def process_input(self, user_input: str) -> str:
        # Routes to handler based on current phase
        handlers = {
            InterviewPhase.GREETING: self._handle_greeting,
            InterviewPhase.BUILDING_TYPE: self._handle_building_type,
            # ... etc
        }
```

**Note:** Current implementation uses fixed phases. For true entropy-driven questions, see Section 5.

### 3.2 Answer Parsing

**Implementation:**
```python
# render_server/qbd_interview.py
class AnswerParser:
    # Pattern-based extraction
    @classmethod
    def parse_number(cls, text: str) -> Optional[int]
    
    @classmethod
    def parse_sqft(cls, text: str) -> Optional[int]
    
    @classmethod
    def parse_building_type(cls, text: str) -> Optional[str]
    
    @classmethod
    def parse_special_rooms(cls, text: str) -> List[str]
    # ... etc
```

---

## 4. Output Generation

### 4.1 Layout to Geometry

**Algebra:**
```
render: Layout × Type → Drawing
```

**Implementation:**
```python
# render_server/qbd_layout_generator.py
def layout_to_walls(layout: PlacedLayout, output_format: OutputFormat) -> List[Dict]
def layout_to_doors(layout: PlacedLayout, output_format: OutputFormat) -> List[Dict]
def layout_to_windows(layout: PlacedLayout, walls_batch: List[Dict], ...) -> List[Dict]
def layout_to_rooms_data(layout: PlacedLayout, ...) -> Dict[str, Dict]
def layout_to_dimensions(layout: PlacedLayout, ...) -> List[Dict]
```

### 4.2 Drawing Generation (Sheets)

**Implementation:**
```python
# ArchEngine_CAD/generators/generator_service.py
class GeneratorService:
    def generate_sheet(self, sheet_id: str) -> bool
    def generate_all(self)  # All enabled sheets
    
# Sheet types mapped to generators:
# SheetType.FLOOR_PLAN → floor plan renderer
# SheetType.SECTION_A → section_renderer.py
# SheetType.ELEVATION_NORTH → elevation_renderer.py
# SheetType.DETAILS → detail_renderer.py
```

**SVG Generation:**
```python
# ArchEngine_kernel/scripts/sheets/generators/
section_renderer.py    # render_section() - LOD-based rendering
elevation_renderer.py  # render_elevation() - facade rendering
detail_renderer.py     # Construction details
```

---

## 5. Gap Analysis: Formal vs Implementation

### 5.1 Fully Implemented

| Feature | Status | Location |
|---------|--------|----------|
| Fragment application | ✅ | `qbd_interview.py`, `room_relationships.py` |
| Structural validation | ✅ | `SpatialGraph.validate()` |
| Derivation rules | ✅ | `create_spatial_graph_from_qbd()` |
| Grid-based solver | ✅ | `coordinate_solver.py` |
| Output generation | ✅ | `qbd_layout_generator.py` |
| Sheet generation | ✅ | `generators/` folder |
| Fixed-phase interview | ✅ | `qbd_interview.py` |

### 5.2 Partially Implemented

| Feature | Status | Gap | Location |
|---------|--------|-----|----------|
| Logical validation | ⚠️ | No contradiction detection | `room_relationships.py` |
| Feasibility validation | ⚠️ | Basic only (area sum) | `qbd_layout_generator.py` |
| Constraint propagation | ⚠️ | Implicit, not explicit | `coordinate_solver.py` |
| Scoring | ⚠️ | Score exists, breakdown partial | `PlacedLayout` |
| Version control | ⚠️ | Format spec exists, code pending | `QBD_Format_v2.1.md` |

### 5.3 Not Yet Implemented

| Feature | Status | Priority |
|---------|--------|----------|
| Entropy-driven questions | ❌ | High |
| Wave Function Collapse solver | ❌ | Medium |
| Rectangular duals | ❌ | Medium |
| Inverse design | ❌ | Low |
| Probabilistic constraints | ❌ | Low |
| Pareto optimization | ❌ | Low |
| ML-learned priorities | ❌ | Research |

---

## 6. Recommended Implementation Path

### Phase 1: Validation Enhancement
```python
# Add to room_relationships.py
class SpatialGraph:
    def detect_contradictions(self) -> List[Contradiction]:
        # Check for adjacent + separate between same pair
        # Check for circular dependencies
        # Check for unsatisfiable constraints
        
    def propagate_constraints(self) -> 'SpatialGraph':
        # Explicit constraint propagation
        # Reduce search space before solving
```

### Phase 2: Entropy-Driven Questions
```python
# New file: render_server/question_generator.py
class QuestionGenerator:
    def generate_questions(self, state: SpatialGraph, n: int = 5) -> List[Question]:
        # Calculate entropy reduction for each possible question
        # Return top n questions
        
    def calculate_entropy(self, state: SpatialGraph) -> float:
        # Measure uncertainty in current state
        # Based on: underspecified rooms, unconstrained relationships
```

### Phase 3: Enhanced Solver
```python
# Enhance coordinate_solver.py
def solve_layout_wfc(graph: SpatialGraph, ...) -> PlacedLayout:
    # Wave Function Collapse implementation
    # Better for non-rectangular shapes
    
def solve_layout_rectangular_duals(graph: SpatialGraph, ...) -> PlacedLayout:
    # Graph-to-rectangles algorithm
    # Guarantees adjacency requirements
```

### Phase 4: Version Control
```python
# New file: core/version_control.py
class VersionGraph:
    def fork(self, version_id: str) -> str:
    def merge(self, v1: str, v2: str) -> str:
    def lock(self, version_id: str):
    def diff(self, v1: str, v2: str) -> List[Fragment]:
```

---

## 7. Testing the Algebra

### 7.1 Property-Based Tests

```python
# tests/test_algebra_properties.py

def test_commutativity_independent_fragments():
    """Fragments on different entities commute."""
    s0 = empty_state()
    f1 = add_entity("room", {"name": "A"})
    f2 = add_entity("room", {"name": "B"})
    
    s_ab = apply(apply(s0, f1), f2)
    s_ba = apply(apply(s0, f2), f1)
    
    assert equivalent(s_ab, s_ba)

def test_validity_preservation():
    """Valid fragments preserve validity."""
    s = valid_state()
    f = random_valid_fragment(s)
    s_prime = apply(s, f)
    
    assert is_valid(s_prime)

def test_solver_termination():
    """Solver always terminates."""
    s = random_state()
    result = solve(s)
    
    assert result is not None  # Either layout or error
```

### 7.2 Integration Tests

```python
# tests/test_end_to_end.py

def test_full_design_workflow():
    """Complete workflow from questions to drawings."""
    interview = QBDInterview()
    
    # Simulate conversation
    interview.process_input("3 bedroom house")
    interview.process_input("2 bathrooms")
    interview.process_input("2000 sqft")
    interview.process_input("2 car garage")
    interview.process_input("modern style")
    
    # Generate
    result = interview._generate_design()
    
    assert result["success"]
    assert result["walls_batch"]
    assert result["rooms"]
```

---

## 8. File Organization

```
ArchEngine/
├── FORMAL_SPECIFICATION.md          # This document
├── IMPLEMENTATION_MAPPING.md        # This document
├── ArchEngine_CAD/
│   ├── generators/
│   │   ├── generator_service.py     # Sheet generation orchestration
│   │   └── generator_adapters.py    # Format adapters
│   └── sheets/
│       ├── models.py                # Sheet data models
│       └── sheet_registry.py        # Sheet management
├── ArchEngine_kernel/
│   ├── render_server/
│   │   ├── qbd_interview.py         # Interview state machine
│   │   ├── qbd_layout_generator.py  # Layout generation
│   │   ├── qbd_session.py           # Session management
│   │   ├── room_relationships.py    # Spatial graph
│   │   ├── coordinate_solver.py     # Geometric solver
│   │   └── generators/              # Drawing generators
│   │       ├── section_renderer.py
│   │       ├── elevation_renderer.py
│   │       └── detail_renderer.py
│   └── scripts/sheets/
│       ├── svg_builder.py           # SVG construction
│       └── lod_layers.py            # Level-of-detail
└── Shared/
    ├── Docs/
    │   ├── QBD_ALGEBRA.md           # Original algebra docs
    │   └── QBD_Algebra_2.md         # Updated algebra docs
    └── Specs/
        └── QBD_Format_v2.1.md       # JSON format spec
```

---

## 9. Next Steps

1. **Review Formal Specification** — Check mathematical correctness
2. **Prioritize Gaps** — Which unimplemented features matter most?
3. **Enhance Validation** — Add contradiction detection
4. **Implement Entropy Questions** — Replace fixed-phase interview
5. **Add Property Tests** — Verify algebraic properties
6. **Document Domain Extension** — How to apply to other domains

---

*Document Status: Draft v0.1*
*Last Updated: 2026-02-24*
