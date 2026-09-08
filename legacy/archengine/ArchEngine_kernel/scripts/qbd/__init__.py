"""QBD Algebra - Question Based Design Formal System.

The mathematical foundation that sits between the LLM and the output schema.
It guarantees consistency, validity, and determinism.

The LLM proposes. The formal system validates and solves.

Usage:
    from qbd import QBDState, Fragment, solve_state

    # Create state
    state = QBDState()

    # Apply fragments from LLM
    result = state.apply_fragment(add_room("Living Room", "living"))
    result = state.apply_fragment(add_room("Kitchen", "kitchen"))
    result = state.apply_fragment(set_adjacency("room-xxx", "room-yyy", "required", "open"))
    result = state.apply_fragment(set_constraint("footprint_max", 150))

    # Solve
    solution = solve_state(state)
    if solution.status == "solved":
        print(solution.layout)
"""

# Core classes
from .state import QBDState, StateLifecycle

# Fragments
from .fragments import (
    Fragment,
    FragmentAction,
    FragmentParser,
    # Fragment factories
    add_room,
    remove_room,
    update_room,
    add_furniture,
    set_adjacency,
    remove_adjacency,
    set_separation,
    set_site,
    set_constraint,
    set_priority,
    set_style,
    pin_room,
    unpin_room,
)

# Templates
from .templates import (
    create_master_template,
    create_room_template,
    create_adjacency_template,
    create_separation_template,
)

# Validation
from .validator import QBDValidator, validate_state

# Derivation
from .deriver import QBDDeriver, derive_values, apply_derived_to_state

# Solver
from .solver import QBDSolver, SolverResult, solve_state

# Questions
from .questions import QuestionGenerator, Question, generate_questions

# Errors
from .errors import (
    QBDError,
    QBDWarning,
    ValidationResult,
    ErrorCode,
    ErrorType,
    error_to_natural_language,
)

# Defaults
from .defaults import (
    ROOM_DEFAULTS,
    FURNITURE_DEFAULTS,
    DOOR_DEFAULTS,
    WINDOW_DEFAULTS,
    BUILDING_DEFAULTS,
    get_room_defaults,
    get_furniture_dimensions,
    sqft_to_sqm,
    sqm_to_sqft,
)

__all__ = [
    # State
    "QBDState",
    "StateLifecycle",

    # Fragments
    "Fragment",
    "FragmentAction",
    "FragmentParser",
    "add_room",
    "remove_room",
    "update_room",
    "add_furniture",
    "set_adjacency",
    "remove_adjacency",
    "set_separation",
    "set_site",
    "set_constraint",
    "set_priority",
    "set_style",
    "pin_room",
    "unpin_room",

    # Templates
    "create_master_template",
    "create_room_template",

    # Validation
    "QBDValidator",
    "validate_state",

    # Derivation
    "QBDDeriver",
    "derive_values",

    # Solver
    "QBDSolver",
    "SolverResult",
    "solve_state",

    # Questions
    "QuestionGenerator",
    "Question",
    "generate_questions",

    # Errors
    "QBDError",
    "QBDWarning",
    "ValidationResult",
    "error_to_natural_language",

    # Defaults
    "ROOM_DEFAULTS",
    "FURNITURE_DEFAULTS",
    "get_room_defaults",
    "get_furniture_dimensions",
    "sqft_to_sqm",
]
