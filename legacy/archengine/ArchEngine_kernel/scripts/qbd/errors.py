"""Error types and responses for QBD Algebra.

Standardized error format for all failure modes.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class ErrorCode(Enum):
    """QBD error codes."""
    INVALID_FRAGMENT = "INVALID_FRAGMENT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    CONTRADICTION = "CONTRADICTION"
    UNSATISFIABLE = "UNSATISFIABLE"
    UNDERDETERMINED = "UNDERDETERMINED"
    SOLVER_FAILED = "SOLVER_FAILED"
    LOCKED_STATE = "LOCKED_STATE"
    UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"
    INVALID_VALUE = "INVALID_VALUE"
    PINNED_ELEMENT = "PINNED_ELEMENT"


class ErrorType(Enum):
    """Error type categories."""
    STRUCTURAL = "structural"
    LOGICAL = "logical"
    FEASIBILITY = "feasibility"
    CONSTRAINT = "constraint"


@dataclass
class ResolutionOption:
    """A possible resolution for an error."""
    action: str
    description: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QBDError:
    """A QBD Algebra error."""
    code: ErrorCode
    error_type: ErrorType
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    fragment_id: Optional[str] = None
    resolution_options: List[ResolutionOption] = field(default_factory=list)
    help_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "code": self.code.value,
            "type": self.error_type.value,
            "message": self.message,
            "details": self.details,
            "fragment_id": self.fragment_id,
            "resolution_options": [
                {"action": r.action, "description": r.description, "params": r.params}
                for r in self.resolution_options
            ],
            "help": self.help_text,
        }


@dataclass
class QBDWarning:
    """A QBD Algebra warning (non-blocking)."""
    warning_type: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.warning_type,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class ValidationResult:
    """Result of validation."""
    valid: bool
    errors: List[QBDError] = field(default_factory=list)
    warnings: List[QBDWarning] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }

    def add_error(self, error: QBDError):
        """Add an error and mark as invalid."""
        self.errors.append(error)
        self.valid = False

    def add_warning(self, warning: QBDWarning):
        """Add a warning (doesn't affect validity)."""
        self.warnings.append(warning)


# =============================================================================
# Error Factories
# =============================================================================

def invalid_fragment_error(
    message: str,
    fragment_id: str = None,
    details: Dict = None
) -> QBDError:
    """Create an invalid fragment error."""
    return QBDError(
        code=ErrorCode.INVALID_FRAGMENT,
        error_type=ErrorType.STRUCTURAL,
        message=message,
        details=details or {},
        fragment_id=fragment_id,
        help_text="Fragment doesn't match expected structure. Check action type and required fields.",
    )


def unknown_reference_error(
    ref_type: str,
    ref_id: str,
    fragment_id: str = None
) -> QBDError:
    """Create an unknown reference error."""
    return QBDError(
        code=ErrorCode.UNKNOWN_REFERENCE,
        error_type=ErrorType.STRUCTURAL,
        message=f"Reference to unknown {ref_type}: {ref_id}",
        details={"reference_type": ref_type, "reference_id": ref_id},
        fragment_id=fragment_id,
        help_text=f"The {ref_type} '{ref_id}' doesn't exist. Check the ID or create the element first.",
    )


def contradiction_error(
    description: str,
    constraint_a: str,
    constraint_b: str,
    resolution_options: List[ResolutionOption] = None
) -> QBDError:
    """Create a contradiction error."""
    return QBDError(
        code=ErrorCode.CONTRADICTION,
        error_type=ErrorType.LOGICAL,
        message=description,
        details={
            "constraint_a": constraint_a,
            "constraint_b": constraint_b,
        },
        resolution_options=resolution_options or [
            ResolutionOption("remove_first", f"Remove: {constraint_a}"),
            ResolutionOption("remove_second", f"Remove: {constraint_b}"),
        ],
        help_text="Two constraints directly conflict. One must be removed.",
    )


def unsatisfiable_error(
    description: str,
    details: Dict[str, Any],
    resolution_options: List[ResolutionOption] = None
) -> QBDError:
    """Create an unsatisfiable constraints error."""
    return QBDError(
        code=ErrorCode.UNSATISFIABLE,
        error_type=ErrorType.FEASIBILITY,
        message=description,
        details=details,
        resolution_options=resolution_options or [],
        help_text="The constraints cannot all be satisfied. Something must give.",
    )


def underdetermined_error(
    description: str,
    missing: List[str]
) -> QBDError:
    """Create an underdetermined error."""
    return QBDError(
        code=ErrorCode.UNDERDETERMINED,
        error_type=ErrorType.CONSTRAINT,
        message=description,
        details={"missing": missing},
        help_text="Not enough information to produce a solution. Provide more details.",
    )


def pinned_element_error(
    element_type: str,
    element_id: str,
    attempted_change: str
) -> QBDError:
    """Create a pinned element error."""
    return QBDError(
        code=ErrorCode.PINNED_ELEMENT,
        error_type=ErrorType.CONSTRAINT,
        message=f"Cannot modify pinned {element_type}: {element_id}",
        details={
            "element_type": element_type,
            "element_id": element_id,
            "attempted_change": attempted_change,
        },
        resolution_options=[
            ResolutionOption("unpin", f"Unpin {element_id} first", {"element_id": element_id}),
        ],
        help_text="This element is pinned and cannot be modified. Unpin it first.",
    )


def locked_state_error() -> QBDError:
    """Create a locked state error."""
    return QBDError(
        code=ErrorCode.LOCKED_STATE,
        error_type=ErrorType.CONSTRAINT,
        message="Design is locked and cannot be modified",
        resolution_options=[
            ResolutionOption("unlock", "Unlock the design to make changes"),
        ],
        help_text="The design has been locked. Unlock it to continue editing.",
    )


# =============================================================================
# LLM Translation Helpers
# =============================================================================

def error_to_natural_language(error: QBDError) -> str:
    """Convert error to natural language for LLM to present.

    This provides suggested phrasing for presenting errors to users.
    """
    if error.code == ErrorCode.CONTRADICTION:
        return (
            f"There's a conflict in your requirements — "
            f"{error.details.get('constraint_a', 'one constraint')} conflicts with "
            f"{error.details.get('constraint_b', 'another')}. Which do you prefer?"
        )

    elif error.code == ErrorCode.UNSATISFIABLE:
        details = error.details
        if "program_required" in details and "footprint_max" in details:
            overage = details.get("overage", 0)
            return (
                f"The rooms you've described add up to about {details['program_required']} m², "
                f"but you set a {details['footprint_max']} m² limit. "
                f"We could either increase the limit, make some rooms smaller, or remove a room. "
                f"What would you like to do?"
            )
        return f"I couldn't make this work: {error.message}"

    elif error.code == ErrorCode.UNDERDETERMINED:
        missing = error.details.get("missing", [])
        if missing:
            return (
                f"I need a bit more information before I can generate a layout. "
                f"Could you tell me about: {', '.join(missing[:2])}?"
            )
        return "I need more information to proceed. Could you provide more details?"

    elif error.code == ErrorCode.UNKNOWN_REFERENCE:
        ref_type = error.details.get("reference_type", "element")
        ref_id = error.details.get("reference_id", "unknown")
        return f"I don't see a {ref_type} called '{ref_id}'. Did you mean something else?"

    elif error.code == ErrorCode.PINNED_ELEMENT:
        element_id = error.details.get("element_id", "this element")
        return (
            f"You've locked {element_id} so I can't change it. "
            f"Would you like me to unlock it first?"
        )

    else:
        return error.message
