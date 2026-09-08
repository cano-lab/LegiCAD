"""Anthropic Claude API provider."""

import os
from typing import List

import requests

from ..provider import LLMProvider, Message, LLMResponse


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key: str = None, model: str = "claude-sonnet-4-20250514"):
        """Initialize Anthropic provider.

        Args:
            api_key: Anthropic API key (default: from ANTHROPIC_API_KEY env var)
            model: Model to use (default: claude-sonnet-4-20250514)
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model

    @property
    def name(self) -> str:
        return f"Claude ({self.model})"

    def is_available(self) -> bool:
        """Check if API key is configured."""
        return bool(self.api_key)

    def chat(self, messages: List[Message], **kwargs) -> LLMResponse:
        """Send chat request to Anthropic API.

        Args:
            messages: List of Message objects
            **kwargs: Optional parameters:
                - temperature: Sampling temperature (default: 0.7)
                - max_tokens: Maximum tokens to generate (default: 4096)
                - top_p: Top-p sampling (default: None)
                - stop_sequences: Stop sequences (default: None)

        Returns:
            LLMResponse with generated content

        Raises:
            requests.RequestException: If the request fails
            RuntimeError: If API key is not configured
        """
        if not self.api_key:
            raise RuntimeError("Anthropic API key not configured")

        # Extract system message (Anthropic handles it separately)
        system = ""
        chat_messages = []
        for m in messages:
            if m.role == "system":
                system = m.content
            else:
                chat_messages.append({"role": m.role, "content": m.content})

        payload = {
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "messages": chat_messages,
        }

        if system:
            payload["system"] = system

        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]

        if "top_p" in kwargs:
            payload["top_p"] = kwargs["top_p"]

        if "stop_sequences" in kwargs:
            payload["stop_sequences"] = kwargs["stop_sequences"]

        response = requests.post(
            self.API_URL,
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
                "anthropic-version": self.API_VERSION
            },
            json=payload,
            timeout=kwargs.get("timeout", 120)
        )
        response.raise_for_status()
        data = response.json()

        # Extract text from content blocks
        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")

        return LLMResponse(
            content=content,
            model=data.get("model", self.model),
            usage={
                "input": data["usage"]["input_tokens"],
                "output": data["usage"]["output_tokens"]
            } if "usage" in data else None,
            raw=data
        )
