"""Generate building schemas from natural language descriptions."""

import json
import re
from pathlib import Path
from typing import Dict, Any, Optional

from .config import LLMConfig
from .provider import Message, LLMProvider


# Default system prompt for building generation
SYSTEM_PROMPT = """You are an architectural design assistant. Generate building layouts as JSON.

Output format (QBD schema):
{
  "success": true,
  "width": <building width in mm>,
  "depth": <building depth in mm>,
  "sqft": <total square feet>,
  "walls_batch": [
    {"index": 0, "start": [x, y, z], "end": [x, y, z], "height": 2700, "category": "exterior|interior"}
  ],
  "doors": [
    {"wall_index": 0, "offset": <mm from wall start>, "width": 914, "height": 2134, "swing": "left_in|right_in"}
  ],
  "windows": [
    {"wall_index": 0, "offset": <mm>, "width": 1200, "height": 1200, "sill_height": 900}
  ],
  "rooms": {
    "room_id": {"name": "Living Room", "room_type": "living", "bounds": {"x": 0, "z": 0, "width": 5000, "height": 4000}, "area": 20.0}
  }
}

Rules:
- All dimensions in millimeters
- Walls are defined by start/end points in 3D (Y is up, Y=0 for floor level)
- Exterior walls have category "exterior"
- Interior walls have category "interior"
- Connect rooms logically with doors
- Place windows on exterior walls only
- Typical wall height is 2700mm (9 feet)
- Standard door width is 914mm (36 inches)
- Standard door height is 2134mm (7 feet)
- Minimum room sizes: bedroom 3000x3000mm, bathroom 1500x2000mm
- Walls must form closed polygons for each room
- 1 sqft = 92903 mm²

Only output valid JSON, no explanation or markdown."""


class SchemaGenerator:
    """Generate building schemas from natural language."""

    def __init__(self, provider: LLMProvider = None, system_prompt: str = None):
        """Initialize schema generator.

        Args:
            provider: LLM provider to use (default: active provider from LLMConfig)
            system_prompt: Custom system prompt (default: built-in prompt)
        """
        self.provider = provider
        self.system_prompt = system_prompt or self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        """Load system prompt from file or use default."""
        prompt_path = Path(__file__).parent / "prompts" / "system.txt"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return SYSTEM_PROMPT

    def _get_provider(self) -> LLMProvider:
        """Get the provider to use."""
        if self.provider:
            return self.provider
        provider = LLMConfig.get_active()
        if not provider:
            raise RuntimeError("No LLM provider available")
        return provider

    def _extract_json(self, content: str) -> str:
        """Extract JSON from response content.

        Handles markdown code blocks and raw JSON.
        """
        content = content.strip()

        # Handle markdown code blocks
        if "```json" in content:
            match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            if match:
                return match.group(1).strip()

        if "```" in content:
            match = re.search(r"```\s*(.*?)\s*```", content, re.DOTALL)
            if match:
                return match.group(1).strip()

        # Try to find JSON object
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return match.group(0)

        return content

    def generate(
        self,
        description: str,
        temperature: float = 0.7,
        max_tokens: int = 8000,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a building schema from a text description.

        Args:
            description: Natural language description of the building
            temperature: Sampling temperature (default: 0.7)
            max_tokens: Maximum tokens to generate (default: 8000)
            **kwargs: Additional provider-specific options

        Returns:
            Dict containing the building schema

        Raises:
            RuntimeError: If no provider is available
            json.JSONDecodeError: If response is not valid JSON
        """
        provider = self._get_provider()

        messages = [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=f"Create a floor plan for: {description}")
        ]

        response = provider.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        # Parse JSON from response
        json_content = self._extract_json(response.content)

        try:
            schema = json.loads(json_content)
        except json.JSONDecodeError as e:
            # Try to provide helpful error message
            raise json.JSONDecodeError(
                f"Failed to parse LLM response as JSON. Raw content:\n{response.content[:500]}...",
                json_content,
                e.pos
            )

        # Add metadata
        schema["_metadata"] = {
            "provider": provider.name,
            "model": response.model,
            "description": description,
            "usage": response.usage
        }

        return schema

    def generate_with_examples(
        self,
        description: str,
        examples: list = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Generate a schema using few-shot examples.

        Args:
            description: Natural language description
            examples: List of (input, output) tuples for few-shot learning
            **kwargs: Additional options passed to generate()

        Returns:
            Dict containing the building schema
        """
        provider = self._get_provider()

        messages = [
            Message(role="system", content=self.system_prompt),
        ]

        # Add examples
        if examples:
            for example_input, example_output in examples:
                messages.append(Message(role="user", content=f"Create a floor plan for: {example_input}"))
                if isinstance(example_output, dict):
                    example_output = json.dumps(example_output, indent=2)
                messages.append(Message(role="assistant", content=example_output))

        # Add the actual request
        messages.append(Message(role="user", content=f"Create a floor plan for: {description}"))

        response = provider.chat(
            messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 8000)
        )

        json_content = self._extract_json(response.content)
        schema = json.loads(json_content)

        schema["_metadata"] = {
            "provider": provider.name,
            "model": response.model,
            "description": description,
            "usage": response.usage
        }

        return schema
