"""LLM abstraction layer for building schema generation and modification.

This module provides a unified interface to multiple LLM backends (LM Studio,
OpenAI, Claude, Gemini) for generating and modifying building schemas from
natural language descriptions.

Two approaches are available:
1. Direct schema generation (legacy) - LLM generates complete JSON schemas
2. Fragment-based (recommended) - LLM emits fragments, QBD Algebra validates and solves

Quick Start (Fragment-based with QBD):
    from llm import LLMConfig, FragmentEmitter
    from qbd import QBDState, solve_state

    LLMConfig.set_active("lmstudio")

    # Emit fragments from natural language
    emitter = FragmentEmitter()
    fragments = emitter.emit_from_description("3 bedroom 2 bath house")

    # Apply to QBD state
    state = QBDState()
    for frag in fragments:
        state.apply_fragment(Fragment.parse(frag))

    # Solve
    result = solve_state(state)

Quick Start (Direct schema - legacy):
    from llm import LLMConfig, generate_building, modify_building

    LLMConfig.set_active("lmstudio")
    schema = generate_building("3 bedroom 2 bath ranch house 1800 sqft")
"""

from .provider import LLMProvider, Message, LLMResponse
from .config import LLMConfig
from .schema_generator import SchemaGenerator
from .schema_modifier import SchemaModifier
from .action_parser import TemplateModifier, ActionParser, ActionApplier
from .fragment_emitter import FragmentEmitter, emit_fragments, apply_fragments_to_state

# Initialize defaults on import
LLMConfig.register_defaults()

__all__ = [
    # Core classes
    "LLMProvider",
    "Message",
    "LLMResponse",
    "LLMConfig",
    "SchemaGenerator",
    "SchemaModifier",
    "TemplateModifier",  # Fast template-based modifier
    "ActionParser",
    "ActionApplier",
    # Fragment-based (QBD integration)
    "FragmentEmitter",
    "emit_fragments",
    "apply_fragments_to_state",
    # Helper functions
    "generate_building",
    "modify_building",
    "get_status",
]


def generate_building(description: str, **kwargs) -> dict:
    """Quick helper to generate a building from text.

    Args:
        description: Natural language description of the building
            e.g. "3 bedroom 2 bath ranch house 1800 sqft"
        **kwargs: Additional options passed to SchemaGenerator.generate()
            - temperature: Sampling temperature (default: 0.7)
            - max_tokens: Maximum tokens (default: 8000)

    Returns:
        Dict containing the building schema with walls, doors, windows, rooms

    Raises:
        RuntimeError: If no LLM provider is available
        json.JSONDecodeError: If LLM response is not valid JSON

    Example:
        >>> schema = generate_building("small 2 bedroom cabin")
        >>> print(f"Walls: {len(schema['walls_batch'])}")
    """
    generator = SchemaGenerator()
    return generator.generate(description, **kwargs)


def modify_building(
    schema: dict,
    request: str,
    pinned_elements: dict = None,
    **kwargs
) -> dict:
    """Quick helper to modify a building schema.

    Args:
        schema: Current building schema
        request: Natural language modification request
            e.g. "Make the kitchen larger"
        pinned_elements: Dict of element types to pinned IDs that should not change
            e.g. {"rooms": ["room_living"], "walls": ["0", "1"]}
        **kwargs: Additional options passed to SchemaModifier.modify()
            - temperature: Sampling temperature (default: 0.5)
            - max_tokens: Maximum tokens (default: 8000)

    Returns:
        Modified building schema

    Raises:
        RuntimeError: If no LLM provider is available
        json.JSONDecodeError: If LLM response is not valid JSON

    Example:
        >>> modified = modify_building(schema, "Add a garage", pinned_elements={"rooms": ["room_living"]})
    """
    modifier = SchemaModifier()
    return modifier.modify(schema, request, pinned_elements, **kwargs)


def get_status() -> dict:
    """Get status of all LLM providers.

    Returns:
        Dict with provider status information including:
        - active: Name of the currently active provider
        - providers: Dict of provider name to status info

    Example:
        >>> status = get_status()
        >>> for name, info in status['providers'].items():
        ...     print(f"{name}: {'available' if info['available'] else 'unavailable'}")
    """
    return LLMConfig.status()
