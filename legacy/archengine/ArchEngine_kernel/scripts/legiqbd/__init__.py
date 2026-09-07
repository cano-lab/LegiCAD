"""LegiQBD - Conversational Building Design Interface.

The first interface to the Legible Studio system. LegiQBD provides
a natural language conversation for designing homes:

User: "I need a 3 bedroom house with an open kitchen"
LegiQBD: [Applies fragments to QBD, generates follow-up questions]
LegiQBD: "Great! How many bathrooms do you need?"

Architecture:
    User Input
        |
    Intent Classification (LLM)
        |
    Fragment Emission (LLM -> JSON fragments)
        |
    QBD Algebra (validation, derivation, solving)
        |
    Response Generation (LLM -> natural language)
        |
    User Output

API Usage (for Legible Studio integration):
    from legiqbd import LegiQBDAPI, get_api

    api = get_api()  # Singleton instance

    # Get initial state (when no file is open)
    state = api.get_initial_state()
    # Returns: {
    #     "greeting": "What kind of home are you dreaming of?",
    #     "questions": [...],  # First 3 questions
    #     "phase": "greeting",
    #     "has_design": False,
    #     "session_id": "session-xxx"
    # }

    # Process user chat
    result = api.chat("I need a 3 bedroom 2 bath house")
    # Returns: {
    #     "response": "...",
    #     "rooms": [...],
    #     "questions": [...],
    #     "is_solved": True,
    #     "layout": {...}
    # }

Quick Start (standalone):
    from legiqbd import ConversationEngine

    engine = ConversationEngine()
    response = engine.start_conversation()
    print(response.text)

    response = engine.process_input("3 bedroom 2 bath house")
    print(response.text)

CLI Usage:
    python -m legiqbd.cli
"""

from .session import Session, SessionConfig, SessionPhase, Message
from .engine import ConversationEngine, EngineResponse, IntentResult
from .formatter import ResponseFormatter, OutputFormat, format_response, format_design
from .visualizer import ASCIIVisualizer, render_layout, render_rooms, quick_preview
from .api import LegiQBDAPI, get_api, initial_state, chat as api_chat, design_state, solve

__all__ = [
    # Session
    "Session",
    "SessionConfig",
    "SessionPhase",
    "Message",

    # Engine
    "ConversationEngine",
    "EngineResponse",
    "IntentResult",

    # Formatter
    "ResponseFormatter",
    "OutputFormat",
    "format_response",
    "format_design",

    # Visualizer
    "ASCIIVisualizer",
    "render_layout",
    "render_rooms",
    "quick_preview",

    # API (for CAD integration)
    "LegiQBDAPI",
    "get_api",
    "initial_state",
    "api_chat",
    "design_state",
    "solve",
]


def start_session(provider: str = None) -> ConversationEngine:
    """Convenience function to start a new session.

    Args:
        provider: Optional LLM provider name ("lmstudio", "openai", etc)

    Returns:
        ConversationEngine ready to use
    """
    if provider:
        from llm import LLMConfig
        LLMConfig.set_active(provider)

    return ConversationEngine()


def chat(message: str, engine: ConversationEngine = None) -> str:
    """Simple one-shot chat interface.

    Args:
        message: User message
        engine: Optional existing engine (creates new if None)

    Returns:
        Response text
    """
    if engine is None:
        engine = start_session()
        engine.start_conversation()

    response = engine.process_input(message)
    return response.text
