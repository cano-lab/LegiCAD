"""
Smart Panel System - Context-aware panel visibility.

Panels emerge from context. They appear when relevant, fade when not.
No manual show/hide. The interface emerges from the state.

Based on SMART_PANEL_SPEC.md
"""
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import List, Dict, Optional, Set, Callable, Any, Tuple
import time

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal, QPoint
from PyQt6.QtGui import QColor


# =============================================================================
# Enums
# =============================================================================

class WorkflowStage(Enum):
    """Application workflow stages."""
    LEGI_QBD = 'legi_qbd'    # Topology/blob manipulation
    LEGI_CAD = 'legi_cad'    # Wall/fixture editing
    LEGI_DOC = 'legi_doc'    # Documentation/viewports


class SchemaState(Enum):
    """Schema completeness states."""
    EMPTY = 'empty'
    ACCUMULATING = 'accumulating'
    COMPLETE = 'complete'
    SOLVED = 'solved'
    LOCKED = 'locked'


class TaskType(Enum):
    """Active task types."""
    IDLE = 'idle'
    DRAGGING_BLOB = 'dragging_blob'
    DRAGGING_WALL = 'dragging_wall'
    DRAGGING_OPENING = 'dragging_opening'
    DRAGGING_FIXTURE = 'dragging_fixture'
    EDITING_TEXT = 'editing_text'
    PLACING_VIEWPORT = 'placing_viewport'
    MEASURING = 'measuring'
    CHATTING = 'chatting'


class ElementType(Enum):
    """Building element types."""
    BLOB = 'blob'
    RELATIONSHIP = 'relationship'
    WALL = 'wall'
    DOOR = 'door'
    WINDOW = 'window'
    ROOM = 'room'
    FIXTURE = 'fixture'
    FURNITURE = 'furniture'
    CONTROL_POINT = 'control_point'
    COORDINATE_MARKER = 'coordinate_marker'
    VIEWPORT = 'viewport'
    ANNOTATION = 'annotation'


class LODLevel(IntEnum):
    """LOD levels."""
    TOPOLOGY = 1
    WALLS = 2
    FIXTURES = 3
    VIEWPORTS = 4
    DOCUMENTATION = 5


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class GravityState:
    """Current gravity weights."""
    design: float = 0.33
    client: float = 0.33
    build: float = 0.34


@dataclass
class LODState:
    """Current LOD state."""
    level: int = 2
    transition_to: Optional[int] = None
    transition_progress: float = 0.0


@dataclass
class Selection:
    """Current selection state."""
    element_ids: List[str] = field(default_factory=list)
    element_types: List[ElementType] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.element_ids)

    @property
    def has_selection(self) -> bool:
        return self.count > 0


@dataclass
class PanelContext:
    """Context for evaluating panel visibility."""
    workflow_stage: WorkflowStage = WorkflowStage.LEGI_CAD
    lod: LODState = field(default_factory=LODState)
    gravity: GravityState = field(default_factory=GravityState)
    selection: Selection = field(default_factory=Selection)
    schema_state: SchemaState = SchemaState.ACCUMULATING
    active_task: TaskType = TaskType.IDLE


@dataclass
class GravityCondition:
    """Gravity thresholds for panel visibility."""
    design_min: Optional[float] = None
    design_max: Optional[float] = None
    client_min: Optional[float] = None
    client_max: Optional[float] = None
    build_min: Optional[float] = None
    build_max: Optional[float] = None


@dataclass
class SelectionCondition:
    """Selection requirements for panel visibility."""
    required: bool = False
    element_types: Optional[List[ElementType]] = None
    min_count: Optional[int] = None
    max_count: Optional[int] = None


@dataclass
class StateCondition:
    """Schema state requirements."""
    schema_states: Optional[List[SchemaState]] = None
    requires_unsaved_changes: Optional[bool] = None


@dataclass
class TaskCondition:
    """Task requirements."""
    during: Optional[List[TaskType]] = None
    not_during: Optional[List[TaskType]] = None


@dataclass
class PanelConditions:
    """All conditions for panel visibility."""
    workflow_stages: Optional[List[WorkflowStage]] = None  # None = all stages
    lod_min: int = 1
    lod_max: int = 5
    gravity: Optional[GravityCondition] = None
    selection: Optional[SelectionCondition] = None
    state: Optional[StateCondition] = None
    task: Optional[TaskCondition] = None


@dataclass
class PanelDefinition:
    """Definition of a smart panel."""
    id: str
    name: str
    widget_class: type  # The QWidget class to instantiate
    conditions: PanelConditions
    z_index: int = 50
    can_minimize: bool = True


@dataclass
class PanelState:
    """Runtime state of a panel."""
    id: str
    base_opacity: float = 0.0
    target_opacity: float = 0.0
    user_minimized: bool = False
    user_pinned: bool = False  # User pinned to keep visible
    visible: bool = False
    ghost: bool = False  # Show as ghost (panel exists but not in current context)
    transition_start: float = 0.0
    transition_duration: float = 0.3
    last_visible_time: float = 0.0  # For minimum hold time
    last_interaction_time: float = 0.0  # For "cooling off" period
    why_hidden: str = ""  # Reason for being hidden (for tooltip)


# =============================================================================
# Visibility Evaluation
# =============================================================================

def evaluate_panel_visibility(panel: PanelDefinition, context: PanelContext) -> Tuple[float, str]:
    """
    Evaluate panel visibility based on context.

    Philosophy:
    - LOD gates are HARD (can't place fixtures at topology level - that's logical)
    - Gravity affects EMPHASIS, not ACCESS (dimmed but never hidden)
    - At balanced gravity (center), everything is fully visible
    - Selection requirements are SOFT (show what you could do if you selected)

    Returns:
        Tuple of (opacity 0.0-1.0, reason_hidden string)
    """
    opacity = 1.0
    conditions = panel.conditions
    hint = ""  # Soft hint, not a hard gate message

    # Workflow stage check (hard gate - logical constraint)
    if conditions.workflow_stages is not None:
        if context.workflow_stage not in conditions.workflow_stages:
            stages = [s.value for s in conditions.workflow_stages]
            return 0.0, f"Available in: {', '.join(stages)}"

    # LOD check (hard gate - logical constraint)
    # You CAN'T place fixtures at topology level - that makes sense
    current_lod = context.lod.level
    if current_lod < conditions.lod_min or current_lod > conditions.lod_max:
        if conditions.lod_min == conditions.lod_max:
            return 0.0, f"Shift+scroll to LOD {conditions.lod_min}"
        else:
            return 0.0, f"Shift+scroll to LOD {conditions.lod_min}-{conditions.lod_max}"

    # Gravity check (SOFT - affects emphasis, not access)
    # At center (0.33, 0.33, 0.34), everything is at full opacity
    # Moving toward a corner emphasizes relevant panels, dims others
    if conditions.gravity:
        g = conditions.gravity
        cg = context.gravity

        # Calculate how "centered" the gravity is (0 = corner, 1 = center)
        # Center is (0.33, 0.33, 0.34)
        center_distance = (
            abs(cg.design - 0.333) +
            abs(cg.client - 0.333) +
            abs(cg.build - 0.333)
        )
        # Max distance from center is ~0.667 (at a corner)
        centeredness = 1.0 - (center_distance / 0.667)

        # At center, all panels are full opacity
        # Away from center, panels fade based on gravity match
        gravity_match = 1.0

        # Design gravity - how well does current match requirement?
        if g.design_min is not None and cg.design < g.design_min:
            match = cg.design / g.design_min if g.design_min > 0 else 1.0
            gravity_match = min(gravity_match, match)
            if match < 0.7:
                hint = f"Design-focused"

        # Client gravity
        if g.client_min is not None and cg.client < g.client_min:
            match = cg.client / g.client_min if g.client_min > 0 else 1.0
            gravity_match = min(gravity_match, match)
            if match < 0.7:
                hint = f"Client-focused"

        # Build gravity
        if g.build_min is not None and cg.build < g.build_min:
            match = cg.build / g.build_min if g.build_min > 0 else 1.0
            gravity_match = min(gravity_match, match)
            if match < 0.7:
                hint = f"Build-focused"

        # Blend: at center everything is visible, away from center gravity matters more
        # minimum opacity is 0.4 (never fully hidden by gravity)
        blended_opacity = centeredness + (1 - centeredness) * gravity_match
        opacity *= max(0.4, blended_opacity)

    # Selection check (SOFT - show what you could do)
    # Panel is dimmed if nothing selected, but still visible and accessible
    if conditions.selection and conditions.selection.required:
        sel = conditions.selection

        if not context.selection.has_selection:
            # Dimmed but visible - shows what's available
            opacity *= 0.5
            types = [t.value for t in (sel.element_types or [])]
            hint = f"Select: {', '.join(types) if types else 'element'}"
        elif sel.element_types:
            has_matching = any(
                t in sel.element_types
                for t in context.selection.element_types
            )
            if not has_matching:
                opacity *= 0.5
                types = [t.value for t in sel.element_types]
                hint = f"Select: {', '.join(types)}"

        # Count checks are soft too
        if sel.min_count and context.selection.count < sel.min_count:
            opacity *= 0.6
            hint = f"Select {sel.min_count}+"

        if sel.max_count and context.selection.count > sel.max_count:
            opacity *= 0.6
            hint = f"Select ≤{sel.max_count}"

    # State check (soft)
    if conditions.state:
        s = conditions.state
        if s.schema_states and context.schema_state not in s.schema_states:
            opacity *= 0.5
            hint = "Different schema state"

    # Task check (hard gate - don't show fixture palette while dragging fixture)
    if conditions.task:
        t = conditions.task

        if t.during and context.active_task not in t.during:
            return 0.0, "Not during this task"

        if t.not_during and context.active_task in t.not_during:
            return 0.0, "Not available during this task"

    return max(0.3, min(1.0, opacity)), hint


# =============================================================================
# Panel Manager
# =============================================================================

class PanelManager:
    """
    Manages smart panel visibility based on context.

    Panels fade in/out based on workflow, LOD, gravity, selection, etc.

    Safeguards:
    - Hysteresis: Different thresholds for appear/disappear
    - Minimum hold time: Stay visible for at least N seconds
    - Ghost mode: Show hidden panels as faint indicators
    - Pin: User can pin panels to keep them visible
    """

    def __init__(self):
        self._definitions: Dict[str, PanelDefinition] = {}
        self._states: Dict[str, PanelState] = {}
        self._context = PanelContext()
        self._last_update = time.time()

        # Transition settings
        self._fade_in_duration = 0.3   # seconds
        self._fade_out_duration = 0.2  # seconds

        # Safeguard settings
        self._hysteresis_threshold = 0.15  # Must exceed target by this to trigger change
        self._min_hold_time = 1.5  # seconds - minimum time to stay visible
        self._ghost_opacity = 0.15  # Opacity for ghost panels
        self._show_ghosts = True  # Whether to show ghost panels

    def register_panel(self, definition: PanelDefinition):
        """Register a panel definition."""
        self._definitions[definition.id] = definition
        self._states[definition.id] = PanelState(
            id=definition.id,
            base_opacity=0.0,
            target_opacity=0.0
        )

    def unregister_panel(self, panel_id: str):
        """Unregister a panel."""
        self._definitions.pop(panel_id, None)
        self._states.pop(panel_id, None)

    def set_context(self, context: PanelContext):
        """Update the panel context."""
        self._context = context

    def update_gravity(self, design: float, client: float, build: float):
        """Update gravity state."""
        self._context.gravity = GravityState(design, client, build)

    def update_lod(self, level: int, transition: float = 0.0):
        """Update LOD state."""
        self._context.lod = LODState(level=level, transition_progress=transition)

    def update_selection(self, element_ids: List[str], element_types: List[ElementType]):
        """Update selection state."""
        self._context.selection = Selection(element_ids, element_types)

    def update_workflow(self, stage: WorkflowStage):
        """Update workflow stage."""
        self._context.workflow_stage = stage

    def update_task(self, task: TaskType):
        """Update active task."""
        self._context.active_task = task

    def update(self) -> Dict[str, Tuple[float, bool, str]]:
        """
        Update all panel visibility states.

        Returns dict of panel_id -> (opacity, is_ghost, why_hidden)
        """
        now = time.time()
        delta = now - self._last_update
        self._last_update = now

        results = {}

        for panel_id, definition in self._definitions.items():
            state = self._states[panel_id]

            # Calculate target opacity and reason
            target, why_hidden = evaluate_panel_visibility(definition, self._context)
            state.why_hidden = why_hidden

            # Check if panel should be shown as ghost
            is_ghost = target < 0.5 and self._show_ghosts and why_hidden

            # Apply user pinned (keep visible)
            if state.user_pinned:
                target = 1.0
                is_ghost = False

            # Apply user minimized
            if state.user_minimized:
                target = 0.0
                is_ghost = False

            # Hysteresis: require larger change to trigger visibility toggle
            should_update_target = False
            if state.visible and target < 0.5:
                # Currently visible, want to hide - require lower threshold
                if target < (0.5 - self._hysteresis_threshold):
                    should_update_target = True
            elif not state.visible and target > 0.5:
                # Currently hidden, want to show - require higher threshold
                if target > (0.5 + self._hysteresis_threshold):
                    should_update_target = True
            elif abs(target - state.target_opacity) > 0.1:
                should_update_target = True

            # Minimum hold time: don't hide if recently became visible
            if state.visible and target < 0.5:
                time_visible = now - state.last_visible_time
                if time_visible < self._min_hold_time:
                    should_update_target = False
                    target = state.target_opacity  # Keep current target

            # Update target if changed significantly
            if should_update_target and abs(target - state.target_opacity) > 0.01:
                state.target_opacity = target
                state.transition_start = now
                state.transition_duration = (
                    self._fade_in_duration if target > state.base_opacity
                    else self._fade_out_duration
                )

            # Animate opacity
            if state.transition_duration > 0:
                elapsed = now - state.transition_start
                t = min(1.0, elapsed / state.transition_duration)

                # Ease in-out
                if t < 0.5:
                    eased = 2 * t * t
                else:
                    eased = 1 - pow(-2 * t + 2, 2) / 2

                # Interpolate
                diff = state.target_opacity - state.base_opacity
                state.base_opacity += diff * eased

                if t >= 1.0:
                    state.base_opacity = state.target_opacity

            # Track visibility state
            was_visible = state.visible
            state.visible = state.base_opacity > 0.01
            state.ghost = is_ghost

            # Track when panel became visible
            if state.visible and not was_visible:
                state.last_visible_time = now

            # For ghosts, use ghost opacity
            display_opacity = state.base_opacity
            if is_ghost and state.base_opacity < self._ghost_opacity:
                display_opacity = self._ghost_opacity

            results[panel_id] = (display_opacity, is_ghost, why_hidden)

        return results

    def toggle_minimize(self, panel_id: str):
        """Toggle user minimize state for a panel."""
        if panel_id in self._states:
            self._states[panel_id].user_minimized = not self._states[panel_id].user_minimized

    def toggle_pin(self, panel_id: str) -> bool:
        """Toggle user pin state for a panel. Returns new pin state."""
        if panel_id in self._states:
            self._states[panel_id].user_pinned = not self._states[panel_id].user_pinned
            return self._states[panel_id].user_pinned
        return False

    def is_panel_pinned(self, panel_id: str) -> bool:
        """Check if a panel is pinned."""
        state = self._states.get(panel_id)
        return state.user_pinned if state else False

    def get_visible_panels(self) -> List[Tuple[PanelDefinition, float]]:
        """Get list of visible panels with their opacities."""
        visible = []
        for panel_id, state in self._states.items():
            if state.visible:
                definition = self._definitions[panel_id]
                visible.append((definition, state.base_opacity))

        # Sort by z-index
        visible.sort(key=lambda x: x[0].z_index)
        return visible

    def is_panel_visible(self, panel_id: str) -> bool:
        """Check if a panel is currently visible."""
        state = self._states.get(panel_id)
        return state.visible if state else False

    def get_panel_opacity(self, panel_id: str) -> float:
        """Get current opacity of a panel."""
        state = self._states.get(panel_id)
        return state.base_opacity if state else 0.0


# =============================================================================
# Workflow Stage Detection
# =============================================================================

def detect_workflow_stage(lod_level: int) -> WorkflowStage:
    """Detect workflow stage from LOD level."""
    if lod_level <= 1:
        return WorkflowStage.LEGI_QBD
    elif lod_level <= 3:
        return WorkflowStage.LEGI_CAD
    else:
        return WorkflowStage.LEGI_DOC
