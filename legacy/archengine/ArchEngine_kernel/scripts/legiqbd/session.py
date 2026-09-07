"""Session management for LegiQBD.

Tracks conversation history, QBD state, and user preferences.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import uuid

# Import QBD
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from qbd import QBDState, StateLifecycle


class SessionPhase(Enum):
    """Session phase - what we're currently doing."""
    GREETING = "greeting"           # Initial hello
    DISCOVERY = "discovery"         # Gathering requirements
    REFINING = "refining"           # Adjusting details
    SOLVING = "solving"             # Running solver
    REVIEWING = "reviewing"         # User reviewing result
    MODIFYING = "modifying"         # User making changes to solved design
    COMPLETE = "complete"           # Design finalized


@dataclass
class Message:
    """A single message in the conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionConfig:
    """Session configuration."""
    auto_solve: bool = True  # Automatically solve when ready
    show_questions: bool = True  # Show generated questions
    verbose: bool = False  # Verbose output
    max_history: int = 50  # Max messages to keep in context


class Session:
    """A LegiQBD design session."""

    def __init__(self, session_id: str = None, config: SessionConfig = None):
        self.id = session_id or f"session-{uuid.uuid4().hex[:8]}"
        self.config = config or SessionConfig()
        self.created_at = datetime.now().isoformat()

        # Core state
        self.qbd_state = QBDState()
        self.phase = SessionPhase.GREETING

        # Conversation history
        self.messages: List[Message] = []

        # Tracking
        self.questions_asked: List[str] = []  # Question IDs we've asked
        self.user_preferences: Dict[str, Any] = {}
        self.solve_count = 0

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def lifecycle(self) -> StateLifecycle:
        """Current QBD state lifecycle."""
        return self.qbd_state.lifecycle

    @property
    def room_count(self) -> int:
        """Number of rooms in design."""
        return len(self.qbd_state.rooms)

    @property
    def is_solvable(self) -> bool:
        """Check if we have enough info to solve."""
        return self.lifecycle in (StateLifecycle.COMPLETE, StateLifecycle.SOLVED)

    @property
    def is_solved(self) -> bool:
        """Check if design is solved."""
        return self.lifecycle == StateLifecycle.SOLVED

    @property
    def solved_layout(self) -> Optional[Dict[str, Any]]:
        """Get solved layout if available."""
        return self.qbd_state.solved_layout

    # =========================================================================
    # Message Management
    # =========================================================================

    def add_message(self, role: str, content: str, **metadata) -> Message:
        """Add a message to history."""
        msg = Message(role=role, content=content, metadata=metadata)
        self.messages.append(msg)

        # Trim if needed
        if len(self.messages) > self.config.max_history:
            self.messages = self.messages[-self.config.max_history:]

        return msg

    def add_user_message(self, content: str) -> Message:
        """Add a user message."""
        return self.add_message("user", content)

    def add_assistant_message(self, content: str, **metadata) -> Message:
        """Add an assistant message."""
        return self.add_message("assistant", content, **metadata)

    def get_history(self, limit: int = None) -> List[Dict[str, str]]:
        """Get message history for LLM context."""
        msgs = self.messages[-limit:] if limit else self.messages
        return [{"role": m.role, "content": m.content} for m in msgs]

    def get_last_user_message(self) -> Optional[str]:
        """Get the last user message."""
        for msg in reversed(self.messages):
            if msg.role == "user":
                return msg.content
        return None

    # =========================================================================
    # Phase Management
    # =========================================================================

    def advance_phase(self):
        """Advance to the next logical phase."""
        if self.phase == SessionPhase.GREETING:
            self.phase = SessionPhase.DISCOVERY

        elif self.phase == SessionPhase.DISCOVERY:
            if self.is_solvable:
                self.phase = SessionPhase.SOLVING
            else:
                self.phase = SessionPhase.REFINING

        elif self.phase == SessionPhase.REFINING:
            if self.is_solvable:
                self.phase = SessionPhase.SOLVING

        elif self.phase == SessionPhase.SOLVING:
            if self.is_solved:
                self.phase = SessionPhase.REVIEWING

        elif self.phase == SessionPhase.REVIEWING:
            # Stay in reviewing until user confirms or modifies
            pass

        elif self.phase == SessionPhase.MODIFYING:
            self.phase = SessionPhase.SOLVING

    def set_phase(self, phase: SessionPhase):
        """Explicitly set phase."""
        self.phase = phase

    # =========================================================================
    # Question Tracking
    # =========================================================================

    def mark_question_asked(self, question_id: str):
        """Mark a question as asked."""
        if question_id not in self.questions_asked:
            self.questions_asked.append(question_id)

    def was_question_asked(self, question_id: str) -> bool:
        """Check if question was already asked."""
        return question_id in self.questions_asked

    # =========================================================================
    # State Summary
    # =========================================================================

    def get_state_summary(self) -> Dict[str, Any]:
        """Get a summary of current state."""
        rooms = self.qbd_state.rooms
        adjacencies = self.qbd_state.adjacencies
        constraints = self.qbd_state.constraints

        return {
            "session_id": self.id,
            "phase": self.phase.value,
            "lifecycle": self.lifecycle.value,
            "rooms": {
                "count": len(rooms),
                "list": [{"name": r["name"], "type": r["type"]} for r in rooms]
            },
            "adjacencies": len(adjacencies),
            "constraints": {k: v for k, v in constraints.items() if v is not None},
            "is_solvable": self.is_solvable,
            "is_solved": self.is_solved,
            "solve_count": self.solve_count,
            "message_count": len(self.messages),
        }

    def get_design_summary(self) -> str:
        """Get a human-readable design summary."""
        rooms = self.qbd_state.rooms
        if not rooms:
            return "No rooms defined yet."

        lines = []
        lines.append(f"**Current Design** ({len(rooms)} rooms)")
        lines.append("")

        # Group by type
        by_type = {}
        for room in rooms:
            rtype = room.get("type", "other")
            by_type.setdefault(rtype, []).append(room)

        for rtype, rlist in by_type.items():
            names = [r["name"] for r in rlist]
            lines.append(f"- {rtype}: {', '.join(names)}")

        # Adjacencies
        adj = self.qbd_state.adjacencies
        if adj:
            lines.append("")
            lines.append(f"**Connections** ({len(adj)})")
            for a in adj[:5]:
                conn = a.get("connection_type", "door")
                lines.append(f"- {a['room_a'][-8:]} ↔ {a['room_b'][-8:]} ({conn})")

        # Constraints
        constraints = self.qbd_state.constraints
        active = {k: v for k, v in constraints.items() if v is not None}
        if active:
            lines.append("")
            lines.append("**Constraints**")
            for k, v in active.items():
                lines.append(f"- {k}: {v}")

        return "\n".join(lines)

    # =========================================================================
    # Serialization
    # =========================================================================

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session to dictionary."""
        return {
            "id": self.id,
            "created_at": self.created_at,
            "phase": self.phase.value,
            "config": {
                "auto_solve": self.config.auto_solve,
                "show_questions": self.config.show_questions,
                "verbose": self.config.verbose,
            },
            "qbd_state": self.qbd_state.to_dict(),
            "messages": [
                {"role": m.role, "content": m.content, "timestamp": m.timestamp}
                for m in self.messages
            ],
            "questions_asked": self.questions_asked,
            "user_preferences": self.user_preferences,
            "solve_count": self.solve_count,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        """Deserialize from dictionary."""
        config = SessionConfig(**data.get("config", {}))
        session = cls(session_id=data.get("id"), config=config)
        session.created_at = data.get("created_at", session.created_at)
        session.phase = SessionPhase(data.get("phase", "greeting"))
        session.qbd_state = QBDState.from_dict(data.get("qbd_state", {}))
        session.questions_asked = data.get("questions_asked", [])
        session.user_preferences = data.get("user_preferences", {})
        session.solve_count = data.get("solve_count", 0)

        # Restore messages
        for m in data.get("messages", []):
            session.messages.append(Message(
                role=m["role"],
                content=m["content"],
                timestamp=m.get("timestamp", "")
            ))

        return session
