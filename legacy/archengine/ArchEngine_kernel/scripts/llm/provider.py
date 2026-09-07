"""Base provider interface for LLM backends."""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass


@dataclass
class Message:
    """Chat message with role and content."""
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    content: str
    model: str
    usage: Optional[Dict[str, int]] = None  # tokens used
    raw: Optional[Dict[str, Any]] = None    # raw API response


class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    def chat(self, messages: List[Message], **kwargs) -> LLMResponse:
        """Send chat messages and get response.

        Args:
            messages: List of Message objects with role and content
            **kwargs: Provider-specific options (temperature, max_tokens, etc.)

        Returns:
            LLMResponse with content and metadata
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is available/configured.

        Returns:
            True if the provider can be used
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for display.

        Returns:
            Human-readable provider name
        """
        pass
