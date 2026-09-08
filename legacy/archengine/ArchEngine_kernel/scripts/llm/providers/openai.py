"""OpenAI API provider."""

import os
from typing import List

import requests

from ..provider import LLMProvider, Message, LLMResponse


class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""

    API_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: str = None, model: str = "gpt-4o"):
        """Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key (default: from OPENAI_API_KEY env var)
            model: Model to use (default: gpt-4o)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model

    @property
    def name(self) -> str:
        return f"OpenAI ({self.model})"

    def is_available(self) -> bool:
        """Check if API key is configured."""
        return bool(self.api_key)

    def chat(self, messages: List[Message], **kwargs) -> LLMResponse:
        """Send chat request to OpenAI API.

        Args:
            messages: List of Message objects
            **kwargs: Optional parameters:
                - temperature: Sampling temperature (default: 0.7)
                - max_tokens: Maximum tokens to generate (default: 4096)
                - top_p: Top-p sampling (default: None)
                - stop: Stop sequences (default: None)
                - response_format: Response format (default: None)

        Returns:
            LLMResponse with generated content

        Raises:
            requests.RequestException: If the request fails
            RuntimeError: If API key is not configured
        """
        if not self.api_key:
            raise RuntimeError("OpenAI API key not configured")

        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }

        if "top_p" in kwargs:
            payload["top_p"] = kwargs["top_p"]

        if "stop" in kwargs:
            payload["stop"] = kwargs["stop"]

        if "response_format" in kwargs:
            payload["response_format"] = kwargs["response_format"]

        response = requests.post(
            self.API_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=kwargs.get("timeout", 120)
        )
        response.raise_for_status()
        data = response.json()

        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=data.get("model", self.model),
            usage=data.get("usage"),
            raw=data
        )
