"""LegiQBD API for Legible Studio integration.

Provides a clean interface for the CAD frontend to consume.
When no file is open, the chat panel appears with initial questions.

Usage:
    from legiqbd.api import LegiQBDAPI

    api = LegiQBDAPI()

    # Get initial state (for empty/new file)
    state = api.get_initial_state()
    # Returns: {
    #     "greeting": "What kind of home are you dreaming of?",
    #     "questions": [...],  # First 3 questions
    #     "phase": "greeting",
    #     "has_design": False
    # }

    # Process user input
    result = api.chat("I need a 3 bedroom 2 bath house")
    # Returns: {
    #     "response": "Great! Let me set that up...",
    #     "rooms": [...],
    #     "questions": [...],  # Follow-up questions
    #     "phase": "discovery",
    #     "is_solvable": True,
    #     "layout": {...}  # If solved
    # }
"""

import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict

# Setup path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from qbd import QBDState, generate_questions, solve_state
from llm import LLMConfig

from .session import Session, SessionPhase, SessionConfig
from .engine import ConversationEngine
from .formatter import ResponseFormatter


# =============================================================================
# INITIAL PROMPTS
# =============================================================================

GREETING_PROMPTS = [
    "What kind of home are you dreaming of?",
    "Tell me about your ideal home.",
    "Let's design your perfect space. What do you have in mind?",
]

STARTER_QUESTIONS = [
    {
        "id": "q_start_bedrooms",
        "text": "How many bedrooms do you need?",
        "options": ["1", "2", "3", "4", "5+"],
        "category": "program"
    },
    {
        "id": "q_start_style",
        "text": "What style appeals to you?",
        "options": ["Modern", "Traditional", "Farmhouse", "Ranch", "Not sure"],
        "category": "character"
    },
    {
        "id": "q_start_size",
        "text": "Roughly how big?",
        "options": ["Small (<1500 sqft)", "Medium (1500-2500)", "Large (2500+)", "Not sure"],
        "category": "constraints"
    },
]


# =============================================================================
# API RESPONSE TYPES
# =============================================================================

@dataclass
class InitialState:
    """State returned when no file is open."""
    greeting: str
    questions: List[Dict]
    phase: str
    has_design: bool
    session_id: str


@dataclass
class ChatResponse:
    """Response from processing user input."""
    response: str
    rooms: List[Dict]
    room_count: int
    questions: List[Dict]
    phase: str
    is_solvable: bool
    is_solved: bool
    layout: Optional[Dict]
    errors: List[str]
    session_id: str


@dataclass
class DesignState:
    """Current state of the design."""
    rooms: List[Dict]
    room_count: int
    adjacencies: int
    constraints: Dict
    phase: str
    is_solvable: bool
    is_solved: bool
    layout: Optional[Dict]
    score: Optional[float]
    session_id: str


# =============================================================================
# LEGIQBD API
# =============================================================================

class LegiQBDAPI:
    """
    API for LegiQBD integration with Legible Studio.

    Manages sessions and provides a clean interface for the CAD frontend.
    """

    def __init__(self):
        """Initialize API with session management."""
        self._sessions: Dict[str, ConversationEngine] = {}
        self._active_session: Optional[str] = None

        # Check LLM availability
        self._llm_available = self._check_llm()

    def _check_llm(self) -> bool:
        """Check if LLM is available."""
        try:
            status = LLMConfig.status()
            return status.get("active") is not None
        except:
            return False

    # =========================================================================
    # SESSION MANAGEMENT
    # =========================================================================

    def new_session(self) -> str:
        """Create a new session and return its ID."""
        engine = ConversationEngine()
        session_id = engine.session.id
        self._sessions[session_id] = engine
        self._active_session = session_id
        return session_id

    def get_session(self, session_id: str = None) -> Optional[ConversationEngine]:
        """Get a session by ID, or the active session."""
        if session_id:
            return self._sessions.get(session_id)
        if self._active_session:
            return self._sessions.get(self._active_session)
        return None

    def set_active_session(self, session_id: str):
        """Set the active session."""
        if session_id in self._sessions:
            self._active_session = session_id

    # =========================================================================
    # INITIAL STATE (No file open)
    # =========================================================================

    def get_initial_state(self) -> Dict[str, Any]:
        """
        Get initial state for when no file is open.

        This is what the chat panel shows on startup.
        Returns greeting and starter questions.
        """
        # Create new session
        session_id = self.new_session()
        engine = self._sessions[session_id]

        # Get greeting from LLM if available, otherwise use default
        if self._llm_available:
            try:
                response = engine.start_conversation()
                greeting = response.text
            except:
                greeting = GREETING_PROMPTS[0]
        else:
            greeting = GREETING_PROMPTS[0]

        return asdict(InitialState(
            greeting=greeting,
            questions=STARTER_QUESTIONS,
            phase="greeting",
            has_design=False,
            session_id=session_id
        ))

    def get_starter_questions(self) -> List[Dict]:
        """Get the starter questions for quick-start UI."""
        return STARTER_QUESTIONS

    # =========================================================================
    # CHAT INTERFACE
    # =========================================================================

    def chat(self, message: str, session_id: str = None) -> Dict[str, Any]:
        """
        Process a chat message and return response.

        Args:
            message: User's message
            session_id: Optional session ID (uses active if not provided)

        Returns:
            ChatResponse as dict
        """
        engine = self.get_session(session_id)

        if not engine:
            # Create new session if none exists
            session_id = self.new_session()
            engine = self._sessions[session_id]
            engine.start_conversation()

        # Process input
        response = engine.process_input(message)

        # Get current rooms
        rooms = [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "type": r.get("type"),
                "area_min": r.get("area_min")
            }
            for r in engine.session.qbd_state.rooms
        ]

        # Get follow-up questions
        questions = []
        if not response.is_solved:
            try:
                questions = generate_questions(engine.session.qbd_state, max_questions=3)
            except:
                pass

        # Get layout if solved
        layout = None
        if response.is_solved:
            layout = engine.session.solved_layout

        return asdict(ChatResponse(
            response=response.text,
            rooms=rooms,
            room_count=len(rooms),
            questions=questions,
            phase=response.phase,
            is_solvable=response.is_solvable,
            is_solved=response.is_solved,
            layout=layout,
            errors=response.errors,
            session_id=engine.session.id
        ))

    def answer_question(self, question_id: str, answer: str,
                        session_id: str = None) -> Dict[str, Any]:
        """
        Answer a specific question.

        Args:
            question_id: ID of the question being answered
            answer: User's answer
            session_id: Optional session ID

        Returns:
            ChatResponse as dict
        """
        # Convert to natural language and process
        message = f"{answer}"
        return self.chat(message, session_id)

    # =========================================================================
    # DESIGN STATE
    # =========================================================================

    def get_design_state(self, session_id: str = None) -> Dict[str, Any]:
        """
        Get current state of the design.

        Args:
            session_id: Optional session ID

        Returns:
            DesignState as dict
        """
        engine = self.get_session(session_id)

        if not engine:
            return asdict(DesignState(
                rooms=[],
                room_count=0,
                adjacencies=0,
                constraints={},
                phase="greeting",
                is_solvable=False,
                is_solved=False,
                layout=None,
                score=None,
                session_id=""
            ))

        state = engine.session.qbd_state
        session = engine.session

        rooms = [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "type": r.get("type"),
                "area_min": r.get("area_min")
            }
            for r in state.rooms
        ]

        layout = session.solved_layout
        score = None
        if layout:
            score = layout.get("score")

        return asdict(DesignState(
            rooms=rooms,
            room_count=len(rooms),
            adjacencies=len(state.adjacencies),
            constraints={k: v for k, v in state.constraints.items() if v is not None},
            phase=session.phase.value,
            is_solvable=session.is_solvable,
            is_solved=session.is_solved,
            layout=layout,
            score=score,
            session_id=session.id
        ))

    # =========================================================================
    # SOLVER
    # =========================================================================

    def solve(self, session_id: str = None) -> Dict[str, Any]:
        """
        Manually trigger the solver.

        Returns:
            Dict with success status and layout or error
        """
        engine = self.get_session(session_id)

        if not engine:
            return {"success": False, "error": "No active session"}

        if not engine.session.is_solvable:
            return {"success": False, "error": "Not enough information to solve"}

        success, result = engine.solve()

        if success:
            return {
                "success": True,
                "layout": result.get("layout"),
                "score": result.get("score"),
                "metrics": result.get("metrics")
            }
        else:
            return {
                "success": False,
                "error": result.get("error"),
                "message": result.get("message")
            }

    # =========================================================================
    # SERIALIZATION
    # =========================================================================

    def save_session(self, session_id: str = None) -> str:
        """Save session to JSON string."""
        engine = self.get_session(session_id)
        if engine:
            return engine.session.to_json()
        return "{}"

    def load_session(self, json_str: str) -> str:
        """Load session from JSON string. Returns session ID."""
        data = json.loads(json_str)
        session = Session.from_dict(data)
        engine = ConversationEngine(session=session)

        self._sessions[session.id] = engine
        self._active_session = session.id

        return session.id

    # =========================================================================
    # STATUS
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        """Get API status."""
        return {
            "llm_available": self._llm_available,
            "active_session": self._active_session,
            "session_count": len(self._sessions),
            "llm_provider": LLMConfig.status().get("active") if self._llm_available else None
        }


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_api_instance: Optional[LegiQBDAPI] = None

def get_api() -> LegiQBDAPI:
    """Get the singleton API instance."""
    global _api_instance
    if _api_instance is None:
        _api_instance = LegiQBDAPI()
    return _api_instance


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def initial_state() -> Dict[str, Any]:
    """Get initial state for new/empty file."""
    return get_api().get_initial_state()

def chat(message: str) -> Dict[str, Any]:
    """Process a chat message."""
    return get_api().chat(message)

def design_state() -> Dict[str, Any]:
    """Get current design state."""
    return get_api().get_design_state()

def solve() -> Dict[str, Any]:
    """Solve the current design."""
    return get_api().solve()
